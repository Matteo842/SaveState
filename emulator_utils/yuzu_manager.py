# emulator_utils/yuzu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# --- Yuzu Specific Helper Functions ---

def parse_nacp(filepath: str):
    """
    Parses a Nintendo Switch control.nacp file to extract the game title.

    Args:
        filepath: The absolute path to the control.nacp file.

    Returns:
        The game title as a string if found, otherwise None.
        Searches for the first non-empty title entry (usually English).
    """
    log.debug(f"Attempting to parse NACP file: {filepath}")
    if not os.path.isfile(filepath):
        log.warning(f"NACP file not found: {filepath}")
        return None

    try:
        with open(filepath, 'rb') as f:
            nacp_data = f.read()

        if len(nacp_data) < 0x4000: # NACP size is 0x4000 bytes
            log.warning(f"NACP file is too small: {len(nacp_data)} bytes in {filepath}")
            return None

        title_offset_start = 0x3000
        title_entry_size = 0x100
        max_title_length = 0x100

        for i in range(16): # Iterate through language entries
            entry_start = title_offset_start + (i * title_entry_size)
            title_bytes = nacp_data[entry_start : entry_start + max_title_length]

            null_terminator_index = title_bytes.find(b'\x00')
            if null_terminator_index == -1:
                title_bytes_clean = title_bytes
            else:
                title_bytes_clean = title_bytes[:null_terminator_index]

            if not title_bytes_clean: # Skip empty entries
                continue

            try:
                title = title_bytes_clean.decode('utf-8').strip()
                if title: # If we found a non-empty title, return it
                    log.debug(f"Found title in NACP entry {i}: '{title}'")
                    return title
            except UnicodeDecodeError:
                log.warning(f"Could not decode title in NACP entry {i} for file {filepath}. Bytes: {title_bytes_clean[:20]}...")

        log.warning(f"No valid title found in any NACP language entry for {filepath}.")
        return None

    except IOError as e:
        log.error(f"Error reading NACP file {filepath}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing NACP file {filepath}: {e}", exc_info=True)
        return None

def get_yuzu_appdata_path(executable_dir=None):
    """Gets the default Yuzu AppData path based on the OS or from the executable directory for portable installations."""
    # Check for portable installation if executable_dir is provided
    if executable_dir:
        # Check if there's a 'nand' directory in the executable directory (portable installation)
        portable_nand_path = os.path.join(executable_dir, "nand")
        if os.path.isdir(portable_nand_path):
            log.info(f"Found Yuzu portable installation at: {executable_dir}")
            return executable_dir
        
        # Check if there's a 'user' directory in the executable directory (another portable structure)
        portable_user_path = os.path.join(executable_dir, "user")
        if os.path.isdir(portable_user_path):
            log.info(f"Found Yuzu portable installation with user directory at: {executable_dir}")
            return executable_dir
    
    # If not portable or portable path not found, proceed with standard paths
    system = platform.system()
    user_home = os.path.expanduser("~")
    path_to_check = None

    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            path_to_check = os.path.join(appdata, "yuzu")
        else:
            log.error("APPDATA environment variable not found on Windows.")
            return None
    elif system == "Linux":
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(user_home, ".config"))
        path_to_check = os.path.join(xdg_config_home, "yuzu")
        flatpak_path = os.path.join(user_home, ".var", "app", "org.yuzu_emu.yuzu", "config", "yuzu")
        if os.path.isdir(flatpak_path):
             log.info(f"Found Yuzu Flatpak config directory: {flatpak_path}")
             return flatpak_path

    elif system == "Darwin": # macOS
        path_to_check = os.path.join(user_home, "Library", "Application Support", "yuzu")
    else:
        log.error(f"Unsupported operating system for Yuzu path detection: {system}")
        return None

    if path_to_check and os.path.isdir(path_to_check):
        log.info(f"Found Yuzu AppData directory: {path_to_check}")
        return path_to_check
    else:
        log.warning(f"Yuzu AppData directory not found at expected location: {path_to_check}")
        if system == "Linux":
             legacy_path = os.path.join(user_home, ".local", "share", "yuzu")
             if os.path.isdir(legacy_path):
                 log.info(f"Found legacy Yuzu data directory: {legacy_path}")
                 return legacy_path
        return None

def get_yuzu_game_title_map(yuzu_appdata_dir: str):
    """
    Loads a map of Title IDs to game names from a local JSON file.
    
    Returns:
        A dictionary mapping uppercase Title IDs to game names.
    """
    title_map = {}
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    json_file_name = "switch_game_list.json"
    json_path = os.path.join(current_script_dir, json_file_name)
    log.info(f"Attempting to load game titles from: {json_path}")

    if not os.path.isfile(json_path):
        log.error(f"Game title JSON file not found at '{json_path}'. Cannot map Yuzu Title IDs to names.")
        return title_map

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Expecting a dictionary like {'games': {'TITLE_ID': 'Name', ...}}
        raw_title_map = data.get("games")
        if isinstance(raw_title_map, dict):
            # Ensure keys are uppercase for consistent lookup
            title_map = {tid.upper(): name for tid, name in raw_title_map.items()}
            log.info(f"Loaded {len(title_map)} game titles from {json_file_name}.")
        else:
             log.error(f"Invalid format in {json_file_name}. Expected a dictionary with a 'games' key containing title mappings.")

    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON from {json_path}: {e}")
    except IOError as e:
        log.error(f"Error reading file {json_path}: {e}")
    except Exception as e:
        log.error(f"Unexpected error loading game titles from {json_path}: {e}", exc_info=True)

    return title_map

def find_yuzu_profiles(executable_dir: str | None = None):
    """
    Finds Yuzu game profiles/saves by scanning the save directory structure.
    NOTE: Currently uses TitleID as the profile name if JSON lookup fails.

    Args:
        executable_dir: Path to Yuzu executable directory for portable installations.

    Returns:
        List of profile dicts: [{'id': TitleID, 'paths': [full_path_to_titleid_folder], 'name': GameName or TitleID}, ...]
    """
    profiles = []
    log.info("Attempting to find Yuzu profiles...")

    yuzu_appdata_dir = get_yuzu_appdata_path(executable_dir)
    if not yuzu_appdata_dir:
        log.error("Could not determine Yuzu AppData path. Cannot find profiles.")
        return profiles

    nand_path = os.path.join(yuzu_appdata_dir, "nand")
    # The user saves are inside the '0' user directory within 'save'
    user_save_root = os.path.join(nand_path, "user", "save", "0000000000000000")

    if not os.path.isdir(user_save_root):
        log.error(f"Yuzu user save root directory not found: {user_save_root}")
        return profiles

    game_title_map = get_yuzu_game_title_map(yuzu_appdata_dir)

    log.info(f"Scanning Yuzu user save directory: {user_save_root}")
    found_profiles_count = 0
    try:
        # Now iterates through the actual user profile ID folders inside '0000000000000000'
        for user_profile_id in os.listdir(user_save_root):
            user_profile_path = os.path.join(user_save_root, user_profile_id)
            if os.path.isdir(user_profile_path):
                log.debug(f"  Scanning user profile ID: {user_profile_id}")
                for title_id_folder in os.listdir(user_profile_path):
                     if len(title_id_folder) == 16 and all(c in '0123456789abcdefABCDEF' for c in title_id_folder):
                        title_id_path = os.path.join(user_profile_path, title_id_folder)
                        if os.path.isdir(title_id_path):
                            title_id_upper = title_id_folder.upper()
                            log.debug(f"    Found potential game save folder: {title_id_upper}")

                            game_name = game_title_map.get(title_id_upper)

                            if not game_name:
                                log.debug(f"      TitleID {title_id_upper} not in JSON map. Looking for NACP...")
                                nacp_path = None
                                for root, _, files in os.walk(title_id_path):
                                     if 'control.nacp' in files:
                                         nacp_path = os.path.join(root, 'control.nacp')
                                         log.debug(f"      Found NACP at: {nacp_path}")
                                         break
                                if nacp_path:
                                     game_name = parse_nacp(nacp_path)

                            if not game_name:
                                game_name = f"Game ({title_id_upper})"
                                log.warning(f"      Could not determine game name for {title_id_upper} from map or NACP. Using fallback.")

                            profile = {
                                'id': title_id_upper,
                                'paths': [title_id_path], # Changed 'path' to 'paths' and made it a list
                                'name': game_name
                            }
                            profiles.append(profile)
                            found_profiles_count += 1

    except OSError as e:
        log.error(f"Error listing Yuzu save directory '{user_save_root}': {e}")
    except Exception as e:
        log.error(f"Unexpected error scanning Yuzu save directory: {e}", exc_info=True)

    log.info(f"Found {found_profiles_count} Yuzu profiles across all user hashes.")
    return profiles
