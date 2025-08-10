# emulator_utils/mgba_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import glob
import configparser
import re

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

def get_mgba_saves_path():
    """Gets the mGBA save directory: checks config savedir, then lastDirectory, then defaults."""
    system = platform.system()
    user_home = os.path.expanduser("~")
    config_dir = None
    default_save_dir = None
    config_save_dir = None
    last_rom_dir = None

    # 1. Determine potential config directory and default save directory
    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            config_dir = os.path.join(appdata, "mGBA")
            default_save_dir = os.path.join(config_dir, "saves")
        else:
            log.error("APPDATA environment variable not found on Windows.")
            return None
    elif system == "Linux":
        config_dir = os.path.join(user_home, ".config", "mgba")
        default_save_dir = os.path.join(config_dir, "saves")
    elif system == "Darwin": # macOS
        config_dir = os.path.join(user_home, "Library", "Application Support", "mgba")
        default_save_dir = os.path.join(config_dir, "saves")
    else:
        log.error(f"Unsupported operating system for mGBA path detection: {system}")
        return None

    # 2. Try reading config.ini for custom save/last ROM directory
    if config_dir:
        config_file_path = os.path.join(config_dir, "config.ini")
        if os.path.isfile(config_file_path):
            log.info(f"Found mGBA config file: {config_file_path}")
            parser = configparser.ConfigParser()
            try:
                parser.read(config_file_path)
                # Check for 'savedir' first (highest priority)
                if parser.has_section('ports.qt') and parser.has_option('ports.qt', 'savedir'):
                    custom_path = parser.get('ports.qt', 'savedir')
                    custom_path = os.path.abspath(os.path.expanduser(custom_path))
                    if os.path.isdir(custom_path):
                        log.info(f"Found custom save directory 'savedir' in config.ini: {custom_path}")
                        config_save_dir = custom_path
                    else:
                        log.warning(f"'savedir' found in config.ini ('{custom_path}') but it's not a valid directory. Ignoring.")
                else:
                    log.info("No 'savedir' option found in config.ini '[ports.qt]'.")

                # If no specific savedir was found/valid, check lastDirectory as fallback
                if not config_save_dir and parser.has_section('ports.qt') and parser.has_option('ports.qt', 'lastDirectory'):
                    rom_path = parser.get('ports.qt', 'lastDirectory')
                    # lastDirectory often points to a file, get the directory part
                    if os.path.isfile(rom_path):
                         rom_path = os.path.dirname(rom_path)
                    rom_path = os.path.abspath(os.path.expanduser(rom_path))
                    if os.path.isdir(rom_path):
                        log.info(f"Found last ROM directory 'lastDirectory' in config.ini: {rom_path}")
                        last_rom_dir = rom_path # Use this path to search for .sav files
                    else:
                        log.warning(f"'lastDirectory' found in config.ini ('{rom_path}') but it's not a valid directory. Ignoring.")
                elif not config_save_dir:
                     log.info("No 'lastDirectory' option found in config.ini '[ports.qt]'.")

            except configparser.Error as e:
                log.error(f"Error parsing mGBA config.ini: {e}")
            except Exception as e:
                 log.error(f"Unexpected error reading mGBA config.ini: {e}", exc_info=True)
        else:
            log.info(f"mGBA config.ini not found at {config_file_path}. Will use default path if it exists.")

    # 3. Return the determined path
    # Prioritize custom path from config if valid
    if config_save_dir:
        return config_save_dir
    
    # Fallback to lastDirectory if it was found and is valid
    if last_rom_dir:
        log.info(f"Using last ROM directory as fallback: {last_rom_dir}")
        return last_rom_dir
    
    # Fallback to default path if it exists
    if default_save_dir and os.path.isdir(default_save_dir):
        log.info(f"Using default mGBA saves directory: {default_save_dir}")
        return default_save_dir
    
    # If neither custom nor default path is valid/found
    log.warning(f"Could not find a valid mGBA save directory (Checked config savedir: '{config_save_dir}', config lastDir: '{last_rom_dir}', Default: '{default_save_dir}').")
    return None

def find_mgba_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds mGBA save files (.sav) in the standard save directory.
    Note: This currently does NOT find saves stored next to ROM files.

    Args:
        executable_path: Optional path, currently ignored as we look in standard folders.

    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'save_name', 'paths': [full_path]}, ...]
    """
    profiles: list[dict] = []
    log.info("Attempting to find mGBA profiles in standard save directory...")

    saves_dir = get_mgba_saves_path()
    if not saves_dir:
        log.warning("Could not determine or find standard mGBA saves directory. Signalling for user prompt.")
        return None

    try:
        # Look for .sav files directly within the saves directory
        search_pattern = os.path.join(saves_dir, "*.sav")
        save_files = glob.glob(search_pattern)

        log.info(f"Found {len(save_files)} .sav files in {saves_dir}")

        for file_path in save_files:
            if os.path.isfile(file_path):
                # Use the filename without extension as both ID and Name initially
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                profile_id = base_name # Keep full name for ID

                # Clean the name for display by removing trailing language codes like (En,Fr,De,...)
                profile_name = re.sub(r'\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$', '', base_name).strip()
                # If cleaning didn't change anything (maybe different pattern), use original
                if not profile_name:
                    profile_name = base_name 

                profile = {
                    'id': profile_id,
                    'name': profile_name, # Use the cleaned name for display
                    'paths': [file_path] # Standard format with list of paths
                }
                profiles.append(profile)
                log.debug(f"  Added mGBA profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")

    except OSError as e:
        log.error(f"Error accessing mGBA saves directory '{saves_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error finding mGBA profiles: {e}", exc_info=True)

    if profiles:
        log.info(f"Found {len(profiles)} mGBA profiles in standard directory.")
        return profiles
    else:
        log.info("No mGBA profiles found. Signalling for user prompt.")
        return None

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    found_profiles = find_mgba_profiles()
    if found_profiles:
        print("Found mGBA Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print("No mGBA profiles found in standard directory.")
