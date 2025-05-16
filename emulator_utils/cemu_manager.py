# emulator_utils/cemu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import xml.etree.ElementTree as ET
import platform
import getpass

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

def get_cemu_game_title(mlc_path: str, title_id: str, title_id_save_base_path: str) -> str | None:
    """Attempts to read the game title from standard title path or save path meta file."""
    # Path 1: Standard metadata location
    standard_meta_dir = os.path.join(mlc_path, "usr", "title", "00050000", title_id, "meta")
    standard_meta_xml_file = os.path.join(standard_meta_dir, "meta.xml")
    standard_title_txt_file = os.path.join(standard_meta_dir, "title.txt")

    # Path 2: Metadata possibly inside the save directory itself
    save_meta_dir = os.path.join(title_id_save_base_path, "meta")
    save_meta_xml_file = os.path.join(save_meta_dir, "meta.xml")
    save_title_txt_file = os.path.join(save_meta_dir, "title.txt")

    title = None

    # --- Try reading logic --- Priority: Standard XML, Save XML, Standard TXT, Save TXT

    # 1. Try Standard meta.xml
    log.debug(f"  Checking for standard meta.xml at: {standard_meta_xml_file}")
    if os.path.isfile(standard_meta_xml_file):
        log.debug(f"    Attempting to read title from standard meta.xml: {standard_meta_xml_file}")
        title = _parse_cemu_meta_xml(standard_meta_xml_file)
        if title: return title

    # 2. Try Save meta.xml
    if not title:
        log.debug(f"  Checking for save meta.xml at: {save_meta_xml_file}")
        if os.path.isfile(save_meta_xml_file):
            log.debug(f"    Attempting to read title from save meta.xml: {save_meta_xml_file}")
            title = _parse_cemu_meta_xml(save_meta_xml_file)
            if title: return title

    # 3. Try Standard title.txt
    if not title:
        log.debug(f"  Checking for standard title.txt at: {standard_title_txt_file}")
        if os.path.isfile(standard_title_txt_file):
            log.debug(f"    Attempting to read title from standard title.txt: {standard_title_txt_file}")
            title = _parse_cemu_title_txt(standard_title_txt_file)
            if title: return title

    # 4. Try Save title.txt
    if not title:
        log.debug(f"  Checking for save title.txt at: {save_title_txt_file}")
        if os.path.isfile(save_title_txt_file):
            log.debug(f"    Attempting to read title from save title.txt: {save_title_txt_file}")
            title = _parse_cemu_title_txt(save_title_txt_file)
            if title: return title

    # 5. If nothing worked
    if not title:
        log.warning(f"  Could not find title in standard or save locations for {title_id}")
        log.debug(f"    Checked standard paths: {standard_meta_xml_file} (exists: {os.path.isfile(standard_meta_xml_file)}), {standard_title_txt_file} (exists: {os.path.isfile(standard_title_txt_file)}) ")
        log.debug(f"    Checked save paths: {save_meta_xml_file} (exists: {os.path.isfile(save_meta_xml_file)}), {save_title_txt_file} (exists: {os.path.isfile(save_title_txt_file)}) ")

    return title # Return title found (could be None)


# Helper function to parse meta.xml to avoid code duplication
def _parse_cemu_meta_xml(file_path: str) -> str | None:
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        potential_tags = [
            'longname_en', 'longname_fr', 'longname_de', 'longname_es',
            'longname_it', 'longname_nl', 'longname_pt', 'longname_ru',
            'longname_ja', 'longname_ko', 'longname_zhcn', 'longname_zhtw'
        ]
        for tag in potential_tags:
            name_element = root.find(f'.//{tag}')
            if name_element is not None and name_element.text:
                title = name_element.text.strip()
                if title:
                    log.debug(f"      Found title in <{tag}>: '{title}'")
                    return title
        log.warning(f"    meta.xml parsed, but no suitable <longname_XX> tag found in {file_path}")
    except ET.ParseError as e:
        log.error(f"    Error parsing meta.xml {file_path}: {e}")
    except Exception as e:
        log.error(f"    Unexpected error reading meta.xml {file_path}: {e}")
    return None

# Helper function to parse title.txt
def _parse_cemu_title_txt(file_path: str) -> str | None:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            title = f.readline().strip()
            if title:
                log.debug(f"      Found title in title.txt: '{title}'")
                return title
            else:
                log.warning(f"    Title file is empty: {file_path}")
    except Exception as e:
        log.error(f"    Error reading title.txt {file_path}: {e}")
    return None


def find_cemu_profiles(executable_path: str | None):
    log.info(f"Attempting to find Cemu profiles. Executable hint: {executable_path}")
    profiles = []
    mlc_path = None
    user_home = os.path.expanduser('~')
    system = platform.system()
    cemu_base_dir_candidate = None
    executable_was_file = False

    if executable_path:
        if os.path.isfile(executable_path):
            cemu_base_dir_candidate = os.path.dirname(executable_path)
            executable_was_file = True
            log.debug(f"Executable path is a file. Base dir candidate: {cemu_base_dir_candidate}")
        elif os.path.isdir(executable_path):
            cemu_base_dir_candidate = executable_path
            log.debug(f"Executable path is a directory. Base dir candidate: {cemu_base_dir_candidate}")
        else:
            log.warning(f"Provided executable_path '{executable_path}' is not a valid file or directory.")

    # Priority 1: settings.xml (if cemu_base_dir_candidate is valid)
    if not mlc_path and cemu_base_dir_candidate:
        settings_file_path = os.path.join(cemu_base_dir_candidate, "settings.xml")
        if os.path.isfile(settings_file_path):
            log.info(f"Found Cemu settings file: {settings_file_path}")
            try:
                tree = ET.parse(settings_file_path)
                root = tree.getroot()
                mlc_path_element = root.find('.//mlc_path') # More robust find
                if mlc_path_element is not None and mlc_path_element.text:
                    potential_mlc_from_settings = mlc_path_element.text.strip()
                    if os.path.isdir(potential_mlc_from_settings):
                        mlc_path = potential_mlc_from_settings
                        log.info(f"  Using mlc_path from settings.xml: {mlc_path}")
                    else:
                        log.warning(f"  Path '{potential_mlc_from_settings}' from settings.xml <mlc_path> is not a valid directory. Ignoring.")
                else:
                    log.info(f"  No <mlc_path> tag found or tag is empty in {settings_file_path}.")
            except ET.ParseError as e:
                log.error(f"  Error parsing Cemu settings.xml: {e}. Will try other locations.")
            except Exception as e:
                log.error(f"  Unexpected error reading Cemu settings.xml: {e}. Will try other locations.")
        else:
            log.debug(f"Cemu settings.xml not found at: {settings_file_path}")

    # Priority 2: mlc01 next to cemu_base_dir_candidate (if valid)
    if not mlc_path and cemu_base_dir_candidate:
        potential_mlc_location = os.path.join(cemu_base_dir_candidate, "mlc01")
        if os.path.isdir(potential_mlc_location):
            mlc_path = potential_mlc_location
            log.info(f"Found mlc01 in the candidate base directory: {mlc_path}")

    # Priority 3: mlc01 in parent of cemu_base_dir_candidate (if executable_path was a file)
    if not mlc_path and cemu_base_dir_candidate and executable_was_file:
        parent_of_base_dir = os.path.dirname(cemu_base_dir_candidate)
        potential_mlc_location = os.path.join(parent_of_base_dir, "mlc01")
        if os.path.isdir(potential_mlc_location):
            mlc_path = potential_mlc_location
            log.info(f"Found mlc01 in parent of executable's dir: {mlc_path}")

    # Priority 4: More advanced Wine prefix path deduction (if system is Linux and executable_path was a file)
    if not mlc_path and system == "Linux" and cemu_base_dir_candidate and executable_was_file:
        # Original exe_dir for Wine deduction is cemu_base_dir_candidate if executable_was_file
        current_path_segment = cemu_base_dir_candidate 
        drive_c_path = None
        for _ in range(10): # Limit depth
            parent_segment, folder_name = os.path.split(current_path_segment)
            if folder_name.lower() == "drive_c":
                drive_c_path = current_path_segment
                break
            if parent_segment == current_path_segment: break
            current_path_segment = parent_segment
        
        if drive_c_path:
            try:
                wine_user = getpass.getuser()
                wine_appdata_paths = [
                    os.path.join(drive_c_path, "users", wine_user, "AppData", "Roaming", "Cemu", "mlc01"),
                    os.path.join(drive_c_path, "users", "Public", "AppData", "Roaming", "Cemu", "mlc01"),
                    os.path.join(drive_c_path, "users", wine_user, "AppData", "Local", "Cemu", "mlc01"),
                    os.path.join(drive_c_path, "users", "Public", "AppData", "Local", "Cemu", "mlc01")
                ]
                for p_path in wine_appdata_paths:
                    if os.path.isdir(p_path):
                        mlc_path = p_path
                        log.info(f"Found mlc01 in deduced Wine AppData path: {mlc_path}")
                        break
            except Exception as e:
                log.debug(f"Error or incomplete info for deducing Wine AppData path: {e}")

    # Priority 5: Standard OS-specific locations (if not found by other means)
    if not mlc_path:
        log.info("mlc01 not found via executable-relative paths or settings.xml. Checking OS standard locations.")
        if system == "Windows":
            appdata = os.getenv('APPDATA')
            local_appdata = os.getenv('LOCALAPPDATA')
            paths_to_check_windows = []
            if appdata: paths_to_check_windows.append(os.path.join(appdata, "Cemu", "mlc01"))
            if local_appdata: paths_to_check_windows.append(os.path.join(local_appdata, "Cemu", "mlc01"))
            
            for p_path in paths_to_check_windows:
                if os.path.isdir(p_path):
                    mlc_path = p_path
                    log.info(f"Found mlc01 in Windows standard path: {mlc_path}")
                    break

        elif system == "Linux":
            linux_paths_to_check = [
                os.path.join(user_home, ".local", "share", "Cemu", "mlc01"),
                os.path.join(user_home, ".local", "share", "cemu", "mlc01"),
                os.path.join(user_home, ".config", "Cemu", "mlc01"),
                os.path.join(user_home, ".config", "cemu", "mlc01"),
                os.path.join(user_home, ".cemu", "mlc01")
            ]
            for p_path in linux_paths_to_check:
                if os.path.isdir(p_path):
                    mlc_path = p_path
                    log.info(f"Found mlc01 in Linux standard path: {mlc_path}")
                    break
        
        elif system == "Darwin": # macOS
            mac_paths_to_check = [
                os.path.join(user_home, "Library", "Application Support", "Cemu", "mlc01"),
                os.path.join(user_home, ".config", "Cemu", "mlc01"), # Less common but possible
                os.path.join(user_home, ".cemu", "mlc01")
            ]
            for p_path in mac_paths_to_check:
                if os.path.isdir(p_path):
                    mlc_path = p_path
                    log.info(f"Found mlc01 in macOS standard path: {mlc_path}")
                    break

    if not mlc_path:
        log.warning("Could not determine Cemu mlc01 path. Cemu profiles cannot be found.")
        return []

    log.info(f"Using Cemu mlc01 path: {mlc_path}")

    # Determine saves_base_path (typically for retail games: usr/save/00050000)
    # For simplicity, focusing on the primary retail save location.
    # Cemu save structure can be complex with updates, DLCs in other similar folders (0005000C, 0005000E)
    # but game saves are predominantly under 00050000.
    saves_base_path = os.path.join(mlc_path, "usr", "save", "00050000")

    if not os.path.isdir(saves_base_path):
        log.warning(f"Cemu retail saves base path not found or not a directory: {saves_base_path}")
        # Also check common/mlc01/usr/save/common if previous doesn't exist
        common_saves_base_path = os.path.join(mlc_path, "usr", "save", "common")
        if os.path.isdir(common_saves_base_path):
            log.info(f"Found common saves base path: {common_saves_base_path}. Using this instead.")
            saves_base_path = common_saves_base_path # Use this if 00050000 is not present
        else:
            log.warning(f"Common saves base path also not found: {common_saves_base_path}")
            return profiles # profiles is empty [] at this point

    log.info(f"Scanning Cemu saves in: {saves_base_path}")
    try:
        potential_dirs = [d for d in os.listdir(saves_base_path) if os.path.isdir(os.path.join(saves_base_path, d))]
    except FileNotFoundError:
        log.warning(f"Cemu saves directory appears to have been removed or is inaccessible: {saves_base_path}")
        return profiles # profiles is empty []
    except Exception as e:
        log.error(f"Error listing Cemu save directories in {saves_base_path}: {e}")
        return profiles # profiles is empty []
    
    if not potential_dirs:
        log.info(f"No potential game save (Title ID) directories found in {saves_base_path}.")
        return profiles

    for title_id in potential_dirs:
        # Skip invalid looking title IDs if necessary (e.g., not hex, wrong length)
        # Basic check: 8 hex characters is typical for 00050000 type
        if not (len(title_id) == 8 and all(c in '0123456789abcdefABCDEF' for c in title_id)):
            # Allow for cases like the user's '101c9500 copia'
            if ' ' in title_id or 'copia' in title_id:
                 log.debug(f"Processing non-standard directory name as potential Title ID: {title_id}")
            else:
                log.debug(f"Skipping directory, does not look like a standard Cemu Title ID: {title_id}")
                continue

        title_id_save_base_path = os.path.join(saves_base_path, title_id) # Path like .../save/00050000/101c9500

        # --- Find User Save Directory --- 
        # User saves are typically in a subdirectory named like 'user/80000001' or similar
        user_save_dir = None
        user_dir_path = os.path.join(title_id_save_base_path, "user")
        if os.path.isdir(user_dir_path):
            try:
                user_subdirs = [d for d in os.listdir(user_dir_path) if os.path.isdir(os.path.join(user_dir_path, d))]
                if user_subdirs:
                    # Pick the first user directory found (usually only one)
                    # TODO: Handle multiple users if Cemu supports it clearly?
                    user_save_dir = os.path.join(user_dir_path, user_subdirs[0])
                    log.debug(f"  Found user save directory for {title_id}: {user_save_dir}")
                else:
                    log.warning(f"  'user' directory exists for {title_id}, but contains no subdirectories.")
            except OSError as e:
                log.error(f"  Error listing user directories in {user_dir_path}: {e}")
        else:
             log.warning(f"  'user' subdirectory not found in {title_id_save_base_path}")

        # If no user save directory found, we can't make a profile for this Title ID
        if not user_save_dir:
             log.warning(f"  Could not find a user save directory for Title ID {title_id}. Skipping profile.")
             continue

        # --- Get Game Title --- 
        game_name = get_cemu_game_title(mlc_path, title_id, title_id_save_base_path) # Pass both paths
        if not game_name:
            log.warning(f"  Using Title ID '{title_id}' as fallback name.")
            game_name = title_id

        # --- Create Profile --- 
        profile = {
            'id': title_id,
            'name': game_name,
            'paths': [user_save_dir] # Path to the actual save data
        }
        profiles.append(profile)
        log.debug(f"Added Cemu profile: ID='{profile['id']}', Name='{profile['name']}', Path='{profile['paths'][0]}'")

    log.info(f"Found {len(profiles)} Cemu profiles.")
    return profiles

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Provide a dummy path for testing - replace with actual if needed
    # Example: dummy_exe = "D:\\Emulators\\Cemu\\Cemu.exe"
    dummy_exe = "Cemu_dummy.exe"

    # To test properly:
    # 1. Create a directory structure like: temp_cemu/Cemu.exe
    # 2. Create subdirs: temp_cemu/mlc01/usr/save/00050000/101c9500/user/80000001/
    # 3. Create subdirs: temp_cemu/mlc01/usr/title/00050000/101c9500/meta/
    # 4. Create dummy save files inside .../80000001/
    # 5. Create file: temp_cemu/mlc01/usr/title/00050000/101c9500/meta/title.txt with "The Legend of Zelda: Breath of the Wild" inside.
    # 6. Set dummy_exe = "temp_cemu/Cemu.exe"

    print(f"--- Testing Cemu Profile Finder with exe: {dummy_exe} ---")
    found_profiles = find_cemu_profiles(dummy_exe)
    if found_profiles:
        print("Found Cemu Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print(f"No Cemu profiles found (or dummy path '{dummy_exe}' is invalid/missing 'mlc01' structure).")
