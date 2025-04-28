# emulator_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import struct # <-- per parse_imkvdb

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
    'yuzu': { # <-- NUOVA AGGIUNTA PER YUZU
        'profile_finder': lambda exec_dir: find_yuzu_profiles(executable_dir=None),
        'name': 'Yuzu'
    },
    # Example for future addition:
    # 'rpcs3': {
    #    'profile_finder': lambda: find_rpcs3_profiles(), # Hypothetical function
    #    'name': 'RPCS3'
    # },
}

# --- Ryujinx Specific Helper Functions ---
# (Le funzioni get_ryujinx_appdata_path, get_game_title_map, parse_imkvdb,
#  _get_ryujinx_save_dir, _get_ryujinx_system_save_dir rimangono invariate)
# ... (codice Ryujinx omesso per brevità, è identico a prima) ...

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


# --- Yuzu Specific Helper Functions (NUOVE) ---

def parse_nacp(filepath: str) -> str | None:
    """
    Parses a Nintendo Switch control.nacp file to extract the game title.

    Args:
        filepath: The absolute path to the control.nacp file.

    Returns:
        The game title as a string if found, otherwise None.
        Searches for the first non-empty title entry (usually English).
    """
    if not os.path.isfile(filepath):
        log.debug(f"NACP file not found: {filepath}")
        return None

    try:
        with open(filepath, 'rb') as f:
            # Titles start at offset 0x3000. Each title entry is 0x200 bytes long.
            # We check multiple entries (e.g., first 16 for different languages).
            title_offset_start = 0x3000
            title_entry_size = 0x200 # 512 bytes
            max_languages_to_check = 16 # Standard number of language entries

            for i in range(max_languages_to_check):
                current_offset = title_offset_start + (i * title_entry_size)
                f.seek(current_offset)
                # Read the title data (up to 512 bytes per entry)
                title_bytes = f.read(title_entry_size)
                if not title_bytes:
                    log.warning(f"Could not read title entry {i} from NACP: {filepath}")
                    continue # Try next language

                # Titles are null-terminated UTF-8 strings. Find the first null byte.
                null_terminator_pos = title_bytes.find(b'\x00')
                if null_terminator_pos != -1:
                    title_bytes = title_bytes[:null_terminator_pos] # Trim null terminator and beyond

                # Decode UTF-8
                try:
                    title_str = title_bytes.decode('utf-8').strip()
                    if title_str: # If we found a non-empty title, return it
                        log.debug(f"Found title in NACP '{filepath}' (Entry {i}): {title_str}")
                        return title_str
                except UnicodeDecodeError:
                    log.warning(f"Could not decode UTF-8 title entry {i} from NACP: {filepath}")
                    continue # Try next language

            # If no non-empty title was found after checking entries
            log.warning(f"No valid game title found in NACP file: {filepath}")
            return None

    except OSError as e:
        log.error(f"Error reading NACP file '{filepath}': {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing NACP file '{filepath}': {e}", exc_info=True)
        return None

def get_yuzu_appdata_path():
    """Gets the default Yuzu AppData path based on the OS."""
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
        # Check for Flatpak path first
        flatpak_path = os.path.join(user_home, ".var", "app", "org.yuzu_emu.yuzu", "data", "yuzu")
        if os.path.isdir(flatpak_path):
            log.info(f"Found Yuzu Flatpak data directory: {flatpak_path}")
            return flatpak_path
        # Default Linux path (XDG Base Directory)
        path_to_check = os.path.join(user_home, ".local", "share", "yuzu")
    elif system == "Darwin": # macOS
        path_to_check = os.path.join(user_home, "Library", "Application Support", "yuzu")
    else:
        log.error(f"Unsupported operating system for Yuzu path detection: {system}")
        return None

    # Check if the derived path exists
    if path_to_check and os.path.isdir(path_to_check):
        log.info(f"Found Yuzu AppData directory: {path_to_check}")
        return path_to_check
    else:
        log.error(f"Yuzu AppData directory not found at expected location: {path_to_check}")
        return None

def get_yuzu_game_title_map(yuzu_appdata_dir: str) -> dict[str, str]:
    """
    Loads a map of Title IDs to game names from a local JSON file.
    
    Returns:
        A dictionary mapping uppercase Title IDs to game names.
    """
    # Determine the path to the JSON file (assuming it's in the same dir as this script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_file_path = os.path.join(script_dir, "switch_game_list.json")

    title_map = {}
    if not os.path.isfile(json_file_path):
        log.error(f"Game list file not found: {json_file_path}. Cannot map Yuzu Title IDs to names.")
        return title_map

    log.info(f"Loading Yuzu game titles from local file: {json_file_path}")
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Assuming the structure is {'games': {'TITLE_ID': 'Name', ...}}
        raw_title_map = data.get("games")
        if isinstance(raw_title_map, dict):
            # Ensure keys are uppercase for consistent lookup
            title_map = {tid.upper(): name for tid, name in raw_title_map.items()}
            log.info(f"Loaded {len(title_map)} game titles from {json_file_path}.")
        else:
            log.error(f"Invalid format in {json_file_path}: 'games' key not found or not a dictionary.")

    except json.JSONDecodeError:
        log.error(f"Error decoding JSON from file: {json_file_path}")
    except OSError as e:
        log.error(f"Error reading file '{json_file_path}': {e}")
    except Exception as e:
        log.error(f"Unexpected error loading Yuzu game titles from {json_file_path}: {e}", exc_info=True)

    return title_map

def find_yuzu_profiles(executable_dir: str | None = None) -> list[dict]:
    """
    Finds Yuzu game profiles/saves by scanning the save directory structure.
    NOTE: Currently uses TitleID as the profile name.

    Args:
        executable_dir: Ignored for Yuzu, kept for signature consistency.

    Returns:
        List of profile dicts: [{'id': TitleID, 'path': full_path_to_titleid_folder, 'name': TitleID}, ...]
    """
    log.info("Attempting to find Yuzu profiles...")
    profiles = []

    # 1. Get Yuzu AppData path
    yuzu_appdata_dir = get_yuzu_appdata_path()

    if not yuzu_appdata_dir:
        log.error("Cannot find Yuzu profiles: Yuzu AppData directory is unknown.")
        return None # <-- Se AppData non trovato, restituisce None

    # 2. Get the Title ID -> Game Name map
    game_title_map = get_yuzu_game_title_map(yuzu_appdata_dir) # Keys are UPPERCASE TitleIDs

    # 3. Path to the user saves directory within Yuzu's NAND structure
    user_save_dir = os.path.join(yuzu_appdata_dir, "nand", "user", "save", "0000000000000000") # User 0 save folder

    if not os.path.isdir(user_save_dir):
        log.warning(f"Yuzu base save directory not found: {user_save_dir}")
        return []

    # 4. Scan for User ID folders and then Title ID folders
    try:
        log.info(f"Scanning Yuzu save directory: {user_save_dir}")
        # Iterate through potential User ID folders (usually just one non-zero)
        for user_id_folder_name in os.listdir(user_save_dir):
            user_id_path = os.path.join(user_save_dir, user_id_folder_name)
            # Check if it's a directory and looks like a User ID (hex or decimal?)
            # Yuzu user IDs seem to be decimal, but let's be flexible
            if os.path.isdir(user_id_path) and user_id_folder_name != '0': # Ignore the '0' folder if present
                log.debug(f"  Scanning User ID folder: {user_id_folder_name}")
                try:
                    # Iterate through Title ID folders within the User ID folder
                    for title_id_folder_name in os.listdir(user_id_path):
                        title_id_path = os.path.join(user_id_path, title_id_folder_name)
                        # Check if it's a directory and looks like a Title ID (16 hex chars)
                        if os.path.isdir(title_id_path) and len(title_id_folder_name) == 16:
                            try:
                                int(title_id_folder_name, 16) # Verify it's hex
                                title_id = title_id_folder_name.upper() # Use UPPERCASE TitleID

                                # Look up the game name using the Title ID
                                game_name = game_title_map.get(title_id, f"Unknown Title (ID: {title_id})")

                                profile_data = {
                                    'id': title_id,
                                    'path': title_id_path,
                                    'name': game_name # Use looked-up name or fallback
                                }
                                profiles.append(profile_data)
                                log.debug(f"    Found Yuzu profile: {profile_data}")

                            except ValueError:
                                log.debug(f"    Skipping item, name is not a valid 16-char hex Title ID: {title_id_folder_name}")
                            except Exception as e_inner:
                                log.warning(f"    Error processing potential Yuzu save folder '{title_id_folder_name}': {e_inner}")
                except OSError as e_user:
                     log.warning(f"  Error accessing contents of User ID folder '{user_id_path}': {e_user}")
                except Exception as e_user_scan:
                     log.error(f"  Unexpected error scanning User ID folder '{user_id_path}': {e_user_scan}", exc_info=True)

        log.info(f"Found {len(profiles)} potential Yuzu profiles.")

    except OSError as e:
        log.error(f"Error accessing Yuzu base save directory '{user_save_dir}': {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error scanning Yuzu save directory: {e}", exc_info=True)
        return []

    # 5. Sort and return (sorting by name, which is currently TitleID)
    profiles.sort(key=lambda p: p.get('name', p.get('id', '')))
    return profiles

# --- End Yuzu ---


# --- Main Detection Function (MODIFICATA) ---

def detect_and_find_profiles(target_path: str | None) -> tuple[str, list[dict]] | None:
    """
    Detects if the target path belongs to a known emulator and finds its profiles.
    """
    if not target_path or not isinstance(target_path, str):
        log.debug("detect_and_find_profiles: Invalid target_path provided.")
        return None

    target_path_lower = target_path.lower()
    executable_dir = None
    if os.path.isfile(target_path):
        executable_dir = os.path.dirname(target_path)
        log.debug(f"Derived executable directory (may not be used by all finders): {executable_dir}")

    # Iterate through the configured emulators
    for keyword, config in EMULATOR_CONFIG.items():
        # Check if the keyword (e.g., 'ryujinx', 'yuzu') is in the target path
        if keyword in target_path_lower:
            emulator_name = config['name']
            profile_finder = config['profile_finder']
            log.info(f"Detected known emulator '{emulator_name}' based on target path: {target_path}")
            try:
                # Call the specific profile finder function for the detected emulator
                # Both Ryujinx and Yuzu finders currently ignore executable_dir
                profiles = profile_finder(executable_dir) # Pass executable_dir (might be None)

                # === MODIFICA ===
                # Controlla se la funzione ha restituito una LISTA (anche vuota)
                # invece di None o False, per indicare che l'emulatore è stato
                # riconosciuto ma potrebbe non avere salvataggi.
                if profiles is not None: # Check if the finder *ran successfully* and returned a list
                    log.info(f"Profile finder for {config['name']} ran. Found {len(profiles)} profiles.")
                    # Restituisci SEMPRE se il finder ha avuto successo,
                    # anche se la lista è vuota. Sarà compito del chiamante
                    # decidere cosa fare con una lista vuota.
                    return config['name'], profiles
                else:
                    # Finder ha restituito None (fallimento interno del finder)
                    log.warning(f"Profile finder for '{config['name']}' failed or returned None. Continuing detection...")
                    # Non ritornare, continua a cercare altri emulatori o usa euristica
                # === FINE MODIFICA ===

            except Exception as e:
                log.error(f"Error calling profile finder for {emulator_name}: {e}", exc_info=True)
                # Return the emulator name but an empty list to indicate an error during profile finding
                return emulator_name, []

    # If no keyword matched
    log.debug(f"Target path '{target_path}' did not match any known emulator keywords.")
    return None


# --- Example Usage (MODIFICATO per testare anche Yuzu) ---
if __name__ == "__main__":
    # Setup basic logging TO CONSOLE for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.StreamHandler()])

    # --- Test Ryujinx ---
    log.info("--- Running Ryujinx Test ---")
    found_ryujinx = find_ryujinx_profiles(executable_dir=None)
    if found_ryujinx:
        print("\n--- Found Ryujinx Profiles/Games ---")
        for profile_info in found_ryujinx:
            print(f"- SaveID: {profile_info['id']}")
            print(f"  Name:   {profile_info['name']}")
            print(f"  Path:   {profile_info['path']}")
            print("-" * 20)
    else:
        print("\nNo Ryujinx profiles found or an error occurred.")

    # --- Test Yuzu ---
    log.info("\n--- Running Yuzu Test ---")
    found_yuzu = find_yuzu_profiles(executable_dir=None)
    if found_yuzu:
        print("\n--- Found Yuzu Profiles/Games ---")
        for profile_info in found_yuzu:
            print(f"- TitleID: {profile_info['id']}")
            print(f"  Name:    {profile_info['name']} (Currently TitleID)") # Specificare limitazione
            print(f"  Path:    {profile_info['path']}")
            print("-" * 20)
    else:
        print("\nNo Yuzu profiles found or an error occurred.")

    log.info("\nFinished emulator_manager.py test run.")
