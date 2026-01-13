# core_logic.py
# -*- coding: utf-8 -*-
from datetime import datetime
import logging
import os
import json
import config
import re
import platform
import glob
import zipfile
import shutil

# Import the appropriate guess_save_path function based on platform
if platform.system() == "Linux":
    from save_path_finder_linux import guess_save_path
    logging.info("core_logic: Using Linux-specific implementation of guess_save_path")
else:
    from save_path_finder import guess_save_path
    logging.info(f"core_logic: Using default implementation of guess_save_path for {platform.system()}")

try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Library 'thefuzz' found and loaded.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    # Log the warning only once here at startup if missing
    logging.warning("Library 'thefuzz' not found. Fuzzy matching will be disabled.")
    logging.warning("Install it with: pip install thefuzz[speedup]")

# --- Define profiles file path (dynamic using settings_manager) ---
PROFILES_FILENAME = "game_save_profiles.json"
try:
    import settings_manager as _sm
    _ACTIVE_CONFIG_DIR = _sm.get_active_config_dir()
except Exception:
    _ACTIVE_CONFIG_DIR = config.get_app_data_folder()
    logging.warning("Failed to import settings_manager for active config dir; falling back to AppData.")

if _ACTIVE_CONFIG_DIR:
    PROFILES_FILE_PATH = os.path.join(_ACTIVE_CONFIG_DIR, PROFILES_FILENAME)
else:
    logging.error("Unable to determine configuration directory, using relative path for game_save_profiles.json.")
    PROFILES_FILE_PATH = os.path.abspath(PROFILES_FILENAME)
logging.info(f"Profile file path in use: {PROFILES_FILE_PATH}")
# --- End definition ---

# --- Helper: Mirror JSONs to backup root with rotation ---
def _get_backup_root_from_settings() -> str:
    """Best-effort retrieval of backup root directory from settings, with config fallback."""
    try:
        import settings_manager
        settings, _ = settings_manager.load_settings()
        backup_root = settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
    except Exception:
        backup_root = getattr(config, "BACKUP_BASE_DIR", None)
    return backup_root

def _mirror_json_to_backup_root(filename: str, json_obj: dict, rotation: int = 10) -> None:
    """Write a mirror copy of json_obj into backup_root/.savestate/filename and keep N rotated snapshots.

    If rotation <= 0, only the primary mirror file is written (no timestamped snapshots).
    """
    backup_root = _get_backup_root_from_settings()
    if not backup_root:
        return
    mirror_dir = os.path.join(backup_root, ".savestate")
    os.makedirs(mirror_dir, exist_ok=True)

    # Write primary mirror
    mirror_path = os.path.join(mirror_dir, filename)
    with open(mirror_path, "w", encoding="utf-8") as mf:
        json.dump(json_obj, mf, indent=4, ensure_ascii=False)
    logging.info(f"Mirror saved: {mirror_path}")

    # Write timestamped snapshot only if rotation is enabled (> 0)
    if rotation and rotation > 0:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = os.path.join(mirror_dir, f"{os.path.splitext(filename)[0]}-{ts}.json")
        try:
            with open(snapshot_path, "w", encoding="utf-8") as sf:
                json.dump(json_obj, sf, indent=2, ensure_ascii=False)
        except Exception:
            logging.warning(f"Failed to write snapshot mirror for {filename}")

        # Rotate old snapshots
        try:
            candidates = [f for f in os.listdir(mirror_dir) if f.startswith(os.path.splitext(filename)[0] + "-") and f.endswith(".json")]
            candidates.sort(reverse=True)
            for old in candidates[rotation:]:
                try:
                    os.remove(os.path.join(mirror_dir, old))
                except Exception:
                    pass
        except Exception:
            pass

# <<< Function to sanitize folder names >>>
def sanitize_foldername(name):
    """Removes or replaces invalid characters for file/folder names,
       preserving internal dots and removing external ones."""
    if not isinstance(name, str):
        return "_invalid_profile_name_" # Handle non-string input

    # 1. Remove control characters (newlines, tabs, carriage returns, etc.)
    #    These are not valid in file/folder names on any OS
    safe_name = re.sub(r'[\x00-\x1f\x7f]', ' ', name)  # Replace with space to preserve word separation

    # 2. Remove universally invalid characters in file/folder names
    #    ( <>:"/\|?* ) Keep letters, numbers, spaces, _, -, .
    safe_name = re.sub(r'[<>:"/\\|?*]', '', safe_name)

    # 3. Collapse multiple spaces into single space (after replacing control chars)
    safe_name = re.sub(r'\s+', ' ', safe_name)

    # 4. Remove initial/final whitespace
    safe_name = safe_name.strip()

    # 5. Remove initial/final DOTS (AFTER removing spaces)
    #    This loop removes multiple dots if present (e.g., "..name..")
    if safe_name: # Avoid errors if the string has become empty
        safe_name = safe_name.strip('.')

    # 6. Remove any whitespace that might have been exposed
    #    after removing dots (e.g., ". name .")
    safe_name = safe_name.strip()

    # 7. Handle case where name becomes empty or just spaces after cleaning
    if not safe_name or safe_name.isspace():
        safe_name = "_invalid_profile_name_" # Fallback name

    return safe_name


def _is_safe_zip_path(member_path: str, target_dir: str) -> bool:
    """
    Check if a ZIP member path is safe to extract (prevents Zip Slip vulnerability).
    
    A path is considered safe if, when joined with the target directory,
    the resulting absolute path is still within the target directory.
    
    Args:
        member_path: The path of the file inside the ZIP archive
        target_dir: The target extraction directory
        
    Returns:
        True if the path is safe, False if it could escape the target directory
    """
    # Normalize the target directory to absolute path
    abs_target = os.path.abspath(target_dir)
    
    # Join and normalize the full extraction path
    # Replace forward slashes with OS separator for cross-platform compatibility
    normalized_member = member_path.replace('/', os.sep)
    full_path = os.path.normpath(os.path.join(abs_target, normalized_member))
    
    # Check if the resulting path starts with the target directory
    # We add os.sep to prevent partial matches (e.g., /home/user vs /home/user2)
    return full_path.startswith(abs_target + os.sep) or full_path == abs_target


def _safe_extract_member(zipf: zipfile.ZipFile, member: str, target_dir: str) -> bool:
    """
    Safely extract a single ZIP member with Zip Slip protection.
    
    Args:
        zipf: Open ZipFile object
        member: Member path inside the ZIP
        target_dir: Target extraction directory
        
    Returns:
        True if extraction succeeded, False if path was unsafe or extraction failed
    """
    if not _is_safe_zip_path(member, target_dir):
        logging.error(f"SECURITY: Blocked unsafe ZIP path (potential path traversal): '{member}'")
        return False
    
    try:
        zipf.extract(member, target_dir)
        return True
    except Exception as e:
        logging.error(f"Error extracting '{member}': {e}")
        return False


def _safe_extractall(zipf: zipfile.ZipFile, target_dir: str) -> tuple:
    """
    Safely extract all members from a ZIP file with Zip Slip protection.
    
    Args:
        zipf: Open ZipFile object
        target_dir: Target extraction directory
        
    Returns:
        Tuple (success: bool, blocked_paths: list, error_messages: list)
    """
    blocked_paths = []
    error_messages = []
    all_success = True
    
    for member in zipf.namelist():
        if not _is_safe_zip_path(member, target_dir):
            blocked_paths.append(member)
            logging.error(f"SECURITY: Blocked unsafe ZIP path: '{member}'")
            all_success = False
            continue
        
        try:
            zipf.extract(member, target_dir)
        except Exception as e:
            error_messages.append(f"Error extracting '{member}': {e}")
            logging.error(f"Error extracting '{member}': {e}")
            all_success = False
    
    if blocked_paths:
        logging.warning(f"Blocked {len(blocked_paths)} potentially malicious paths in ZIP archive")
    
    return all_success, blocked_paths, error_messages


# --- Profile Management ---

# --- Profile Group Helper Functions ---
def is_group_profile(profile_data: dict) -> bool:
    """
    Check if a profile is a group (Matrioska profile) rather than a regular profile.
    
    A group profile has type='group' and contains references to other profiles
    instead of direct save paths.
    
    Args:
        profile_data: The profile data dictionary
        
    Returns:
        True if this is a group profile, False otherwise
    """
    if not isinstance(profile_data, dict):
        return False
    return profile_data.get('type') == 'group'


def get_group_member_profiles(group_name: str, profiles_dict: dict) -> list:
    """
    Get the list of profile names that belong to a group.
    
    Args:
        group_name: Name of the group profile
        profiles_dict: Dictionary of all profiles
        
    Returns:
        List of profile names contained in the group (in order)
    """
    if group_name not in profiles_dict:
        return []
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        return []
    
    return group_data.get('profiles', [])


def create_group_profile(group_name: str, profile_names: list, profiles_dict: dict, 
                         icon_path: str = None, settings: dict = None) -> tuple:
    """
    Create a new group profile containing multiple existing profiles.
    
    The group will appear as a single entry in the profile list, but when
    backup/restore is triggered, it will process all contained profiles.
    
    Args:
        group_name: Name for the new group
        profile_names: List of existing profile names to include in the group
        profiles_dict: Dictionary of all profiles (will be modified in place)
        icon_path: Optional path to a custom icon for the group
        settings: Optional group settings dict with keys:
            - enabled: bool - Master toggle for group settings override
            - max_backups: int or None - Override max backups for all members
            - compression_mode: str or None - Override compression mode
            - max_source_size_mb: int or None - Override max source size
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    # Validate group name
    if not group_name or not isinstance(group_name, str):
        return False, "Group name cannot be empty"
    
    if group_name in profiles_dict:
        return False, f"A profile with name '{group_name}' already exists"
    
    # Validate profile names
    if not profile_names or not isinstance(profile_names, list):
        return False, "At least one profile must be selected for the group"
    
    valid_profiles = []
    for name in profile_names:
        if name not in profiles_dict:
            logging.warning(f"Profile '{name}' not found, skipping for group")
            continue
        
        profile_data = profiles_dict[name]
        
        # Don't allow adding groups to groups (no nested groups)
        if is_group_profile(profile_data):
            return False, f"Cannot add group '{name}' to another group (nested groups not supported)"
        
        # Check if profile is already in another group
        if profile_data.get('member_of_group'):
            existing_group = profile_data.get('member_of_group')
            return False, f"Profile '{name}' is already a member of group '{existing_group}'"
        
        valid_profiles.append(name)
    
    if not valid_profiles:
        return False, "No valid profiles found to add to the group"
    
    if len(valid_profiles) < 1:
        return False, "At least one profile is required to create a group"
    
    # Create the group profile
    group_data = {
        'type': 'group',
        'profiles': valid_profiles,
    }
    if icon_path:
        group_data['icon'] = icon_path
    
    # Add group settings if provided
    if settings and isinstance(settings, dict):
        group_data['settings'] = settings.copy()
        logging.debug(f"Group '{group_name}' created with settings: {settings}")
    
    # Mark member profiles as belonging to this group
    for profile_name in valid_profiles:
        profiles_dict[profile_name]['member_of_group'] = group_name
    
    # Add the group to profiles
    profiles_dict[group_name] = group_data
    
    logging.info(f"Created group '{group_name}' with {len(valid_profiles)} profile(s): {valid_profiles}")
    return True, None


def update_group_profile(group_name: str, new_profile_names: list, profiles_dict: dict,
                         new_group_name: str = None, icon_path: str = None,
                         new_settings: dict = None) -> tuple:
    """
    Update an existing group profile with new settings.
    
    Args:
        group_name: Current name of the group
        new_profile_names: New list of profile names for the group
        profiles_dict: Dictionary of all profiles (will be modified in place)
        new_group_name: Optional new name for the group (for renaming)
        icon_path: Optional new icon path for the group
        new_settings: Optional group settings dict to update/replace:
            - enabled: bool - Master toggle for group settings override
            - max_backups: int or None - Override max backups for all members
            - compression_mode: str or None - Override compression mode
            - max_source_size_mb: int or None - Override max source size
            Pass None to keep existing settings, pass empty dict {} to clear settings
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    if group_name not in profiles_dict:
        return False, f"Group '{group_name}' not found"
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        return False, f"'{group_name}' is not a group profile"
    
    # Validate new profile names
    if not new_profile_names or not isinstance(new_profile_names, list):
        return False, "At least one profile must be selected for the group"
    
    # Get current member list
    current_members = group_data.get('profiles', [])
    
    # Preserve existing settings if not being updated
    existing_settings = group_data.get('settings', {})
    
    # Validate new profiles
    valid_profiles = []
    for name in new_profile_names:
        if name not in profiles_dict:
            logging.warning(f"Profile '{name}' not found, skipping for group update")
            continue
        
        profile_data = profiles_dict[name]
        
        # Don't allow adding groups to groups
        if is_group_profile(profile_data):
            return False, f"Cannot add group '{name}' to another group"
        
        # Check if profile is already in another group (but allow if it's in this group)
        member_of = profile_data.get('member_of_group')
        if member_of and member_of != group_name:
            return False, f"Profile '{name}' is already a member of group '{member_of}'"
        
        valid_profiles.append(name)
    
    if not valid_profiles:
        return False, "No valid profiles found for the group"
    
    # Handle renaming
    final_group_name = new_group_name if new_group_name and new_group_name != group_name else group_name
    
    if new_group_name and new_group_name != group_name:
        if new_group_name in profiles_dict:
            return False, f"A profile with name '{new_group_name}' already exists"
    
    # Remove member_of_group from profiles no longer in the group
    for old_member in current_members:
        if old_member in profiles_dict and old_member not in valid_profiles:
            if profiles_dict[old_member].get('member_of_group') == group_name:
                del profiles_dict[old_member]['member_of_group']
                logging.debug(f"Removed '{old_member}' from group '{group_name}'")
    
    # Update member_of_group for all profiles in the group
    for profile_name in valid_profiles:
        profiles_dict[profile_name]['member_of_group'] = final_group_name
    
    # Determine final settings
    final_settings = existing_settings
    if new_settings is not None:
        if isinstance(new_settings, dict):
            if new_settings:  # Non-empty dict: update settings
                final_settings = new_settings.copy()
            else:  # Empty dict: clear settings
                final_settings = {}
    
    # Update or rename the group
    if new_group_name and new_group_name != group_name:
        # Rename: delete old, create new
        del profiles_dict[group_name]
        profiles_dict[final_group_name] = {
            'type': 'group',
            'profiles': valid_profiles,
        }
        if icon_path:
            profiles_dict[final_group_name]['icon'] = icon_path
        if final_settings:
            profiles_dict[final_group_name]['settings'] = final_settings
        logging.info(f"Renamed group '{group_name}' to '{final_group_name}'")
    else:
        # Just update
        group_data['profiles'] = valid_profiles
        if icon_path is not None:  # Allow clearing icon with empty string
            if icon_path:
                group_data['icon'] = icon_path
            elif 'icon' in group_data:
                del group_data['icon']
        # Update settings
        if final_settings:
            group_data['settings'] = final_settings
        elif 'settings' in group_data and not final_settings:
            del group_data['settings']  # Clear settings if empty
    
    logging.info(f"Updated group '{final_group_name}' with {len(valid_profiles)} profile(s)")
    if final_settings:
        logging.debug(f"Group '{final_group_name}' settings: {final_settings}")
    return True, None


def ungroup_profile(group_name: str, profiles_dict: dict) -> tuple:
    """
    Dissolve a group profile, making its member profiles visible again.
    
    This only removes the group itself; the member profiles remain unchanged
    except for removing their 'member_of_group' reference.
    
    Args:
        group_name: Name of the group to dissolve
        profiles_dict: Dictionary of all profiles (will be modified in place)
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    if group_name not in profiles_dict:
        return False, f"Group '{group_name}' not found"
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        return False, f"'{group_name}' is not a group profile"
    
    # Get member profiles
    member_profiles = group_data.get('profiles', [])
    
    # Remove member_of_group from all member profiles
    for profile_name in member_profiles:
        if profile_name in profiles_dict:
            profile_data = profiles_dict[profile_name]
            if profile_data.get('member_of_group') == group_name:
                del profile_data['member_of_group']
                logging.debug(f"Removed group membership from '{profile_name}'")
    
    # Delete the group itself
    del profiles_dict[group_name]
    
    logging.info(f"Ungrouped '{group_name}', {len(member_profiles)} profile(s) are now visible")
    return True, None


def get_visible_profiles(profiles_dict: dict) -> dict:
    """
    Get profiles that should be visible in the profile list.
    
    This filters out profiles that are members of a group (they are hidden
    because the group represents them). Groups themselves are visible.
    
    Args:
        profiles_dict: Dictionary of all profiles
        
    Returns:
        Dictionary of profiles that should be displayed in the list
    """
    visible = {}
    for name, data in profiles_dict.items():
        if not isinstance(data, dict):
            continue
        
        # Show groups
        if is_group_profile(data):
            visible[name] = data
            continue
        
        # Show profiles that are NOT members of any group
        if not data.get('member_of_group'):
            visible[name] = data
    
    return visible


def get_effective_profile_settings(profile_name: str, profile_data: dict, 
                                    profiles_dict: dict, global_settings: dict) -> dict:
    """
    Get effective backup settings for a profile considering group membership.
    
    Priority: Group override > Profile override > Global settings
    
    This function resolves which settings should be used when backing up a profile.
    If the profile is in a group that has settings override enabled, those settings
    take precedence over both the profile's own overrides and global settings.
    
    Args:
        profile_name: Name of the profile
        profile_data: The profile data dictionary
        profiles_dict: Dictionary of all profiles (to look up group data)
        global_settings: The global application settings dictionary
        
    Returns:
        Dictionary with effective settings:
        - max_backups: int
        - max_source_size_mb: int
        - compression_mode: str
    """
    # Start with global settings as defaults
    effective = {
        'max_backups': global_settings.get('max_backups', 5),
        'max_source_size_mb': global_settings.get('max_source_size_mb', 500),
        'compression_mode': global_settings.get('compression_mode', 'standard'),
    }
    
    # Apply profile-level overrides (if any)
    profile_overrides = profile_data.get('overrides', {})
    if profile_overrides:
        for key in effective:
            if key in profile_overrides and profile_overrides[key] is not None:
                effective[key] = profile_overrides[key]
                logging.debug(f"Profile '{profile_name}' override: {key}={profile_overrides[key]}")
    
    # Apply group-level overrides (highest priority)
    group_name = profile_data.get('member_of_group')
    if group_name and group_name in profiles_dict:
        group_data = profiles_dict[group_name]
        if is_group_profile(group_data):
            group_settings = group_data.get('settings', {})
            if group_settings.get('enabled'):
                for key in effective:
                    if key in group_settings and group_settings[key] is not None:
                        effective[key] = group_settings[key]
                        logging.debug(f"Profile '{profile_name}' using group '{group_name}' override: {key}={group_settings[key]}")
    
    return effective


def get_group_settings(group_name: str, profiles_dict: dict) -> dict:
    """
    Get the settings for a group profile.
    
    Args:
        group_name: Name of the group
        profiles_dict: Dictionary of all profiles
        
    Returns:
        Dictionary with group settings, or empty dict if no settings
    """
    if group_name not in profiles_dict:
        return {}
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        return {}
    
    return group_data.get('settings', {}).copy()


def remove_profile_from_group(profile_name: str, profiles_dict: dict) -> tuple:
    """
    Remove a profile from its group (if any).
    
    If the group becomes empty after removal, the group is also deleted.
    
    Args:
        profile_name: Name of the profile to remove from group
        profiles_dict: Dictionary of all profiles (will be modified in place)
        
    Returns:
        Tuple (success: bool, group_deleted: bool, error_message: str or None)
    """
    if profile_name not in profiles_dict:
        return False, False, f"Profile '{profile_name}' not found"
    
    profile_data = profiles_dict[profile_name]
    group_name = profile_data.get('member_of_group')
    
    if not group_name:
        return True, False, None  # Not in a group, nothing to do
    
    if group_name not in profiles_dict:
        # Group doesn't exist, just clean up the reference
        del profile_data['member_of_group']
        return True, False, None
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        # Corrupted data, clean up
        del profile_data['member_of_group']
        return True, False, None
    
    # Remove from group's profile list
    group_profiles = group_data.get('profiles', [])
    if profile_name in group_profiles:
        group_profiles.remove(profile_name)
    
    # Remove member_of_group from the profile
    del profile_data['member_of_group']
    
    # Check if group is now empty
    group_deleted = False
    if not group_profiles:
        del profiles_dict[group_name]
        group_deleted = True
        logging.info(f"Group '{group_name}' was empty after removing '{profile_name}', deleted group")
    else:
        logging.debug(f"Removed '{profile_name}' from group '{group_name}'")
    
    return True, group_deleted, None


def handle_profile_rename_in_group(old_name: str, new_name: str, profiles_dict: dict) -> bool:
    """
    Update group references when a profile is renamed.
    
    Args:
        old_name: The old profile name
        new_name: The new profile name
        profiles_dict: Dictionary of all profiles
        
    Returns:
        True if update was successful, False otherwise
    """
    if old_name not in profiles_dict:
        return False
    
    profile_data = profiles_dict[old_name]
    group_name = profile_data.get('member_of_group')
    
    if not group_name or group_name not in profiles_dict:
        return True  # Not in a group, nothing to update
    
    group_data = profiles_dict[group_name]
    if not is_group_profile(group_data):
        return True
    
    # Update the profile list in the group
    group_profiles = group_data.get('profiles', [])
    if old_name in group_profiles:
        idx = group_profiles.index(old_name)
        group_profiles[idx] = new_name
        logging.debug(f"Updated group '{group_name}': renamed '{old_name}' to '{new_name}'")
    
    return True


# <<< Function to get profile backup summary >>>
def get_profile_backup_summary(profile_name, backup_base_dir):
    """
    Returns a summary of backups for a profile.
    Returns: tuple (count: int, last_backup_datetime: datetime | None)
    """
    # Use the existing function that already sorts by date (newest first)
    backups = list_available_backups(profile_name, backup_base_dir) # Pass the argument
    count = len(backups)
    last_backup_dt = None

    if count > 0:
        most_recent_backup_path = backups[0][1] # Index 1 is the full path
        try:
            mtime_timestamp = os.path.getmtime(most_recent_backup_path)
            last_backup_dt = datetime.fromtimestamp(mtime_timestamp)
        except FileNotFoundError:
            logging.error(f"Last backup file not found ({most_recent_backup_path}) during getmtime for {profile_name}.")
        except Exception as e:
            logging.error(f"Unable to get last backup date for {profile_name} by '{most_recent_backup_path}': {e}")
    return count, last_backup_dt

# Loads profiles from the profile file, ensuring they are valid
def load_profiles():
    """
    Loads profiles from PROFILES_FILE_PATH, ensuring that values are
    dictionaries containing at least the 'path' key.
    """
    profiles_data = {} # Inizializza vuoto
    # Prima prova a caricare il contenuto grezzo del file JSON
    if os.path.exists(PROFILES_FILE_PATH):
        try:
            with open(PROFILES_FILE_PATH, 'r', encoding='utf-8') as f:
                profiles_data = json.load(f)
            logging.debug(f"File '{PROFILES_FILE_PATH}' caricato.")
        except json.JSONDecodeError:
            logging.warning(f"File profili '{PROFILES_FILE_PATH}' corrotto o vuoto. Sarà sovrascritto al prossimo salvataggio.")
            profiles_data = {} # Tratta come vuoto se corrotto
        except Exception as e:
            logging.error(f"Errore imprevisto durante la lettura iniziale di '{PROFILES_FILE_PATH}': {e}")
            profiles_data = {} # Tratta come vuoto per altri errori

    # Ora processa i dati caricati (profiles_data)
    loaded_profiles = {} # Dizionario per i profili processati e validati
    profiles_dict_source = {} # Dizionario sorgente da cui leggere i profili effettivi

    try:
        if isinstance(profiles_data, dict):
            # Controlla se è il nuovo formato con metadati o il vecchio formato
            if "__metadata__" in profiles_data and "profiles" in profiles_data:
                profiles_dict_source = profiles_data.get("profiles", {}) # Nuovo formato
                logging.debug("Processing profiles from new format (with metadata).")
            elif "__metadata__" not in profiles_data:
                # Se non ci sono metadati, assumi sia il vecchio formato (dict nome->path)
                profiles_dict_source = profiles_data
                logging.debug("Processing profiles assuming old format (name -> path string).")
            else:
                # Formato con metadata ma senza chiave 'profiles'? Strano.
                logging.warning("Profile file has '__metadata__' but missing 'profiles' key. Treating as empty.")
                profiles_dict_source = {}

            # --- Ciclo di Conversione e Validazione ---
            for name, path_or_data in profiles_dict_source.items():
                if isinstance(path_or_data, str):
                    # Vecchio formato: converti in dizionario base
                    logging.debug(f"Converting old format profile '{name}' to dict.")
                    # Verifica validità percorso prima di aggiungere
                    if os.path.isdir(path_or_data): # Controlla se il percorso è valido
                        loaded_profiles[name] = {'path': path_or_data}
                    else:
                        logging.warning(f"Path '{path_or_data}' for profile '{name}' (old format) is invalid. Skipping.")
                elif isinstance(path_or_data, dict):
                    # Check if this is a group profile (Matrioska profile)
                    if path_or_data.get('type') == 'group':
                        # Group profiles don't have 'paths' or 'path' - they contain references to other profiles
                        if 'profiles' in path_or_data and isinstance(path_or_data['profiles'], list):
                            loaded_profiles[name] = path_or_data.copy()
                            logging.debug(f"Group profile '{name}' validated with {len(path_or_data['profiles'])} member(s).")
                        else:
                            logging.warning(f"Group profile '{name}' is missing 'profiles' list. Skipping.")
                        continue
                    
                    # Nuovo formato o già convertito: assicurati che 'path' esista e sia valido
                    paths_key_present = 'paths' in path_or_data and isinstance(path_or_data['paths'], list) and path_or_data['paths']
                    path_key_present = 'path' in path_or_data and isinstance(path_or_data['path'], str) and path_or_data['path']

                    if paths_key_present:
                        # Validazione 'paths': Controlla che *almeno uno* dei percorsi sia una stringa valida (non necessariamente esistente qui)
                        # La validazione dell'esistenza avverrà dopo, al momento del backup.
                        if any(isinstance(p, str) and p for p in path_or_data['paths']):
                            loaded_profiles[name] = path_or_data.copy()
                            logging.debug(f"Profile '{name}' validated with 'paths' key.")
                        else:
                            logging.warning(f"Profile '{name}' has 'paths' key, but the list is empty or contains invalid entries. Skipping.")
                    elif path_key_present:
                        # Validazione 'path': Controlla che sia una stringa valida (non necessariamente esistente qui)
                        # La validazione dell'esistenza avverrà dopo.
                        if os.path.basename(path_or_data['path']): # Controllo base che non sia solo \ o / o vuota
                             loaded_profiles[name] = path_or_data.copy()
                             logging.debug(f"Profile '{name}' validated with 'path' key.")
                        else:
                             logging.warning(f"Profile '{name}' has 'path' key, but the path string '{path_or_data['path']}' seems invalid. Skipping.")
                    else:
                        # Nessuna chiave valida trovata
                        logging.warning(f"Profile '{name}' is a dict but missing a valid 'paths' (list) or 'path' (string) key. Skipping.")
                else:
                    # Formato imprevisto per questo profilo
                    logging.warning(f"Unrecognized profile format for '{name}'. Skipping.")
                    continue # Salta questo profilo problematico

        else:
            # Il file JSON non conteneva un dizionario principale
            logging.error(f"Profile file '{PROFILES_FILE_PATH}' content is not a valid JSON dictionary.")
            loaded_profiles = {}

    except Exception as e:
        # Cattura errori durante l'elaborazione del dizionario caricato
        logging.error(f"Error processing loaded profile data: {e}", exc_info=True)
        loaded_profiles = {} # Reset in caso di errore nell'elaborazione

    logging.info(f"Loaded and processed {len(loaded_profiles)} profiles from '{PROFILES_FILE_PATH}'.")
    
    # Clean up orphaned icons from deleted profiles
    try:
        from gui_components.icon_extractor import cleanup_orphaned_icons
        cleanup_orphaned_icons(loaded_profiles)
    except Exception as e:
        logging.debug(f"Could not cleanup orphaned icons: {e}")
    
    return loaded_profiles # Restituisci i profili processati

# Saves the profiles to the profile file
def save_profiles(profiles):
    """ 
    Save profiles in PROFILES_FILE_PATH. 
    """
    data_to_save = {
        "__metadata__": {
            "version": 1, # Esempio
            "saved_at": datetime.now().isoformat()
        },
        "profiles": profiles
    }
    try:
        # Assicura che la directory esista
        os.makedirs(os.path.dirname(PROFILES_FILE_PATH), exist_ok=True)
        with open(PROFILES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logging.info(f"Saved {len(profiles)} profiles in '{PROFILES_FILE_PATH}'.")
        # Mirror only when NOT in portable mode (portable is already in backup root)
        try:
            do_mirror = True
            try:
                import settings_manager as _sm2
                if _sm2.is_portable_mode():
                    do_mirror = False
            except Exception:
                pass
            if do_mirror:
                rotation = 0
                try:
                    import settings_manager as _sm3
                    settings, _ = _sm3.load_settings()
                    rotation = int(settings.get("mirror_rotation_keep", 0))
                except Exception:
                    rotation = 0
                _mirror_json_to_backup_root("game_save_profiles.json", data_to_save, rotation=rotation)
        except Exception as e_mirror:
            logging.warning(f"Unable to mirror profiles JSON to backup root: {e_mirror}")
        return True
    except Exception as e:
        logging.error(f"Error saving profiles in '{PROFILES_FILE_PATH}': {e}")
        return False

# --- Function to add a profile ---
def delete_profile(profiles, profile_name):
    """Deletes a profile from the dictionary. Returns True if deleted, False otherwise."""
    if profile_name in profiles:
        profile_data = profiles[profile_name]
        
        # Delete cached icon for this profile (only if no other profile uses the same icon)
        try:
            from gui_components.icon_extractor import delete_profile_icon
            delete_profile_icon(profile_data, profiles, profile_name)
        except Exception as e:
            logging.debug(f"Could not delete profile icon: {e}")
        
        del profiles[profile_name]
        logging.info(f"Profile '{profile_name}' removed from memory.")
        return True
    else:
        logging.warning(f"Attempt to delete non-existing profile: '{profile_name}'.")
        return False

# --- Backup/Restore Operations ---
def manage_backups(profile_name, backup_base_dir, max_backups):
    """Delete older .zip backups if they exceed the specified limit.
    
    Locked backups are excluded from the count and are never deleted during rotation.
    """
    deleted_files = []
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.debug(f"ManageBackups - Original name: '{profile_name}', Folder searched: '{profile_backup_dir}'")
    
    # Try to get the locked backup path for this profile
    locked_backup_path = None
    try:
        from gui_components import lock_backup_manager
        locked_backup_path = lock_backup_manager.get_locked_backup_for_profile(profile_name)
        if locked_backup_path:
            logging.debug(f"ManageBackups - Locked backup found: {locked_backup_path}")
    except ImportError:
        logging.debug("lock_backup_manager not available, skipping lock check")
    except Exception as e:
        logging.warning(f"Error checking locked backup: {e}")

    try:
        if not os.path.isdir(profile_backup_dir): return deleted_files

        logging.info(f"Checking outdated (.zip) backups in: {profile_backup_dir}")
        all_backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]
        
        # Separate locked and unlocked backups
        unlocked_backup_files = []
        for f in all_backup_files:
            full_path = os.path.join(profile_backup_dir, f)
            if locked_backup_path and os.path.normcase(os.path.normpath(full_path)) == os.path.normcase(os.path.normpath(locked_backup_path)):
                logging.debug(f"  Excluding locked backup from rotation: {f}")
            else:
                unlocked_backup_files.append(f)
        
        # Only count unlocked backups against the limit
        if len(unlocked_backup_files) <= max_backups:
            logging.info(f"Found {len(unlocked_backup_files)} unlocked backup(s) (.zip) (<= limit {max_backups})."
                        + (f" (1 locked backup excluded from count)" if locked_backup_path else ""))
            return deleted_files

        num_to_delete = len(unlocked_backup_files) - max_backups
        # Sort unlocked backups by modification time (oldest first)
        unlocked_backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        logging.info(f"Deleting {num_to_delete} older (.zip) backup(s)...")
        deleted_count = 0
        for i in range(num_to_delete):
            file_to_delete = os.path.join(profile_backup_dir, unlocked_backup_files[i])
            try:
                logging.info(f"  Deleting: {unlocked_backup_files[i]}")
                os.remove(file_to_delete)
                deleted_files.append(unlocked_backup_files[i])
                deleted_count += 1
            except Exception as e:
                logging.error(f"  Error deleting {unlocked_backup_files[i]}: {e}")
        logging.info(f"Deleted {deleted_count} outdated (.zip) backup(s).")

    except Exception as e:
        logging.error(f"Error managing outdated (.zip) backups for '{profile_name}': {e}")
    return deleted_files

# --- Backup Helper Functions ---

def _validate_source_paths(paths_to_process: list) -> tuple:
    """
    Validate that all source paths exist.
    
    Args:
        paths_to_process: List of normalized paths to validate
        
    Returns:
        Tuple (success: bool, invalid_paths: list)
    """
    invalid_paths = []
    
    logging.info("Starting path validation")
    for path in paths_to_process:
        try:
            if not os.path.exists(path):
                invalid_paths.append(path)
                logging.warning(f"Path does not exist: '{path}'")
        except OSError as e_os:
            invalid_paths.append(f"{path} (Error: OSError: {e_os})")
            logging.error(f"OS error checking path '{path}': {e_os}")
        except Exception as e_val:
            invalid_paths.append(f"{path} (Error: {type(e_val).__name__} - {e_val})")
            logging.error(f"General error checking path '{path}': {e_val}")
    
    if invalid_paths:
        logging.warning(f"Path validation failed: {len(invalid_paths)} invalid path(s)")
        return False, invalid_paths
    
    logging.info("Path validation successful - All paths OK")
    return True, []


def _check_source_size_limit(paths_to_process: list, max_source_size_mb: int) -> tuple:
    """
    Check if total source size is within the specified limit.
    
    Args:
        paths_to_process: List of paths to check
        max_source_size_mb: Maximum allowed size in MB (-1 to skip check)
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    logging.info(f"Checking source size for {len(paths_to_process)} path(s) "
                 f"(Limit: {'None' if max_source_size_mb == -1 else str(max_source_size_mb) + ' MB'})...")
    
    if max_source_size_mb == -1:
        logging.info("Source size check skipped (limit not set).")
        return True, None
    
    max_source_size_bytes = max_source_size_mb * 1024 * 1024
    total_size_bytes = _get_actual_total_source_size(paths_to_process)
    
    if total_size_bytes == -1:
        return False, "ERROR: Critical error while calculating total source size."
    
    current_size_mb = total_size_bytes / (1024 * 1024)
    logging.info(f"Total source size: {current_size_mb:.2f} MB")
    
    if total_size_bytes > max_source_size_bytes:
        msg = (f"ERROR: Backup cancelled!\n"
               f"Total source size ({current_size_mb:.2f} MB) exceeds the limit ({max_source_size_mb} MB).")
        return False, msg
    
    return True, None


def _get_compression_settings(compression_mode: str) -> tuple:
    """
    Get ZIP compression settings based on mode.
    
    Args:
        compression_mode: One of 'standard', 'best', 'fast', 'none'
        
    Returns:
        Tuple (compression_type, compression_level)
    """
    if compression_mode == "best":
        logging.info("Compression Mode: Maximum (Deflate Level 9)")
        return zipfile.ZIP_DEFLATED, 9
    elif compression_mode == "fast":
        logging.info("Compression Mode: Fast (Deflate Level 1)")
        return zipfile.ZIP_DEFLATED, 1
    elif compression_mode == "none":
        logging.info("Compression Mode: None (Store)")
        return zipfile.ZIP_STORED, None
    else:  # "standard" or default
        logging.info("Compression Mode: Standard (Deflate Level 6)")
        return zipfile.ZIP_DEFLATED, 6


def _detect_duckstation_single_file(profile_name: str, source_path: str) -> str:
    """
    Detect if this is a DuckStation profile and return the specific .mcd file to backup.
    
    DuckStation stores memory card files (.mcd) in a memcards directory.
    For single-path profiles pointing to this directory, we backup only the specific
    memory card file matching the profile name.
    
    Args:
        profile_name: Name of the profile
        source_path: Single source path (must be a directory)
        
    Returns:
        Path to the .mcd file if DuckStation detected, None otherwise
    """
    if not os.path.isdir(source_path):
        logging.debug(f"Single path is a file '{source_path}'. DuckStation logic not applicable.")
        return None
    
    logging.debug("--- DuckStation Detection ---")
    normalized_save_path = os.path.normpath(source_path).lower()
    expected_suffix = os.path.join("duckstation", "memcards").lower()
    
    logging.debug(f"  Source path: '{source_path}'")
    logging.debug(f"  Normalized: '{normalized_save_path}'")
    logging.debug(f"  Expected suffix: '{expected_suffix}'")
    
    if not normalized_save_path.endswith(expected_suffix):
        logging.debug("Single path is not DuckStation memcards directory. Standard backup.")
        return None
    
    # Extract the actual memory card name from profile name
    actual_card_name = profile_name
    prefix = "DuckStation - "
    if profile_name.startswith(prefix):
        actual_card_name = profile_name[len(prefix):]
    
    mcd_filename = actual_card_name + ".mcd"
    potential_mcd_path = os.path.join(source_path, mcd_filename)
    
    logging.debug(f"  Looking for MCD file: '{potential_mcd_path}'")
    
    if os.path.isfile(potential_mcd_path):
        logging.info(f"DuckStation profile detected. Will backup single file: {mcd_filename}")
        return potential_mcd_path
    else:
        logging.warning(f"Path looks like DuckStation memcards, but '{mcd_filename}' not found. "
                       f"Performing standard directory backup.")
        return None


def _detect_ymir_saturn_save(profile_data: dict) -> tuple:
    """
    Detect if this is a Ymir (Saturn) profile and return info for extracting the specific save.
    
    Ymir stores all Saturn saves in a single backup RAM file (bup-int.bin).
    Each game save is identified by a saturn_save_id (e.g., "SEGARALLY_0").
    For backup, we extract the specific save to a .bup file.
    For restore, we import the .bup file back into the backup RAM.
    
    Args:
        profile_data: Dictionary containing profile data with 'emulator' and 'saturn_save_id' keys
        
    Returns:
        Tuple (backup_ram_path: str, saturn_save_id: str) if Ymir detected, (None, None) otherwise
    """
    if not isinstance(profile_data, dict):
        return None, None
    
    # Check if this is a Ymir profile
    emulator = profile_data.get('emulator', '').lower()
    if emulator != 'ymir':
        return None, None
    
    # Get the Saturn save ID
    saturn_save_id = profile_data.get('saturn_save_id')
    if not saturn_save_id:
        logging.debug("Ymir profile detected but no saturn_save_id found.")
        return None, None
    
    # Find the backup RAM file (bup-int.bin) in the paths
    paths = profile_data.get('paths', [])
    if not paths:
        path = profile_data.get('path')
        if path:
            paths = [path]
    
    backup_ram_path = None
    for p in paths:
        if os.path.basename(p).lower() == 'bup-int.bin' and os.path.isfile(p):
            backup_ram_path = p
            break
        # Also check for external backup files
        if os.path.basename(p).lower().startswith('bup-ext') and os.path.isfile(p):
            backup_ram_path = p
            break
    
    if not backup_ram_path:
        logging.warning(f"Ymir profile detected but no backup RAM file found in paths: {paths}")
        return None, None
    
    logging.debug(f"Ymir profile detected: saturn_save_id='{saturn_save_id}', backup_ram='{backup_ram_path}'")
    return backup_ram_path, saturn_save_id


def _perform_ymir_backup(profile_name: str, profile_data: dict, archive_path: str, 
                          zip_compression, zip_compresslevel) -> tuple:
    """
    Perform a specialized backup for Ymir (Saturn) profiles.
    
    Extracts the specific game save from backup RAM to a .bup file and adds it to the ZIP.
    
    Args:
        profile_name: Name of the profile
        profile_data: Profile data dictionary
        archive_path: Path to the ZIP archive being created
        zip_compression: ZIP compression type
        zip_compresslevel: ZIP compression level
        
    Returns:
        Tuple (success: bool, message: str)
    """
    import tempfile
    
    backup_ram_path, saturn_save_id = _detect_ymir_saturn_save(profile_data)
    
    if not backup_ram_path or not saturn_save_id:
        return False, "Could not detect Ymir backup RAM file or Saturn save ID"
    
    try:
        from emulator_utils.ymir_manager import extract_saturn_save
    except ImportError as e:
        logging.error(f"Could not import ymir_manager: {e}")
        return False, f"Ymir manager not available: {e}"
    
    # Create a temporary directory for the extracted save
    temp_dir = tempfile.mkdtemp(prefix="savestate_ymir_")
    
    try:
        # Extract the save to a .bup file
        bup_filename = f"{saturn_save_id}.bup"
        bup_path = os.path.join(temp_dir, bup_filename)
        
        logging.debug(f"Ymir: Extracting save '{saturn_save_id}' from '{backup_ram_path}'...")
        extracted_path = extract_saturn_save(backup_ram_path, saturn_save_id, bup_path)
        
        if not extracted_path or not os.path.isfile(extracted_path):
            return False, f"Failed to extract Saturn save '{saturn_save_id}' from backup RAM"
        
        logging.debug(f"Ymir: Save extracted to '{extracted_path}' ({os.path.getsize(extracted_path)} bytes)")
        
        # Create the ZIP archive with the extracted .bup file
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, 
                            compresslevel=zip_compresslevel) as zipf:
            
            # Write manifest
            manifest_data = {
                "schema": 1,
                "app_version": getattr(config, "APP_VERSION", "unknown"),
                "created_at": datetime.now().isoformat(),
                "profile_name": profile_name,
                "emulator": "Ymir",
                "saturn_save_id": saturn_save_id,
                "backup_ram_path": backup_ram_path,
                "platform": platform.system(),
            }
            zipf.writestr("savestate/manifest.json", json.dumps(manifest_data, indent=2, ensure_ascii=False))
            
            # Add the .bup file
            zipf.write(extracted_path, arcname=bup_filename)
            logging.debug(f"Ymir: Added '{bup_filename}' to backup archive")
        
        return True, f"Ymir save '{saturn_save_id}' backed up successfully"
        
    except Exception as e:
        logging.error(f"Ymir backup failed: {e}", exc_info=True)
        return False, f"Ymir backup failed: {e}"
    
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def _perform_ymir_restore(profile_name: str, profile_data: dict, archive_path: str) -> tuple:
    """
    Perform a specialized restore for Ymir (Saturn) profiles.
    
    Extracts the .bup file from the ZIP and imports it into the backup RAM.
    
    Args:
        profile_name: Name of the profile
        profile_data: Profile data dictionary
        archive_path: Path to the ZIP archive to restore from
        
    Returns:
        Tuple (success: bool, message: str)
    """
    import tempfile
    
    backup_ram_path, saturn_save_id = _detect_ymir_saturn_save(profile_data)
    
    if not backup_ram_path:
        return False, "Could not detect Ymir backup RAM file"
    
    try:
        from emulator_utils.ymir_manager import import_saturn_save
    except ImportError as e:
        logging.error(f"Could not import ymir_manager: {e}")
        return False, f"Ymir manager not available: {e}"
    
    # Create a temporary directory for extraction
    temp_dir = tempfile.mkdtemp(prefix="savestate_ymir_restore_")
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zipf:
            # Find the .bup file in the archive
            bup_file = None
            for member in zipf.namelist():
                if member.endswith('.bup') and not member.startswith('savestate/'):
                    bup_file = member
                    break
            
            if not bup_file:
                return False, "No .bup save file found in the backup archive"
            
            # Extract the .bup file
            logging.debug(f"Ymir: Extracting '{bup_file}' from archive...")
            zipf.extract(bup_file, temp_dir)
            extracted_bup_path = os.path.join(temp_dir, bup_file)
            
            if not os.path.isfile(extracted_bup_path):
                return False, f"Failed to extract .bup file from archive"
        
        # Import the save into backup RAM
        logging.debug(f"Ymir: Importing save into '{backup_ram_path}'...")
        success = import_saturn_save(backup_ram_path, extracted_bup_path, overwrite=True)
        
        if success:
            return True, f"Ymir save restored successfully to '{backup_ram_path}'"
        else:
            return False, "Failed to import save into backup RAM"
        
    except Exception as e:
        logging.error(f"Ymir restore failed: {e}", exc_info=True)
        return False, f"Ymir restore failed: {e}"
    
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def _add_directory_to_zip(zipf: zipfile.ZipFile, source_path: str) -> None:
    """
    Add all files from a directory to a ZIP archive, preserving structure.
    
    Args:
        zipf: Open ZipFile object in write mode
        source_path: Path to the directory to add
    """
    base_folder_name = os.path.basename(source_path)
    len_source_path_parent = len(os.path.dirname(source_path)) + len(os.sep)
    
    for foldername, subfolders, filenames in os.walk(source_path):
        for filename in filenames:
            file_path_absolute = os.path.join(foldername, filename)
            # arcname preserves the base folder in the archive
            arcname = file_path_absolute[len_source_path_parent:]
            
            logging.debug(f"  Adding file: '{file_path_absolute}' as '{arcname}'")
            try:
                zipf.write(file_path_absolute, arcname=arcname)
            except FileNotFoundError:
                logging.warning(f"  Skipped file (not found during walk): '{file_path_absolute}'")
            except Exception as e:
                logging.error(f"  Error adding file '{file_path_absolute}' to zip: {e}")


def _add_single_file_to_zip(zipf: zipfile.ZipFile, source_path: str) -> None:
    """
    Add a single file to a ZIP archive, preserving its parent directory structure.
    
    Args:
        zipf: Open ZipFile object in write mode
        source_path: Path to the file to add
        
    Raises:
        FileNotFoundError: If the source file doesn't exist
        Exception: For other errors during archiving
    """
    source_dir = os.path.dirname(source_path)
    source_base_dir = os.path.dirname(source_dir)
    len_source_base_dir = len(source_base_dir) + len(os.sep)
    
    # arcname will be: parent_folder/file_name
    arcname = source_path[len_source_base_dir:]
    
    logging.debug(f"Adding file: '{source_path}' as '{arcname}'")
    zipf.write(source_path, arcname=arcname)


def _write_backup_manifest(zipf: zipfile.ZipFile, profile_name: str, 
                           paths_to_process: list, is_multiple_paths: bool) -> None:
    """
    Write a manifest.json file to the ZIP archive for self-description.
    
    Args:
        zipf: Open ZipFile object in write mode
        profile_name: Name of the profile being backed up
        paths_to_process: List of source paths
        is_multiple_paths: Whether this is a multi-path profile
    """
    try:
        manifest_data = {
            "schema": 1,
            "app_version": getattr(config, "APP_VERSION", "unknown"),
            "created_at": datetime.now().isoformat(),
            "profile_name": profile_name,
            "paths": paths_to_process,
            "multiple_paths": is_multiple_paths,
            "platform": platform.system(),
        }
        zipf.writestr("savestate/manifest.json", json.dumps(manifest_data, indent=2, ensure_ascii=False))
        logging.debug("Added savestate/manifest.json to the backup archive")
    except Exception as e:
        logging.warning(f"Unable to write backup manifest.json: {e}")


# --- Backup Function ---
def perform_backup(profile_name, source_paths, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard", profile_data=None):
    """
    Perform a backup using zipfile. Handles a single path (str) or multiple paths (list).
    
    Args:
        profile_name: Name of the profile to backup
        source_paths: Single path string or list of paths to backup
        backup_base_dir: Base directory for storing backups
        max_backups: Maximum number of backups to keep (-1 for unlimited)
        max_source_size_mb: Maximum source size in MB (-1 for no limit)
        compression_mode: 'standard', 'best', 'fast', or 'none'
        profile_data: Optional profile data dictionary (for emulator-specific handling)
        
    Returns:
        Tuple (success: bool, message: str)
    """
    logging.info(f"Starting perform_backup for: '{profile_name}'")
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.info(f"Original Name: '{profile_name}', Sanitized Folder Name: '{sanitized_folder_name}'")
    logging.debug(f"Backup path built: '{profile_backup_dir}'")

    is_multiple_paths = isinstance(source_paths, list)
    paths_to_process = [os.path.normpath(p) for p in (source_paths if is_multiple_paths else [source_paths])]
    logging.debug(f"Paths to process after normalization: {paths_to_process}")

    # --- Validate source paths ---
    paths_ok, invalid_paths = _validate_source_paths(paths_to_process)
    if not paths_ok:
        error_details = "\n".join(invalid_paths)
        error_message = f"One or more source paths do not exist or caused errors:\n{error_details}"
        logging.error(f"Backup error '{profile_name}': {error_message}")
        return False, error_message

    # --- Check source size limit ---
    size_ok, size_error = _check_source_size_limit(paths_to_process, max_source_size_mb)
    if not size_ok:
        logging.error(size_error)
        return False, size_error

    # --- Create backup directory ---
    try:
        os.makedirs(profile_backup_dir, exist_ok=True)
    except Exception as e:
        msg = f"ERROR: Unable to create backup directory '{profile_backup_dir}': {e}"
        logging.error(msg, exc_info=True)
        return False, msg

    # --- Prepare ZIP archive ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"Backup_{sanitized_folder_name}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    logging.info(f"Creating backup for '{profile_name}': {len(paths_to_process)} source(s) -> '{archive_path}'")

    zip_compression, zip_compresslevel = _get_compression_settings(compression_mode)

    # --- Check for Ymir (Saturn) specialized backup ---
    if profile_data:
        backup_ram_path, saturn_save_id = _detect_ymir_saturn_save(profile_data)
        if backup_ram_path and saturn_save_id:
            logging.info(f"Using Ymir specialized backup for '{profile_name}' (save: {saturn_save_id})")
            success, message = _perform_ymir_backup(profile_name, profile_data, archive_path, 
                                                    zip_compression, zip_compresslevel)
            if success:
                # Manage old backups
                deleted_files = manage_backups(profile_name, backup_base_dir, max_backups)
                deleted_msg = f" Deleted {len(deleted_files)} obsolete backups." if deleted_files else ""
                return True, f"Backup completed successfully:\n'{archive_name}'" + deleted_msg
            else:
                # Try to delete failed archive
                try:
                    if os.path.exists(archive_path):
                        os.remove(archive_path)
                except Exception:
                    pass
                return False, message

    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, compresslevel=zip_compresslevel) as zipf:
            # Write manifest for self-describing backup
            _write_backup_manifest(zipf, profile_name, paths_to_process, is_multiple_paths)

            # Check for DuckStation single-file backup (only for single-path profiles)
            duckstation_mcd_file = None
            if not is_multiple_paths:
                duckstation_mcd_file = _detect_duckstation_single_file(profile_name, paths_to_process[0])

            # --- Execute Backup ---
            if duckstation_mcd_file:
                # DuckStation: backup only the specific .mcd file
                mcd_arcname = os.path.basename(duckstation_mcd_file)
                logging.debug(f"Adding DuckStation file: '{duckstation_mcd_file}' as '{mcd_arcname}'")
                zipf.write(duckstation_mcd_file, arcname=mcd_arcname)
                logging.info(f"DuckStation file '{mcd_arcname}' added to archive.")
            else:
                # Standard backup: process all paths
                logging.debug(f"Executing standard backup for {len(paths_to_process)} path(s).")
                for source_path in paths_to_process:
                    logging.debug(f"Processing source path: {source_path}")
                    if os.path.isdir(source_path):
                        _add_directory_to_zip(zipf, source_path)
                    elif os.path.isfile(source_path):
                        _add_single_file_to_zip(zipf, source_path)

        logging.info(f"Backup archive created successfully: '{archive_path}'")

    except (IOError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        msg = f"ERROR during ZIP archive creation '{archive_path}': {e}"
        logging.error(msg, exc_info=True)
        # Try to delete the potentially corrupted/incomplete archive
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
                logging.warning(f"Potentially incomplete archive deleted: {archive_path}")
        except Exception as del_e:
            logging.error(f"Unable to delete incomplete archive '{archive_path}': {del_e}")
        return False, msg
    except Exception as e: # Catch other unexpected errors
         msg = f"UNEXPECTED ERROR during ZIP backup creation '{profile_name}': {e}"
         logging.error(msg, exc_info=True)
         try:
             if os.path.exists(archive_path): os.remove(archive_path); logging.warning(f"Failed archive removed: {archive_name}")
         except Exception as rem_e: logging.error(f"Unable to remove failed archive: {rem_e}")
         return False, msg
    # --- END ZIP Archive Creation ---

    # --- Gestione Vecchi Backup ---
    deleted_files = manage_backups(profile_name, backup_base_dir, max_backups)
    deleted_msg = f" Deleted {len(deleted_files)} obsolete backups." if deleted_files else ""
    # --- FINE Gestione ---

    return True, f"Backup completed successfully:\n'{archive_name}'" + deleted_msg

# --- Support Function for Folder Size Calculation ---
def list_available_backups(profile_name, backup_base_dir):
    """Restituisce una lista di tuple (nome_file, percorso_completo, data_modifica_str) per i backup di un profilo."""
    backups = []
    sanitized_folder_name = sanitize_foldername(profile_name)
    # <<< MODIFICATO: Usa backup_base_dir dalle impostazioni (richiede passaggio o accesso globale)
    # Assumendo che 'config' fornisca il percorso corretto
    
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.debug(f"ListBackups - Original name: '{profile_name}', Folder searched: '{profile_backup_dir}'")

    if not os.path.isdir(profile_backup_dir):
        return backups # Nessuna cartella = nessun backup

    try:
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]
        # Ordina dal più recente
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)), reverse=True)

        for fname in backup_files:
            fpath = os.path.join(profile_backup_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                backup_datetime = datetime.fromtimestamp(mtime)
                #date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = "Unknown date"
            backups.append((fname, fpath, backup_datetime))
    except Exception as e:
        logging.error(f"Error listing backups for '{profile_name}': {e}")

    return backups

# --- Restore Helper Functions ---

def _validate_restore_archive(archive_path: str) -> tuple:
    """
    Validate that the archive exists and is a valid ZIP file.
    
    Args:
        archive_path: Path to the archive file
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    if not os.path.isfile(archive_path):
        return False, f"ERROR: Restore archive not found: '{archive_path}'"
    
    if not zipfile.is_zipfile(archive_path):
        return False, f"ERROR: The selected file is not a valid ZIP archive: '{archive_path}'"
    
    return True, None


def _cleanup_destination_path(dest_path: str) -> tuple:
    """
    Clean up a single destination path before restoration.
    Creates parent directories if needed and removes existing content.
    
    Args:
        dest_path: The destination path to clean up
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    # Ensure the parent directory exists
    parent_dir = os.path.dirname(dest_path)
    try:
        if parent_dir and not os.path.exists(parent_dir):
            logging.info(f"Creating missing parent directory: '{parent_dir}'")
            os.makedirs(parent_dir, exist_ok=True)
    except Exception as e:
        return False, f"ERROR creating parent directory '{parent_dir}': {e}"

    # Clean existing content
    if os.path.isdir(dest_path):
        logging.warning(f"Removing contents of existing directory: '{dest_path}'")
        try:
            for item in os.listdir(dest_path):
                item_path = os.path.join(dest_path, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    logging.debug(f"  Removed subdirectory: {item_path}")
                elif os.path.isfile(item_path):
                    os.remove(item_path)
                    logging.debug(f"  Removed file: {item_path}")
            logging.info(f"Contents of '{dest_path}' successfully cleaned.")
        except Exception as e:
            return False, f"ERROR during cleanup of destination directory '{dest_path}': {e}"
    
    elif os.path.isfile(dest_path):
        logging.warning(f"Removing existing single file: '{dest_path}'")
        try:
            os.remove(dest_path)
            logging.info(f"Single file successfully removed: '{dest_path}'")
        except FileNotFoundError:
            logging.info(f"Destination file '{dest_path}' did not exist, no removal necessary.")
        except Exception as e:
            return False, f"ERROR removing destination file '{dest_path}': {e}"
    else:
        logging.info(f"Destination path '{dest_path}' does not exist (will be created).")
    
    return True, None


def _cleanup_all_destination_paths(paths_to_process: list) -> tuple:
    """
    Clean up all destination paths before restoration.
    
    Args:
        paths_to_process: List of destination paths
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    logging.warning("--- Preparing to clean destination path(s) before restore ---")
    
    for dest_path in paths_to_process:
        success, error = _cleanup_destination_path(dest_path)
        if not success:
            logging.error(error, exc_info=True)
            return False, error
    
    logging.warning("--- Destination cleanup completed ---")
    return True, None


def _find_zip_base_folders(zipf: zipfile.ZipFile, dest_map: dict) -> bool:
    """
    Check if the ZIP contains base folders matching the destination map.
    
    Args:
        zipf: Open ZipFile object
        dest_map: Dictionary mapping base folder names to destination paths
        
    Returns:
        True if matching base folders found, False otherwise
    """
    for member in zipf.namelist():
        normalized_path = member.replace('/', os.sep)
        path_parts = normalized_path.split(os.sep, 1)
        if len(path_parts) > 0:
            base_folder = path_parts[0]
            if base_folder in dest_map:
                logging.debug(f"Found matching base folder: '{base_folder}' in ZIP member: '{member}'")
                return True
    return False


def _find_zip_matching_filenames(zipf: zipfile.ZipFile, paths_to_process: list) -> bool:
    """
    Check if the ZIP contains files matching destination filenames directly.
    
    Args:
        zipf: Open ZipFile object
        paths_to_process: List of destination paths
        
    Returns:
        True if matching filenames found, False otherwise
    """
    zip_members = zipf.namelist()
    for dest_path in paths_to_process:
        dest_filename = os.path.basename(dest_path)
        for member in zip_members:
            normalized_m = member.replace('/', os.sep)
            if normalized_m.endswith(os.sep + dest_filename) or normalized_m == dest_filename:
                logging.debug(f"Found matching filename: '{dest_filename}' in ZIP member: '{member}'")
                return True
    return False


def _extract_by_filename_matching(zipf: zipfile.ZipFile, paths_to_process: list) -> tuple:
    """
    Extract files from ZIP by matching filenames to destination paths.
    Used as fallback when base folder matching fails.
    
    Args:
        zipf: Open ZipFile object
        paths_to_process: List of destination paths
        
    Returns:
        Tuple (success: bool, error_message: str or None)
    """
    logging.warning("Base folders not found in ZIP. Trying alternative extraction method based on filenames.")
    
    filename_to_dest = {os.path.basename(p): p for p in paths_to_process}
    logging.debug(f"Filename to destination map: {filename_to_dest}")
    
    zip_filename_to_path = {os.path.basename(m.replace('/', os.sep)): m for m in zipf.namelist()}
    logging.debug(f"ZIP filename to path map: {zip_filename_to_path}")
    
    matches_found = False
    for filename, dest_path in filename_to_dest.items():
        if filename in zip_filename_to_path:
            matches_found = True
            zip_path = zip_filename_to_path[filename]
            logging.info(f"Found match: {filename} in ZIP as {zip_path}")
            
            # Security check: verify zip_path doesn't contain path traversal
            if '..' in zip_path or zip_path.startswith('/') or zip_path.startswith('\\'):
                msg = f"SECURITY: Blocked suspicious ZIP path: '{zip_path}'"
                logging.error(msg)
                return False, msg
            
            try:
                dest_dir = os.path.dirname(dest_path)
                if dest_dir and not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                
                with zipf.open(zip_path) as source, open(dest_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
                logging.info(f"Successfully extracted {zip_path} to {dest_path}")
            except Exception as e:
                logging.error(f"Error extracting {zip_path} to {dest_path}: {e}")
                return False, f"Error during alternative extraction method: {e}"
    
    if matches_found:
        return True, None
    
    return False, "No matching files found"


def _extract_member_to_destination(zipf: zipfile.ZipFile, member_path: str, 
                                    dest_map: dict, error_messages: list) -> bool:
    """
    Extract a single ZIP member to its corresponding destination.
    
    Args:
        zipf: Open ZipFile object
        member_path: Path of the member inside the ZIP
        dest_map: Dictionary mapping base folder names to destination paths
        error_messages: List to append error messages to
        
    Returns:
        True if extraction succeeded, False otherwise
    """
    normalized_member_path = member_path.replace('/', os.sep)
    
    try:
        zip_base_folder = normalized_member_path.split(os.sep, 1)[0]
    except IndexError:
        logging.warning(f"Skipping member with invalid path format: '{member_path}'")
        return True  # Not an error, just skip
    
    if zip_base_folder not in dest_map:
        logging.warning(f"ZIP member '{member_path}' (base: '{zip_base_folder}') "
                       f"doesn't match any destination ({list(dest_map.keys())}). Skipping.")
        return True  # Not an error, just skip
    
    target_dest_path_base = dest_map[zip_base_folder]
    relative_path = normalized_member_path[len(zip_base_folder):].lstrip(os.sep)
    full_extract_path = os.path.join(target_dest_path_base, relative_path)
    
    # Security check: Zip Slip protection
    if not _is_safe_zip_path(relative_path, target_dest_path_base):
        msg = f"SECURITY: Blocked unsafe ZIP path (potential path traversal): '{member_path}'"
        logging.error(msg)
        error_messages.append(msg)
        return False
    
    # Handle directories
    if member_path.endswith('/') or member_path.endswith('\\'):
        if relative_path:
            logging.debug(f"  Creating directory from zip: {full_extract_path}")
            os.makedirs(full_extract_path, exist_ok=True)
        return True
    
    # Handle files
    file_dir = os.path.dirname(full_extract_path)
    if file_dir and not os.path.exists(file_dir):
        logging.debug(f"  Creating directory for file: {file_dir}")
        os.makedirs(file_dir, exist_ok=True)
    
    try:
        with zipf.open(member_path) as source, open(full_extract_path, 'wb') as target:
            shutil.copyfileobj(source, target)
        logging.debug(f"  Extracted file {member_path} -> {full_extract_path}")
        return True
    except Exception as e:
        msg = f"ERROR extracting file '{member_path}' to '{full_extract_path}': {e}"
        logging.error(msg, exc_info=True)
        error_messages.append(msg)
        return False


# --- Restore Function ---
def perform_restore(profile_name, destination_paths, archive_to_restore_path, profile_data=None):
    """
    Perform restoration from a ZIP archive. Handles a single path (str) or multiple paths (list).
    
    Args:
        profile_name: Name of the profile being restored
        destination_paths: Single path string or list of destination paths
        archive_to_restore_path: Path to the backup archive
        profile_data: Optional profile data dictionary (for emulator-specific handling)
        
    Returns:
        Tuple (success: bool, message: str)
    """
    logging.info(f"Starting perform_restore for profile: '{profile_name}'")
    logging.info(f"Archive selected for restoration: '{archive_to_restore_path}'")

    is_multiple_paths = isinstance(destination_paths, list)
    paths_to_process = [os.path.normpath(p) for p in (destination_paths if is_multiple_paths else [destination_paths])]
    logging.info(f"Target destination path(s): {paths_to_process}")

    # --- Validate archive ---
    archive_ok, archive_error = _validate_restore_archive(archive_to_restore_path)
    if not archive_ok:
        logging.error(archive_error)
        return False, archive_error

    # --- Check for Ymir (Saturn) specialized restore ---
    if profile_data:
        backup_ram_path, saturn_save_id = _detect_ymir_saturn_save(profile_data)
        if backup_ram_path:
            logging.info(f"Using Ymir specialized restore for '{profile_name}'")
            return _perform_ymir_restore(profile_name, profile_data, archive_to_restore_path)

    # --- Clean destination paths ---
    cleanup_ok, cleanup_error = _cleanup_all_destination_paths(paths_to_process)
    if not cleanup_ok:
        return False, cleanup_error

    # --- Archive Extraction ---
    logging.info(f"Starting extraction from '{archive_to_restore_path}'...")
    extracted_successfully = True
    error_messages = []

    try:
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:
            zip_members = zipf.namelist()
            logging.debug(f"ZIP contains {len(zip_members)} members. First 10: {zip_members[:10]}")

            if is_multiple_paths:
                # --- Multi-Path Extraction ---
                logging.debug("Multi-path restore: Mapping zip content to destination paths.")
                dest_map = {os.path.basename(p): p for p in paths_to_process}
                logging.debug(f"Destination map created: {dest_map}")

                # Check extraction strategy
                zip_has_base_folders = _find_zip_base_folders(zipf, dest_map)
                zip_has_matching_filenames = _find_zip_matching_filenames(zipf, paths_to_process)

                logging.debug(f"ZIP has base folders: {zip_has_base_folders}, has matching filenames: {zip_has_matching_filenames}")

                # Try alternative filename-based extraction if base folders not found
                if not zip_has_base_folders and zip_has_matching_filenames:
                    alt_success, alt_error = _extract_by_filename_matching(zipf, paths_to_process)
                    if alt_success:
                        return True, "Restore completed successfully using alternative extraction method."
                    elif alt_error and alt_error != "No matching files found":
                        return False, alt_error
                    # If no matches found, fall through to error below

                # If we can't find base folders, fail with clear error
                if not zip_has_base_folders:
                    msg = ("ERROR: Multi-path restore failed. ZIP does not contain expected "
                           "base folders nor matching filenames for destinations.")
                    logging.error(msg)
                    logging.error(f"Archive members (sample): {zip_members[:10]}")
                    logging.error(f"Expected destinations: {list(dest_map.keys())}")
                    return False, msg

                # Standard multi-path extraction
                for member_path in zip_members:
                    if not _extract_member_to_destination(zipf, member_path, dest_map, error_messages):
                        extracted_successfully = False

            else:
                # --- Single Path Extraction ---
                single_dest_path = paths_to_process[0]
                os.makedirs(single_dest_path, exist_ok=True)
                logging.debug(f"Single path restore: Extracting all content to '{single_dest_path}'")

                success, blocked, extract_errors = _safe_extractall(zipf, single_dest_path)
                if blocked:
                    error_messages.append(f"SECURITY: Blocked {len(blocked)} potentially malicious paths")
                    extracted_successfully = False
                if extract_errors:
                    error_messages.extend(extract_errors)
                    extracted_successfully = False
                if success:
                    logging.info(f"Content successfully extracted to '{single_dest_path}'")

    except zipfile.BadZipFile:
        msg = f"ERROR: The file is not a valid ZIP archive or is corrupted: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    except (IOError, OSError) as e: # Catch IO/OS errors
        msg = f"ERROR IO/OS during extraction: {e}"
        logging.error(msg, exc_info=True)
        error_messages.append(msg)
        extracted_successfully = False
    except Exception as e:
        msg = f"FATAL ERROR unexpected during the restore process: {e}"
        logging.error(msg, exc_info=True)
        # Make sure to return accumulated errors if present
        final_message = msg
        if error_messages:
            final_message += "\n\nAdditional errors encountered during extraction:\n" + "\n".join(error_messages)
        return False, final_message
    # --- END Archive Extraction ---

    # --- Risultato Finale ---
    if extracted_successfully:
        msg = f"Restore completed successfully for profile '{profile_name}'."
        logging.info(msg)
        final_message = msg
        if error_messages: # Aggiunge avvisi anche in caso di successo parziale
             final_message += "\n\nATTENZIONE: Sono stati riscontrati alcuni errori durante l'estrazione:\n" + "\n".join(error_messages)
        return True, final_message
    else:
        msg = f"Restore for profile '{profile_name}' failed or completed with errors."
        logging.error(msg)
        final_message = msg
        if error_messages:
            final_message += "\n\nDettaglio errori:\n" + "\n".join(error_messages)
        return False, final_message

# --- Steam Detection Logic ---
# Steam utilities are now in a separate module for better organization.
# These imports maintain backward compatibility with existing code.

from steam_utils import (
    get_steam_install_path,
    find_steam_libraries,
    find_installed_steam_games,
    find_steam_userdata_info,
    clear_steam_cache,
    STEAM_ID64_BASE,
)

# --- Function to delete a backup file ---
def delete_single_backup_file(file_path):
    """Deletes a single backup file specified by the full path.
    
    Returns (False, message) if the backup is locked.
    """
    if not file_path:
        msg = "ERROR: No file path specified for deletion."
        logging.error(msg)
        return False, msg
    if not os.path.isfile(file_path):
        msg = f"ERROR: File to delete not found or is not a valid file: '{file_path}'"
        logging.error(msg)
        return False, msg # Considera errore se file non esiste
    
    # Check if the backup is locked
    try:
        from gui_components import lock_backup_manager
        if lock_backup_manager.is_backup_locked(file_path):
            backup_name = os.path.basename(file_path)
            msg = f"Cannot delete '{backup_name}': backup is locked. Unlock it first."
            logging.warning(msg)
            return False, msg
    except ImportError:
        logging.debug("lock_backup_manager not available, skipping lock check")
    except Exception as e:
        logging.warning(f"Error checking backup lock status: {e}")

    backup_name = os.path.basename(file_path)
    logging.warning(f"Attempting permanent deletion of file: {file_path}")

    try:
        os.remove(file_path)
        msg = f"File '{backup_name}' deleted successfully."
        logging.info(msg)
        return True, msg
    except OSError as e:
        msg = f"ERROR OS during deletion of '{backup_name}': {e}"
        logging.error(msg)
        return False, msg
    except Exception as e:
        msg = f"ERROR unexpected during deletion of '{backup_name}': {e}"
        logging.exception(msg) # Logga traceback
        return False, msg

# --- Function to calculate the size of a folder ---
def get_directory_size(directory_path):
    """Calculates recursively the total size of a folder in bytes."""
    total_size = 0
    if not os.path.isdir(directory_path): # <<< NEW: Check if it's a valid directory
         logging.error(f"ERROR get_directory_size: Path is not a valid directory: {directory_path}")
         return -1 # Indicates error

    try:
        for dirpath, dirnames, filenames in os.walk(directory_path, topdown=True, onerror=lambda err: logging.warning(f"Error walking {err.filename}: {err.strerror}")):
            # Escludi ricorsivamente cartelle comuni non utente (opzionale)
            # dirnames[:] = [d for d in dirnames if d.lower() not in ['__pycache__', '.git', '.svn']]

            for f in filenames:
                fp = os.path.join(dirpath, f)
                # Salta link simbolici rotti o file inaccessibili
                try:
                    if not os.path.islink(fp):
                         total_size += os.path.getsize(fp)
                    # else: logging.debug(f"Skipping symlink: {fp}") # Log se necessario
                except OSError as e:
                    logging.warning(f"ERROR getting size for {fp}: {e}") # Logga ma continua
    except Exception as e:
        logging.error(f"ERROR during size calculation for {directory_path}: {e}")
        return -1 # Returns -1 to indicate calculation error
    return total_size

# --- Function to get display name from backup filename ---
def get_display_name_from_backup_filename(filename):
    """
    Removes the timestamp suffix (_YYYYMMDD_HHMMSS) from a backup file name
    for a cleaner display.

    Ex: "Backup_ProfiloX_20250422_030000.zip" -> "Backup_ProfiloX"
    """
    if isinstance(filename, str) and filename.endswith(".zip"):
        # Tenta di rimuovere il pattern specifico _8cifre_6cifre.zip
        # Usiamo re.sub per sostituire il pattern con '' (stringa vuota)
        # Il pattern: _ seguita da 8 cifre (\d{8}), _ seguita da 6 cifre (\d{6}), seguito da .zip alla fine ($)
        display_name = re.sub(r'_\d{8}_\d{6}\.zip$', '.zip', filename)
        # Se la sostituzione ha funzionato, rimuoviamo anche l'estensione .zip finale per la visualizzazione
        if display_name != filename: # Verifica se la sostituzione è avvenuta
             return display_name[:-4] # Rimuovi ".zip"
        else:
             # Se il pattern non corrisponde, restituisci il nome senza estensione come fallback
             logging.warning(f"Timestamp pattern not found in backup filename: {filename}")
             return filename[:-4] if filename.endswith('.zip') else filename
    return filename # Restituisci l'input originale se non è una stringa o non finisce per .zip

# --- JSON Backup Restore Functions ---
def restore_json_from_backup_root() -> bool:
    """Restore JSON files (profiles, settings, favorites) from backup_root/.savestate/ directory."""
    backup_root = _get_backup_root_from_settings()
    if not backup_root:
        logging.error("Cannot restore JSONs: backup root not found")
        return False
    
    mirror_dir = os.path.join(backup_root, ".savestate")
    if not os.path.isdir(mirror_dir):
        logging.warning(f"Mirror directory does not exist: {mirror_dir}")
        return False
    
    # Files to restore (match mirror filenames)
    files_to_restore = ["game_save_profiles.json", "settings.json", "favorites_status.json", "cloud_settings.json"]
    restored_count = 0
    
    for filename in files_to_restore:
        source_file = os.path.join(mirror_dir, filename)
        if not os.path.isfile(source_file):
            logging.warning(f"Backup file not found: {source_file}")
            continue
        
        # Determine destination based on file type
        if filename == "game_save_profiles.json":
            dest_path = PROFILES_FILE_PATH
        elif filename == "settings.json":
            try:
                import settings_manager as _sm_restore
                dest_root = _sm_restore.get_active_config_dir()
            except Exception:
                dest_root = config.get_app_data_folder()
            dest_path = os.path.join(dest_root, filename)
        elif filename == "favorites_status.json":
            try:
                # Use path constant from favorites_manager to avoid duplication
                from gui_components import favorites_manager as _fav
                dest_path = _fav.FAVORITES_FILE_PATH
            except Exception:
                try:
                    import settings_manager as _sm_restore2
                    dest_root = _sm_restore2.get_active_config_dir()
                except Exception:
                    dest_root = config.get_app_data_folder()
                dest_path = os.path.join(dest_root, filename)
        else:
            continue
        
        try:
            import shutil
            # Skip if source and destination coincide (portable mode)
            try:
                if os.path.normcase(os.path.abspath(source_file)) == os.path.normcase(os.path.abspath(dest_path)):
                    logging.info(f"Skipping restore for {filename}: source and destination are the same.")
                    restored_count += 1
                    continue
            except Exception:
                pass
            # Create backup of current file before overwriting
            if os.path.exists(dest_path):
                backup_path = dest_path + ".before_restore"
                shutil.copy2(dest_path, backup_path)
                logging.info(f"Created backup of current file: {backup_path}")
            
            # Copy the backup file to destination
            shutil.copy2(source_file, dest_path)
            logging.info(f"Restored {filename} from {source_file} to {dest_path}")
            restored_count += 1
        except Exception as e:
            logging.error(f"Failed to restore {filename}: {e}", exc_info=True)
    
    return restored_count > 0

def read_manifest_from_zip(zip_path: str) -> dict:
    """Read and parse manifest.json from savestate/ folder inside a ZIP archive.
    Returns manifest dict if found and valid, None otherwise."""
    import zipfile
    
    if not os.path.isfile(zip_path):
        logging.error(f"ZIP file not found: {zip_path}")
        return None
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            manifest_path = "savestate/manifest.json"
            
            # Check if manifest exists in ZIP
            if manifest_path not in zipf.namelist():
                logging.warning(f"No manifest.json found in {zip_path}")
                return None
            
            # Read and parse manifest
            with zipf.open(manifest_path) as manifest_file:
                manifest_data = json.load(manifest_file)
                logging.info(f"Successfully read manifest from {zip_path}")
                return manifest_data
                
    except zipfile.BadZipFile:
        logging.error(f"Invalid ZIP file: {zip_path}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in manifest: {e}")
        return None
    except Exception as e:
        logging.error(f"Error reading manifest from ZIP: {e}", exc_info=True)
        return None

def validate_backup_zip(zip_path: str) -> tuple:
    """Validate a backup ZIP file and return (is_valid: bool, manifest: dict or None, error_msg: str)."""
    import zipfile
    
    if not os.path.isfile(zip_path):
        return False, None, f"File not found: {zip_path}"
    
    if not zipfile.is_zipfile(zip_path):
        return False, None, "Not a valid ZIP file"
    
    manifest = read_manifest_from_zip(zip_path)
    if manifest is None:
        return False, None, "No valid manifest.json found in savestate/ folder"
    
    # Validate manifest has required fields
    required_fields = ["profile_name", "created_at"]
    for field in required_fields:
        if field not in manifest:
            return False, manifest, f"Manifest missing required field: {field}"
    
    return True, manifest, ""

def _get_actual_total_source_size(source_paths_list):
    """Calculates the total actual size of source paths, resolving .lnk shortcuts on Windows."""
    total_size = 0
    logging.debug(f"Calculating actual total source size for paths: {source_paths_list}")

    for single_path_str in source_paths_list:
        actual_path_to_measure = single_path_str
        is_shortcut = False
        original_shortcut_path = None

        if platform.system() == "Windows" and \
           single_path_str.lower().endswith(".lnk") and \
           os.path.isfile(single_path_str):
            is_shortcut = True
            original_shortcut_path = single_path_str
            try:
                try:
                    import winshell
                except Exception:
                    winshell = None
                if winshell is None:
                    raise RuntimeError("winshell not available to resolve .lnk")
                shortcut = winshell.shortcut(single_path_str)
                target_path = shortcut.path
                if target_path and os.path.exists(target_path):
                    actual_path_to_measure = target_path
                    logging.debug(f"Resolved shortcut '{single_path_str}' to '{actual_path_to_measure}'")
                elif target_path:
                    logging.warning(f"Shortcut '{single_path_str}' target '{target_path}' does not exist. Skipping for size calculation.")
                    continue
                else:
                    logging.warning(f"Shortcut '{single_path_str}' has an empty or invalid target path. Skipping for size calculation.")
                    continue
            except Exception as e_lnk:
                logging.warning(f"Could not resolve shortcut '{single_path_str}': {e_lnk}. Skipping for size calculation.")
                continue
        
        if not os.path.exists(actual_path_to_measure):
            log_msg = f"Source path '{actual_path_to_measure}'"
            if is_shortcut:
                log_msg += f" (from shortcut '{original_shortcut_path}')"
            log_msg += " does not exist. Skipping for size calculation."
            logging.warning(log_msg)
            continue

        try:
            current_item_size = 0
            if os.path.isfile(actual_path_to_measure):
                current_item_size = os.path.getsize(actual_path_to_measure)
                logging.debug(f"Size of file '{actual_path_to_measure}': {current_item_size} bytes")
            elif os.path.isdir(actual_path_to_measure):
                dir_size = get_directory_size(actual_path_to_measure) # Assumes get_directory_size exists and is robust
                if dir_size != -1:
                    current_item_size = dir_size
                    logging.debug(f"Size of directory '{actual_path_to_measure}': {current_item_size} bytes")
                else:
                    logging.warning(f"Could not get size of directory '{actual_path_to_measure}'. Skipping.")
                    continue
            else:
                logging.warning(f"Path '{actual_path_to_measure}' (from '{original_shortcut_path}' if shortcut) is not a file or directory. Skipping.")
                continue
            total_size += current_item_size
        except OSError as e_size:
            logging.warning(f"OS error getting size for '{actual_path_to_measure}': {e_size}. Skipping.")
            continue
            
    logging.info(f"Total actual calculated source size: {total_size} bytes ({total_size / (1024*1024):.2f} MB).")
    return total_size