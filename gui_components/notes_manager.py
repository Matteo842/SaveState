# gui_components/notes_manager.py
# -*- coding: utf-8 -*-
"""
Manages profile notes stored in a separate JSON file (profile_notes.json).
Follows the same pattern as favorites_manager.py.
Notes are stored as {profile_name: note_text_string}.
"""

import os
import json
import logging
import config
from datetime import datetime

# --- Notes File Name and Path (dynamic using settings_manager) ---
NOTES_FILENAME = "profile_notes.json"
try:
    import settings_manager as _sm
    _ACTIVE_CONFIG_DIR = _sm.get_active_config_dir()
except Exception:
    _ACTIVE_CONFIG_DIR = config.get_app_data_folder()
    logging.warning("Failed to import settings_manager for active config dir; falling back to AppData.")

if _ACTIVE_CONFIG_DIR:
    NOTES_FILE_PATH = os.path.join(_ACTIVE_CONFIG_DIR, NOTES_FILENAME)
else:
    logging.error("Unable to determine configuration directory for notes. Using relative path.")
    NOTES_FILE_PATH = os.path.abspath(NOTES_FILENAME)
logging.info(f"Profile notes file path in use: {NOTES_FILE_PATH}")
# --- End of Notes File Path Definition ---

_notes_cache = {}  # Internal cache to avoid continuous disk reads
_cache_loaded = False  # Flag to know if cache has been loaded


def _get_existing_profile_names():
    """Return a set with current profile names; empty set if not available."""
    try:
        import core_logic
        profiles_dict = core_logic.load_profiles()
        if isinstance(profiles_dict, dict):
            return set(profiles_dict.keys())
    except Exception as e:
        logging.debug(f"Unable to retrieve current profile names for notes prune: {e}")
    return set()


def _prune_stale_notes(notes_dict: dict) -> dict:
    """Return a cleaned copy of notes_dict keeping only existing profiles with non-empty notes."""
    if not isinstance(notes_dict, dict):
        return {}
    try:
        existing = _get_existing_profile_names()
        if not existing:
            # Cannot resolve profiles, return original filtering empty strings
            return {k: str(v) for k, v in notes_dict.items() if v and str(v).strip()}
        cleaned = {name: str(text) for name, text in notes_dict.items()
                   if name in existing and text and str(text).strip()}
        return cleaned
    except Exception:
        return {k: str(v) for k, v in notes_dict.items() if v and str(v).strip()}


def load_notes():
    """Loads profile notes from NOTES_FILE_PATH.
       Returns a dictionary {profile_name: note_text}.
    """
    global _notes_cache, _cache_loaded
    if _cache_loaded:
        return _notes_cache.copy()

    notes = {}
    if os.path.exists(NOTES_FILE_PATH):
        try:
            with open(NOTES_FILE_PATH, 'r', encoding='utf-8') as f:
                notes = json.load(f)
            if not isinstance(notes, dict):
                logging.warning(f"Notes file '{NOTES_FILE_PATH}' does not contain a valid dictionary. Reset.")
                notes = {}

            # Auto-prune stale entries
            cleaned = _prune_stale_notes(notes)
            if cleaned != notes:
                try:
                    os.makedirs(os.path.dirname(NOTES_FILE_PATH), exist_ok=True)
                    with open(NOTES_FILE_PATH, 'w', encoding='utf-8') as wf:
                        json.dump(cleaned, wf, indent=4, ensure_ascii=False, sort_keys=True)
                    logging.info(f"Pruned notes file: removed {len(notes) - len(cleaned)} stale entries.")
                    notes = cleaned
                except Exception as e_rewrite:
                    logging.warning(f"Unable to rewrite pruned notes file: {e_rewrite}")

            logging.info(f"Loaded {len(notes)} profile notes from '{NOTES_FILE_PATH}'.")
        except json.JSONDecodeError:
            logging.warning(f"Notes file '{NOTES_FILE_PATH}' is corrupted or empty. Reset.")
            notes = {}
        except Exception as e:
            logging.error(f"Error loading notes from '{NOTES_FILE_PATH}': {e}")
            notes = {}
    else:
        logging.info(f"Notes file '{NOTES_FILE_PATH}' not found. Starting with empty notes.")

    _notes_cache = notes.copy()
    _cache_loaded = True
    return notes


def save_notes(notes_dict):
    """Saves the profile notes dictionary to NOTES_FILE_PATH.
       Returns True if saving succeeds, False otherwise.
    """
    global _notes_cache
    if not isinstance(notes_dict, dict):
        logging.error("Attempt to save invalid notes (not a dictionary).")
        return False
    try:
        notes_to_write = _prune_stale_notes(notes_dict)
        os.makedirs(os.path.dirname(NOTES_FILE_PATH), exist_ok=True)
        with open(NOTES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(notes_to_write, f, indent=4, ensure_ascii=False, sort_keys=True)
        logging.info(f"Saved {len(notes_to_write)} notes to '{NOTES_FILE_PATH}'.")
        _notes_cache = notes_to_write.copy()
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
                try:
                    import core_logic
                    core_logic._mirror_json_to_backup_root("profile_notes.json", notes_to_write, rotation=rotation)
                except Exception as e_core:
                    logging.warning(f"Mirror notes to backup root failed: {e_core}")
        except Exception as e_mirror:
            logging.warning(f"Unable to mirror notes to backup root: {e_mirror}")
        return True
    except Exception as e:
        logging.error(f"Error saving notes to '{NOTES_FILE_PATH}': {e}")
        return False


def get_note(profile_name):
    """Returns the note text for a profile, or empty string if none."""
    notes = load_notes()
    return notes.get(profile_name, "")


def has_note(profile_name):
    """Returns True if the profile has a non-empty note."""
    return bool(get_note(profile_name))


def set_note(profile_name, text):
    """Sets or removes a note for a profile. Empty text removes the note."""
    notes = load_notes()
    text = text.strip() if text else ""
    if text:
        notes[profile_name] = text
    elif profile_name in notes:
        del notes[profile_name]
    logging.info(f"{'Set' if text else 'Removed'} note for profile '{profile_name}'.")
    return save_notes(notes)


def remove_note(profile_name):
    """Removes a note for a profile (when profile is deleted)."""
    notes = load_notes()
    if profile_name in notes:
        del notes[profile_name]
        logging.info(f"Removed note for deleted profile '{profile_name}'.")
        return save_notes(notes)
    return True  # Success even if no note existed
