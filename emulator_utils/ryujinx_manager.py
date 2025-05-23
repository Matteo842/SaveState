# emulator_utils/ryujinx_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import struct # per parse_imkvdb

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

# --- Ryujinx Specific Helper Functions ---

def get_ryujinx_appdata_path(executable_dir=None):
    """Gets the default Ryujinx AppData path based on the OS or from the executable directory for portable installations."""
    # Check for portable installation if executable_dir is provided
    if executable_dir:
        # Check if there's a 'portable.ini' file in the executable directory (portable installation marker)
        portable_ini_path = os.path.join(executable_dir, "portable.ini")
        if os.path.isfile(portable_ini_path):
            log.info(f"Found Ryujinx portable installation with portable.ini at: {executable_dir}")
            return executable_dir
            
        # Check if there's a 'portable' directory in the executable directory (another portable structure)
        portable_dir_path = os.path.join(executable_dir, "portable")
        if os.path.isdir(portable_dir_path):
            log.info(f"Found Ryujinx portable installation with portable directory at: {executable_dir}")
            return executable_dir
            
        # Check if there's a 'bis' directory in the executable directory (another portable structure)
        bis_dir_path = os.path.join(executable_dir, "bis")
        if os.path.isdir(bis_dir_path):
            log.info(f"Found Ryujinx portable installation with bis directory at: {executable_dir}")
            return executable_dir
    
    # If not portable or portable path not found, proceed with standard paths
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

    if file_path is None:
        log.warning("Il percorso del file indice di salvataggio (imkvdb.arc) è None. Impossibile analizzare.")
        return save_map

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
                    save_map[save_data_id_hex] = program_id_hex # Store uppercase
                    log.debug(f"  Mapped SaveID {save_data_id_hex} to TitleID {program_id_hex}")

                except struct.error as e:
                    log.error(f"Error unpacking data for entry {i+1}: {e}")
                    break # Stop parsing if unpacking fails
                except Exception as e:
                    log.error(f"Unexpected error processing entry {i+1}: {e}")
                    break # Stop parsing on unexpected errors

    except IOError as e:
        log.error(f"Error reading file '{file_path}': {e}")
    except Exception as e:
        log.error(f"Unexpected error opening or reading file '{file_path}': {e}", exc_info=True)

    log.info(f"Successfully mapped {len(save_map)} save entries from index.")
    return save_map

def _get_ryujinx_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx user save directory."""
    if not ryujinx_appdata_dir:
        return None
    # Path depends on the system, but usually under 'bis/user/save'
    save_dir = os.path.join(ryujinx_appdata_dir, "bis", "user", "save")
    log.debug(f"Checking for Ryujinx save directory: {save_dir}")
    return save_dir

def _get_ryujinx_system_save_dir(ryujinx_appdata_dir):
    """Determines the Ryujinx system save directory (where imkvdb.arc resides)."""
    if not ryujinx_appdata_dir:
        return None
    # Path where the save index usually is, including the specific subdirs
    system_save_dir = os.path.join(ryujinx_appdata_dir, "bis", "system", "save", "8000000000000000", "0")
    log.debug(f"Checking for Ryujinx system save directory (for index): {system_save_dir}")
    # Return the path directly, parse_imkvdb will handle if the *file* exists
    # We just need the directory containing it.
    # Check if the base 'save' directory exists as a preliminary check
    base_system_save = os.path.dirname(os.path.dirname(system_save_dir))
    if os.path.isdir(base_system_save):
        return system_save_dir
    else:
        log.warning(f"Base system save directory '{base_system_save}' not found.")
        return None

def find_ryujinx_profiles(executable_dir: str | None = None):
    """
    Finds Ryujinx game profiles/saves using metadata and the save index.

    Args:
        executable_dir: Path to Ryujinx executable directory for portable installations.

    Returns:
        List of profile dicts: [{'id': SaveDataID, 'paths': [full_save_path], 'name': GameName}, ...]
    """
    profiles = []
    log.info("Attempting to find Ryujinx profiles...")

    ryujinx_appdata_dir = get_ryujinx_appdata_path(executable_dir)
    if not ryujinx_appdata_dir:
        log.error("Could not determine Ryujinx AppData path. Cannot find profiles.")
        return profiles # Empty list

    user_save_dir = _get_ryujinx_save_dir(ryujinx_appdata_dir)
    system_save_dir = _get_ryujinx_system_save_dir(ryujinx_appdata_dir)
    save_index_file = os.path.join(system_save_dir, "imkvdb.arc") if system_save_dir else None

    if not user_save_dir or not os.path.isdir(user_save_dir):
        log.error(f"Ryujinx user save directory not found or is not a directory: {user_save_dir}")
        return profiles

    # 1. Get TitleID -> GameName map from metadata (best effort)
    game_title_map = get_game_title_map(ryujinx_appdata_dir) # TitleID (UPPER) -> Name

    # 2. Get SaveDataID -> TitleID map from save index (critical)
    save_to_title_map = parse_imkvdb(save_index_file) # SaveDataID (UPPER) -> TitleID (UPPER)

    if not save_to_title_map:
        log.warning("Could not load save index (imkvdb.arc). Game names for saves might be generic or based on TitleID if available otherwise.")
        # No longer returning profiles here, will attempt to list SaveDataIDs directly.

    log.info(f"Scanning Ryujinx user save directory: {user_save_dir}")
    try:
        for item in os.listdir(user_save_dir):
            item_path = os.path.join(user_save_dir, item)
            # Check if the item is a directory and its name looks like a SaveDataID (16 hex chars)
            if os.path.isdir(item_path) and len(item) == 16 and all(c in '0123456789abcdefABCDEF' for c in item):
                save_data_id_upper = item.upper() # Use uppercase for consistency
                log.debug(f"  Found potential save directory: {save_data_id_upper}")

                # Look up the TitleID using the save index map
                title_id_upper = save_to_title_map.get(save_data_id_upper)

                game_name: str
                if title_id_upper:
                    # We have the TitleID, now find the game name using the metadata map
                    game_name = game_title_map.get(title_id_upper)
                    if game_name:
                        log.debug(f"    Mapped SaveID {save_data_id_upper} to TitleID {title_id_upper} -> Game '{game_name}'")
                    else:
                        # Fallback if metadata lookup failed or title wasn't found for a known TitleID
                        game_name = f"Game (Title ID: {title_id_upper})"
                        log.warning(f"    Could not find game name for TitleID {title_id_upper} (mapped from SaveID {save_data_id_upper}). Using TitleID as fallback name.")
                else:
                    # SaveDataID found in the directory, but TitleID not in the save index map (or map is empty)
                    game_name = f"Game Data (Save ID: {save_data_id_upper})"
                    if not save_to_title_map and save_index_file and os.path.exists(save_index_file):
                        # This means imkvdb.arc was found but parse_imkvdb returned an empty map (e.g. parsing error or empty file)
                        log.warning(f"  SaveID {save_data_id_upper}: TitleID not found. Save index file '{save_index_file}' might be corrupt, empty, or SaveDataID unlisted.")
                    elif not save_index_file or not os.path.exists(save_index_file):
                        log.info(f"  SaveID {save_data_id_upper}: TitleID not found because save index file was not found. Using SaveDataID in name.")
                    else: # save_to_title_map is empty from a non-existent file, or this specific ID is not in a loaded map
                        log.warning(f"  SaveID {save_data_id_upper}: TitleID not found in (potentially empty or unparsed) save index. Using SaveDataID in name.")
                
                profile = {
                    'id': save_data_id_upper, # The directory name is the unique SaveDataID
                    'paths': [item_path],        # Changed 'path' to 'paths' and made it a list
                    'name': game_name         # Name derived from TitleID via metadata or fallback
                }
                profiles.append(profile)

    except OSError as e:
        log.error(f"Error listing Ryujinx user save directory '{user_save_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error scanning Ryujinx user save directory: {e}", exc_info=True)

    log.info(f"Found {len(profiles)} Ryujinx profiles.")
    return profiles
