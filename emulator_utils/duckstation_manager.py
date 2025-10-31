# emulator_utils/duckstation_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import re
from utils import sanitize_profile_display_name

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

    elif system == "Linux":
        user_home = os.path.expanduser("~")
        # 1. Check Flatpak path first
        flatpak_path = os.path.join(user_home, ".var", "app", "org.duckstation.DuckStation", "config", "duckstation", "memcards")
        if os.path.isdir(flatpak_path):
            memcard_path = flatpak_path
            log.debug(f"Found DuckStation memcards via Flatpak path: {memcard_path}")
        else:
            log.debug(f"Flatpak path not found: {flatpak_path}")
            # 2. Check standard XDG config path
            xdg_config_path = os.path.join(user_home, ".config", "duckstation", "memcards")
            if os.path.isdir(xdg_config_path):
                memcard_path = xdg_config_path
                log.debug(f"Found DuckStation memcards via XDG config path: {memcard_path}")
            else:
                log.debug(f"XDG config path not found: {xdg_config_path}. No standard Linux path found.")

    elif system == "Darwin": # macOS
        user_home = os.path.expanduser("~")
        # Standard macOS Application Support path
        macos_path = os.path.join(user_home, "Library", "Application Support", "DuckStation", "memcards")
        if os.path.isdir(macos_path):
            memcard_path = macos_path
            log.debug(f"Found DuckStation memcards via macOS Application Support path: {memcard_path}")
        else:
            log.debug(f"macOS Application Support path not found: {macos_path}")
            # Alternative path (less common)
            alt_macos_path = os.path.join(user_home, ".config", "duckstation", "memcards")
            if os.path.isdir(alt_macos_path):
                memcard_path = alt_macos_path
                log.debug(f"Found DuckStation memcards via alternative macOS path: {memcard_path}")
            else:
                log.debug(f"Alternative macOS path not found: {alt_macos_path}. No standard macOS path found.")

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

    if not memcard_dir or not os.path.isdir(memcard_dir):
        log.error("Failed to find DuckStation memory card directory. Cannot list profiles.")
        return None # Indicate failure: directory not found

    profiles = []
    try:
        for item in os.listdir(memcard_dir):
            if item.lower().endswith('.mcd'):
                full_path = os.path.join(memcard_dir, item)
                log.info(f"DUCKMAN: Generated path: '{full_path}' (Type: {type(full_path)}) Encoding check: {full_path.encode()[:50]}...")
                profile_name = sanitize_profile_display_name(os.path.splitext(item)[0])
                # Use filename without extension + simple counter for ID uniqueness for now
                # A better approach might involve hashing path or using metadata if available
                # Let's use a simple sanitization + prefix
                sanitized_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', os.path.splitext(item)[0]) # Basic sanitization
                profile_id = f"duckstation_{sanitized_name.lower()}"
                
                profile_info = {
                    'id': profile_id,
                    'name': profile_name,
                    # Corretto: Usa 'paths' e assegna la lista con il percorso del file .mcd
                    'paths': [full_path],
                    'emulator': 'DuckStation'
                }
                profiles.append(profile_info)
                log.debug(f"Found DuckStation profile: {profile_info}")
    except OSError as e:
        log.error(f"Error accessing DuckStation memory card directory '{memcard_dir}': {e}")
        return None

    log.info(f"Found {len(profiles)} DuckStation memory card profile(s).")
    return profiles if profiles else None


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
                print(f"  Path: {profile['paths'][0]}")
                print("-" * 20)
        else:
             print("No .mcd files found in the detected directory.")
    else:
        print("\nCould not list DuckStation profiles (directory not found, permission error, or other issue). Check logs.")

    log.info("\nFinished duckstation_manager.py test run.")
