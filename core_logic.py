# core_logic.py
# -*- coding: utf-8 -*-
from datetime import datetime
import logging
import os
import json
import zipfile
import config
import re

try:
    import winreg
except ImportError:
    winreg = None
try:
    import vdf
except ImportError:
    vdf = None


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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def sanitize_foldername(name):
    """Rimuove o sostituisce caratteri non validi per nomi di file/cartelle."""
    # Logica esistente usata per safe_profile_name in perform_backup
    # Mantiene lettere, numeri, spazi, underscore, trattini. Rimuove il resto.
    # Puoi aggiungere altri caratteri sicuri se necessario.
    # Rimuove anche spazi extra all'inizio/fine.
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    # Opzionale: sostituisci spazi multipli o spazi con underscore se preferisci
    # safe_name = re.sub(r'\s+', '_', safe_name)
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
        # Il primo elemento nella lista restituita è il più recente.
        # Prendiamo il suo percorso completo (indice 1 nella tupla restituita da list_available_backups).
        most_recent_backup_path = backups[0][1]
        try:
            # Ottieni il timestamp di modifica del file più recente
            mtime_timestamp = os.path.getmtime(most_recent_backup_path)
            # Converti il timestamp in un oggetto datetime
            last_backup_dt = datetime.fromtimestamp(mtime_timestamp)
        except FileNotFoundError:
            logging.error(f"Last backup file not found ({most_recent_backup_path}) during getmtime for {profile_name}.")
            # Potrebbe succedere se il file viene eliminato tra list e getmtime (raro)
        except Exception as e:
            logging.error(f"Unable to get last backup date for {profile_name} by '{most_recent_backup_path}': {e}")
            # Lascia last_backup_dt a None se c'è un errore

    # Restituisce il conteggio e l'oggetto datetime (o None se nessun backup o errore data)
    return count, last_backup_dt

def load_profiles():
    """Carica i profili da PROFILES_FILE_PATH."""
    profiles = {}
    # La cartella viene creata da get_app_data_folder() la prima volta che viene chiamato (da qui o da settings_manager)
    if os.path.exists(PROFILES_FILE_PATH): # <-- Usa PATH
        try:
            with open(PROFILES_FILE_PATH, 'r', encoding='utf-8') as f: # <-- Usa PATH
                profiles = json.load(f)
            logging.info(f"Loaded {len(profiles)} profiles from '{PROFILES_FILE_PATH}'.") # <-- Usa PATH
        except json.JSONDecodeError:
            logging.warning(f"Profile files '{PROFILES_FILE_PATH}' corrupt or empty...") # <-- Usa PATH
        except Exception as e:
            logging.error(f"Error loading profiles from '{PROFILES_FILE_PATH}': {e}") # <-- Usa PATH
    else:
        logging.info(f"Profile files '{PROFILES_FILE_PATH}' not found...") # <-- Usa PATH
    return profiles

def save_profiles(profiles):
    """Salva i profili in PROFILES_FILE_PATH."""
    # La cartella viene creata da get_app_data_folder()
    try:
        with open(PROFILES_FILE_PATH, 'w', encoding='utf-8') as f: # <-- Usa PATH
            json.dump(profiles, f, indent=4, ensure_ascii=False)
        logging.info(f"Saved {len(profiles)} profiles in '{PROFILES_FILE_PATH}'.") # <-- Usa PATH
        return True
    except Exception as e:
        logging.error(f"Error saving profiles in '{PROFILES_FILE_PATH}': {e}") # <-- Usa PATH
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

def manage_backups(profile_name, backup_base_dir, max_backups): # Parametro 'max_backups' (minuscolo)
    """Elimina i backup .zip più vecchi se superano il limite specificato.""" # Docstring aggiornato
    deleted_files = []
    # --- NUOVO: Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name) # <-- Usa nome sanificato
    logging.debug(f"ManageBackups - Original name: '{profile_name}', Folder searched: '{profile_backup_dir}'")

    try:
        if not os.path.isdir(profile_backup_dir): return deleted_files # Cerca dir sanificata

        logging.info(f"Checking outdated (.zip) backups in: {profile_backup_dir}")
    
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]
        
        # Ordina i file per data di modifica (dal più recente al più vecchio)
        if len(backup_files) <= max_backups:
            # Usa 'max_backups' anche nel messaggio di log
            logging.info(f"Found {len(backup_files)} backup (.zip) (<= limit {max_backups}).")
            return deleted_files

        # Calcola num_to_delete una sola volta, usando il parametro minuscolo
        num_to_delete = len(backup_files) - max_backups

        # Ordina i file per data di modifica (dal più vecchio al più recente)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        logging.info(f"Deleting {num_to_delete} older (.zip) backup...")

        deleted_count = 0
        # Itera per eliminare i file più vecchi (i primi nella lista ordinata)
        for i in range(num_to_delete):
            file_to_delete = os.path.join(profile_backup_dir, backup_files[i])
            try:
                logging.info(f"  Deleting: {backup_files[i]}")
                os.remove(file_to_delete)
                deleted_files.append(backup_files[i])
                deleted_count += 1
            except Exception as e:
                logging.error(f"  Error deleting {backup_files[i]}: {e}")
        logging.info(f"Deleted {deleted_count} outdated (.zip) backups.")

    except Exception as e:
        # Ora questo loggherà l'eccezione originale se ce ne sono altre, non il NameError
        logging.error(f"Error managing outdated (.zip) backups for '{profile_name}': {e}")
    return deleted_files


def perform_backup(profile_name, save_folder_path, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard"):
    """Esegue il backup usando zipfile. Restituisce (bool successo, str messaggio)."""
    logging.info(f"Starting perform_backup for: '{profile_name}'")

    # --- Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    logging.info(f"===> Original Name: '{profile_name}', Sanitized Name Result: '{sanitized_folder_name}'")

    # --- Crea percorso backup USANDO nome sanificato ---
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name) # <-- Riga CRUCIALE!
    logging.debug(f"Backup path built: '{profile_backup_dir}'")

    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.isdir(save_folder_path):
        msg = f"ERROR: Source save folder specified is not valid: '{save_folder_path}'"
        logging.error(msg)
        return False, msg

    # --- Controllo Dimensione Sorgente ---
    # (Nota: sembrano esserci due blocchi uguali per il controllo dimensione, ne basta uno)
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
        os.makedirs(profile_backup_dir, exist_ok=True) # <-- Usa percorso (che dovrebbe essere) sanificato
        logging.info(f"Backup folder verified/created: '{profile_backup_dir}'")
    except Exception as e:
        msg = f"ERROR creating backup folder '{profile_backup_dir}': {e}"
        logging.error(msg)
        logging.error(f"(Original problematic profile name: '{profile_name}')")
        return False, msg
    # --- FINE Creazione Cartella ---

    # --- Creazione Archivio ZIP ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Usa nome sanificato anche per il file zip per coerenza? Sì.
    safe_profile_name_for_zip = sanitize_foldername(profile_name) # Riutilizza helper
    if not safe_profile_name_for_zip: safe_profile_name_for_zip = "_backup_" # Fallback se nome diventa vuoto
    archive_name = f"Backup_{safe_profile_name_for_zip}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name) # Usa dir sanificata

    logging.info(f"Starting backup (ZIP) for '{profile_name}': From '{save_folder_path}' to '{archive_path}'")

    # Opzioni Compressione
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
                for file in files:
                    file_path_absolute = os.path.join(root, file)
                    arcname = os.path.relpath(file_path_absolute, save_folder_path)
                    logging.debug(f"  Adding: '{file_path_absolute}' as '{arcname}'")
                    zipf.write(file_path_absolute, arcname=arcname)

        # Gestione backup vecchi (passa nome originale, manage_backups sanifica internamente)
        deleted = manage_backups(profile_name, backup_base_dir, max_backups)
        deleted_msg = " Eliminati {0} backup obsoleti.".format(len(deleted)) if deleted else ""
        msg = "Backup (ZIP) per '{0}' completato con successo.".format(profile_name) + deleted_msg
        logging.info(msg)
        return True, msg

    except (IOError, OSError, zipfile.BadZipFile) as e:
        msg = f"ERROR during ZIP backup creation '{archive_name}': {e}"
        logging.exception(msg)
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
    # --- NUOVO: Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    # NOTA: Qui usa ancora config.BACKUP_BASE_DIR, andrebbe uniformato leggendo dalle impostazioni
    # ma per ora sistemiamo solo la sanificazione.
    profile_backup_dir = os.path.join(config.BACKUP_BASE_DIR, sanitized_folder_name) # <-- Usa nome sanificato
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
                date_str = "Data sconosciuta"
            backups.append((fname, fpath, date_str))
    except Exception as e:
        logging.error(f"Error listing backups for '{profile_name}': {e}")

    return backups


def perform_restore(profile_name, save_folder_path, archive_to_restore_path):
    """Esegue il ripristino da un archivio ZIP. Restituisce (bool successo, str messaggio)."""
    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.exists(archive_to_restore_path) or not zipfile.is_zipfile(archive_to_restore_path):
        msg = f"ERROR: Archive to restore not found: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg

    # Assicurati che la destinazione esista
    try:
        os.makedirs(save_folder_path, exist_ok=True)
    except Exception as e:
        msg = f"ERROR: Target save folder specified is not valid: '{save_folder_path}': {e}"
        logging.error(msg)
        return False, msg

    logging.info(f"Starting restore for: '{profile_name}'")
    logging.info(f"Restoring from: '{archive_to_restore_path}' to: '{save_folder_path}'")
    logging.info(f"Backup folder verified/created: '{save_folder_path}'")

    try:
        # Apri l'archivio ZIP in lettura ('r')
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:
            # Estrai TUTTO il contenuto nella cartella di destinazione
            # I percorsi relativi (senza la cartella base) memorizzati durante il backup
            # verranno ricreati a partire da 'save_folder_path'.
            # extractall sovrascrive i file esistenti per default.
            logging.info(f"Extracting '{archive_to_restore_path}' to '{save_folder_path}'...")
            zipf.extractall(path=save_folder_path)

        msg = "Ripristino (ZIP) per '{0}' completato con successo.".format(profile_name)
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


# --- Logica Rilevamento Steam  ---

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
    if winreg is None: return None # Non su Windows o errore import

    try:
        key_path = r"Software\Valve\Steam"
        potential_hives = [(winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")]
        for hive, hive_name in potential_hives:
            try:
                hkey = winreg.OpenKey(hive, key_path)
                path_value, _ = winreg.QueryValueEx(hkey, "SteamPath")
                winreg.CloseKey(hkey)
                if path_value and os.path.isdir(path_value.replace('/', '\\')):
                     _steam_install_path = os.path.normpath(path_value.replace('/', '\\'))
                     logging.info(f"Found Steam installation ({hive_name}): {_steam_install_path}")
                     return _steam_install_path
            except (FileNotFoundError, OSError): continue # Ignora se chiave non trovata o accesso negato
            except Exception as e: logging.warning(f"Errore lettura registro ({hive_name}): {e}")

        logging.error("Steam installation not found in registry.")
        return None
    except Exception as e:
        logging.error(f"Unexpected error searching for Steam: {e}")
        return None

def _parse_vdf(file_path):
    """Helper interno per parsare VDF. Restituisce dict o None."""
    if vdf is None: return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            content = '\n'.join(line for line in content.splitlines() if not line.strip().startswith('//'))
            return vdf.loads(content, mapper=dict)
    except FileNotFoundError: return None
    except Exception as e:
        # Logga solo errori su file importanti
        if any(f in file_path for f in ['libraryfolders.vdf', 'loginusers.vdf']):
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

    main_lib_path = os.path.normpath(steam_path)
    if main_lib_path not in libs: libs.append(main_lib_path)

    vdf_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
    logging.info(f"Reading libraries from: {vdf_path}")
    data = _parse_vdf(vdf_path)
    added_libs_count = 0

    if data:
        lib_folders_data = data.get('libraryfolders', data)
        if isinstance(lib_folders_data, dict):
            for key, value in lib_folders_data.items():
                 if key.isdigit() or isinstance(value, dict):
                     lib_info = value if isinstance(value, dict) else lib_folders_data.get(key)
                     if isinstance(lib_info, dict) and 'path' in lib_info:
                         lib_path = os.path.normpath(lib_info['path'].replace('\\\\', '\\'))
                         if os.path.isdir(lib_path) and lib_path not in libs:
                             libs.append(lib_path)
                             added_libs_count += 1
                         # else: logging.warning(f"Percorso libreria VDF non valido: '{lib_path}'")

    logging.info(f"Found {len(libs)} total Steam libraries ({added_libs_count} from VDF).")
    _steam_libraries = libs
    return libs

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
                        if all(k in app_state for k in ['appid', 'name', 'installdir']):
                            appid = app_state['appid']
                            installdir_relative = app_state['installdir']
                            installdir_absolute = os.path.normpath(os.path.join(steamapps_path, 'common', installdir_relative))
                            # Verifica installazione
                            is_installed = (app_state.get('StateFlags') == '4') or (os.path.isdir(installdir_absolute))
                            if is_installed and appid not in games:
                                name = app_state.get('name', "Gioco {0}".format(appid)).replace('™', '').replace('®', '').strip()
                                games[appid] = {'name': name, 'installdir': installdir_absolute}
                                total_games_found += 1
        except Exception as e:
            logging.error(f"Error scanning games in '{steamapps_path}': {e}")

    logging.info(f"Found {total_games_found} installed Steam games.")
    _installed_steam_games = games
    return games

# Costante per la conversione ID3 <-> ID64
STEAM_ID64_BASE = 76561197960265728

def find_steam_userdata_info():
    """Trova userdata path, SteamID3, lista ID possibili e dettagli ID (incluso display name).
       Restituisce SEMPRE una tupla di 4 elementi:
       (path|None, id|None, possible_ids_list|[], id_details_dict|{}).
       id_details ora contiene anche 'display_name'.
    """
    global _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details

    # Cache (logica esistente, potrebbe necessitare aggiustamento se vogliamo refresh forzato)
    if (_steam_userdata_path and _steam_id3 and
            _cached_possible_ids is not None and _cached_id_details is not None and
            # Aggiungi controllo: i dettagli contengono già 'display_name'?
            all('display_name' in v for v in _cached_id_details.values())):
        logging.debug("Uso info userdata Steam (con display names) dalla cache.")
        return _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details

    # Resetta cache se ricalcoliamo
    _steam_userdata_path = None; _steam_id3 = None
    _cached_possible_ids = None; _cached_id_details = None

    logging.info("Starting new Steam userdata scan (including profile names)...")
    steam_path = get_steam_install_path()
    if not steam_path:
        logging.error("ERROR: Unable to find Steam installation path.")
        return None, None, [], {}

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        logging.warning(f"Steam 'userdata' folder not found in '{steam_path}'.")
        return None, None, [], {}

    # --- NUOVO: Leggi loginusers.vdf ---
    loginusers_path = os.path.join(steam_path, 'config', 'loginusers.vdf')
    loginusers_data = None
    user_persona_names = {} # Dizionario per mappare SteamID64 -> PersonaName
    if vdf: # Solo se libreria vdf è disponibile
        logging.info(f"Reading profile names from: {loginusers_path}")
        loginusers_data = _parse_vdf(loginusers_path) # Usa helper esistente
        if loginusers_data and 'users' in loginusers_data:
            for steam_id64_str, user_data in loginusers_data['users'].items():
                if isinstance(user_data, dict) and 'PersonaName' in user_data:
                    user_persona_names[steam_id64_str] = user_data['PersonaName']
            logging.info(f"Found {len(user_persona_names)} profile names in loginusers.vdf.")
        else:
            logging.warning("Format 'loginusers.vdf' not recognized or file empty/corrupted.")
    else:
        logging.warning("Library 'vdf' not available, unable to read Steam profile names.")
    # --- FINE LETTURA loginusers.vdf ---

    possible_ids = []
    last_modified_time = 0
    likely_id = None
    id_details = {} # Ricreiamo questo dizionario

    logging.info(f"Searching Steam user ID in: {userdata_base}")
    try:
        for entry in os.listdir(userdata_base): # entry è lo SteamID3 come stringa
            user_path = os.path.join(userdata_base, entry)
            if entry.isdigit() and entry != '0' and os.path.isdir(user_path):
                possible_ids.append(entry)
                current_mtime = 0
                last_mod_str = "N/D"
                display_name = entry # Default: mostra ID3 se non troviamo il nome

                # --- NUOVO: Trova PersonaName ---
                try:
                    steam_id3_int = int(entry)
                    steam_id64 = steam_id3_int + STEAM_ID64_BASE
                    steam_id64_str = str(steam_id64)
                    if steam_id64_str in user_persona_names:
                        display_name = user_persona_names[steam_id64_str] # Usa PersonaName trovato
                except ValueError:
                    logging.warning(f"User ID found in userdata is not numeric: {entry}")
                except Exception as e_name:
                     logging.error(f"ERROR retrieving name for ID {entry}: {e_name}")
                # --- FINE Trova PersonaName ---

                # Cerca data più recente (logica esistente)
                for check_path in [os.path.join(user_path, 'config', 'localconfig.vdf'), user_path]:
                    try:
                        if os.path.exists(check_path):
                            mtime = os.path.getmtime(check_path)
                            current_mtime = max(current_mtime, mtime)
                            # Formatta data più leggibile
                            try:
                                last_mod_str = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M')
                            except ValueError: # Gestisce timestamp invalidi
                                 last_mod_str = "Data invalida"
                    except Exception: pass

                # Salva dettagli, INCLUSO display_name
                id_details[entry] = {
                    'mtime': current_mtime,
                    'last_mod_str': last_mod_str,
                    'display_name': display_name # <-- NUOVO CAMPO
                }

                # Determina ID più probabile (logica esistente)
                if current_mtime > last_modified_time:
                    last_modified_time = current_mtime
                    likely_id = entry

    except Exception as e:
        logging.error(f"ERROR scanning 'userdata': {e}")
        # In caso di errore, resetta tutto per sicurezza
        userdata_base, likely_id, possible_ids, id_details = None, None, [], {}


    # Cache dei risultati completi
    _steam_userdata_path = userdata_base
    _steam_id3 = likely_id
    _cached_possible_ids = possible_ids
    _cached_id_details = id_details # Ora contiene anche display_name

    logging.info(f"Found {len(possible_ids)} IDs in userdata. Most likely ID: {likely_id}")
    for uid, details in id_details.items():
         logging.info(f"  - ID: {uid}, Name: {details.get('display_name', '?')}, Last Mod: {details.get('last_mod_str', '?')}")

    return userdata_base, likely_id, possible_ids, id_details

def are_names_similar(name1, name2, min_match_words=2):
    # ... (versione corretta da risposta precedente) ...
    try:
        clean_name1 = re.sub(r'[™®©:,.-]', '', name1).lower()
        clean_name2 = re.sub(r'[™®©:,.-]', '', name2).lower()
        ignore_words = {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty', 'demo', 'trial', 'play', 'launch'}
        pattern = r'\b(?:[ivx]+|[a-z0-9]+)\b'
        words1 = set(w for w in re.findall(pattern, clean_name1) if w not in ignore_words and len(w) > 1)
        words2 = set(w for w in re.findall(pattern, clean_name2) if w not in ignore_words and len(w) > 1)
        common_words = words1.intersection(words2)
        starts_with_match = False
        name1_no_space = clean_name1.replace(' ', '')
        name2_no_space = clean_name2.replace(' ', '')
        MIN_PREFIX_LEN = 3
        if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
            if len(name1_no_space) > len(name2_no_space):
                starts_with_match = name1_no_space.startswith(name2_no_space)
            elif len(name2_no_space) > len(name1_no_space):
                 starts_with_match = name2_no_space.startswith(name1_no_space)
        is_similar = len(common_words) >= min_match_words or starts_with_match
        return is_similar
    except Exception as e_sim:
        logging.error(f"Error in are_names_similar('{name1}', '{name2}'): {e_sim}", exc_info=True)
        return False

# --- FUNZIONE GUESS_SAVE_PATH AGGIORNATA (CON LOGGING EXTRA) ---
def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True):
    guesses = []
    checked_paths = set()

    sanitized_name = re.sub(r'^(Play |Launch )', '', game_name, flags=re.IGNORECASE)
    sanitized_name = re.sub(r'[™®©:]', '', sanitized_name).strip()
    sanitized_name_nospace = sanitized_name.replace(' ', '')
    acronym = "".join(c for c in sanitized_name if c.isupper())
    valid_acronym = acronym if len(acronym) >= 2 else None
    name_variations = list(dict.fromkeys([sanitized_name, sanitized_name_nospace, valid_acronym] if valid_acronym else [sanitized_name, sanitized_name_nospace]))

    common_publishers = getattr(config, 'COMMON_PUBLISHERS', [])
    common_save_subdirs = getattr(config, 'COMMON_SAVE_SUBDIRS', ['Saves', 'Save', 'SaveGame', 'Worlds', 'Players', 'Characters'])
    common_save_subdirs_lower = {s.lower() for s in common_save_subdirs}

    logging.info(f"Heuristic save search for '{game_name}' (AppID: {appid})")
    logging.info(f"Cleaned game name for search: '{sanitized_name}'")
    if valid_acronym: logging.info(f"Generated acronym for search: '{valid_acronym}'")
    logging.debug(f"Name variations for checks: {name_variations}")
    logging.debug(f"Common save subdirs (lower): {common_save_subdirs_lower}")

    # --- Funzione Helper add_guess (CON LOGGING EXTRA SU ISDIR) ---
    def add_guess(path, source_description):
        if not path: return False
        norm_path = os.path.normpath(path) # Normalizza subito
        if norm_path in checked_paths: return False
        checked_paths.add(norm_path)
        logging.debug(f"  add_guess checking: '{norm_path}' (Source: {source_description})") # Log tentativo

        is_dir = False
        try:
            # --- LOGGING SPECIFICO PER ISDIR ---
            is_dir = os.path.isdir(norm_path)
            logging.debug(f"    os.path.isdir('{norm_path}') returned: {is_dir}")
            # --- FINE LOGGING SPECIFICO ---
        except OSError as e_isdir:
             # Logga esplicitamente errore da isdir
             logging.warning(f"    os.path.isdir('{norm_path}') failed with OSError: {e_isdir}")
             return False # Se isdir fallisce, non possiamo usarlo
        except Exception as e_isdir_other:
             logging.error(f"    os.path.isdir('{norm_path}') failed with unexpected error: {e_isdir_other}")
             return False

        if is_dir:
            try: # remotecache filter
                items = os.listdir(norm_path)
                if len(items) == 1 and os.path.isfile(os.path.join(norm_path, items[0])) and items[0].lower() == "remotecache.vdf":
                    logging.info(f"    Path ignored ('{norm_path}') as it only contains remotecache.vdf.")
                    return False
            except OSError: pass

            drive, tail = os.path.splitdrive(norm_path)
            if not (tail and tail != os.sep):
                logging.debug(f"    Path ignored because it is a root drive: '{norm_path}'")
                return False

            # Check for common save subdirs within this path
            subdir_found = False
            try:
                for item in os.listdir(norm_path):
                    if item.lower() in common_save_subdirs_lower:
                        sub_path = os.path.join(norm_path, item)
                        if os.path.isdir(sub_path): # Verifica se anche la subdir è una cartella
                            logging.info(f"    Found common save subdir '{item}' inside. Adding: '{sub_path}'")
                            source_for_sub = f"{source_description}/{item}"
                            norm_sub_path = os.path.normpath(sub_path)
                            if norm_sub_path not in checked_paths:
                                 checked_paths.add(norm_sub_path)
                                 if norm_sub_path not in guesses:
                                      guesses.append(norm_sub_path)
                            subdir_found = True
            except OSError as e_list_sub:
                 logging.warning(f"    Could not list contents of '{norm_path}' to check for subdirs: {e_list_sub}")

            if not subdir_found:
                 logging.info(f"    Found valid path: '{norm_path}' (Source: {source_description})")
                 if norm_path not in guesses:
                     guesses.append(norm_path)
                 return True
            else:
                 return True # Indicate success as subdirs were added
        else:
             logging.debug(f"    Path '{norm_path}' is not a directory.")
             return False
    # --- END Helper Function add_guess ---

    # --- Steam Userdata Check ---
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        # ... (come prima, chiama add_guess) ...
        logging.info(f"Checking Steam Userdata for AppID {appid} (User: {steam_id3_to_use})...")
        base_userdata = os.path.join(steam_userdata_path, steam_id3_to_use, appid)
        remote_path = os.path.join(base_userdata, 'remote')
        add_guess(remote_path, "Steam Userdata/remote")
        add_guess(base_userdata, "Steam Userdata/AppID Base")

    # --- Generic Heuristic Search ---
    logging.info("Starting generic heuristic search...")
    user_profile = os.path.expanduser('~')
    common_locations = {
        # ... (definizione common_locations come prima) ...
        "Documents": os.path.join(user_profile, 'Documents'),
        "My Games": os.path.join(user_profile, 'Documents', 'My Games'),
        "Saved Games": os.path.join(user_profile, 'Saved Games'),
        "AppData/Roaming": os.getenv('APPDATA'),
        "AppData/Local": os.getenv('LOCALAPPDATA'),
        "AppData/LocalLow": os.path.join(os.getenv('LOCALAPPDATA', ''), '..', 'LocalLow') if os.getenv('LOCALAPPDATA') else None,
        "Public Documents": os.path.join(os.getenv('PUBLIC', 'C:\\Users\\Public'), 'Documents')
    }
    valid_locations = {name: os.path.normpath(path) for name, path in common_locations.items() if path and os.path.isdir(path)}
    logging.debug(f"Valid common locations found: {list(valid_locations.keys())}")

    # --- Direct Path Checks (CON LOGGING EXTRA) ---
    logging.info("Performing direct path checks...") # Log inizio check diretto
    for loc_name, base_folder in valid_locations.items():
        for variation in name_variations:
            if not variation: continue
            # Check <Location>/<GameVariation>
            direct_path = os.path.join(base_folder, variation)
            logging.debug(f"  Direct check: {direct_path}") # Log percorso costruito
            add_guess(direct_path, f"{loc_name}/Direct/{variation}")
            # Check <Location>/<Publisher>/<GameVariation>
            for publisher in common_publishers:
                pub_path = os.path.join(base_folder, publisher, variation)
                logging.debug(f"  Direct check (pub): {pub_path}") # Log percorso costruito
                add_guess(pub_path, f"{loc_name}/{publisher}/Direct/{variation}")

    # --- Exploratory Search ---
    logging.info("Performing exploratory search (iterating folders)...") # Log inizio esplorazione
    for loc_name, base_folder in valid_locations.items():
        # ... (Logica esplorativa come prima, con i suoi log e try/except) ...
        logging.debug(f"Exploring in '{loc_name}' ({base_folder})...")
        try:
            for lvl1_folder_name in os.listdir(base_folder):
                lvl1_path = os.path.join(base_folder, lvl1_folder_name)
                if not os.path.isdir(lvl1_path): continue
                lvl1_name_lower = lvl1_folder_name.lower()
                # logging.debug(f"  Examining Lvl1: '{lvl1_folder_name}'") # Rimosso per meno verbosità
                if are_names_similar(sanitized_name, lvl1_folder_name) or \
                   (valid_acronym and lvl1_name_lower == valid_acronym.lower()):
                    add_guess(lvl1_path, f"{loc_name}/GameNameLvl1/{lvl1_folder_name}")
                try:
                    for lvl2_folder_name in os.listdir(lvl1_path):
                        lvl2_path = os.path.join(lvl1_path, lvl2_folder_name)
                        if not os.path.isdir(lvl2_path): continue
                        lvl2_name_lower = lvl2_folder_name.lower()
                        # logging.debug(f"    Examining Lvl2 (inside '{lvl1_folder_name}'): '{lvl2_folder_name}'") # Rimosso
                        if are_names_similar(sanitized_name, lvl2_folder_name) or \
                           (valid_acronym and lvl2_name_lower == valid_acronym.lower()):
                            add_guess(lvl2_path, f"{loc_name}/{lvl1_folder_name}/GameNameLvl2/{lvl2_folder_name}")
                except OSError as e_lvl1:
                    if not isinstance(e_lvl1, PermissionError) and getattr(e_lvl1, 'winerror', 0) != 5:
                        logging.warning(f"  Could not read inside '{lvl1_path}': {e_lvl1}")
        except OSError as e_base:
             if not isinstance(e_base, PermissionError) and getattr(e_base, 'winerror', 0) != 5:
                logging.warning(f"Error accessing subfolders in '{base_folder}': {e_base}")


    # --- Search Inside Install Dir ---
    if game_install_dir and os.path.isdir(game_install_dir):
        # ... (Logica invariata, log già presenti) ...
        logging.info(f"Checking common subfolders INSIDE (max depth 3) '{game_install_dir}'...")
        max_depth = 3
        install_dir_depth = game_install_dir.rstrip(os.sep).count(os.sep)
        try:
            for root, dirs, files in os.walk(game_install_dir, topdown=True):
                current_relative_depth = root.rstrip(os.sep).count(os.sep) - install_dir_depth
                if current_relative_depth >= max_depth:
                    dirs[:] = []; continue
                for dir_name in list(dirs):
                    potential_path = os.path.join(root, dir_name)
                    relative_log_path = os.path.relpath(potential_path, game_install_dir)
                    if dir_name.lower() in common_save_subdirs_lower:
                        add_guess(potential_path, f"InstallDirWalk/SaveSubdir/{relative_log_path}")
                    elif are_names_similar(sanitized_name, dir_name) or (valid_acronym and dir_name.lower() == valid_acronym.lower()):
                        add_guess(potential_path, f"InstallDirWalk/GameMatch/{relative_log_path}")
        except Exception as e_walk:
             logging.error(f"Error during os.walk in '{game_install_dir}': {e_walk}")

    # --- Deduplicate and Final Sort ---
    # ... (Logica invariata, log già presenti) ...
    final_guesses = []
    for g in guesses:
        norm_g = os.path.normpath(g)
        if norm_g not in final_guesses:
            final_guesses.append(norm_g)
    def final_sort_key(path):
        priority = 0
        path_lower = path.lower()
        if steam_userdata_path and path_lower.startswith(os.path.normpath(steam_userdata_path).lower()):
            priority += 10
        if os.path.basename(path_lower) in common_save_subdirs_lower:
            priority -= 1
        return (priority, path_lower)
    sorted_final_guesses = sorted(final_guesses, key=final_sort_key)
    logging.info(f"Search finished. Found {len(sorted_final_guesses)} unique potential paths (sorted).")
    logging.debug(f"Final sorted paths: {sorted_final_guesses}")

    return sorted_final_guesses

    
def delete_single_backup_file(file_path):
    """Elimina un singolo file di backup specificato dal percorso completo.
    Restituisce (bool successo, str messaggio).
    """
    # Verifica preliminare se il percorso è valido e il file esiste
    if not file_path:
        msg = "ERROR: Nessun percorso file specificato per l'eliminazione."
        logging.error(msg)
        return False, msg
    if not os.path.isfile(file_path): # Controlla se è un file esistente
        msg = f"ERROR: File da eliminare non trovato o non è un file valido: '{file_path}'"
        logging.error(msg)
        # Restituisci successo 'True' se il file non esiste già? O False?
        # Decidiamo che è un errore se si prova a cancellare qualcosa che non c'è.
        return False, msg

    backup_name = os.path.basename(file_path)
    # Logghiamo come WARNING perché è un'azione distruttiva irreversibile
    logging.warning(f"Tentativo di eliminazione permanente del file: {file_path}")

    try:
        # Tenta di eliminare il file
        os.remove(file_path)
        msg = f"File '{backup_name}' eliminato con successo."
        logging.info(msg)
        return True, msg
    except OSError as e:
        # Errore specifico del sistema operativo (es. permessi negati, file in uso)
        msg = f"ERROR del Sistema Operativo durante l'eliminazione di '{backup_name}': {e}"
        logging.error(msg)
        return False, msg
    except Exception as e:
        # Qualsiasi altro errore imprevisto
        msg = f"ERROR imprevisto durante l'eliminazione di '{backup_name}': {e}"
        logging.exception(msg) # Usiamo exception per loggare anche il traceback
        return False, msg
        
def get_directory_size(directory_path):
    """Calcola ricorsivamente la dimensione totale di una cartella in bytes."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(directory_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # Salta link simbolici per evitare cicli o errori
                if not os.path.islink(fp):
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError as e:
                        # Logga errore per file specifico ma continua
                        logging.error(f"ERROR ottenere dimensione per {fp}: {e}")
    except Exception as e:
         logging.error(f"ERROR durante calcolo dimensione per {directory_path}: {e}")
         return -1 # Restituisce -1 per indicare errore nel calcolo
    return total_size

# --- Altre funzioni core se necessario ---