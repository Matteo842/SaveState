# settings_manager.py
import json
import os
import config # Importa per ottenere i valori PREDEFINITI
import logging


# --- Usa la funzione da config per definire il percorso ---
SETTINGS_FILENAME = "settings.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Ottieni la cartella base
if APP_DATA_FOLDER: # Controlla se get_app_data_folder ha restituito un percorso valido
    SETTINGS_FILE_PATH = os.path.join(APP_DATA_FOLDER, SETTINGS_FILENAME)
else:
    # Fallback se non abbiamo una cartella dati (molto raro)
    logging.error("Impossibile determinare APP_DATA_FOLDER, uso percorso relativo per settings.json.")
    SETTINGS_FILE_PATH = os.path.abspath(SETTINGS_FILENAME)
logging.info(f"Percorso file impostazioni in uso: {SETTINGS_FILE_PATH}")
# --- FINE NUOVA DEFINIZIONE ---


def load_settings():
    """Carica le impostazioni da SETTINGS_FILE_PATH."""
    first_launch = not os.path.exists(SETTINGS_FILE_PATH) # <-- Usa la nuova variabile
    defaults = {
        "backup_base_dir": config.BACKUP_BASE_DIR,
        "max_backups": config.MAX_BACKUPS,
        "max_source_size_mb": 200, # Limite default 500 MB per la sorgente
        "theme": "dark", # Valori possibili: 'dark', 'light'
        "language": "en", # Default language code (ISO 639-1)
        "compression_mode": "standard",
        "check_free_space_enabled": True,
        "ini_whitelist": [ # File da controllare per i percorsi
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
            # Aggiungi altri nomi comuni se ne conosci
        ],
        "ini_blacklist": [ # File da ignorare sempre
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
            # Aggiungi altri nomi comuni da ignorare
        ]
        

    }

    if first_launch:
        logging.info("Loading settings from file...")
        logging.info(f"File impostazioni '{SETTINGS_FILE_PATH}' non trovato...") # <-- Usa la nuova variabile
        # Potremmo salvare i default qui, ma aspettiamo la conferma dall'utente nel dialogo
        return defaults.copy(), True # Restituisce COPIA dei default e True per primo avvio

    try:
        with open(SETTINGS_FILE_PATH, 'r', encoding='utf-8') as f: # <-- Usa la nuova variabile
            user_settings = json.load(f)
        logging.info("Settings loaded successfully")
        logging.info(f"Impostazioni caricate correttamente da '{SETTINGS_FILE_PATH}'.") # <-- Usa la nuova variabile
        # Unisci i default con le impostazioni utente per gestire chiavi mancanti
        # Le impostazioni utente sovrascrivono i default
        settings = defaults.copy()
        settings.update(user_settings)
              
        # --- VALIDAZIONE TEMA ---
        if settings.get("theme") not in ["light", "dark"]:
            logging.warning(f"Valore tema non valido ('{settings.get('theme')}'), verrà usato il default '{defaults['theme']}'.")
            settings["theme"] = defaults["theme"]
        # --- FINE NUOVA ---
        return settings, False
    except Exception:
        # ...
        return defaults.copy(), True
        
        
        # --- VALIDAZIONE LINGUA ---
        if settings.get("language") not in ["it", "en"]:
            logging.warning(f"Valore lingua non valido ('{settings.get('language')}'), verrà usato il default '{defaults['language']}'.")
            settings["language"] = defaults["language"]
        # --- FINE VALIDAZIONE ---
        
        # --- VALIDAZIONE COMPRESSION MODE ---
        valid_modes = ["standard", "maximum", "stored"]
        if settings.get("compression_mode") not in valid_modes:
            logging.warning(f"Valore compression_mode non valido ('{settings.get('compression_mode')}'), verrà usato il default '{defaults['compression_mode']}'.")
            settings["compression_mode"] = defaults["compression_mode"]
        # --- FINE VALIDAZIONE --- 
        
        # Validazione semplice (opzionale ma consigliata)
        if not isinstance(settings["max_backups"], int) or settings["max_backups"] < 1:
             logging.warning(f"Valore max_backups non valido ('{settings['max_backups']}'), verrà usato il default {defaults['max_backups']}.")
             settings["max_backups"] = defaults["max_backups"]
        if not isinstance(settings.get("max_source_size_mb"), int) or settings["max_source_size_mb"] < 1:
            logging.warning(f"Valore max_source_size_mb non valido ('{settings.get('max_source_size_mb')}'), verrà usato il default {defaults['max_source_size_mb']}.")
            settings["max_source_size_mb"] = defaults["max_source_size_mb"]
        # --- FINE NUOVA ---
        # Potremmo aggiungere un controllo se backup_base_dir è una stringa valida

    # Validazione semplice tipi lista (assicurati siano liste di stringhe)
        if not isinstance(settings.get("ini_whitelist"), list):
             logging.warning("'ini_whitelist' nel file delle impostazioni non è una lista valida, verrà usata la lista predefinita.")
             settings["ini_whitelist"] = defaults["ini_whitelist"]
        if not isinstance(settings.get("ini_blacklist"), list):
             logging.warning("'ini_blacklist' nel file delle impostazioni non è una lista valida, verrà usata la lista predefinita.")
             settings["ini_blacklist"] = defaults["ini_blacklist"]
        # ... (validazione per max_backups come prima) ...
        if not isinstance(settings["max_backups"], int) or settings["max_backups"] < 1:
             logging.warning(f"Valore max_backups non valido ('{settings['max_backups']}'), verrà usato il default {defaults['max_backups']}.")
             settings["max_backups"] = defaults["max_backups"]

        return settings, False # Restituisce impostazioni caricate/unite e False per non primo avvio
    except (json.JSONDecodeError, KeyError, TypeError):
        logging.error(f"Lettura o validazione di '{SETTINGS_FILE_PATH}' fallita...", exc_info=True)
        return defaults.copy(), True # Tratta come primo avvio se file corrotto
    except Exception:
        logging.error(f"Errore imprevisto durante la lettura delle impostazioni da '{SETTINGS_FILE_PATH}'. ...", exc_info=True)
        return defaults.copy(), True
        
    # Aggiungi una validazione semplice per il nuovo booleano alla fine delle validazioni esistenti:
        if not isinstance(settings.get("check_free_space_enabled"), bool):
             logging.warning(f"Valore check_free_space_enabled non valido ('{settings.get('check_free_space_enabled')}'), verrà usato il default {defaults['check_free_space_enabled']}.")
             settings["check_free_space_enabled"] = defaults["check_free_space_enabled"]

        return settings, False # O True se primo avvio/errore
        

def save_settings(settings_dict):
    """Salva il dizionario delle impostazioni in SETTINGS_FILE. Restituisce bool (successo)."""
    try:
        with open(SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f: # <-- Usa la nuova variabile
            json.dump(settings_dict, f, indent=4)
        logging.info("Saving settings to file...")
        logging.info(f"Impostazioni salvate correttamente in '{SETTINGS_FILE_PATH}'.") # <-- Usa la nuova variabile
        return True
    except Exception:
        logging.error(f"Errore durante il salvataggio delle impostazioni in '{SETTINGS_FILE_PATH}'.", exc_info=True)
        return False