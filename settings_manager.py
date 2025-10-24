# settings_manager.py
import json
import os
import sys
import shutil
import config # Import for default values
import logging
import time


# --- Dynamic configuration directory resolution ---
SETTINGS_FILENAME = "settings.json"
PORTABLE_POINTER_FILENAME = ".savestate_portable.json"  # Hidden on Unix; hidden attribute set on Windows

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
            logging.debug(f"Reading AppData settings from: {path}")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    portable_flag = data.get("portable_config_only", False)
                    logging.debug(f"AppData settings loaded. portable_config_only={portable_flag}")
                return data
        else:
            logging.debug(f"No settings file found in AppData: {path}")
    except Exception as e:
        logging.warning(f"Unable to read settings.json from AppData: {e}")
    return None


def _get_executable_dir() -> str:
    """Return the directory containing the running executable or script.

    Supports PyInstaller (sys.frozen) and normal Python execution.
    """
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
            return os.path.dirname(os.path.abspath(sys.executable))
        # Best-effort fallback to the script path
        if hasattr(sys, "argv") and sys.argv and sys.argv[0]:
            return os.path.dirname(os.path.abspath(sys.argv[0]))
    except Exception:
        pass
    # Last resort: directory of this module
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _get_portable_pointer_path() -> str:
    """Full path to the hidden portable pointer JSON next to the executable."""
    try:
        return os.path.join(_get_executable_dir(), PORTABLE_POINTER_FILENAME)
    except Exception:
        return PORTABLE_POINTER_FILENAME


def _make_file_hidden_windows(path: str) -> None:
    """Mark file hidden on Windows. No-op on other platforms."""
    try:
        if os.name == "nt" and isinstance(path, str):
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(ctypes.c_wchar_p(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        # Best effort only; ignoring failures keeps portability
        pass


def _read_portable_pointer() -> str | None:
    """Read backup base directory from the hidden pointer JSON next to the executable.

    The file may contain either a raw JSON string ("D:/path") or an object
    like {"backup_base_dir": "D:/path"} or {"path": "D:/path"}.
    Returns the backup base dir string, or None if not found/invalid.
    """
    try:
        pointer_path = _get_portable_pointer_path()
        if not os.path.isfile(pointer_path):
            return None
        with open(pointer_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, str) and data:
            return data
        if isinstance(data, dict):
            for key in ("backup_base_dir", "path"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    return val
    except Exception:
        pass
    return None


def _delete_portable_pointer() -> bool:
    """Delete the hidden portable pointer JSON if it exists.

    Returns True if deleted (or not present), False on failure.
    """
    try:
        pointer_path = _get_portable_pointer_path()
        if os.path.isfile(pointer_path):
            try:
                os.remove(pointer_path)
                logging.info("Portable pointer removed (portable mode off).")
            except Exception as e_rm:
                logging.warning(f"Unable to remove portable pointer JSON: {e_rm}")
                return False
        return True
    except Exception:
        return False


def _write_portable_pointer(backup_root: str) -> bool:
    """Write the hidden portable pointer JSON next to the executable.

    Writes only the backup path (JSON string). Also attempts to hide the file on Windows.
    Returns True on success, False on failure.
    """
    try:
        if not isinstance(backup_root, str) or not backup_root:
            return False
        pointer_path = _get_portable_pointer_path()
        # Ensure parent exists
        try:
            os.makedirs(os.path.dirname(pointer_path), exist_ok=True)
        except Exception:
            pass

        last_error = None
        for attempt in range(3):
            try:
                # Write to a temp file first, then replace to avoid locks/permission issues
                temp_path = pointer_path + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(backup_root, f, indent=0)

                # Try to delete the old pointer if present, then move the temp into place
                try:
                    if os.path.exists(pointer_path):
                        try:
                            os.remove(pointer_path)
                        except Exception:
                            # Fall back to replace without prior delete
                            pass
                    os.replace(temp_path, pointer_path)
                except Exception as e_rep:
                    # Cleanup temp and re-raise to outer except
                    try:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception:
                        pass
                    raise e_rep

                _make_file_hidden_windows(pointer_path)
                logging.info(f"Portable pointer written next to executable: {pointer_path}")
                return True
            except Exception as e_ptr:
                last_error = e_ptr
                # Short backoff and retry (handles transient AV/EDR locks)
                try:
                    time.sleep(0.15 * (2 ** attempt))
                except Exception:
                    pass
        if last_error:
            logging.warning(f"Unable to write portable pointer JSON after retries: {last_error}")
        return False
    except Exception as e_outer:
        logging.warning(f"Unable to write portable pointer JSON: {e_outer}")
        return False


def get_active_config_dir() -> str:
    """Return the directory where JSON configs should be read from and written to.

    Logic:
      - If AppData settings.json exists AND indicates portable_config_only true with a valid
        backup_base_dir, then point to <backup>/.savestate.
      - Otherwise, if AppData settings are absent, read the hidden pointer JSON next to the
        executable and point to <backup>/.savestate.
      - Otherwise, use AppData directory.
    """
    # 0) Runtime override takes precedence for current session
    global _RUNTIME_CONFIG_DIR_OVERRIDE
    if _RUNTIME_CONFIG_DIR_OVERRIDE:
        logging.debug(f"Using runtime override config directory: {_RUNTIME_CONFIG_DIR_OVERRIDE}")
        return _RUNTIME_CONFIG_DIR_OVERRIDE

    app_dir = config.get_app_data_folder()
    logging.debug(f"Determining active config directory. AppData location: {app_dir}")
    data = _read_appdata_settings()
    
    try:
        if isinstance(data, dict) and bool(data.get("portable_config_only")):
            # AppData says portable mode is active: read the path from the pointer file
            logging.debug("AppData settings indicate portable_config_only=true, reading pointer file for backup path...")
            pointer_path = _get_portable_pointer_path()
            logging.debug(f"Pointer file location: {pointer_path}")
            backup_root = _read_portable_pointer()
            if isinstance(backup_root, str) and backup_root:
                target = os.path.join(backup_root, ".savestate")
                logging.debug(f"Using portable configuration from '{target}' (pointer: '{pointer_path}')")
                try:
                    os.makedirs(target, exist_ok=True)
                except Exception:
                    pass
                return target
            else:
                logging.warning(f"portable_config_only=true in AppData, but pointer file is missing or invalid. Falling back to AppData.")
    except Exception as e_portable:
        logging.warning(f"Error checking portable mode from AppData: {e_portable}")
    # If no AppData settings are present, try the hidden pointer next to the executable
    try:
        if data is None:
            logging.debug("No settings found in AppData, checking for pointer file next to executable...")
            pointer_backup = _read_portable_pointer()
            if isinstance(pointer_backup, str) and pointer_backup:
                target = os.path.join(pointer_backup, ".savestate")
                logging.debug(f"Found pointer file (no AppData settings): Using portable config from '{target}'")
                try:
                    os.makedirs(target, exist_ok=True)
                except Exception:
                    pass
                return target
            else:
                logging.debug("No pointer file found next to executable.")
    except Exception as e_ptr:
        logging.debug(f"Error reading pointer file: {e_ptr}")

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
                        logging.debug(f"Found portable settings in default backup path fallback: {savestate_dir}")
                        return savestate_dir
                except Exception:
                    pass
    except Exception:
        pass

    # Fallback to AppData
    logging.debug(f"Using standard AppData configuration directory: {app_dir}")
    if not app_dir:
        app_dir = os.path.abspath("SaveState")
        logging.warning(f"AppData folder not found, using fallback directory: {app_dir}")
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
    
    # Log configuration mode clearly (once)
    if is_portable_mode():
        pointer_path = _get_portable_pointer_path()
        logging.info(f"✓ PORTABLE MODE: Configuration loaded from '{active_config_dir}' (pointer: '{pointer_path}')")
    else:
        logging.info(f"Standard mode: Configuration loaded from '{active_config_dir}'")
    
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
                # If we are switching portable→portable (backup dir changed), migrate data
                try:
                    previous_active_dir = None
                    try:
                        # Determine previous active dir before this save took effect
                        previous_active_dir = _RUNTIME_CONFIG_DIR_OVERRIDE or get_active_config_dir()
                    except Exception:
                        previous_active_dir = None
                    new_portable_dir = target_config_dir
                    if previous_active_dir and os.path.basename(os.path.normpath(previous_active_dir)) == ".savestate" and os.path.normcase(os.path.abspath(previous_active_dir)) != os.path.normcase(os.path.abspath(new_portable_dir)):
                        for name in ["game_save_profiles.json", "favorites_status.json"]:
                            src = os.path.join(previous_active_dir, name)
                            dst = os.path.join(new_portable_dir, name)
                            try:
                                if os.path.isfile(src):
                                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                                    shutil.copy2(src, dst)
                                    logging.info(f"Moved '{name}' from old portable to new portable directory.")
                            except Exception as e_move:
                                logging.warning(f"Unable to move '{name}' during portable→portable migration: {e_move}")
                except Exception as e_pp:
                    logging.debug(f"Portable→portable migration skipped/failed: {e_pp}")
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

                # IMPORTANT: Update ONLY the portable_config_only flag in AppData settings.json
                # This preserves all other user settings in AppData (as backup) while enabling
                # portable mode. On next launch, get_active_config_dir() will read AppData,
                # see portable_config_only=true, and then read the pointer file for the path.
                try:
                    appdata_settings_path = _get_appdata_settings_path()
                    os.makedirs(os.path.dirname(appdata_settings_path), exist_ok=True)
                    
                    # Read existing settings from AppData to preserve them
                    existing_appdata_settings = {}
                    if os.path.isfile(appdata_settings_path):
                        try:
                            with open(appdata_settings_path, 'r', encoding='utf-8') as f:
                                existing_appdata_settings = json.load(f)
                            if not isinstance(existing_appdata_settings, dict):
                                existing_appdata_settings = {}
                        except Exception:
                            logging.debug("Could not read existing AppData settings, creating new.")
                            existing_appdata_settings = {}
                    
                    # Update ONLY the portable flag, preserving everything else
                    existing_appdata_settings["portable_config_only"] = True
                    
                    with open(appdata_settings_path, 'w', encoding='utf-8') as f:
                        json.dump(existing_appdata_settings, f, indent=4)
                    logging.info(f"Updated AppData settings.json portable mode flag (preserved other settings): {appdata_settings_path}")
                except Exception as e_appdata:
                    logging.warning(f"Unable to update AppData portable mode flag: {e_appdata}")

                # Write the hidden pointer JSON next to the executable so subsequent launches
                # know which backup root contains the portable config.
                try:
                    _write_portable_pointer(backup_root)
                except Exception:
                    pass

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

            # Explicitly remove the portable pointer when leaving portable mode
            try:
                _delete_portable_pointer()
            except Exception:
                pass

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