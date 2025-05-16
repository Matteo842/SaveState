# emulator_utils/dolphin_manager.py
# -*- coding: utf-8 -*-

import os
import platform
import logging
import re
import struct # Necessario per leggere dati binari
import codecs # Needed for Wii banner parsing

log = logging.getLogger(__name__)

def get_dolphin_save_dirs(executable_path: str | None = None) -> list[str]:
    """
    Determines potential Dolphin save directories (GC and Wii).
    Checks both portable (relative to executable) and standard locations.
    Returns a list of existing save directory paths found.
    """
    save_dirs = []
    potential_bases = []

    # 1. Check for portable install ('User' directory next to exe)
    if executable_path and os.path.isfile(executable_path):
        exe_dir = os.path.dirname(executable_path)
        user_dir = os.path.join(exe_dir, "User")
        if os.path.isdir(user_dir):
            log.debug(f"Found potential Dolphin portable base: {user_dir}")
            potential_bases.append(user_dir)
        else:
            log.debug(f"No 'User' directory found next to executable: {exe_dir}")

    # 2. Check standard locations based on OS for the Global User Directory
    system = platform.system()
    user_home = os.path.expanduser("~")
    standard_user_data_dir = None # This is the directory expected to contain GC, Wii, etc.

    if system == "Windows":
        # Typically C:\Users\<user>\Documents\Dolphin Emulator
        standard_user_data_dir = os.path.join(user_home, "Documents", "Dolphin Emulator")
    elif system == "Linux":
        # Paths that are expected to BE the "Global User Directory" containing GC, Wii, etc.
        # Order: Standard XDG Data, Flatpak Data, Legacy home directory.
        paths_to_check_linux_user_data = [
            os.path.join(user_home, ".local", "share", "dolphin-emu"),                                   # Standard XDG Data
            os.path.join(user_home, ".var", "app", "org.DolphinEmu.dolphin-emu", "data", "dolphin-emu"),  # Flatpak Data
            os.path.join(user_home, ".dolphin-emu")                                                       # Legacy ~/.dolphin-emu
        ]
        for path_linux in paths_to_check_linux_user_data:
            if os.path.isdir(path_linux):
                log.debug(f"Found potential Dolphin Global User Directory on Linux: {path_linux}")
                standard_user_data_dir = path_linux
                break # Use the first valid path found in order of preference

    elif system == "Darwin": # macOS
        # ~/Library/Application Support/Dolphin/
        standard_user_data_dir = os.path.join(user_home, "Library", "Application Support", "Dolphin")

    if standard_user_data_dir and os.path.isdir(standard_user_data_dir) and standard_user_data_dir not in potential_bases:
        log.debug(f"Adding standard Global User Directory to potential bases: {standard_user_data_dir}")
        potential_bases.append(standard_user_data_dir)
    elif standard_user_data_dir in potential_bases:
        log.debug(f"Standard Global User Directory already found (likely portable): {standard_user_data_dir}")
    else:
        log.debug(f"Standard Dolphin Global User Directory not found or invalid: {standard_user_data_dir}")

    if not potential_bases:
        log.warning("Could not find any potential Dolphin Global User Directory (portable or standard).")
        return []

    # 3. Check for GC and Wii save directories within potential Global User Directories
    for base_dir in potential_bases: # base_dir IS a "Global User Directory"
        log.debug(f"Checking for save subdirectories in Global User Directory: {base_dir}")
        gc_path = os.path.join(base_dir, "GC")
        wii_path = os.path.join(base_dir, "Wii", "title") # Wii saves are typically nested

        if os.path.isdir(gc_path):
            log.info(f"Found Dolphin GC save directory: {gc_path}")
            if gc_path not in save_dirs:
                save_dirs.append(gc_path)
        else:
            log.debug(f"GC save directory not found in base: {base_dir}")

        if os.path.isdir(wii_path):
            log.info(f"Found Dolphin Wii save directory: {wii_path}")
            if wii_path not in save_dirs:
                 save_dirs.append(wii_path)
        else:
             log.debug(f"Wii save directory ('{os.path.join('Wii', 'title')}') not found in base: {base_dir}")

    if not save_dirs:
        log.warning("Found Dolphin Global User Directory(ies) but no GC or Wii save subdirectories within them.")

    return save_dirs


def _parse_gc_banner_bin(banner_path: str) -> str | None:
    """
    Parses a GC banner.bin file to extract the game title.
    Tries common encodings. Returns None if unable to parse.
    """
    try:
        with open(banner_path, 'rb') as f:
            # Basic check: Read magic bytes (BNR1/BNR2) - optional but good practice
            magic = f.read(4)
            if magic not in (b'BNR1', b'BNR2'):
                log.warning(f"Invalid magic bytes in banner.bin: {banner_path} ({magic!r})")
                # Continue anyway, might still work for some variants

            # Game titles often start around offset 0x20.
            # Let's read a block that should contain multiple titles.
            # Example structure might have:
            # 0x20: Short Title (32 bytes)
            # 0x40: Short Maker (32 bytes)
            # 0x60: Long Title (64 bytes)
            # 0xA0: Long Maker (64 bytes)
            # 0xE0: Description (128 bytes)
            # We'll try reading the Long Title first, then Short Title.

            # Try Long Title (Offset 0x60, Length 64)
            f.seek(0x60)
            long_title_bytes = f.read(64).split(b'\x00', 1)[0] # Read until null terminator

            # Try Short Title (Offset 0x20, Length 32) if Long Title empty
            if not long_title_bytes:
                 f.seek(0x20)
                 long_title_bytes = f.read(32).split(b'\x00', 1)[0] # Use same variable

            if not long_title_bytes:
                 log.debug(f"No title data found at expected offsets in banner.bin: {banner_path}")
                 return None

            # Attempt decoding (try common encodings)
            encodings_to_try = ['utf-8', 'shift_jis', 'latin_1'] # Add others if needed
            title = None
            for enc in encodings_to_try:
                try:
                    title = long_title_bytes.decode(enc).strip()
                    if title: # Stop if we get a non-empty title
                         log.debug(f"Decoded title '{title}' using {enc} from {banner_path}")
                         return title
                except UnicodeDecodeError:
                    continue # Try next encoding
                except Exception as decode_err: # Catch other potential decoding issues
                     log.warning(f"Error decoding title bytes with {enc} from {banner_path}: {decode_err}")
                     continue

            if not title:
                 log.warning(f"Could not decode title from banner.bin: {banner_path} (Bytes: {long_title_bytes!r})")
            return None # Return None if all decoding attempts fail

    except FileNotFoundError:
        log.error(f"banner.bin not found at expected path: {banner_path}")
        return None
    except OSError as e:
        log.error(f"OS Error reading banner.bin {banner_path}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing banner.bin {banner_path}: {e}", exc_info=True)
        return None


# --- Add Wii Banner Parsing Function (basic structure) ---
def _parse_wii_banner_bin(banner_path: str) -> str | None:
    """Parses the banner.bin file for Wii titles to extract the game name.

    Wii banner.bin often stores the title at offset 0x20, encoded in UTF-16BE.
    """
    expected_size = 0x480 # Standard Wii banner size, adjust if needed
    title_offset = 0x20
    # Max title length isn't strictly defined, read a reasonable amount
    max_read_bytes = 256

    try:
        if not os.path.exists(banner_path):
            log.debug(f"Wii banner.bin not found at {banner_path}")
            return None

        file_size = os.path.getsize(banner_path)
        if file_size < title_offset + 2: # Need at least offset + 2 bytes for a char
            log.warning(f"Wii banner.bin too small: {banner_path} ({file_size} bytes)")
            return None

        with open(banner_path, 'rb') as f:
            f.seek(title_offset)
            raw_title_bytes = f.read(max_read_bytes)

        # Decode using UTF-16 Big Endian
        try:
            # Find the first double null byte (0x0000) which terminates the string
            null_terminator_pos = -1
            for i in range(0, len(raw_title_bytes) - 1, 2):
                if raw_title_bytes[i] == 0x00 and raw_title_bytes[i+1] == 0x00:
                    null_terminator_pos = i
                    break

            if null_terminator_pos != -1:
                title_bytes = raw_title_bytes[:null_terminator_pos]
            else:
                # No null terminator found within read range, use all bytes read
                title_bytes = raw_title_bytes
                log.debug("Wii banner name wasn't null-terminated within read bytes")

            # Check for empty title after trimming
            if not title_bytes:
                 log.debug("Wii banner name section is empty after processing nulls")
                 return None

            title = title_bytes.decode('utf-16-be').strip()
            log.debug(f"Decoded Wii title (UTF-16BE): '{title}'")
            # Basic sanity check - reject if too short or looks like garbage?
            if title and len(title) > 1:
                 return title
            else:
                 log.warning(f"Parsed Wii title seems invalid: '{title}'")
                 return None

        except UnicodeDecodeError:
            log.warning(f"Could not decode Wii banner title as UTF-16BE: {banner_path}", exc_info=True)
            # Add fallbacks to other encodings if necessary here (e.g., Shift_JIS for JP games?)
            return None
        except Exception as e:
            log.error(f"Error reading/decoding Wii banner title section: {e}", exc_info=True)
            return None

    except OSError as e:
        log.error(f"OS Error accessing Wii banner.bin '{banner_path}': {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing Wii banner.bin '{banner_path}': {e}", exc_info=True)
        return None

# ------------------------------------------------------


def find_dolphin_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds Dolphin game save profiles by scanning determined save directories.
    Attempts to parse banner.bin for GC game names. Uses directory names as fallback/for Wii.
    """
    log.info("Attempting to find Dolphin profiles...")
    save_dirs = get_dolphin_save_dirs(executable_path)
    profiles = []

    if not save_dirs:
        log.error("Cannot find Dolphin profiles: Save directory locations are unknown.")
        return []

    for save_dir in save_dirs:
        log.info(f"Scanning Dolphin save directory: {save_dir}")

        # --- CORRECTED TYPE DETECTION ---
        # Determine type based on the save_dir path itself
        current_scan_type = None
        base_name = os.path.basename(save_dir).lower()
        parent_base_name = os.path.basename(os.path.dirname(save_dir)).lower()

        if base_name == 'gc':
             current_scan_type = 'GC'
        elif base_name == 'title' and parent_base_name == 'wii':
             current_scan_type = 'Wii'
        else:
            log.warning(f"Unexpected save directory structure, cannot determine type: {save_dir}")
            continue # Skip this directory

        log.debug(f"Determined scan type for '{save_dir}' as: {current_scan_type}")
        # ---------------------------------

        try:
            # --- MODIFIED GC LOGIC --- 
            if current_scan_type == 'GC':
                region_folders = os.listdir(save_dir)
                log.debug(f"  Regions/Items found in GC dir '{save_dir}': {region_folders}")
                for region_name in region_folders:
                    region_path = os.path.join(save_dir, region_name)
                    # Check if it's a directory and a known region
                    if os.path.isdir(region_path) and region_name.upper() in ['USA', 'EUR', 'JAP']:
                        log.debug(f"    Scanning GC Region Folder: {region_path}")
                        try:
                            game_id_folders = os.listdir(region_path)
                            log.debug(f"      Game IDs/Items found in region '{region_name}': {game_id_folders}")
                            for game_id_name in game_id_folders: # This is the actual game ID like GM8E01
                                game_id_path = os.path.join(region_path, game_id_name)

                                # --- Skip Memory Card simulations --- 
                                if game_id_name.upper() in ['CARD A', 'CARD B']:
                                     log.debug(f"        Skipping Memory Card folder: {game_id_name}")
                                     continue
                                # ------------------------------------

                                # Check if it's a directory and looks like a GC ID
                                if os.path.isdir(game_id_path) and len(game_id_name) == 6 and game_id_name.isalnum():
                                    log.debug(f"        Found potential GC Game ID folder: {game_id_name}")
                                    profile_id = game_id_name
                                    profile_name = game_id_name # Default name is ID
                                    profile_type = 'GC'
                                    # --- Try to get name from banner.bin ---
                                    banner_file = os.path.join(game_id_path, "banner.bin")
                                    if os.path.isfile(banner_file):
                                        log.debug(f"          Found banner.bin, attempting parse: {banner_file}")
                                        parsed_name = _parse_gc_banner_bin(banner_file)
                                        if parsed_name:
                                            profile_name = parsed_name # Use parsed name!
                                            log.info(f"          Successfully parsed GC game name: '{profile_name}' (ID: {profile_id})")
                                        else:
                                            log.warning(f"          Failed to parse banner.bin for {profile_id}, using ID as name.")
                                    else:
                                        log.debug(f"          banner.bin not found in {game_id_path}, using ID as name.")
                                    # -----------------------------------------
                                    profiles.append({
                                        'id': profile_id,
                                        'name': profile_name,
                                        'paths': [game_id_path], # Use list and 'paths'
                                        'type': profile_type
                                    })
                                else:
                                    log.debug(f"        Skipping item in region '{region_name}' (not dir or not 6 chars): {game_id_name}")
                        except OSError as region_e:
                            log.error(f"      Error scanning GC region directory '{region_path}': {region_e}")
                    else:
                         log.debug(f"    Skipping item in GC dir (not dir or not known region): {region_name}")
            # --- END MODIFIED GC LOGIC ---

            # --- MODIFIED Wii Logic --- 
            elif current_scan_type == 'Wii':
                high_tid_folders = os.listdir(save_dir) # e.g., ['00000001', '00010000']
                log.debug(f"  High-Level Title ID folders found in Wii dir '{save_dir}': {high_tid_folders}")
                for high_tid_name in high_tid_folders:
                    high_tid_path = os.path.join(save_dir, high_tid_name)
                    # --- Refined Check: Only look in game title folders (00010000) ---
                    if os.path.isdir(high_tid_path) and high_tid_name.startswith('00010000'):
                    # ---------------------------------------------------------------
                        log.debug(f"    Scanning High-Level TID Folder: {high_tid_path}")
                        try:
                            low_tid_folders = os.listdir(high_tid_path) # e.g., ['524d4750']
                            log.debug(f"      Low-Level Title ID folders found in '{high_tid_name}': {low_tid_folders}")
                            for low_tid_name in low_tid_folders:
                                low_tid_path = os.path.join(high_tid_path, low_tid_name)
                                # Check if it's a directory and has the 8-char length of low TID
                                if os.path.isdir(low_tid_path) and len(low_tid_name) == 8:
                                    log.debug(f"        Found potential Wii Game Title ID folder: {low_tid_name}")
                                    profile_id = low_tid_name # Use the 8-char Low TID
                                    profile_name = low_tid_name # Default name is ID
                                    profile_type = 'Wii'

                                    # --- Try to get name from Wii banner.bin --- 
                                    # Look in the folder itself or in a 'data' subfolder
                                    banner_path_direct = os.path.join(low_tid_path, "banner.bin")
                                    banner_path_data = os.path.join(low_tid_path, "data", "banner.bin")
                                    
                                    banner_to_parse = None
                                    if os.path.isfile(banner_path_direct):
                                        banner_to_parse = banner_path_direct
                                    elif os.path.isfile(banner_path_data):
                                        banner_to_parse = banner_path_data

                                    if banner_to_parse:
                                        log.debug(f"          Found Wii banner.bin, attempting parse: {banner_to_parse}")
                                        parsed_name = _parse_wii_banner_bin(banner_to_parse)
                                        if parsed_name:
                                            profile_name = parsed_name # Use parsed name!
                                            log.info(f"          Successfully parsed Wii game name: '{profile_name}' (ID: {profile_id})")
                                        else:
                                            log.warning(f"          Failed to parse Wii banner.bin for {profile_id}, using ID as name.")
                                    else:
                                        log.debug(f"          Wii banner.bin not found in {low_tid_path} or its data subdir, using ID as name.")
                                    # -------------------------------------------

                                    # *** Add the profile to the list ***
                                    profiles.append({
                                        'id': profile_id,
                                        'name': profile_name,
                                        'paths': [low_tid_path], # Use list and 'paths'
                                        'type': profile_type
                                    })
                                else:
                                    log.debug(f"        Skipping item in high TID '{high_tid_name}' (not dir or not 8 chars): {low_tid_name}")
                        except OSError as low_tid_e:
                            log.error(f"      Error scanning Wii low TID directory '{high_tid_path}': {low_tid_e}")
                    else:
                        log.debug(f"    Skipping item in Wii title dir (not dir or not known high TID prefix): {high_tid_name}")
            # --- END MODIFIED Wii Logic ---

        except FileNotFoundError:
             log.error(f"Save directory not found during scan (was it deleted?): '{save_dir}'")
        except OSError as e:
            log.error(f"Error scanning Dolphin save directory '{save_dir}': {e}")
        except Exception as e:
            log.error(f"Unexpected error scanning Dolphin directory '{save_dir}': {e}", exc_info=True)

    log.info(f"Found {len(profiles)} Dolphin profiles (GC named via banner.bin where possible).")
    profiles.sort(key=lambda p: p.get('name', ''))
    return profiles


# --- Example Usage ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    # Try finding saves without assuming an executable path (checks standard locations)
    print("--- Finding Dolphin Profiles (Standard Paths) ---")
    standard_profiles = find_dolphin_profiles()
    for p in standard_profiles:
        print(p)

    # Example: Simulate finding a portable install (replace with actual path if needed)
    # print("\n--- Finding Dolphin Profiles (Simulated Portable Path) ---")
    # portable_exe_path = "C:\\path\\to\\Dolphin\\Dolphin.exe" # CHANGE THIS
    # portable_profiles = find_dolphin_profiles(portable_exe_path)
    # for p in portable_profiles:
    #      print(p)
