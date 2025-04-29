# emulator_manager.py
# -*- coding: utf-8 -*-

import os
import logging
#import platform
#import json
#import re

# Import specific finder functions
from .ryujinx_manager import find_ryujinx_profiles
from .yuzu_manager import find_yuzu_profiles
from .rpcs3_manager import find_rpcs3_profiles
from .dolphin_manager import find_dolphin_profiles

# Configure basic logging for this module
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

# --- Emulator Configuration --- 
# Maps a keyword found in the executable path to the function that finds its profiles.
EMULATOR_CONFIG = {
    'ryujinx': { # Keyword to check in the target path (lowercase)
        'profile_finder': find_ryujinx_profiles, # Use imported function
        'name': 'Ryujinx' # Display name
    },
    'yuzu': { # <-- NUOVA AGGIUNTA PER YUZU
        'profile_finder': lambda path: find_yuzu_profiles(path), # Use imported function
        'name': 'Yuzu'
    },
    'rpcs3': { # <-- NUOVA AGGIUNTA PER RPCS3
        # Use lambda to pass executable path
        'profile_finder': lambda path: find_rpcs3_profiles(path),
        'name': 'RPCS3'
    },
    'dolphin': { 
        'name': 'Dolphin',
        'profile_finder': lambda path: find_dolphin_profiles(path)
    },
    # 'cemu': { # Example for another emulator (Commented out)
    #    'profile_finder': lambda: find_cemu_profiles(), # Hypothetical function
    #    'name': 'Cemu'
    # },
}

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
                profiles = profile_finder(target_path) # Pass target_path

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

    # --- Test Yuzu ---
    log.info("--- Running Yuzu Test ---")
    # This will now use the imported function
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

    # --- Test RPCS3 ---
    log.info("\n--- Running RPCS3 Test ---")
    # This will now use the imported function via lambda
    found_rpcs3 = find_rpcs3_profiles(executable_path=None) # Test call without path
    if found_rpcs3:
        print("\n--- Found RPCS3 Profiles/Games ---")
        for profile_info in found_rpcs3:
            print(f"- SaveID: {profile_info['id']}")
            print(f"  Name:   {profile_info['name']}")
            print(f"  Path:   {profile_info['path']}")
            print("-" * 20)
    else:
        print("\nNo RPCS3 profiles found or an error occurred.")

    log.info("\nFinished emulator_manager.py test run.")
