# emulator_utils/rpcs3_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import struct
import re # Keep re import even if not used in simplified version
from collections import namedtuple
from .sfo_utils import parse_param_sfo # <-- Import the shared function

log = logging.getLogger(__name__)

# Structure definitions for PARAM.SFO parsing - Keep these if used elsewhere, otherwise remove?
# Let's keep them for now as get_rpcs3_saves_path might implicitly rely on their existence
# or future code might. If they become truly unused, we can remove later.
SFOHeader = namedtuple('SFOHeader', ['magic', 'version', 'key_table_start', 'data_table_start', 'num_entries'])
SFOEntry = namedtuple('SFOEntry', ['key_offset', 'data_fmt', 'data_len', 'data_max_len', 'data_offset'])

# Restore the flexible version that checks portable/standard and scans user IDs
def get_rpcs3_saves_path(executable_path: str | None = None) -> str | None:
    """Determines the RPCS3 save directory path, checking portable and standard locations."""
    log.debug(f"Determining RPCS3 saves path. Executable: {executable_path}")

    base_paths_to_check = []

    # 1. Identify potential base directories (portable and standard)
    portable_base_dir = None
    if executable_path:
        # Check if executable_path is a file or directory
        if os.path.isfile(executable_path):
            # If it's a file (normal case), get the directory containing the executable
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            # If it's already a directory, use it directly
            exe_dir = executable_path
        else:
            # If it's neither a file nor a directory, log a warning
            log.warning(f"Provided executable_path is neither a file nor a directory: {executable_path}")
            exe_dir = None
            
        # If we have a valid directory, check for the portable RPCS3 structure
        if exe_dir:
            portable_base_dir = os.path.join(exe_dir, "dev_hdd0", "home")
            if os.path.isdir(portable_base_dir):
                log.debug(f"Found potential portable base home: {portable_base_dir}")
                base_paths_to_check.append(portable_base_dir)
            else:
                log.debug(f"Portable base home not found or not a directory: {portable_base_dir}")

    standard_base_dir = None
    system = platform.system()
    user_home = os.path.expanduser("~")
    standard_config_root = None
    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            standard_config_root = os.path.join(appdata, "rpcs3")
    elif system == "Linux":
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(user_home, ".config"))
        standard_config_root = os.path.join(xdg_config_home, "rpcs3")
    elif system == "Darwin":
        standard_config_root = os.path.join(user_home, "Library", "Application Support", "rpcs3")

    if standard_config_root:
        standard_base_dir = os.path.join(standard_config_root, "dev_hdd0", "home")
        # Avoid adding duplicates if portable and standard point to the same place
        if os.path.isdir(standard_base_dir) and standard_base_dir not in base_paths_to_check:
            log.debug(f"Found potential standard base home: {standard_base_dir}")
            base_paths_to_check.append(standard_base_dir)
        elif standard_base_dir in base_paths_to_check:
             log.debug(f"Standard base home already checked (same as portable?): {standard_base_dir}")
        else:
            log.debug(f"Standard base home not found or not a directory: {standard_base_dir}")
    else:
        log.debug(f"Could not determine standard config root for OS '{system}'.")

    if not base_paths_to_check:
        log.error("Could not find any potential RPCS3 base home directory (portable or standard)." )
        return None

    # 2. Scan identified base directories for savedata
    for base_home_dir in base_paths_to_check:
        log.debug(f"Scanning base home directory: {base_home_dir}")

        # First, check the default user ID '00000001'
        default_save_path = os.path.join(base_home_dir, "00000001", "savedata")
        log.debug(f"Checking default save path: {default_save_path}")
        if os.path.isdir(default_save_path):
            log.info(f"Found RPCS3 save directory (default user): {default_save_path}")
            return default_save_path
        else:
            log.debug(f"Default save path not found or not a directory.")

        # If default not found, scan for other potential user IDs (8 digits)
        log.debug(f"Default user saves not found in {base_home_dir}, scanning for other user IDs...")
        try:
            for item_name in os.listdir(base_home_dir):
                item_path = os.path.join(base_home_dir, item_name)
                # Check if it's a directory and looks like an 8-digit user ID
                if os.path.isdir(item_path) and re.match(r'^\d{8}$', item_name):
                    log.debug(f"Found potential user ID folder: {item_name}")
                    user_save_path = os.path.join(item_path, "savedata")
                    log.debug(f"Checking save path for user {item_name}: {user_save_path}")
                    if os.path.isdir(user_save_path):
                        log.info(f"Found RPCS3 save directory (user {item_name}): {user_save_path}")
                        return user_save_path
                    else:
                        log.debug(f"Save path for user {item_name} not found or not a directory.")
            log.debug(f"No other user ID save directories found in {base_home_dir}.")
        except OSError as e:
            log.warning(f"Error scanning directory {base_home_dir} for user IDs: {e}")
        except Exception as e:
             log.error(f"Unexpected error scanning {base_home_dir}: {e}", exc_info=True)

    # If no path was found after checking all bases
    log.error("Could not determine RPCS3 save directory after checking all potential locations.")
    return None


def find_rpcs3_profiles(executable_path: str | None = None) -> list[dict]:
    """Finds RPCS3 game save profiles by scanning the savedata directory determined by get_rpcs3_saves_path."""
    log.info("Attempting to find RPCS3 profiles...")
    log.debug(f"find_rpcs3_profiles received executable_path: {executable_path}")
    savedata_dir = get_rpcs3_saves_path(executable_path)

    if not savedata_dir:
        log.error("Cannot find RPCS3 profiles: Save directory location is unknown.")
        return []

    log.info(f"Scanning RPCS3 savedata directory: {savedata_dir}")
    profiles = []
    processed_base_ids = set()

    try:
        for item_name in os.listdir(savedata_dir):
            item_path = os.path.join(savedata_dir, item_name)
            if os.path.isdir(item_path):
                # Extract base game ID (e.g., BCES00065 from BCES00065_NDI...)
                # This regex assumes IDs like XXXXYYYYY...
                match = re.match(r'^([A-Z]{4}\d{5})', item_name)
                if not match:
                    log.debug(f"Skipping directory with non-standard name format: {item_name}")
                    continue

                base_game_id = match.group(1)

                # If we haven't processed this base game ID yet
                if base_game_id not in processed_base_ids:
                    sfo_path = os.path.join(item_path, 'PARAM.SFO')
                    if os.path.isfile(sfo_path):
                        game_title = parse_param_sfo(sfo_path)
                        profile_name = game_title if game_title else base_game_id # Fallback to ID

                        profiles.append({
                            'id': base_game_id, # Use the base ID
                            'paths': [item_path], # Changed 'path' to 'paths' and made it a list
                            'name': profile_name
                        })
                        processed_base_ids.add(base_game_id) # Mark as processed
                    else:
                        log.debug(f"No PARAM.SFO found in potential profile dir: {item_path}")
                # else: # Already processed this base ID, skip subsequent saves (like _SAVE1, _SAVE2)
                #    log.debug(f"Skipping already processed base ID {base_game_id} for path {item_path}")

    except OSError as e:
        log.error(f"Error scanning RPCS3 savedata directory '{savedata_dir}': {e}")
        return []
    except Exception as e:
         log.error(f"Unexpected error scanning RPCS3 savedata directory '{savedata_dir}': {e}", exc_info=True)
         return [] # Return empty on unexpected errors too

    log.info(f"Found {len(profiles)} unique RPCS3 profiles.") # Log unique count
    return profiles
