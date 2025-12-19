# lock_backup_manager.py
# -*- coding: utf-8 -*-
"""
Manager for locked backups - handles metadata and read-only protection.

Each profile can have at most ONE locked backup. Locked backups:
- Cannot be deleted through the app
- Are excluded from the max_backups rotation count
- Have the read-only attribute set on the filesystem
"""

import os
import json
import stat
import logging
import config

# --- Locked Backups File Name and Path (dynamic using settings_manager) ---
LOCKED_BACKUPS_FILENAME = "locked_backups.json"
try:
    import settings_manager as _sm
    _ACTIVE_CONFIG_DIR = _sm.get_active_config_dir()
except Exception:
    _ACTIVE_CONFIG_DIR = config.get_app_data_folder()
    logging.warning("Failed to import settings_manager for active config dir; falling back to AppData.")

if _ACTIVE_CONFIG_DIR:
    LOCKED_BACKUPS_FILE_PATH = os.path.join(_ACTIVE_CONFIG_DIR, LOCKED_BACKUPS_FILENAME)
else:
    logging.error("Unable to determine configuration directory for locked backups. Using relative path.")
    LOCKED_BACKUPS_FILE_PATH = os.path.abspath(LOCKED_BACKUPS_FILENAME)
logging.info(f"Locked backups file path in use: {LOCKED_BACKUPS_FILE_PATH}")
# --- End of Locked Backups File Path Definition ---

_locked_cache = {}  # Internal cache to avoid continuous disk reads
_cache_loaded = False  # Flag to know if cache has been loaded


def _set_file_readonly(file_path: str, readonly: bool = True) -> bool:
    """
    Set or remove the read-only attribute on a file.
    
    Args:
        file_path: Path to the file
        readonly: True to set read-only, False to remove it
        
    Returns:
        True if successful, False otherwise
    """
    if not os.path.isfile(file_path):
        logging.warning(f"Cannot set read-only attribute: file does not exist: {file_path}")
        return False
    
    try:
        if readonly:
            # Set read-only (remove write permission)
            current_mode = os.stat(file_path).st_mode
            os.chmod(file_path, current_mode & ~stat.S_IWRITE)
            logging.debug(f"Set read-only attribute on: {file_path}")
        else:
            # Remove read-only (add write permission)
            current_mode = os.stat(file_path).st_mode
            os.chmod(file_path, current_mode | stat.S_IWRITE)
            logging.debug(f"Removed read-only attribute from: {file_path}")
        return True
    except OSError as e:
        logging.error(f"Failed to {'set' if readonly else 'remove'} read-only attribute on {file_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error setting file attributes on {file_path}: {e}")
        return False


def _prune_stale_locks(locked_dict: dict) -> dict:
    """
    Return a cleaned copy of locked_dict, removing entries where the backup file no longer exists.
    
    Args:
        locked_dict: Dictionary with structure {"locked": {"profile_name": "backup_path"}}
        
    Returns:
        Cleaned dictionary
    """
    if not isinstance(locked_dict, dict):
        return {"locked": {}}
    
    locked_entries = locked_dict.get("locked", {})
    if not isinstance(locked_entries, dict):
        return {"locked": {}}
    
    cleaned = {}
    for profile_name, backup_path in locked_entries.items():
        if isinstance(backup_path, str) and os.path.isfile(backup_path):
            cleaned[profile_name] = backup_path
        else:
            logging.info(f"Pruned stale lock entry for profile '{profile_name}': file no longer exists")
    
    return {"locked": cleaned}


def load_locked_backups() -> dict:
    """
    Load locked backups status from LOCKED_BACKUPS_FILE_PATH.
    
    Returns:
        Dictionary with structure {"locked": {"profile_name": "backup_path"}}
    """
    global _locked_cache, _cache_loaded
    
    if _cache_loaded:
        return _locked_cache.copy()
    
    locked_data = {"locked": {}}
    
    if os.path.exists(LOCKED_BACKUPS_FILE_PATH):
        try:
            with open(LOCKED_BACKUPS_FILE_PATH, 'r', encoding='utf-8') as f:
                locked_data = json.load(f)
            
            if not isinstance(locked_data, dict):
                logging.warning(f"Locked backups file '{LOCKED_BACKUPS_FILE_PATH}' does not contain a valid dictionary. Reset.")
                locked_data = {"locked": {}}
            
            # Ensure "locked" key exists
            if "locked" not in locked_data:
                locked_data["locked"] = {}
            
            # Auto-prune stale entries and rewrite if necessary
            cleaned = _prune_stale_locks(locked_data)
            if cleaned != locked_data:
                try:
                    os.makedirs(os.path.dirname(LOCKED_BACKUPS_FILE_PATH), exist_ok=True)
                    with open(LOCKED_BACKUPS_FILE_PATH, 'w', encoding='utf-8') as wf:
                        json.dump(cleaned, wf, indent=4, ensure_ascii=False)
                    removed_count = len(locked_data.get("locked", {})) - len(cleaned.get("locked", {}))
                    logging.info(f"Pruned locked backups file: removed {removed_count} stale entries.")
                    locked_data = cleaned
                except Exception as e_rewrite:
                    logging.warning(f"Unable to rewrite pruned locked backups file: {e_rewrite}")
            
            logging.info(f"Loaded {len(locked_data.get('locked', {}))} locked backups from '{LOCKED_BACKUPS_FILE_PATH}'.")
            
        except json.JSONDecodeError:
            logging.warning(f"Locked backups file '{LOCKED_BACKUPS_FILE_PATH}' is corrupted or empty. Reset.")
            locked_data = {"locked": {}}
        except Exception as e:
            logging.error(f"Error loading locked backups from '{LOCKED_BACKUPS_FILE_PATH}': {e}")
            locked_data = {"locked": {}}
    else:
        logging.info(f"Locked backups file '{LOCKED_BACKUPS_FILE_PATH}' not found. Starting with empty list.")
    
    _locked_cache = locked_data.copy()
    _cache_loaded = True
    return locked_data


def save_locked_backups(locked_dict: dict) -> bool:
    """
    Save the locked backups dictionary to LOCKED_BACKUPS_FILE_PATH.
    
    Args:
        locked_dict: Dictionary with structure {"locked": {"profile_name": "backup_path"}}
        
    Returns:
        True if saving succeeds, False otherwise
    """
    global _locked_cache
    
    if not isinstance(locked_dict, dict):
        logging.error("Attempt to save invalid locked backups data (not a dictionary).")
        return False
    
    try:
        # Clean before saving
        data_to_write = _prune_stale_locks(locked_dict)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(LOCKED_BACKUPS_FILE_PATH), exist_ok=True)
        
        with open(LOCKED_BACKUPS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_to_write, f, indent=4, ensure_ascii=False)
        
        logging.info(f"Saved {len(data_to_write.get('locked', {}))} locked backups to '{LOCKED_BACKUPS_FILE_PATH}'.")
        _locked_cache = data_to_write.copy()
        
        # Mirror only when NOT in portable mode
        try:
            do_mirror = True
            try:
                import settings_manager as _smirror
                if _smirror.is_portable_mode():
                    do_mirror = False
            except Exception:
                pass
            
            if do_mirror:
                rotation = 0
                try:
                    import settings_manager as _sm4
                    settings, _ = _sm4.load_settings()
                    rotation = int(settings.get("mirror_rotation_keep", 0))
                except Exception:
                    rotation = 0
                
                # Use core_logic helper to mirror into backup root
                try:
                    import core_logic
                    core_logic._mirror_json_to_backup_root("locked_backups.json", data_to_write, rotation=rotation)
                except Exception as e_core:
                    logging.warning(f"Mirror locked backups to backup root failed: {e_core}")
        except Exception as e_mirror:
            logging.warning(f"Unable to mirror locked backups to backup root: {e_mirror}")
        
        return True
    except Exception as e:
        logging.error(f"Error saving locked backups to '{LOCKED_BACKUPS_FILE_PATH}': {e}")
        return False


def is_backup_locked(backup_path: str) -> bool:
    """
    Check if a specific backup file is locked.
    
    Args:
        backup_path: Full path to the backup file
        
    Returns:
        True if the backup is locked, False otherwise
    """
    if not backup_path:
        return False
    
    locked_data = load_locked_backups()
    locked_entries = locked_data.get("locked", {})
    
    # Normalize the path for comparison
    normalized_path = os.path.normcase(os.path.normpath(backup_path))
    
    for profile_name, locked_path in locked_entries.items():
        if os.path.normcase(os.path.normpath(locked_path)) == normalized_path:
            return True
    
    return False


def get_locked_backup_for_profile(profile_name: str) -> str | None:
    """
    Get the locked backup path for a specific profile.
    
    Args:
        profile_name: Name of the profile
        
    Returns:
        Full path to the locked backup, or None if no backup is locked
    """
    if not profile_name:
        return None
    
    locked_data = load_locked_backups()
    locked_entries = locked_data.get("locked", {})
    
    return locked_entries.get(profile_name)


def has_locked_backup(profile_name: str) -> bool:
    """
    Check if a profile has a locked backup.
    
    Args:
        profile_name: Name of the profile
        
    Returns:
        True if the profile has a locked backup, False otherwise
    """
    return get_locked_backup_for_profile(profile_name) is not None


def lock_backup(profile_name: str, backup_path: str) -> tuple[bool, str]:
    """
    Lock a backup for a profile.
    
    Each profile can have at most one locked backup. If there's already a locked
    backup for this profile, the operation will fail.
    
    Args:
        profile_name: Name of the profile
        backup_path: Full path to the backup file to lock
        
    Returns:
        Tuple (success: bool, message: str)
    """
    if not profile_name or not backup_path:
        return False, "Invalid profile name or backup path."
    
    if not os.path.isfile(backup_path):
        return False, f"Backup file does not exist: {backup_path}"
    
    locked_data = load_locked_backups()
    locked_entries = locked_data.get("locked", {})
    
    # Check if this profile already has a locked backup
    existing_lock = locked_entries.get(profile_name)
    if existing_lock:
        if os.path.normcase(os.path.normpath(existing_lock)) == os.path.normcase(os.path.normpath(backup_path)):
            return True, "This backup is already locked."
        else:
            return False, f"Profile '{profile_name}' already has a locked backup. Unlock it first."
    
    # Set the read-only attribute on the file
    if not _set_file_readonly(backup_path, readonly=True):
        return False, "Failed to set read-only attribute on the backup file."
    
    # Add to locked backups
    locked_entries[profile_name] = backup_path
    locked_data["locked"] = locked_entries
    
    if save_locked_backups(locked_data):
        logging.info(f"Locked backup for profile '{profile_name}': {backup_path}")
        return True, f"Backup locked successfully."
    else:
        # Rollback the read-only attribute if saving failed
        _set_file_readonly(backup_path, readonly=False)
        return False, "Failed to save locked backups data."


def unlock_backup(profile_name: str, backup_path: str = None) -> tuple[bool, str]:
    """
    Unlock a backup for a profile.
    
    Args:
        profile_name: Name of the profile
        backup_path: Full path to the backup file (optional, will use stored path if not provided)
        
    Returns:
        Tuple (success: bool, message: str)
    """
    if not profile_name:
        return False, "Invalid profile name."
    
    locked_data = load_locked_backups()
    locked_entries = locked_data.get("locked", {})
    
    # Get the stored locked backup path
    stored_path = locked_entries.get(profile_name)
    if not stored_path:
        return True, "No locked backup found for this profile."
    
    # If backup_path is provided, verify it matches the stored path
    if backup_path and os.path.normcase(os.path.normpath(backup_path)) != os.path.normcase(os.path.normpath(stored_path)):
        return False, "Provided backup path does not match the locked backup."
    
    # Use the stored path
    actual_path = stored_path
    
    # Remove the read-only attribute (if the file still exists)
    if os.path.isfile(actual_path):
        if not _set_file_readonly(actual_path, readonly=False):
            logging.warning(f"Failed to remove read-only attribute from {actual_path}, but continuing with unlock.")
    
    # Remove from locked backups
    del locked_entries[profile_name]
    locked_data["locked"] = locked_entries
    
    if save_locked_backups(locked_data):
        logging.info(f"Unlocked backup for profile '{profile_name}': {actual_path}")
        return True, "Backup unlocked successfully."
    else:
        return False, "Failed to save locked backups data."


def remove_profile_locks(profile_name: str) -> bool:
    """
    Remove all lock entries for a profile (when a profile is deleted).
    
    Args:
        profile_name: Name of the profile
        
    Returns:
        True if successful, False otherwise
    """
    if not profile_name:
        return True
    
    locked_data = load_locked_backups()
    locked_entries = locked_data.get("locked", {})
    
    if profile_name in locked_entries:
        # Try to remove read-only attribute first
        backup_path = locked_entries[profile_name]
        if os.path.isfile(backup_path):
            _set_file_readonly(backup_path, readonly=False)
        
        del locked_entries[profile_name]
        locked_data["locked"] = locked_entries
        logging.info(f"Removed lock entry for deleted profile '{profile_name}'.")
        return save_locked_backups(locked_data)
    
    return True


def invalidate_cache():
    """Force reload of locked backups data from disk on next access."""
    global _locked_cache, _cache_loaded
    _locked_cache = {}
    _cache_loaded = False
    logging.debug("Locked backups cache invalidated.")
