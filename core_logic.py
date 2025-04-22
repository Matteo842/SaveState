# core_logic.py
# -*- coding: utf-8 -*-
from datetime import datetime
import logging
import os
import json
import config
import re
import platform
import glob

try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Libreria 'thefuzz' trovata e caricata.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    # Logga il warning una sola volta qui all'avvio se manca
    logging.warning("Libreria 'thefuzz' non trovata. Il fuzzy matching sarà disabilitato.")
    logging.warning("Installala con: pip install thefuzz[speedup]")

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

# <<< Funzione per generare abbreviazioni multiple >>>
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

# <<< Helper per check sequenza iniziali >>>
def matches_initial_sequence(folder_name, game_title_words):
    """
    Controlla se folder_name (es. "ME") CORRISPONDE ESATTAMENTE alla sequenza
    delle iniziali di game_title_words (es. ["Metro", "Exodus"]).
    """
    if not folder_name or not game_title_words:
        return False
    try:
        # Estrai le iniziali MAIUSCOLE dalle parole significative
        word_initials = [word[0].upper() for word in game_title_words if word]
        # Unisci le iniziali per formare la sequenza attesa (es. "ME")
        expected_sequence = "".join(word_initials)
        # Confronta (case-insensitive) il nome della cartella con la sequenza attesa
        return folder_name.upper() == expected_sequence
    except Exception as e:
        # Logga eventuali errori imprevisti durante l'elaborazione
        logging.error(f"Error in matches_initial_sequence ('{folder_name}', {game_title_words}): {e}")
        return False

def sanitize_foldername(name):
    """Rimuove o sostituisce caratteri non validi per nomi di file/cartelle,
       preservando i punti interni e rimuovendo quelli esterni."""
    if not isinstance(name, str):
        return "_invalid_profile_name_" # Gestisce input non stringa

    # 1. Rimuovi caratteri universalmente non validi nei nomi file/cartella
    #    ( <>:"/\|?* ) Manteniamo lettere, numeri, spazi, _, -, .
    #    Usiamo un'espressione regolare per questo.
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name)

    # 2. Rimuovi spazi bianchi iniziali/finali
    safe_name = safe_name.strip()

    # 3. Rimuovi PUNTI iniziali/finali (DOPO aver rimosso gli spazi)
    #    Questo ciclo rimuove multipli punti se presenti (es. "..nome..")
    if safe_name: # Evita errori se la stringa è diventata vuota
        safe_name = safe_name.strip('.')

    # 4. Rimuovi di nuovo eventuali spazi bianchi che potrebbero essere
    #    rimasti esposti dopo aver tolto i punti (es. ". nome .")
    safe_name = safe_name.strip()

    # 5. Gestisci caso in cui il nome diventi vuoto o solo spazi dopo la pulizia
    if not safe_name or safe_name.isspace():
        safe_name = "_invalid_profile_name_" # Nome di fallback

    return safe_name

 # --- Gestione Profili ---

def get_profile_backup_summary(profile_name, backup_base_dir):
    """
    Restituisce un riassunto dei backup per un profilo.
    Returns: tuple (count: int, last_backup_datetime: datetime | None)
    """
    # Usa la funzione esistente che già ordina per data (nuovo prima)
    backups = list_available_backups(profile_name, backup_base_dir) # Passa l'argomento
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

# --- Funzione per caricare i profili ---
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

# --- Funzione per salvare i profili ---
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

# --- Funzione per aggiungere un profilo ---
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

# --- Funzione di backup ---
def perform_backup(profile_name, save_folder_path, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard"):
    """Esegue il backup usando zipfile. Restituisce (bool successo, str messaggio)."""
    import zipfile
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

# --- Funzione di supporto per calcolo dimensione cartella ---
def list_available_backups(profile_name, backup_base_dir):
    """Restituisce una lista di tuple (nome_file, percorso_completo, data_modifica_str) per i backup di un profilo."""
    backups = []
    sanitized_folder_name = sanitize_foldername(profile_name)
    # <<< MODIFICATO: Usa backup_base_dir dalle impostazioni (richiede passaggio o accesso globale)
    # Assumendo che 'config' fornisca il percorso corretto
    
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

# --- Funzione di Ripristino ---
def perform_restore(profile_name, save_folder_path, archive_to_restore_path):
    """Esegue il ripristino da un archivio ZIP. Restituisce (bool successo, str messaggio)."""
    import zipfile
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

# Trova il percorso di installazione di Steam
def get_steam_install_path():
    """Trova il percorso di installazione di Steam. Restituisce str o None."""
    try:
        import winreg # <-- Import spostato qui
    except ImportError:
         logging.warning("Modulo winreg non disponibile su questa piattaforma.")
         return None # O gestisci l'errore come preferisci
    
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

# Trova il percorso userdata di Steam
def _parse_vdf(file_path):
    """Helper interno per parsare VDF. Restituisce dict o None."""
    try:
        import vdf # <--- SPOSTATO QUI DENTRO
    except ImportError:
         vdf = None # Imposta a None se fallisce per gestirlo dopo

    if vdf is None:
        # Logga l'errore solo se si prova effettivamente a parsare
        logging.error("Libreria 'vdf' non trovata. Impossibile parsare file VDF.")
        return None
    if not os.path.isfile(file_path): return None
   
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

# Trova librerie Steam
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

# Trova giochi installati
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
    try:
        import vdf
    except ImportError:
        vdf = None
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

# <<< Funzione are_names_similar usa anche check sequenza >>>
def are_names_similar(name1, name2, min_match_words=2, fuzzy_threshold=88, game_title_words_for_seq=None):
    try:
        # --- Pulizia Migliorata ---
        # Rimuovi TUTTO tranne lettere, numeri e spazi, poi normalizza spazi
        pattern_alphanum_space = r'[^a-zA-Z0-9\s]'
        clean_name1 = re.sub(pattern_alphanum_space, '', name1).lower()
        clean_name2 = re.sub(pattern_alphanum_space, '', name2).lower()
        # Normalizza spazi multipli/iniziali/finali
        clean_name1 = re.sub(r'\s+', ' ', clean_name1).strip()
        clean_name2 = re.sub(r'\s+', ' ', clean_name2).strip()

        try:
             ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty', 'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete', 'collection', 'hd', 'ultra', 'deluxe', 'game', 'year'})
             ignore_words_lower = {w.lower() for w in ignore_words}
        except Exception as e_config:
             logging.error(f"ARE_NAMES_SIMILAR: Error getting ignore words from config: {e_config}")
             ignore_words_lower = {'a', 'an', 'the', 'of', 'and'} # Fallback sicuro

        # Usa il pattern aggiornato per estrarre parole (solo lettere/numeri)
        pattern_words = r'\b\w+\b' # \w include numeri e underscore, va bene qui
        words1 = {w for w in re.findall(pattern_words, clean_name1) if w not in ignore_words_lower and len(w) > 1}
        words2 = {w for w in re.findall(pattern_words, clean_name2) if w not in ignore_words_lower and len(w) > 1}

        # 1. Check parole comuni
        common_words = words1.intersection(words2)
        common_check_result = len(common_words) >= min_match_words
        if common_check_result:
            return True

        # 2. Check prefix (starts_with) / uguaglianza senza spazi
        name1_no_space = clean_name1.replace(' ', '') # Ora dovrebbe essere "overcooked2"
        name2_no_space = clean_name2.replace(' ', '') # Questo è "overcooked2"
        MIN_PREFIX_LEN = 3
        starts_with_match = False
        if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
            # Controlla uguaglianza esatta senza spazi PRIMA di startswith
            if name1_no_space == name2_no_space:
                 starts_with_match = True # <<-- QUI DOVREBBE DIVENTARE TRUE
            elif len(name1_no_space) > len(name2_no_space):
                if name1_no_space.startswith(name2_no_space): starts_with_match = True
            elif len(name2_no_space) > len(name1_no_space):
                 if name2_no_space.startswith(name1_no_space): starts_with_match = True    
        if starts_with_match:
            return True

        # 3. Check Sequenza Iniziali
        seq_match_result = False
        if game_title_words_for_seq:
            seq_match_result = matches_initial_sequence(name2, game_title_words_for_seq) # Assumi matches_initial_sequence esista e funzioni
            if seq_match_result:
                 return True

        # 4. Fuzzy Matching
        if THEFUZZ_AVAILABLE and fuzzy_threshold <= 100:
            # Definisci ratio SOLO qui dentro
            ratio = fuzz.token_sort_ratio(clean_name1, clean_name2)
            fuzzy_check_result = ratio >= fuzzy_threshold
            if fuzzy_check_result:
                # Ritorna immediatamente se il check fuzzy passa
                return True
        # Se nessuna condizione sopra ha ritornato True
        return False
    except Exception as e_sim:
        logging.error(f"ARE_NAMES_SIMILAR: === Error comparing '{name1}' vs '{name2}': {e_sim} ===", exc_info=True)
        return False # Ritorna False in caso di errore

# <<< Funzione per indovinare i percorsi di salvataggio >>>
def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None):
    """
    Tenta di indovinare i possibili percorsi di salvataggio per un gioco usando varie euristiche.
    Chiama le funzioni esterne `clean_for_comparison` e `final_sort_key` per l'elaborazione e l'ordinamento.

    Args:
        game_name (str): Nome del gioco.
        game_install_dir (str|None): Percorso di installazione del gioco (se noto).
        appid (str|None): Steam AppID del gioco (se noto).
        steam_userdata_path (str|None): Percorso base della cartella userdata di Steam.
        steam_id3_to_use (str|None): SteamID3 dell'utente da usare per la ricerca in userdata.
        is_steam_game (bool): Flag che indica se è un gioco Steam.
        installed_steam_games_dict (dict|None): Dizionario {appid: {'name':..., 'installdir':...}}
                                                dei giochi Steam installati.

    Returns:
        list[tuple[str, int]]: Lista di tuple (percorso_trovato, punteggio) ordinate per probabilità decrescente.
    """
    guesses_data = {}
    checked_paths = set()

    # --- Variabili comuni (accessibili anche da final_sort_key tramite il dizionario) ---
    sanitized_name_base = re.sub(r'^(Play |Launch )', '', game_name, flags=re.IGNORECASE)
    sanitized_name = re.sub(r'[™®©:]', '', sanitized_name_base).strip()
    game_abbreviations = generate_abbreviations(sanitized_name, game_install_dir)
    if sanitized_name not in game_abbreviations: game_abbreviations.insert(0, sanitized_name)

    # --- Calcola set maiuscoli/minuscoli ---
    game_abbreviations_upper = set(a.upper() for a in game_abbreviations if a) # Aggiunto 'if a' per sicurezza
    game_abbreviations_lower = set(a.lower() for a in game_abbreviations if a) # Aggiunto 'if a' per sicurezza
    # --- FINE ---
    
    # Carica configurazioni
    try:
        ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', set())
        common_save_extensions = getattr(config, 'COMMON_SAVE_EXTENSIONS', set())
        common_save_filenames = getattr(config, 'COMMON_SAVE_FILENAMES', set())
        common_save_subdirs = getattr(config, 'COMMON_SAVE_SUBDIRS', [])
        common_publishers = getattr(config, 'COMMON_PUBLISHERS', [])
        common_publishers_set = set(p.lower() for p in common_publishers if p) # Converti in minuscolo per check case-insensitive
        
        BANNED_FOLDER_NAMES_LOWER = getattr(config, 'BANNED_FOLDER_NAMES_LOWER', {
             "microsoft", "nvidia corporation", "intel", "amd", "google", "mozilla",
             "common files", "internet explorer", "windows", "system32", "syswow64",
             "program files", "program files (x86)", "programdata", "drivers",
             "perflogs", "dell", "hp", "lenovo", "avast software", "avg",
             "kaspersky lab", "mcafee", "adobe", "python", "java", "oracle", "steam",
             "$recycle.bin", "config.msi", "system volume information",
             "default", "all users", "public", "vortex", "soundtrack", 
             "artbook", "extras", "dlc", "ost", "digital Content"
        })
    
    except AttributeError as e_attr:
        logging.error(f"Errore nel caricare configurazione da 'config': {e_attr}. Usando valori di default.")
        # Fornisci valori di default sicuri qui se necessario
        ignore_words = {'a', 'an', 'the', 'of', 'and'}
        common_save_extensions = {'.sav', '.save', '.dat'}
        common_save_filenames = {'save', 'user', 'profile', 'settings', 'config', 'game', 'player'}
        common_save_subdirs = ['Saves', 'Save', 'SaveGame', 'Saved', 'SaveGames']
        common_publishers = []
        BANNED_FOLDER_NAMES_LOWER = {"windows", "program files", "program files (x86)", "system32"} # Esempio minimo

    ignore_words_lower = {w.lower() for w in ignore_words}
    game_title_sig_words = [w for w in re.findall(r'\b\w+\b', sanitized_name) if w.lower() not in ignore_words_lower and len(w) > 1]
    common_save_subdirs_lower = {s.lower() for s in common_save_subdirs}

    logging.info(f"Heuristic save search for '{game_name}' (AppID: {appid})")
    logging.debug(f"Generated name abbreviations (upper): {game_abbreviations_upper}")
    logging.debug(f"Generated name abbreviations (lower): {game_abbreviations_lower}")
    logging.debug(f"Significant title words for sequence check: {game_title_sig_words}")
    logging.debug(f"Using banned folder names (lowercase): {BANNED_FOLDER_NAMES_LOWER}")


# --- Funzione Helper add_guess ---
    def add_guess(path, source_description):
        nonlocal guesses_data, checked_paths
        # Accede a: installed_steam_games_dict, appid, clean_for_comparison, THEFUZZ_AVAILABLE, fuzz, common_save_extensions, common_save_filenames (da guess_save_path e modulo/globali)
        if not path: return False
        try:
            # --- NORMALIZZA E STRIPPA IL PERCORSO ---
            try:
                # Applica normpath e POI strip() per rimuovere spazi SOLO all'inizio/fine
                norm_path = os.path.normpath(path).strip()
                if not norm_path: # Gestisce caso in cui il path diventi vuoto
                    logging.debug(f"ADD_GUESS: Path became empty after normpath/strip: '{path}'. Skipping.")
                    return False
            except Exception as e_norm_strip:
                logging.error(f"ADD_GUESS: Error during normpath/strip for path '{path}': {e_norm_strip}. Skipping.")
                return False
            # --- FINE NORMALIZZAZIONE/STRIP ---

            logging.debug(f"ADD_GUESS: Checking normalized/stripped path '{norm_path}' (Source: {source_description})")

            # Usa il path normalizzato/strippato e minuscolo come chiave
            norm_path_lower = norm_path.lower() # Applica lower() DOPO strip()

            if norm_path_lower in checked_paths:
                logging.debug(f"ADD_GUESS: Path '{norm_path}' (lower: {norm_path_lower}) already checked. Skipping.")
                return False

            checked_paths.add(norm_path_lower) # Aggiungi la chiave unica al set dei controllati

            # --- CONTROLLO ISDIR ---
            is_directory = False
            try:
                # Usa il path normalizzato e strippato per i check OS
                is_directory = os.path.isdir(norm_path)
            except OSError as e_isdir:
                # Logga solo errori OS non comuni per isdir
                if not isinstance(e_isdir, PermissionError) and getattr(e_isdir, 'winerror', 0) != 5:
                    logging.warning(f"ADD_GUESS: OSError checking isdir for '{norm_path}': {e_isdir}. Skipping entry.")
                return False # Considera errore se non possiamo fare isdir
            except Exception as e_isdir_other:
                logging.error(f"ADD_GUESS: Unexpected error checking isdir for '{norm_path}': {e_isdir_other}. Skipping entry.", exc_info=True)
                return False

            if not is_directory:
                logging.debug(f"ADD_GUESS: Path '{norm_path}' is NOT a directory. Rejecting.")
                return False
            # --- FINE CONTROLLO ISDIR ---

            # --- Filtro remotecache.vdf ---
            try:
                items = os.listdir(norm_path) # Usa path normalizzato/strippato
                if len(items) == 1 and items[0].lower() == "remotecache.vdf" and os.path.isfile(os.path.join(norm_path, items[0])):
                    logging.debug(f"ADD_GUESS: Path ignored ('{norm_path}') as it only contains remotecache.vdf.")
                    return False
            except OSError as e_list_rc:
                if not isinstance(e_list_rc, PermissionError) and getattr(e_list_rc, 'winerror', 0) != 5:
                    logging.warning(f"ADD_GUESS: OSError listing directory for remotecache check '{norm_path}': {e_list_rc}")
                # Non ritornare False qui necessariamente

            # --- Filtro root drive ---
            try:
                drive, tail = os.path.splitdrive(norm_path) # Usa path normalizzato/strippato
                if not tail or tail == os.sep:
                    logging.debug(f"ADD_GUESS: Path ignored because it is a root drive: '{norm_path}'")
                    return False
            except Exception as e_split:
                logging.warning(f"ADD_GUESS: Error during splitdrive for '{norm_path}': {e_split}")

            # <<< Controllo Corrispondenza Altri Giochi >>>
            # Usa path normalizzato/strippato per basename
            try:
                game_match_check_passed = True
                if installed_steam_games_dict and appid and THEFUZZ_AVAILABLE:
                    logging.debug(f"ADD_GUESS: Checking against other games for '{norm_path}'...")
                    path_basename = os.path.basename(norm_path)
                    cleaned_folder = clean_for_comparison(path_basename)
                    if cleaned_folder:
                        for other_appid, other_game_info in installed_steam_games_dict.items():
                            if other_appid != appid:
                                other_game_orig_name = other_game_info.get('name', '')
                                if other_game_orig_name:
                                    cleaned_other_game = clean_for_comparison(other_game_orig_name)
                                    other_set_ratio = fuzz.token_set_ratio(cleaned_other_game, cleaned_folder)
                                    logging.debug(f"ADD_GUESS: Comparing folder '{cleaned_folder}' with other game '{cleaned_other_game}' (Orig: '{other_game_orig_name}', AppID: {other_appid}). Ratio: {other_set_ratio}")
                                    if other_set_ratio > 95:
                                        logging.warning(f"ADD_GUESS: Path REJECTED: '{norm_path}' strongly matches OTHER game '{other_game_orig_name}' (AppID: {other_appid}, Ratio: {other_set_ratio}).")
                                        game_match_check_passed = False
                                        break
                        if game_match_check_passed:
                            logging.debug(f"ADD_GUESS: Check against other games PASSED for '{norm_path}'.")
                    else:
                        logging.debug(f"ADD_GUESS: Cleaned folder name for '{path_basename}' is empty, skipping other game check.")

                if not game_match_check_passed: return False
            except NameError as e_name:
                logging.error(f"ADD_GUESS: NameError during other game check (maybe clean_for_comparison not found?): {e_name}", exc_info=True)
            except Exception as e_other_game:
                logging.error(f"ADD_GUESS: Unexpected error during other game check for '{norm_path}': {e_other_game}", exc_info=True)
            # <<< FINE Controllo Altri Giochi >>>

            # --- Content Check ---
            contains_save_like_files = False
            try:
                logging.debug(f"ADD_GUESS: Starting content check for '{norm_path}'.")
                # Usa path normalizzato/strippato per listdir e join
                for item in os.listdir(norm_path):
                    item_lower = item.lower()
                    item_path = os.path.join(norm_path, item)
                    if os.path.isfile(item_path):
                        _, ext = os.path.splitext(item_lower)
                        if ext in common_save_extensions: contains_save_like_files = True; break
                        for fname_part in common_save_filenames:
                                if fname_part in item_lower: contains_save_like_files = True; break
                    if contains_save_like_files: break
                logging.debug(f"ADD_GUESS: Content check finished for '{norm_path}'. Found save-like: {contains_save_like_files}")
            except OSError as e_list:
                if not isinstance(e_list, PermissionError) and getattr(e_list, 'winerror', 0) != 5:
                        logging.warning(f"ADD_GUESS: Content check OSError in '{norm_path}': {e_list}")
            except Exception as e_content:
                logging.error(f"ADD_GUESS: Unexpected error during content check for '{norm_path}': {e_content}", exc_info=True)
            # --- FINE Content Check ---

            # --- Decisione Finale di Aggiunta ---
            # Logga e aggiunge norm_path (che è già stato normalizzato E strippato)
            log_msg_found = f"ADD_GUESS: Preparing to add path: '{norm_path}' (Source: {source_description})"
            logging.info(log_msg_found + f" [HasSavesCheck: {contains_save_like_files}]")

            # La chiave è già normalizzata/strippata/minuscola
            dict_key = norm_path_lower
            if dict_key not in guesses_data:
                # Salva il path normalizzato e strippato nel dizionario
                guesses_data[dict_key] = (norm_path, source_description, contains_save_like_files)
                logging.info(f"ADD_GUESS: Successfully ADDED path '{norm_path}'. Current total guesses: {len(guesses_data)}")
                return True
            else:
                # Questo log non dovrebbe più apparire se strip() funziona
                logging.warning(f"ADD_GUESS: Path '{norm_path}' was already in guesses_data but checked_paths logic failed?")
                return False

        except Exception as e_global:
            # Cattura qualsiasi altra eccezione imprevista all'interno di add_guess
            logging.error(f"ADD_GUESS: UNEXPECTED GLOBAL EXCEPTION checking initial path '{path}': {e_global}", exc_info=True)
            return False # Ritorna False se c'è un errore imprevisto
    # --- FINE Helper add_guess ---

    # --- Logica Cross-Platform per Common Locations ---
    system = platform.system(); user_profile = os.path.expanduser('~'); common_locations = {}
    if system == "Windows":
        appdata = os.getenv('APPDATA'); localappdata = os.getenv('LOCALAPPDATA')
        public_docs = os.path.join(os.getenv('PUBLIC', 'C:\\Users\\Public'), 'Documents')
        saved_games = os.path.join(user_profile, 'Saved Games'); documents = os.path.join(user_profile, 'Documents')
        common_locations = {
            "Saved Games": saved_games, "Documents": documents, "My Games": os.path.join(documents, 'My Games'),
            "AppData/Roaming": appdata, "AppData/Local": localappdata,
            "AppData/LocalLow": os.path.join(localappdata, '..', 'LocalLow') if localappdata else None,
            "Public Documents": public_docs,
        }
        programdata = os.getenv('ProgramData');
        if programdata: common_locations["ProgramData"] = programdata
    # Aggiungere qui la logica per Linux/macOS se necessario
    elif system == "Linux": pass # TODO: Implement Linux paths
    elif system == "Darwin": pass # TODO: Implement macOS paths
    else: common_locations = {"Home": user_profile}

    # Filtra solo percorsi validi e directory esistenti
    valid_locations = {}
    for name, path in common_locations.items():
        if path:
            try:
                # Normalizza e controlla esistenza senza generare eccezioni su Windows per nomi lunghi
                norm_path = os.path.normpath(path)
                if os.path.isdir(norm_path):
                     valid_locations[name] = norm_path
            except (OSError, TypeError, ValueError) as e_path:
                logging.warning(f"Could not validate common location '{name}' path '{path}': {e_path}") # <-- Riga corretta

    logging.info(f"Valid common locations to search ({system}): {list(valid_locations.keys())}")
    logging.debug(f"Valid common location paths: {list(valid_locations.values())}")
    # --- FINE Logica Cross-Platform ---

    # --- Steam Userdata Check ---
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        logging.info(f"Checking Steam Userdata for AppID {appid} (User: {steam_id3_to_use})...")
        # Usa try-except perché os.path.join può fallire con input non validi
        try:
            user_data_folder_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
            if os.path.isdir(user_data_folder_for_id):
                base_userdata_appid = os.path.join(user_data_folder_for_id, appid)
                remote_path = os.path.join(base_userdata_appid, 'remote')
                # Chiama add_guess che gestisce controlli isdir ed errori interni
                if add_guess(remote_path, f"Steam Userdata/{steam_id3_to_use}/{appid}/remote"):
                    try: # Scansiona sottocartelle di remote
                        for entry in os.listdir(remote_path):
                            sub_path = os.path.join(remote_path, entry); sub_lower = entry.lower()
                            # Aggiungi check isdir qui per evitare chiamate inutili a are_names_similar
                            if os.path.isdir(sub_path) and (
                                sub_lower in common_save_subdirs_lower or
                                any(s in sub_lower for s in ['save', 'profile', 'user', 'slot']) or
                                are_names_similar(sanitized_name, entry, game_title_words_for_seq=game_title_sig_words) or
                                entry.upper() in [a.upper() for a in game_abbreviations] ):
                                    add_guess(sub_path, f"Steam Userdata/.../remote/{entry}")
                    except Exception as e_remote_sub:
                         if not isinstance(e_remote_sub, FileNotFoundError): # Non loggare se remote non esiste
                              logging.warning(f"Error scanning subfolders in remote path '{remote_path}': {e_remote_sub}")
                # Aggiungi base solo se non contiene solo remotecache (il check è in add_guess)
                add_guess(base_userdata_appid, f"Steam Userdata/{steam_id3_to_use}/{appid}/Base")
            else:
                 logging.warning(f"Steam user ID folder not found or invalid: '{user_data_folder_for_id}'")
        except TypeError as e_join:
             logging.error(f"Error constructing Steam userdata path (invalid input?): {e_join}")
    # --- FINE Steam Userdata Check ---

    # --- Generic Heuristic Search ---
    # >> Direct Path Checks
    logging.info("Performing direct path checks...")
    for loc_name, base_folder in valid_locations.items():
        for variation in game_abbreviations:
            if not variation: continue
            try:
                direct_path = os.path.join(base_folder, variation)
                add_guess(direct_path, f"{loc_name}/Direct/{variation}")
                for publisher in common_publishers:
                     try: # Proteggi join con publisher
                          pub_path = os.path.join(base_folder, publisher, variation)
                          add_guess(pub_path, f"{loc_name}/{publisher}/Direct/{variation}")
                     except (TypeError, ValueError): pass # Ignora publisher non validi
                # Check <Location>/<Variation>/<CommonSaveSubdir> solo se direct_path è valido
                if os.path.isdir(direct_path):
                    for save_subdir in common_save_subdirs:
                        try: # Proteggi join con save_subdir
                             sub_dir_path = os.path.join(direct_path, save_subdir)
                             add_guess(sub_dir_path, f"{loc_name}/Direct/{variation}/{save_subdir}")
                        except (TypeError, ValueError): pass # Ignora subdir non validi
            except (TypeError, ValueError) as e_join_direct:
                 logging.warning(f"Error constructing direct path with variation '{variation}' in '{base_folder}': {e_join_direct}")


    # >> Exploratory Search
    logging.info("Performing exploratory search (iterating folders)...")
    for loc_name, base_folder in valid_locations.items():
        logging.debug(f"Exploring in '{loc_name}' ({base_folder})...")
        try:
            for lvl1_folder_name in os.listdir(base_folder):
                lvl1_folder_name_lower = lvl1_folder_name.lower()
                if lvl1_folder_name.lower() in BANNED_FOLDER_NAMES_LOWER: continue
                try:
                     lvl1_path = os.path.join(base_folder, lvl1_folder_name)
                     if not os.path.isdir(lvl1_path): continue
                except (OSError, TypeError, ValueError): continue # Salta elementi non validi/accessibili

                # <<< Determina se la cartella Lvl1 è potenzialmente correlata al gioco target >>>
                # Controlla se è un publisher noto O se il nome è simile al gioco target
                is_lvl1_publisher = lvl1_folder_name_lower in common_publishers_set # Check contro il set (case-insensitive)
                is_lvl1_related_to_target = is_lvl1_publisher or \
                                            (are_names_similar(sanitized_name, lvl1_folder_name, game_title_words_for_seq=game_title_sig_words))
                
                lvl1_name_upper = lvl1_folder_name.upper()
                is_lvl1_match = lvl1_name_upper in game_abbreviations_upper or \
                                    are_names_similar(sanitized_name, lvl1_folder_name, game_title_words_for_seq=game_title_sig_words, min_match_words=2, fuzzy_threshold=85)

                if is_lvl1_match:
                    logging.debug(f"  Match found at Lvl1: '{lvl1_folder_name}'")
                    if add_guess(lvl1_path, f"{loc_name}/GameNameLvl1/{lvl1_folder_name}"):
                        try:
                            for save_subdir in os.listdir(lvl1_path):
                                try: # Controlla validità subdir
                                     subdir_path = os.path.join(lvl1_path, save_subdir)
                                     if save_subdir.lower() in common_save_subdirs_lower and os.path.isdir(subdir_path):
                                         add_guess(subdir_path, f"{loc_name}/GameNameLvl1/{lvl1_folder_name}/{save_subdir}")
                                except (OSError, TypeError, ValueError): continue
                        except OSError: pass # Ignora errori lettura subdirs Lvl1

                # Check Lvl2
                try: # try esterno per gestire errori lettura contenuto lvl1_path
                    for lvl2_folder_name in os.listdir(lvl1_path):
                        try: # try interno per gestire errori su singola cartella lvl2
                            lvl2_path = os.path.join(lvl1_path, lvl2_folder_name)
                            if not os.path.isdir(lvl2_path): continue # Salta se non è una cartella

                            lvl2_name_lower = lvl2_folder_name.lower()
                            lvl2_name_upper = lvl2_folder_name.upper()

                            # <<< INIZIO LOGICA DI MATCH LVL2 >>>
                            is_lvl2_similar_name = are_names_similar(sanitized_name, lvl2_folder_name, game_title_words_for_seq=game_title_sig_words)
                            is_lvl2_abbreviation = lvl2_name_upper in game_abbreviations_upper
                            is_lvl2_match = False
                            log_reason = ""
                            if is_lvl1_related_to_target:
                                is_lvl2_match = is_lvl2_similar_name or is_lvl2_abbreviation
                                log_reason = f"(Parent Related: {is_lvl1_related_to_target}, NameSimilar: {is_lvl2_similar_name}, IsAbbr: {is_lvl2_abbreviation})"
                            else:
                                is_lvl2_match = is_lvl2_similar_name
                                log_reason = f"(Parent UNrelated: {is_lvl1_related_to_target}, NameSimilar: {is_lvl2_similar_name})"
                            # <<< FINE LOGICA DI MATCH LVL2 >>>

                            if is_lvl2_match:
                                logging.debug(f"    Match found at Lvl2: '{lvl2_folder_name}' in '{lvl1_folder_name}' {log_reason}")
                                if add_guess(lvl2_path, f"{loc_name}/{lvl1_folder_name}/GameNameLvl2/{lvl2_folder_name}"):
                                    try:
                                        for save_subdir_lvl3 in os.listdir(lvl2_path):
                                            try:
                                                if save_subdir_lvl3.lower() in common_save_subdirs_lower:
                                                    subdir_path_lvl3 = os.path.join(lvl2_path, save_subdir_lvl3)
                                                    if os.path.isdir(subdir_path_lvl3):
                                                        add_guess(subdir_path_lvl3, f"{loc_name}/.../GameNameLvl2/{lvl2_folder_name}/{save_subdir_lvl3}")
                                            except (OSError, TypeError, ValueError): continue
                                    except OSError: pass

                            elif lvl2_name_lower in common_save_subdirs_lower and \
                                (is_lvl1_publisher or is_lvl1_match or are_names_similar(sanitized_name, lvl1_folder_name, min_match_words=1)):
                                    logging.debug(f"    Match found at Lvl2 (Save Subdir): '{lvl2_folder_name}' in '{lvl1_folder_name}' (Parent relevant)")
                                    if add_guess(lvl2_path, f"{loc_name}/{lvl1_folder_name}/SaveSubdirLvl2/{lvl2_folder_name}"):
                                        # Check Lvl3
                                        try:
                                            for lvl3_folder_name in os.listdir(lvl2_path):
                                                 try:
                                                      if lvl3_folder_name.lower() in common_save_subdirs_lower:
                                                          lvl3_path = os.path.join(lvl2_path, lvl3_folder_name)
                                                          if os.path.isdir(lvl3_path):
                                                              logging.debug(f"      Found common save subdir at Lvl3: '{lvl3_folder_name}'")
                                                              add_guess(lvl3_path, f"{loc_name}/{lvl1_folder_name}/{lvl2_folder_name}/SaveSubdirLvl3/{lvl3_folder_name}")
                                                 except (OSError, TypeError, ValueError): continue
                                        except OSError: pass

                        except (OSError, TypeError, ValueError) as e_lvl2_item:
                            continue # Passa al prossimo elemento in lvl1_path

                except OSError as e_lvl1_list: # Errore durante la lettura del contenuto di lvl1_path
                    if not isinstance(e_lvl1_list, PermissionError) and getattr(e_lvl1_list, 'winerror', 0) != 5:
                        logging.warning(f"  Could not read inside '{lvl1_path}': {e_lvl1_list}")
                # --- Fine del Blocco Check Lvl2 
        except OSError as e_base:
            if not isinstance(e_base, PermissionError) and getattr(e_base, 'winerror', 0) != 5: logging.warning(f"Error accessing subfolders in '{base_folder}': {e_base}")
    # --- FINE Exploratory Search ---

    # --- Search Inside Install Dir ---
    if game_install_dir and os.path.isdir(game_install_dir):
        logging.info(f"Checking common subfolders INSIDE (max depth 3) '{game_install_dir}'...")
        max_depth = 3
        install_dir_depth = 0 # Default
        try:
             install_dir_depth = game_install_dir.rstrip(os.sep).count(os.sep)
        except Exception as e_depth:
             logging.warning(f"Could not calculate install dir depth: {e_depth}")

        try:
            for root, dirs, files in os.walk(game_install_dir, topdown=True, onerror=lambda err: logging.warning(f"Error during install dir walk: {err}")):
                logging.debug(f"  [DEBUG WALK] Entering root: {root}")
                current_relative_depth = 0 # Default
                try:
                    current_depth = root.rstrip(os.sep).count(os.sep)
                    current_relative_depth = current_depth - install_dir_depth
                except Exception as e_reldepth:
                     logging.warning(f"Could not calculate relative depth for {root}: {e_reldepth}")

                if current_relative_depth >= max_depth: dirs[:] = []; continue

                dirs[:] = [d for d in dirs if d.lower() not in BANNED_FOLDER_NAMES_LOWER]

                for dir_name in list(dirs):
                    potential_path = None # Inizializza per sicurezza
                    relative_log_path = dir_name # Inizializza fallback
                    is_dir_actual = False # Inizializza il risultato del VERO check isdir

                    # 1. Calcola path e verifica se è una directory in modo sicuro
                    try:
                        potential_path = os.path.join(root, dir_name)
                        # Il check isdir è fondamentale, fallo qui dentro il try
                        is_dir_actual = os.path.isdir(potential_path)
                        # Calcola relpath solo se potential_path è valido
                        relative_log_path = os.path.relpath(potential_path, game_install_dir)

                    except (ValueError, TypeError, OSError) as e_path_or_dir:
                        # Se c'è un errore nel creare il path o nel fare isdir, logga e salta
                        logging.debug(f"    [DEBUG WALK] Error calculating path or checking isdir for dir='{dir_name}' in root='{root}': {e_path_or_dir}")
                        continue # Salta al prossimo dir_name nel ciclo

                    # 2. Log di Debug (Usa il risultato 'is_dir_actual' appena calcolato)
                    # --- BLOCCO DEBUG ---
                    logging.debug(f"    [DEBUG WALK] Analyzing: root='{root}', dir='{dir_name}', IsDir={is_dir_actual}")
                    if is_dir_actual: # Logga dettagli solo se è una directory valida
                        temp_dir_name_lower = dir_name.lower()
                        temp_dir_name_upper = dir_name.upper()
                        is_common_subdir_debug = temp_dir_name_lower in common_save_subdirs_lower
                        is_game_match_debug = temp_dir_name_upper in game_abbreviations_upper or \
                                            are_names_similar(sanitized_name, dir_name, game_title_words_for_seq=game_title_sig_words, fuzzy_threshold=85)
                        logging.debug(f"      [DEBUG WALK] -> Check results: is_common_subdir={is_common_subdir_debug}, is_game_match={is_game_match_debug}")
                    # --- FINE BLOCCO DEBUG ---

                    # 3. Logica Principale (Usa il risultato 'is_dir_actual')
                    if is_dir_actual:
                        # Calcola versioni lower/upper solo se è una directory
                        dir_name_lower = dir_name.lower()
                        dir_name_upper = dir_name.upper()

                        logging.debug(f"        [DEBUG WALK] Evaluating conditions for dir='{dir_name}'...") # Log Pre-Check

                        # Controlla se è una common save subdir o un game match
                        if dir_name_lower in common_save_subdirs_lower:
                            logging.debug(f"          [DEBUG WALK] Match Common! -> Calling add_guess for {potential_path}") # Log Pre-Add
                            add_guess(potential_path, f"InstallDirWalk/SaveSubdir/{relative_log_path}")
                        elif dir_name_upper in game_abbreviations_upper or \
                            are_names_similar(sanitized_name, dir_name, game_title_words_for_seq=game_title_sig_words, fuzzy_threshold=85):
                                logging.debug(f"          [DEBUG WALK] Match GameName/Abbr! -> Calling add_guess for {potential_path}") # Log Pre-Add
                                add_guess(potential_path, f"InstallDirWalk/GameMatch/{relative_log_path}")

        except Exception as e_walk:
            logging.error(f"Unexpected error during os.walk in '{game_install_dir}': {e_walk}")
    # --- FINE Search Inside Install Dir ---


    # --- ############################################################### ---
    # --- Ordinamento Finale usando la funzione esterna final_sort_key    ---
    # --- ############################################################### ---
    logging.info("Finalizing and sorting potential paths with scores...")
    final_results_with_scores = []
    try:
        guesses_list = list(guesses_data.values())

        # 1. Crea il dizionario con i dati necessari a final_sort_key
        outer_scope_data_for_sort = {
             'game_name': game_name,
             #'appid': appid,
             'installed_steam_games_dict': installed_steam_games_dict,
             'common_save_subdirs_lower': common_save_subdirs_lower,
             'game_abbreviations': game_abbreviations, # old
             'game_abbreviations_lower': game_abbreviations_lower, 
             'game_title_sig_words': game_title_sig_words,
             'steam_userdata_path': steam_userdata_path,
             'clean_func': clean_for_comparison
        }

        # 2. Usa una lambda per chiamare final_sort_key (definita esternamente)
        #    con entrambi gli argomenti
        sorted_guesses_list = sorted(guesses_list,
                                     key=lambda tpl: final_sort_key(tpl, outer_scope_data_for_sort))

        # Estrai percorso e ricalcola punteggio per il risultato finale
        for item_tuple in sorted_guesses_list:
            original_path = item_tuple[0]
            try:
                # Ricalcola il punteggio positivo usando la chiave negata e passando i dati
                score = -final_sort_key(item_tuple, outer_scope_data_for_sort)[0]
                final_results_with_scores.append((original_path, score))
            except Exception as e_score_calc:
                logging.warning(f"Could not calculate score for path '{original_path}' during final list creation: {e_score_calc}", exc_info=True) # Aggiunto exc_info
                final_results_with_scores.append((original_path, -9999))

        logging.info(f"Search finished. Found {len(final_results_with_scores)} unique paths with scores.")
        if final_results_with_scores:
             logging.debug(f"Paths found (sorted by likelihood):")
             for i, (p, s) in enumerate(final_results_with_scores):
                 orig_data_tuple = guesses_data.get(p.lower())
                 source_info = f"(Source: {orig_data_tuple[1]}, HasSaves: {orig_data_tuple[2]})" if orig_data_tuple else "(Data not found?)"
                 logging.debug(f"  {i+1}. Score: {s} | Path: '{p}' {source_info}")

    except Exception as e_final:
        logging.error(f"Error during final sorting/processing of paths with scores: {e_final}", exc_info=True)
        final_results_with_scores = []

    # Restituisce la lista di tuple (path, score)
    return final_results_with_scores

# <<< Funzione di pulizia per confronto >>>
def clean_for_comparison(name):
    """
    Pulisce un nome per confronti più dettagliati, mantenendo numeri e spazi.
    Rimuove simboli comuni e normalizza i separatori.
    """
    if not isinstance(name, str): # Gestisce input non stringa
        return ""
    # Rimuove simboli ™®©:, ma mantiene numeri, spazi, trattini
    name = re.sub(r'[™®©:]', '', name)
    # Sostituisci trattini/underscore con spazi per normalizzare i separatori
    name = re.sub(r'[-_]', ' ', name)
    # Rimuovi spazi multipli e trim
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()
    
    # <<< Funzione di ordinamento potenziata per dare priorità a match più precisi con il nome originale >>>

# <<< Funzione di ordinamento finale >>>
def final_sort_key(guess_tuple, outer_scope_data):
    """
    Assegna un punteggio a una tupla (path, source, contains_saves) trovata da guess_save_path.
    Punteggi più alti = più probabile. Include logica per match più precisi e cap per userdata.
    """
    # --- Estrai dati dalla tupla e dallo scope esterno ---
    path, source, contains_saves = guess_tuple
    game_name = outer_scope_data.get('game_name', "")
    #appid = outer_scope_data.get('appid', None)
    common_save_subdirs_lower = outer_scope_data.get('common_save_subdirs_lower', set()) # Recupera sottocartelle comuni
    #game_abbreviations = outer_scope_data.get('game_abbreviations', []) # Recupera abbreviazioni
    game_title_sig_words = outer_scope_data.get('game_title_sig_words', []) # Recupera parole significative
    steam_userdata_path = outer_scope_data.get('steam_userdata_path', None) # Recupera userdata path
    clean_func = outer_scope_data.get('clean_func', lambda x: x.lower()) # Recupera funzione pulizia
    game_abbreviations_lower = outer_scope_data.get('game_abbreviations_lower', set())
    global THEFUZZ_AVAILABLE # Usa globale per thefuzz

    score = 0
    path_lower = path.lower()
    basename = os.path.basename(path) # Calcola basename dall'originale path una volta
    basename_lower = basename.lower() # Deriva la versione minuscola da esso
    source_lower = source.lower()
    parent_dir_lower = os.path.dirname(path_lower)
    parent_basename_lower = os.path.basename(parent_dir_lower)

    # --- Identifica Tipi Speciali di Percorso ---
    is_steam_remote = steam_userdata_path and 'steam userdata' in source_lower and '/remote' in source_lower
    is_steam_base = steam_userdata_path and 'steam userdata' in source_lower and source_lower.endswith('/base')
    prime_locations_parents = []
    try:
         user_profile = os.path.expanduser('~')
         prime_locations_parents = [
             os.path.normpath(os.path.join(user_profile, 'Saved Games')).lower(),
             os.path.normpath(os.getenv('APPDATA', '')).lower(),
             os.path.normpath(os.getenv('LOCALAPPDATA', '')).lower(),
             os.path.normpath(os.path.join(os.getenv('LOCALAPPDATA', ''), '..', 'LocalLow')).lower() if os.getenv('LOCALAPPDATA') else None,
             os.path.normpath(os.path.join(user_profile, 'Documents', 'My Games')).lower(),
         ]
         prime_locations_parents = [loc for loc in prime_locations_parents if loc and os.path.isdir(loc)]
    except Exception as e_prime:
         logging.warning(f"Errore nel determinare prime locations in final_sort_key: {e_prime}")
    is_in_prime_user_location = any(path_lower.startswith(loc + os.sep) for loc in prime_locations_parents) and not (is_steam_remote or is_steam_base)
    is_install_dir_walk = 'installdirwalk' in source_lower

    # --- ASSEGNA PUNTEGGIO BASE PER LOCAZIONE ---
    if is_steam_remote:            score += 1500
    elif is_steam_base:            score += 150; score += 500 if contains_saves else 0 # Spostato bonus qui
    elif is_in_prime_user_location:score += 1000
    elif 'documents' in path_lower and 'my games' not in path_lower: score += 300
    elif is_install_dir_walk:      score -= 500
    else:                          score += 100

    # --- BONUS INDICATORI POSITIVI ---
    if contains_saves and not is_steam_base: score += 600 # Bonus saves per NON steam_base
    is_common_save_subdir_basename = basename_lower in common_save_subdirs_lower
    if is_common_save_subdir_basename: score += 350
    is_direct_abbr_match = basename_lower in game_abbreviations_lower
    is_sequence_match = matches_initial_sequence(basename, game_title_sig_words)
    is_direct_source = 'direct' in source_lower or 'gamenamelvl' in source_lower
    if is_direct_abbr_match or is_sequence_match or is_direct_source: score += 100 # Bonus ridotto mantenuto
    parent_basename_lower = os.path.basename(parent_dir_lower)
    if is_common_save_subdir_basename and parent_basename_lower in game_abbreviations_lower: score += 100

    # --- BONUS SIMILARITA' NOME ---
    # (Logica per exact_match_bonus e fuzzy_set_bonus)
    cleaned_folder = clean_func(basename_lower)
    cleaned_original_game = clean_func(game_name)
    exact_match_bonus = 0; fuzzy_set_bonus = 0
    if cleaned_original_game and cleaned_folder:
        if cleaned_folder == cleaned_original_game: exact_match_bonus = 400
        elif THEFUZZ_AVAILABLE:
            set_ratio = fuzz.token_set_ratio(cleaned_original_game, cleaned_folder)
            if set_ratio > 85: fuzzy_set_bonus = int(((set_ratio - 85) / 15) * 300)
    score += exact_match_bonus + fuzzy_set_bonus

    # --- MALUS SPECIFICI ---
    if basename_lower in ['data', 'settings', 'config', 'cache', 'logs'] and not contains_saves and not is_in_prime_user_location and not is_steam_remote: score -= 150
    if len(basename_lower) <= 3 and not is_common_save_subdir_basename and not contains_saves: score -= 30
    if is_install_dir_walk and (not contains_saves or not is_common_save_subdir_basename): score -= 300

    # <<< CAP PER USERDATA >>>
    # Applica un limite massimo al punteggio se il percorso è dentro steam userdata
    MAX_USERDATA_SCORE = 1100 # Imposta il cap (puoi aggiustarlo, es. 1000, 1100, 1200)
    # Controlla se steam_userdata_path esiste ed è una stringa valida
    if steam_userdata_path and isinstance(steam_userdata_path, str):
        try:
            # Normalizza il percorso base di userdata per un confronto sicuro
            norm_userdata_base = os.path.normpath(steam_userdata_path).lower()
            # Controlla se il percorso del guess inizia con il percorso base di userdata
            if path_lower.startswith(norm_userdata_base + os.sep):
                if score > MAX_USERDATA_SCORE:
                    logging.debug(f"  -> Capping userdata path score for '{path}' from {score} to {MAX_USERDATA_SCORE}")
                    score = MAX_USERDATA_SCORE
        except Exception as e_cap:
            # Logga eventuali errori durante il check del cap ma non bloccare
            logging.warning(f"Error applying userdata score cap for path '{path}': {e_cap}")
    # <<< FINE CAP PER USERDATA >>>

    # Restituisci la chiave di ordinamento (punteggio negativo per ordine decrescente)
    return (-score, path_lower)

# --- Funzione per eliminare un file di backup ---
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

# --- Funzione per calcolare la dimensione di una cartella ---
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
 
def get_display_name_from_backup_filename(filename):
    """
    Rimuove il suffisso timestamp (_YYYYMMDD_HHMMSS) da un nome file di backup
    per una visualizzazione più pulita.

    Es: "Backup_ProfiloX_20250422_030000.zip" -> "Backup_ProfiloX"
    """
    if isinstance(filename, str) and filename.endswith(".zip"):
        # Tenta di rimuovere il pattern specifico _8cifre_6cifre.zip
        # Usiamo re.sub per sostituire il pattern con '' (stringa vuota)
        # Il pattern: _ seguita da 8 cifre (\d{8}), _ seguita da 6 cifre (\d{6}), seguito da .zip alla fine ($)
        display_name = re.sub(r'_\d{8}_\d{6}\.zip$', '.zip', filename)
        # Se la sostituzione ha funzionato, rimuoviamo anche l'estensione .zip finale per la visualizzazione
        if display_name != filename: # Verifica se la sostituzione è avvenuta
             return display_name[:-4] # Rimuovi ".zip"
        else:
             # Se il pattern non corrisponde, restituisci il nome senza estensione come fallback
             logging.warning(f"Timestamp pattern not found in backup filename: {filename}")
             return filename[:-4] if filename.endswith('.zip') else filename
    return filename # Restituisci l'input originale se non è una stringa o non finisce per .zip