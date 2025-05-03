import os
import re
import glob
import logging
import json

# Configure basic logging for this module
log = logging.getLogger(__name__)

# Path to the Citra titles JSON database
CITRA_TITLES_JSON_PATH = os.path.join(os.path.dirname(__file__), "citra_titles.json") # Moved to emulator_utils dir

# Cache for the loaded titles
_citra_titles_cache: dict = None

def load_citra_titles() -> dict:
    """Loads the Citra titles database from the JSON file."""
    global _citra_titles_cache
    if _citra_titles_cache is not None:
        return _citra_titles_cache

    if not os.path.exists(CITRA_TITLES_JSON_PATH):
        log.warning(f"Citra titles database not found at: {CITRA_TITLES_JSON_PATH}")
        log.warning("Run the update_citra_db.py script to generate it.")
        _citra_titles_cache = {}
        return _citra_titles_cache

    try:
        with open(CITRA_TITLES_JSON_PATH, 'r', encoding='utf-8') as f:
            _citra_titles_cache = json.load(f)
        log.info(f"Successfully loaded {len(_citra_titles_cache)} titles from {CITRA_TITLES_JSON_PATH}")
        return _citra_titles_cache
    except json.JSONDecodeError:
        log.exception(f"Error decoding JSON from {CITRA_TITLES_JSON_PATH}. Please check the file integrity.")
        _citra_titles_cache = {}
        return _citra_titles_cache
    except Exception as e:
        log.exception(f"Failed to load Citra titles database: {e}")
        _citra_titles_cache = {}
        return _citra_titles_cache

def _get_citra_sdmc_path(user_profile_path=None):
    """Gets the default Citra/Azahar SDMC path, checking Azahar first."""
    appdata_path = os.getenv('APPDATA', '')
    if not appdata_path:
        log.error("Could not determine APPDATA environment variable.")
        return None

    azahar_base_path = os.path.join(appdata_path, 'Azahar')
    citra_base_path = os.path.join(appdata_path, 'Citra')
    sdmc_path = None

    if os.path.isdir(azahar_base_path):
        log.info(f"Found Azahar directory: {azahar_base_path}")
        sdmc_path = os.path.join(azahar_base_path, 'sdmc')
    elif os.path.isdir(citra_base_path):
        log.info(f"Found Citra directory: {citra_base_path}")
        sdmc_path = os.path.join(citra_base_path, 'sdmc')
    else:
        log.error(f"Neither Azahar ('{azahar_base_path}') nor Citra ('{citra_base_path}') directory found in APPDATA.")
        return None # Indicate failure

    log.debug(f"Using SDMC path: {sdmc_path}")
    return sdmc_path


def find_citra_profiles(user_profile_path=None) -> list:
    """Finds Citra game save directories and uses the JSON database to get game names."""
    profiles_list = []
    
    # Load the titles database
    citra_titles = load_citra_titles()
    
    # Determine the base path for Citra saves
    sdmc_path = _get_citra_sdmc_path(user_profile_path)
    
    # Added check if sdmc_path could be determined
    if not sdmc_path:
        log.error("Could not determine Citra SDMC path. Aborting profile search.")
        return []
        
    # Pattern to find the base 'title' directory containing game saves
    save_root_pattern = os.path.join(
        sdmc_path,
        'Nintendo 3DS',
        '*',  # Console ID (variable)
        '*',  # Internal ID (variable)
        'title',
        '00040000'  # Standard save title prefix
    )

    potential_roots = glob.glob(save_root_pattern)

    if not potential_roots:
        log.info(f"Citra save directory pattern not found: {save_root_pattern}")
        return []

    for save_root in potential_roots:
        if not os.path.isdir(save_root):
            continue

        try:
            for title_id_folder in os.listdir(save_root):
                title_id_path = os.path.join(save_root, title_id_folder)
                
                if os.path.isdir(title_id_path) and re.match(r"^[0-9a-fA-F]{8}$", title_id_folder):
                    data_dir_standard = os.path.join(title_id_path, 'data', '00000001')
                    data_dir_alt = os.path.join(title_id_path, 'data')

                    save_path_to_use = None
                    if os.path.isdir(data_dir_standard):
                        save_path_to_use = data_dir_standard
                    elif os.path.isdir(data_dir_alt):
                         # Check if standard path exists within alt path (avoid duplicates)
                        if not os.path.exists(data_dir_standard):
                            save_path_to_use = data_dir_alt
                    
                    if save_path_to_use:
                        # Use Title ID as the key
                        game_id = title_id_folder 
                        # Get game name from JSON database, fallback to full ID
                        full_game_id = f"00040000{game_id.lower()}"
                        game_name = citra_titles.get(full_game_id, full_game_id) # Use .get() with fallback
                        
                        # Check if the actual save data directory exists
                        if os.path.isdir(save_path_to_use):
                            log.debug(f"Found potential Citra profile: ID='{full_game_id}', Name='{game_name}', Path='{save_path_to_use}' (Directory)")
                            profile_entry = {
                                'id': full_game_id, # Use the full 16-char ID
                                'name': game_name,
                                'paths': [save_path_to_use] 
                            }
                            profiles_list.append(profile_entry)
                        else:
                            log.warning(f"Save directory not found: {save_path_to_use}. Skipping profile.")
                            continue # Skip profile if directory not found

        except FileNotFoundError:
            log.error(f"Error accessing Citra save directory structure within: {save_root}")
        except OSError as e:
            log.error(f"Error reading Citra save directory {save_root}: {e}")

    if not profiles_list:
        log.info(f"No Citra game profiles found in expected locations under {sdmc_path}")

    return profiles_list # Return the list of dictionaries

# Example usage (for testing):
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    found_profiles = find_citra_profiles()
    if found_profiles:
        print("Found Citra Profiles:")
        for profile in found_profiles:
            print(f"  ID: {profile.get('id')}, Name: {profile.get('name')}, Path: {profile.get('paths')}")
    else:
        print("No Citra profiles found.")
