# emulator_utils/desmume_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import re # For cleaning names
import platform

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

def _get_desmume_save_dirs(executable_path: str | None = None) -> list[str]:
    """
    Determines potential DeSmuME save directories.
    Checks portable, Linux, and macOS standard locations.
    """
    potential_dirs = []
    user_home = os.path.expanduser("~")
    system = platform.system()

    # 1. Portable check
    actual_emulator_dir = None
    if executable_path:
        if os.path.isfile(executable_path):
            actual_emulator_dir = os.path.dirname(executable_path)
            log.debug(f"executable_path ('{executable_path}') is a file, using parent dir: {actual_emulator_dir} for portable check.")
        elif os.path.isdir(executable_path):
            actual_emulator_dir = executable_path # Assume it's the emulator's root directory
            log.debug(f"executable_path ('{executable_path}') is a directory, using it directly for portable check.")
        else:
            log.debug(f"executable_path ('{executable_path}') is neither a file nor a directory, skipping portable check based on it.")

    if actual_emulator_dir:
        for portable_subdir_name in ["Battery", "battery", "Saves", "saves"]:
            portable_path = os.path.join(actual_emulator_dir, portable_subdir_name)
            if os.path.isdir(portable_path):
                log.debug(f"Found potential DeSmuME portable save directory: {portable_path}")
                if portable_path not in potential_dirs:
                    potential_dirs.append(portable_path)
    else:
        log.debug("No valid executable_path provided or determined for portable check.")

    # 2. Standard OS-specific paths
    if system == "Linux":
        linux_paths = [
            os.path.join(user_home, ".config", "desmume", "Battery"),
            os.path.join(user_home, ".config", "desmume", "saves"),
            os.path.join(user_home, ".var", "app", "org.desmume.DeSmuME", "config", "desmume", "Battery"),
            os.path.join(user_home, ".var", "app", "org.desmume.DeSmuME", "config", "desmume", "saves"),
        ]
        for path in linux_paths:
            if os.path.isdir(path):
                log.debug(f"Found potential DeSmuME Linux save directory: {path}")
                if path not in potential_dirs:
                    potential_dirs.append(path)
    elif system == "Darwin": # macOS
        macos_paths = [
            os.path.join(user_home, "Library", "Application Support", "DeSmuME", "Battery"),
            os.path.join(user_home, "Library", "Application Support", "DeSmuME", "Saves"),
            os.path.join(user_home, "Library", "Application Support", "org.desmume.DeSmuME", "Battery"), # Bundle ID variant
            os.path.join(user_home, "Library", "Application Support", "org.desmume.DeSmuME", "Saves"),   # Bundle ID variant
        ]
        for path in macos_paths:
            if os.path.isdir(path):
                log.debug(f"Found potential DeSmuME macOS save directory: {path}")
                if path not in potential_dirs:
                    potential_dirs.append(path)
    elif system == "Windows":
        # For Windows, DeSmuME is often portable or uses the exe dir.
        # We can check APPDATA as a fallback, though less common for .dsv files directly.
        appdata_path = os.getenv("APPDATA")
        if appdata_path:
            win_paths = [
                os.path.join(appdata_path, "DeSmuME", "Battery"),
                os.path.join(appdata_path, "DeSmuME", "Saves"),
            ]
            for path in win_paths:
                if os.path.isdir(path):
                    log.debug(f"Found potential DeSmuME Windows AppData save directory: {path}")
                    if path not in potential_dirs:
                        potential_dirs.append(path)

    if not potential_dirs:
        log.warning("Could not find any potential DeSmuME save directories (portable or standard).")
    return potential_dirs

def find_desmume_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds DeSmuME save files (.dsv) by checking various locations.
    Locations include portable (near executable) and standard OS paths.

    Args:
        executable_path: Optional. The full path to the DeSmuME executable.
                         If provided, portable paths are checked.

    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'cleaned_save_name', 'paths': [full_path]}, ...]
    """
    profiles = []
    log.info(f"Attempting to find DeSmuME profiles... Executable path: {executable_path if executable_path else 'Not provided'}")

    save_dirs_to_check = _get_desmume_save_dirs(executable_path)

    if not save_dirs_to_check:
        log.warning("No DeSmuME save directories found to scan. Cannot find profiles.")
        return profiles

    all_found_files = {} # To handle duplicates from multiple paths pointing to same file

    for saves_dir in save_dirs_to_check:
        log.info(f"Searching for .dsv files in: {saves_dir}")
        try:
            search_pattern = os.path.join(saves_dir, "*.dsv")
            save_files = glob.glob(search_pattern)

            log.debug(f"Found {len(save_files)} .dsv files in {saves_dir}")

            for file_path in save_files:
                if os.path.isfile(file_path):
                    # Resolve to real path to avoid duplicates from symlinks etc.
                    real_file_path = os.path.realpath(file_path)
                    if real_file_path in all_found_files:
                        log.debug(f"Skipping duplicate file (already processed): {file_path}")
                        continue
                    all_found_files[real_file_path] = True

                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    profile_id = base_name
                    profile_name = re.sub(r'\s*\((USA|Europe|Japan|World|[A-Za-z]{2}(?:,[A-Za-z]{2})*)\)$', '', base_name, flags=re.IGNORECASE).strip()
                    if not profile_name or profile_name == base_name:
                        profile_name = re.sub(r'\s*\((En|Fr|De|Es|It|Ja|Nl|Pt)\)$', '', base_name, flags=re.IGNORECASE).strip()
                    if not profile_name:
                        profile_name = base_name

                    profile = {
                        'id': profile_id,
                        'name': profile_name,
                        'paths': [file_path]
                    }
                    profiles.append(profile)
                    log.debug(f"  Added DeSmuME profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")

        except OSError as e:
            log.error(f"Error accessing DeSmuME save directory '{saves_dir}': {e}")
        except Exception as e:
            log.error(f"Unexpected error finding DeSmuME profiles in '{saves_dir}': {e}", exc_info=True)

    log.info(f"Found {len(profiles)} unique DeSmuME profiles (.dsv) across all checked directories.")
    profiles.sort(key=lambda p: p.get('name', '')) # Sort for consistent output
    return profiles

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Provide a dummy path for testing - replace with actual if needed
    # Example: dummy_exe = "D:\\Emulators\\DeSmuME\\DeSmuME_x64.exe"
    # dummy_exe = "DeSmuME_dummy.exe" # Test without a valid exe (should use standard paths)
    dummy_exe = None # Test with no exe path

    # To test properly with a dummy exe:
    # 1. Create a directory for the dummy exe: temp_desmume_portable/
    # 2. Put a dummy DeSmuME_dummy.exe in it.
    # 3. Create subdirectories: temp_desmume_portable/Battery/ or temp_desmume_portable/Saves/
    # 4. Create dummy files: temp_desmume_portable/Battery/MyGame (USA).dsv
    # 5. Set dummy_exe = "temp_desmume_portable/DeSmuME_dummy.exe"

    # To test standard paths (e.g., Linux):
    # 1. Create: ~/.config/desmume/Battery/ or ~/.config/desmume/saves/
    # 2. Put dummy .dsv files there: ~/.config/desmume/Battery/AnotherGame (EUR).dsv
    # 3. Run with dummy_exe = None

    print(f"--- Testing DeSmuME Profile Finder with exe: {dummy_exe if dummy_exe else 'None (standard paths only)'} ---")
    found_profiles = find_desmume_profiles(dummy_exe)
    if found_profiles:
        print("Found DeSmuME Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print(f"No DeSmuME profiles found (exe path: '{dummy_exe if dummy_exe else 'None'}').")
