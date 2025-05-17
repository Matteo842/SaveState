# ppsspp_manager.py
import os
import logging
import platform # Added platform import
import re # Import re for potential future use, though simple check used now
from .sfo_utils import parse_param_sfo

# Costanti
EMULATOR_NAME = "PPSSPP"
CORRECT_STANDARD_SUBPATH = os.path.join("PPSSPP", "PSP", "SAVEDATA") # Path from user screenshot

def find_ppsspp_profiles(executable_path=None): 
    """
    Trova i profili di salvataggio di PPSSPP basati sulle cartelle degli ID dei giochi.

    Cerca nella posizione standard: %UserProfile%\\Documents\\PPSSPP\\PSP\\SAVEDATA
    Ogni sottocartella in SAVEDATA è considerata un profilo di gioco separato.

    Args:
        executable_path (str, optional): Path to the emulator executable. Defaults to None.

    Returns:
        list: Una lista di dizionari, ognuno rappresentante un profilo trovato.
              Ogni dizionario ha le chiavi: 'emulator', 'id', 'name', 'paths'.
              'id' e 'name' sono l'ID della cartella del gioco (es. 'ULUS10041').
              'paths' è una lista di percorsi completi alle cartelle specifiche del gioco.
    """
    profiles = []
    log = logging.getLogger(__name__) 
    log.info("Scanning for PPSSPP save profiles...")

    save_data_base_path = None 
    profiles_dict = {} # Use a dictionary to group paths by base ID
    
    system = platform.system() # Get OS once
    user_home = os.path.expanduser('~') # Get user_home once

    potential_paths_to_check = []

    # 1. Check for portable mode first if executable_path is provided
    if executable_path:
        # Ensure executable_path is a file, then get its directory
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
            portable_save_path = os.path.join(exe_dir, "memstick", "PSP", "SAVEDATA")
            potential_paths_to_check.append(portable_save_path)
            log.debug(f"Added portable path to check: {portable_save_path}")
        else:
            log.warning(f"Provided executable_path '{executable_path}' is not a valid file. Skipping portable check.")

    # 2. Add OS-specific standard paths
    if system == "Windows":
        documents_path = os.path.join(user_home, 'Documents')
        # CORRECT_STANDARD_SUBPATH is "PPSSPP/PSP/SAVEDATA"
        win_standard_path = os.path.join(documents_path, CORRECT_STANDARD_SUBPATH)
        potential_paths_to_check.append(win_standard_path)
        log.debug(f"Added Windows standard path to check: {win_standard_path}")
    
    elif system == "Linux":
        # Flatpak path
        flatpak_config_path = os.path.join(user_home, ".var", "app", "org.ppsspp.PPSSPP", "config", "ppsspp", "PSP", "SAVEDATA")
        potential_paths_to_check.append(flatpak_config_path)
        log.debug(f"Added Linux Flatpak path to check: {flatpak_config_path}")
        
        # Standard XDG config path
        xdg_config_path = os.path.join(user_home, ".config", "ppsspp", "PSP", "SAVEDATA")
        potential_paths_to_check.append(xdg_config_path)
        log.debug(f"Added Linux XDG config path to check: {xdg_config_path}")

    elif system == "Darwin": # macOS
        # Standard macOS path (often similar to Linux XDG or in Application Support)
        mac_app_support_path = os.path.join(user_home, "Library", "Application Support", "PPSSPP", "PSP", "SAVEDATA")
        potential_paths_to_check.append(mac_app_support_path)
        log.debug(f"Added macOS Application Support path to check: {mac_app_support_path}")
        
        # macOS can also use .config/ppsspp for newer builds
        mac_xdg_config_path = os.path.join(user_home, ".config", "ppsspp", "PSP", "SAVEDATA")
        potential_paths_to_check.append(mac_xdg_config_path)
        log.debug(f"Added macOS XDG-like path to check: {mac_xdg_config_path}")

    # 3. Iterate and find the first valid path
    for path_to_try in potential_paths_to_check:
        log.info(f"Checking PPSSPP SAVEDATA location: {path_to_try}")
        if os.path.isdir(path_to_try):
            log.info(f"Found valid PPSSPP SAVEDATA at: {path_to_try}")
            save_data_base_path = path_to_try
            break # Use the first one found
    
    if not save_data_base_path:
        log.warning(f"Could not find any valid PPSSPP SAVEDATA directory after checking: {potential_paths_to_check}")
        return [] # Exit if no valid path is found

    try:
        # --- Proceed with listing profiles using the found save_data_base_path ---
        log.info(f"Scanning directory for game IDs: {save_data_base_path}")
        # Elenca le sottocartelle (ID dei giochi) dentro SAVEDATA
        for item_name in os.listdir(save_data_base_path):
            item_path = os.path.join(save_data_base_path, item_name)

            if os.path.isdir(item_path):
                # Extract base game ID
                base_game_id = None
                if item_name.endswith("DATA00"):
                    base_game_id = item_name[:-6]
                elif item_name.endswith("PROFILE00"):
                    base_game_id = item_name[:-9]
                
                if not base_game_id:
                    log.debug(f"Skipping folder '{item_name}' as it doesn't match known suffixes (DATA00, PROFILE00).")
                    continue # Skip folders we don't recognize pattern of
                
                game_id_for_display = item_name # Keep original folder name for logging/debug if needed
                log.debug(f"Found potential PPSSPP folder: {game_id_for_display} (Base ID: {base_game_id}) at {item_path}")

                # Check if we already have an entry for this base_game_id
                if base_game_id not in profiles_dict:
                    # First time seeing this game ID, create new profile entry
                    profiles_dict[base_game_id] = {
                        'emulator': EMULATOR_NAME,
                        'id': base_game_id, # Use base ID as the main identifier
                        'name': base_game_id, # Default name is the base ID
                        'paths': [item_path] # Initialize paths list
                    }
                    # Attempt to parse SFO for the name from this first path found
                    sfo_path = os.path.join(item_path, "PARAM.SFO")
                    if os.path.isfile(sfo_path):
                        try:
                            extracted_title = parse_param_sfo(sfo_path)
                            if extracted_title:
                                profiles_dict[base_game_id]['name'] = extracted_title
                                log.debug(f"  Successfully parsed PARAM.SFO for {base_game_id}: '{extracted_title}'")
                            else:
                                log.warning(f"  parse_param_sfo returned None or empty for {sfo_path} (Base ID: {base_game_id})")
                        except Exception as sfo_error:
                            log.error(f"  Error parsing {sfo_path} (Base ID: {base_game_id}): {sfo_error}", exc_info=False)
                    else:
                        log.debug(f"  PARAM.SFO not found in first path {item_path} for {base_game_id}")
                else:
                    # Base ID already exists, just add this path to the list
                    profiles_dict[base_game_id]['paths'].append(item_path)
                    log.debug(f"  Added path {item_path} to existing profile for {base_game_id}")
                    # Optional: Try parsing SFO again if name is still the ID and SFO exists here
                    if profiles_dict[base_game_id]['name'] == base_game_id:
                        sfo_path = os.path.join(item_path, "PARAM.SFO")
                        if os.path.isfile(sfo_path):
                            log.debug(f"  Attempting SFO parse from additional path {item_path} for {base_game_id}")
                            try:
                                extracted_title = parse_param_sfo(sfo_path)
                                if extracted_title:
                                    profiles_dict[base_game_id]['name'] = extracted_title
                                    log.debug(f"    Successfully parsed PARAM.SFO from additional path: '{extracted_title}'")
                            except Exception as sfo_error:
                                log.error(f"    Error parsing SFO from additional path {sfo_path}: {sfo_error}", exc_info=False)


    except FileNotFoundError:
        log.info(f"Standard PPSSPP save path component not found.")
    except Exception as e:
        log.error(f"Error scanning for PPSSPP profiles: {e}", exc_info=True)

    # Convert the dictionary values back to a list
    profiles = list(profiles_dict.values())
    log.info(f"Found {len(profiles)} unique PPSSPP game profile(s) after grouping.")
    # Log the grouped paths for clarity
    for p in profiles:
        log.debug(f"  Profile '{p['name']}' (ID: {p['id']}) includes paths: {p['paths']}")
        
    return profiles

# Esempio di utilizzo (per test)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.info("--- Running PPSSPP Test --- ")
    found_profiles = find_ppsspp_profiles()
    if found_profiles:
        print("\nFound PPSSPP Profiles (Grouped):")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}")
            print(f"    Paths: {p['paths']}") # Show the list of paths
    else:
        print("\nNo PPSSPP profiles found in standard location.")
