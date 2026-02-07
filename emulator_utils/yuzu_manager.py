# emulator_utils/yuzu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import pickle

from .obfuscation_utils import xor_bytes

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

def get_yuzu_appdata_path(executable_dir=None, is_eden=False):
    """
    Gets the default Yuzu/Citron/Eden AppData path based on the OS or from the executable directory for portable installations.
    
    Args:
        executable_dir: Path to the emulator executable directory for portable installations.
        is_eden: If True, prioritizes Eden's AppData folder but falls back to Yuzu if not found.
    """
    # Check for portable installation if executable_dir is provided
    if executable_dir:
        # Check if there's a 'nand' directory in the executable directory (portable installation)
        portable_nand_path = os.path.join(executable_dir, "nand")
        if os.path.isdir(portable_nand_path):
            log.info(f"Found Yuzu/Citron/Eden portable installation at: {executable_dir}")
            return executable_dir
        
        # Check for Citron's Release/user structure (e.g., E:\Citron\Release\user)
        # where 'user' directory contains nand/saves (like AppData)
        release_path = None
        if executable_dir.endswith("Release"):
            release_path = executable_dir
        else:
            # Check if there's a Release subdirectory
            potential_release_path = os.path.join(executable_dir, "Release")
            if os.path.isdir(potential_release_path):
                release_path = potential_release_path
        
        if release_path:
            release_user_path = os.path.join(release_path, "user")
            if os.path.isdir(release_user_path):
                # Check if this user directory contains nand (Citron structure)
                release_nand_path = os.path.join(release_user_path, "nand")
                if os.path.isdir(release_nand_path):
                    log.info(f"Found Citron portable installation with Release/user directory at: {release_user_path}")
                    return release_user_path  # Return user dir, not Release dir
        
        # Check if there's a 'user' directory in the executable directory (standard portable structure)
        portable_user_path = os.path.join(executable_dir, "user")
        if os.path.isdir(portable_user_path):
            log.info(f"Found Yuzu/Citron/Eden portable installation with user directory at: {executable_dir}")
            return executable_dir
    
    # If not portable or portable path not found, proceed with standard paths
    system = platform.system()
    user_home = os.path.expanduser("~")
    paths_to_check = []

    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            # If Eden is detected, check Eden folder first, then fall back to Yuzu
            if is_eden:
                paths_to_check = [
                    os.path.join(appdata, "eden"),
                    os.path.join(appdata, "yuzu")
                ]
            else:
                # Check for Citron first, then Yuzu
                paths_to_check = [
                    os.path.join(appdata, "citron"),
                    os.path.join(appdata, "yuzu")
                ]
        else:
            log.error("APPDATA environment variable not found on Windows.")
            return None
    elif system == "Linux":
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(user_home, ".config"))
        # If Eden is detected, check Eden locations first
        if is_eden:
            paths_to_check = [
                os.path.join(xdg_config_home, "eden"),
                os.path.join(user_home, ".local", "share", "eden"),
                os.path.join(xdg_config_home, "yuzu"),
                os.path.join(user_home, ".var", "app", "org.yuzu_emu.yuzu", "config", "yuzu"),
                os.path.join(user_home, ".local", "share", "yuzu")
            ]
        else:
            # Check for Citron and Yuzu in various locations
            paths_to_check = [
                os.path.join(xdg_config_home, "citron"),
                os.path.join(xdg_config_home, "yuzu"),
                os.path.join(user_home, ".var", "app", "org.yuzu_emu.yuzu", "config", "yuzu"),
                os.path.join(user_home, ".local", "share", "citron"),
                os.path.join(user_home, ".local", "share", "yuzu")
            ]
    elif system == "Darwin": # macOS
        if is_eden:
            paths_to_check = [
                os.path.join(user_home, "Library", "Application Support", "eden"),
                os.path.join(user_home, "Library", "Application Support", "yuzu")
            ]
        else:
            paths_to_check = [
                os.path.join(user_home, "Library", "Application Support", "citron"),
                os.path.join(user_home, "Library", "Application Support", "yuzu")
            ]
    else:
        log.error(f"Unsupported operating system for Yuzu/Citron/Eden path detection: {system}")
        return None

    # Try each path until we find one that exists
    for path_to_check in paths_to_check:
        if path_to_check and os.path.isdir(path_to_check):
            emulator_name = "Eden" if "eden" in path_to_check.lower() else ("Citron" if "citron" in path_to_check.lower() else "Yuzu")
            log.info(f"Found {emulator_name} AppData directory: {path_to_check}")
            return path_to_check
    
    log.warning(f"Yuzu/Citron/Eden AppData directory not found in any expected location")
    return None

def get_yuzu_game_title_map(yuzu_appdata_dir: str):
    """
    Loads a map of Title IDs to game names from a local JSON file or a pickle file.
    
    Returns:
        A dictionary mapping uppercase Title IDs to game names.
    """
    title_map = {}
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    json_file_name = "switch_game_list.json"
    pkl_file_name = "switch_game_map.pkl"
    json_path = os.path.join(current_script_dir, json_file_name)
    pkl_path = os.path.join(current_script_dir, pkl_file_name)

    log.info(f"Attempting to load game titles from: {json_path} or {pkl_path}")

    loaded_from_json = False
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            raw_data_from_json = json.load(f)
        
        # Expect the actual map to be under the 'games' key
        actual_game_map_from_json = raw_data_from_json.get("games")

        if isinstance(actual_game_map_from_json, dict):
            for title_id, game_name in actual_game_map_from_json.items():
                if isinstance(title_id, str) and isinstance(game_name, str):
                    title_map[title_id.upper()] = game_name
            loaded_from_json = True
            log.info(f"Successfully loaded {len(title_map)} titles from {json_file_name}")
        else:
             log.error(f"Invalid format in {json_file_name}. Expected a 'games' key containing a dictionary mapping.")

    except FileNotFoundError:
        log.info(f"{json_file_name} not found. Attempting to load from {pkl_file_name}.")
    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON from {json_path}: {e}. Attempting to load from {pkl_file_name}.")
    except Exception as e:
        log.error(f"Unexpected error loading titles from {json_path}: {e}. Attempting to load from {pkl_file_name}.")

    if not loaded_from_json:
        try:
            with open(pkl_path, 'rb') as pf:
                obf_map = pickle.load(pf)
            
            for tid, ob_name in obf_map.items():
                try:
                    game_name = xor_bytes(ob_name).decode('utf-8')
                    title_map[tid.upper()] = game_name # Assuming tid is already string and upper
                except UnicodeDecodeError:
                    log.warning(f"Could not decode game name for TID {tid} from {pkl_file_name}. Skipping.")
                except Exception as e_dec:
                    log.warning(f"Error deobfuscating/processing TID {tid} from {pkl_file_name}: {e_dec}. Skipping.")
            log.info(f"Successfully loaded and deobfuscated {len(title_map)} titles from {pkl_file_name}")
        except FileNotFoundError:
            log.error(f"Neither {json_file_name} nor {pkl_file_name} were found in {current_script_dir}.")
        except pickle.UnpicklingError as e_pkl_load:
            log.error(f"Error loading pickle data from {pkl_path}: {e_pkl_load}")
        except Exception as e_pkl:
            log.error(f"Unexpected error loading titles from {pkl_path}: {e_pkl}", exc_info=True)

    if not title_map:
        log.warning(f"Game title map is empty after attempting to load from both JSON and PKL sources.")

    return title_map

def scan_yuzu_save_directory(save_root_dir: str, game_title_map: dict, folder_label: str = ""):
    """
    Scans a Yuzu/Citron/Eden save directory and returns found profiles.
    
    Args:
        save_root_dir: The root save directory to scan (e.g., .../nand/user/save/0000000000000000)
        game_title_map: Dictionary mapping Title IDs to game names
        folder_label: Label to append to game names (e.g., "Yuzu Folder", "Eden Folder")
    
    Returns:
        List of profile dicts
    """
    profiles = []
    found_count = 0
    
    if not os.path.isdir(save_root_dir):
        log.warning(f"Save root directory not found: {save_root_dir}")
        return profiles
    
    log.info(f"Scanning save directory: {save_root_dir}")
    
    try:
        # Iterate through the actual user profile ID folders inside '0000000000000000'
        for user_profile_id in os.listdir(save_root_dir):
            user_profile_path = os.path.join(save_root_dir, user_profile_id)
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

                            # Add folder label to distinguish between Eden and Yuzu folders
                            # User request: Only show label for Yuzu folders. Eden folder (default) should have no label.
                            if folder_label == "Eden Folder":
                                display_name = game_name
                            else:
                                display_name = f"{game_name} ({folder_label})" if folder_label else game_name
                            
                            # Use a unique ID that includes the folder label to avoid deduplication
                            unique_id = f"{title_id_upper}_{folder_label.replace(' ', '_')}" if folder_label else title_id_upper

                            profile = {
                                'id': unique_id,
                                'paths': [title_id_path],
                                'name': display_name,
                                'title_id': title_id_upper,  # Keep original title ID for reference
                                'label': folder_label
                            }
                            profiles.append(profile)
                            found_count += 1

    except OSError as e:
        log.error(f"Error listing save directory '{save_root_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error scanning save directory: {e}", exc_info=True)
    
    log.info(f"Found {found_count} profiles in {save_root_dir}")
    return profiles


def find_yuzu_profiles(executable_dir: str | None = None, is_eden: bool = False):
    """
    Finds Yuzu/Citron/Eden game profiles/saves by scanning the save directory structure.
    For Eden, searches in both Eden and Yuzu folders to find all available saves.
    NOTE: Currently uses TitleID as the profile name if JSON lookup fails.

    Args:
        executable_dir: Path to Yuzu/Citron/Eden executable directory for portable installations.
        is_eden: If True, searches in both Eden and Yuzu folders.

    Returns:
        List of profile dicts: [{'id': unique_id, 'paths': [full_path_to_titleid_folder], 'name': GameName (Folder Label), 'title_id': TitleID}, ...]
    """
    all_profiles = []
    log.info("Attempting to find Yuzu/Citron/Eden profiles...")

    # Get the game title map (only need to load once)
    system = platform.system()
    user_home = os.path.expanduser("~")
    
    # Determine a reference directory for loading the game title map
    reference_dir = executable_dir if executable_dir else user_home
    game_title_map = get_yuzu_game_title_map(reference_dir)

    if is_eden:
        # For Eden, search in both Eden and Yuzu folders
        log.info("Eden detected: Searching in both Eden and Yuzu folders...")
        
        folders_to_check = []
        
        # Check for portable installation first
        if executable_dir:
            portable_nand_path = os.path.join(executable_dir, "nand")
            if os.path.isdir(portable_nand_path):
                log.info(f"Found Eden portable installation at: {executable_dir}")
                folders_to_check.append((executable_dir, "Eden Folder"))
        
        # Add standard Eden and Yuzu paths based on OS
        if system == "Windows":
            appdata = os.getenv('APPDATA')
            if appdata:
                folders_to_check.extend([
                    (os.path.join(appdata, "eden"), "Eden Folder"),
                    (os.path.join(appdata, "yuzu"), "Yuzu Folder")
                ])
        elif system == "Linux":
            xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(user_home, ".config"))
            folders_to_check.extend([
                (os.path.join(xdg_config_home, "eden"), "Eden Folder"),
                (os.path.join(user_home, ".local", "share", "eden"), "Eden Folder"),
                (os.path.join(xdg_config_home, "yuzu"), "Yuzu Folder"),
                (os.path.join(user_home, ".local", "share", "yuzu"), "Yuzu Folder")
            ])
        elif system == "Darwin":  # macOS
            folders_to_check.extend([
                (os.path.join(user_home, "Library", "Application Support", "eden"), "Eden Folder"),
                (os.path.join(user_home, "Library", "Application Support", "yuzu"), "Yuzu Folder")
            ])
        
        # Scan each folder that exists
        for base_path, label in folders_to_check:
            if os.path.isdir(base_path):
                nand_path = os.path.join(base_path, "nand")
                user_save_root = os.path.join(nand_path, "user", "save", "0000000000000000")
                profiles = scan_yuzu_save_directory(user_save_root, game_title_map, label)
                all_profiles.extend(profiles)
        
        if not all_profiles:
            log.warning("No profiles found in either Eden or Yuzu folders.")
    else:
        # For Yuzu/Citron, use the original single-folder logic
        yuzu_appdata_dir = get_yuzu_appdata_path(executable_dir, is_eden=False)
        if not yuzu_appdata_dir:
            log.error("Could not determine Yuzu/Citron AppData path. Cannot find profiles.")
            return all_profiles

        nand_path = os.path.join(yuzu_appdata_dir, "nand")
        user_save_root = os.path.join(nand_path, "user", "save", "0000000000000000")
        
        # Determine folder label based on which emulator was found
        folder_label = ""
        if "citron" in yuzu_appdata_dir.lower():
            folder_label = "Citron Folder"
        elif "yuzu" in yuzu_appdata_dir.lower():
            folder_label = "Yuzu Folder"
        
        all_profiles = scan_yuzu_save_directory(user_save_root, game_title_map, folder_label)

    log.info(f"Found {len(all_profiles)} total Yuzu/Citron/Eden profiles.")
    return all_profiles
