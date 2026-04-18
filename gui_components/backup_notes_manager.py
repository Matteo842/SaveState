# gui_components/backup_notes_manager.py
# -*- coding: utf-8 -*-
"""
Manages per-backup notes stored in a separate JSON file (backup_notes.json).
Follows the same pattern as notes_manager.py and lock_backup_manager.py.

Notes are stored as {normalized_backup_path: note_text_string}.
The key is the normalized full path of the backup ZIP file, so the note stays
attached to the specific backup even if the parent profile is renamed.
"""

import os
import json
import logging
import config

# --- Backup notes file name and path (dynamic using settings_manager) ---
BACKUP_NOTES_FILENAME = "backup_notes.json"
try:
    import settings_manager as _sm
    _ACTIVE_CONFIG_DIR = _sm.get_active_config_dir()
except Exception:
    _ACTIVE_CONFIG_DIR = config.get_app_data_folder()
    logging.warning("Failed to import settings_manager for active config dir; falling back to AppData.")

if _ACTIVE_CONFIG_DIR:
    BACKUP_NOTES_FILE_PATH = os.path.join(_ACTIVE_CONFIG_DIR, BACKUP_NOTES_FILENAME)
else:
    logging.error("Unable to determine configuration directory for backup notes. Using relative path.")
    BACKUP_NOTES_FILE_PATH = os.path.abspath(BACKUP_NOTES_FILENAME)
logging.info(f"Backup notes file path in use: {BACKUP_NOTES_FILE_PATH}")
# --- End of backup notes file path definition ---

_notes_cache = {}
_cache_loaded = False


def _normalize_path(backup_path: str) -> str:
    """Return a normalized path used as a dictionary key.

    Uses os.path.normpath + normcase so Windows paths with mixed slashes/cases
    map to the same key.
    """
    if not backup_path:
        return ""
    try:
        return os.path.normcase(os.path.normpath(backup_path))
    except Exception:
        return backup_path


def _prune_stale_notes(notes_dict: dict) -> dict:
    """Return a cleaned copy keeping only entries whose backup file still exists
    and whose note text is non-empty.
    """
    if not isinstance(notes_dict, dict):
        return {}
    cleaned = {}
    for path_key, text in notes_dict.items():
        if not isinstance(path_key, str) or not text or not str(text).strip():
            continue
        try:
            if os.path.isfile(path_key):
                cleaned[path_key] = str(text)
            else:
                logging.info(f"Pruned stale backup note entry: file no longer exists ({path_key})")
        except Exception:
            # On any error, keep the entry rather than losing user data
            cleaned[path_key] = str(text)
    return cleaned


def load_notes() -> dict:
    """Load backup notes from BACKUP_NOTES_FILE_PATH.
    Returns a dictionary {normalized_backup_path: note_text}.
    """
    global _notes_cache, _cache_loaded
    if _cache_loaded:
        return _notes_cache.copy()

    notes = {}
    if os.path.exists(BACKUP_NOTES_FILE_PATH):
        try:
            with open(BACKUP_NOTES_FILE_PATH, 'r', encoding='utf-8') as f:
                notes = json.load(f)
            if not isinstance(notes, dict):
                logging.warning(f"Backup notes file '{BACKUP_NOTES_FILE_PATH}' does not contain a valid dictionary. Reset.")
                notes = {}

            # Auto-prune stale entries and rewrite if necessary
            cleaned = _prune_stale_notes(notes)
            if cleaned != notes:
                try:
                    os.makedirs(os.path.dirname(BACKUP_NOTES_FILE_PATH), exist_ok=True)
                    with open(BACKUP_NOTES_FILE_PATH, 'w', encoding='utf-8') as wf:
                        json.dump(cleaned, wf, indent=4, ensure_ascii=False, sort_keys=True)
                    logging.info(f"Pruned backup notes file: removed {len(notes) - len(cleaned)} stale entries.")
                    notes = cleaned
                except Exception as e_rewrite:
                    logging.warning(f"Unable to rewrite pruned backup notes file: {e_rewrite}")

            logging.info(f"Loaded {len(notes)} backup notes from '{BACKUP_NOTES_FILE_PATH}'.")
        except json.JSONDecodeError:
            logging.warning(f"Backup notes file '{BACKUP_NOTES_FILE_PATH}' is corrupted or empty. Reset.")
            notes = {}
        except Exception as e:
            logging.error(f"Error loading backup notes from '{BACKUP_NOTES_FILE_PATH}': {e}")
            notes = {}
    else:
        logging.info(f"Backup notes file '{BACKUP_NOTES_FILE_PATH}' not found. Starting with empty notes.")

    _notes_cache = notes.copy()
    _cache_loaded = True
    return notes


def save_notes(notes_dict: dict) -> bool:
    """Save the backup notes dictionary to disk.
    Returns True if saving succeeds, False otherwise.
    """
    global _notes_cache
    if not isinstance(notes_dict, dict):
        logging.error("Attempt to save invalid backup notes (not a dictionary).")
        return False
    try:
        notes_to_write = _prune_stale_notes(notes_dict)
        os.makedirs(os.path.dirname(BACKUP_NOTES_FILE_PATH), exist_ok=True)
        with open(BACKUP_NOTES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(notes_to_write, f, indent=4, ensure_ascii=False, sort_keys=True)
        logging.info(f"Saved {len(notes_to_write)} backup notes to '{BACKUP_NOTES_FILE_PATH}'.")
        _notes_cache = notes_to_write.copy()

        # Mirror only when NOT in portable mode (same pattern as notes_manager)
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
                    core_logic._mirror_json_to_backup_root("backup_notes.json", notes_to_write, rotation=rotation)
                except Exception as e_core:
                    logging.warning(f"Mirror backup notes to backup root failed: {e_core}")
        except Exception as e_mirror:
            logging.warning(f"Unable to mirror backup notes to backup root: {e_mirror}")
        return True
    except Exception as e:
        logging.error(f"Error saving backup notes to '{BACKUP_NOTES_FILE_PATH}': {e}")
        return False


def get_note(backup_path: str) -> str:
    """Return the note text for a backup path, or empty string if none."""
    if not backup_path:
        return ""
    notes = load_notes()
    return notes.get(_normalize_path(backup_path), "")


def has_note(backup_path: str) -> bool:
    """Return True if the backup has a non-empty note."""
    return bool(get_note(backup_path))


def set_note(backup_path: str, text: str) -> bool:
    """Set or remove a note for a backup. Empty text removes the note."""
    if not backup_path:
        return False
    notes = load_notes()
    key = _normalize_path(backup_path)
    text = text.strip() if text else ""
    if text:
        notes[key] = text
    elif key in notes:
        del notes[key]
    logging.info(f"{'Set' if text else 'Removed'} note for backup '{os.path.basename(backup_path)}'.")
    return save_notes(notes)


def remove_note(backup_path: str) -> bool:
    """Remove the note for a specific backup (e.g. when the backup is deleted)."""
    if not backup_path:
        return True
    notes = load_notes()
    key = _normalize_path(backup_path)
    if key in notes:
        del notes[key]
        logging.info(f"Removed note for deleted backup '{os.path.basename(backup_path)}'.")
        return save_notes(notes)
    return True


def invalidate_cache():
    """Force reload of backup notes data from disk on next access."""
    global _notes_cache, _cache_loaded
    _notes_cache = {}
    _cache_loaded = False
    logging.debug("Backup notes cache invalidated.")
