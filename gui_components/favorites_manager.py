# favorites_manager.py
# -*- coding: utf-8 -*-

import os
import json
import logging
import config # Importa config per ottenere la cartella dati
from datetime import datetime

# --- Favorites File Name and Path ---
FAVORITES_FILENAME = "favorites_status.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Use the same function from config
if APP_DATA_FOLDER:
    FAVORITES_FILE_PATH = os.path.join(APP_DATA_FOLDER, FAVORITES_FILENAME)
else:
    # Fallback if data folder not found
    logging.error("Unable to determine APP_DATA_FOLDER for favorites. Using relative path.")
    FAVORITES_FILE_PATH = os.path.abspath(FAVORITES_FILENAME)
logging.info(f"Favorites file path in use: {FAVORITES_FILE_PATH}")
# --- End of Favorites File Path Definition ---

_favorites_cache = {} # Internal cache to avoid continuous disk reads
_cache_loaded = False # Flag to know if cache has been loaded

def load_favorites():
    """Loads favorites status from FAVORITES_FILE_PATH.
       Returns a dictionary {profile_name: bool}.
    """
    global _favorites_cache, _cache_loaded
    if _cache_loaded:
         #logging.debug("Restituzione cache preferiti.")
         return _favorites_cache.copy() # Returns a copy of the cache

    favorites_status = {}
    if os.path.exists(FAVORITES_FILE_PATH):
        try:
            with open(FAVORITES_FILE_PATH, 'r', encoding='utf-8') as f:
                favorites_status = json.load(f)
            if not isinstance(favorites_status, dict):
                 logging.warning(f"Favorites file '{FAVORITES_FILE_PATH}' does not contain a valid dictionary. Reset.")
                 favorites_status = {}
            # Verifica che i valori siano booleani (opzionale ma consigliato)
            #for key, value in list(favorites_status.items()):
            #    if not isinstance(value, bool):
            #        logging.warning(f"Valore non booleano per '{key}' nel file preferiti. Rimosso.")
            #        del favorites_status[key]

            logging.info(f"Loaded {len(favorites_status)} favorites from '{FAVORITES_FILE_PATH}'.")
        except json.JSONDecodeError:
            logging.warning(f"Favorites file '{FAVORITES_FILE_PATH}' is corrupted or empty. Reset.")
            favorites_status = {}
        except Exception as e:
            logging.error(f"Error loading favorites from '{FAVORITES_FILE_PATH}': {e}")
            favorites_status = {}
    else:
        logging.info(f"Favorites file '{FAVORITES_FILE_PATH}' not found. Starting with empty list.")

    _favorites_cache = favorites_status.copy() # Update cache
    _cache_loaded = True
    return favorites_status # Returns the just loaded dictionary

def save_favorites(favorites_dict):
    """Saves the favorites status dictionary in FAVORITES_FILE_PATH.
       Returns True if saving succeeds, False otherwise.
    """
    global _favorites_cache
    if not isinstance(favorites_dict, dict):
        logging.error("Attempt to save invalid favorites status (not a dictionary).")
        return False
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(FAVORITES_FILE_PATH), exist_ok=True)
        with open(FAVORITES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(favorites_dict, f, indent=4, ensure_ascii=False)
        logging.info(f"Saved {len(favorites_dict)} favorites to '{FAVORITES_FILE_PATH}'.")
        _favorites_cache = favorites_dict.copy() # Update cache after successful saving
        # Mirror in backup root for resiliency
        try:
            backup_root = None
            try:
                import settings_manager
                settings, _ = settings_manager.load_settings()
                backup_root = settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
            except Exception:
                backup_root = getattr(config, "BACKUP_BASE_DIR", None)
            if backup_root:
                mirror_dir = os.path.join(backup_root, ".savestate")
                os.makedirs(mirror_dir, exist_ok=True)
                mirror_path = os.path.join(mirror_dir, "favorites_status.json")
                with open(mirror_path, 'w', encoding='utf-8') as mf:
                    json.dump(favorites_dict, mf, indent=4, ensure_ascii=False)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                snap_path = os.path.join(mirror_dir, f"favorites_status-{ts}.json")
                try:
                    with open(snap_path, 'w', encoding='utf-8') as sf:
                        json.dump(favorites_dict, sf, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                # Rotate keep last 10
                try:
                    candidates = [f for f in os.listdir(mirror_dir) if f.startswith("favorites_status-") and f.endswith(".json")]
                    candidates.sort(reverse=True)
                    for old in candidates[10:]:
                        try: os.remove(os.path.join(mirror_dir, old))
                        except Exception: pass
                except Exception:
                    pass
        except Exception as e_mirror:
            logging.warning(f"Unable to mirror favorites to backup root: {e_mirror}")
        return True
    except Exception as e:
        logging.error(f"Error saving favorites to '{FAVORITES_FILE_PATH}': {e}")
        return False

def is_favorite(profile_name):
    """Checks if a profile is a favorite (loads if necessary)."""
    favorites = load_favorites() # Use the function that handles the cache
    return favorites.get(profile_name, False) # Default to False if not present

def set_favorite_status(profile_name, is_fav):
    """Sets the favorite status for a profile and saves."""
    if not isinstance(is_fav, bool):
         logging.warning(f"Attempt to set favorite status to non-boolean ({is_fav}) for '{profile_name}'. Ignored.")
         return False # Indicates failure

    favorites = load_favorites() # Load current status (or cache)
    if favorites.get(profile_name) == is_fav:
         #logging.debug(f"Stato preferito per '{profile_name}' è già {is_fav}. Nessun salvataggio necessario.")
         return True # No change, but operation "succeeded"

    favorites[profile_name] = is_fav
    logging.info(f"Set favorite status for '{profile_name}' to {is_fav}.")
    return save_favorites(favorites) # Save the updated dictionary

def toggle_favorite(profile_name):
    """Inverts the favorite status for a profile and saves."""
    favorites = load_favorites() # Load current status (or cache)
    current_status = favorites.get(profile_name, False)
    new_status = not current_status
    return set_favorite_status(profile_name, new_status) # Use the set function to save

def remove_profile(profile_name):
    """Removes a profile from the favorites file (when a profile is deleted)."""
    favorites = load_favorites()
    if profile_name in favorites:
        del favorites[profile_name]
        logging.info(f"Removed '{profile_name}' from favorites file.")
        return save_favorites(favorites)
    #logging.debug(f"Tentativo di rimuovere profilo non preferito '{profile_name}'. Nessuna azione.")
    return True # Consider success even if it wasn't there