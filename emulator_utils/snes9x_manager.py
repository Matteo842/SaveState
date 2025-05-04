# emulator_utils/snes9x_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import re

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

def find_snes9x_profiles(executable_path: str | None) -> list[dict]:
    """
    Finds Snes9x save files (.srm) in the 'Saves' subdirectory
    relative to the emulator's executable directory.

    Args:
        executable_path: The full path to the Snes9x executable (e.g., snes9x.exe).

    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'save_name', 'paths': [full_path]}, ...]
    """
    profiles = []
    if not executable_path or not os.path.isfile(executable_path):
        log.warning("find_snes9x_profiles: Valid executable_path is required.")
        return profiles

    log.info(f"Attempting to find Snes9x profiles relative to: {executable_path}")

    # Assume the 'Saves' directory is in the same directory as the executable
    emulator_dir = os.path.dirname(executable_path)
    saves_dir = os.path.join(emulator_dir, "Saves") # Check Title Case first

    if not os.path.isdir(saves_dir):
        log.warning(f"Snes9x 'Saves' directory not found at: {saves_dir}. Checking lowercase 'saves'...")
        # Check common alternative name 'saves' (lowercase)
        saves_dir_lower = os.path.join(emulator_dir, "saves")
        if os.path.isdir(saves_dir_lower):
             log.info(f"Found alternative Snes9x saves directory: {saves_dir_lower}")
             saves_dir = saves_dir_lower
        else:
             log.warning(f"Snes9x 'saves' (lowercase) directory also not found at: {saves_dir_lower}. Cannot find profiles.")
             return profiles # Exit if no Saves directory found

    log.info(f"Searching for .srm files in: {saves_dir}")

    try:
        # Look for .srm files (standard SRAM saves)
        search_pattern = os.path.join(saves_dir, "*.srm")
        save_files = glob.glob(search_pattern)

        log.info(f"Found {len(save_files)} .srm files in {saves_dir}")

        for file_path in save_files:
            if os.path.isfile(file_path):
                # Use the filename without extension as both ID and Name initially
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                profile_id = base_name # Keep full name for ID

                # Clean the name for display by removing trailing language codes like (En,Fr,De,...)
                profile_name = re.sub(r'\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$', '', base_name).strip()
                # If cleaning didn't change anything, use original
                if not profile_name:
                    profile_name = base_name

                profile = {
                    'id': profile_id,
                    'name': profile_name, # Use the cleaned name for display
                    'paths': [file_path] # IMPORTANT: List contains only the single .srm file path
                }
                profiles.append(profile)
                log.debug(f"  Added Snes9x profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")

    except OSError as e:
        log.error(f"Error accessing Snes9x saves directory '{saves_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error finding Snes9x profiles: {e}", exc_info=True)

    log.info(f"Found {len(profiles)} Snes9x profiles (.srm).")
    return profiles

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Provide a dummy path for testing - replace with actual if needed
    # Example: dummy_exe = "D:\\Emulators\\Snes9x\\snes9x-x64.exe"
    dummy_exe = "snes9x-dummy.exe" # Use a non-existent path for basic test run

    # To test properly:
    # 1. Create a directory structure like: temp_snes9x/snes9x-x64.exe
    # 2. Create a subdirectory: temp_snes9x/Saves/
    # 3. Create dummy files: temp_snes9x/Saves/Game1.srm, temp_snes9x/Saves/Game2.srm
    # 4. Set dummy_exe = "temp_snes9x/snes9x-x64.exe"

    print(f"--- Testing Snes9x Profile Finder with exe: {dummy_exe} ---")
    found_profiles = find_snes9x_profiles(dummy_exe)
    if found_profiles:
        print("Found Snes9x Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print(f"No Snes9x profiles found (or dummy path '{dummy_exe}' is invalid/missing 'Saves' folder).")
