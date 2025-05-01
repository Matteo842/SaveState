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
from .duckstation_manager import find_duckstation_profiles # <-- ADD THIS IMPORT
#from .pcsx2_manager import find_pcsx2_profiles
#from .pcsx2_manager2 import list_ps2_saves # <-- RE-ADD this import

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
    'duckstation': { # <-- ADD THIS ENTRY
        'name': 'DuckStation',
        # Pass executable path even if unused by finder, for consistency
        'profile_finder': lambda path: find_duckstation_profiles(path)
    },
    # 'pcsx2': { # Temporarily disable PCSX2 during DuckStation dev if causing issues
    #     'name': 'PCSX2',
    #     'profile_finder': lambda path: find_pcsx2_profiles(path)
    # },
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
                # --- PCSX2 Specific Logic (Re-implemented based on user request) --- 
                if emulator_name == 'PCSX2':
                    # 1. Find the memory card files (.ps2 paths) using the original finder
                    memcard_list = find_pcsx2_profiles(target_path)
                    if memcard_list is None:
                        log.warning(f"PCSX2 profile finder (find_pcsx2_profiles) returned None. Skipping.")
                        continue # Try next emulator keyword if any
                    
                    all_ps2_saves = [] # List to hold combined saves from all memcards
                    if not memcard_list:
                         log.info("No PCSX2 memory card files (.ps2) found.")
                    else:
                        log.info(f"Found {len(memcard_list)} PCSX2 memory card file(s), scanning contents...")
                        # 2. Iterate through each memory card found
                        for memcard_info in memcard_list:
                            actual_memcard_path = memcard_info.get('path')
                            memcard_filename = os.path.basename(actual_memcard_path) if actual_memcard_path else 'Unknown.ps2'
                            
                            if not actual_memcard_path or not isinstance(actual_memcard_path, str):
                                log.warning(f"Skipping memory card entry due to missing or invalid path: {memcard_info}")
                                continue
                                
                            log.debug(f"Listing saves in memory card file: {actual_memcard_path}")
                            # 3. Call the new function to list saves inside this memcard
                            saves_in_memcard = list_ps2_saves(actual_memcard_path)
                            
                            if saves_in_memcard:
                                # 4. Format results, appending memcard name to save name
                                for save_entry in saves_in_memcard:
                                    save_name = save_entry.get('name')
                                    if not save_name or save_name in ['.', '..']:
                                        continue # Skip invalid or navigation entries
                                        
                                    # Combine save name and memcard filename for display
                                    display_name = f"{save_name} ({memcard_filename})"
                                    
                                    formatted_save = {
                                        'id': save_name, # Use the actual save directory name as ID
                                        'name': display_name, # Show combined name in UI
                                        'path': actual_memcard_path, # Path to the memcard file
                                        'emulator': 'PCSX2' # Ensure emulator type is set
                                        # Optional: Add 'memcard_source': memcard_filename if needed elsewhere
                                    }
                                    all_ps2_saves.append(formatted_save)
                                    log.debug(f"  Formatted save found: {formatted_save['name']} from {memcard_filename}")
                            else:
                                log.debug(f"No valid save directories found in {memcard_filename}.")
                    
                    # Return the aggregated list of individual save directories
                    log.info(f"Returning {len(all_ps2_saves)} formatted PCSX2 save entries from all scanned memory cards.")
                    return emulator_name, all_ps2_saves

                # --- Logic for other emulators (Unchanged) --- 
                elif emulator_name != 'PCSX2': # Check name directly
                    profiles = profile_finder(target_path)
                    if profiles is not None: 
                        log.info(f"Profile finder for {config['name']} ran. Found {len(profiles)} profiles.")
                        return config['name'], profiles
                    else:
                        log.warning(f"Profile finder for '{config['name']}' failed or returned None. Continuing detection...")
 
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

    # --- Test DuckStation --- ADD THIS TEST
    log.info("\n--- Running DuckStation Test ---")
    # Use lambda or direct call based on how EMULATOR_CONFIG is set
    found_duckstation = find_duckstation_profiles(executable_path=None) # Test call without path
    if found_duckstation is not None:
        print("\n--- Found DuckStation Memory Card Profiles ---")
        if found_duckstation:
             for profile_info in found_duckstation:
                 print(f"- ID:   {profile_info['id']}")
                 print(f"  Name: {profile_info['name']}")
                 print(f"  Path: {profile_info['path']}")
                 print("-" * 20)
        else:
             print("No DuckStation .mcd files found in the detected directory.")
    else:
        print("\nCould not list DuckStation profiles (directory not found, permission error, or other issue). Check logs.")

    log.info("\nFinished emulator_manager.py test run.")
