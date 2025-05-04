# emulator_utils/desmume_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import re # For cleaning names

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

def find_desmume_profiles(executable_path: str | None) -> list[dict]:
    """
    Finds DeSmuME save files (.dsv) in the 'Battery' subdirectory
    relative to the emulator's executable directory.

    Args:
        executable_path: The full path to the DeSmuME executable (e.g., DeSmuME_x64.exe).

    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'cleaned_save_name', 'paths': [full_path]}, ...]
    """
    profiles = []
    if not executable_path or not os.path.isfile(executable_path):
        log.warning("find_desmume_profiles: Valid executable_path is required.")
        return profiles

    log.info(f"Attempting to find DeSmuME profiles relative to: {executable_path}")

    # Assume the 'Battery' directory is in the same directory as the executable
    emulator_dir = os.path.dirname(executable_path)
    saves_dir_primary = os.path.join(emulator_dir, "Battery") # Check standard case first
    saves_dir_secondary = os.path.join(emulator_dir, "battery") # Check lowercase as fallback
    saves_dir = None

    if os.path.isdir(saves_dir_primary):
        saves_dir = saves_dir_primary
        log.info(f"Found DeSmuME 'Battery' directory at: {saves_dir}")
    elif os.path.isdir(saves_dir_secondary):
        saves_dir = saves_dir_secondary
        log.info(f"Found alternative DeSmuME 'battery' (lowercase) directory at: {saves_dir}")
    else:
        log.warning(f"DeSmuME 'Battery' or 'battery' directory not found near {executable_path}. Cannot find profiles.")
        return profiles # Exit if no Battery directory found

    log.info(f"Searching for .dsv files in: {saves_dir}")

    try:
        # Look for .dsv files (standard main save files)
        search_pattern = os.path.join(saves_dir, "*.dsv")
        save_files = glob.glob(search_pattern)

        log.info(f"Found {len(save_files)} .dsv files in {saves_dir}")

        for file_path in save_files:
            if os.path.isfile(file_path):
                # Use the filename without extension as ID
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                profile_id = base_name # Keep full name for ID

                # Clean the name for display
                # Remove trailing codes like (USA), (Europe), (En,Fr,De,...), etc.
                # More comprehensive regex to catch different patterns
                profile_name = re.sub(r'\s*\((USA|Europe|Japan|World|[A-Za-z]{2}(?:,[A-Za-z]{2})*)\)$', '', base_name, flags=re.IGNORECASE).strip()
                # If cleaning left an empty string or didn't change, use original base_name
                if not profile_name or profile_name == base_name:
                     # Attempt a simpler region/language removal if the first didn't catch it
                     profile_name = re.sub(r'\s*\((En|Fr|De|Es|It|Ja|Nl|Pt)\)$', '', base_name, flags=re.IGNORECASE).strip()

                if not profile_name: # Fallback if still empty
                     profile_name = base_name

                profile = {
                    'id': profile_id,
                    'name': profile_name, # Use the cleaned name for display
                    'paths': [file_path] # List contains only the single .dsv file path
                }
                profiles.append(profile)
                log.debug(f"  Added DeSmuME profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")

    except OSError as e:
        log.error(f"Error accessing DeSmuME Battery directory '{saves_dir}': {e}")
    except Exception as e:
        log.error(f"Unexpected error finding DeSmuME profiles: {e}", exc_info=True)

    log.info(f"Found {len(profiles)} DeSmuME profiles (.dsv).")
    return profiles

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Provide a dummy path for testing - replace with actual if needed
    # Example: dummy_exe = "D:\\Emulators\\DeSmuME\\DeSmuME_x64.exe"
    dummy_exe = "DeSmuME_dummy.exe"

    # To test properly:
    # 1. Create a directory structure like: temp_desmume/DeSmuME_x64.exe
    # 2. Create a subdirectory: temp_desmume/Battery/
    # 3. Create dummy files: temp_desmume/Battery/Pokemon Platinum (USA).dsv, temp_desmume/Battery/Chrono Trigger (Europe) (En,Fr,De).dsv
    # 4. Set dummy_exe = "temp_desmume/DeSmuME_x64.exe"

    print(f"--- Testing DeSmuME Profile Finder with exe: {dummy_exe} ---")
    found_profiles = find_desmume_profiles(dummy_exe)
    if found_profiles:
        print("Found DeSmuME Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print(f"No DeSmuME profiles found (or dummy path '{dummy_exe}' is invalid/missing 'Battery' folder).")
