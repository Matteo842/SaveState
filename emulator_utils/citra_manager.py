import os
import re
import glob
import logging
import json
import platform
import pickle

from .obfuscation_utils import xor_bytes

# Configure basic logging for this module
log = logging.getLogger(__name__)

# Path to the Citra titles JSON database
CITRA_TITLES_JSON_PATH = os.path.join(os.path.dirname(__file__), "citra_titles.json")
CITRA_TITLES_PKL_PATH = os.path.join(os.path.dirname(__file__), "citra_titles_map.pkl")

# Cache for the loaded titles
_citra_titles_cache: dict = None

def load_citra_titles() -> dict:
    """Loads the Citra titles database from JSON or PKL file."""
    global _citra_titles_cache
    if _citra_titles_cache is not None:
        return _citra_titles_cache

    loaded_titles = {}
    loaded_from_json = False

    # Try loading from JSON first
    if os.path.exists(CITRA_TITLES_JSON_PATH):
        try:
            with open(CITRA_TITLES_JSON_PATH, 'r', encoding='utf-8') as f:
                loaded_titles = json.load(f)
            log.info(f"Successfully loaded {len(loaded_titles)} titles from {CITRA_TITLES_JSON_PATH}")
            loaded_from_json = True
        except json.JSONDecodeError:
            log.exception(f"Error decoding JSON from {CITRA_TITLES_JSON_PATH}. Will attempt PKL.")
        except Exception as e:
            log.exception(f"Failed to load Citra titles from JSON {CITRA_TITLES_JSON_PATH}: {e}. Will attempt PKL.")
    else:
        log.info(f"Citra titles JSON not found at: {CITRA_TITLES_JSON_PATH}. Attempting PKL.")

    # If JSON loading failed or file not found, try PKL
    if not loaded_from_json:
        if os.path.exists(CITRA_TITLES_PKL_PATH):
            try:
                with open(CITRA_TITLES_PKL_PATH, 'rb') as pf:
                    obf_map = pickle.load(pf)
                
                temp_loaded_titles = {}
                for tid, ob_name in obf_map.items():
                    try:
                        game_name = xor_bytes(ob_name).decode('utf-8')
                        temp_loaded_titles[tid] = game_name # Assuming tid is already correct format
                    except UnicodeDecodeError:
                        log.warning(f"Could not decode game name for TID {tid} from {CITRA_TITLES_PKL_PATH}. Skipping.")
                    except Exception as e_dec:
                        log.warning(f"Error deobfuscating/processing TID {tid} from {CITRA_TITLES_PKL_PATH}: {e_dec}. Skipping.")
                loaded_titles = temp_loaded_titles
                log.info(f"Successfully loaded and deobfuscated {len(loaded_titles)} titles from {CITRA_TITLES_PKL_PATH}")
            except pickle.UnpicklingError as e_pkl_load:
                log.exception(f"Error loading pickle data from {CITRA_TITLES_PKL_PATH}.")
                loaded_titles = {} # Ensure cache is empty on error
            except Exception as e_pkl:
                log.exception(f"Failed to load Citra titles from PKL {CITRA_TITLES_PKL_PATH}: {e_pkl}.")
                loaded_titles = {} # Ensure cache is empty on error
        else:
            log.warning(f"Citra titles PKL not found at: {CITRA_TITLES_PKL_PATH}. Title map will be empty.")
            loaded_titles = {}

    _citra_titles_cache = loaded_titles
    if not _citra_titles_cache:
        log.warning("Citra titles cache is empty after attempting all loading methods.")
    return _citra_titles_cache

def _get_citra_sdmc_path(user_profile_path=None):
    """Gets the default Citra/Azahar SDMC path, checking standard locations based on OS."""
    system = platform.system()
    user_home = os.path.expanduser("~")
    sdmc_path_candidate = None

    if system == "Windows":
        appdata_path = os.getenv('APPDATA', '')
        if not appdata_path:
            log.error("Could not determine APPDATA environment variable on Windows.")
            return None

        # Windows: Check Azahar first, then Citra
        azahar_base_path = os.path.join(appdata_path, 'Azahar')
        citra_base_path = os.path.join(appdata_path, 'Citra')

        if os.path.isdir(azahar_base_path):
            log.info(f"Found Azahar directory: {azahar_base_path}")
            sdmc_path_candidate = os.path.join(azahar_base_path, 'sdmc')
        elif os.path.isdir(citra_base_path):
            log.info(f"Found Citra directory: {citra_base_path}")
            sdmc_path_candidate = os.path.join(citra_base_path, 'sdmc')
        else:
            log.error(f"Neither Azahar ('{azahar_base_path}') nor Citra ('{citra_base_path}') directory found in APPDATA.")
            return None

    elif system == "Linux":
        # Linux: Check standard XDG data path, then Flatpak data path
        paths_to_check_linux = [
            os.path.join(user_home, '.local', 'share', 'citra-emu', 'sdmc'), # Standard XDG
            os.path.join(user_home, '.var', 'app', 'org.citra_emu.citra', 'data', 'citra-emu', 'sdmc'), # Flatpak
            # Less common for sdmc, but as a fallback for config locations
            os.path.join(user_home, '.config', 'citra-emu', 'sdmc'),
            os.path.join(user_home, '.var', 'app', 'org.citra_emu.citra', 'config', 'citra-emu', 'sdmc')
        ]
        for path_linux in paths_to_check_linux:
            if os.path.isdir(path_linux):
                log.info(f"Found Citra SDMC directory on Linux: {path_linux}")
                sdmc_path_candidate = path_linux
                break
        if not sdmc_path_candidate:
            log.error(f"Citra SDMC directory not found in standard Linux locations.")
            return None

    elif system == "Darwin": # macOS
        macos_path = os.path.join(user_home, 'Library', 'Application Support', 'Citra', 'sdmc')
        if os.path.isdir(macos_path):
            log.info(f"Found Citra SDMC directory on macOS: {macos_path}")
            sdmc_path_candidate = macos_path
        else:
            log.error(f"Citra SDMC directory not found at: {macos_path}")
            return None
            
    else:
        log.error(f"Unsupported operating system for Citra path detection: {system}")
        return None

    if sdmc_path_candidate and os.path.isdir(sdmc_path_candidate):
        log.debug(f"Using SDMC path: {sdmc_path_candidate}")
        return sdmc_path_candidate
    else:
        log.error(f"Determined SDMC path candidate '{sdmc_path_candidate}' is not a valid directory. Citra saves cannot be located.")
        return None


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
