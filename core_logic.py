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
    logging.error("Impossibile determinare APP_DATA_FOLDER, uso percorso relativo per game_save_profiles.json.")
    PROFILES_FILE_PATH = os.path.abspath(PROFILES_FILENAME)
logging.info(f"Percorso file profili in uso: {PROFILES_FILE_PATH}")
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
            logging.error(f"File ultimo backup non trovato ({most_recent_backup_path}) durante getmtime per {profile_name}.")
            # Potrebbe succedere se il file viene eliminato tra list e getmtime (raro)
        except Exception as e:
            logging.error(f"Impossibile ottenere data ultimo backup per {profile_name} da '{most_recent_backup_path}': {e}")
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
            logging.info(f"Caricati {len(profiles)} profili da '{PROFILES_FILE_PATH}'.") # <-- Usa PATH
        except json.JSONDecodeError:
            logging.warning(f"File profili '{PROFILES_FILE_PATH}' corrotto o vuoto...") # <-- Usa PATH
        except Exception as e:
            logging.error(f"Errore caricamento profili da '{PROFILES_FILE_PATH}': {e}") # <-- Usa PATH
    else:
        logging.info(f"File profili '{PROFILES_FILE_PATH}' non trovato...") # <-- Usa PATH
    return profiles

def save_profiles(profiles):
    """Salva i profili in PROFILES_FILE_PATH."""
    # La cartella viene creata da get_app_data_folder()
    try:
        with open(PROFILES_FILE_PATH, 'w', encoding='utf-8') as f: # <-- Usa PATH
            json.dump(profiles, f, indent=4, ensure_ascii=False)
        logging.info(f"Salvati {len(profiles)} profili in '{PROFILES_FILE_PATH}'.") # <-- Usa PATH
        return True
    except Exception as e:
        logging.error(f"Errore salvataggio profili in '{PROFILES_FILE_PATH}': {e}") # <-- Usa PATH
        return False

def delete_profile(profiles, profile_name):
    """Elimina un profilo dal dizionario. Restituisce True se eliminato, False altrimenti."""
    if profile_name in profiles:
        del profiles[profile_name]
        logging.info(f"Profilo '{profile_name}' rimosso dalla memoria.")
        return True
    else:
        logging.warning(f"Tentativo di eliminare profilo non esistente: '{profile_name}'.")
        return False

# --- Operazioni Backup/Restore ---

def manage_backups(profile_name, backup_base_dir, max_backups): # Parametro 'max_backups' (minuscolo)
    """Elimina i backup .zip più vecchi se superano il limite specificato.""" # Docstring aggiornato
    deleted_files = []
    # --- NUOVO: Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name) # <-- Usa nome sanificato
    logging.debug(f"ManageBackups - Nome originale: '{profile_name}', Cartella cercata: '{profile_backup_dir}'")

    try:
        if not os.path.isdir(profile_backup_dir): return deleted_files # Cerca dir sanificata

        logging.info(f"Controllo backup (.zip) obsoleti in: {profile_backup_dir}")
    
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".zip")]

        # --- CORREZIONE 1: Usa il parametro 'max_backups' (minuscolo) ---
        if len(backup_files) <= max_backups:
            # Usa 'max_backups' anche nel messaggio di log
            logging.info(f"Trovati {len(backup_files)} backup (.zip) (<= limite {max_backups}).")
            return deleted_files

        # Calcola num_to_delete una sola volta, usando il parametro minuscolo
        num_to_delete = len(backup_files) - max_backups

        # Ordina i file per data di modifica (dal più vecchio al più recente)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        # --- CORREZIONE 2: Rimuovi la riga duplicata qui sotto ---
        # num_to_delete = len(backup_files) - max_backups # RIGA RIMOSSA

        logging.info(f"Eliminazione dei {num_to_delete} backup (.zip) più vecchi...")

        deleted_count = 0
        # Itera per eliminare i file più vecchi (i primi nella lista ordinata)
        for i in range(num_to_delete):
            file_to_delete = os.path.join(profile_backup_dir, backup_files[i])
            try:
                logging.info(f"  Elimino: {backup_files[i]}")
                os.remove(file_to_delete)
                deleted_files.append(backup_files[i])
                deleted_count += 1
            except Exception as e:
                logging.error(f"  Errore eliminazione {backup_files[i]}: {e}")
        logging.info(f"Eliminati {deleted_count} backup (.zip) obsoleti.")

    except Exception as e:
        # Ora questo loggherà l'eccezione originale se ce ne sono altre, non il NameError
        logging.error(f"Errore gestione backup obsoleti (.zip) per '{profile_name}': {e}")
    return deleted_files


def perform_backup(profile_name, save_folder_path, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard"):
    """Esegue il backup usando zipfile. Restituisce (bool successo, str messaggio)."""
    logging.info(f"Avvio perform_backup per: '{profile_name}'") # Log inizio funzione

    # --- Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    logging.info(f"===> Nome Originale: '{profile_name}', Nome Sanificato Risultante: '{sanitized_folder_name}'") # Log verifica sanitizzazione

    # --- Crea percorso backup USANDO nome sanificato ---
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name) # <-- Riga CRUCIALE!
    logging.debug(f"Percorso backup costruito: '{profile_backup_dir}'") # Log debug percorso

    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.isdir(save_folder_path):
        msg = f"ERRORE: La cartella sorgente dei salvataggi specificata non è valida: '{save_folder_path}'"
        logging.error(msg)
        return False, msg

    # --- Controllo Dimensione Sorgente ---
    # (Nota: sembrano esserci due blocchi uguali per il controllo dimensione, ne basta uno)
    logging.info(f"Controllo dimensione sorgente '{save_folder_path}' (Limite: {'Nessuno' if max_source_size_mb == -1 else str(max_source_size_mb) + ' MB'})...")
    if max_source_size_mb != -1:
        max_source_size_bytes = max_source_size_mb * 1024 * 1024
        current_size_bytes = get_directory_size(save_folder_path)
        if current_size_bytes == -1:
            msg = f"ERRORE: Impossibile calcolare dimensione sorgente '{save_folder_path}'."
            logging.error(msg)
            return False, msg

        current_size_mb = current_size_bytes / (1024*1024)
        logging.info(f"Dimensione attuale sorgente: {current_size_mb:.2f} MB")

        if current_size_bytes > max_source_size_bytes:
            msg = (f"ERRORE: Backup annullato!\n"
                   f"Dimensione sorgente ({current_size_mb:.2f} MB) supera limite ({max_source_size_mb} MB).")
            logging.error(msg)
            return False, msg
    else:
        logging.info("Controllo dimensione sorgente saltato (Nessun Limite impostato).")
    # --- FINE Controllo Dimensione ---

    # --- Creazione Cartella Backup ---
    try:
        logging.info(f"Tentativo di creare/verificare la cartella: '{profile_backup_dir}'") # Log percorso usato
        os.makedirs(profile_backup_dir, exist_ok=True) # <-- Usa percorso (che dovrebbe essere) sanificato
        logging.info(f"Cartella backup verificata/creata: '{profile_backup_dir}'")
    except Exception as e:
        msg = f"ERRORE creazione cartella backup '{profile_backup_dir}': {e}"
        logging.error(msg)
        logging.error(f"(Nome profilo originale problematico: '{profile_name}')")
        return False, msg
    # --- FINE Creazione Cartella ---

    # --- Creazione Archivio ZIP ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Usa nome sanificato anche per il file zip per coerenza? Sì.
    safe_profile_name_for_zip = sanitize_foldername(profile_name) # Riutilizza helper
    if not safe_profile_name_for_zip: safe_profile_name_for_zip = "_backup_" # Fallback se nome diventa vuoto
    archive_name = f"Backup_{safe_profile_name_for_zip}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name) # Usa dir sanificata

    logging.info(f"Inizio backup (ZIP) per '{profile_name}': Da '{save_folder_path}' a '{archive_path}'")

    # Opzioni Compressione
    zip_compression = zipfile.ZIP_DEFLATED
    zip_compresslevel = 6 # Default Standard
    if compression_mode == "stored":
        zip_compression = zipfile.ZIP_STORED
        zip_compresslevel = None
        logging.info("Modalità Compressione: Nessuna (Stored)")
    elif compression_mode == "maximum":
        zip_compresslevel = 9
        logging.info("Modalità Compressione: Massima (Deflate Livello 9)")
    else:
         logging.info("Modalità Compressione: Standard (Deflate Livello 6)")

    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, compresslevel=zip_compresslevel) as zipf:
            for root, dirs, files in os.walk(save_folder_path):
                for file in files:
                    file_path_absolute = os.path.join(root, file)
                    arcname = os.path.relpath(file_path_absolute, save_folder_path)
                    logging.debug(f"  Aggiungo: '{file_path_absolute}' come '{arcname}'")
                    zipf.write(file_path_absolute, arcname=arcname)

        # Gestione backup vecchi (passa nome originale, manage_backups sanifica internamente)
        deleted = manage_backups(profile_name, backup_base_dir, max_backups)
        deleted_msg = f" Eliminati {len(deleted)} backup obsoleti." if deleted else ""
        msg = f"Backup (ZIP) per '{profile_name}' completato con successo.{deleted_msg}"
        logging.info(msg)
        return True, msg

    except (IOError, OSError, zipfile.BadZipFile) as e:
        msg = f"ERRORE durante la creazione del backup ZIP '{archive_name}': {e}"
        logging.exception(msg)
        if os.path.exists(archive_path):
            try: os.remove(archive_path); logging.warning(f"Archivio ZIP fallito rimosso: {archive_name}")
            except Exception as rem_e: logging.error(f"Impossibile rimuovere archivio ZIP fallito: {rem_e}")
        return False, msg
    except Exception as e:
        msg = f"ERRORE imprevisto durante backup ZIP '{profile_name}': {e}"
        logging.exception(msg)
        if os.path.exists(archive_path):
            try: os.remove(archive_path); logging.warning(f"Archivio ZIP fallito rimosso: {archive_name}")
            except Exception as rem_e: logging.error(f"Impossibile rimuovere archivio ZIP fallito: {rem_e}")
        return False, msg


def list_available_backups(profile_name):
    """Restituisce una lista di tuple (nome_file, percorso_completo, data_modifica_str) per i backup di un profilo."""
    backups = []
    # --- NUOVO: Sanifica nome cartella ---
    sanitized_folder_name = sanitize_foldername(profile_name)
    # NOTA: Qui usa ancora config.BACKUP_BASE_DIR, andrebbe uniformato leggendo dalle impostazioni
    # ma per ora sistemiamo solo la sanificazione.
    profile_backup_dir = os.path.join(config.BACKUP_BASE_DIR, sanitized_folder_name) # <-- Usa nome sanificato
    logging.debug(f"ListBackups - Nome originale: '{profile_name}', Cartella cercata: '{profile_backup_dir}'")

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
        logging.error(f"Errore nel listare i backup per '{profile_name}': {e}")

    return backups


def perform_restore(profile_name, save_folder_path, archive_to_restore_path):
    """Esegue il ripristino da un archivio ZIP. Restituisce (bool successo, str messaggio)."""
    save_folder_path = os.path.normpath(save_folder_path)
    if not os.path.exists(archive_to_restore_path) or not zipfile.is_zipfile(archive_to_restore_path):
        msg = f"ERRORE: File ZIP di backup non valido o non trovato: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg

    # Assicurati che la destinazione esista
    try:
        os.makedirs(save_folder_path, exist_ok=True)
    except Exception as e:
        msg = f"ERRORE creazione cartella destinazione '{save_folder_path}': {e}"
        logging.error(msg)
        return False, msg

    logging.info(f"Inizio ripristino (ZIP) per '{profile_name}': Da '{os.path.basename(archive_to_restore_path)}' a '{save_folder_path}'")

    try:
        # Apri l'archivio ZIP in lettura ('r')
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:
            # Estrai TUTTO il contenuto nella cartella di destinazione
            # I percorsi relativi (senza la cartella base) memorizzati durante il backup
            # verranno ricreati a partire da 'save_folder_path'.
            # extractall sovrascrive i file esistenti per default.
            logging.info(f"Estrazione di '{archive_to_restore_path}' in '{save_folder_path}'...")
            zipf.extractall(path=save_folder_path)

        msg = f"Ripristino (ZIP) per '{profile_name}' completato con successo."
        logging.info(msg)
        return True, msg

    except (zipfile.BadZipFile, IOError, OSError) as e:
        msg = f"ERRORE durante l'estrazione del backup ZIP '{os.path.basename(archive_to_restore_path)}': {e}"
        logging.exception(msg)
        return False, msg
    except Exception as e:
        msg = f"ERRORE imprevisto durante ripristino ZIP '{profile_name}': {e}"
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
                     logging.info(f"Trovata installazione Steam ({hive_name}): {_steam_install_path}")
                     return _steam_install_path
            except (FileNotFoundError, OSError): continue # Ignora se chiave non trovata o accesso negato
            except Exception as e: logging.warning(f"Errore lettura registro ({hive_name}): {e}")

        logging.error("Installazione Steam non trovata nel registro.")
        return None
    except Exception as e:
        logging.error(f"Errore imprevisto ricerca Steam: {e}")
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
             logging.error(f"Errore parsing VDF '{os.path.basename(file_path)}': {e}")
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
    logging.info(f"Lettura librerie da: {vdf_path}")
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

    logging.info(f"Trovate {len(libs)} librerie Steam totali ({added_libs_count} da VDF).")
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

    logging.info("Scansione librerie per giochi Steam installati...")
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
                                name = app_state.get('name', f"Gioco {appid}").replace('™', '').replace('®', '').strip()
                                games[appid] = {'name': name, 'installdir': installdir_absolute}
                                total_games_found += 1
        except Exception as e:
            logging.error(f"Errore scansione giochi in '{steamapps_path}': {e}")

    logging.info(f"Trovati {total_games_found} giochi Steam installati.")
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

    logging.info("Avvio nuova scansione userdata Steam (incluso nomi profili)...")
    steam_path = get_steam_install_path()
    if not steam_path:
        logging.error("Installazione Steam non trovata durante ricerca userdata.")
        return None, None, [], {}

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        logging.warning(f"Cartella 'userdata' non trovata in '{steam_path}'.")
        return None, None, [], {}

    # --- NUOVO: Leggi loginusers.vdf ---
    loginusers_path = os.path.join(steam_path, 'config', 'loginusers.vdf')
    loginusers_data = None
    user_persona_names = {} # Dizionario per mappare SteamID64 -> PersonaName
    if vdf: # Solo se libreria vdf è disponibile
        logging.info(f"Lettura nomi profilo da: {loginusers_path}")
        loginusers_data = _parse_vdf(loginusers_path) # Usa helper esistente
        if loginusers_data and 'users' in loginusers_data:
            for steam_id64_str, user_data in loginusers_data['users'].items():
                if isinstance(user_data, dict) and 'PersonaName' in user_data:
                    user_persona_names[steam_id64_str] = user_data['PersonaName']
            logging.info(f"Trovati {len(user_persona_names)} nomi profilo in loginusers.vdf.")
        else:
            logging.warning("Formato 'loginusers.vdf' non riconosciuto o file vuoto/corrotto.")
    else:
        logging.warning("Libreria 'vdf' non disponibile, impossibile leggere i nomi profilo Steam.")
    # --- FINE LETTURA loginusers.vdf ---

    possible_ids = []
    last_modified_time = 0
    likely_id = None
    id_details = {} # Ricreiamo questo dizionario

    logging.info(f"Ricerca ID utente Steam in: {userdata_base}")
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
                    logging.warning(f"ID utente non numerico trovato in userdata: {entry}")
                except Exception as e_name:
                     logging.error(f"Errore recupero nome per ID {entry}: {e_name}")
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
        logging.error(f"Errore scansione 'userdata': {e}")
        # In caso di errore, resetta tutto per sicurezza
        userdata_base, likely_id, possible_ids, id_details = None, None, [], {}


    # Cache dei risultati completi
    _steam_userdata_path = userdata_base
    _steam_id3 = likely_id
    _cached_possible_ids = possible_ids
    _cached_id_details = id_details # Ora contiene anche display_name

    logging.info(f"Trovati {len(possible_ids)} ID in userdata. ID più probabile: {likely_id}")
    for uid, details in id_details.items():
         logging.info(f"  - ID: {uid}, Nome: {details.get('display_name', '?')}, Ultima Mod: {details.get('last_mod_str', '?')}")

    return userdata_base, likely_id, possible_ids, id_details

def are_names_similar(name1, name2, min_match_words=2):
    """Checks if two names share a minimum number of significant words (case-insensitive)."""
    try:
        # Pulizia base: rimuovi simboli comuni, converti in minuscolo
        # Mantieni numeri romani (I, V, X) - regex semplificata
        # Aggiunto lo spazio alla lista di caratteri da NON rimuovere subito
        clean_name1 = re.sub(r'[™®©:,.-]', '', name1).lower()
        clean_name2 = re.sub(r'[™®©:,.-]', '', name2).lower()

        # Dividi in parole (alfanumeriche o numeri romani I,V,X), ignora parole comuni corte
        ignore_words = {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty', 'demo', 'trial', 'play', 'launch'}
        pattern = r'\b(?:[ivx]+|[a-z0-9]+)\b' # Trova parole o numeri romani
        words1 = set(w for w in re.findall(pattern, clean_name1) if w not in ignore_words and len(w) > 1)
        words2 = set(w for w in re.findall(pattern, clean_name2) if w not in ignore_words and len(w) > 1)

        common_words = words1.intersection(words2)

        # Controlla anche se una parte significativa inizia con l'altra (dopo pulizia)
        sstarts_with_match = False
        # Usa le versioni pulite SENZA spazi per il controllo startswith
        name1_no_space = clean_name1.replace(' ', '')
        name2_no_space = clean_name2.replace(' ', '')

        # Definisci una lunghezza minima ragionevole per evitare match casuali (es. 'a' vs 'apple')
        MIN_PREFIX_LEN = 3

        # Controlla se ENTRAMBI i nomi sono lunghi almeno MIN_PREFIX_LEN
        if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
            # Esegui startswith controllando il più lungo vs il più corto
            if len(name1_no_space) > len(name2_no_space):
                starts_with_match = name1_no_space.startswith(name2_no_space)
            elif len(name2_no_space) > len(name1_no_space):
                 starts_with_match = name2_no_space.startswith(name1_no_space)
            # else: # Se hanno stessa lunghezza, startswith funziona solo se sono identici
            #    starts_with_match = (name1_no_space == name2_no_space)
            #    Non serve gestirlo esplicitamente, se sono uguali probabilmente hanno common_words
    # --- FINE NUOVO Blocco ---

        # Considera simili se condividono abbastanza parole O se uno inizia con l'altro
        is_similar = len(common_words) >= min_match_words or starts_with_match
        # Rimuoviamo il logging di debug da qui per non intasare troppo
        # logging.debug(f"Similarity Check: '{name1}' vs '{name2}' -> W1={words1}, W2={words2}, Common={common_words}, StartsWith={starts_with_match} -> Similar={is_similar}")
        return is_similar
    except Exception as e_sim:
        logging.error(f"Error in are_names_similar('{name1}', '{name2}'): {e_sim}")
        return False # Default a non simile in caso di errore

def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True):
    """
    Tenta di indovinare la cartella salvataggi per un gioco usando euristiche.
    Se is_steam_game è True e le info sono fornite, controlla anche Steam Userdata.
    Include filtro remotecache, ricerca acronimo e check per save annidati.
    """
    guesses = []
    checked_paths = set() # Per evitare duplicati e controlli ripetuti

    # --- Funzione Helper add_guess (con filtro remotecache.vdf) ---
    def add_guess(path, source_description):
        """
        Helper interno per aggiungere un percorso valido alla lista,
        con controlli aggiuntivi (non radice, non solo remotecache.vdf).
        """
        if not path: return False
        try:
            norm_path = os.path.normpath(path)
            if norm_path in checked_paths: return False
            checked_paths.add(norm_path)

            if os.path.isdir(norm_path):
                # Check filtro remotecache.vdf
                try:
                    items = os.listdir(norm_path)
                    if len(items) == 1:
                        single_item_path = os.path.join(norm_path, items[0])
                        if os.path.isfile(single_item_path) and items[0].lower() == "remotecache.vdf":
                            logging.info(f"Percorso ignorato ('{norm_path}') perché contiene solo remotecache.vdf. Fonte: {source_description}")
                            return False
                except OSError as e_list:
                    logging.warning(f"Impossibile leggere il contenuto di '{norm_path}' durante il check remotecache: {e_list}")

                # Check non-radice
                drive, tail = os.path.splitdrive(norm_path)
                if tail and tail != os.sep:
                    logging.info(f"Trovato percorso potenziale valido ({source_description}): '{norm_path}'")
                    if norm_path not in guesses:
                        guesses.append(norm_path)
                    return True # Indica che il percorso è stato aggiunto o era già valido/presente
                else:
                    logging.debug(f"Percorso ignorato perché è una radice: '{norm_path}'")
        except Exception as e:
            logging.warning(f"Errore durante la verifica del percorso '{path}': {e}")
        return False # Se uno qualsiasi dei controlli fallisce o c'è errore
    # --- FINE Funzione Helper add_guess ---


    # --- 1. Pulisci il Nome del Gioco ---
    logging.info(f"Ricerca euristica salvataggi per '{game_name}' (AppID: {appid})")
    sanitized_name = re.sub(r'^(Play |Launch )', '', game_name, flags=re.IGNORECASE)
    sanitized_name = re.sub(r'[™®©:]', '', sanitized_name).strip()
    logging.info(f"Nome gioco pulito per ricerca: '{sanitized_name}'")

    # --- 2. Genera Acronimo Semplice ---
    acronym = "".join(c for c in sanitized_name if c.isupper())
    valid_acronym = acronym if len(acronym) >= 2 else None
    if valid_acronym:
        logging.info(f"Acronimo generato per ricerca: '{valid_acronym}'")
    # --- FINE Genera Acronimo ---


    # --- 3. Steam Userdata ---
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        logging.info(f"Controllo Steam Userdata per AppID {appid} (Utente: {steam_id3_to_use})...")
        base_userdata = os.path.join(steam_userdata_path, steam_id3_to_use, appid)
        remote_path = os.path.join(base_userdata, 'remote')
        # Aggiungi remote_path se valido
        if add_guess(remote_path, "Steam Userdata/remote"):
            # E controlla anche DENTRO remote per sottocartelle rilevanti
            try:
                for entry in os.listdir(remote_path):
                    sub = os.path.join(remote_path, entry)
                    sub_lower = entry.lower()
                    if os.path.isdir(sub) and \
                       (any(s in sub_lower for s in ['save', 'profile']) or \
                        are_names_similar(sanitized_name, entry) or \
                        (valid_acronym and sub_lower == valid_acronym.lower())):
                         add_guess(sub, f"Steam Userdata/remote/{entry}")
            except Exception as e_remote_sub: logging.warning(f"Errore scansione sottocartelle in remote: {e_remote_sub}")
        # Aggiungi la cartella base dell'AppID se valida
        add_guess(base_userdata, "Steam Userdata/AppID Base")
    # --- FINE Sezione 3 ---


    # --- 4. Ricerca Euristica Generica (Cartelle Comuni Utente) ---
    logging.info("Inizio ricerca euristica generica (incl. acronimo)...")
    user_profile = os.path.expanduser('~')
    logging.debug(f"  Profilo utente ('~'): {user_profile}")
    common_locations = {
        "Documents": os.path.join(user_profile, 'Documents'),
        "My Games": os.path.join(user_profile, 'Documents', 'My Games'),
        "Saved Games": os.path.join(user_profile, 'Saved Games'),
        "AppData/Roaming": os.getenv('APPDATA'),
        "AppData/Local": os.getenv('LOCALAPPDATA'),
        "AppData/LocalLow": os.path.join(os.getenv('LOCALAPPDATA', ''), '..', 'LocalLow') if os.getenv('LOCALAPPDATA') else None,
        "Public Documents": os.path.join(os.getenv('PUBLIC', 'C:\\Users\\Public'), 'Documents')
    }
    logging.debug(f"  Percorsi comuni candidati: {common_locations}")
    valid_locations = {name: os.path.normpath(path) for name, path in common_locations.items() if path and os.path.isdir(path)}
    logging.debug(f"  Percorsi comuni VALIDI trovati: {valid_locations}")

    common_publishers = [
         'My Games', 'Saved Games', 'Ubisoft', 'EA', 'Electronic Arts', 'Rockstar Games',
         'Bethesda Softworks', 'CD Projekt Red', 'Square Enix', 'Activision', 'Valve',
         'Epic Games', 'FromSoftware', 'Capcom', 'Sega', 'Bandai Namco', 'DevolverDigital',
         '2K Games', 'Paradox Interactive', 'Team17', 'Focus Home Interactive', 'HelloGames',
         'Warner Bros. Interactive Entertainment', 'WB Games', 'Landfall Games', 'Team Cherry'
    ]
    common_save_subdirs = ['Saves', 'Save', 'SaveGame', 'SaveGames', 'Saved', 'storage', 'PlayerData', 'Profile', 'Profiles', 'User', 'Data', 'SaveData', 'Backup']
    common_save_subdirs_lower = {s.lower() for s in common_save_subdirs} # Crea set minuscolo una volta

    for loc_name, base_folder in valid_locations.items():
        logging.debug(f"Controllo in '{loc_name}' ({base_folder})...")
        try: # Try per listdir su base_folder
            for actual_subfolder in os.listdir(base_folder):
                actual_subfolder_path = os.path.join(base_folder, actual_subfolder)
                if not os.path.isdir(actual_subfolder_path): continue

                actual_subfolder_lower = actual_subfolder.lower()
                logging.debug(f"  Esamino sottocartella: '{actual_subfolder}'")

                # Check Acronimo Diretto
                if valid_acronym and actual_subfolder_lower == valid_acronym.lower():
                     logging.debug("    -> Trovata corrispondenza Acronimo Diretto!")
                     add_guess(actual_subfolder_path, f"{loc_name}/AcronymDirect")

                # Check Nome Simile
                is_similar_name_lvl1 = are_names_similar(sanitized_name, actual_subfolder)
                logging.debug(f"    -> Risultato are_names_similar('{sanitized_name}', '{actual_subfolder}'): {is_similar_name_lvl1}")
                if is_similar_name_lvl1:
                    added_main = add_guess(actual_subfolder_path, f"{loc_name}/SimilarNameLvl1")
                    if added_main:
                        try: # Try per listdir su actual_subfolder_path
                            logging.debug(f"      Controllo SaveSubdir DENTRO '{actual_subfolder_path}'...")
                            for inner in os.listdir(actual_subfolder_path):
                                if inner.lower() in common_save_subdirs_lower:
                                    intermediate_path = os.path.join(actual_subfolder_path, inner)
                                    logging.debug(f"        Trovato SaveSubdir intermedio: '{intermediate_path}'")
                                    # --- Check Annidato ---
                                    deeper_path_found = None
                                    if os.path.isdir(intermediate_path):
                                        try: # Try per listdir su intermediate_path
                                            logging.debug("          Controllo DENTRO SaveSubdir intermedio...")
                                            for deeper_item in os.listdir(intermediate_path):
                                                deeper_path = os.path.join(intermediate_path, deeper_item)
                                                if os.path.isdir(deeper_path) and deeper_item.lower() in common_save_subdirs_lower:
                                                    deeper_path_found = deeper_path
                                                    logging.debug(f"            -> Trovato percorso save annidato: {deeper_path_found}")
                                                    break
                                        except OSError as e_deeper:
                                            logging.warning(f"          Impossibile leggere dentro '{intermediate_path}': {e_deeper}")
                                    # --- Fine Check Annidato ---
                                    if deeper_path_found:
                                        logging.debug(f"        -> Aggiungo percorso annidato: {deeper_path_found}")
                                        add_guess(deeper_path_found, f"{loc_name}/SimilarNameLvl1/SaveSubdirNested")
                                    elif os.path.isdir(intermediate_path):
                                        logging.debug(f"        -> Aggiungo percorso intermedio: {intermediate_path}")
                                        add_guess(intermediate_path, f"{loc_name}/SimilarNameLvl1/SaveSubdir")
                        except OSError: pass # Ignora errori lettura dentro actual_subfolder_path

                # Check Publisher comune
                is_common_publisher = any(p.lower() == actual_subfolder_lower for p in common_publishers)
                if is_common_publisher:
                    logging.debug(f"  Lvl1: '{actual_subfolder}' è un PUBLISHER comune.")
                    try: # Try per listdir su actual_subfolder_path (publisher)
                        logging.debug(f"    Controllo DENTRO Publisher '{actual_subfolder_path}'...")
                        for inner_folder in os.listdir(actual_subfolder_path):
                            inner_folder_path = os.path.join(actual_subfolder_path, inner_folder)
                            if not os.path.isdir(inner_folder_path): continue

                            inner_folder_lower = inner_folder.lower()

                            # Check Acronimo Dentro Publisher
                            if valid_acronym and inner_folder_lower == valid_acronym.lower():
                                 logging.debug("      -> Trovata corrispondenza Acronimo in Publisher!")
                                 add_guess(inner_folder_path, f"{loc_name}/{actual_subfolder}/AcronymInPublisher")

                            # Check Nome Simile Dentro Publisher
                            is_similar_name_lvl2 = are_names_similar(sanitized_name, inner_folder)
                            logging.debug(f"      -> Risultato are_names_similar('{sanitized_name}', '{inner_folder}'): {is_similar_name_lvl2}")
                            if is_similar_name_lvl2:
                                added_inner = add_guess(inner_folder_path, f"{loc_name}/{actual_subfolder}/SimilarNameLvl2")
                                if added_inner:
                                    try: # Try per listdir su inner_folder_path
                                        logging.debug(f"        Controllo SaveSubdir DENTRO '{inner_folder_path}'...")
                                        for save_subdir in os.listdir(inner_folder_path):
                                            if save_subdir.lower() in common_save_subdirs_lower:
                                                intermediate_path = os.path.join(inner_folder_path, save_subdir)
                                                logging.debug(f"          Trovato SaveSubdir intermedio: '{intermediate_path}'")
                                                # --- Check Annidato ---
                                                deeper_path_found = None
                                                if os.path.isdir(intermediate_path):
                                                    try: # Try per listdir su intermediate_path
                                                        logging.debug("            Controllo DENTRO SaveSubdir intermedio...")
                                                        for deeper_item in os.listdir(intermediate_path):
                                                            deeper_path = os.path.join(intermediate_path, deeper_item)
                                                            if os.path.isdir(deeper_path) and deeper_item.lower() in common_save_subdirs_lower:
                                                                deeper_path_found = deeper_path
                                                                logging.debug(f"              -> Trovato percorso save annidato (in pub/sim): {deeper_path_found}")
                                                                break
                                                    except OSError as e_deeper:
                                                        logging.warning(f"            Impossibile leggere dentro '{intermediate_path}': {e_deeper}")
                                                # --- Fine Check Annidato ---
                                                if deeper_path_found:
                                                    logging.debug(f"          -> Aggiungo percorso annidato: {deeper_path_found}")
                                                    add_guess(deeper_path_found, f"{loc_name}/{actual_subfolder}/SimilarNameLvl2/SaveSubdirNested")
                                                elif os.path.isdir(intermediate_path):
                                                    logging.debug(f"          -> Aggiungo percorso intermedio: {intermediate_path}")
                                                    add_guess(intermediate_path, f"{loc_name}/{actual_subfolder}/SimilarNameLvl2/SaveSubdir")
                                    except OSError: pass # Ignora errori lettura dentro inner_folder_path
                    except OSError as e_pub_inner:
                         logging.warning(f"Errore accesso sottocartelle in publisher '{actual_subfolder_path}': {e_pub_inner}")

        except OSError as e_base:
            logging.warning(f"Errore accesso sottocartelle in '{base_folder}': {e_base}")
    # --- FINE Sezione 4 ---


    # --- 5. Ricerca Euristica (Dentro Cartella Installazione) ---
    if game_install_dir and os.path.isdir(game_install_dir):
        logging.info(f"Controllo sottocartelle comuni DENTRO (max depth 3) '{game_install_dir}'...")
        max_depth = 3
        install_dir_depth = game_install_dir.rstrip(os.sep).count(os.sep)
        try:
            for root, dirs, files in os.walk(game_install_dir, topdown=True):
                # Limita profondità
                current_relative_depth = root.rstrip(os.sep).count(os.sep) - install_dir_depth
                if current_relative_depth >= max_depth:
                    dirs[:] = [] # Non scendere oltre
                    continue
                # Cerca cartelle save comuni
                for dir_name in list(dirs):
                    potential_path = os.path.join(root, dir_name)
                    if dir_name.lower() in common_save_subdirs_lower:
                        # Verifica che sia effettivamente una cartella prima di aggiungerla
                        if os.path.isdir(potential_path):
                            relative_log_path = os.path.relpath(potential_path, game_install_dir)
                            add_guess(potential_path, f"InstallDirWalk/{relative_log_path}")
        except Exception as e_walk:
             logging.error(f"Errore durante os.walk in '{game_install_dir}': {e_walk}")
    # --- FINE Sezione 5 ---


    # --- Rimozione Duplicati e Return ---
    final_guesses = []
    for g in guesses:
        if g not in final_guesses:
            final_guesses.append(g)
    logging.info(f"Ricerca terminata. Trovati {len(final_guesses)} percorsi unici potenziali.")
    return final_guesses

    
def delete_single_backup_file(file_path):
    """Elimina un singolo file di backup specificato dal percorso completo.
    Restituisce (bool successo, str messaggio).
    """
    # Verifica preliminare se il percorso è valido e il file esiste
    if not file_path:
        msg = "Errore: Nessun percorso file specificato per l'eliminazione."
        logging.error(msg)
        return False, msg
    if not os.path.isfile(file_path): # Controlla se è un file esistente
        msg = f"Errore: File da eliminare non trovato o non è un file valido: '{file_path}'"
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
        msg = f"Errore del Sistema Operativo durante l'eliminazione di '{backup_name}': {e}"
        logging.error(msg)
        return False, msg
    except Exception as e:
        # Qualsiasi altro errore imprevisto
        msg = f"Errore imprevisto durante l'eliminazione di '{backup_name}': {e}"
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
                        logging.error(f"Impossibile ottenere dimensione per {fp}: {e}")
    except Exception as e:
         logging.error(f"Errore durante calcolo dimensione per {directory_path}: {e}")
         return -1 # Restituisce -1 per indicare errore nel calcolo
    return total_size

# --- Altre funzioni core se necessario ---