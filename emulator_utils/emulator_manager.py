# emulator_manager.py
# -*- coding: utf-8 -*-

import logging
import os
from typing import Dict, List, Callable, Any, Optional

# Import specific emulator profile finders
from .rpcs3_manager import find_rpcs3_profiles
from .yuzu_manager import find_yuzu_profiles
from . import ppsspp_manager
from .citra_manager import find_citra_profiles
from .ryujinx_manager import find_ryujinx_profiles
from .dolphin_manager import find_dolphin_profiles
from .duckstation_manager import find_duckstation_profiles
from .mgba_manager import find_mgba_profiles
from .snes9x_manager import find_snes9x_profiles
from .desmume_manager import find_desmume_profiles
from .cemu_manager import find_cemu_profiles
from .flycast_manager import find_flycast_profiles
from .shadps4_manager import find_shadps4_profiles
from .sameboy_manager import find_sameboy_profiles

# Configure basic logging for this module
log = logging.getLogger(__name__)

# Define a type alias for the profile finder function for clarity
ProfileFinder = Callable[[Optional[str]], Dict[str, str]]

# Dictionary mapping emulator keys (used internally) to their configuration
# 'name' is the display name, 'profile_finder' is the function to call
EMULATORS: Dict[str, Dict[str, Any]] = {
    'rpcs3': {
        'name': 'RPCS3',
        'profile_finder': lambda path: find_rpcs3_profiles(path)
    },
    'yuzu': {
        'name': 'Yuzu',
        'profile_finder': lambda path: find_yuzu_profiles(path)
    },
    'ppsspp': {
        'name': 'PPSSPP',
        'profile_finder': lambda path: ppsspp_manager.find_ppsspp_profiles(path)
    },
    'citra': {
        'name': 'Citra',
        'profile_finder': lambda path: find_citra_profiles(path)
    },
    'azahar': {
        'name': 'Azahar',
        'profile_finder': lambda path: find_citra_profiles(path)
    },
    'ryujinx': {
        'name': 'Ryujinx',
        'profile_finder': lambda path: find_ryujinx_profiles(path)
    },
    'dolphin': {
        'name': 'Dolphin',
        'profile_finder': lambda path: find_dolphin_profiles(path)
    },
    'duckstation': {
        'name': 'DuckStation',
        'profile_finder': lambda path: find_duckstation_profiles(path)
    },
    'mgba': {
        'name': 'mGBA',
        'profile_finder': lambda path: find_mgba_profiles(path)
    },
    'snes9x': {
        'name': 'Snes9x',
        'profile_finder': lambda path: find_snes9x_profiles(path)
    },
    'desmume': {
        'name': 'DeSmuME',
        'profile_finder': lambda path: find_desmume_profiles(path)
    },
    'cemu': {
        'name': 'Cemu',
        'profile_finder': lambda path: find_cemu_profiles(path)
    },
    'flycast': {
        'name': 'Flycast',
        'profile_finder': lambda path: find_flycast_profiles(path)
    },
    'shadps4': {
        'name': 'ShadPS4',
        'profile_finder': lambda path: find_shadps4_profiles(path)
    },
    'sameboy': {
        'name': 'SameBoy',
        'profile_finder': lambda path: find_sameboy_profiles(path)
    },
}

def get_emulator_display_name(emulator_key: str) -> Optional[str]:
    """Returns the display name for a given emulator key."""
    return EMULATORS.get(emulator_key, {}).get('name')

def get_available_emulators() -> List[str]:
    """Returns a list of keys for the configured emulators."""
    return list(EMULATORS.keys())

def find_profiles_for_emulator(emulator_key: str, custom_path: Optional[str] = None) -> Dict[str, str]:
    """ 
    Finds profiles for a specific emulator using its registered finder function.

    Args:
        emulator_key (str): The key identifying the emulator (e.g., 'rpcs3', 'citra').
        custom_path (Optional[str]): An optional custom path to search for profiles.

    Returns:
        Dict[str, str]: A dictionary of profiles found {profile_id: profile_path}.
                       Returns an empty dict if the emulator key is invalid or no profiles are found.
    """
    emulator_config = EMULATORS.get(emulator_key)
    if not emulator_config:
        log.error(f"Invalid emulator key provided: {emulator_key}")
        return {}

    profile_finder: Optional[ProfileFinder] = emulator_config.get('profile_finder')
    if not profile_finder:
        log.error(f"No profile finder configured for emulator: {emulator_key}")
        return {}

    try:
        # Pass the custom_path to the finder function
        profiles = profile_finder(custom_path)
        log.info(f"Found {len(profiles)} profiles for {emulator_config.get('name', emulator_key)}.")
        return profiles
    except Exception as e:
        log.exception(f"Error finding profiles for {emulator_config.get('name', emulator_key)}: {e}")
        return {}

def detect_and_find_profiles(target_path: str | None) -> tuple[str, list[dict]] | None:
    """
    Detects if the target path belongs to a known emulator and finds its profiles.
    Checks for Azahar explicitly first.
    """
    if not target_path or not isinstance(target_path, str):
        log.debug("detect_and_find_profiles: Invalid target_path provided.")
        return None

    target_path_lower = target_path.lower()
    executable_dir = None
    if os.path.isfile(target_path):
        executable_dir = os.path.dirname(target_path)
        log.debug(f"Derived executable directory (may not be used by all finders): {executable_dir}")

    # --- Explicit Check for Azahar First --- START ---
    if 'azahar' in target_path_lower:
        emulator_key = 'azahar'
        config = EMULATORS.get(emulator_key)
        if config:
            emulator_name = config['name']
            profile_finder = config['profile_finder']
            log.info(f"Detected known emulator '{emulator_name}' based on target path: {target_path}")
            try:
                # Note: For Azahar/Citra, find_citra_profiles ignores the path argument
                profiles = profile_finder(target_path) 
                if profiles is not None:
                    log.info(f"Profile finder for {emulator_name} ran. Found {len(profiles)} profiles.")
                    # Return the DISPLAY name and profiles
                    return emulator_name, profiles
                else:
                    log.warning(f"Profile finder for '{emulator_name}' failed or returned None.")
                    # Return name and empty list to signal finder issue
                    return emulator_name, []
            except Exception as e:
                log.error(f"Error calling profile finder for {emulator_name}: {e}", exc_info=True)
                return emulator_name, []
        else:
            log.error(f"'azahar' found in path, but no configuration found in EMULATORS.")
            # Fall through to the generic loop just in case
    # --- Explicit Check for Azahar First --- END ---

    # --- Generic Loop for Other Emulators --- START ---
    # Iterate through the configured emulators (excluding azahar now)
    for keyword, config in EMULATORS.items():
        if keyword == 'azahar': # Skip azahar, already checked
            continue
            
        # Check if the keyword (e.g., 'ryujinx', 'yuzu', 'citra', 'snes9x', 'desmume', 'cemu') is in the target path
        if keyword in target_path_lower:
            emulator_name = config['name']
            profile_finder = config['profile_finder']
            log.info(f"Detected known emulator '{emulator_name}' based on target path: {target_path}")

            # Determine the actual path to pass to the profile finder
            # If target_path is a file (e.g. an .exe), use its directory.
            # Otherwise (if it's already a dir or None), use target_path as is.
            path_to_scan = target_path 
            if target_path and os.path.isfile(target_path):
                path_to_scan = os.path.dirname(target_path)
                log.debug(f"Target path '{target_path}' is a file. Using its directory '{path_to_scan}' for profile finding for {emulator_name}.")

            try:
                # Pass the (potentially modified) path_to_scan to the finder
                profiles = profile_finder(path_to_scan) 
                if profiles is not None:
                    log.info(f"Profile finder for {config['name']} ran. Found {len(profiles)} profiles.")
                    
                    # Convert profiles from dict to list if needed
                    # This ensures compatibility with EmulatorGameSelectionDialog
                    # which expects a list of dictionaries
                    profiles_list = []
                    if isinstance(profiles, dict):
                        for profile_id, profile_data in profiles.items():
                            # If profile_data is already a dict with 'id', use it as is
                            if isinstance(profile_data, dict) and 'id' in profile_data:
                                profiles_list.append(profile_data)
                            # If profile_data is a string or dict without 'id', create a new dict
                            else:
                                profile_dict = {'id': profile_id}
                                if isinstance(profile_data, dict):
                                    # Merge the existing dict with our new one
                                    profile_dict.update(profile_data)
                                else:
                                    # profile_data is a string (or other non-dict), use it as 'name'
                                    profile_dict['name'] = str(profile_data)
                                    profile_dict['path'] = str(profile_data)  # Default path to the same value
                                profiles_list.append(profile_dict)
                    else:
                        # If profiles is already a list, use it as is
                        profiles_list = profiles
                    
                    # Return the DISPLAY name and profiles list
                    return emulator_name, profiles_list
                else:
                    log.warning(f"Profile finder for '{config['name']}' failed or returned None. Continuing detection...")
                    # We continue here, maybe another keyword matches later?
            except Exception as e:
                log.error(f"Error calling profile finder for {emulator_name}: {e}", exc_info=True)
                # Return the emulator name but an empty list to indicate an error during profile finding
                return emulator_name, [] 
    # --- Generic Loop for Other Emulators --- END ---

    # If no keyword matched
    log.debug(f"Target path '{target_path}' did not match any known emulator keywords.")
    return None

# Example Usage (Optional - for testing or demonstration)
if __name__ == "__main__":
    # Setup basic logging TO CONSOLE for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.StreamHandler()])

    # --- Test Yuzu ---
    log.info("--- Running Yuzu Test ---")
    # This will now use the imported function
    found_yuzu = find_profiles_for_emulator('yuzu')
    if found_yuzu:
        print("\n--- Found Yuzu Profiles/Games ---")
        for profile_info in found_yuzu.items():
            print(f"- TitleID: {profile_info[0]}")
            print(f"  Name:    {profile_info[1]}") 
            print("-" * 20)
    else:
        print("\nNo Yuzu profiles found or an error occurred.")

    # --- Test RPCS3 ---
    log.info("\n--- Running RPCS3 Test ---")
    # This will now use the imported function via lambda
    found_rpcs3 = find_profiles_for_emulator('rpcs3') 
    if found_rpcs3:
        print("\n--- Found RPCS3 Profiles/Games ---")
        for profile_info in found_rpcs3.items():
            print(f"- SaveID: {profile_info[0]}")
            print(f"  Name:   {profile_info[1]}")
            print("-" * 20)
    else:
        print("\nNo RPCS3 profiles found or an error occurred.")

    # --- Test DuckStation ---
    log.info("\n--- Running DuckStation Test ---")
    # Use lambda or direct call based on how EMULATOR_CONFIG is set
    found_duckstation = find_profiles_for_emulator('duckstation') 
    if found_duckstation is not None:
        print("\n--- Found DuckStation Memory Card Profiles ---")
        if found_duckstation:
             for profile_info in found_duckstation.items():
                 print(f"- ID:   {profile_info[0]}")
                 print(f"  Name: {profile_info[1]}")
                 print("-" * 20)
        else:
             print("No DuckStation .mcd files found in the detected directory.")
    else:
        print("\nCould not list DuckStation profiles (directory not found, permission error, or other issue). Check logs.")

    log.info("\nFinished emulator_manager.py test run.")
