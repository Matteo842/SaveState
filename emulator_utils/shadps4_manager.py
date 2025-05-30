# emulator_utils/shadps4_manager.py
# -*- coding: utf-8 -*-

import logging
import os
import json
import pickle
from typing import Dict, Optional
from .obfuscation_utils import xor_bytes

log = logging.getLogger(__name__)

# Load PS4 game titles from JSON or encrypted PKL file
def load_ps4_game_titles() -> Dict[str, str]:
    """Load PS4 game titles from JSON or encrypted PKL file."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, 'ps4_game_list.json')
    pkl_path = os.path.join(current_dir, 'ps4_game_map.pkl')

    # Try JSON first
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('games', {})
        except Exception as e:
            log.error(f"Error loading PS4 game list from JSON: {e}")

    # Try PKL next
    if os.path.exists(pkl_path):
        try:
            with open(pkl_path, 'rb') as pf:
                obf_map = pickle.load(pf)
        except Exception as e:
            log.error(f"Error loading PS4 game titles from PKL: {e}")
        else:
            titles = {}
            for game_id, ob_name in obf_map.items():
                try:
                    game_name = xor_bytes(ob_name).decode('utf-8')
                    titles[game_id] = game_name
                except Exception as de:
                    log.warning(f"Error deobfuscating PS4 game title for ID {game_id}: {de}")
            log.info(f"Loaded {len(titles)} PS4 game titles from PKL.")
            return titles

    log.warning(f"No PS4 game list found (JSON or PKL) at {current_dir}")
    return {}

# Load the game titles when the module is imported
PS4_GAME_TITLES = load_ps4_game_titles()

def find_shadps4_profiles(custom_path: Optional[str]) -> Dict[str, Dict[str, str]]:
    """
    Finds ShadPS4 game save profiles.

    ShadPS4 save structure is expected to be:
    [custom_path]/user/savedata/[user_id]/[game_id_CUSAXXXXX]/

    Args:
        custom_path: The root installation path of ShadPS4.

    Returns:
        A dictionary where keys are game IDs (e.g., 'CUSA03173')
        and values are dictionaries, each containing 'id', 'name' (game title if known),
        and 'paths' (absolute paths to the game's save data directories).
        Returns an empty dictionary if the path is not found or not valid.
    """
    profiles: Dict[str, Dict[str, str]] = {}

    if not custom_path:
        log.info("ShadPS4 custom_path not provided. Cannot locate saves.")
        return profiles

    if not os.path.isdir(custom_path):
        log.warning(f"ShadPS4 custom_path '{custom_path}' does not exist or is not a directory.")
        return profiles

    base_save_path = os.path.join(custom_path, "user", "savedata")

    if not os.path.isdir(base_save_path):
        log.info(f"ShadPS4 save data directory not found at '{base_save_path}'. Looked for 'user/savedata' under custom path.")
        return profiles

    try:
        for user_id_folder in os.listdir(base_save_path):
            user_save_path = os.path.join(base_save_path, user_id_folder)
            if os.path.isdir(user_save_path):
                for game_id_folder in os.listdir(user_save_path):
                    # Basic check for PS4 Game ID format (CUSA, CUSX, etc.)
                    if game_id_folder.startswith("CUSA") and os.path.isdir(os.path.join(user_save_path, game_id_folder)):
                        game_save_path = os.path.join(user_save_path, game_id_folder)
                        
                        # Get game title from our dictionary, or use ID if not found
                        game_title = PS4_GAME_TITLES.get(game_id_folder, game_id_folder)
                        if game_title == game_id_folder:
                            log.debug(f"Game title not found for ID: {game_id_folder}")
                        
                        profiles[game_id_folder] = {
                            'id': game_id_folder,
                            'name': game_title,
                            'paths': [game_save_path]
                        }
                        log.debug(f"Found ShadPS4 game: {game_id_folder} ({game_title}) at {game_save_path}")
    except OSError as e:
        log.error(f"Error accessing ShadPS4 save directory '{base_save_path}': {e}")
        return {}

    if not profiles:
        log.info(f"No ShadPS4 game profiles found in '{base_save_path}'.")

    return profiles

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                        handlers=[logging.StreamHandler()])

    # Create dummy directory structure for testing
    test_shadps4_path = "D:\\shadps4_test_install"
    dummy_save_path = os.path.join(test_shadps4_path, "user", "savedata", "1", "CUSA03173")
    os.makedirs(dummy_save_path, exist_ok=True)
    with open(os.path.join(dummy_save_path, "save.dat"), "w") as f:
        f.write("dummy save data")
    
    dummy_save_path_2 = os.path.join(test_shadps4_path, "user", "savedata", "1", "CUSA01715")
    os.makedirs(dummy_save_path_2, exist_ok=True)

    dummy_save_path_other_user = os.path.join(test_shadps4_path, "user", "savedata", "2", "CUSA00341")
    os.makedirs(dummy_save_path_other_user, exist_ok=True)

    log.info(f"--- Testing find_shadps4_profiles with path: {test_shadps4_path} ---")
    found_profiles = find_shadps4_profiles(test_shadps4_path)

    if found_profiles:
        print("\n--- Found ShadPS4 Profiles ---")
        for game_id, profile_details in found_profiles.items():
            print(f"- Game ID (key): {game_id}")
            print(f"  Profile ID:    {profile_details.get('id')}")
            print(f"  Display Name:  {profile_details.get('name')}")
            print(f"  Paths:         {profile_details.get('paths')}")
            print("-" * 20)
    else:
        print("\nNo ShadPS4 profiles found.")

    # Test with non-existent path
    log.info("\n--- Testing find_shadps4_profiles with non-existent path ---")
    found_profiles_non_existent = find_shadps4_profiles("D:\\non_existent_shadps4")
    if not found_profiles_non_existent:
        print("Correctly found no profiles for non-existent path.")

    # Clean up dummy directories (optional)
    # import shutil
    # shutil.rmtree(test_shadps4_path, ignore_errors=True)
    # log.info(f"Cleaned up dummy directory: {test_shadps4_path}")
