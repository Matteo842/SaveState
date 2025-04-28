# emulator_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
# emulator_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import struct # <-- Aggiunto per parse_imkvdb

# Configure basic logging for this module
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

# --- Emulator Configuration ---
# Maps a keyword found in the executable path to the function that finds its profiles.
EMULATOR_CONFIG = {
    'ryujinx': { # Keyword to check in the target path (lowercase)
        'profile_finder': lambda exec_dir: find_ryujinx_profiles(executable_dir=None), # Function to call
        'name': 'Ryujinx' # Display name
    },
    # Example for future addition:
    # 'rpcs3': {
    #    'profile_finder': lambda: find_rpcs3_profiles(), # Hypothetical function
    #    'name': 'RPCS3'
    # },
}

# --- Ryujinx Specific Helper Functions (INTEGRATED FROM YOUR SCRIPT) ---

def get_ryujinx_appdata_path():
    """Gets the default Ryujinx AppData path based on the OS."""
    system = platform.system()
    user_home = os.path.expanduser("~")
    path_to_check = None # Initialize

    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            path_to_check = os.path.join(appdata, "Ryujinx")
        else:
            log.error("APPDATA environment variable not found on Windows.")
            return None
    elif system == "Linux":
        # Check for Flatpak path first
        flatpak_path = os.path.join(user_home, ".var", "app", "org.ryujinx.Ryujinx", "config", "Ryujinx")
        if os.path.isdir(flatpak_path):
            log.info(f"Found Ryujinx Flatpak config directory: {flatpak_path}")
            return flatpak_path
        # Default Linux path
        path_to_check = os.path.join(user_home, ".config", "Ryujinx")
    elif system == "Darwin": # macOS
        path_to_check = os.path.join(user_home, "Library", "Application Support", "Ryujinx")
    else:
        log.error(f"Unsupported operating system for Ryujinx path detection: {system}")
        return None

    # Check if the derived path exists
    if path_to_check and os.path.isdir(path_to_check):
        log.info(f"Found Ryujinx AppData directory: {path_to_check}")
        return path_to_check
    else:
        log.error(f"Ryujinx AppData directory not found at expected location: {path_to_check}")
        return None

def get_game_title_map(ryujinx_appdata_dir):
    """Scans the Ryujinx games directory to map Title IDs to game names."""
    title_map = {}
    if not ryujinx_appdata_dir:
        log.error("Cannot get game titles: Ryujinx AppData directory is unknown.")
        return title_map

    games_metadata_dir = os.path.join(ryujinx_appdata_dir, "games")
    if not os.path.isdir(games_metadata_dir):
        log.warning(f"Ryujinx games metadata directory not found: {games_metadata_dir}")
        return title_map

    log.info(f"Scanning for game metadata in: {games_metadata_dir}")
    try:
        for title_id in os.listdir(games_metadata_dir):
            title_id_path = os.path.join(games_metadata_dir, title_id)
            if os.path.isdir(title_id_path):
                metadata_file = os.path.join(title_id_path, "gui", "metadata.json")
                if os.path.isfile(metadata_file):
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        game_title = metadata.get("title")
                        if game_title is None or not isinstance(game_title, str) or not game_title.strip():
                            game_title = f"Unknown Title ({title_id})" # Use ID if title is missing/invalid
                        # Store with uppercase TitleID as key
                        title_map[title_id.upper()] = game_title.strip()
                        log.debug(f"  Found metadata: {title_id.upper()} -> {game_title.strip()}")
                    except json.JSONDecodeError:
                        log.warning(f"  Could not decode JSON in {metadata_file}")
                        title_map[title_id.upper()] = f"Invalid Metadata ({title_id})"
                    except Exception as e:
                        log.warning(f"  Error reading {metadata_file}: {e}")
                        title_map[title_id.upper()] = f"Metadata Read Error ({title_id})"
                # else: # Log if metadata is missing (optional)
                    # log.debug(f"  No metadata.json found for {title_id}")
                    # title_map[title_id.upper()] = f"No Metadata ({title_id})"
    except OSError as e:
        log.error(f"Error listing Ryujinx games metadata directory '{games_metadata_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error scanning game metadata: {e}", exc_info=True)

    log.info(f"Found {len(title_map)} game titles from metadata.")
    return title_map

def parse_imkvdb(file_path):
    """Legge il file imkvdb.arc e restituisce una mappa SaveDataId -> TitleId (entrambi uppercase hex)."""
    save_map = {} # SaveDataId (UPPER) -> TitleId (UPPER)
    expected_file_magic = 0x564B4D49  # IMKV
    expected_entry_magic = 0x4E454D49  # IMEN
    expected_key_size = 64
    expected_value_size = 64

    if not os.path.isfile(file_path):
        log.error(f"Save index file imkvdb.arc not found at '{file_path}'. Cannot map saves.")
        return save_map

    log.info(f"Parsing save index file: {file_path}")
    try:
        with open(file_path, 'rb') as f:
            # 1. Read File Header (12 bytes)
            header_data = f.read(12)
            if len(header_data) < 12:
                log.error(f"File imkvdb.arc too short for header ({len(header_data)} bytes).")
                return save_map

            file_magic, _, entry_count = struct.unpack('<IIi', header_data)

            if file_magic != expected_file_magic:
                log.error(f"Invalid file magic number (Expected: {expected_file_magic:X}, Got: {file_magic:X}). File might be corrupt.")
                return save_map

            log.debug(f"Found {entry_count} entries in save index.")

            # 2. Read Entries
            for i in range(entry_count):
                # 2a. Read Entry Header (12 bytes)
                entry_header_data = f.read(12)
                if len(entry_header_data) < 12:
                    log.error(f"Truncated read at entry header {i+1}.")
                    break

                entry_magic, key_size, value_size = struct.unpack('<Iii', entry_header_data)

                # Validate entry magic and sizes
                if entry_magic != expected_entry_magic:
                    log.warning(f"Invalid entry magic {i+1} (Expected: {expected_entry_magic:X}, Got: {entry_magic:X}). Skipping.")
                    bytes_to_skip = expected_key_size + expected_value_size
                    f.read(bytes_to_skip) # Attempt to skip expected size
                    continue

                if key_size != expected_key_size or value_size != expected_value_size:
                    log.warning(f"Invalid entry sizes {i+1} (Key: {key_size} vs {expected_key_size}, Value: {value_size} vs {expected_value_size}). Skipping.")
                    bytes_to_skip = (key_size if 0 < key_size < 1024 else expected_key_size) + \
                                    (value_size if 0 < value_size < 1024 else expected_value_size)
                    f.read(bytes_to_skip) # Attempt to skip based on read/expected sizes
                    continue

                # 2b. Read Key Data (64 bytes)
                key_data = f.read(key_size)
                if len(key_data) < key_size:
                    log.error(f"Truncated read at key data for entry {i+1}.")
                    break

                # 2c. Read Value Data (64 bytes)
                value_data = f.read(value_size)
                if len(value_data) < value_size:
                    log.error(f"Truncated read at value data for entry {i+1}.")
                    break

                try:
                    # Unpack Key (SaveDataAttribute) - only need ProgramId (TitleID)
                    # < Q (ProgramId) ... >
                    program_id = struct.unpack('<Q', key_data[:8])[0] # Read only the first 8 bytes

                    # Unpack Value (SaveDataIndexerValue) - only need SaveDataId
                    # < Q (SaveDataId) ... >
                    save_data_id = struct.unpack('<Q', value_data[:8])[0] # Read only the first 8 bytes

                    # Format IDs as uppercase hex strings (16 chars, zero-padded)
                    save_data_id_hex = f"{save_data_id:016X}"
                    program_id_hex = f"{program_id:016X}"

                    # Add to map
                    save_map[save_data_id_hex] = program_id_hex
                    log.debug(f"  Mapped SaveID {save_data_id_hex} -> TitleID {program_id_hex}")

                except struct.error as e:
                    log.error(f"Error unpacking entry {i+1}: {e}. Skipping.")
                    continue # Skip to the next entry

    except FileNotFoundError:
        # Already handled at the start, but keep for safety
        log.error(f"File imkvdb.arc not found at '{file_path}'.")
    except Exception as e:
        log.error(f"Unexpected error reading imkvdb.arc: {e}", exc_info=True)

    log.info(f"Parsed {len(save_map)} SaveID -> TitleID mappings from index.")
    return save_map

def _get_ryujinx_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx user save directory."""
    if not ryujinx_appdata_dir: return None
    ryujinx_save_path = os.path.join(ryujinx_appdata_dir, 'bis', 'user', 'save')
    log.debug(f"Potential Ryujinx user save directory: {ryujinx_save_path}")
    if os.path.isdir(ryujinx_save_path):
         return ryujinx_save_path
    else:
         log.warning(f"Ryujinx user save directory path derived but does not exist: {ryujinx_save_path}")
         return None

def _get_ryujinx_system_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx system save directory (where imkvdb.arc resides)."""
    if not ryujinx_appdata_dir: return None
    # Path where imkvdb.arc is typically located
    ryujinx_sys_save_path = os.path.join(ryujinx_appdata_dir, 'bis', 'system', 'save', '8000000000000000', '0')
    log.debug(f"Potential Ryujinx system save directory (for index): {ryujinx_sys_save_path}")
    if os.path.isdir(ryujinx_sys_save_path):
         return ryujinx_sys_save_path
    else:
         log.warning(f"Ryujinx system save directory path derived but does not exist: {ryujinx_sys_save_path}")
         return None

# --- Main Profile Finder Function (REWRITTEN) ---

def find_ryujinx_profiles(executable_dir: str | None = None) -> list[dict]:
    """
    Finds Ryujinx game profiles/saves using metadata and the save index.

    Args:
        executable_dir: Ignored for Ryujinx, kept for signature consistency.

    Returns:
        List of profile dicts: [{'id': SaveDataID, 'path': full_save_path, 'name': GameName}, ...]
    """
    log.info("Attempting to find Ryujinx profiles (using metadata and save index)...")
    profiles_data = []

    # 1. Find base AppData directory
    ryujinx_appdata_dir = get_ryujinx_appdata_path()
    if not ryujinx_appdata_dir:
        log.error("Cannot find Ryujinx profiles: AppData directory not found.")
        return []

    # 2. Load TitleID -> Game Name map from metadata
    game_title_map = get_game_title_map(ryujinx_appdata_dir) # Keys are UPPERCASE TitleIDs

    # 3. Load SaveDataID -> TitleID map from imkvdb.arc
    ryujinx_sys_save_dir = _get_ryujinx_system_save_dir(ryujinx_appdata_dir)
    save_to_title_map = {} # Default empty map
    if ryujinx_sys_save_dir:
        imkvdb_path = os.path.join(ryujinx_sys_save_dir, "imkvdb.arc")
        save_to_title_map = parse_imkvdb(imkvdb_path) # Keys are UPPERCASE SaveDataIDs
    else:
        log.error("Cannot map saves to titles: System save directory (for index file) not found.")
        # We can still proceed, but names might be less accurate

    # 4. Find user save directory
    ryujinx_user_save_dir = _get_ryujinx_save_dir(ryujinx_appdata_dir)
    if not ryujinx_user_save_dir:
        log.error("Cannot find Ryujinx profiles: User save directory not found.")
        return []

    # 5. Scan user save directory and build profile list
    try:
        log.info(f"Scanning user save directory for profiles: {ryujinx_user_save_dir}")
        for item_name in os.listdir(ryujinx_user_save_dir):
            item_path = os.path.join(ryujinx_user_save_dir, item_name)
            # Check if it's a directory and looks like a SaveDataID (hex, 16 chars)
            if os.path.isdir(item_path) and len(item_name) == 16:
                try:
                    int(item_name, 16) # Verify it's hex
                    save_data_id = item_name.upper() # Use UPPERCASE SaveDataID

                    # Find TitleID from the save index map
                    title_id = save_to_title_map.get(save_data_id) # Look up using UPPERCASE SaveDataID

                    game_name = f"Unknown Game (SaveID: {save_data_id})" # Default/Fallback name

                    if title_id:
                        # Find Game Name from the metadata map using the TitleID (already UPPERCASE)
                        game_name_from_meta = game_title_map.get(title_id)
                        if game_name_from_meta:
                            game_name = game_name_from_meta # Use name from metadata
                        else:
                            game_name = f"Unknown Title (TitleID: {title_id})" # Fallback if TitleID not in metadata map
                    # else: title_id is None, keep the default "Unknown Game (SaveID: ...)"

                    profile_info = {
                        'id': save_data_id, # The ID is the SaveDataID (folder name)
                        'path': os.path.normpath(item_path), # Full path to the save folder
                        'name': game_name # Resolved game name or fallback
                    }
                    profiles_data.append(profile_info)
                    log.debug(f"Found Ryujinx profile: {profile_info}")

                except ValueError:
                    log.debug(f"Skipping item, name is not a valid 16-char hex ID: {item_name}")
                except Exception as e_inner:
                    log.warning(f"Error processing potential save folder '{item_name}': {e_inner}")

        log.info(f"Found {len(profiles_data)} potential Ryujinx profiles.")

    except OSError as e:
        log.error(f"Error accessing Ryujinx user save directory '{ryujinx_user_save_dir}': {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error scanning user save directory: {e}", exc_info=True)
        return []

    # 6. Sort and return
    profiles_data.sort(key=lambda p: p.get('name', p.get('id', '')))
    return profiles_data

# --- End Ryujinx ---

def detect_and_find_profiles(target_path: str | None) -> tuple[str, list[dict]] | None:
    """
    Detects if the target path belongs to a known emulator and finds its profiles.
    (This function remains largely the same, just calls the updated find_ryujinx_profiles)
    """
    if not target_path or not isinstance(target_path, str):
        return None

    target_path_lower = target_path.lower()
    executable_dir = None
    if os.path.isfile(target_path):
        executable_dir = os.path.dirname(target_path)
        log.debug(f"Derived executable directory (may not be used by all finders): {executable_dir}")

    for keyword, config in EMULATOR_CONFIG.items():
        if keyword in target_path_lower:
            emulator_name = config['name']
            profile_finder = config['profile_finder']
            logging.info(f"Detected known emulator '{emulator_name}' based on target path: {target_path}")
            try:
                # Pass None for Ryujinx, derived path otherwise (as before)
                exec_dir_to_pass = None if keyword == 'ryujinx' else executable_dir
                profiles = profile_finder(exec_dir_to_pass) # Calls the REWRITTEN find_ryujinx_profiles
                return emulator_name, profiles
            except Exception as e:
                log.error(f"Error calling profile finder for {emulator_name}: {e}", exc_info=True)
                return emulator_name, [] # Return empty list on error

    log.debug(f"Target path '{target_path}' did not match any known emulator keywords.")
    return None


# Example usage (for testing purposes)
if __name__ == "__main__":
    # Setup basic logging TO CONSOLE for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.StreamHandler()])

    log.info("Running emulator_manager.py directly for testing (Metadata + Index Mode)...")

    # executable_dir is ignored for Ryujinx testing
    found_profiles = find_ryujinx_profiles(executable_dir=None)

    if found_profiles:
        print("\n--- Found Ryujinx Profiles/Games ---")
        for profile_info in found_profiles:
            print(f"- SaveID: {profile_info['id']}")
            print(f"  Name:   {profile_info['name']}")
            print(f"  Path:   {profile_info['path']}")
            print("-" * 20)
    else:
        print("\nNo Ryujinx profiles found or an error occurred.")

    log.info("Finished emulator_manager.py test run.")
import struct # <-- Aggiunto per parse_imkvdb

# Configure basic logging for this module
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

# --- Emulator Configuration ---
# Maps a keyword found in the executable path to the function that finds its profiles.
EMULATOR_CONFIG = {
    'ryujinx': { # Keyword to check in the target path (lowercase)
        'profile_finder': lambda exec_dir: find_ryujinx_profiles(executable_dir=None), # Function to call
        'name': 'Ryujinx' # Display name
    },
    # Example for future addition:
    # 'rpcs3': {
    #    'profile_finder': lambda: find_rpcs3_profiles(), # Hypothetical function
    #    'name': 'RPCS3'
    # },
}

# --- Ryujinx Specific Helper Functions (INTEGRATED FROM YOUR SCRIPT) ---

def get_ryujinx_appdata_path():
    """Gets the default Ryujinx AppData path based on the OS."""
    system = platform.system()
    user_home = os.path.expanduser("~")
    path_to_check = None # Initialize

    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            path_to_check = os.path.join(appdata, "Ryujinx")
        else:
            log.error("APPDATA environment variable not found on Windows.")
            return None
    elif system == "Linux":
        # Check for Flatpak path first
        flatpak_path = os.path.join(user_home, ".var", "app", "org.ryujinx.Ryujinx", "config", "Ryujinx")
        if os.path.isdir(flatpak_path):
            log.info(f"Found Ryujinx Flatpak config directory: {flatpak_path}")
            return flatpak_path
        # Default Linux path
        path_to_check = os.path.join(user_home, ".config", "Ryujinx")
    elif system == "Darwin": # macOS
        path_to_check = os.path.join(user_home, "Library", "Application Support", "Ryujinx")
    else:
        log.error(f"Unsupported operating system for Ryujinx path detection: {system}")
        return None

    # Check if the derived path exists
    if path_to_check and os.path.isdir(path_to_check):
        log.info(f"Found Ryujinx AppData directory: {path_to_check}")
        return path_to_check
    else:
        log.error(f"Ryujinx AppData directory not found at expected location: {path_to_check}")
        return None

def get_game_title_map(ryujinx_appdata_dir):
    """Scans the Ryujinx games directory to map Title IDs to game names."""
    title_map = {}
    if not ryujinx_appdata_dir:
        log.error("Cannot get game titles: Ryujinx AppData directory is unknown.")
        return title_map

    games_metadata_dir = os.path.join(ryujinx_appdata_dir, "games")
    if not os.path.isdir(games_metadata_dir):
        log.warning(f"Ryujinx games metadata directory not found: {games_metadata_dir}")
        return title_map

    log.info(f"Scanning for game metadata in: {games_metadata_dir}")
    try:
        for title_id in os.listdir(games_metadata_dir):
            title_id_path = os.path.join(games_metadata_dir, title_id)
            if os.path.isdir(title_id_path):
                metadata_file = os.path.join(title_id_path, "gui", "metadata.json")
                if os.path.isfile(metadata_file):
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        game_title = metadata.get("title")
                        if game_title is None or not isinstance(game_title, str) or not game_title.strip():
                            game_title = f"Unknown Title ({title_id})" # Use ID if title is missing/invalid
                        # Store with uppercase TitleID as key
                        title_map[title_id.upper()] = game_title.strip()
                        log.debug(f"  Found metadata: {title_id.upper()} -> {game_title.strip()}")
                    except json.JSONDecodeError:
                        log.warning(f"  Could not decode JSON in {metadata_file}")
                        title_map[title_id.upper()] = f"Invalid Metadata ({title_id})"
                    except Exception as e:
                        log.warning(f"  Error reading {metadata_file}: {e}")
                        title_map[title_id.upper()] = f"Metadata Read Error ({title_id})"
                # else: # Log if metadata is missing (optional)
                    # log.debug(f"  No metadata.json found for {title_id}")
                    # title_map[title_id.upper()] = f"No Metadata ({title_id})"
    except OSError as e:
        log.error(f"Error listing Ryujinx games metadata directory '{games_metadata_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error scanning game metadata: {e}", exc_info=True)

    log.info(f"Found {len(title_map)} game titles from metadata.")
    return title_map

def parse_imkvdb(file_path):
    """Legge il file imkvdb.arc e restituisce una mappa SaveDataId -> TitleId (entrambi uppercase hex)."""
    save_map = {} # SaveDataId (UPPER) -> TitleId (UPPER)
    expected_file_magic = 0x564B4D49  # IMKV
    expected_entry_magic = 0x4E454D49  # IMEN
    expected_key_size = 64
    expected_value_size = 64

    if not os.path.isfile(file_path):
        log.error(f"Save index file imkvdb.arc not found at '{file_path}'. Cannot map saves.")
        return save_map

    log.info(f"Parsing save index file: {file_path}")
    try:
        with open(file_path, 'rb') as f:
            # 1. Read File Header (12 bytes)
            header_data = f.read(12)
            if len(header_data) < 12:
                log.error(f"File imkvdb.arc too short for header ({len(header_data)} bytes).")
                return save_map

            file_magic, _, entry_count = struct.unpack('<IIi', header_data)

            if file_magic != expected_file_magic:
                log.error(f"Invalid file magic number (Expected: {expected_file_magic:X}, Got: {file_magic:X}). File might be corrupt.")
                return save_map

            log.debug(f"Found {entry_count} entries in save index.")

            # 2. Read Entries
            for i in range(entry_count):
                # 2a. Read Entry Header (12 bytes)
                entry_header_data = f.read(12)
                if len(entry_header_data) < 12:
                    log.error(f"Truncated read at entry header {i+1}.")
                    break

                entry_magic, key_size, value_size = struct.unpack('<Iii', entry_header_data)

                # Validate entry magic and sizes
                if entry_magic != expected_entry_magic:
                    log.warning(f"Invalid entry magic {i+1} (Expected: {expected_entry_magic:X}, Got: {entry_magic:X}). Skipping.")
                    bytes_to_skip = expected_key_size + expected_value_size
                    f.read(bytes_to_skip) # Attempt to skip expected size
                    continue

                if key_size != expected_key_size or value_size != expected_value_size:
                    log.warning(f"Invalid entry sizes {i+1} (Key: {key_size} vs {expected_key_size}, Value: {value_size} vs {expected_value_size}). Skipping.")
                    bytes_to_skip = (key_size if 0 < key_size < 1024 else expected_key_size) + \
                                    (value_size if 0 < value_size < 1024 else expected_value_size)
                    f.read(bytes_to_skip) # Attempt to skip based on read/expected sizes
                    continue

                # 2b. Read Key Data (64 bytes)
                key_data = f.read(key_size)
                if len(key_data) < key_size:
                    log.error(f"Truncated read at key data for entry {i+1}.")
                    break

                # 2c. Read Value Data (64 bytes)
                value_data = f.read(value_size)
                if len(value_data) < value_size:
                    log.error(f"Truncated read at value data for entry {i+1}.")
                    break

                try:
                    # Unpack Key (SaveDataAttribute) - only need ProgramId (TitleID)
                    # < Q (ProgramId) ... >
                    program_id = struct.unpack('<Q', key_data[:8])[0] # Read only the first 8 bytes

                    # Unpack Value (SaveDataIndexerValue) - only need SaveDataId
                    # < Q (SaveDataId) ... >
                    save_data_id = struct.unpack('<Q', value_data[:8])[0] # Read only the first 8 bytes

                    # Format IDs as uppercase hex strings (16 chars, zero-padded)
                    save_data_id_hex = f"{save_data_id:016X}"
                    program_id_hex = f"{program_id:016X}"

                    # Add to map
                    save_map[save_data_id_hex] = program_id_hex
                    log.debug(f"  Mapped SaveID {save_data_id_hex} -> TitleID {program_id_hex}")

                except struct.error as e:
                    log.error(f"Error unpacking entry {i+1}: {e}. Skipping.")
                    continue # Skip to the next entry

    except FileNotFoundError:
        # Already handled at the start, but keep for safety
        log.error(f"File imkvdb.arc not found at '{file_path}'.")
    except Exception as e:
        log.error(f"Unexpected error reading imkvdb.arc: {e}", exc_info=True)

    log.info(f"Parsed {len(save_map)} SaveID -> TitleID mappings from index.")
    return save_map

def _get_ryujinx_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx user save directory."""
    if not ryujinx_appdata_dir: return None
    ryujinx_save_path = os.path.join(ryujinx_appdata_dir, 'bis', 'user', 'save')
    log.debug(f"Potential Ryujinx user save directory: {ryujinx_save_path}")
    if os.path.isdir(ryujinx_save_path):
         return ryujinx_save_path
    else:
         log.warning(f"Ryujinx user save directory path derived but does not exist: {ryujinx_save_path}")
         return None

def _get_ryujinx_system_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx system save directory (where imkvdb.arc resides)."""
    if not ryujinx_appdata_dir: return None
    # Path where imkvdb.arc is typically located
    ryujinx_sys_save_path = os.path.join(ryujinx_appdata_dir, 'bis', 'system', 'save', '8000000000000000', '0')
    log.debug(f"Potential Ryujinx system save directory (for index): {ryujinx_sys_save_path}")
    if os.path.isdir(ryujinx_sys_save_path):
         return ryujinx_sys_save_path
    else:
         log.warning(f"Ryujinx system save directory path derived but does not exist: {ryujinx_sys_save_path}")
         return None

# --- Main Profile Finder Function (REWRITTEN) ---

def find_ryujinx_profiles(executable_dir: str | None = None) -> list[dict]:
    """
    Finds Ryujinx game profiles/saves using metadata and the save index.

    Args:
        executable_dir: Ignored for Ryujinx, kept for signature consistency.

    Returns:
        List of profile dicts: [{'id': SaveDataID, 'path': full_save_path, 'name': GameName}, ...]
    """
    log.info("Attempting to find Ryujinx profiles (using metadata and save index)...")
    profiles_data = []

    # 1. Find base AppData directory
    ryujinx_appdata_dir = get_ryujinx_appdata_path()
    if not ryujinx_appdata_dir:
        log.error("Cannot find Ryujinx profiles: AppData directory not found.")
        return []

    # 2. Load TitleID -> Game Name map from metadata
    game_title_map = get_game_title_map(ryujinx_appdata_dir) # Keys are UPPERCASE TitleIDs

    # 3. Load SaveDataID -> TitleID map from imkvdb.arc
    ryujinx_sys_save_dir = _get_ryujinx_system_save_dir(ryujinx_appdata_dir)
    save_to_title_map = {} # Default empty map
    if ryujinx_sys_save_dir:
        imkvdb_path = os.path.join(ryujinx_sys_save_dir, "imkvdb.arc")
        save_to_title_map = parse_imkvdb(imkvdb_path) # Keys are UPPERCASE SaveDataIDs
    else:
        log.error("Cannot map saves to titles: System save directory (for index file) not found.")
        # We can still proceed, but names might be less accurate

    # 4. Find user save directory
    ryujinx_user_save_dir = _get_ryujinx_save_dir(ryujinx_appdata_dir)
    if not ryujinx_user_save_dir:
        log.error("Cannot find Ryujinx profiles: User save directory not found.")
        return []

    # 5. Scan user save directory and build profile list
    try:
        log.info(f"Scanning user save directory for profiles: {ryujinx_user_save_dir}")
        for item_name in os.listdir(ryujinx_user_save_dir):
            item_path = os.path.join(ryujinx_user_save_dir, item_name)
            # Check if it's a directory and looks like a SaveDataID (hex, 16 chars)
            if os.path.isdir(item_path) and len(item_name) == 16:
                try:
                    int(item_name, 16) # Verify it's hex
                    save_data_id = item_name.upper() # Use UPPERCASE SaveDataID

                    # Find TitleID from the save index map
                    title_id = save_to_title_map.get(save_data_id) # Look up using UPPERCASE SaveDataID

                    game_name = f"Unknown Game (SaveID: {save_data_id})" # Default/Fallback name

                    if title_id:
                        # Find Game Name from the metadata map using the TitleID (already UPPERCASE)
                        game_name_from_meta = game_title_map.get(title_id)
                        if game_name_from_meta:
                            game_name = game_name_from_meta # Use name from metadata
                        else:
                            game_name = f"Unknown Title (TitleID: {title_id})" # Fallback if TitleID not in metadata map
                    # else: title_id is None, keep the default "Unknown Game (SaveID: ...)"

                    profile_info = {
                        'id': save_data_id, # The ID is the SaveDataID (folder name)
                        'path': os.path.normpath(item_path), # Full path to the save folder
                        'name': game_name # Resolved game name or fallback
                    }
                    profiles_data.append(profile_info)
                    log.debug(f"Found Ryujinx profile: {profile_info}")

                except ValueError:
                    log.debug(f"Skipping item, name is not a valid 16-char hex ID: {item_name}")
                except Exception as e_inner:
                    log.warning(f"Error processing potential save folder '{item_name}': {e_inner}")

        log.info(f"Found {len(profiles_data)} potential Ryujinx profiles.")

    except OSError as e:
        log.error(f"Error accessing Ryujinx user save directory '{ryujinx_user_save_dir}': {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error scanning user save directory: {e}", exc_info=True)
        return []

    # 6. Sort and return
    profiles_data.sort(key=lambda p: p.get('name', p.get('id', '')))
    return profiles_data

# --- End Ryujinx ---

def detect_and_find_profiles(target_path: str | None) -> tuple[str, list[dict]] | None:
    """
    Detects if the target path belongs to a known emulator and finds its profiles.
    (This function remains largely the same, just calls the updated find_ryujinx_profiles)
    """
    if not target_path or not isinstance(target_path, str):
        return None

    target_path_lower = target_path.lower()
    executable_dir = None
    if os.path.isfile(target_path):
        executable_dir = os.path.dirname(target_path)
        log.debug(f"Derived executable directory (may not be used by all finders): {executable_dir}")

    for keyword, config in EMULATOR_CONFIG.items():
        if keyword in target_path_lower:
            emulator_name = config['name']
            profile_finder = config['profile_finder']
            logging.info(f"Detected known emulator '{emulator_name}' based on target path: {target_path}")
            try:
                # Pass None for Ryujinx, derived path otherwise (as before)
                exec_dir_to_pass = None if keyword == 'ryujinx' else executable_dir
                profiles = profile_finder(exec_dir_to_pass) # Calls the REWRITTEN find_ryujinx_profiles
                return emulator_name, profiles
            except Exception as e:
                log.error(f"Error calling profile finder for {emulator_name}: {e}", exc_info=True)
                return emulator_name, [] # Return empty list on error

    log.debug(f"Target path '{target_path}' did not match any known emulator keywords.")
    return None


# Example usage (for testing purposes)
if __name__ == "__main__":
    # Setup basic logging TO CONSOLE for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.StreamHandler()])

    log.info("Running emulator_manager.py directly for testing (Metadata + Index Mode)...")

    # executable_dir is ignored for Ryujinx testing
    found_profiles = find_ryujinx_profiles(executable_dir=None)

    if found_profiles:
        print("\n--- Found Ryujinx Profiles/Games ---")
        for profile_info in found_profiles:
            print(f"- SaveID: {profile_info['id']}")
            print(f"  Name:   {profile_info['name']}")
            print(f"  Path:   {profile_info['path']}")
            print("-" * 20)
    else:
        print("\nNo Ryujinx profiles found or an error occurred.")

    log.info("Finished emulator_manager.py test run.")
