# emulator_utils/ares_manager.py
# -*- coding: utf-8 -*-

"""
Manager for the ares multi-system emulator.

ares is a multi-system emulator that stores its configuration in a BML file
called 'settings.bml' located alongside the executable.

Save files are organized as follows:
  - If the user has configured a custom Saves path in ares settings (Paths > Saves),
    saves are stored in: <custom_saves_path>/<SystemName>/<romname>.sav (and similar)
  - If no custom path is set, saves are placed alongside the ROM files themselves.
    In this case, we CANNOT determine where saves are, so we return None and the
    UI should inform the user to configure the Saves path in ares.

The settings.bml file uses BML (Binary Markup Language) format. The relevant key is:
    Paths
      Saves: <path>

If the Saves value is empty or missing, no custom path has been set.
"""

import os
import logging
import glob
import re
from typing import Optional
from utils import sanitize_profile_display_name

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Known ares system folder names.
# These are the ACTUAL folder names ares creates in the saves directory,
# verified from settings.bml internal section names and real save files.
# NOTE: ares uses concatenated names without spaces for many systems
# (e.g. "GameBoy" not "Game Boy"), but for some it uses spaces.
# The list below includes BOTH styles so we catch all real directories.
ARES_SYSTEMS = [
    # Main systems - names taken from settings.bml sections
    # (these are the internal IDs ares uses for folder creation)
    "Atari2600",
    "ColecoVision",
    "MyVision",
    "Famicom",
    "FamicomDiskSystem",
    "Game Boy",          # ares uses "Game Boy" with a space (verified)
    "Game Boy Color",    # May also exist as separate folder
    "GameBoy",           # Alternate form (from settings.bml section name)
    "GameBoyColor",      # Alternate form (from settings.bml section name)
    "GameBoyAdvance",
    "Game Boy Advance",
    "MegaDrive",
    "Mega Drive",
    "Mega32X",
    "MegaCD",
    "MegaCD32X",
    "MasterSystem",
    "Master System",
    "GameGear",
    "Game Gear",
    "MSX",
    "MSX2",
    "Nintendo 64",
    "Nintendo64",
    "Nintendo64DD",
    "NeoGeoAES",
    "Neo Geo AES",
    "NeoGeoMVS",
    "Neo Geo MVS",
    "NeoGeoPocket",
    "Neo Geo Pocket",
    "NeoGeoPocketColor",
    "Neo Geo Pocket Color",
    "PCEngine",
    "PC Engine",
    "PCEngineCD",
    "PC Engine CD",
    "SuperGrafx",
    "SuperGrafxCD",
    "PlayStation",
    "Saturn",
    "SuperFamicom",
    "Super Famicom",
    "SG-1000",
    "SC-3000",
    "WonderSwan",
    "WonderSwanColor",
    "WonderSwan Color",
    "PocketChallengeV2",
    "Pocket Challenge V2",
    "ZXSpectrum",
    "ZX Spectrum",
    "ZXSpectrum128",
    "ZX Spectrum 128",
]

# Save file extensions commonly used by ares across different systems.
# IMPORTANT: Verified extensions from real save files:
#   - .ram for Game Boy / Game Boy Color battery saves
#   - .card for PlayStation memory cards (NOT .mcd like other emulators!)
#   - .sav, .srm, .eep, .fla, .mpk for other systems
ARES_SAVE_EXTENSIONS = [
    ".sav", ".srm", ".ram", ".eep", ".fla", ".sra",
    ".mpk", ".nv", ".rtc", ".bak",
    # PlayStation memory card (ares uses .card, NOT .mcd!)
    ".card",
    # Include .mcd/.mcr as fallback in case different ares versions use them
    ".mcd", ".mcr",
]


def _parse_bml_saves_path(settings_path: str) -> Optional[str]:
    """
    Parses the ares settings.bml file to extract the Saves path.
    
    BML format uses indentation-based nesting. The relevant structure is:
        Paths
          Saves: <path>
    
    Args:
        settings_path: Full path to the settings.bml file.
    
    Returns:
        The saves path string if found and non-empty, None otherwise.
    """
    if not os.path.isfile(settings_path):
        log.warning(f"ares settings.bml not found at: {settings_path}")
        return None
    
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (IOError, OSError) as e:
        log.error(f"Error reading ares settings.bml: {e}")
        return None
    except UnicodeDecodeError:
        # Try with latin-1 as fallback
        try:
            with open(settings_path, 'r', encoding='latin-1') as f:
                content = f.read()
        except Exception as e2:
            log.error(f"Error reading ares settings.bml with fallback encoding: {e2}")
            return None

    # Parse the BML content to find Paths/Saves
    # BML format: indentation-based, key: value or key\n  subkey: value
    # We look for a line matching "Saves:" under the "Paths" section
    in_paths_section = False
    paths_indent = -1
    
    for line in content.splitlines():
        stripped = line.strip()
        
        # Calculate indentation level
        indent = len(line) - len(line.lstrip())
        
        # Check if we're entering the Paths section
        if stripped == "Paths" or stripped.startswith("Paths "):
            in_paths_section = True
            paths_indent = indent
            continue
        
        if in_paths_section:
            # If we encounter a line at the same or lower indent level as Paths,
            # we've left the Paths section
            if indent <= paths_indent and stripped:
                in_paths_section = False
                continue
            
            # Look for "Saves:" or "Saves: <path>"
            if stripped.startswith("Saves:") or stripped.startswith("Saves "):
                # Extract the value after "Saves:" or "Saves "
                saves_value = ""
                if ":" in stripped:
                    saves_value = stripped.split(":", 1)[1].strip()
                elif " " in stripped:
                    saves_value = stripped.split(" ", 1)[1].strip()
                
                if saves_value:
                    # Normalize the path
                    saves_value = saves_value.replace("\\", "/").rstrip("/")
                    # Convert to OS-native path
                    saves_value = os.path.normpath(saves_value)
                    log.info(f"Found ares Saves path in settings.bml: {saves_value}")
                    return saves_value
                else:
                    log.info("ares Saves path is empty in settings.bml (saves go alongside ROMs).")
                    return None
    
    # If we didn't find a Saves key at all, it's treated as empty/default
    log.info("No 'Saves' key found in ares settings.bml. Saves path is not configured.")
    return None


def _find_settings_bml(executable_path: str | None = None) -> Optional[str]:
    """
    Finds the settings.bml file for ares.
    
    Priority:
    1. In the same directory as the executable (portable mode)
    2. In standard OS-specific locations
    
    Args:
        executable_path: Path to the ares executable or its directory.
    
    Returns:
        Full path to settings.bml if found, None otherwise.
    """
    candidates = []
    
    # 1. Check near executable (portable)
    if executable_path:
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        else:
            exe_dir = None
        
        if exe_dir:
            portable_settings = os.path.join(exe_dir, "settings.bml")
            candidates.append(portable_settings)
            log.debug(f"Checking for portable ares settings.bml: {portable_settings}")
    
    # 2. Standard OS-specific locations
    import platform
    system = platform.system()
    user_home = os.path.expanduser("~")
    
    if system == "Windows":
        # On Windows, ares stores settings in the local AppData folder
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            candidates.append(os.path.join(local_appdata, "ares", "settings.bml"))
        appdata = os.getenv("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "ares", "settings.bml"))
    elif system == "Linux":
        # Standard XDG paths
        xdg_config = os.getenv("XDG_CONFIG_HOME", os.path.join(user_home, ".config"))
        candidates.append(os.path.join(xdg_config, "ares", "settings.bml"))
        xdg_data = os.getenv("XDG_DATA_HOME", os.path.join(user_home, ".local", "share"))
        candidates.append(os.path.join(xdg_data, "ares", "settings.bml"))
    elif system == "Darwin":  # macOS
        candidates.append(os.path.join(user_home, "Library", "Application Support", "ares", "settings.bml"))
    
    # Check each candidate
    for candidate in candidates:
        if os.path.isfile(candidate):
            log.info(f"Found ares settings.bml at: {candidate}")
            return candidate
        else:
            log.debug(f"ares settings.bml not found at: {candidate}")
    
    log.warning("Could not find ares settings.bml in any standard location.")
    return None


def _scan_save_directory(saves_path: str) -> list[dict]:
    """
    Scans the ares saves directory for save files organized by system.
    
    Expected structure:
        <saves_path>/
            <SystemName>/
                <game_name>.sav
                <game_name>.srm
                ...
    
    Args:
        saves_path: The root saves directory path.
    
    Returns:
        List of profile dicts.
    """
    profiles = []
    seen_ids = set()  # Avoid duplicates
    
    if not os.path.isdir(saves_path):
        log.warning(f"ares saves directory does not exist: {saves_path}")
        return profiles
    
    log.info(f"Scanning ares saves directory: {saves_path}")
    
    # Build a set of known system folder names (lowercased) for fast filtering.
    # This is important because the saves path may be the emulator root directory,
    # and we don't want to scan unrelated folders like Database, Shaders, etc.
    _known_systems_lower = {s.lower() for s in ARES_SYSTEMS}
    
    try:
        # Walk through the saves directory
        # First level: system directories
        for entry in os.listdir(saves_path):
            system_dir = os.path.join(saves_path, entry)
            
            if not os.path.isdir(system_dir):
                # Could be a save file at root level too
                if os.path.isfile(system_dir):
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in ARES_SAVE_EXTENSIONS:
                        base_name = os.path.splitext(entry)[0]
                        profile_id = f"ares_{base_name.lower()}"
                        if profile_id not in seen_ids:
                            seen_ids.add(profile_id)
                            display_name = sanitize_profile_display_name(base_name)
                            profiles.append({
                                'id': profile_id,
                                'name': display_name,
                                'paths': [system_dir],
                                'emulator': 'ares',
                                'system': 'Unknown'
                            })
                continue
            
            # Only scan directories that match known ares system names.
            # This avoids scanning unrelated emulator directories (Database, Shaders, etc.)
            # when the saves path is set to the emulator root directory.
            if entry.lower() not in _known_systems_lower:
                log.debug(f"Skipping non-system directory: {entry}")
                continue
            
            system_name = entry  # e.g. "Game Boy", "PlayStation", etc.
            log.debug(f"Scanning ares system directory: {system_name}")
            
            # Group save files by game name (base name without extension)
            game_saves = {}  # game_name -> list of file paths
            
            try:
                for save_file in os.listdir(system_dir):
                    save_path = os.path.join(system_dir, save_file)
                    
                    if not os.path.isfile(save_path):
                        continue
                    
                    ext = os.path.splitext(save_file)[1].lower()
                    if ext in ARES_SAVE_EXTENSIONS:
                        game_name = os.path.splitext(save_file)[0]
                        if game_name not in game_saves:
                            game_saves[game_name] = []
                        game_saves[game_name].append(save_path)
                
            except OSError as e:
                log.error(f"Error scanning ares system directory '{system_dir}': {e}")
                continue
            
            # Create a profile for each game
            for game_name, save_files in game_saves.items():
                # Create a unique ID using system + game name
                safe_system = re.sub(r'[^a-zA-Z0-9]', '_', system_name).lower()
                safe_game = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', game_name).lower()
                profile_id = f"ares_{safe_system}_{safe_game}"
                
                if profile_id in seen_ids:
                    log.debug(f"Skipping duplicate profile ID: {profile_id}")
                    continue
                seen_ids.add(profile_id)
                
                # Display name: "GameName (SystemName)"
                display_name = sanitize_profile_display_name(game_name)
                display_name_with_system = f"{display_name} ({system_name})"
                
                profile = {
                    'id': profile_id,
                    'name': display_name_with_system,
                    'paths': sorted(save_files),  # All save files for this game
                    'emulator': 'ares',
                    'system': system_name
                }
                profiles.append(profile)
                log.debug(f"  Added ares profile: ID='{profile_id}', Name='{display_name_with_system}', "
                         f"Files={len(save_files)}")
    
    except OSError as e:
        log.error(f"Error scanning ares saves directory '{saves_path}': {e}")
    
    return profiles


def find_ares_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds ares save files by reading the settings.bml configuration.
    
    This function:
    1. Locates the settings.bml file (near the executable or in standard paths)
    2. Parses the Saves path from settings.bml
    3. If no save path is configured, returns None (UI should warn the user)
    4. Otherwise, scans the saves directory for save files organized by system
    
    Args:
        executable_path: Optional path to the ares executable or its directory.
                        Used to locate settings.bml in portable mode.
    
    Returns:
        List of profile dicts if saves directory is configured and found.
        None if saves path is not configured (saves go alongside ROMs)
        or if settings.bml cannot be found.
    """
    log.info(f"Scanning for ares profiles... Executable path: "
             f"{executable_path if executable_path else 'Not provided'}")
    
    # Step 1: Find settings.bml
    settings_path = _find_settings_bml(executable_path)
    
    if not settings_path:
        log.warning("Could not find ares settings.bml. Cannot determine saves location.")
        # Return special marker to indicate we need user intervention
        return None
    
    # Step 2: Parse the Saves path
    saves_path = _parse_bml_saves_path(settings_path)
    
    if not saves_path:
        # The Saves path is not configured - saves go alongside ROMs
        # We CANNOT determine where those are without knowing ROM locations
        log.warning("ares Saves path is not configured. Saves are stored alongside ROMs. "
                    "User needs to set a custom Saves directory in ares settings.")
        # Return None to signal the UI to show a warning
        return None
    
    # Step 3: Verify the saves path exists
    if not os.path.isdir(saves_path):
        log.warning(f"ares Saves path configured in settings.bml does not exist: {saves_path}")
        # Maybe the user set it but hasn't played a game yet, or the path is wrong
        # Still return None so the UI can handle it
        return None
    
    # Step 4: Scan the saves directory
    profiles = _scan_save_directory(saves_path)
    
    if profiles:
        profiles.sort(key=lambda p: p.get('name', ''))
        log.info(f"Found {len(profiles)} ares profiles across all systems.")
        return profiles
    else:
        log.info("No ares save files found in the configured saves directory.")
        # Return empty list (not None!) — the path IS configured, there just
        # aren't any saves yet.  Returning None would trigger the misleading
        # "Save Path Not Configured" message in the UI.
        return []


def _resolve_ares_saves_path(executable_path: str | None = None) -> Optional[str]:
    """
    Resolves the ares saves directory path.
    
    Returns:
        The saves path string if found, configured, and existing. None otherwise.
    """
    settings_path = _find_settings_bml(executable_path)
    if not settings_path:
        log.warning("Could not find ares settings.bml.")
        return None
    
    saves_path = _parse_bml_saves_path(settings_path)
    if not saves_path:
        log.warning("ares Saves path is not configured.")
        return None
    
    if not os.path.isdir(saves_path):
        log.warning(f"ares Saves path does not exist: {saves_path}")
        return None
    
    return saves_path


def list_ares_systems(executable_path: str | None = None) -> list[dict]:
    """
    List the ares systems (consoles) that have save files.
    
    This is the first step of the two-step flow, analogous to
    RetroArch's list_retroarch_cores(). Each entry contains:
        - id: folder name (e.g. "Game Boy", "PlayStation")
        - name: display name (same as folder name)
        - count: number of save files found
    
    Args:
        executable_path: Optional path to the ares executable or its directory.
    
    Returns:
        List of system dicts sorted by name. Empty list if nothing found.
    """
    saves_path = _resolve_ares_saves_path(executable_path)
    if not saves_path:
        return []
    
    _known_systems_lower = {s.lower() for s in ARES_SYSTEMS}
    systems = []
    
    try:
        for entry in os.listdir(saves_path):
            system_dir = os.path.join(saves_path, entry)
            if not os.path.isdir(system_dir):
                continue
            
            # Only include known ares system folders
            if entry.lower() not in _known_systems_lower:
                continue
            
            # Count save files in this system directory
            count = 0
            try:
                for f in os.listdir(system_dir):
                    if os.path.isfile(os.path.join(system_dir, f)):
                        ext = os.path.splitext(f)[1].lower()
                        if ext in ARES_SAVE_EXTENSIONS:
                            count += 1
            except OSError:
                continue
            
            if count > 0:
                systems.append({
                    'id': entry,
                    'name': entry,
                    'count': count
                })
    except OSError as e:
        log.error(f"Error listing ares systems in '{saves_path}': {e}")
        return []
    
    systems.sort(key=lambda s: s.get('name', '').lower())
    log.info(f"Found {len(systems)} ares systems with saves.")
    return systems


def find_ares_profiles_for_system(
    system_id: str,
    executable_path: str | None = None
) -> list[dict]:
    """
    Find save profiles for a specific ares system (console).
    
    This is the second step of the two-step flow, analogous to
    RetroArch's find_retroarch_profiles(). Returns profiles for the
    selected system only.
    
    Args:
        system_id: The system folder name (e.g. "Game Boy", "PlayStation").
        executable_path: Optional path to the ares executable or its directory.
    
    Returns:
        List of profile dicts for the given system. Empty list if nothing found.
    """
    system_id = (system_id or '').strip()
    if not system_id:
        return []
    
    saves_path = _resolve_ares_saves_path(executable_path)
    if not saves_path:
        return []
    
    system_dir = os.path.join(saves_path, system_id)
    if not os.path.isdir(system_dir):
        log.warning(f"ares system directory does not exist: {system_dir}")
        return []
    
    profiles = []
    game_saves = {}  # game_name -> list of file paths
    
    try:
        for save_file in os.listdir(system_dir):
            save_path = os.path.join(system_dir, save_file)
            if not os.path.isfile(save_path):
                continue
            
            ext = os.path.splitext(save_file)[1].lower()
            if ext in ARES_SAVE_EXTENSIONS:
                game_name = os.path.splitext(save_file)[0]
                if game_name not in game_saves:
                    game_saves[game_name] = []
                game_saves[game_name].append(save_path)
    except OSError as e:
        log.error(f"Error scanning ares system directory '{system_dir}': {e}")
        return []
    
    for game_name, save_files in game_saves.items():
        safe_system = re.sub(r'[^a-zA-Z0-9]', '_', system_id).lower()
        safe_game = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', game_name).lower()
        profile_id = f"ares_{safe_system}_{safe_game}"
        
        display_name = sanitize_profile_display_name(game_name)
        
        profile = {
            'id': profile_id,
            'name': display_name,
            'paths': sorted(save_files),
            'emulator': 'ares',
            'system': system_id
        }
        profiles.append(profile)
        log.debug(f"  ares profile: ID='{profile_id}', Name='{display_name}', Files={len(save_files)}")
    
    profiles.sort(key=lambda p: p.get('name', ''))
    log.info(f"Found {len(profiles)} ares profiles for system '{system_id}'.")
    return profiles


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                       format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                       handlers=[logging.StreamHandler()])

    log.info("--- Running ares Manager Test ---")
    
    # Test with a specific path or None
    # Example: test_path = "D:\\ares-v147\\ares.exe"
    test_path = None
    
    found_profiles = find_ares_profiles(test_path)
    
    if found_profiles is not None:
        print(f"\n--- Found {len(found_profiles)} ares Profiles ---")
        if found_profiles:
            for profile in found_profiles:
                print(f"- ID:     {profile['id']}")
                print(f"  Name:   {profile['name']}")
                print(f"  System: {profile.get('system', 'N/A')}")
                print(f"  Files:  {', '.join(profile['paths'])}")
                print("-" * 40)
        else:
            print("No save files found in the configured saves directory.")
    else:
        print("\nares Saves path is NOT configured.")
        print("The user needs to set a custom Saves directory in ares Settings > Paths > Saves.")
        print("Without this, saves go alongside ROM files and cannot be automatically detected.")
    
    log.info("\nFinished ares_manager.py test run.")
