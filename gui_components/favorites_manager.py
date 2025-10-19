# favorites_manager.py
# -*- coding: utf-8 -*-

import os
import json
import logging
import config # Importa config per ottenere la cartella dati
from datetime import datetime

# --- Favorites File Name and Path (dynamic using settings_manager) ---
FAVORITES_FILENAME = "favorites_status.json"
try:
    import settings_manager as _sm
    _ACTIVE_CONFIG_DIR = _sm.get_active_config_dir()
except Exception:
    _ACTIVE_CONFIG_DIR = config.get_app_data_folder()
    logging.warning("Failed to import settings_manager for active config dir; falling back to AppData.")

if _ACTIVE_CONFIG_DIR:
    FAVORITES_FILE_PATH = os.path.join(_ACTIVE_CONFIG_DIR, FAVORITES_FILENAME)
else:
    logging.error("Unable to determine configuration directory for favorites. Using relative path.")
    FAVORITES_FILE_PATH = os.path.abspath(FAVORITES_FILENAME)
logging.info(f"Favorites file path in use: {FAVORITES_FILE_PATH}")
# --- End of Favorites File Path Definition ---

_favorites_cache = {} # Internal cache to avoid continuous disk reads
_cache_loaded = False # Flag to know if cache has been loaded

def _get_existing_profile_names():
    """Return a set with current profile names; empty set if not available.

    Uses a lazy import of core_logic to avoid import cycles.
    """
    try:
        import core_logic
        profiles_dict = core_logic.load_profiles()
        if isinstance(profiles_dict, dict):
            return set(profiles_dict.keys())
    except Exception as e:
        logging.debug(f"Unable to retrieve current profile names for favorites prune: {e}")
    return set()


def _prune_stale_favorites(fav_dict: dict) -> dict:
    """Return a cleaned copy of fav_dict keeping only existing profiles.

    - Drops entries for profiles that no longer exist
    - Coerces values to bool to avoid unexpected types
    """
    if not isinstance(fav_dict, dict):
        return {}
    try:
        existing = _get_existing_profile_names()
        if not existing:
            # If we cannot resolve profiles, return the original dict coerced to bools
            return {k: bool(v) for k, v in fav_dict.items()}
        cleaned = {name: bool(is_fav) for name, is_fav in fav_dict.items() if name in existing}
        return cleaned
    except Exception:
        return {k: bool(v) for k, v in fav_dict.items()}

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

            # Auto-prune and rewrite file if necessary
            cleaned = _prune_stale_favorites(favorites_status)
            if cleaned != favorites_status:
                try:
                    os.makedirs(os.path.dirname(FAVORITES_FILE_PATH), exist_ok=True)
                    with open(FAVORITES_FILE_PATH, 'w', encoding='utf-8') as wf:
                        json.dump(cleaned, wf, indent=4, ensure_ascii=False, sort_keys=True)
                    logging.info(f"Pruned and rewrote favorites file: removed {len(favorites_status) - len(cleaned)} stale entries.")
                    favorites_status = cleaned
                except Exception as e_rewrite:
                    logging.warning(f"Unable to rewrite pruned favorites file: {e_rewrite}")

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
        # Clean before saving so the file doesn't accumulate deleted profiles
        favorites_to_write = _prune_stale_favorites(favorites_dict)
        # Ensure the directory exists
        os.makedirs(os.path.dirname(FAVORITES_FILE_PATH), exist_ok=True)
        with open(FAVORITES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(favorites_to_write, f, indent=4, ensure_ascii=False, sort_keys=True)
        logging.info(f"Saved {len(favorites_to_write)} favorites to '{FAVORITES_FILE_PATH}'.")
        _favorites_cache = favorites_to_write.copy() # Update cache after successful saving
        # Mirror only when NOT in portable mode
        try:
            do_mirror = True
            try:
                import settings_manager as _smirror
                if _smirror.is_portable_mode():
                    do_mirror = False
            except Exception:
                pass
            if do_mirror:
                rotation = 0
                try:
                    import settings_manager as _sm4
                    settings, _ = _sm4.load_settings()
                    rotation = int(settings.get("mirror_rotation_keep", 0))
                except Exception:
                    rotation = 0
                # Use core_logic helper to mirror into backup root
                try:
                    import core_logic
                    core_logic._mirror_json_to_backup_root("favorites_status.json", favorites_to_write, rotation=rotation)
                except Exception as e_core:
                    logging.warning(f"Mirror favorites to backup root failed: {e_core}")
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