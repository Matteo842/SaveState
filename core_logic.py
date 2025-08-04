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

# Import the appropriate guess_save_path function based on platform
if platform.system() == "Linux":
    from save_path_finder_linux import guess_save_path
    logging.info("core_logic: Using Linux-specific implementation of guess_save_path")
else:
    from save_path_finder import guess_save_path
    logging.info(f"core_logic: Using default implementation of guess_save_path for {platform.system()}")

try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Library 'thefuzz' found and loaded.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    # Log the warning only once here at startup if missing
    logging.warning("Library 'thefuzz' not found. Fuzzy matching will be disabled.")
    logging.warning("Install it with: pip install thefuzz[speedup]")

# --- Define profiles file path ---
PROFILES_FILENAME = "game_save_profiles.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Get base folder
if APP_DATA_FOLDER: # Check if valid
    PROFILES_FILE_PATH = os.path.join(APP_DATA_FOLDER, PROFILES_FILENAME)
else:
    # Fallback
    logging.error("Unable to determine APP_DATA_FOLDER, using relative path for game_save_profiles.json.")
    PROFILES_FILE_PATH = os.path.abspath(PROFILES_FILENAME)
logging.info(f"Profile file path in use: {PROFILES_FILE_PATH}")
# --- End definition ---

# <<< Function to sanitize folder names >>>
def sanitize_foldername(name):
    """Removes or replaces invalid characters for file/folder names,
       preserving internal dots and removing external ones."""
    if not isinstance(name, str):
        return "_invalid_profile_name_" # Handle non-string input

    # 1. Remove universally invalid characters in file/folder names
    #    ( <>:"/\|?* ) Keep letters, numbers, spaces, _, -, .
    #    We use a regular expression for this.
    safe_name = re.sub(r'[<>:"/\\|?*]', '', name)

    # 2. Remove initial/final whitespace
    safe_name = safe_name.strip()

    # 3. Remove initial/final DOTS (AFTER removing spaces)
    #    This loop removes multiple dots if present (e.g., "..name..")
    if safe_name: # Avoid errors if the string has become empty
        safe_name = safe_name.strip('.')

    # 4. Remove any whitespace that might have been exposed
    #    after removing dots (e.g., ". name .")
    safe_name = safe_name.strip()

    # 5. Handle case where name becomes empty or just spaces after cleaning
    if not safe_name or safe_name.isspace():
        safe_name = "_invalid_profile_name_" # Fallback name

    return safe_name

# --- Profile Management ---

# <<< Function to get profile backup summary >>>
def get_profile_backup_summary(profile_name, backup_base_dir):
    """
    Returns a summary of backups for a profile.
    Returns: tuple (count: int, last_backup_datetime: datetime | None)
    """
    # Use the existing function that already sorts by date (newest first)
    backups = list_available_backups(profile_name, backup_base_dir) # Pass the argument
    count = len(backups)
    last_backup_dt = None

    if count > 0:
        most_recent_backup_path = backups[0][1] # Index 1 is the full path
        try:
            mtime_timestamp = os.path.getmtime(most_recent_backup_path)
            last_backup_dt = datetime.fromtimestamp(mtime_timestamp)
        except FileNotFoundError:
            logging.error(f"Last backup file not found ({most_recent_backup_path}) during getmtime for {profile_name}.")
        except Exception as e:
            logging.error(f"Unable to get last backup date for {profile_name} by '{most_recent_backup_path}': {e}")
    return count, last_backup_dt

# Loads profiles from the profile file, ensuring they are valid
def load_profiles():
    """
    Loads profiles from PROFILES_FILE_PATH, ensuring that values are
    dictionaries containing at least the 'path' key.
    """
    profiles_data = {} # Inizializza vuoto
    # Prima prova a caricare il contenuto grezzo del file JSON
    if os.path.exists(PROFILES_FILE_PATH):
        try:
            with open(PROFILES_FILE_PATH, 'r', encoding='utf-8') as f:
                profiles_data = json.load(f)
            logging.debug(f"File '{PROFILES_FILE_PATH}' caricato.")
        except json.JSONDecodeError:
            logging.warning(f"File profili '{PROFILES_FILE_PATH}' corrotto o vuoto. Sarà sovrascritto al prossimo salvataggio.")
            profiles_data = {} # Tratta come vuoto se corrotto
        except Exception as e:
            logging.error(f"Errore imprevisto durante la lettura iniziale di '{PROFILES_FILE_PATH}': {e}")
            profiles_data = {} # Tratta come vuoto per altri errori

    # Ora processa i dati caricati (profiles_data)
    loaded_profiles = {} # Dizionario per i profili processati e validati
    profiles_dict_source = {} # Dizionario sorgente da cui leggere i profili effettivi

    try:
        if isinstance(profiles_data, dict):
            # Controlla se è il nuovo formato con metadati o il vecchio formato
            if "__metadata__" in profiles_data and "profiles" in profiles_data:
                profiles_dict_source = profiles_data.get("profiles", {}) # Nuovo formato
                logging.debug("Processing profiles from new format (with metadata).")
            elif "__metadata__" not in profiles_data:
                # Se non ci sono metadati, assumi sia il vecchio formato (dict nome->path)
                profiles_dict_source = profiles_data
                logging.debug("Processing profiles assuming old format (name -> path string).")
            else:
                # Formato con metadata ma senza chiave 'profiles'? Strano.
                logging.warning("Profile file has '__metadata__' but missing 'profiles' key. Treating as empty.")
                profiles_dict_source = {}

            # --- Ciclo di Conversione e Validazione ---
            for name, path_or_data in profiles_dict_source.items():
                if isinstance(path_or_data, str):
                    # Vecchio formato: converti in dizionario base
                    logging.debug(f"Converting old format profile '{name}' to dict.")
                    # Verifica validità percorso prima di aggiungere
                    if os.path.isdir(path_or_data): # Controlla se il percorso è valido
                        loaded_profiles[name] = {'path': path_or_data}
                    else:
                        logging.warning(f"Path '{path_or_data}' for profile '{name}' (old format) is invalid. Skipping.")
                elif isinstance(path_or_data, dict):
                    # Nuovo formato o già convertito: assicurati che 'path' esista e sia valido
                    paths_key_present = 'paths' in path_or_data and isinstance(path_or_data['paths'], list) and path_or_data['paths']
                    path_key_present = 'path' in path_or_data and isinstance(path_or_data['path'], str) and path_or_data['path']

                    if paths_key_present:
                        # Validazione 'paths': Controlla che *almeno uno* dei percorsi sia una stringa valida (non necessariamente esistente qui)
                        # La validazione dell'esistenza avverrà dopo, al momento del backup.
                        if any(isinstance(p, str) and p for p in path_or_data['paths']):
                            loaded_profiles[name] = path_or_data.copy()
                            logging.debug(f"Profile '{name}' validated with 'paths' key.")
                        else:
                            logging.warning(f"Profile '{name}' has 'paths' key, but the list is empty or contains invalid entries. Skipping.")
                    elif path_key_present:
                        # Validazione 'path': Controlla che sia una stringa valida (non necessariamente esistente qui)
                        # La validazione dell'esistenza avverrà dopo.
                        if os.path.basename(path_or_data['path']): # Controllo base che non sia solo \ o / o vuota
                             loaded_profiles[name] = path_or_data.copy()
                             logging.debug(f"Profile '{name}' validated with 'path' key.")
                        else:
                             logging.warning(f"Profile '{name}' has 'path' key, but the path string '{path_or_data['path']}' seems invalid. Skipping.")
                    else:
                        # Nessuna chiave valida trovata
                        logging.warning(f"Profile '{name}' is a dict but missing a valid 'paths' (list) or 'path' (string) key. Skipping.")
                else:
                    # Formato imprevisto per questo profilo
                    logging.warning(f"Unrecognized profile format for '{name}'. Skipping.")
                    continue # Salta questo profilo problematico

        else:
            # Il file JSON non conteneva un dizionario principale
            logging.error(f"Profile file '{PROFILES_FILE_PATH}' content is not a valid JSON dictionary.")
            loaded_profiles = {}

    except Exception as e:
        # Cattura errori durante l'elaborazione del dizionario caricato
        logging.error(f"Error processing loaded profile data: {e}", exc_info=True)
        loaded_profiles = {} # Reset in caso di errore nell'elaborazione

    logging.info(f"Loaded and processed {len(loaded_profiles)} profiles from '{PROFILES_FILE_PATH}'.")
    return loaded_profiles # Restituisci i profili processati

# Saves the profiles to the profile file
def save_profiles(profiles):
    """ 
    Save profiles in PROFILES_FILE_PATH. 
    """
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

# --- Function to add a profile ---
def delete_profile(profiles, profile_name):
    """Deletes a profile from the dictionary. Returns True if deleted, False otherwise."""
    if profile_name in profiles:
        del profiles[profile_name]
        logging.info(f"Profile '{profile_name}' removed from memory.")
        return True
    else:
        logging.warning(f"Attempt to delete non-existing profile: '{profile_name}'.")
        return False

# --- Backup/Restore Operations ---
def manage_backups(profile_name, backup_base_dir, max_backups):
    """Delete older .zip backups if they exceed the specified limit."""
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
                logging.info(f"  Deleting: {backup_files[i]}")
                os.remove(file_to_delete)
                deleted_files.append(backup_files[i])
                deleted_count += 1
            except Exception as e:
                logging.error(f"  Error deleting {backup_files[i]}: {e}")
        logging.info(f"Deleted {deleted_count} outdated (.zip) backups.")

    except Exception as e:
        logging.error(f"Error managing outdated (.zip) backups for '{profile_name}': {e}")
    return deleted_files

# --- Backup Function ---
def perform_backup(profile_name, source_paths, backup_base_dir, max_backups, max_source_size_mb, compression_mode="standard"):
    """
    Esegue il backup usando zipfile. Gestisce un singolo percorso (str) o percorsi multipli (list).
    Restituisce (bool successo, str messaggio).
    """
    # Import necessari localmente se non sono globali nel modulo
    import zipfile
    # import shutil - non serve qui
    logging.info(f"Starting perform_backup for: '{profile_name}'")
    sanitized_folder_name = sanitize_foldername(profile_name)
    profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
    logging.info(f"Original Name: '{profile_name}', Sanitized Folder Name: '{sanitized_folder_name}'")
    logging.debug(f"Backup path built: '{profile_backup_dir}'")

    is_multiple_paths = isinstance(source_paths, list)
    # Normalizza tutti i percorsi subito
    paths_to_process = [os.path.normpath(p) for p in (source_paths if is_multiple_paths else [source_paths])]
    logging.debug(f"Paths to process after normalization: {paths_to_process}")

    # --- Validazione Percorsi Sorgente --- 
    invalid_paths = []
    paths_ok = True

    logging.info("Starting path validation")
    for i, path in enumerate(paths_to_process):
        try:
            # Specific checks
            exists = os.path.exists(path)
            if not exists:
                paths_ok = False
                invalid_paths.append(path)
                logging.warning(f"Path does not exist: '{path}'")
        except OSError as e_os:
            error_msg = f"OSError: {e_os}"
            paths_ok = False
            invalid_paths.append(f"{path} (Error: {error_msg})")
            logging.error(f"OS error checking path '{path}': {e_os}")
        except Exception as e_val:
            error_msg = f"Exception: {type(e_val).__name__} - {e_val}"
            paths_ok = False
            invalid_paths.append(f"{path} (Error: {error_msg})")
            logging.error(f"General error checking path '{path}': {e_val}")

    if not paths_ok:
        # Build a clear error message for the user
        error_details = "\n".join(invalid_paths)
        error_message_for_ui = f"One or more source paths do not exist or caused errors:\n{error_details}"
        logging.error(f"Backup error '{profile_name}': {error_message_for_ui}")
        return False, error_message_for_ui # Return the detailed message
    
    logging.info("Path validation successful - All paths OK")
    # --- End Validation --- No additional file/directory checks here ---

 
     # --- Source Size Check ---
    logging.info(f"Checking source size for {len(paths_to_process)} path(s) (Limit: {'None' if max_source_size_mb == -1 else str(max_source_size_mb) + ' MB'})...")
    total_size_bytes = 0
    if max_source_size_mb != -1:
        max_source_size_bytes = max_source_size_mb * 1024 * 1024
        total_size_bytes = _get_actual_total_source_size(paths_to_process)

        if total_size_bytes == -1: # Indicates a critical error in size calculation by helper
            msg = "ERROR: Critical error while calculating total source size."
            logging.error(msg)
            return False, msg

        current_size_mb = total_size_bytes / (1024*1024)
        logging.info(f"Total source size: {current_size_mb:.2f} MB")
        if total_size_bytes > max_source_size_bytes:
            msg = (f"ERROR: Backup cancelled!\n"
                   f"Total source size ({current_size_mb:.2f} MB) exceeds the limit ({max_source_size_mb} MB).")
            logging.error(msg)
            return False, msg
    else:
        logging.info("Source size check skipped (limit not set).")
    # --- END Size Check ---


    # --- Creazione Directory Backup ---
    try:
        os.makedirs(profile_backup_dir, exist_ok=True)
    except Exception as e:
        msg = f"ERROR: Unable to create backup directory'{profile_backup_dir}': {e}"
        logging.error(msg, exc_info=True)
        return False, msg
    # --- FINE Creazione Directory ---


    # --- Creazione Archivio ZIP ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_profile_name_for_zip = sanitize_foldername(profile_name) # Usa nome profilo per nome file zip
    archive_name = f"Backup_{safe_profile_name_for_zip}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    logging.info(f"Backup startup (ZIP) for '{profile_name}': From {len(paths_to_process)} source/s to '{archive_path}'")

    zip_compression = zipfile.ZIP_DEFLATED
    zip_compresslevel = 6 # Default Standard

    if compression_mode == "best":
        zip_compresslevel = 9
        logging.info("Compression Mode: Maximum (Deflate Level 9)")
    elif compression_mode == "fast":
        zip_compresslevel = 1
        logging.info("Compression Mode: Fast (Deflate Level 1)")
    elif compression_mode == "none":
        zip_compression = zipfile.ZIP_STORED
        zip_compresslevel = None # Non applicabile per STORED
        logging.info("Compression Mode: None (Store)")
    else: # "standard" or default
        logging.info("Compression Mode: Standard (Deflate Level 6)")


    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, compresslevel=zip_compresslevel) as zipf:

            # --- Logica Specifica DuckStation (SOLO se NON multi-percorso) --- START
            is_duckstation_single_file = False
            specific_mcd_file_to_backup = None
            if not is_multiple_paths:
                 single_source_path = paths_to_process[0] # C'è solo un percorso
                 if os.path.isdir(single_source_path): # Controlla solo se è una directory
                    logging.debug(f"--- DuckStation Control (Single Path Mode - Directory) ---")
                    normalized_save_path = os.path.normpath(single_source_path).lower()
                    expected_suffix = os.path.join("duckstation", "memcards").lower()
                    logging.debug(f"  Single source path: '{single_source_path}'")
                    logging.debug(f"  Normalized: '{normalized_save_path}'")
                    logging.debug(f"  Expected suffix: '{expected_suffix}'")

                    if normalized_save_path.endswith(expected_suffix):
                         actual_card_name = profile_name # Usa il nome profilo come base
                         prefix = "DuckStation - "
                         if profile_name.startswith(prefix):
                             actual_card_name = profile_name[len(prefix):] # Estrai nome reale carta
                         mcd_filename = actual_card_name + ".mcd"
                         potential_mcd_path = os.path.join(single_source_path, mcd_filename)
                         logging.debug(f"  Potential MCD Pathway: '{potential_mcd_path}'")
                         if os.path.isfile(potential_mcd_path):
                             is_duckstation_single_file = True
                             specific_mcd_file_to_backup = potential_mcd_path
                             logging.info(f"DuckStation profile detected. Preparing single file backup: {mcd_filename}")
                         else:
                             logging.warning(f"The path looks like DuckStation memcards, but the specific file '{mcd_filename}' not found in '{single_source_path}'. performing standard directory backups.")
                    else:
                         logging.debug(f"Single path is not DuckStation memcards directory. I do standard backups.")
                 elif os.path.isfile(single_source_path):
                      logging.debug(f"Single path is a file '{single_source_path}'. Don't applyg DuckStation logic.")
                 # --- Logica Specifica DuckStation --- END

            # --- Esecuzione Backup ---
            if is_duckstation_single_file and specific_mcd_file_to_backup:
                 # Backup solo del file .mcd specifico per DuckStation
                 try:
                     mcd_arcname = os.path.basename(specific_mcd_file_to_backup) # Nome file nello zip
                     logging.debug(f"Adding DuckStation Single File: '{specific_mcd_file_to_backup}' as '{mcd_arcname}'")
                     zipf.write(specific_mcd_file_to_backup, arcname=mcd_arcname)
                     logging.info(f"Single file successfully added {mcd_arcname} to the archive.")
                 except FileNotFoundError:
                     logging.error(f"  CRITICAL ERROR: DuckStation .mcd file disappeared during backup: '{specific_mcd_file_to_backup}'")
                     raise # Propaga l'errore per annullare il backup
                 except Exception as e_write:
                     logging.error(f"  Error adding DuckStation file '{specific_mcd_file_to_backup}' to the zip: {e_write}", exc_info=True)
                     raise # Propaga l'errore
            else:
                 # Standard Backup: Process all paths in the list (or the single one)
                 logging.debug(f"Executing standard backup for {len(paths_to_process)} path(s).")
                 for source_path in paths_to_process:
                     logging.debug(f"Processing source path: {source_path}")
                     if os.path.isdir(source_path):
                         # Add the directory content
                         base_folder_name = os.path.basename(source_path) # Folder name (e.g. SAVEDATA)
                         len_source_path_parent = len(os.path.dirname(source_path)) + len(os.sep)

                         for foldername, subfolders, filenames in os.walk(source_path):
                             for filename in filenames:
                                 file_path_absolute = os.path.join(foldername, filename)
                                 # Create arcname: base_folder_name / internal_relative_path
                                 # Example: SAVEDATA/file.txt
                                 relative_path = file_path_absolute[len_source_path_parent:]
                                 arcname = relative_path # Already includes the base folder in the calculated relative path
                                 logging.debug(f"  Adding file: '{file_path_absolute}' as '{arcname}'")
                                 try:
                                      zipf.write(file_path_absolute, arcname=arcname)
                                 except FileNotFoundError:
                                      logging.warning(f"  Skipped file (not found during walk?): '{file_path_absolute}'")
                                 except Exception as e_write_walk:
                                      logging.error(f"  Error adding file '{file_path_absolute}' to zip during walk: {e_write_walk}")
                     elif os.path.isfile(source_path):
                         # --- Modified Logic for Single Files (in list or not) ---
                         # Calculate arcname to preserve relative structure, as os.walk does
                         source_dir = os.path.dirname(source_path)
                         # Use the PARENT directory of the file's directory as the base for arcname
                         # to include the file's directory itself in the archive.
                         source_base_dir = os.path.dirname(source_dir)
                         len_source_base_dir = len(source_base_dir) + len(os.sep)

                         # arcname will be: file_folder_name/file_name.bin
                         # Example: 00000001/GC_S00.bin
                         arcname = source_path[len_source_base_dir:]

                         logging.debug(f"Adding file (from list/single): '{source_path}' as '{arcname}'")
                         try:
                             zipf.write(source_path, arcname=arcname)
                         except FileNotFoundError:
                              logging.error(f"  CRITICAL ERROR: Source file disappeared during backup: '{source_path}'")
                              raise # Propagate to cancel
                         except Exception as e_write_single:
                              logging.error(f"  Error adding file '{source_path}' to zip: {e_write_single}", exc_info=True)
                              raise # Propagate to cancel

        logging.info(f"Backup archive created successfully: '{archive_path}'")

    except (IOError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        msg = f"ERROR during ZIP archive creation '{archive_path}': {e}"
        logging.error(msg, exc_info=True)
        # Try to delete the potentially corrupted/incomplete archive
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
                logging.warning(f"Potentially incomplete archive deleted: {archive_path}")
        except Exception as del_e:
            logging.error(f"Unable to delete incomplete archive '{archive_path}': {del_e}")
        return False, msg
    except Exception as e: # Catch other unexpected errors
         msg = f"UNEXPECTED ERROR during ZIP backup creation '{profile_name}': {e}"
         logging.error(msg, exc_info=True)
         try:
             if os.path.exists(archive_path): os.remove(archive_path); logging.warning(f"Failed archive removed: {archive_name}")
         except Exception as rem_e: logging.error(f"Unable to remove failed archive: {rem_e}")
         return False, msg
    # --- END ZIP Archive Creation ---

    # --- Gestione Vecchi Backup ---
    deleted_files = manage_backups(profile_name, backup_base_dir, max_backups)
    deleted_msg = f" Deleted {len(deleted_files)} obsolete backups." if deleted_files else ""
    # --- FINE Gestione ---

    return True, f"Backup completed successfully:\n'{archive_name}'" + deleted_msg

# --- Support Function for Folder Size Calculation ---
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
                backup_datetime = datetime.fromtimestamp(mtime)
                #date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = "Unknown date"
            backups.append((fname, fpath, backup_datetime))
    except Exception as e:
        logging.error(f"Error listing backups for '{profile_name}': {e}")

    return backups

# --- Restore Function ---
def perform_restore(profile_name, destination_paths, archive_to_restore_path):
    """
    Performs restoration from a ZIP archive. Handles a single path (str) or multiple paths (list).
    Returns (bool success, str message).
    """
    # Necessary imports locally if they are not global in the module
    import zipfile
    import shutil
    logging.info(f"Starting perform_restore for profile: '{profile_name}'")
    logging.info(f"Archive selected for restoration: '{archive_to_restore_path}'")

    # SPECIAL HANDLING FOR XEMU PROFILES
    # Check if this is an xemu profile by loading profile data
    try:
        profiles = load_profiles()
        if profile_name in profiles:
            profile_data = profiles[profile_name]
            if isinstance(profile_data, dict) and profile_data.get('type') == 'xbox_game_save':
                logging.info(f"Detected xemu game save profile for restore: {profile_name}")
                try:
                    from emulator_utils.xemu_manager import restore_xbox_save
                    
                    # Get executable path from profile data
                    executable_path = None
                    
                    # Helper function to extract executable path
                    def extract_executable_path(path_str):
                        if not path_str:
                            return None
                        if path_str.endswith('.exe'):
                            return path_str
                        elif path_str.endswith('.qcow2'):
                            # If it's an HDD file, the executable might be in the same directory
                            hdd_dir = os.path.dirname(path_str)
                            # Look for xemu.exe in the same directory
                            potential_exe = os.path.join(hdd_dir, 'xemu.exe')
                            if os.path.isfile(potential_exe):
                                return potential_exe
                            # Otherwise return the directory
                            return hdd_dir
                        elif os.path.isdir(path_str):
                            # If it's a directory, look for xemu.exe inside
                            potential_exe = os.path.join(path_str, 'xemu.exe')
                            if os.path.isfile(potential_exe):
                                return potential_exe
                            return path_str
                        return path_str
                    
                    # Try to find executable path from profile
                    if 'paths' in profile_data and profile_data['paths']:
                        executable_path = extract_executable_path(profile_data['paths'][0])
                    elif 'path' in profile_data:
                        executable_path = extract_executable_path(profile_data['path'])
                    
                    # Use xemu's specialized restore function with direct ZIP file path
                    success, message = restore_xbox_save(profile_data['id'], archive_to_restore_path, executable_path)
                    
                    if success:
                        return True, f"Xbox save restore completed successfully for: {profile_name}\n{message}"
                    else:
                        return False, f"Xbox save restore failed for: {profile_name}\n{message}"
                        
                except Exception as e:
                    logging.error(f"Error during xemu restore for '{profile_name}': {e}", exc_info=True)
                    return False, f"Xbox save restore error: {e}"
    except Exception as e:
        logging.warning(f"Could not check for xemu profile type: {e}")
        # Continue with standard restore logic

    is_multiple_paths = isinstance(destination_paths, list)
    # Normalize all paths immediately
    paths_to_process = [os.path.normpath(p) for p in (destination_paths if is_multiple_paths else [destination_paths])]

    logging.info(f"Target destination path(s): {paths_to_process}")

    # --- Archive Validation ---
    if not os.path.isfile(archive_to_restore_path):
        msg = f"ERROR: Restore archive not found: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    if not zipfile.is_zipfile(archive_to_restore_path):
        msg = f"ERROR: The selected file is not a valid ZIP archive: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    # --- END Validation ---

    # --- Destination Cleanup (before extraction) ---
    logging.warning(f"--- Preparing to clean destination path(s) before restore ---")
    for dest_path in paths_to_process:
        # Ensure the parent directory exists for the destination path
        parent_dir = os.path.dirname(dest_path)
        try:
            if parent_dir and not os.path.exists(parent_dir):
                 logging.info(f"Creating missing parent directory: '{parent_dir}'")
                 os.makedirs(parent_dir, exist_ok=True)
        except Exception as e_mkdir:
             msg = f"ERROR creating parent directory '{parent_dir}' for destination '{dest_path}': {e_mkdir}"
             logging.error(msg, exc_info=True)
             # Consider whether to stop here? For now, log and continue.
             # return False, msg

        # Check what to do with the existing destination path
        if os.path.isdir(dest_path):
            logging.warning(f"Attempting to remove contents of existing directory: '{dest_path}'")
            try:
                for item in os.listdir(dest_path):
                    item_path = os.path.join(dest_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logging.debug(f"  Removed subdirectory: {item_path}")
                    elif os.path.isfile(item_path):
                        os.remove(item_path)
                        logging.debug(f"  Removed file: {item_path}")
                logging.info(f"Contents of '{dest_path}' successfully cleaned.")
            except Exception as e:
                msg = f"ERROR during cleanup of destination directory '{dest_path}': {e}"
                logging.error(msg, exc_info=True)
                return False, msg
        elif os.path.isfile(dest_path): # Handles the case of single file destination (e.g. Duckstation .mcd)
             logging.warning(f"Attempting to remove existing single file: '{dest_path}'")
             try:
                 os.remove(dest_path)
                 logging.info(f"Single file successfully removed: '{dest_path}'")
             except FileNotFoundError:
                 logging.info(f"Destination file '{dest_path}' did not exist, no removal necessary.")
             except Exception as e:
                 msg = f"ERROR removing destination file '{dest_path}': {e}"
                 logging.error(msg, exc_info=True)
                 return False, msg
        else:
             # The path doesn't exist, will be created by extraction if necessary
             logging.info(f"Destination path '{dest_path}' does not exist.")
    logging.warning(f"--- Destination cleanup completed ---")
    # --- END Cleanup ---

    # --- Estrazione Archivio ---
    logging.info(f"Start extraction from '{archive_to_restore_path}'...")
    extracted_successfully = True
    error_messages = []

    try:
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:

            # --- Differentiated extraction logic ---
            if is_multiple_paths:
                # --- Multi-Path Extraction ---
                logging.debug("Multi-path restore: Mapping zip content to destination paths.")
                # Create a map: base folder name (in zip) -> complete destination path
                dest_map = {os.path.basename(p): p for p in paths_to_process}
                logging.debug(f"Destination map created: {dest_map}")

                # Check if the zip contains base folders (e.g. 'SAVEDATA/', 'SYSTEM/')
                # Improved cross-platform compatibility for path checking
                zip_members = zipf.namelist()
                logging.debug(f"ZIP contains {len(zip_members)} members. First 10: {zip_members[:10]}")
                
                # More robust check that works on both Windows and Linux
                zip_contains_base_folders = False
                for m in zip_members:
                    # Normalize path separators for the current OS
                    normalized_path = m.replace('/', os.sep)
                    # Split the path to get the base folder
                    path_parts = normalized_path.split(os.sep, 1)
                    if len(path_parts) > 0:
                        base_folder = path_parts[0]
                        if base_folder in dest_map:
                            zip_contains_base_folders = True
                            logging.debug(f"Found matching base folder: '{base_folder}' in ZIP member: '{m}'")
                            break
                
                logging.debug(f"Does the zip contain base folders matching the destinations? {zip_contains_base_folders}")
                # If no base folders found, also try checking for exact filename matches
                if not zip_contains_base_folders and len(zip_members) > 0:
                    logging.debug("No base folders found, checking if any ZIP members match destination filenames directly.")
                    for dest_path in paths_to_process:
                        dest_filename = os.path.basename(dest_path)
                        for m in zip_members:
                            if m.endswith(dest_filename) or m.endswith(dest_filename + '/'):
                                zip_contains_base_folders = True
                                logging.debug(f"Found matching filename: '{dest_filename}' in ZIP member: '{m}'")
                                break

                if not zip_contains_base_folders:
                    # Nuovo codice: prova a trovare i file basandosi sul nome file finale
                    logging.warning("Base folders not found in ZIP. Trying alternative extraction method based on filenames.")
                    
                    # Crea una mappa dei nomi file (senza percorso) alle destinazioni complete
                    filename_to_dest = {os.path.basename(p): p for p in paths_to_process}
                    logging.debug(f"Filename to destination map: {filename_to_dest}")
                    
                    # Crea una mappa dei nomi file (senza percorso) ai percorsi completi nel ZIP
                    zip_files = zipf.namelist()
                    zip_filename_to_path = {os.path.basename(m.replace('/', os.sep)): m for m in zip_files}
                    logging.debug(f"ZIP filename to path map: {zip_filename_to_path}")
                    
                    # Verifica se possiamo trovare corrispondenze
                    matches_found = False
                    for filename, dest_path in filename_to_dest.items():
                        if filename in zip_filename_to_path:
                            matches_found = True
                            zip_path = zip_filename_to_path[filename]
                            logging.info(f"Found match: {filename} in ZIP as {zip_path}")
                            
                            # Estrai il file
                            try:
                                # Assicurati che la directory di destinazione esista
                                dest_dir = os.path.dirname(dest_path)
                                if dest_dir and not os.path.exists(dest_dir):
                                    os.makedirs(dest_dir, exist_ok=True)
                                    
                                # Estrai il file
                                with zipf.open(zip_path) as source, open(dest_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                                logging.info(f"Successfully extracted {zip_path} to {dest_path}")
                            except Exception as e:
                                logging.error(f"Error extracting {zip_path} to {dest_path}: {e}")
                                return False, f"Error during alternative extraction method: {e}"
                    
                    if matches_found:
                        return True, f"Restore completed successfully using alternative extraction method."
                    
                    # Se arriviamo qui, non abbiamo trovato corrispondenze
                    msg = "ERROR: Multi-path restore failed. The ZIP archive doesn't seem to contain the expected base folders (e.g. SAVEDATA/, SYSTEM/). Backup potentially corrupted or created incorrectly."
                    logging.error(msg)
                    logging.error(f"Archive members (example): {zipf.namelist()[:10]}")
                    logging.error(f"Expected destination map: {dest_map}")
                    return False, msg

                # Extract member by member to the correct destination
                for member_path in zipf.namelist():
                    normalized_member_path = member_path.replace('/', os.sep)
                    try:
                        # Get the base part of the path in the zip (e.g. 'SAVEDATA')
                        zip_base_folder = normalized_member_path.split(os.sep, 1)[0]
                    except IndexError:
                        logging.warning(f"Skipping member with potentially invalid path format: '{member_path}'")
                        continue

                    if zip_base_folder in dest_map:
                        target_dest_path_base = dest_map[zip_base_folder]
                        # Get the relative path *inside* the base folder (e.g. 'file.txt' from 'SAVEDATA/file.txt')
                        relative_path = normalized_member_path[len(zip_base_folder):].lstrip(os.sep)
                        # Build the complete extraction path
                        full_extract_path = os.path.join(target_dest_path_base, relative_path)

                        # Ensure the directory for the file exists before extracting
                        if member_path.endswith('/') or member_path.endswith('\\'): # It's a directory in the zip
                            if relative_path: # Avoid creating '.' if the relative path is empty
                                logging.debug(f"  Creating directory from zip: {full_extract_path}")
                                os.makedirs(full_extract_path, exist_ok=True)
                        else: # It's a file
                            file_dir = os.path.dirname(full_extract_path)
                            if file_dir and not os.path.exists(file_dir): # Ensure it's not empty and create it if it doesn't exist
                                logging.debug(f"  Creating directory for file: {file_dir}")
                                os.makedirs(file_dir, exist_ok=True)
                            try:
                                # Extract the single file overwriting if it exists
                                with zipf.open(member_path) as source, open(full_extract_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                                logging.debug(f"  Extracted file {member_path} -> {full_extract_path}")
                            except Exception as e_file:
                                msg = f"ERROR extracting file '{member_path}' to '{full_extract_path}': {e_file}"
                                logging.error(msg, exc_info=True)
                                error_messages.append(msg)
                                extracted_successfully = False # Mark partial failure
                    else:
                        # This member doesn't belong to any of the expected base folders
                        msg = f"WARNING: Zip member '{member_path}' (base: '{zip_base_folder}') doesn't match any expected destination ({list(dest_map.keys())}). Skipping."
                        logging.warning(msg)
                        # Consider whether to treat this as an error: error_messages.append(msg); extracted_successfully = False

            else: # Single Path Extraction
                # --- Single Path Extraction --- (Use extractall for simplicity)
                single_dest_path = paths_to_process[0]
                # Ensure the destination directory exists (should already exist from cleanup, but double-check)
                os.makedirs(single_dest_path, exist_ok=True)
                logging.debug(f"Single path restore: Extracting all content to '{single_dest_path}'")
                try:
                    zipf.extractall(single_dest_path)
                    logging.info(f"Content successfully extracted to '{single_dest_path}'")
                except Exception as e_extractall:
                    msg = f"ERROR during extractall to '{single_dest_path}': {e_extractall}"
                    logging.error(msg, exc_info=True)
                    error_messages.append(msg)
                    extracted_successfully = False

    except zipfile.BadZipFile:
        msg = f"ERROR: The file is not a valid ZIP archive or is corrupted: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    except (IOError, OSError) as e: # Catch IO/OS errors
        msg = f"ERROR IO/OS during extraction: {e}"
        logging.error(msg, exc_info=True)
        error_messages.append(msg)
        extracted_successfully = False
    except Exception as e:
        msg = f"FATAL ERROR unexpected during the restore process: {e}"
        logging.error(msg, exc_info=True)
        # Make sure to return accumulated errors if present
        final_message = msg
        if error_messages:
            final_message += "\n\nAdditional errors encountered during extraction:\n" + "\n".join(error_messages)
        return False, final_message
    # --- END Archive Extraction ---

    # --- Risultato Finale ---
    if extracted_successfully:
        msg = f"Restore completed successfully for profile '{profile_name}'."
        logging.info(msg)
        final_message = msg
        if error_messages: # Aggiunge avvisi anche in caso di successo parziale
             final_message += "\n\nATTENZIONE: Sono stati riscontrati alcuni errori durante l'estrazione:\n" + "\n".join(error_messages)
        return True, final_message
    else:
        msg = f"Restore for profile '{profile_name}' failed or completed with errors."
        logging.error(msg)
        final_message = msg
        if error_messages:
            final_message += "\n\nDettaglio errori:\n" + "\n".join(error_messages)
        return False, final_message

# --- Steam Detection Logic ---

# Global internal cache in core_logic
_steam_install_path = None
_steam_libraries = None
_installed_steam_games = None
_steam_userdata_path = None
_steam_id3 = None
_cached_possible_ids = None
_cached_id_details = None

# Find Steam installation path
def get_steam_install_path():
    """Find Steam installation path. Returns str or None."""
    # Manteniamo il tentativo di importare winreg per Windows, ma non è più l'unico modo.
    winreg_module = None
    try:
        import winreg as wr # Usa un alias per evitare conflitti se winreg fosse già importato globalmente
        winreg_module = wr
    except ImportError:
         logging.info("Modulo winreg non disponibile su questa piattaforma (normale per non-Windows).")
    
    global _steam_install_path 
    if _steam_install_path is not None: # Controllo più esplicito per None
        return _steam_install_path

    current_os = platform.system()
    found_path = None

    if current_os == "Windows":
        if not winreg_module:
            logging.warning("winreg non importato correttamente su Windows, impossibile cercare Steam nel registro.")
            # Non ritornare None qui se vuoi provare altri metodi anche su Windows in futuro
        else:
            try:
                key_path = r"Software\\Valve\\Steam"
                potential_hives = [(winreg_module.HKEY_CURRENT_USER, "HKCU"), (winreg_module.HKEY_LOCAL_MACHINE, "HKLM")]
                for hive, hive_name in potential_hives:
                    try:
                        # Usa 'with' per la gestione automatica della chiusura della chiave
                        with winreg_module.OpenKey(hive, key_path) as hkey:
                            path_value, _ = winreg_module.QueryValueEx(hkey, "SteamPath")
                        
                        norm_path = os.path.normpath(path_value.replace('/', '\\\\'))
                        if os.path.isdir(norm_path):
                            found_path = norm_path
                            logging.info(f"Found Steam installation ({hive_name}) via registry: {found_path}")
                            break # Trovato, esci dal loop degli hives
                    except (FileNotFoundError, OSError): 
                        logging.debug(f"SteamPath not found in registry hive: {hive_name}\\{key_path}")
                        continue # Prova il prossimo hive
                    except Exception as e: 
                        logging.warning(f"Error reading registry ({hive_name}): {e}")
                if not found_path:
                    logging.warning("Steam installation not found in Windows registry (dopo aver controllato HKCU e HKLM).")
            except Exception as e:
                logging.error(f"Unexpected error searching for Steam on Windows via registry: {e}")
        
        # Qui potresti aggiungere altri metodi di ricerca specifici per Windows se il registro fallisce
        # e found_path è ancora None.

    elif current_os == "Linux":
        logging.info("Attempting to find Steam on Linux...")
        common_linux_paths = [
            os.path.expanduser("~/.local/share/Steam"),
            os.path.expanduser("~/.steam/steam"), # Percorso legacy comune
            os.path.expanduser("~/.steam/root"),   # Altro percorso legacy possibile (spesso un link a .steam/steam)
            os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam") # Flatpak
        ]
        for path_to_check in common_linux_paths:
            if not os.path.isdir(path_to_check):
                logging.debug(f"Path does not exist or is not a directory: {path_to_check}")
                continue

            logging.debug(f"Checking for Steam indicators in: {path_to_check}")
            
            # Indicatori per un'installazione di Steam valida
            has_steam_sh = os.path.exists(os.path.join(path_to_check, "steam.sh"))
            has_steamapps = os.path.isdir(os.path.join(path_to_check, "steamapps"))
            has_userdata = os.path.isdir(os.path.join(path_to_check, "userdata"))
            # File di configurazione cruciali
            has_config_vdf = os.path.exists(os.path.join(path_to_check, "config", "config.vdf"))
            has_libraryfolders_vdf = os.path.exists(os.path.join(path_to_check, "steamapps", "libraryfolders.vdf"))

            # Considera un percorso valido se ha steamapps e userdata, o file di configurazione chiave
            if (has_steamapps and has_userdata) or has_config_vdf or has_libraryfolders_vdf or has_steam_sh:
                found_path = os.path.normpath(path_to_check)
                logging.info(f"Found Steam installation on Linux at: {found_path} (Indicators: sh:{has_steam_sh}, apps:{has_steamapps}, user:{has_userdata}, conf_vdf:{has_config_vdf}, lib_vdf:{has_libraryfolders_vdf})")
                break # Trovato, esci dal loop dei percorsi
            else:
                logging.debug(f"No clear Steam indicators found in {path_to_check}")
        
        if not found_path:
            logging.warning("Steam installation not found in common Linux paths.")

    elif current_os == "Darwin": # macOS
        logging.info("Attempting to find Steam on macOS...")
        common_mac_paths = [
            os.path.expanduser("~/Library/Application Support/Steam")
        ]
        for path_to_check in common_mac_paths:
            if not os.path.isdir(path_to_check):
                logging.debug(f"Path does not exist or is not a directory: {path_to_check}")
                continue
            
            logging.debug(f"Checking for Steam indicators in: {path_to_check}")
            has_steamapps = os.path.isdir(os.path.join(path_to_check, "steamapps"))
            has_userdata = os.path.isdir(os.path.join(path_to_check, "userdata"))

            if has_steamapps and has_userdata: # Su Mac, questi due sono buoni indicatori
                found_path = os.path.normpath(path_to_check)
                logging.info(f"Found Steam installation on macOS at: {found_path}")
                break # Trovato
        if not found_path:
            logging.warning("Steam installation not found in common macOS paths.")
    else:
        logging.info(f"Steam path detection for OS '{current_os}' is not specifically implemented.")

    if found_path:
        _steam_install_path = found_path # Memorizza nella cache solo se trovato
        return _steam_install_path
    
    logging.warning("Steam installation path could not be determined.")
    return None

# Find Steam userdata path
def _parse_vdf(file_path):
    """Helper internal for parsing VDF. Returns dict or None."""
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

# Find Steam libraries
def find_steam_libraries():
    """Find Steam libraries. Returns list of paths."""
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

# Find installed Steam games
def find_installed_steam_games():
    """Find installed Steam games. Returns dict {appid: {'name':..., 'installdir':...}}."""
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
                        raw_appid = app_state.get('appid', 'MISSING_APPID')
                        raw_name = app_state.get('name', 'MISSING_NAME')
                        raw_installdir = app_state.get('installdir', 'MISSING_INSTALLDIR')
                        raw_state_flags = app_state.get('StateFlags', 'MISSING_STATEFLAGS')
                        logging.debug(f"Processing ACF '{filename}': AppID='{raw_appid}', Name='{raw_name}', InstallDir='{raw_installdir}', StateFlags='{raw_state_flags}'")

                        # <<< MODIFICATO: Verifica più robusta dei campi necessari
                        if all(k in app_state for k in ['appid', 'name', 'installdir']) and 'StateFlags' in app_state:
                            appid = app_state['appid'] # Should be a string from VDF
                            if appid in processed_appids:
                                logging.debug(f"Skipping AppID {appid} ('{app_state.get('name', 'N/A')}') from '{filename}': already processed.")
                                continue # Già trovato (probabilmente nella libreria principale)

                            installdir_relative = app_state['installdir']
                            # Costruisci percorso assoluto relativo alla LIBRERIA corrente
                            installdir_absolute = os.path.normpath(os.path.join(steamapps_path, 'common', installdir_relative))
                            name_original = app_state.get('name', f"Unknown Game {appid}")
                            name = name_original.replace('™', '').replace('®', '').strip()

                            # Verifica installazione: StateFlags 4 = installato, 1026 = installato+aggiornamento, 6 = installato+validazione?
                            # Controlliamo anche se la cartella esiste fisicamente come fallback
                            state_flags = int(app_state.get('StateFlags', 0))
                            is_installed_by_flag = (state_flags in [4, 6, 1026]) or \
                                           (state_flags == 2 and os.path.isdir(installdir_absolute)) # 2=UpdateRequired?
                            
                            is_dir_present = os.path.isdir(installdir_absolute)
                            logging.debug(f"  AppID {appid} ('{name}'): RelativeDir='{installdir_relative}', AbsoluteDir='{installdir_absolute}', StateFlags={state_flags}, InstalledByFlag={is_installed_by_flag}, DirPresent={is_dir_present}")

                            if not is_installed_by_flag:
                                logging.debug(f"  Skipping AppID {appid} ('{name}'): Not installed according to StateFlags ({state_flags}).")
                                continue
                            if not is_dir_present:
                                logging.debug(f"  Skipping AppID {appid} ('{name}'): Install directory '{installdir_absolute}' not found.")
                                continue

                            # FILTRO PER ESCLUDERE STEAM RUNTIME E SIMILI
                            name_lower = name.lower()
                            if "steam" in name_lower and "runtime" in name_lower:
                                logging.info(f"Skipping '{name}' (AppID: {appid}) as it appears to be a Steam Runtime tool.")
                                continue # Salta l'aggiunta di questo elemento
                            
                            # Sanity check for installdir_absolute before adding
                            if not installdir_absolute or not isinstance(installdir_absolute, str):
                                logging.warning(f"  Skipping AppID {appid} ('{name}'): Calculated installdir_absolute is invalid ('{installdir_absolute}').")
                                continue

                            games[appid] = {'name': name, 'installdir': installdir_absolute}
                            processed_appids.add(appid)
                            total_games_found += 1
                            logging.debug(f"  Successfully added game: {name} (AppID: {appid}), InstallDir: {installdir_absolute} from library '{lib_path}'")
                        else:
                            logging.debug(f"Skipping ACF file '{filename}' (AppID: {raw_appid}): missing one or more required fields (appid, name, installdir, StateFlags). Fields found: {list(app_state.keys())}")
        except Exception as e:
            logging.error(f"Error scanning games in '{steamapps_path}': {e}")

    logging.info(f"Found {total_games_found} installed Steam games.")
    _installed_steam_games = games
    return games

# Constant for ID3 <-> ID64 conversion
STEAM_ID64_BASE = 76561197960265728

# Find Steam userdata info
def find_steam_userdata_info():
    """Find userdata path, SteamID3, list of possible IDs and ID details (including display name)."""
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

# --- Function to delete a backup file ---
def delete_single_backup_file(file_path):
    """Deletes a single backup file specified by the full path."""
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

# --- Function to calculate the size of a folder ---
def get_directory_size(directory_path):
    """Calculates recursively the total size of a folder in bytes."""
    total_size = 0
    if not os.path.isdir(directory_path): # <<< NEW: Check if it's a valid directory
         logging.error(f"ERROR get_directory_size: Path is not a valid directory: {directory_path}")
         return -1 # Indicates error

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
        return -1 # Returns -1 to indicate calculation error
    return total_size

# --- Function to get display name from backup filename ---
def get_display_name_from_backup_filename(filename):
    """
    Removes the timestamp suffix (_YYYYMMDD_HHMMSS) from a backup file name
    for a cleaner display.

    Ex: "Backup_ProfiloX_20250422_030000.zip" -> "Backup_ProfiloX"
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

def _get_actual_total_source_size(source_paths_list):
    """Calculates the total actual size of source paths, resolving .lnk shortcuts on Windows."""
    total_size = 0
    logging.debug(f"Calculating actual total source size for paths: {source_paths_list}")

    for single_path_str in source_paths_list:
        actual_path_to_measure = single_path_str
        is_shortcut = False
        original_shortcut_path = None

        if platform.system() == "Windows" and \
           single_path_str.lower().endswith(".lnk") and \
           os.path.isfile(single_path_str):
            is_shortcut = True
            original_shortcut_path = single_path_str
            try:
                shortcut = winshell.shortcut(single_path_str)
                target_path = shortcut.path
                if target_path and os.path.exists(target_path):
                    actual_path_to_measure = target_path
                    logging.debug(f"Resolved shortcut '{single_path_str}' to '{actual_path_to_measure}'")
                elif target_path:
                    logging.warning(f"Shortcut '{single_path_str}' target '{target_path}' does not exist. Skipping for size calculation.")
                    continue
                else:
                    logging.warning(f"Shortcut '{single_path_str}' has an empty or invalid target path. Skipping for size calculation.")
                    continue
            except Exception as e_lnk:
                logging.warning(f"Could not resolve shortcut '{single_path_str}': {e_lnk}. Skipping for size calculation.")
                continue
        
        if not os.path.exists(actual_path_to_measure):
            log_msg = f"Source path '{actual_path_to_measure}'"
            if is_shortcut:
                log_msg += f" (from shortcut '{original_shortcut_path}')"
            log_msg += " does not exist. Skipping for size calculation."
            logging.warning(log_msg)
            continue

        try:
            current_item_size = 0
            if os.path.isfile(actual_path_to_measure):
                current_item_size = os.path.getsize(actual_path_to_measure)
                logging.debug(f"Size of file '{actual_path_to_measure}': {current_item_size} bytes")
            elif os.path.isdir(actual_path_to_measure):
                dir_size = get_directory_size(actual_path_to_measure) # Assumes get_directory_size exists and is robust
                if dir_size != -1:
                    current_item_size = dir_size
                    logging.debug(f"Size of directory '{actual_path_to_measure}': {current_item_size} bytes")
                else:
                    logging.warning(f"Could not get size of directory '{actual_path_to_measure}'. Skipping.")
                    continue
            else:
                logging.warning(f"Path '{actual_path_to_measure}' (from '{original_shortcut_path}' if shortcut) is not a file or directory. Skipping.")
                continue
            total_size += current_item_size
        except OSError as e_size:
            logging.warning(f"OS error getting size for '{actual_path_to_measure}': {e_size}. Skipping.")
            continue
            
    logging.info(f"Total actual calculated source size: {total_size} bytes ({total_size / (1024*1024):.2f} MB).")
    return total_size