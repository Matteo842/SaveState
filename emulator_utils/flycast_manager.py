# emulator_utils/flycast_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import re
import struct # Added for unpacking binary data

log = logging.getLogger(__name__)

# Constants for VMU parsing based on ElysianVMU specification
VMU_BLOCK_SIZE = 512
VMU_ROOT_BLOCK_INDEX = 255
VMU_ROOT_BLOCK_OFFSET = VMU_ROOT_BLOCK_INDEX * VMU_BLOCK_SIZE

# Offsets within the Root Block (relative to start of Root Block)
RB_MAGIC_OFFSET = 0x000
RB_MAGIC_SIZE = 16
RB_MAGIC_EXPECTED = b'\x55' * 16
RB_FAT_FIRST_OFFSET = 0x046
RB_FAT_SIZE_OFFSET = 0x048
RB_DIR_LAST_OFFSET = 0x04a # Last block of directory
RB_DIR_SIZE_OFFSET = 0x04c # Size of directory in blocks

# Offsets within a Directory Entry (32 bytes total)
DE_TYPE_OFFSET = 0x00
DE_FILENAME_OFFSET = 0x04
DE_FILENAME_SIZE = 12
# DE_START_FAT_OFFSET = 0x02 # First data block of the file
# DE_FILE_SIZE_BLOCKS_OFFSET = 0x18 # File size in blocks (Hypothesized position)

# Directory Entry Types
DE_TYPE_EMPTY_OR_DELETED = 0x00
DE_TYPE_DATA = 0x33
DE_TYPE_GAME = 0xCC


def _extract_titles_from_vmu_dump(vmu_bin_path: str) -> list[str]:
    """Parses a VMU .bin dump to extract filenames from its directory listing."""
    titles = []
    try:
        with open(vmu_bin_path, 'rb') as f:
            # 1. Read the Root Block
            f.seek(VMU_ROOT_BLOCK_OFFSET)
            root_block_data = f.read(VMU_BLOCK_SIZE)
            if len(root_block_data) < VMU_BLOCK_SIZE:
                log.warning(f"Could not read full root block from {vmu_bin_path}.")
                return titles

            # 2. Verify Magic Number
            magic = root_block_data[RB_MAGIC_OFFSET : RB_MAGIC_OFFSET + RB_MAGIC_SIZE]
            if magic != RB_MAGIC_EXPECTED:
                log.warning(f"Invalid VMU magic number in {vmu_bin_path}. Not a valid format or not initialized.")
                return titles

            # 3. Get Directory Info from Root Block (Little Endian)
            dir_last_block = struct.unpack('<H', root_block_data[RB_DIR_LAST_OFFSET : RB_DIR_LAST_OFFSET + 2])[0]
            dir_size_blocks = struct.unpack('<H', root_block_data[RB_DIR_SIZE_OFFSET : RB_DIR_SIZE_OFFSET + 2])[0]

            if dir_size_blocks == 0:
                log.info(f"VMU dump {vmu_bin_path} has a directory size of 0 blocks.")
                return titles

            # 4. Calculate Directory Start
            # Formula: (Last Directory Block - Directory Size in Blocks) + 1
            # Ensure dir_last_block is treated as an index (0 to N-1)
            # If dir_last_block is 253 and dir_size_blocks is 13, then first dir block is 253 - 13 + 1 = 241
            dir_start_block = (dir_last_block - dir_size_blocks) + 1
            
            directory_start_offset = dir_start_block * VMU_BLOCK_SIZE
            total_directory_bytes = dir_size_blocks * VMU_BLOCK_SIZE
            num_directory_entries = total_directory_bytes // 32

            f.seek(directory_start_offset)
            directory_data = f.read(total_directory_bytes)
            if len(directory_data) < total_directory_bytes:
                log.warning(f"Could not read full directory area from {vmu_bin_path}.")
                return titles

            # 5. Iterate Through Directory Entries
            for i in range(num_directory_entries):
                entry_offset = i * 32
                entry_data = directory_data[entry_offset : entry_offset + 32]
                if len(entry_data) < 32:
                    continue # Should not happen if directory_data was read fully

                file_type = entry_data[DE_TYPE_OFFSET]

                # Check if entry is active (not empty/deleted)
                # Also check for the 0xE5 pattern often used for deleted SFN entries, though ElysianVMU only mentions 0x00.
                if file_type == DE_TYPE_EMPTY_OR_DELETED or entry_data[DE_FILENAME_OFFSET] == 0xE5:
                    continue
                
                if file_type not in [DE_TYPE_DATA, DE_TYPE_GAME]:
                    # Could be an unknown type or an uninitialized entry that's not 0x00
                    # log.debug(f"Skipping entry with unknown type {file_type:#02x} in {vmu_bin_path}")
                    continue

                filename_bytes = entry_data[DE_FILENAME_OFFSET : DE_FILENAME_OFFSET + DE_FILENAME_SIZE]
                
                try:
                    # Filename is Shift-JIS, but for VMS files, it's typically ASCII.
                    # We'll try Shift-JIS, then CP932 (similar, common for Japanese DOS/Windows),
                    # then latin-1 as a fallback for simple ASCII names.
                    # Trim trailing spaces (0x20) and nulls (0x00) which might pad Shift-JIS fixed field.
                    try:
                        filename_str = filename_bytes.decode('shift_jis').rstrip(' \x00')
                    except UnicodeDecodeError:
                        try:
                            filename_str = filename_bytes.decode('cp932').rstrip(' \x00')
                        except UnicodeDecodeError:
                            filename_str = filename_bytes.decode('latin-1').rstrip(' \x00')
                    
                    if filename_str and not filename_str.isspace():
                        # log.debug(f"Found file: '{filename_str}' in {vmu_bin_path}")
                        titles.append(filename_str)
                except Exception as e:
                    log.error(f"Error decoding filename in {vmu_bin_path}: {filename_bytes.hex()} - {e}")
                    # Fallback: use a hex representation or a placeholder if decoding fails badly
                    titles.append(f"[undecodable:{filename_bytes.hex()}]")

    except FileNotFoundError:
        log.error(f"VMU dump file not found: {vmu_bin_path}")
    except Exception as e:
        log.error(f"Error parsing VMU dump {vmu_bin_path}: {e}", exc_info=True)
    
    return titles


# VMU library will be loaded on demand
vmu_library = None
vmu_library_available = False
_vmu_import_attempted = False # To ensure we only try to import once

# Ensure the NullHandler is added even if basicConfig was called,
# if this module is used as part of a larger application.
log.addHandler(logging.NullHandler())


def get_flycast_savedata_path(executable_dir_hint: str | None = None) -> str | None:
    """Tries to find the default Flycast emulator save data directory."""
    log.info("Attempting to find Flycast save data path.")
    system = platform.system()
    potential_paths = []

    # 1. Check paths relative to the executable directory hint first
    if executable_dir_hint and os.path.isdir(executable_dir_hint):
        log.debug(f"Using executable directory hint: {executable_dir_hint}")
        common_subdirs = ['data', 'saves', 'VMU', 'save', 'user'] # Common save subdirectories
        for subdir in common_subdirs:
            potential_paths.append(os.path.join(executable_dir_hint, subdir))

    # 2. Check system-specific common locations
    # Added more robust path suggestions based on common RetroArch and standalone Flycast locations
    if system == "Windows":
        appdata_local = os.environ.get('LOCALAPPDATA')
        appdata_roaming = os.environ.get('APPDATA')
        user_profile = os.environ.get('USERPROFILE')

        if appdata_roaming:
             # RetroArch common path
            potential_paths.append(os.path.join(appdata_roaming, 'RetroArch', 'saves', 'Flycast'))
            potential_paths.append(os.path.join(appdata_roaming, 'RetroArch', 'saves', 'flycast')) # case variation

        # Standalone Flycast common paths
        if user_profile:
            potential_paths.append(os.path.join(user_profile, 'Documents', 'Flycast', 'saves'))
            potential_paths.append(os.path.join(user_profile, 'Documents', 'Flycast', 'data'))
            potential_paths.append(os.path.join(user_profile, 'AppData', 'Roaming', 'Flycast', 'saves')) # Another Roaming possibility
            potential_paths.append(os.path.join(user_profile, 'AppData', 'Roaming', 'Flycast', 'data'))
        if appdata_local:
             potential_paths.append(os.path.join(appdata_local, 'Flycast', 'saves')) # Local AppData possibility
             potential_paths.append(os.path.join(appdata_local, 'Flycast', 'data'))


    elif system == "Linux":
        home_path = os.environ.get('HOME')
        if home_path:
            # RetroArch common path
            potential_paths.append(os.path.join(home_path, '.config', 'retroarch', 'saves', 'Flycast'))
            potential_paths.append(os.path.join(home_path, '.config', 'retroarch', 'saves', 'flycast'))
            # Standalone Flycast common paths
            potential_paths.append(os.path.join(home_path, '.local', 'share', 'flycast', 'data')) # XDG Base Directory spec
            potential_paths.append(os.path.join(home_path, '.flycast', 'data')) # Older location / direct dot folder
            potential_paths.append(os.path.join(home_path, '.config', 'flycast', 'data')) # XDG config possibility


    elif system == "Darwin": # macOS
        home_path = os.environ.get('HOME')
        if home_path:
            # RetroArch common path
            potential_paths.append(os.path.join(home_path, 'Library', 'Application Support', 'RetroArch', 'saves', 'Flycast'))
            potential_paths.append(os.path.join(home_path, 'Library', 'Application Support', 'RetroArch', 'saves', 'flycast'))
            # Standalone Flycast common paths
            potential_paths.append(os.path.join(home_path, 'Library', 'Application Support', 'Flycast', 'data'))


    # Check for the default "data" subdirectory within the executable hint directory if not already covered
    if executable_dir_hint and os.path.isdir(executable_dir_hint):
         potential_paths.append(os.path.join(executable_dir_hint, 'data'))


    log.debug(f"Checking potential paths: {potential_paths}")
    for path in potential_paths:
        # Also check for a 'data' subdirectory within potential paths if the path itself isn't the final dir
        check_paths = [path]
        if os.path.isdir(path):
             # Check if the path already contains typical VMU files or subdirs
             if any(os.path.exists(os.path.join(path, sub)) for sub in ['VMU_CARD_A.DCI', 'VMU_CARD_A.VMU', 'data']):
                  check_paths = [path]
             else:
                 # If the path exists but doesn't look like the final dir, check its 'data' subdir
                 check_paths.append(os.path.join(path, 'data'))


        for final_path in check_paths:
            if os.path.isdir(final_path):
                log.info(f"Found Flycast save data directory: {final_path}")
                return final_path

    log.warning("Could not automatically determine Flycast save data directory. Please ensure Flycast is configured or provide the path manually.")
    return None


def find_flycast_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds Flycast save files and extracts game titles.
    Treats the found savedata_dir as a single "profile" containing multiple game save entries.
    Returns a list containing one profile dictionary, or an empty list if no saves are found.
    """
    global vmu_library, vmu_library_available, _vmu_import_attempted
    if not _vmu_import_attempted:
        try:
            log.debug("Attempting to import 'vmut' library on demand for Flycast.")
            import vmut as vmu_lib_temp
            vmu_library = vmu_lib_temp
            vmu_library_available = True
            log.info("VMU library 'vmut' found and loaded on demand.")
        except ImportError as e:
            vmu_library_available = False
            vmu_library = None
            log.warning(f"VMU library 'vmut' not found on demand ({e}). Game titles from Flycast VMU files will not be available via library; using manual parsing.")
        _vmu_import_attempted = True

    log.info("Scanning for Flycast game saves...")

    exe_dir_hint = None
    if executable_path:
        if os.path.isfile(executable_path):
            exe_dir_hint = os.path.dirname(executable_path)
            log.debug(f"executable_path ('{executable_path}') is a file, using parent dir: {exe_dir_hint} as hint.")
        elif os.path.isdir(executable_path):
            exe_dir_hint = executable_path # Assume it's the emulator's root directory
            log.debug(f"executable_path ('{executable_path}') is a directory, using it directly as hint.")
        else:
            log.debug(f"executable_path ('{executable_path}') is neither a file nor a directory, skipping as hint.")
            exe_dir_hint = None

    savedata_dir = get_flycast_savedata_path(executable_dir_hint=exe_dir_hint)

    if not savedata_dir or not os.path.isdir(savedata_dir):
        log.warning("Flycast save data directory not found or not accessible. Cannot list game saves.")
        return []

    current_profile_games = []
    unique_titles_in_profile = set()
    # save_extensions = ('.vmu', '.srm', '.gdi', '.bin', '.vms') # .srm and .gdi are not handled yet

    try:
        for root, _, files in os.walk(savedata_dir):
            for item in files:
                full_path = os.path.join(root, item)
                item_lower = item.lower()
                filename_no_ext, ext_lower = os.path.splitext(item_lower)

                if ext_lower == '.bin':
                    # Heuristic to check if .bin is likely a VMU dump
                    if not ("vmu" in item_lower or "save" in item_lower or "card" in item_lower or "state" in item_lower or "dci" in item_lower):
                        log.debug(f"Skipping .bin file '{item}' as its name does not suggest it's a VMU dump.")
                        continue
                    
                    log.info(f"Processing VMU dump: {full_path}")
                    dump_titles = _extract_titles_from_vmu_dump(full_path)
                    if dump_titles:
                        for title in dump_titles:
                            # Sanitize and ensure uniqueness for titles from the dump
                            clean_title = title.strip()
                            if not clean_title: continue # Skip empty titles

                            game_name_to_display = clean_title # SIMPLIFIED NAME
                            if game_name_to_display not in unique_titles_in_profile:
                                # Generate ID: flycast_gamename_sourcefile.bin
                                source_file_name_for_id = os.path.basename(full_path).lower().replace('.','_')
                                game_id = f"flycast_{game_name_to_display.lower().replace(' ', '_').replace('.', '_')}_{source_file_name_for_id}"
                                
                                current_profile_games.append({
                                    "id": game_id,
                                    "name": game_name_to_display, 
                                    "paths": [full_path], # 'paths' is now a list 
                                    "type": "VMU Game (from Dump)"
                                })
                                unique_titles_in_profile.add(game_name_to_display)
                    continue # Processed .bin, move to next file

                elif ext_lower in ['.vms', '.vmu']:
                    game_name_to_display = filename_no_ext # Default to filename without extension
                    file_type = "VMU Save File (Unknown Title)" # Default type
                    source_file_name_for_id = os.path.basename(full_path).lower().replace('.','_')
                    game_id_base = game_name_to_display.lower().replace(' ', '_').replace('.', '_')

                    if vmu_library_available and vmu_library is not None:
                        try:
                            log.debug(f"Attempting to parse '{item}' with vmu_library.Vms_file")
                            vms_file_obj = vmu_library.Vms_file(file=full_path)
                            if vms_file_obj and hasattr(vms_file_obj, 'info') and 'description' in vms_file_obj.info:
                                extracted_title = vms_file_obj.info['description'].strip()
                                if extracted_title and extracted_title.lower() not in ["(nome vuoto)", "(no title found)", ""]:
                                    game_name_to_display = extracted_title # SIMPLIFIED NAME
                                    game_id_base = game_name_to_display.lower().replace(' ', '_').replace('.', '_')
                                    file_type = "VMU Game"
                                    log.info(f"Parsed title '{extracted_title}' from Vms_file for '{item}'.")
                                else:
                                    file_type = "VMU Save File (Empty Title)"
                                    log.info(f"Empty or placeholder title from Vms_file for '{item}'. Using filename: {filename_no_ext}")
                            else:
                                file_type = "VMU Save File (No Info)"
                                log.warning(f"Vms_file for '{item}' lacks 'info' or 'description'. Using filename: {filename_no_ext}")
                        except Exception as e_vms:
                            file_type = "VMU Save File (Parse Error)"
                            log.error(f"Error parsing '{item}' with vmu_library.Vms_file: {e_vms}. Using filename: {filename_no_ext}")
                    else:
                        file_type = "VMU Save File (Lib Not Avail)"
                        log.info(f"VMU library not available. Using filename for '{item}': {filename_no_ext}")
                    
                    final_game_id = f"flycast_{game_id_base}_{source_file_name_for_id}"
                    if game_name_to_display not in unique_titles_in_profile: # Check based on name to avoid visual duplicates
                        # Ensure ID uniqueness if names clash but files are different (though name check should cover this)
                        # This basic ID generation might need refinement if complex clashes occur.
                        current_profile_games.append({
                            "id": final_game_id,
                            "name": game_name_to_display, 
                            "paths": [full_path], # 'paths' is now a list
                            "type": file_type
                        })
                        unique_titles_in_profile.add(game_name_to_display)
                
                # Optionally, handle other extensions like .srm if needed, or just let them be skipped
                # else:
                #     log.debug(f"Skipping file with unhandled extension: {item}")

    except Exception as e_walk:
        log.error(f"Error walking directory {savedata_dir}: {e_walk}", exc_info=True)
        return [] # Return empty on major error walking directory

    if current_profile_games:
        log.info(f"Found {len(current_profile_games)} game save entries in {savedata_dir}.")
        return current_profile_games
    else:
        log.info(f"No game saves found in {savedata_dir}")
        return []