# settings_manager.py
import json
import os
import sys
import shutil
import config # Import for default values
import logging


# --- Dynamic configuration directory resolution ---
SETTINGS_FILENAME = "settings.json"

# Runtime override for the active config directory (set after save_settings)
_RUNTIME_CONFIG_DIR_OVERRIDE = None


def _get_appdata_settings_path() -> str:
    app_dir = config.get_app_data_folder()
    try:
        os.makedirs(app_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(app_dir, SETTINGS_FILENAME)


def _read_appdata_settings() -> dict | None:
    """Read settings.json from AppData if present. Returns dict or None."""
    path = _get_appdata_settings_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        logging.warning("Unable to read settings.json from AppData (may be pointer or full config).")
    return None


def get_active_config_dir() -> str:
    """Return the directory where JSON configs should be read from and written to.

    Logic:
      - If AppData settings.json exists AND indicates portable_config_only true with a valid
        backup_base_dir, then point to <backup>/.savestate.
      - Otherwise, use AppData directory.
    """
    # 0) Runtime override takes precedence for current session
    global _RUNTIME_CONFIG_DIR_OVERRIDE
    if _RUNTIME_CONFIG_DIR_OVERRIDE:
        return _RUNTIME_CONFIG_DIR_OVERRIDE

    app_dir = config.get_app_data_folder()
    data = _read_appdata_settings()
    try:
        if isinstance(data, dict) and bool(data.get("portable_config_only")):
            backup_root = data.get("backup_base_dir")
            if isinstance(backup_root, str) and backup_root:
                target = os.path.join(backup_root, ".savestate")
                try:
                    os.makedirs(target, exist_ok=True)
                except Exception:
                    pass
                return target
    except Exception:
        pass
    # If no AppData settings indicate portable, try default backup path fallback
    try:
        backup_default = getattr(config, "BACKUP_BASE_DIR", None)
        if isinstance(backup_default, str) and backup_default:
            savestate_dir = os.path.join(backup_default, ".savestate")
            settings_path = os.path.join(savestate_dir, SETTINGS_FILENAME)
            if os.path.isfile(settings_path):
                try:
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        portable_settings = json.load(f)
                    if bool(portable_settings.get("portable_config_only")):
                        return savestate_dir
                except Exception:
                    pass
    except Exception:
        pass

    # Fallback to AppData
    if not app_dir:
        app_dir = os.path.abspath("SaveState")
        try:
            os.makedirs(app_dir, exist_ok=True)
        except Exception:
            pass
    return app_dir


def is_portable_mode() -> bool:
    """True if the active configuration directory is the backup .savestate or runtime override implies it."""
    try:
        active_dir = _RUNTIME_CONFIG_DIR_OVERRIDE or get_active_config_dir()
        return os.path.basename(os.path.normpath(active_dir)) == ".savestate"
    except Exception:
        return False


def load_settings():
    """Load settings from the active settings file path."""
    active_config_dir = get_active_config_dir()
    settings_file_path = os.path.join(active_config_dir, SETTINGS_FILENAME)
    first_launch = not os.path.exists(settings_file_path)
    defaults = {
        "backup_base_dir": config.BACKUP_BASE_DIR,
        "max_backups": config.MAX_BACKUPS,
        "max_source_size_mb": 200, # Default limit 500 MB for the source
        "theme": "dark", # Possible values: 'dark', 'light'
        "compression_mode": "standard",
        "check_free_space_enabled": True,
        "enable_global_drag_effect": True, # ADDED: For the pynput global mouse drag detection overlay
        # Portable mode default follows AppData pointer if present
        "portable_config_only": bool(is_portable_mode()),
        "ini_whitelist": [ # Files to check for paths
            "steam_emu.ini",
            "user_steam_emu.ini",
            "config.ini",
            "settings.ini",
            "user.ini",
            "codex.ini",
            "cream_api.ini",
            "goglog.ini",
            "CPY.ini",
            "ds.ini",
        
        ],
        "ini_blacklist": [ # File to ignore always
            "reshade.ini",
            "reshade_presets.ini",
            "dxvk.conf",
            "d3d9.ini",
            "d3d11.ini",
            "opengl32.ini",
            "graphicsconfig.ini",
            "unins.ini",
            "unins000.ini",
            "browscap.ini",
        ]
        

    }

    if first_launch:
        logging.info("Loading settings from file...")
        logging.info(f"Settings file '{settings_file_path}' not found...") 
        # We could save defaults here, but we wait for user confirmation in the dialog
        return defaults.copy(), True # Returns COPY of defaults and True for first launch

    try:
        with open(settings_file_path, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        logging.info("Settings loaded successfully")
        logging.info(f"Settings loaded successfully from '{settings_file_path}'.")
        # Merge defaults with user settings to handle missing keys
        # User settings override defaults
        settings = defaults.copy()
        settings.update(user_settings)
              
        # --- VALIDATION THEME ---
        if settings.get("theme") not in ["light", "dark"]:
            logging.warning(f"Invalid theme value ('{settings.get('theme')}'), using default '{defaults['theme']}'.")
            settings["theme"] = defaults["theme"]

        # --- VALIDATION COMPRESSION MODE ---
        valid_modes = ["standard", "maximum", "stored"]
        if settings.get("compression_mode") not in valid_modes:
            logging.warning(f"Invalid compression_mode value ('{settings.get('compression_mode')}'), using default '{defaults['compression_mode']}'.")
            settings["compression_mode"] = defaults["compression_mode"]

        # Simple validation (optional but recommended)
        if not isinstance(settings["max_backups"], int) or settings["max_backups"] < 1:
            logging.warning(f"Invalid max_backups value ('{settings['max_backups']}'), using default {defaults['max_backups']}.")
            settings["max_backups"] = defaults["max_backups"]
        if not isinstance(settings.get("max_source_size_mb"), int) or settings["max_source_size_mb"] < 1:
            logging.warning(f"Invalid max_source_size_mb value ('{settings.get('max_source_size_mb')}'), using default {defaults['max_source_size_mb']}.")
            settings["max_source_size_mb"] = defaults["max_source_size_mb"]

        # Simple validation type list (ensure they are lists of strings)
        if not isinstance(settings.get("ini_whitelist"), list):
            logging.warning("'ini_whitelist' in the settings file is not a valid list, using the default list.")
            settings["ini_whitelist"] = defaults["ini_whitelist"]
        if not isinstance(settings.get("ini_blacklist"), list):
            logging.warning("'ini_blacklist' in the settings file is not a valid list, using the default list.")
            settings["ini_blacklist"] = defaults["ini_blacklist"]

        # Boolean validation
        if not isinstance(settings.get("check_free_space_enabled"), bool):
            logging.warning(f"Invalid value for check_free_space_enabled ('{settings.get('check_free_space_enabled')}'), using default {defaults['check_free_space_enabled']}.")
            settings["check_free_space_enabled"] = defaults["check_free_space_enabled"]

        # --- VALIDATION GLOBAL DRAG EFFECT (boolean) ---
        if not isinstance(settings.get("enable_global_drag_effect"), bool):
            logging.warning(f"Invalid value for enable_global_drag_effect ('{settings.get('enable_global_drag_effect')}'), using default {defaults['enable_global_drag_effect']}.")
            settings["enable_global_drag_effect"] = defaults["enable_global_drag_effect"]

        # Ensure the backup directory exists
        backup_dir = settings.get("backup_base_dir")
        if backup_dir and isinstance(backup_dir, str):
            try:
                os.makedirs(backup_dir, exist_ok=True)
                logging.info(f"Ensured backup directory exists: {backup_dir}")
            except OSError as e:
                logging.warning(f"Could not create backup directory {backup_dir}: {e}")
        
        return settings, False
    except (json.JSONDecodeError, KeyError, TypeError):
        logging.error(f"Failed to read or validate '{settings_file_path}'...", exc_info=True)
        return defaults.copy(), True # Treat as first launch if file is corrupted
    except Exception:
        logging.error(f"Unexpected error reading settings from '{settings_file_path}'.", exc_info=True)
        return defaults.copy(), True
        

def save_settings(settings_dict):
    """Save the settings dictionary. Supports portable mode. Returns bool (success)."""
    try:
        global _RUNTIME_CONFIG_DIR_OVERRIDE
        # Extract and remove ephemeral flags (not persisted)
        delete_appdata_after_portable = bool(settings_dict.pop("_delete_appdata_after_portable", False))

        portable_flag = bool(settings_dict.get("portable_config_only", False))
        backup_root = settings_dict.get("backup_base_dir", config.BACKUP_BASE_DIR)

        # Decide target config directory
        if portable_flag and backup_root:
            target_config_dir = os.path.join(backup_root, ".savestate")
            try:
                os.makedirs(target_config_dir, exist_ok=True)
            except Exception as e_mkdir:
                logging.error(f"Unable to create portable config directory '{target_config_dir}': {e_mkdir}")
                return False
        else:
            target_config_dir = config.get_app_data_folder()

        # Save settings to the chosen place
        target_settings_path = os.path.join(target_config_dir, SETTINGS_FILENAME)
        with open(target_settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4)
        logging.info(f"Settings saved to '{target_settings_path}'.")

        # If enabling portable mode, migrate other JSONs from AppData to the portable directory
        if portable_flag and backup_root:
            try:
                appdata_dir = config.get_app_data_folder()
                # Do NOT copy settings.json from AppData here: we just wrote the authoritative
                # portable settings above and copying would overwrite the portable flag.
                files = [
                    "game_save_profiles.json",
                    "favorites_status.json",
                ]
                for name in files:
                    src = os.path.join(appdata_dir, name)
                    dst = os.path.join(target_config_dir, name)
                    try:
                        if os.path.isfile(src):
                            shutil.copy2(src, dst)
                            logging.info(f"Migrated '{name}' from AppData to portable directory.")
                    except Exception as e_copy:
                        logging.warning(f"Unable to migrate '{name}': {e_copy}")

                # When not deleting AppData, leave a small pointer settings.json so future launches
                # can resolve the portable directory without guessing.
                try:
                    if not delete_appdata_after_portable and appdata_dir:
                        pointer_path = os.path.join(appdata_dir, SETTINGS_FILENAME)
                        pointer = {
                            "portable_config_only": True,
                            "backup_base_dir": backup_root,
                        }
                        os.makedirs(appdata_dir, exist_ok=True)
                        with open(pointer_path, 'w', encoding='utf-8') as pf:
                            json.dump(pointer, pf, indent=4)
                        logging.info(f"Wrote portable pointer settings to AppData: {pointer_path}")
                except Exception as e_ptr:
                    logging.warning(f"Unable to write portable pointer settings in AppData: {e_ptr}")

                # Optionally delete the AppData folder when requested and different from target
                if delete_appdata_after_portable:
                    try:
                        if os.path.normcase(os.path.abspath(appdata_dir)) != os.path.normcase(os.path.abspath(target_config_dir)) and os.path.isdir(appdata_dir):
                            shutil.rmtree(appdata_dir, ignore_errors=True)
                            logging.info(f"AppData configuration directory removed: {appdata_dir}")
                    except Exception as e_rm:
                        logging.warning(f"Unable to remove AppData configuration directory: {e_rm}")
            except Exception as e_mig:
                logging.warning(f"Migration to portable directory encountered issues: {e_mig}")

        # Update runtime override so subsequent reads in this session use the chosen directory immediately
        try:
            _RUNTIME_CONFIG_DIR_OVERRIDE = target_config_dir
        except Exception:
            pass

        # Mirror settings only if NOT portable (portable dir is already the backup root)
        if not portable_flag:
            try:
                backup_root_effective = backup_root
                if backup_root_effective:
                    mirror_dir = os.path.join(backup_root_effective, ".savestate")
                    os.makedirs(mirror_dir, exist_ok=True)
                    mirror_path = os.path.join(mirror_dir, "settings.json")
                    with open(mirror_path, 'w', encoding='utf-8') as mf:
                        json.dump(settings_dict, mf, indent=4)
            except Exception:
                logging.warning("Unable to mirror settings.json to backup root")

            # Additionally, when LEAVING portable mode, copy other JSONs from the portable
            # directory into AppData so runtime reload has complete data (profiles/favorites).
            try:
                portable_source_dir = None
                if backup_root:
                    candidate = os.path.join(backup_root, ".savestate")
                    if os.path.isdir(candidate):
                        portable_source_dir = candidate
                if not portable_source_dir:
                    try:
                        active_dir = get_active_config_dir()
                        if os.path.basename(os.path.normpath(active_dir)) == ".savestate":
                            portable_source_dir = active_dir
                    except Exception:
                        portable_source_dir = None

                if portable_source_dir and os.path.isdir(portable_source_dir):
                    # Copy only non-settings JSONs; settings.json was just written above
                    for name in ["game_save_profiles.json", "favorites_status.json"]:
                        src = os.path.join(portable_source_dir, name)
                        dst = os.path.join(target_config_dir, name)
                        try:
                            if os.path.isfile(src):
                                os.makedirs(os.path.dirname(dst), exist_ok=True)
                                shutil.copy2(src, dst)
                                logging.info(f"Migrated '{name}' from portable directory to AppData.")
                        except Exception as e_copy_back:
                            logging.warning(f"Unable to migrate '{name}' to AppData: {e_copy_back}")
            except Exception as e_migrate_back:
                logging.warning(f"Issues while migrating data from portable to AppData: {e_migrate_back}")

        return True
    except Exception:
        logging.error("Error saving settings.", exc_info=True)
        return False


def _load_json_for_compare(path: str):
    """Best-effort JSON loader for equality comparison.

    Returns a tuple (ok: bool, data_or_bytes: Any). If JSON parsing fails,
    returns (True, raw_bytes) for byte-wise comparison; if read fails, returns (False, None).
    """
    try:
        if not os.path.isfile(path):
            return False, None
        with open(path, 'r', encoding='utf-8') as f:
            return True, json.load(f)
    except Exception:
        try:
            with open(path, 'rb') as fb:
                return True, fb.read()
        except Exception:
            return False, None


def _json_like_equal(path_a: str, path_b: str) -> bool:
    """Compare two files as JSON if possible, fallback to raw bytes.

    Returns True if equal, False if different, and False if either cannot be read.
    """
    ok_a, data_a = _load_json_for_compare(path_a)
    ok_b, data_b = _load_json_for_compare(path_b)
    if not (ok_a and ok_b):
        return False
    try:
        return data_a == data_b
    except Exception:
        return False


def sync_secondary_config_mirror(current_settings: dict | None = None) -> None:
    """Ensure backup_root/.savestate JSONs mirror the primary config on startup.

    Only runs when NOT in portable mode. Compares and updates these files:
    - settings.json
    - game_save_profiles.json
    - favorites_status.json
    """
    try:
        # Skip if portable mode is active
        if is_portable_mode():
            return

        # Determine primary and secondary dirs
        primary_dir = get_active_config_dir()  # Expected AppData when not portable
        backup_root = None
        if isinstance(current_settings, dict):
            backup_root = current_settings.get("backup_base_dir")
        if not backup_root:
            try:
                loaded, _first = load_settings()
                backup_root = loaded.get("backup_base_dir")
            except Exception:
                backup_root = getattr(config, "BACKUP_BASE_DIR", None)
        if not (primary_dir and backup_root):
            return
        secondary_dir = os.path.join(backup_root, ".savestate")
        try:
            os.makedirs(secondary_dir, exist_ok=True)
        except Exception:
            pass

        filenames = [
            "settings.json",
            "game_save_profiles.json",
            "favorites_status.json",
        ]

        for name in filenames:
            src = os.path.join(primary_dir, name)
            dst = os.path.join(secondary_dir, name)
            try:
                if not os.path.isfile(src):
                    continue
                needs_copy = not os.path.isfile(dst) or not _json_like_equal(src, dst)
                if needs_copy:
                    import shutil
                    shutil.copy2(src, dst)
                    logging.info(f"Synchronized mirror file to backup: {name}")
            except Exception as e_sync:
                logging.warning(f"Unable to synchronize mirror for '{name}': {e_sync}")
    except Exception as e_out:
        logging.debug(f"Startup mirror sync skipped/failed: {e_out}")