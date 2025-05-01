# emulator_utils/duckstation_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

def get_duckstation_memcard_path() -> str | None:
    """Tries to find the default DuckStation memory card directory."""
    log.debug("Attempting to find DuckStation memory card path.")
    system = platform.system()
    memcard_path = None

    # Standard path on Windows is typically Documents/DuckStation/memcards
    if system == "Windows":
        try:
            # Try to get the standard Documents folder path
            user_profile = os.environ.get('USERPROFILE')
            if user_profile:
                 documents_path = os.path.join(user_profile, 'Documents')
                 potential_path = os.path.join(documents_path, 'DuckStation', 'memcards')
                 if os.path.isdir(potential_path):
                     memcard_path = potential_path
                     log.debug(f"Found DuckStation memcards via USERPROFILE/Documents: {memcard_path}")
                 else:
                     log.debug(f"Standard path {potential_path} not found or not a directory.")
            else:
                 log.warning("USERPROFILE environment variable not found, cannot determine Documents path.")
        except Exception as e:
            log.error(f"Error trying to determine Documents path: {e}")

    # Add elif for Linux/macOS if needed later
    elif system == "Linux":
        log.debug("DuckStation path detection for Linux not implemented yet.")
    elif system == "Darwin": # macOS
        log.debug("DuckStation path detection for macOS not implemented yet.")

    if memcard_path:
        log.info(f"Using DuckStation memory card directory: {memcard_path}")
    else:
        log.warning("Could not automatically determine DuckStation memory card directory.")

    return memcard_path


def find_duckstation_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds DuckStation memory card files (.mcd) and treats them as profiles.
    The executable_path is currently ignored but kept for consistency.
    Returns a list of profiles or None if the directory cannot be found/read.
    """
    log.info("Scanning for DuckStation memory card profiles...")
    memcard_dir = get_duckstation_memcard_path()

    if not memcard_dir:
        log.error("Failed to find DuckStation memory card directory. Cannot list profiles.")
        return None # Indicate failure: directory not found

    profiles = []
    try:
        for filename in os.listdir(memcard_dir):
            if filename.lower().endswith('.mcd'):
                full_path = os.path.join(memcard_dir, filename)
                # Use filename without extension for ID and Name
                profile_name = os.path.splitext(filename)[0]
                profile_id = profile_name # Use the same for ID

                if not profile_name: # Skip if filename is just '.mcd'
                    log.warning(f"Skipping memory card file with empty name: {full_path}")
                    continue

                profile_info = {
                    'id': profile_id,
                    'name': profile_name, # Assumes filename is descriptive
                    'path': memcard_dir,   # Path to the directory containing the .mcd file
                    'emulator': 'DuckStation'
                }
                profiles.append(profile_info)
                log.debug(f"Found DuckStation memory card: {profile_name} at {full_path}")

        log.info(f"Found {len(profiles)} DuckStation memory card profile(s).")
        return profiles

    except FileNotFoundError:
        log.error(f"Memory card directory not found unexpectedly during scan: {memcard_dir}")
        return None # Indicate failure: directory disappeared?
    except PermissionError:
        log.error(f"Permission denied when trying to read directory: {memcard_dir}")
        return None # Indicate failure: permissions issue
    except Exception as e:
        log.error(f"An error occurred while scanning for DuckStation profiles: {e}", exc_info=True)
        return None # Indicate failure: other error


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    # Setup basic logging TO CONSOLE for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.StreamHandler()])

    log.info("--- Running DuckStation Manager Test ---")
    found_profiles = find_duckstation_profiles()

    if found_profiles is not None:
        print("\n--- Found DuckStation Memory Card Profiles ---")
        if found_profiles:
            for profile in found_profiles:
                print(f"- ID:   {profile['id']}")
                print(f"  Name: {profile['name']}")
                print(f"  Path: {profile['path']}")
                print("-" * 20)
        else:
             print("No .mcd files found in the detected directory.")
    else:
        print("\nCould not list DuckStation profiles (directory not found, permission error, or other issue). Check logs.")

    log.info("\nFinished duckstation_manager.py test run.")
