# settings_manager.py
import json
import os
import config # Import for default values
import logging


# --- Use the function from config to define the path ---
SETTINGS_FILENAME = "settings.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Get the base folder
if APP_DATA_FOLDER: # Check if get_app_data_folder returned a valid path
    SETTINGS_FILE_PATH = os.path.join(APP_DATA_FOLDER, SETTINGS_FILENAME)
else:
    # Fallback if we don't have a data folder (very rare)
    logging.error("Unable to determine APP_DATA_FOLDER, using relative path for settings.json.")
    SETTINGS_FILE_PATH = os.path.abspath(SETTINGS_FILENAME)
logging.info(f"Settings file path in use: {SETTINGS_FILE_PATH}")
# --- END OF DEFINITION ---


def load_settings():
    """Load settings from SETTINGS_FILE_PATH."""
    first_launch = not os.path.exists(SETTINGS_FILE_PATH)
    defaults = {
        "backup_base_dir": config.BACKUP_BASE_DIR,
        "max_backups": config.MAX_BACKUPS,
        "max_source_size_mb": 200, # Default limit 500 MB for the source
        "theme": "dark", # Possible values: 'dark', 'light'
        "compression_mode": "standard",
        "check_free_space_enabled": True,
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
        logging.info(f"Settings file '{SETTINGS_FILE_PATH}' not found...") 
        # We could save defaults here, but we wait for user confirmation in the dialog
        return defaults.copy(), True # Returns COPY of defaults and True for first launch

    try:
        with open(SETTINGS_FILE_PATH, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        logging.info("Settings loaded successfully")
        logging.info(f"Settings loaded successfully from '{SETTINGS_FILE_PATH}'.")
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
        logging.error(f"Failed to read or validate '{SETTINGS_FILE_PATH}'...", exc_info=True)
        return defaults.copy(), True # Treat as first launch if file is corrupted
    except Exception:
        logging.error(f"Unexpected error reading settings from '{SETTINGS_FILE_PATH}'.", exc_info=True)
        return defaults.copy(), True
        

def save_settings(settings_dict):
    """Save the settings dictionary to SETTINGS_FILE. Returns bool (success)."""
    try:
        with open(SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4)
        logging.info("Saving settings to file...")
        logging.info(f"Settings successfully saved to '{SETTINGS_FILE_PATH}'.")
        return True
    except Exception:
        logging.error(f"Error saving settings to '{SETTINGS_FILE_PATH}'.", exc_info=True)
        return False