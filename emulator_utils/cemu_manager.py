# emulator_utils/cemu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import xml.etree.ElementTree as ET

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


def find_cemu_profiles(executable_path: str | None) -> list[dict]:
    """
    Finds Cemu save data directories located within the 'mlc01' folder,
    typically relative to the emulator's executable. Reads game titles
    from the corresponding title metadata.

    Args:
        executable_path: The full path to the Cemu executable (e.g., Cemu.exe).

    Returns:
        List of profile dicts: [{'id': 'title_id', 'name': 'game_title', 'paths': [save_dir_path]}, ...]
    """
    profiles = []
    if not executable_path or not os.path.isfile(executable_path):
        log.warning("find_cemu_profiles: Valid executable_path is required.")
        return profiles

    log.info(f"Attempting to find Cemu profiles relative to: {executable_path}")

    # Cemu's data directory priority:
    # 1. <mlc_path> from settings.xml next to executable
    # 2. %APPDATA%/Cemu/mlc01 (Standard install location)
    # 3. mlc01 directory next to executable (Portable location)
    emulator_dir = os.path.dirname(executable_path)
    mlc_path = None

    # 1. Try reading mlc_path from settings.xml
    settings_file = os.path.join(emulator_dir, "settings.xml")
    if os.path.isfile(settings_file):
        log.info(f"Found Cemu settings file: {settings_file}")
        try:
            tree = ET.parse(settings_file)
            root = tree.getroot()
            # Find <mlc_path> within <General> section (adjust path if needed based on actual XML structure)
            mlc_path_element = root.find('.//mlc_path') # More robust find
            if mlc_path_element is not None and mlc_path_element.text:
                potential_path = mlc_path_element.text.strip()
                # Basic validation: Check if the potential path exists and is a directory
                if os.path.isdir(potential_path):
                    mlc_path = potential_path
                    log.info(f"  Using mlc_path from settings.xml: {mlc_path}")
                else:
                    log.warning(f"  Path '{potential_path}' from settings.xml <mlc_path> is not a valid directory. Ignoring.")
            else:
                log.info(f"  No <mlc_path> tag found or tag is empty in {settings_file}.")
        except ET.ParseError as e:
            log.error(f"  Error parsing Cemu settings.xml: {e}. Will try other locations.")
        except Exception as e:
            log.error(f"  Unexpected error reading Cemu settings.xml: {e}. Will try other locations.")

    # 2. If not found via settings.xml, check standard AppData location
    if mlc_path is None:
        appdata_path = os.getenv('APPDATA')
        if appdata_path:
            cemu_appdata_mlc_path = os.path.join(appdata_path, "Cemu", "mlc01")
            log.info(f"Checking standard AppData Cemu mlc01 path: {cemu_appdata_mlc_path}")
            if os.path.isdir(cemu_appdata_mlc_path):
                mlc_path = cemu_appdata_mlc_path
                log.info(f"  Using mlc_path from AppData: {mlc_path}")
            else:
                log.info(f"  Standard AppData Cemu mlc01 path not found.")
        else:
            log.warning("Could not determine AppData path. Skipping check.")

    # 3. If still not found, try default location next to executable (portable)
    if mlc_path is None:
        default_mlc_path = os.path.join(emulator_dir, "mlc01")
        log.info(f"Checking for mlc01 directory next to executable: {default_mlc_path}")
        if os.path.isdir(default_mlc_path):
            mlc_path = default_mlc_path
            log.info(f"  Using mlc_path adjacent to executable: {mlc_path}")
        else:
            log.warning(f"Cemu 'mlc01' directory not found next to executable.")

    # If no mlc_path could be determined after all checks
    if mlc_path is None:
        log.error("Could not determine Cemu mlc01 path from settings.xml, AppData, or executable directory. Cannot find profiles.")
        return profiles # Cannot proceed without a valid mlc_path

    log.info(f"Using Cemu mlc path: {mlc_path}")

    # Base path where game saves are stored by Title ID
    saves_base_path = os.path.join(mlc_path, "usr", "save", "00050000")

    if not os.path.isdir(saves_base_path):
        log.warning(f"Cemu saves base directory not found: {saves_base_path}")
        return profiles

    log.info(f"Searching for Title ID directories in: {saves_base_path}")

    # Find all subdirectories in the saves_base_path (potential Title IDs)
    try:
        potential_dirs = [d for d in os.listdir(saves_base_path) if os.path.isdir(os.path.join(saves_base_path, d))]
        log.info(f"Found {len(potential_dirs)} potential Title ID directories.")
    except OSError as e:
        log.error(f"Error listing directories in {saves_base_path}: {e}")
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
