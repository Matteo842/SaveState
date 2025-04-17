# core_logic.py
# -*- coding: utf-8 -*-
from datetime import datetime
import logging
import os
import json
import zipfile
import config
import re
import platform
import glob

try:
    import winreg
except ImportError:
    winreg = None
try:
    import vdf
except ImportError:
    vdf = None
try:
    # Importa thefuzz per fuzzy matching
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
except ImportError:
    THEFUZZ_AVAILABLE = False
    logging.warning("Library 'thefuzz' not found. Fuzzy name matching will be disabled.")
    logging.warning("Install it using: pip install thefuzz")


# --- Definisci percorso file profili ---
PROFILES_FILENAME = "game_save_profiles.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Ottieni cartella base
if APP_DATA_FOLDER: # Controlla se valido
    PROFILES_FILE_PATH = os.path.join(APP_DATA_FOLDER, PROFILES_FILENAME)
else:
    # Fallback
    logging.error("Unable to determine APP_DATA_FOLDER, use relative path for game_save_profiles.json.")
    PROFILES_FILE_PATH = os.path.abspath(PROFILES_FILENAME)
logging.info(f"Profile file path in use: {PROFILES_FILE_PATH}")
# --- Fine definizione ---

# Setup logging base (opzionale, ma utile per debug)
# Assicurati che sia configurato solo una volta all'avvio dell'applicazione
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# <<< NUOVO: Funzione per generare abbreviazioni multiple >>>
def generate_abbreviations(name, game_install_dir=None):
    """
    Genera una lista di possibili abbreviazioni/nomi alternativi per il gioco.
    Include gestione colon e parsing exe migliorato.
    """
    abbreviations = set()
    if not name: return []

    # Nome base pulito
    sanitized_name = re.sub(r'[™®©:]', '', name).strip() # Rimuovi : per processing base
    sanitized_name_nospace = re.sub(r'\s+', '', sanitized_name)
    abbreviations.add(sanitized_name)
    abbreviations.add(sanitized_name_nospace)
    abbreviations.add(re.sub(r'[^a-zA-Z0-9]', '', sanitized_name)) # Solo alfanumerico

    # Ignora parole (da config?)
    ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS',
                      {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                       'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                       'definitive', 'enhanced', 'complete', 'collection',
                       'hd', 'ultra', 'deluxe', 'game', 'year'})
    ignore_words_lower = {w.lower() for w in ignore_words}

    # --- Logica Acronimi Standard ---
    words = re.findall(r'\b\w+\b', sanitized_name)
    significant_words = [w for w in words if w.lower() not in ignore_words_lower and len(w) > 1]
    significant_words_capitalized = [w for w in significant_words if w and w[0].isupper()] # Check w non sia vuoto

    if significant_words:
        acr_all = "".join(w[0] for w in significant_words if w).upper()
        if len(acr_all) >= 2: abbreviations.add(acr_all)

    if significant_words_capitalized:
        acr_caps = "".join(w[0] for w in significant_words_capitalized if w).upper()
        if len(acr_caps) >= 2: abbreviations.add(acr_caps) # Es: HMCC

    # --- NUOVO: Logica Acronimi Post-Colon ---
    if ':' in name: # Usa nome originale con :
        parts = name.split(':', 1)
        if len(parts) > 1 and parts[1].strip():
            name_after_colon = parts[1].strip()
            logging.debug(f"Found colon, analyzing part: '{name_after_colon}'")
            words_after_colon = re.findall(r'\b\w+\b', name_after_colon)
            sig_words_after_colon = [w for w in words_after_colon if w.lower() not in ignore_words_lower and len(w) > 1]
            sig_words_caps_after_colon = [w for w in sig_words_after_colon if w and w[0].isupper()]

            if sig_words_caps_after_colon:
                # Genera acronimo solo dalle maiuscole DOPO il colon
                acr_caps_after_colon = "".join(w[0] for w in sig_words_caps_after_colon if w).upper()
                if len(acr_caps_after_colon) >= 2:
                    logging.info(f"Derived abbreviation from capitalized words after colon: {acr_caps_after_colon}")
                    abbreviations.add(acr_caps_after_colon) # Es: MCC da "Master Chief Collection"

    # --- NUOVO: Parsing Eseguibile Migliorato ---
    if game_install_dir and os.path.isdir(game_install_dir):
        exe_base_name = None
        try:
            # ... (Logica di ricerca .exe come prima usando glob) ...
            common_suffixes = ['Win64-Shipping.exe', 'Win32-Shipping.exe', '.exe']
            found_exe_path = None
            # ... (ciclo glob per cercare exe) ...
            # Assumiamo che trovi 'mcclauncher.exe' e lo metta in found_exe_path

            # --- Blocco di ricerca exe ---
            found_exe = None
            exe_search_patterns = [
                 os.path.join(game_install_dir, f"*{suffix}") for suffix in common_suffixes
            ] + [
                 os.path.join(game_install_dir, "Binaries", "Win64", f"*{suffix}") for suffix in common_suffixes
            ] + [
                 os.path.join(game_install_dir, "bin", f"*{suffix}") for suffix in common_suffixes
            ]
            for pattern in exe_search_patterns:
                 executables = glob.glob(pattern)
                 if executables:
                     # Scegli l'eseguibile più probabile (es. non uno piccolo?)
                     valid_exes = [e for e in executables if os.path.getsize(e) > 100*1024] # Ignora exe piccoli?
                     if valid_exes: found_exe = os.path.basename(valid_exes[0])
                     elif executables: found_exe = os.path.basename(executables[0]) # Fallback al primo trovato
                     if found_exe: break
            # --- Fine blocco ricerca ---

            if found_exe:
                logging.info(f"Found executable: {found_exe}")
                # Estrai nome base rimuovendo suffissi noti
                exe_base_name_temp = found_exe
                for suffix in common_suffixes + ['-Win64-Shipping', '-Win32-Shipping', '-Shipping']:
                     if exe_base_name_temp.lower().endswith(suffix.lower()): # Case insensitive
                          exe_base_name_temp = exe_base_name_temp[:-len(suffix)]
                          break
                exe_base_name_temp = re.sub(r'[-_]+$', '', exe_base_name_temp) # Rimuovi trattini finali

                # <<< NUOVO: Rimuovi parole chiave comuni come 'launcher' >>>
                common_exe_keywords = ['launcher', 'server', 'client', 'editor']
                processed_name = exe_base_name_temp
                keyword_removed = False
                for keyword in common_exe_keywords:
                     if processed_name.lower().endswith(keyword):
                          processed_name = processed_name[:-len(keyword)]
                          keyword_removed = True
                          break # Rimuovi solo la prima occorrenza trovata

                # Pulisci ancora eventuali separatori rimasti alla fine
                processed_name = re.sub(r'[-_]+$', '', processed_name)

                if len(processed_name) >= 2:
                    exe_base_name = processed_name # Usa nome processato
                    logging.info(f"Derived abbreviation from executable: {exe_base_name}")
                    abbreviations.add(exe_base_name)
                elif len(exe_base_name_temp) >= 2:
                     # Fallback: se la rimozione keyword ha reso il nome troppo corto, usa quello originale pre-rimozione
                     exe_base_name = exe_base_name_temp
                     logging.info(f"Derived abbreviation from executable (fallback): {exe_base_name}")
                     abbreviations.add(exe_base_name)

        except Exception as e_exe:
            logging.warning(f"Could not derive name from executable: {e_exe}")

    # Rimuovi None/vuoti e ordina (opzionale)
    final_list = sorted(list(filter(lambda x: x and len(x) >= 2, abbreviations)), key=len, reverse=True)
    logging.debug(f"Generated abbreviations for '{name}': {final_list}")
    return final_list


# <<< NUOVO: Helper per check sequenza iniziali >>>
def matches_initial_sequence(folder_name, game_title_words):
    """
    Controlla se folder_name (es. "MCC") è una sequenza delle iniziali
    di game_title_words (es. ["Master", "Chief", "Collection"]).
    """
    if not folder_name or not game_title_words: return False
    folder_name_upper = folder_name.upper()
    word_initials = [word[0].upper() for word in game_title_words if word]

    folder_idx = 0
    word_idx = 0
    while folder_idx < len(folder_name_upper) and word_idx < len(word_initials):
        if folder_name_upper[folder_idx] == word_initials[word_idx]:
            folder_idx += 1 # Lettera del nome cartella trovata, passa alla successiva
        word_idx += 1 # Passa alla parola successiva del titolo in ogni caso

    # Ritorna True solo se abbiamo matchato TUTTE le lettere del nome cartella
    return folder_idx == len(folder_name_upper)

def sanitize_foldername(name):
    """Rimuove o sostituisce caratteri non validi per nomi di file/cartelle."""
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_name: # Se il nome diventa vuoto dopo la pulizia
        safe_name = "_invalid_profile_name_"
    return safe_name

 # --- Gestione Profili ---
def get_profile_backup_summary(profile_name):
    """
    Restituisce un riassunto dei backup per un profilo.
    Returns: tuple (count: int, last_backup_datetime: datetime | None)
    """
    # Usa la funzione esistente che già ordina per data (nuovo prima)
    backups = list_available_backups(profile_name)
    count = len(backups)
    last_backup_dt = None

    if count > 0:
        most_recent_backup_path = backups[0][1] # Indice 1 è il percorso completo
        try:
            mtime_timestamp = os.path.getmtime(most_recent_backup_path)
            last_backup_dt = datetime.fromtimestamp(mtime_timestamp)
        except FileNotFoundError:
            logging.error(f"Last backup file not found ({most_recent_backup_path}) during getmtime for {profile_name}.")
        except Exception as e:
            logging.error(f"Unable to get last backup date for {profile_name} by '{most_recent_backup_path}': {e}")
    return count, last_backup_dt

def load_profiles():
    """Carica i profili da PROFILES_FILE_PATH."""
    profiles = {}
    if os.path.exists(PROFILES_FILE_PATH):
        try:
            with open(PROFILES_FILE_PATH, 'r', encoding='utf-8') as f:
                profiles_data = json.load(f)
                # <<< MODIFICATO: Gestione formato vecchio/nuovo
                if isinstance(profiles_data, dict):
                    # Potrebbe essere il formato vecchio o nuovo con metadata
                    if "__metadata__" in profiles_data:
                        profiles = profiles_data.get("profiles", {}) # Nuovo formato
                    else:
                         profiles = profiles_data # Vecchio formato? Assumiamo sia valido
                else:
                    logging.warning(f"Profile file '{PROFILES_FILE_PATH}' has unexpected format (not a dictionary).")

            logging.info(f"Loaded {len(profiles)} profiles from '{PROFILES_FILE_PATH}'.")
        except json.JSONDecodeError:
            logging.warning(f"Profile file '{PROFILES_FILE_PATH}' corrupt or empty.")
        except Exception as e:
            logging.error(f"Error loading profiles from '{PROFILES_FILE_PATH}': {e}")
    else:
        logging.info(f"Profile file '{PROFILES_FILE_PATH}' not found, starting fresh.")
    return profiles

def save_profiles(profiles):
    """Salva i profili in PROFILES_FILE_PATH."""
    data_to_save = {
        "__metadata__": {
            "version": 1, # Esempio
            "saved_at": datetime.now().isoformat()
        },
        "profiles": profiles
    }
    try:
        # Assicura che la directory esista
        os.makedirs(os.path.dirname(PROFILES_FILE_PATH), exist_ok=True)
        with open(PROFILES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logging.info(f"Saved {len(profiles)} profiles in '{PROFILES_FILE_PATH}'.")
        return True
    except Exception as e:
        logging.error(f"Error saving profiles in '{PROFILES_FILE_PATH}': {e}")
        return False


def delete_profile(profiles, profile_name):
    """Elimina un profilo dal dizionario. Restituisce True se eliminato, False altrimenti."""
    if profile_name in profiles:
        del profiles[profile_name]
        logging.info(f"Profile '{profile_name}' removed from memory.")
        return True
    else:
        logging.warning(f"Attempt to delete non-existing profile: '{profile_name}'.")
        return False

# --- Operazioni Backup/Restore ---

def manage_backups(profile_name, backup_base_dir, max_backups):
    """Elimina i backup .zip più vecchi se superano il limite specificato."""
    deleted_files = []
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.debug(f"ManageBackups - Original name: '{profile_name}', Folder searched: '{profile_backup_dir}'")

    try:
        if not os.path.isdir(profile_backup_dir): return deleted_files

        logging.info(f"Checking outdated (.zip) backups in: {profile_backup_dir}")
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]

        if len(backup_files) <= max_backups:
            logging.info(f"Found {len(backup_files)} backup (.zip) (<= limit {max_backups}).")
            return deleted_files

        num_to_delete = len(backup_files) - max_backups
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f))) # Ordina dal più vecchio

        logging.info(f"Deleting {num_to_delete} older (.zip) backup...")
        deleted_count = 0
        for i in range(num_to_delete):
            file_to_delete = os.path.join(profile_backup_dir, backup_files[i])
            try:
                logging.info(f"  Deleting: {backup_files[i]}")
                os.remove(file_to_delete)
                deleted_files.append(backup_files[i])
                deleted_count += 1
            except Exception as e:
                logging.error(f"  Error deleting {backup_files[i]}: {e}")
        logging.info(f"Deleted {deleted_count} outdated (.zip) backups.")

    except Exception as e:
        logging.error(f"Error managing outdated (.zip) backups for '{profile_name}': {e}")
    return deleted_files


def perform_backup(profile_name, save_folder_path, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard"):
    """Esegue il backup usando zipfile. Restituisce (bool successo, str messaggio)."""
    logging.info(f"Starting perform_backup for: '{profile_name}'")
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.info(f"Original Name: '{profile_name}', Sanitized Folder Name: '{sanitized_folder_name}'")
    logging.debug(f"Backup path built: '{profile_backup_dir}'")

    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.isdir(save_folder_path):
        msg = f"ERROR: Source save folder is not valid: '{save_folder_path}'"
        logging.error(msg)
        return False, msg

    # --- Controllo Dimensione Sorgente ---
    logging.info(f"Checking source size '{save_folder_path}' (Limit: {'None' if max_source_size_mb == -1 else str(max_source_size_mb) + ' MB'})...")
    if max_source_size_mb != -1:
        max_source_size_bytes = max_source_size_mb * 1024 * 1024
        current_size_bytes = get_directory_size(save_folder_path)
        if current_size_bytes == -1:
            msg = f"ERROR: Unable to calculate source size '{save_folder_path}'."
            logging.error(msg)
            return False, msg
        current_size_mb = current_size_bytes / (1024*1024)
        logging.info(f"Current source size: {current_size_mb:.2f} MB")
        if current_size_bytes > max_source_size_bytes:
            msg = (f"ERROR: Backup cancelled!\n"
                   f"Source size ({current_size_mb:.2f} MB) exceeds limit ({max_source_size_mb} MB).")
            logging.error(msg)
            return False, msg
    else:
        logging.info("Source size check skipped (No Limit set).")
    # --- FINE Controllo Dimensione ---

    # --- Creazione Cartella Backup ---
    try:
        logging.info(f"Attempting to create/verify folder: '{profile_backup_dir}'")
        os.makedirs(profile_backup_dir, exist_ok=True)
        logging.info(f"Backup folder verified/created: '{profile_backup_dir}'")
    except Exception as e:
        msg = f"ERROR creating backup folder '{profile_backup_dir}': {e}"
        logging.error(msg, exc_info=True)
        logging.error(f"(Original problematic profile name: '{profile_name}')")
        return False, msg
    # --- FINE Creazione Cartella ---

    # --- Creazione Archivio ZIP ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_profile_name_for_zip = sanitize_foldername(profile_name)
    if not safe_profile_name_for_zip: safe_profile_name_for_zip = "_backup_" # Fallback
    archive_name = f"Backup_{safe_profile_name_for_zip}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    logging.info(f"Starting backup (ZIP) for '{profile_name}': From '{save_folder_path}' to '{archive_path}'")

    zip_compression = zipfile.ZIP_DEFLATED
    zip_compresslevel = 6 # Default Standard
    if compression_mode == "stored":
        zip_compression = zipfile.ZIP_STORED
        zip_compresslevel = None
        logging.info("Compression Mode: None (Stored)")
    elif compression_mode == "maximum":
        zip_compresslevel = 9
        logging.info("Compression Mode: Maximum (Deflate Level 9)")
    else:
        logging.info("Compression Mode: Standard (Deflate Level 6)")

    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, compresslevel=zip_compresslevel) as zipf:
            for root, dirs, files in os.walk(save_folder_path):
                # <<< NUOVO: Escludi file __pycache__ e simili se necessario
                dirs[:] = [d for d in dirs if d != '__pycache__'] # Non scendere in pycache
                files = [f for f in files if not f.endswith(('.pyc', '.pyo'))] # Non aggiungere file compilati

                for file in files:
                    file_path_absolute = os.path.join(root, file)
                    arcname = os.path.relpath(file_path_absolute, save_folder_path)
                    try:
                        logging.debug(f"  Adding: '{file_path_absolute}' as '{arcname}'")
                        zipf.write(file_path_absolute, arcname=arcname)
                    except FileNotFoundError:
                        logging.warning(f"  Skipped adding file (not found?): '{file_path_absolute}'")
                    except Exception as e_write:
                        logging.error(f"  Error adding file '{file_path_absolute}' to zip: {e_write}")
                        # Considera se interrompere il backup o solo loggare l'errore

        deleted = manage_backups(profile_name, backup_base_dir, max_backups)
        deleted_msg = " Deleted {0} outdated backups.".format(len(deleted)) if deleted else ""
        msg = "Backup (ZIP) for '{0}' completed successfully.".format(profile_name) + deleted_msg
        logging.info(msg)
        return True, msg

    except (IOError, OSError, zipfile.BadZipFile) as e:
        msg = f"ERROR during ZIP backup creation '{archive_name}': {e}"
        logging.exception(msg)
        # Tenta di rimuovere l'archivio fallito
        if os.path.exists(archive_path):
            try: os.remove(archive_path); logging.warning(f"Failed ZIP archive removed: {archive_name}")
            except Exception as rem_e: logging.error(f"Unable to remove failed ZIP archive: {rem_e}")
        return False, msg
    except Exception as e:
        msg = f"ERROR unexpected during ZIP backup '{profile_name}': {e}"
        logging.exception(msg)
        if os.path.exists(archive_path):
            try: os.remove(archive_path); logging.warning(f"Failed ZIP archive removed: {archive_name}")
            except Exception as rem_e: logging.error(f"Unable to remove failed ZIP archive: {rem_e}")
        return False, msg


def list_available_backups(profile_name):
    """Restituisce una lista di tuple (nome_file, percorso_completo, data_modifica_str) per i backup di un profilo."""
    backups = []
    sanitized_folder_name = sanitize_foldername(profile_name)
    # <<< MODIFICATO: Usa backup_base_dir dalle impostazioni (richiede passaggio o accesso globale)
    # Assumendo che 'config' fornisca il percorso corretto
    try:
       backup_base_dir = config.BACKUP_BASE_DIR # O ottienilo dalle impostazioni caricate
    except AttributeError:
       logging.error("BACKUP_BASE_DIR not found in config. Unable to list backups.")
       return [] # Restituisce lista vuota se manca la configurazione base

    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.debug(f"ListBackups - Original name: '{profile_name}', Folder searched: '{profile_backup_dir}'")

    if not os.path.isdir(profile_backup_dir):
        return backups # Nessuna cartella = nessun backup

    try:
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]
        # Ordina dal più recente
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)), reverse=True)

        for fname in backup_files:
            fpath = os.path.join(profile_backup_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = "Unknown date"
            backups.append((fname, fpath, date_str))
    except Exception as e:
        logging.error(f"Error listing backups for '{profile_name}': {e}")

    return backups


def perform_restore(profile_name, save_folder_path, archive_to_restore_path):
    """Esegue il ripristino da un archivio ZIP. Restituisce (bool successo, str messaggio)."""
    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.exists(archive_to_restore_path) or not zipfile.is_zipfile(archive_to_restore_path):
        msg = f"ERROR: Archive to restore not found or is not a valid ZIP: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg

    # Assicurati che la destinazione esista, crea se necessario
    try:
        # <<< MODIFICATO: Verifica se è un file e avvisa
        if os.path.exists(save_folder_path) and not os.path.isdir(save_folder_path):
             msg = f"ERROR: Target path '{save_folder_path}' exists but is a file, not a directory. Cannot restore."
             logging.error(msg)
             return False, msg
        os.makedirs(save_folder_path, exist_ok=True)
    except Exception as e:
        msg = f"ERROR: Could not create or access target restore folder '{save_folder_path}': {e}"
        logging.error(msg)
        return False, msg

    logging.info(f"Starting restore for: '{profile_name}'")
    logging.info(f"Restoring from: '{archive_to_restore_path}' to: '{save_folder_path}'")

    # <<< NUOVO: Avviso sovrascrittura (opzionale, ma utile)
    logging.warning(f"Files in '{save_folder_path}' matching the archive content WILL BE OVERWRITTEN.")

    try:
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:
            # Verifica contenuto (opzionale, ma utile per debug)
            # member_list = zipf.namelist()
            # logging.debug(f"Archive contains {len(member_list)} members. Example: {member_list[:5]}")

            logging.info(f"Extracting '{archive_to_restore_path}' to '{save_folder_path}'...")
            zipf.extractall(path=save_folder_path)

        msg = "Restore (ZIP) for '{0}' completed successfully.".format(profile_name)
        logging.info(msg)
        return True, msg

    except (zipfile.BadZipFile, IOError, OSError) as e:
        msg = f"ERROR during ZIP extraction '{os.path.basename(archive_to_restore_path)}': {e}"
        logging.exception(msg)
        return False, msg
    except Exception as e:
        msg = f"ERROR unexpected during ZIP restore '{profile_name}': {e}"
        logging.exception(msg)
        return False, msg


# --- Logica Rilevamento Steam ---

# Cache globale interna a core_logic
_steam_install_path = None
_steam_libraries = None
_installed_steam_games = None
_steam_userdata_path = None
_steam_id3 = None
_cached_possible_ids = None
_cached_id_details = None

def get_steam_install_path():
    """Trova il percorso di installazione di Steam. Restituisce str o None."""
    global _steam_install_path
    if _steam_install_path: return _steam_install_path
    if platform.system() != "Windows": # <<< MODIFICATO: Rileva OS
        logging.info("Steam registry check skipped (Not on Windows).")
        # Qui potresti aggiungere logica per Linux/Mac se necessario (es. cercare ~/.steam/steam)
        # Per ora, restituisce None se non Windows
        return None

    # Solo per Windows
    if winreg is None: return None # Errore import winreg

    try:
        key_path = r"Software\Valve\Steam"
        potential_hives = [(winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")]
        for hive, hive_name in potential_hives:
            try:
                hkey = winreg.OpenKey(hive, key_path)
                path_value, _ = winreg.QueryValueEx(hkey, "SteamPath")
                winreg.CloseKey(hkey)
                # <<< MODIFICATO: Usa os.path.normpath e controlla esistenza
                norm_path = os.path.normpath(path_value.replace('/', '\\'))
                if os.path.isdir(norm_path):
                    _steam_install_path = norm_path
                    logging.info(f"Found Steam installation ({hive_name}): {_steam_install_path}")
                    return _steam_install_path
            except (FileNotFoundError, OSError): continue
            except Exception as e: logging.warning(f"Error reading registry ({hive_name}): {e}")

        logging.error("Steam installation not found in registry.")
        return None
    except Exception as e:
        logging.error(f"Unexpected error searching for Steam: {e}")
        return None

def _parse_vdf(file_path):
    """Helper interno per parsare VDF. Restituisce dict o None."""
    if vdf is None: return None
    if not os.path.isfile(file_path): return None # <<< NUOVO: Controlla esistenza file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Rimuovi commenti C-style se presenti (semplice rimozione linea)
        content = '\n'.join(line for line in content.splitlines() if not line.strip().startswith('//'))
        return vdf.loads(content, mapper=dict) # Usa mapper=dict per standardizzare
    except FileNotFoundError: return None # Già controllato, ma per sicurezza
    except UnicodeDecodeError:
        logging.warning(f"Encoding error reading VDF '{os.path.basename(file_path)}'. Trying fallback encoding...")
        try:
            # Prova con un encoding diverso se UTF-8 fallisce (raro per VDF)
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            content = '\n'.join(line for line in content.splitlines() if not line.strip().startswith('//'))
            return vdf.loads(content, mapper=dict)
        except Exception as e_fallback:
             logging.error(f"ERROR parsing VDF '{os.path.basename(file_path)}' (fallback failed): {e_fallback}")
             return None
    except Exception as e:
        logging.error(f"ERROR parsing VDF '{os.path.basename(file_path)}': {e}")
        return None

def find_steam_libraries():
    """Trova le librerie Steam. Restituisce lista di path."""
    global _steam_libraries
    if _steam_libraries is not None: return _steam_libraries

    steam_path = get_steam_install_path()
    libs = []
    if not steam_path:
        _steam_libraries = []
        return libs

    # Libreria principale (dove Steam è installato)
    main_lib_steamapps = os.path.join(steam_path, 'steamapps')
    if os.path.isdir(main_lib_steamapps):
         libs.append(steam_path) # Aggiungi il path base di Steam

    # Leggi libraryfolders.vdf per altre librerie
    vdf_path = os.path.join(steam_path, 'config', 'libraryfolders.vdf') # <<< MODIFICATO: Percorso corretto
    logging.info(f"Reading libraries from: {vdf_path}")
    data = _parse_vdf(vdf_path)
    added_libs_count = 0

    if data:
        # Il formato può variare leggermente, cerca 'libraryfolders' o direttamente indici numerici
        lib_folders_data = data.get('libraryfolders', data)
        if isinstance(lib_folders_data, dict):
            for key, value in lib_folders_data.items():
                 # Chiavi sono solitamente indici '0', '1', ... o info sulla libreria stessa
                if key.isdigit() or isinstance(value, dict):
                    lib_info = value if isinstance(value, dict) else lib_folders_data.get(key) # Ottieni il dict info
                    if isinstance(lib_info, dict) and 'path' in lib_info:
                        lib_path_raw = lib_info['path']
                        # <<< MODIFICATO: Normalizza e verifica esistenza steamapps
                        lib_path = os.path.normpath(lib_path_raw.replace('\\\\', '\\'))
                        lib_steamapps_path = os.path.join(lib_path, 'steamapps')
                        if os.path.isdir(lib_steamapps_path) and lib_path not in libs:
                            libs.append(lib_path) # Aggiungi path base della libreria
                            added_libs_count += 1
                        # else: logging.debug(f"Library path from VDF invalid or missing steamapps: '{lib_path}'")

    logging.info(f"Found {len(libs)} total Steam libraries ({added_libs_count} from VDF).")
    _steam_libraries = list(dict.fromkeys(libs)) # Rimuovi duplicati se presenti
    return _steam_libraries

def find_installed_steam_games():
    """Trova giochi installati. Restituisce dict {appid: {'name':..., 'installdir':...}}."""
    global _installed_steam_games
    if _installed_steam_games is not None: return _installed_steam_games

    library_paths = find_steam_libraries()
    games = {}
    if not library_paths:
        _installed_steam_games = {}
        return games

    logging.info("Scanning libraries for installed Steam games...")
    total_games_found = 0
    processed_appids = set() # Per evitare sovrascritture se trovato in più librerie

    for lib_path in library_paths:
        steamapps_path = os.path.join(lib_path, 'steamapps')
        if not os.path.isdir(steamapps_path): continue

        try:
            for filename in os.listdir(steamapps_path):
                if filename.startswith('appmanifest_') and filename.endswith('.acf'):
                    acf_path = os.path.join(steamapps_path, filename)
                    data = _parse_vdf(acf_path)
                    if data and 'AppState' in data:
                        app_state = data['AppState']
                        # <<< MODIFICATO: Verifica più robusta dei campi necessari
                        if all(k in app_state for k in ['appid', 'name', 'installdir']) and 'StateFlags' in app_state:
                            appid = app_state['appid']
                            if appid in processed_appids: continue # Già trovato (probabilmente nella libreria principale)

                            installdir_relative = app_state['installdir']
                            # Costruisci percorso assoluto relativo alla LIBRERIA corrente
                            installdir_absolute = os.path.normpath(os.path.join(steamapps_path, 'common', installdir_relative))

                            # Verifica installazione: StateFlags 4 = installato, 1026 = installato+aggiornamento, 6 = installato+validazione?
                            # Controlliamo anche se la cartella esiste fisicamente come fallback
                            state_flags = int(app_state.get('StateFlags', 0))
                            is_installed = (state_flags in [4, 6, 1026]) or \
                                           (state_flags == 2 and os.path.isdir(installdir_absolute)) # 2=UpdateRequired?

                            if is_installed and os.path.isdir(installdir_absolute): # Doppio check
                                name = app_state.get('name', f"Unknown Game {appid}").replace('™', '').replace('®', '').strip()
                                games[appid] = {'name': name, 'installdir': installdir_absolute}
                                processed_appids.add(appid)
                                total_games_found += 1
                                logging.debug(f"Found game: {name} (AppID: {appid}) in '{lib_path}'")
                        # else: logging.debug(f"ACF file '{filename}' missing required fields.")
        except Exception as e:
            logging.error(f"Error scanning games in '{steamapps_path}': {e}")

    logging.info(f"Found {total_games_found} installed Steam games.")
    _installed_steam_games = games
    return games

# Costante per la conversione ID3 <-> ID64
STEAM_ID64_BASE = 76561197960265728

def find_steam_userdata_info():
    """Trova userdata path, SteamID3, lista ID possibili e dettagli ID (incluso display name)."""
    global _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details

    # Controlla cache (come prima)
    if (_steam_userdata_path and _steam_id3 and
            _cached_possible_ids is not None and _cached_id_details is not None and
            all('display_name' in v for v in _cached_id_details.values())):
        logging.debug("Using cached Steam userdata info (with display names).")
        return _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details

    # Resetta cache
    _steam_userdata_path = None; _steam_id3 = None
    _cached_possible_ids = None; _cached_id_details = None

    logging.info("Starting new Steam userdata scan (including profile names)...")
    steam_path = get_steam_install_path()
    if not steam_path:
        logging.error("ERROR: Unable to find Steam installation path for userdata scan.")
        return None, None, [], {}

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        logging.warning(f"Steam 'userdata' folder not found in '{steam_path}'.")
        return None, None, [], {}

    # --- Lettura loginusers.vdf per i nomi ---
    loginusers_path = os.path.join(steam_path, 'config', 'loginusers.vdf')
    user_persona_names = {} # SteamID64 -> PersonaName
    if vdf:
        logging.info(f"Reading profile names from: {loginusers_path}")
        loginusers_data = _parse_vdf(loginusers_path)
        if loginusers_data and 'users' in loginusers_data:
            for steam_id64_str, user_data in loginusers_data['users'].items():
                if isinstance(user_data, dict) and 'PersonaName' in user_data:
                    user_persona_names[steam_id64_str] = user_data['PersonaName']
            logging.info(f"Found {len(user_persona_names)} profile names in loginusers.vdf.")
        else:
            logging.warning("Format 'loginusers.vdf' not recognized or file empty/corrupted.")
    else:
        logging.warning("Library 'vdf' not available, unable to read Steam profile names.")
    # --- FINE Lettura ---

    possible_ids = []
    last_modified_time = 0
    likely_id = None
    id_details = {}

    logging.info(f"Searching Steam user IDs in: {userdata_base}")
    try:
        for entry in os.listdir(userdata_base): # entry è SteamID3
            user_path = os.path.join(userdata_base, entry)
            if entry.isdigit() and entry != '0' and os.path.isdir(user_path):
                possible_ids.append(entry)
                current_mtime = 0
                last_mod_str = "N/D"
                display_name = f"ID: {entry}" # Default se non troviamo nome

                # --- Trova PersonaName usando ID3 -> ID64 ---
                try:
                    steam_id3_int = int(entry)
                    steam_id64 = steam_id3_int + STEAM_ID64_BASE
                    steam_id64_str = str(steam_id64)
                    if steam_id64_str in user_persona_names:
                        display_name = user_persona_names[steam_id64_str] # Usa nome trovato
                        logging.debug(f"Matched ID3 {entry} to Name: {display_name}")
                except ValueError:
                    logging.warning(f"User ID found in userdata is not numeric: {entry}")
                except Exception as e_name:
                    logging.error(f"ERROR retrieving name for ID {entry}: {e_name}")
                # --- FINE Trova PersonaName ---

                # --- Trova data ultima modifica (come prima) ---
                config_vdf_path = os.path.join(user_path, 'config', 'localconfig.vdf')
                check_paths = [config_vdf_path, user_path] # Controlla VDF prima, poi cartella base utente
                for check_path in check_paths:
                    try:
                        if os.path.exists(check_path):
                            mtime = os.path.getmtime(check_path)
                            if mtime > current_mtime: # Prendi il timestamp più recente tra VDF e folder
                                current_mtime = mtime
                                try:
                                    last_mod_str = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M')
                                except ValueError: last_mod_str = "Invalid Date"
                    except Exception: pass # Ignora errori lettura mtime singolo file

                # Salva dettagli
                id_details[entry] = {
                    'mtime': current_mtime,
                    'last_mod_str': last_mod_str,
                    'display_name': display_name # Salva il nome (o l'ID se non trovato)
                }

                # Determina ID più probabile
                if current_mtime > last_modified_time:
                    last_modified_time = current_mtime
                    likely_id = entry

    except Exception as e:
        logging.error(f"ERROR scanning 'userdata': {e}")
        return None, None, [], {} # Resetta in caso di errore grave

    # Cache e return
    _steam_userdata_path = userdata_base
    _steam_id3 = likely_id
    _cached_possible_ids = possible_ids
    _cached_id_details = id_details

    logging.info(f"Found {len(possible_ids)} IDs in userdata. Most likely ID: {likely_id}")
    for uid, details in id_details.items():
        logging.info(f"  - ID: {uid}, Name: {details.get('display_name', '?')}, Last Mod: {details.get('last_mod_str', '?')}")

    return userdata_base, likely_id, possible_ids, id_details


# <<< MODIFICATO: Funzione are_names_similar usa anche check sequenza >>>
def are_names_similar(name1, name2, min_match_words=2, fuzzy_threshold=88, game_title_words_for_seq=None):
    """
    Compares two names for similarity.
    Includes fuzzy matching and initial sequence check.
    Args:
        ... (parametri precedenti)
        game_title_words_for_seq (list[str], optional): List of significant game title words
                                                      used for the initial sequence check.
    """
    # ... (inizio funzione invariato: pulizia, ignore words, tokenizzazione) ...
    try:
        # Pulizia base
        clean_name1 = re.sub(r'[™®©:,.\-\(\)]', '', name1).lower()
        clean_name2 = re.sub(r'[™®©:,.\-\(\)]', '', name2).lower()
        clean_name1 = re.sub(r'\s+', ' ', clean_name1).strip()
        clean_name2 = re.sub(r'\s+', ' ', clean_name2).strip()

        ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS',
                              {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                               'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                               'definitive', 'enhanced', 'complete', 'collection',
                               'hd', 'ultra', 'deluxe', 'game', 'year'})
        ignore_words_lower = {w.lower() for w in ignore_words}
        pattern = r'\b(?:[ivxlcdm]+|[a-z0-9]+)\b'
        words1 = {w for w in re.findall(pattern, clean_name1) if w not in ignore_words_lower and len(w) > 1}
        words2 = {w for w in re.findall(pattern, clean_name2) if w not in ignore_words_lower and len(w) > 1}

        # 1. Check parole comuni
        common_words = words1.intersection(words2)
        if len(common_words) >= min_match_words:
            logging.debug(f"Similar by common words ({len(common_words)} >= {min_match_words}): '{name1}' vs '{name2}' -> Common: {common_words}")
            return True

        # 2. Check prefix (starts_with)
        name1_no_space = clean_name1.replace(' ', '')
        name2_no_space = clean_name2.replace(' ', '')
        MIN_PREFIX_LEN = 4
        starts_with_match = False
        if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
            if len(name1_no_space) > len(name2_no_space):
                if name1_no_space.startswith(name2_no_space): starts_with_match = True
            elif len(name2_no_space) > len(name1_no_space):
                 if name2_no_space.startswith(name1_no_space): starts_with_match = True
            elif name1_no_space == name2_no_space:
                 starts_with_match = True
        if starts_with_match:
             logging.debug(f"Similar by prefix match: '{name1}' vs '{name2}'")
             return True

        # 3. <<< NUOVO: Check Sequenza Iniziali (es. MCC da Master Chief Collection) >>>
        # Controlliamo se name2 (il nome cartella) è una sequenza delle iniziali di name1 (il nome gioco)
        if game_title_words_for_seq and matches_initial_sequence(name2, game_title_words_for_seq):
             logging.debug(f"Similar by initial sequence match: Folder '{name2}' matches sequence in '{' '.join(game_title_words_for_seq)}'")
             return True

        # 4. Fuzzy Matching (come prima)
        if THEFUZZ_AVAILABLE and fuzzy_threshold <= 100:
            ratio = fuzz.token_sort_ratio(clean_name1, clean_name2)
            if ratio >= fuzzy_threshold:
                logging.debug(f"Similar by fuzzy match (Score: {ratio} >= {fuzzy_threshold}): '{name1}' vs '{name2}'")
                return True

        return False # Nessun match

    except Exception as e_sim:
        logging.error(f"Error in are_names_similar('{name1}', '{name2}'): {e_sim}", exc_info=True)
        return False


# <<< MODIFICATO: Funzione guess_save_path usa abbreviazioni e check sequenza >>>
def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True):
    guesses_data = {}
    checked_paths = set()

    # --- Variabili comuni ---
    sanitized_name_base = re.sub(r'^(Play |Launch )', '', game_name, flags=re.IGNORECASE)
    sanitized_name = re.sub(r'[™®©:]', '', sanitized_name_base).strip()

    # <<< NUOVO: Genera lista di abbreviazioni possibili >>>
    game_abbreviations = generate_abbreviations(sanitized_name, game_install_dir)
    # Aggiungi il nome sanificato originale se non già presente per sicurezza
    if sanitized_name not in game_abbreviations:
        game_abbreviations.insert(0, sanitized_name) # Mettilo all'inizio

    # Estrai parole significative per il check sequenza (da fare una sola volta)
    ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS',
                          {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                           'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                           'definitive', 'enhanced', 'complete', 'collection',
                           'hd', 'ultra', 'deluxe', 'game', 'year', 'subtitle'}) # Come prima
    
    ignore_words_lower = {w.lower() for w in ignore_words}
    game_title_sig_words = [w for w in re.findall(r'\b\w+\b', sanitized_name) if w.lower() not in ignore_words_lower and len(w) > 1]


    # ... (Definizione common_save_extensions, filenames, subdirs come prima) ...
    common_save_extensions = getattr(config, 'COMMON_SAVE_EXTENSIONS',
                                {'.sav', '.save', '.dat', '.bin', '.xml', '.json', '.ini', '.slot', '.prof', '.usr', '.cfg', '.details', '.backup', '.meta'})
    
    common_save_filenames = getattr(config, 'COMMON_SAVE_FILENAMES',
                               {'save', 'user', 'profile', 'settings', 'config', 'game', 'player', 'slot', 'steam_autocloud', 'persistent', 'backup', 'world', 'character'})
    
    common_save_subdirs = getattr(config, 'COMMON_SAVE_SUBDIRS',
                             ['Saves', 'Save', 'SaveGame', 'Saved', 'SaveGames', 'storage', 'PlayerData', 'Profile', 'Profiles', 'User', 'Data', 'SaveData', 'Backup', 'Worlds', 'Players', 'Characters', 'output', 'settings'])
    
    common_save_subdirs_lower = {s.lower() for s in common_save_subdirs}
    common_publishers = getattr(config, 'COMMON_PUBLISHERS', [])

    logging.info(f"Heuristic save search for '{game_name}' (AppID: {appid})")
    logging.debug(f"Generated name variations/abbreviations: {game_abbreviations}")
    logging.debug(f"Significant title words for sequence check: {game_title_sig_words}")

    # <<< NUOVO: Blacklist di nomi cartella da ignorare (lowercase) >>>
    # Idealmente caricare da config: getattr(config, 'BANNED_FOLDER_NAMES', set())
    BANNED_FOLDER_NAMES_LOWER = {
        # Nomi comuni di sistema/aziende/programmi
        "microsoft", "nvidia corporation", "intel", "amd", "google", "mozilla",
        "common files", "internet explorer", "windows", "system32", "syswow64",
        "program files", "program files (x86)", "programdata", # ProgramData lo esploriamo, ma non le subdir comuni qui sotto
        "drivers", "perflogs", "dell", "hp", "lenovo",
        # Antivirus comuni (esempi)
        "avast software", "avg", "kaspersky lab", "mcafee",
        # Altri programmi comuni
        "adobe", "python", "java", "oracle", "steam", # Ignora la cartella 'Steam' generica in posti come Program Files
        # Cartelle di sistema nascoste/speciali
        "$recycle.bin", "config.msi", "system volume information",
        "default", "all users", "public", # Nomi utente generici che appaiono a volte
        # Aggiungi altri nomi che ritieni opportuno ignorare
    }
    logging.debug(f"Using banned folder names (lowercase): {BANNED_FOLDER_NAMES_LOWER}")

    # --- Funzione Helper add_guess (MODIFICATA per content check) ---
    def add_guess(path, source_description):
        """
        Controlla un percorso, esegue content check e lo aggiunge a guesses_data se valido.
        Restituisce True se il path è stato aggiunto/aggiornato, False altrimenti.
        """
        nonlocal guesses_data, checked_paths # Permette modifica variabili esterne
        if not path: return False

        try:
            norm_path = os.path.normpath(path)
            if norm_path in checked_paths:
                # logging.debug(f"  Path '{norm_path}' already checked.")
                return False # Già controllato, non fare nulla
            checked_paths.add(norm_path)

            # logging.debug(f"  add_guess checking: '{norm_path}' (Source: {source_description})") # Log un po' verboso
            if os.path.isdir(norm_path):
                # Filtro remotecache.vdf
                try:
                    items = os.listdir(norm_path)
                    if len(items) == 1 and items[0].lower() == "remotecache.vdf" and os.path.isfile(os.path.join(norm_path, items[0])):
                        logging.debug(f"    Path ignored ('{norm_path}') as it only contains remotecache.vdf.")
                        return False
                except OSError: pass # Ignora errori lettura qui

                # Filtro root drive
                drive, tail = os.path.splitdrive(norm_path)
                if not tail or tail == os.sep:
                    logging.debug(f"    Path ignored because it is a root drive: '{norm_path}'")
                    return False

                # <<< NUOVO: Content Check >>>
                contains_save_like_files = False
                try:
                    for item in os.listdir(norm_path):
                        item_lower = item.lower()
                        item_path = os.path.join(norm_path, item)
                        if os.path.isfile(item_path):
                            _, ext = os.path.splitext(item_lower)
                            if ext in common_save_extensions:
                                contains_save_like_files = True; break
                            for fname_part in common_save_filenames:
                                if fname_part in item_lower:
                                    contains_save_like_files = True; break
                        # Potrebbe controllare anche nomi sottocartelle comuni? Es. 'Slot1'
                        # elif os.path.isdir(item_path) and item_lower in common_save_subdirs_lower...

                        if contains_save_like_files: break # Esci presto se trovato

                except OSError as e_list:
                    logging.warning(f"    Could not perform content check in '{norm_path}': {e_list}")
                # <<< FINE Content Check >>>

                log_msg_found = f"Found potential path: '{norm_path}' (Source: {source_description})"
                if contains_save_like_files:
                    log_msg_found += " [!] Contains save-like files."
                logging.info(log_msg_found)

                # Aggiungi o aggiorna in guesses_data (sempre tenendo il primo source trovato)
                dict_key = norm_path.lower()
                if dict_key not in guesses_data:
                    # Salva il path con case originale, source, e flag saves
                    guesses_data[dict_key] = (norm_path, source_description, contains_save_like_files)
                    return True
                # else: Non aggiorniamo source o flag se già presente

            # else: logging.debug(f"    Path '{norm_path}' is not a directory.")
        except OSError as e_os:
            # Ignora errori comuni come Permesso Negato (5)
            if not isinstance(e_os, PermissionError) and getattr(e_os, 'winerror', 0) != 5:
                logging.warning(f"    OS Error checking path '{norm_path}': {e_os}")
        except Exception as e:
            logging.warning(f"    Error while checking path '{norm_path}': {e}")
        return False
    # --- END Helper Function add_guess ---


    # --- <<< NUOVO: Logica Cross-Platform per Common Locations >>> ---
    system = platform.system()
    user_profile = os.path.expanduser('~')
    common_locations = {}
    logging.info(f"Detected Operating System: {system}")

    if system == "Windows":
        # Percorsi standard Windows
        appdata = os.getenv('APPDATA')
        localappdata = os.getenv('LOCALAPPDATA')
        public_docs = os.path.join(os.getenv('PUBLIC', 'C:\\Users\\Public'), 'Documents')
        saved_games = os.path.join(user_profile, 'Saved Games') # %USERPROFILE%\Saved Games
        documents = os.path.join(user_profile, 'Documents')

        common_locations = {
            "Saved Games": saved_games if os.path.isdir(saved_games) else None,
            "Documents": documents,
            "My Games": os.path.join(documents, 'My Games'),
            "AppData/Roaming": appdata,
            "AppData/Local": localappdata,
            # LocalLow è spesso sotto LocalAppData
            "AppData/LocalLow": os.path.join(localappdata, '..', 'LocalLow') if localappdata else None,
            "Public Documents": public_docs if os.path.isdir(public_docs) else None,
        }
        # Aggiungi ProgramData (All Users AppData) se esiste
        programdata = os.getenv('ProgramData')
        if programdata and os.path.isdir(programdata):
            common_locations["ProgramData"] = programdata

    elif system == "Linux":
        # Percorsi standard Linux (XDG Base Directory Specification)
        xdg_data_home = os.getenv('XDG_DATA_HOME', os.path.join(user_profile, '.local', 'share'))
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(user_profile, '.config'))
        # Percorsi comuni aggiuntivi
        steam_linux_root = os.path.join(user_profile, '.steam', 'steam') # Percorso comune, può variare
        steam_linux_userdata = os.path.join(steam_linux_root, 'userdata')
        documents = os.path.join(user_profile, 'Documents') # Meno comune per salvataggi ma possibile

        common_locations = {
            "XDG_DATA_HOME": xdg_data_home,
            "XDG_CONFIG_HOME": xdg_config_home,
            ".steam/steam/userdata": steam_linux_userdata if os.path.isdir(steam_linux_userdata) else None, # Se esiste
            "Home Folder": user_profile, # Meno probabile ma possibile
            # "~/snap" # Per giochi installati via Snap? Meno standard
             "Documents": documents if os.path.isdir(documents) else None,
        }
        # Aggiungi compatdata per Proton/Wine se esiste Steam Linux
        if os.path.isdir(steam_linux_root):
             compatdata_path = os.path.join(steam_linux_root, 'steamapps', 'compatdata')
             if os.path.isdir(compatdata_path):
                  common_locations["Steam Compatdata"] = compatdata_path

    elif system == "Darwin": # macOS
        # Percorsi standard macOS
        app_support = os.path.join(user_profile, 'Library', 'Application Support')
        preferences = os.path.join(user_profile, 'Library', 'Preferences')
        # Meno comuni ma possibili:
        caches = os.path.join(user_profile, 'Library', 'Caches')
        saved_app_state = os.path.join(user_profile, 'Library', 'Saved Application State')
        documents = os.path.join(user_profile, 'Documents') # A volte usato

        common_locations = {
            "Application Support": app_support,
            "Preferences": preferences,
            "Documents": documents,
            "Caches": caches, # Raro per salvataggi persistenti
            "Saved Application State": saved_app_state # Molto raro per salvataggi
        }
        # Aggiungi percorso Steam userdata anche per Mac
        mac_steam_userdata = os.path.join(app_support, 'Steam', 'userdata')
        if os.path.isdir(mac_steam_userdata):
             common_locations["Steam Userdata (Mac)"] = mac_steam_userdata

    else:
        logging.warning(f"Operating system '{system}' not explicitly supported. Using generic home dir.")
        common_locations = {"Home": user_profile}

    # Filtra percorsi non validi o non esistenti
    valid_locations = {name: os.path.normpath(path) for name, path in common_locations.items() if path and os.path.isdir(path)}
    logging.info(f"Valid common locations to search ({system}): {list(valid_locations.keys())}")
    logging.debug(f"Valid common location paths: {list(valid_locations.values())}")
    # --- FINE Logica Cross-Platform ---


    # --- Steam Userdata Check ---
    # <<< MODIFICATO: Usa are_names_similar con check sequenza per subfolders >>>
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        logging.info(f"Checking Steam Userdata for AppID {appid} (User: {steam_id3_to_use})...")
        if os.path.isdir(steam_userdata_path):
            base_userdata_appid = os.path.join(steam_userdata_path, steam_id3_to_use, appid)
            remote_path = os.path.join(base_userdata_appid, 'remote')
            if add_guess(remote_path, f"Steam Userdata/{steam_id3_to_use}/{appid}/remote"):
                try:
                    for entry in os.listdir(remote_path):
                        sub_path = os.path.join(remote_path, entry)
                        sub_lower = entry.lower()
                        # Aggiungi sub se è dir E (sembra save O matcha nome/abbr/sequenza)
                        if os.path.isdir(sub_path) and \
                           (sub_lower in common_save_subdirs_lower or
                            any(s in sub_lower for s in ['save', 'profile']) or
                            # Passa game_title_sig_words per check sequenza
                            are_names_similar(sanitized_name, entry, game_title_words_for_seq=game_title_sig_words) or
                            entry.upper() in [a.upper() for a in game_abbreviations] ): # Confronto case-insensitive abbreviazioni
                                add_guess(sub_path, f"Steam Userdata/.../remote/{entry}")
                except Exception as e_remote_sub: logging.warning(f"Error scanning subfolders in remote: {e_remote_sub}")
            add_guess(base_userdata_appid, f"Steam Userdata/{steam_id3_to_use}/{appid}/Base")
        else: logging.warning(f"Steam userdata path provided is invalid: '{steam_userdata_path}'")
    # --- FINE Steam Userdata Check ---


    # --- Generic Heuristic Search ---
    logging.info("Starting generic heuristic search in common locations...")

    # --- >> Direct Path Checks (Usa lista abbreviazioni) ---
    logging.info("Performing direct path checks...")
    for loc_name, base_folder in valid_locations.items():
        # <<< MODIFICATO: Itera su game_abbreviations invece di name_variations >>>
        for variation in game_abbreviations:
            if not variation: continue
            # Check <Location>/<Variation>
            direct_path = os.path.join(base_folder, variation)
            add_guess(direct_path, f"{loc_name}/Direct/{variation}")
            # Check <Location>/<Publisher>/<Variation>
            for publisher in common_publishers:
                pub_path = os.path.join(base_folder, publisher, variation)
                add_guess(pub_path, f"{loc_name}/{publisher}/Direct/{variation}")
            # Check <Location>/<Variation>/<CommonSaveSubdir>
            if os.path.isdir(direct_path):
                for save_subdir in common_save_subdirs:
                     add_guess(os.path.join(direct_path, save_subdir), f"{loc_name}/Direct/{variation}/{save_subdir}")

    # --- >> Exploratory Search (Usa lista abbreviazioni e check sequenza) ---
    logging.info("Performing exploratory search (iterating folders)...")
    for loc_name, base_folder in valid_locations.items():
        logging.debug(f"Exploring in '{loc_name}' ({base_folder})...")
        try:
            for lvl1_folder_name in os.listdir(base_folder):
                if lvl1_folder_name.lower() in BANNED_FOLDER_NAMES_LOWER:
                    logging.debug(f"  Skipping banned Lvl1 folder: '{lvl1_folder_name}' in '{base_folder}'")
                    continue # Salta questa cartella e passa alla successiva

                lvl1_path = os.path.join(base_folder, lvl1_folder_name)
                if not os.path.isdir(lvl1_path): continue
                lvl1_name_lower = lvl1_folder_name.lower()
                lvl1_name_upper = lvl1_folder_name.upper() # Per confronto abbreviazioni

                # <<< MODIFICATO: Check Lvl1 usa abbreviazioni e check sequenza >>>
                is_lvl1_match = lvl1_name_upper in [a.upper() for a in game_abbreviations] or \
                                are_names_similar(sanitized_name, lvl1_folder_name, game_title_words_for_seq=game_title_sig_words)

                if is_lvl1_match:
                    # ... (logica aggiunta path e check subdirs come prima) ...
                    logging.debug(f"  Match found at Lvl1: '{lvl1_folder_name}'")
                    if add_guess(lvl1_path, f"{loc_name}/GameNameLvl1/{lvl1_folder_name}"):
                        try: # Check subdirs comuni
                            for save_subdir in os.listdir(lvl1_path):
                                if save_subdir.lower() in common_save_subdirs_lower:
                                    add_guess(os.path.join(lvl1_path, save_subdir), f"{loc_name}/GameNameLvl1/{lvl1_folder_name}/{save_subdir}")
                        except OSError: pass

                # Check Lvl2
                try:
                    for lvl2_folder_name in os.listdir(lvl1_path):
                        lvl2_path = os.path.join(lvl1_path, lvl2_folder_name)
                        if not os.path.isdir(lvl2_path): continue
                        lvl2_name_lower = lvl2_folder_name.lower()
                        lvl2_name_upper = lvl2_folder_name.upper()

                        # <<< MODIFICATO: Check Lvl2a usa abbreviazioni e check sequenza >>>
                        is_lvl2_match = lvl2_name_upper in [a.upper() for a in game_abbreviations] or \
                                        are_names_similar(sanitized_name, lvl2_folder_name, game_title_words_for_seq=game_title_sig_words)

                        if is_lvl2_match:
                            # ... (logica aggiunta path e check subdirs come prima) ...
                            logging.debug(f"    Match found at Lvl2 (Game Name): '{lvl2_folder_name}' in '{lvl1_folder_name}'")
                            if add_guess(lvl2_path, f"{loc_name}/{lvl1_folder_name}/GameNameLvl2/{lvl2_folder_name}"):
                                 try: # Check subdirs comuni
                                     for save_subdir in os.listdir(lvl2_path):
                                         if save_subdir.lower() in common_save_subdirs_lower:
                                             add_guess(os.path.join(lvl2_path, save_subdir), f"{loc_name}/.../GameNameLvl2/{lvl2_folder_name}/{save_subdir}")
                                 except OSError: pass

                        # Check 2b (Lvl2 è save subdir comune E Lvl1 rilevante)
                        elif lvl2_name_lower in common_save_subdirs_lower and \
                             (lvl1_folder_name in common_publishers or is_lvl1_match or are_names_similar(sanitized_name, lvl1_folder_name, min_match_words=1)): # Match Lvl1 permissivo
                                  logging.debug(f"    Match found at Lvl2 (Save Subdir): '{lvl2_folder_name}' in '{lvl1_folder_name}' (Parent relevant)")
                                  add_guess(lvl2_path, f"{loc_name}/{lvl1_folder_name}/SaveSubdirLvl2/{lvl2_folder_name}")

                except OSError as e_lvl1: # Errori lettura Lvl2
                    if not isinstance(e_lvl1, PermissionError) and getattr(e_lvl1, 'winerror', 0) != 5: logging.warning(f"  Could not read inside '{lvl1_path}': {e_lvl1}")
        except OSError as e_base: # Errori lettura Lvl1
            if not isinstance(e_base, PermissionError) and getattr(e_base, 'winerror', 0) != 5: logging.warning(f"Error accessing subfolders in '{base_folder}': {e_base}")
    # --- FINE Exploratory Search ---


    # --- Search Inside Install Dir (Usa lista abbreviazioni e check sequenza) ---
    if game_install_dir and os.path.isdir(game_install_dir):
        logging.info(f"Checking common subfolders INSIDE (max depth 3) '{game_install_dir}'...")
        max_depth = 3
        try: install_dir_depth = game_install_dir.rstrip(os.sep).count(os.sep)
        except Exception: install_dir_depth = 0
        try:
            for root, dirs, files in os.walk(game_install_dir, topdown=True, onerror=lambda err: logging.warning(f"Error during install dir walk: {err}")):
                try: current_depth = root.rstrip(os.sep).count(os.sep); current_relative_depth = current_depth - install_dir_depth
                except Exception: current_relative_depth = 0
                if current_relative_depth >= max_depth: dirs[:] = []; continue

                # <<< NUOVO: Filtra le directory da esplorare ulteriormente usando la blacklist >>>
                # Modifica la lista 'dirs' in-place per evitare la discesa in cartelle bannate
                dirs[:] = [d for d in dirs if d.lower() not in BANNED_FOLDER_NAMES_LOWER]
                
                for dir_name in list(dirs):
                    potential_path = os.path.join(root, dir_name)
                    try: relative_log_path = os.path.relpath(potential_path, game_install_dir)
                    except ValueError: relative_log_path = dir_name

                    dir_name_lower = dir_name.lower()
                    dir_name_upper = dir_name.upper() # Per confronto abbreviazioni

                    # <<< MODIFICATO: Check usa abbreviazioni e check sequenza >>>
                    if dir_name_lower in common_save_subdirs_lower:
                        add_guess(potential_path, f"InstallDirWalk/SaveSubdir/{relative_log_path}")
                    elif dir_name_upper in [a.upper() for a in game_abbreviations] or \
                         are_names_similar(sanitized_name, dir_name, game_title_words_for_seq=game_title_sig_words):
                         add_guess(potential_path, f"InstallDirWalk/GameMatch/{relative_log_path}")

        except Exception as e_walk: logging.error(f"Unexpected error during os.walk in '{game_install_dir}': {e_walk}")
    # --- FINE Search Inside Install Dir ---



    # --- Deduplicate and Final Sort (MODIFICATO per nuovo guesses_data e sorting) ---
    logging.info("Finalizing and sorting potential paths...")

    # guesses_data ora contiene {norm_path: (source, contains_saves)}
    # Converti in lista di tuple per l'ordinamento: [(path, source, contains_saves), ...]
    guesses_list = [(data[0], data[1], data[2]) for data in guesses_data.values()]

    # <<< Funzione di ordinamento con CORREZIONE ordine check Steam Base >>>
    def final_sort_key(guess_tuple):
        """
        Assegna un punteggio a una tupla (path, source, contains_saves).
        Punteggi più alti = più probabile.
        """
        # --- Estrai dati dalla tupla ---
        path, source, contains_saves = guess_tuple
        score = 0 # Inizializza punteggio
        path_lower = path.lower()
        basename_lower = os.path.basename(path_lower)
        source_lower = source.lower()
        parent_dir_lower = os.path.dirname(path_lower) # Utile per controlli

        # --- Identifica Tipi Speciali di Percorso ---
        # Controlla se è Steam Remote
        is_steam_remote = steam_userdata_path and 'steam userdata' in source_lower and '/remote' in source_lower

        # Controlla se è Steam Base (userdata ma finisce con /Base nel source)
        is_steam_base = steam_userdata_path and 'steam userdata' in source_lower and source_lower.endswith('/base') # Più specifico

        # Controlla se è in una locazione utente primaria (ESCLUSA steam userdata, gestita sopra)
        prime_locations_parents = [ # Lista dei parent delle locazioni primarie
            os.path.normpath(os.path.expanduser('~/Saved Games')).lower(),
            os.path.normpath(os.getenv('APPDATA', '')).lower(),
            os.path.normpath(os.getenv('LOCALAPPDATA', '')).lower(),
            os.path.normpath(os.path.join(os.getenv('LOCALAPPDATA', ''), '..', 'LocalLow')).lower() if os.getenv('LOCALAPPDATA') else None,
            os.path.normpath(os.path.join(os.path.expanduser('~/Documents'), 'My Games')).lower(),
        ]
        prime_locations_parents = [loc for loc in prime_locations_parents if loc] # Rimuovi None
        # <<< MODIFICATO: Rinominato e non controlla più steam_userdata_path qui >>>
        is_in_prime_user_location = any(path_lower.startswith(loc + os.sep) for loc in prime_locations_parents)

        # Controlla se proviene dalla cartella di installazione
        is_install_dir_walk = 'installdirwalk' in source_lower
        # --- FINE Identificazione Tipi Speciali ---


        # --- ASSEGNA PUNTEGGIO BASE (ORDINE CORRETTO) ---
        if is_steam_remote:
            score += 1500  # 1. Massima priorità Steam Cloud Remote
        elif is_steam_base:
            # 2. Gestisci Steam Base (DE-PRIORITIZZATO) CORRETTAMENTE ORA
            score += 150   # Punteggio base molto basso
            if contains_saves: score += 500 # Bonus solo se ha saves
        elif is_in_prime_user_location: # Rinominato
            # 3. Priorità alta per AppData, Saved Games, My Games, LocalLow
            score += 1000
        elif 'documents' in path_lower and 'my games' not in path_lower:
            # 4. Documents generico
            score += 300
        elif is_install_dir_walk:
            # 5. Penalità base per InstallDirWalk
            score -= 500
        else:
            # 6. Altro (Public, root, etc.)
            score += 100


        # --- BONUS INDICATORI POSITIVI (Logica invariata rispetto a prima) ---
        if contains_saves:
            if not is_steam_base: score += 600
            else: score += 50 # Piccolo bonus aggiuntivo anche a steam base se ha saves

        is_common_save_subdir = basename_lower in common_save_subdirs_lower
        if is_common_save_subdir:
            score += 350

        # Assicurati che game_abbreviations, matches_initial_sequence, game_title_sig_words
        # siano accessibili (definite nell'ambito di guess_save_path)
        is_direct_abbr_match = any(os.path.basename(path) == abbr for abbr in game_abbreviations)
        is_sequence_match = matches_initial_sequence(os.path.basename(path), game_title_sig_words)
        is_direct_source = 'direct' in source_lower or 'gamenamelvl' in source_lower

        if is_direct_abbr_match or is_sequence_match or is_direct_source:
            score += 250
            if is_sequence_match: score += 100
            if 'direct' in source_lower: score += 50

        parent_basename_lower = os.path.basename(parent_dir_lower)
        if is_common_save_subdir and parent_basename_lower in [a.lower() for a in game_abbreviations]:
            score += 100


        # --- MALUS SPECIFICI (Logica invariata rispetto a prima) ---
        if basename_lower in ['data', 'settings', 'config', 'cache', 'logs'] and not contains_saves and not is_in_prime_user_location and not is_steam_remote:
            score -= 150

        if len(basename_lower) <= 3 and not is_common_save_subdir and not contains_saves:
            score -= 50

        if is_install_dir_walk and (not contains_saves or not is_common_save_subdir):
            score -= 300 # Penalità extra se non convincente


        # --- Restituisci il punteggio ---
        return (-score, path_lower)
    # <<< FINE Funzione di ordinamento >>>

    # Ordina la lista di tuple usando la nuova chiave
    sorted_guesses_list = sorted(guesses_list, key=final_sort_key)

    # Estrai solo i percorsi ordinati per il risultato finale
    final_sorted_paths = [item[0] for item in sorted_guesses_list]

    logging.info(f"Search finished. Found {len(final_sorted_paths)} unique potential paths (sorted by likelihood).")
    if final_sorted_paths:
         logging.debug(f"Paths found with scores (higher is better):")
         # Ricrea punteggi per logging (o salva punteggio durante sort)
         for i, p in enumerate(final_sorted_paths):
             # Trova dati originali per calcolare punteggio
             orig_data_tuple = guesses_data.get(p.lower())
             if orig_data_tuple:
                 score = -final_sort_key( (orig_data_tuple[0], orig_data_tuple[1], orig_data_tuple[2]) )[0] # Calcola punteggio
                 logging.debug(f"  {i+1}. Score: {score} | Path: '{p}' (Source: {orig_data_tuple[1]}, HasSaves: {orig_data_tuple[2]})")
             else: # Non dovrebbe succedere
                  logging.debug(f"  {i+1}. Path: '{p}' (Data not found?)")

    # Ora che la funzione chiave è definita, usiamola per ordinare
    final_sorted_paths = [] # Inizializza a lista vuota per sicurezza
    try:
        logging.info("Finalizing and sorting potential paths...") # Messaggio spostato qui

        # Converti guesses_data in lista di tuple per l'ordinamento
        # guesses_data ora contiene {norm_path_lower: (original_norm_path, source, contains_saves)}
        guesses_list = [(data[0], data[1], data[2]) for data in guesses_data.values()]

        # Ordina la lista di tuple usando la chiave definita sopra
        sorted_guesses_list = sorted(guesses_list, key=final_sort_key)

        # Estrai solo i percorsi ordinati (con case originale) per il risultato finale
        final_sorted_paths = [item[0] for item in sorted_guesses_list] # Questa era una delle righe mancanti

        logging.info(f"Search finished. Found {len(final_sorted_paths)} unique potential paths (sorted by likelihood).")
        if final_sorted_paths:
             logging.debug(f"Paths found with scores (higher is better):")
             # Ricrea punteggi per logging
             for i, p in enumerate(final_sorted_paths):
                 # Trova dati originali usando la chiave lowercase
                 orig_data_tuple = guesses_data.get(p.lower())
                 if orig_data_tuple:
                     try:
                         # Ricalcola il punteggio per il log
                         # Nota: Assicurati che le variabili esterne usate da final_sort_key
                         # (game_abbreviations, game_title_sig_words, etc.) siano ancora accessibili qui se necessario
                         # In questo caso final_sort_key le usa come closure, quindi dovrebbe essere ok.
                         score = -final_sort_key( (orig_data_tuple[0], orig_data_tuple[1], orig_data_tuple[2]) )[0]
                         logging.debug(f"  {i+1}. Score: {score} | Path: '{p}' (Source: {orig_data_tuple[1]}, HasSaves: {orig_data_tuple[2]})")
                     except Exception as e_log_score:
                          logging.warning(f"Could not calculate score for logging path '{p}': {e_log_score}")
                          logging.debug(f"  {i+1}. Path: '{p}' (Source: {orig_data_tuple[1]}, HasSaves: {orig_data_tuple[2]})")
                 else:
                      logging.debug(f"  {i+1}. Path: '{p}' (Original data not found in guesses_data?)") # Improbabile

    except Exception as e_final:
        logging.error(f"Error during final sorting/processing of paths: {e_final}", exc_info=True)
        final_sorted_paths = [] # Resetta a lista vuota in caso di errore

    # Questa return è ora fuori dal try...except e restituirà sempre una lista
    return final_sorted_paths # Questa era l'altra riga mancante

# <<< FINE BLOCCO DA AGGIUNGERE >>>


def delete_single_backup_file(file_path):
    """Elimina un singolo file di backup specificato dal percorso completo."""
    if not file_path:
        msg = "ERROR: No file path specified for deletion."
        logging.error(msg)
        return False, msg
    if not os.path.isfile(file_path):
        msg = f"ERROR: File to delete not found or is not a valid file: '{file_path}'"
        logging.error(msg)
        return False, msg # Considera errore se file non esiste

    backup_name = os.path.basename(file_path)
    logging.warning(f"Attempting permanent deletion of file: {file_path}")

    try:
        os.remove(file_path)
        msg = f"File '{backup_name}' deleted successfully."
        logging.info(msg)
        return True, msg
    except OSError as e:
        msg = f"ERROR OS during deletion of '{backup_name}': {e}"
        logging.error(msg)
        return False, msg
    except Exception as e:
        msg = f"ERROR unexpected during deletion of '{backup_name}': {e}"
        logging.exception(msg) # Logga traceback
        return False, msg

def get_directory_size(directory_path):
    """Calcola ricorsivamente la dimensione totale di una cartella in bytes."""
    total_size = 0
    if not os.path.isdir(directory_path): # <<< NUOVO: Controlla se è una dir valida
         logging.error(f"ERROR get_directory_size: Path is not a valid directory: {directory_path}")
         return -1 # Indica errore

    try:
        for dirpath, dirnames, filenames in os.walk(directory_path, topdown=True, onerror=lambda err: logging.warning(f"Error walking {err.filename}: {err.strerror}")):
            # Escludi ricorsivamente cartelle comuni non utente (opzionale)
            # dirnames[:] = [d for d in dirnames if d.lower() not in ['__pycache__', '.git', '.svn']]

            for f in filenames:
                fp = os.path.join(dirpath, f)
                # Salta link simbolici rotti o file inaccessibili
                try:
                    if not os.path.islink(fp):
                         total_size += os.path.getsize(fp)
                    # else: logging.debug(f"Skipping symlink: {fp}") # Log se necessario
                except OSError as e:
                    logging.warning(f"ERROR getting size for {fp}: {e}") # Logga ma continua
    except Exception as e:
        logging.error(f"ERROR during size calculation for {directory_path}: {e}")
        return -1 # Restituisce -1 per indicare errore nel calcolo
    return total_size

# --- Altre funzioni core se necessario ---
# Es: Funzione per inizializzare/caricare configurazioni esterne per le liste
# def load_heuristic_configs():
#     global common_save_extensions, common_save_filenames, ...
#     # Carica da config.py o file JSON/INI
#     pass