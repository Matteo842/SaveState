# emulator_utils/vita3k_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def get_vita3k_data_path(executable_path: str | None = None) -> str | None:
    """
    Returns the Vita3K data directory path.
    
    Vita3K stores data in:
    - Windows: %APPDATA%/Vita3K/Vita3K/
    - Linux: ~/.local/share/Vita3K/Vita3K/ or ~/.config/Vita3K/Vita3K/
    - macOS: ~/Library/Application Support/Vita3K/Vita3K/
    
    Portable installations have a 'data' folder next to the executable.
    """
    # Check for portable installation first
    if executable_path:
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        else:
            exe_dir = None
        
        if exe_dir:
            # Check for portable 'data' folder
            portable_data = os.path.join(exe_dir, "data")
            if os.path.isdir(portable_data):
                log.info(f"Found Vita3K portable installation at: {portable_data}")
                return portable_data
            
            # Some portable setups might use Vita3K/data
            portable_vita3k_data = os.path.join(exe_dir, "Vita3K", "data")
            if os.path.isdir(portable_vita3k_data):
                log.info(f"Found Vita3K portable installation at: {portable_vita3k_data}")
                return portable_vita3k_data
    
    # Standard installation paths
    system = platform.system()
    user_home = os.path.expanduser("~")
    paths_to_check = []
    
    if system == "Windows":
        appdata = os.getenv('APPDATA')
        localappdata = os.getenv('LOCALAPPDATA')
        if appdata:
            paths_to_check.append(os.path.join(appdata, "Vita3K", "Vita3K"))
        if localappdata:
            paths_to_check.append(os.path.join(localappdata, "Vita3K", "Vita3K"))
    elif system == "Linux":
        paths_to_check = [
            os.path.join(user_home, ".local", "share", "Vita3K", "Vita3K"),
            os.path.join(user_home, ".config", "Vita3K", "Vita3K"),
            # Flatpak location
            os.path.join(user_home, ".var", "app", "org.vita3k.Vita3K", "data", "Vita3K", "Vita3K"),
        ]
    elif system == "Darwin":  # macOS
        paths_to_check = [
            os.path.join(user_home, "Library", "Application Support", "Vita3K", "Vita3K"),
        ]
    else:
        log.error(f"Unsupported OS for Vita3K: {system}")
        return None
    
    for path in paths_to_check:
        if os.path.isdir(path):
            log.info(f"Found Vita3K data directory: {path}")
            return path
    
    log.warning("Vita3K data directory not found in standard locations")
    return None


def parse_param_sfo_vita(sfo_path: str) -> dict:
    """
    Parse PS Vita param.sfo file to extract game information.
    
    Returns dict with 'title' and 'title_id' if successful.
    """
    try:
        with open(sfo_path, 'rb') as f:
            # Read SFO header
            magic = f.read(4)
            if magic != b'\x00PSF':
                log.warning(f"Invalid SFO magic in {sfo_path}")
                return {}
            
            version = int.from_bytes(f.read(4), 'little')
            key_table_offset = int.from_bytes(f.read(4), 'little')
            data_table_offset = int.from_bytes(f.read(4), 'little')
            entries_count = int.from_bytes(f.read(4), 'little')
            
            entries = []
            for _ in range(entries_count):
                key_offset = int.from_bytes(f.read(2), 'little')
                data_fmt = int.from_bytes(f.read(2), 'little')
                data_len = int.from_bytes(f.read(4), 'little')
                data_max_len = int.from_bytes(f.read(4), 'little')
                data_offset = int.from_bytes(f.read(4), 'little')
                
                entries.append({
                    'key_offset': key_offset,
                    'data_fmt': data_fmt,
                    'data_len': data_len,
                    'data_max_len': data_max_len,
                    'data_offset': data_offset
                })
            
            result = {}
            for entry in entries:
                # Read key
                f.seek(key_table_offset + entry['key_offset'])
                key_bytes = b''
                while True:
                    byte = f.read(1)
                    if byte == b'\x00' or not byte:
                        break
                    key_bytes += byte
                key = key_bytes.decode('utf-8', errors='ignore')
                
                # Read data
                f.seek(data_table_offset + entry['data_offset'])
                data_bytes = f.read(entry['data_len'])
                
                # Parse based on format (0x0204 = utf-8 string, 0x0404 = int)
                if entry['data_fmt'] == 0x0204:  # String
                    value = data_bytes.rstrip(b'\x00').decode('utf-8', errors='ignore')
                elif entry['data_fmt'] == 0x0404:  # Integer
                    value = int.from_bytes(data_bytes[:4], 'little')
                else:
                    value = data_bytes
                
                result[key] = value
            
            return {
                'title': result.get('TITLE', result.get('STITLE', '')),
                'title_id': result.get('TITLE_ID', '')
            }
    except Exception as e:
        log.error(f"Error parsing SFO {sfo_path}: {e}", exc_info=True)
        return {}


def find_vita3k_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds Vita3K save data for installed games.
    
    PS Vita save structure:
    - Apps: ux0/app/TITLEID/
    - Saves: ux0/user/00/savedata/TITLEID/
    
    Returns:
        List of profile dicts: [{'id': TITLEID, 'name': GameName, 'paths': [savedata_path]}, ...]
    """
    profiles = []
    log.info("Attempting to find Vita3K profiles...")
    
    vita3k_data = get_vita3k_data_path(executable_path)
    if not vita3k_data:
        log.error("Could not determine Vita3K data path. Cannot find profiles.")
        return None
    
    # Path to ux0 (virtual memory card)
    # Try common locations to be resilient across portable and standard layouts
    ux0_candidates = []
    # Primary expected location
    ux0_candidates.append(os.path.join(vita3k_data, "ux0"))
    # Some layouts nest an extra Vita3K/Vita3K folder inside the data directory
    ux0_candidates.append(os.path.join(vita3k_data, "Vita3K", "Vita3K", "ux0"))
    # In some portable setups ux0 can be next to the executable directory (sibling of data)
    if executable_path:
        exe_dir = executable_path if os.path.isdir(executable_path) else os.path.dirname(executable_path) if os.path.isfile(executable_path) else None
        if exe_dir:
            ux0_candidates.append(os.path.join(exe_dir, "ux0"))
            # Also handle a nested Vita3K/Vita3K alongside the executable
            ux0_candidates.append(os.path.join(exe_dir, "Vita3K", "Vita3K", "ux0"))

    ux0_path = None
    for candidate in ux0_candidates:
        if candidate and os.path.isdir(candidate):
            ux0_path = candidate
            break

    if not ux0_path:
        # Normal if the emulator has never been run or no memory card was created yet
        log.warning(f"ux0 directory not found in known locations under: {vita3k_data}")
        return []
    
    # Path to save data
    savedata_root = os.path.join(ux0_path, "user", "00", "savedata")
    if not os.path.isdir(savedata_root):
        log.info(f"No savedata directory found: {savedata_root}")
        return []
    
    # Path to apps (to get game names)
    app_root = os.path.join(ux0_path, "app")
    
    log.info(f"Scanning Vita3K savedata directory: {savedata_root}")
    
    try:
        for title_id in os.listdir(savedata_root):
            savedata_path = os.path.join(savedata_root, title_id)
            
            if not os.path.isdir(savedata_path):
                continue
            
            # Validate title ID format (e.g., PCSA00000, PCSB12345)
            if not (len(title_id) == 9 and title_id[:3] in ['PCS', 'NPS', 'VCV']):
                log.debug(f"Skipping non-standard directory: {title_id}")
                continue
            
            game_name = None
            
            # Try to get game name from app directory
            app_path = os.path.join(app_root, title_id)
            if os.path.isdir(app_path):
                # Check for param.sfo in app directory
                param_sfo_app = os.path.join(app_path, "sce_sys", "param.sfo")
                if os.path.isfile(param_sfo_app):
                    log.debug(f"Found param.sfo in app: {param_sfo_app}")
                    sfo_data = parse_param_sfo_vita(param_sfo_app)
                    game_name = sfo_data.get('title')
            
            # If not found, try to get from savedata itself (some games have it)
            if not game_name:
                param_sfo_save = os.path.join(savedata_path, "sce_sys", "param.sfo")
                if os.path.isfile(param_sfo_save):
                    log.debug(f"Found param.sfo in savedata: {param_sfo_save}")
                    sfo_data = parse_param_sfo_vita(param_sfo_save)
                    game_name = sfo_data.get('title')
            
            # Fallback to title ID if no name found
            if not game_name:
                game_name = f"Game ({title_id})"
                log.warning(f"Could not determine game name for {title_id}. Using fallback.")
            
            profile = {
                'id': title_id,
                'name': game_name,
                'paths': [savedata_path]
            }
            profiles.append(profile)
            log.debug(f"Added Vita3K profile: ID='{title_id}', Name='{game_name}', Path='{savedata_path}'")
    
    except OSError as e:
        log.error(f"Error scanning Vita3K savedata directory '{savedata_root}': {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error finding Vita3K profiles: {e}", exc_info=True)
        return None
    
    if profiles:
        log.info(f"Found {len(profiles)} Vita3K profiles.")
        profiles.sort(key=lambda p: p.get('name', ''))
        return profiles
    else:
        log.info("No Vita3K profiles found.")
        return []


# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    found_profiles = find_vita3k_profiles()
    if found_profiles is None:
        print("Vita3K data directory not found.")
    elif found_profiles:
        print(f"Found {len(found_profiles)} Vita3K Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print("No Vita3K profiles found.")

