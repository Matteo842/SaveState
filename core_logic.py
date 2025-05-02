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
#import settings_manager # For saving theme settings

try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Libreria 'thefuzz' trovata e caricata.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    # Logga il warning una sola volta qui all'avvio se manca
    logging.warning("Libreria 'thefuzz' non trovata. Il fuzzy matching sarà disabilitato.")
    logging.warning("Installala con: pip install thefuzz[speedup]")

# --- Define profiles file path ---
PROFILES_FILENAME = "game_save_profiles.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Get base folder
if APP_DATA_FOLDER: # Check if valid
    PROFILES_FILE_PATH = os.path.join(APP_DATA_FOLDER, PROFILES_FILENAME)
else:
    # Fallback
    logging.error("Unable to determine APP_DATA_FOLDER, use relative path for game_save_profiles.json.")
    PROFILES_FILE_PATH = os.path.abspath(PROFILES_FILENAME)
logging.info(f"Profile file path in use: {PROFILES_FILE_PATH}")
# --- End definition ---

# <<< Function to generate multiple abbreviations >>>
def generate_abbreviations(name, game_install_dir=None):
    """
    Generates a list of possible abbreviations/alternative names for the game.
    Includes colon handling and improved exe parsing.
    """
    abbreviations = set()
    if not name: return []

    # Clean base name
    sanitized_name = re.sub(r'[™®©:]', '', name).strip() # Remove : for base processing
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

# <<< Helper for initial sequence check >>>
def matches_initial_sequence(folder_name, game_title_words):
    """
    Checks if folder_name (e.g., "ME") EXACTLY MATCHES the sequence
    of initials of game_title_words (e.g., ["Metro", "Exodus"]).
    """
    if not folder_name or not game_title_words:
        return False
    try:
        # Extract UPPERCASE initials from significant words
        word_initials = [word[0].upper() for word in game_title_words if word]
        # Join the initials to form the expected sequence (e.g., "ME")
        expected_sequence = "".join(word_initials)
        # Compare (case-insensitive) the folder name with the expected sequence
        return folder_name.upper() == expected_sequence
    except Exception as e:
        # Log any unexpected errors during processing
        logging.error(f"Error in matches_initial_sequence ('{folder_name}', {game_title_words}): {e}")
        return False

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
    Carica i profili da PROFILES_FILE_PATH, assicurandosi che i valori siano
    dizionari contenenti almeno la chiave 'path'.
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
                    profile_path = path_or_data.get('path')
                    if profile_path and isinstance(profile_path, str) and os.path.isdir(profile_path):
                        # Se il path esiste ed è valido, copia il dizionario
                        loaded_profiles[name] = path_or_data.copy() # Usa copy per sicurezza
                    elif profile_path:
                         # Se il path esiste ma non è valido
                         logging.warning(f"Path '{profile_path}' in profile dict for '{name}' is invalid. Setting empty path.")
                         temp_profile = path_or_data.copy()
                         temp_profile['path'] = "" # Imposta path vuoto
                         loaded_profiles[name] = temp_profile
                    else:
                        # Se manca la chiave 'path'
                        logging.warning(f"Profile '{name}' is a dict but missing 'path' key or path is invalid. Setting empty path.")
                        temp_profile = path_or_data.copy()
                        temp_profile['path'] = "" # Imposta path vuoto
                        loaded_profiles[name] = temp_profile
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
    Salva i profili in PROFILES_FILE_PATH.
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
    for path in paths_to_process:
        if not os.path.exists(path):
            msg = f"ERRORE: Il percorso sorgente non esiste: '{path}'"
            logging.error(msg)
            return False, msg
        # Permetti file solo se NON è multi-percorso (es. Duckstation) E se il percorso è effettivamente un file
        if not is_multiple_paths and os.path.isfile(path):
            logging.debug(f"Single source path is a file: {path}. Allowed.")
        # Se è multi-percorso, TUTTI devono essere directory
        elif is_multiple_paths and not os.path.isdir(path):
            msg = f"ERRORE: Quando si usano percorsi multipli, tutti devono essere directory. Trovato non valido: '{path}'"
            logging.error(msg)
            return False, msg
        # Se è percorso singolo E NON è un file, DEVE essere una directory
        elif not is_multiple_paths and not os.path.isfile(path) and not os.path.isdir(path):
             msg = f"ERRORE: Il percorso sorgente singolo non è né un file né una directory valida: '{path}'"
             logging.error(msg)
             return False, msg
        # Se è multi-percorso e tutti sono directory, va bene
        elif is_multiple_paths and all(os.path.isdir(p) for p in paths_to_process):
             logging.debug("All multiple paths are valid directories.")
        # Se è percorso singolo ed è una directory, va bene
        elif not is_multiple_paths and os.path.isdir(path):
             logging.debug("Single source path is a valid directory.")


    # --- Controllo Dimensione Sorgente ---
    logging.info(f"Controllo dimensione sorgente per {len(paths_to_process)} percorso/i (Limite: {'Nessuno' if max_source_size_mb == -1 else str(max_source_size_mb) + ' MB'})...")
    total_size_bytes = 0
    if max_source_size_mb != -1:
        max_source_size_bytes = max_source_size_mb * 1024 * 1024
        for path in paths_to_process:
            # Calcola dimensione correttamente per file o directory
            size = get_directory_size(path) if os.path.isdir(path) else os.path.getsize(path)
            if size == -1: # Errore da get_directory_size
                msg = f"ERRORE: Impossibile calcolare la dimensione sorgente per '{path}'."
                logging.error(msg)
                return False, msg
            total_size_bytes += size

        current_size_mb = total_size_bytes / (1024*1024)
        logging.info(f"Dimensione totale sorgente: {current_size_mb:.2f} MB")
        if total_size_bytes > max_source_size_bytes:
            msg = (f"ERRORE: Backup annullato!\n"
                   f"Dimensione totale sorgente ({current_size_mb:.2f} MB) supera il limite ({max_source_size_mb} MB).")
            logging.error(msg)
            return False, msg
    else:
        logging.info("Controllo dimensione sorgente saltato (limite non impostato).")
    # --- FINE Controllo Dimensione ---


    # --- Creazione Directory Backup ---
    try:
        os.makedirs(profile_backup_dir, exist_ok=True)
    except Exception as e:
        msg = f"ERRORE: Impossibile creare la directory di backup '{profile_backup_dir}': {e}"
        logging.error(msg, exc_info=True)
        return False, msg
    # --- FINE Creazione Directory ---


    # --- Creazione Archivio ZIP ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_profile_name_for_zip = sanitize_foldername(profile_name) # Usa nome profilo per nome file zip
    archive_name = f"Backup_{safe_profile_name_for_zip}_{timestamp}.zip"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    logging.info(f"Avvio backup (ZIP) per '{profile_name}': Da {len(paths_to_process)} sorgente/i a '{archive_path}'")

    zip_compression = zipfile.ZIP_DEFLATED
    zip_compresslevel = 6 # Default Standard

    if compression_mode == "best":
        zip_compresslevel = 9
        logging.info("Modalità Compressione: Massima (Deflate Livello 9)")
    elif compression_mode == "fast":
        zip_compresslevel = 1
        logging.info("Modalità Compressione: Veloce (Deflate Livello 1)")
    elif compression_mode == "none":
        zip_compression = zipfile.ZIP_STORED
        zip_compresslevel = None # Non applicabile per STORED
        logging.info("Modalità Compressione: Nessuna (Store)")
    else: # "standard" or default
        logging.info("Modalità Compressione: Standard (Deflate Livello 6)")


    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zip_compression, compresslevel=zip_compresslevel) as zipf:

            # --- Logica Specifica DuckStation (SOLO se NON multi-percorso) --- START
            is_duckstation_single_file = False
            specific_mcd_file_to_backup = None
            if not is_multiple_paths:
                 single_source_path = paths_to_process[0] # C'è solo un percorso
                 if os.path.isdir(single_source_path): # Controlla solo se è una directory
                    logging.debug(f"--- Controllo DuckStation (Modalità Percorso Singolo - Directory) ---")
                    normalized_save_path = os.path.normpath(single_source_path).lower()
                    expected_suffix = os.path.join("duckstation", "memcards").lower()
                    logging.debug(f"  Percorso sorgente singolo: '{single_source_path}'")
                    logging.debug(f"  Normalizzato: '{normalized_save_path}'")
                    logging.debug(f"  Suffisso atteso: '{expected_suffix}'")

                    if normalized_save_path.endswith(expected_suffix):
                         actual_card_name = profile_name # Usa il nome profilo come base
                         prefix = "DuckStation - "
                         if profile_name.startswith(prefix):
                             actual_card_name = profile_name[len(prefix):] # Estrai nome reale carta
                         mcd_filename = actual_card_name + ".mcd"
                         potential_mcd_path = os.path.join(single_source_path, mcd_filename)
                         logging.debug(f"  Potenziale percorso MCD: '{potential_mcd_path}'")
                         if os.path.isfile(potential_mcd_path):
                             is_duckstation_single_file = True
                             specific_mcd_file_to_backup = potential_mcd_path
                             logging.info(f"Rilevato profilo DuckStation. Preparazione backup singolo file: {mcd_filename}")
                         else:
                             logging.warning(f"Il percorso assomiglia a DuckStation memcards, ma il file specifico '{mcd_filename}' non trovato in '{single_source_path}'. Eseguo backup standard della directory.")
                    else:
                         logging.debug(f"Il percorso singolo non è la directory memcards di DuckStation. Eseguo backup standard.")
                 elif os.path.isfile(single_source_path):
                      logging.debug(f"Il percorso singolo è un file '{single_source_path}'. Non applico logica DuckStation.")
                 # --- Logica Specifica DuckStation --- END

            # --- Esecuzione Backup ---
            if is_duckstation_single_file and specific_mcd_file_to_backup:
                 # Backup solo del file .mcd specifico per DuckStation
                 try:
                     mcd_arcname = os.path.basename(specific_mcd_file_to_backup) # Nome file nello zip
                     logging.debug(f"Aggiunta file singolo DuckStation: '{specific_mcd_file_to_backup}' come '{mcd_arcname}'")
                     zipf.write(specific_mcd_file_to_backup, arcname=mcd_arcname)
                     logging.info(f"Aggiunto con successo file singolo {mcd_arcname} all'archivio.")
                 except FileNotFoundError:
                     logging.error(f"  ERRORE CRITICO: File .mcd DuckStation scomparso durante il backup: '{specific_mcd_file_to_backup}'")
                     raise # Propaga l'errore per annullare il backup
                 except Exception as e_write:
                     logging.error(f"  Errore aggiunta file DuckStation '{specific_mcd_file_to_backup}' allo zip: {e_write}", exc_info=True)
                     raise # Propaga l'errore
            else:
                 # Backup Standard: Processa tutti i percorsi nella lista (o il singolo)
                 logging.debug(f"Esecuzione backup standard per {len(paths_to_process)} percorso/i.")
                 for source_path in paths_to_process:
                     logging.debug(f"Processo percorso sorgente: {source_path}")
                     if os.path.isdir(source_path):
                         # Aggiungi il contenuto della directory
                         base_folder_name = os.path.basename(source_path) # Nome della cartella (es. SAVEDATA)
                         len_source_path_parent = len(os.path.dirname(source_path)) + len(os.sep)

                         for foldername, subfolders, filenames in os.walk(source_path):
                             for filename in filenames:
                                 file_path_absolute = os.path.join(foldername, filename)
                                 # Crea arcname: base_folder_name / percorso_relativo_interno
                                 # Esempio: SAVEDATA/file1.txt
                                 relative_path = file_path_absolute[len_source_path_parent:]
                                 arcname = relative_path # Già include la base folder nel path relativo calcolato
                                 logging.debug(f"  Aggiunta file: '{file_path_absolute}' come '{arcname}'")
                                 try:
                                      zipf.write(file_path_absolute, arcname=arcname)
                                 except FileNotFoundError:
                                      logging.warning(f"  Saltato file (non trovato durante walk?): '{file_path_absolute}'")
                                 except Exception as e_write_walk:
                                      logging.error(f"  Errore aggiunta file '{file_path_absolute}' allo zip durante walk: {e_write_walk}")
                     elif os.path.isfile(source_path):
                         # Aggiungi il singolo file (caso non-Duckstation)
                         arcname = os.path.basename(source_path)
                         logging.debug(f"Aggiunta file singolo: '{source_path}' come '{arcname}'")
                         try:
                             zipf.write(source_path, arcname=arcname)
                         except FileNotFoundError:
                              logging.error(f"  ERRORE CRITICO: File sorgente singolo scomparso durante il backup: '{source_path}'")
                              raise
                         except Exception as e_write_single:
                              logging.error(f"  Errore aggiunta file singolo '{source_path}' allo zip: {e_write_single}", exc_info=True)
                              raise

        logging.info(f"Archivio di backup creato con successo: '{archive_path}'")

    except (IOError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        msg = f"ERRORE durante la creazione dell'archivio ZIP '{archive_path}': {e}"
        logging.error(msg, exc_info=True)
        # Tenta di eliminare l'archivio potenzialmente corrotto/incompleto
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
                logging.warning(f"Archivio potenzialmente incompleto eliminato: {archive_path}")
        except Exception as del_e:
            logging.error(f"Impossibile eliminare l'archivio incompleto '{archive_path}': {del_e}")
        return False, msg
    except Exception as e: # Cattura altri errori inaspettati
         msg = f"ERRORE inaspettato durante la creazione del backup ZIP '{profile_name}': {e}"
         logging.error(msg, exc_info=True)
         try:
             if os.path.exists(archive_path): os.remove(archive_path); logging.warning(f"Archivio fallito rimosso: {archive_name}")
         except Exception as rem_e: logging.error(f"Impossibile rimuovere l'archivio fallito: {rem_e}")
         return False, msg
    # --- FINE Creazione Archivio ZIP ---

    # --- Gestione Vecchi Backup ---
    deleted_files = manage_backups(profile_name, backup_base_dir, max_backups)
    deleted_msg = f" Eliminati {len(deleted_files)} backup obsoleti." if deleted_files else ""
    # --- FINE Gestione ---

    return True, f"Backup completato con successo:\n'{archive_name}'" + deleted_msg


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
# --- Restore Function ---
def perform_restore(profile_name, destination_paths, archive_to_restore_path):
    """
    Esegue il ripristino da un archivio ZIP. Gestisce un singolo percorso (str) o multipli (list).
    Restituisce (bool successo, str messaggio).
    """
    # Import necessari localmente se non sono globali nel modulo
    import zipfile
    import shutil
    logging.info(f"Avvio perform_restore per profilo: '{profile_name}'")
    logging.info(f"Archivio selezionato per ripristino: '{archive_to_restore_path}'")

    is_multiple_paths = isinstance(destination_paths, list)
    # Normalizza tutti i percorsi subito
    paths_to_process = [os.path.normpath(p) for p in (destination_paths if is_multiple_paths else [destination_paths])]

    logging.info(f"Percorso/i di destinazione target: {paths_to_process}")

    # --- Validazione Archivio ---
    if not os.path.isfile(archive_to_restore_path):
        msg = f"ERRORE: Archivio di ripristino non trovato: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    if not zipfile.is_zipfile(archive_to_restore_path):
        msg = f"ERRORE: Il file selezionato non è un archivio ZIP valido: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    # --- FINE Validazione ---

    # --- Pulizia Destinazione (prima dell'estrazione) ---
    logging.warning(f"--- Preparazione alla pulizia del/i percorso/i di destinazione prima del ripristino ---")
    for dest_path in paths_to_process:
        # Assicura che la directory genitore esista per il percorso di destinazione
        parent_dir = os.path.dirname(dest_path)
        try:
            if parent_dir and not os.path.exists(parent_dir):
                 logging.info(f"Creo directory genitore mancante: '{parent_dir}'")
                 os.makedirs(parent_dir, exist_ok=True)
        except Exception as e_mkdir:
             msg = f"ERRORE nella creazione della directory genitore '{parent_dir}' per la destinazione '{dest_path}': {e_mkdir}"
             logging.error(msg, exc_info=True)
             # Considera se interrompere qui? Per ora logga e continua.
             # return False, msg

        # Controlla cosa fare con il percorso di destinazione esistente
        if os.path.isdir(dest_path):
            logging.warning(f"Tentativo di rimuovere il contenuto della directory esistente: '{dest_path}'")
            try:
                for item in os.listdir(dest_path):
                    item_path = os.path.join(dest_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logging.debug(f"  Rimossa sottodirectory: {item_path}")
                    elif os.path.isfile(item_path):
                        os.remove(item_path)
                        logging.debug(f"  Rimosso file: {item_path}")
                logging.info(f"Contenuto di '{dest_path}' pulito con successo.")
            except Exception as e:
                msg = f"ERRORE durante la pulizia della directory di destinazione '{dest_path}': {e}"
                logging.error(msg, exc_info=True)
                return False, msg
        elif os.path.isfile(dest_path): # Gestisce il caso di destinazione file singolo (es. Duckstation .mcd)
             logging.warning(f"Tentativo di rimuovere il file singolo esistente: '{dest_path}'")
             try:
                 os.remove(dest_path)
                 logging.info(f"File singolo rimosso con successo: '{dest_path}'")
             except FileNotFoundError:
                 logging.info(f"File di destinazione '{dest_path}' non esisteva, nessuna rimozione necessaria.")
             except Exception as e:
                 msg = f"ERRORE nella rimozione del file di destinazione '{dest_path}': {e}"
                 logging.error(msg, exc_info=True)
                 return False, msg
        else:
             # Il percorso non esiste, verrà creato dall'estrazione se necessario
             logging.info(f"Percorso di destinazione '{dest_path}' non esiste.")
    logging.warning(f"--- Pulizia destinazione terminata ---")
    # --- FINE Pulizia ---

    # --- Estrazione Archivio ---
    logging.info(f"Avvio estrazione da '{archive_to_restore_path}'...")
    extracted_successfully = True
    error_messages = []

    try:
        with zipfile.ZipFile(archive_to_restore_path, 'r') as zipf:
            members = zipf.namelist()
            if not members:
                msg = "ERRORE: L'archivio ZIP è vuoto."
                logging.error(msg)
                return False, msg

            # --- Logica di estrazione differenziata ---
            if is_multiple_paths:
                # --- Estrazione Multi-Percorso ---
                logging.debug("Ripristino multi-percorso: Associazione contenuto zip ai percorsi di destinazione.")
                # Crea una mappa: nome cartella base (nello zip) -> percorso destinazione completo
                dest_map = {os.path.basename(p): p for p in paths_to_process}
                logging.debug(f"Mappa destinazioni creata: {dest_map}")

                # Verifica se lo zip contiene cartelle base (es. 'SAVEDATA/', 'SYSTEM/')
                zip_contains_base_folders = any(m.replace('/', os.sep).split(os.sep, 1)[0] in dest_map for m in members if os.sep in m.replace('/', os.sep))
                logging.debug(f"Lo zip contiene cartelle base corrispondenti alle destinazioni? {zip_contains_base_folders}")

                if not zip_contains_base_folders:
                     msg = "ERRORE: Ripristino multi-percorso fallito. L'archivio ZIP non sembra contenere le cartelle base attese (es. SAVEDATA/, SYSTEM/). Backup potenzialmente corrotto o creato in modo errato."
                     logging.error(msg)
                     logging.error(f"Membri archivio (esempio): {members[:10]}")
                     logging.error(f"Mappa destinazioni attesa: {dest_map}")
                     return False, msg

                # Estrai membro per membro nella destinazione corretta
                for member_path in members:
                    normalized_member_path = member_path.replace('/', os.sep)
                    try:
                        # Ottieni la parte base del percorso nello zip (es. 'SAVEDATA')
                        zip_base_folder = normalized_member_path.split(os.sep, 1)[0]
                    except IndexError:
                        logging.warning(f"Skipping member con formato percorso potenzialmente invalido: '{member_path}'")
                        continue

                    if zip_base_folder in dest_map:
                        target_dest_path_base = dest_map[zip_base_folder]
                        # Ottieni il percorso relativo *all'interno* della cartella base (es. 'file.txt' da 'SAVEDATA/file.txt')
                        relative_path_in_zip = normalized_member_path[len(zip_base_folder):].lstrip(os.sep)
                        # Costruisci il percorso di estrazione completo
                        full_extract_path = os.path.join(target_dest_path_base, relative_path_in_zip)

                        # Assicura che la directory per il file esista prima di estrarre
                        if member_path.endswith('/') or member_path.endswith('\\'): # È una directory nello zip
                             if relative_path_in_zip: # Evita di creare '.' se la path relativa è vuota
                                 logging.debug(f"  Creo directory da zip: {full_extract_path}")
                                 os.makedirs(full_extract_path, exist_ok=True)
                        else: # È un file
                             file_dir = os.path.dirname(full_extract_path)
                             if file_dir and not os.path.exists(file_dir): # Assicura che non sia vuota e creala se non esiste
                                 logging.debug(f"  Creo directory per file: {file_dir}")
                                 os.makedirs(file_dir, exist_ok=True)
                             try:
                                 # Estrai il singolo file sovrascrivendo se esiste
                                 with zipf.open(member_path) as source, open(full_extract_path, 'wb') as target:
                                     shutil.copyfileobj(source, target)
                                 logging.debug(f"  Estratto file {member_path} -> {full_extract_path}")
                             except Exception as e_file:
                                 msg = f"ERRORE estrazione file '{member_path}' in '{full_extract_path}': {e_file}"
                                 logging.error(msg, exc_info=True)
                                 error_messages.append(msg)
                                 extracted_successfully = False # Segna fallimento parziale
                    else:
                        # Questo membro non appartiene a nessuna delle cartelle base attese
                        msg = f"ATTENZIONE: Membro zip '{member_path}' (base: '{zip_base_folder}') non corrisponde a nessuna destinazione attesa ({list(dest_map.keys())}). Salto."
                        logging.warning(msg)
                        # Considera se trattare questo come errore: error_messages.append(msg); extracted_successfully = False

            else: # Estrazione Percorso Singolo
                # --- Estrazione Percorso Singolo --- (Usa extractall per semplicità)
                single_dest_path = paths_to_process[0]
                # Assicura che la directory di destinazione esista (dovrebbe già esistere dalla pulizia, ma ricontrolla)
                os.makedirs(single_dest_path, exist_ok=True)
                logging.debug(f"Ripristino percorso singolo: Estrazione di tutto il contenuto in '{single_dest_path}'")
                try:
                    zipf.extractall(single_dest_path)
                    logging.info(f"Contenuto estratto con successo in '{single_dest_path}'")
                except Exception as e_extractall:
                    msg = f"ERRORE durante extractall in '{single_dest_path}': {e_extractall}"
                    logging.error(msg, exc_info=True)
                    error_messages.append(msg)
                    extracted_successfully = False

    except zipfile.BadZipFile:
        msg = f"ERRORE: Il file non è un archivio ZIP valido o è corrotto: '{archive_to_restore_path}'"
        logging.error(msg)
        return False, msg
    except (IOError, OSError) as e:
         msg = f"ERRORE IO/OS durante l'estrazione: {e}"
         logging.error(msg, exc_info=True)
         error_messages.append(msg)
         extracted_successfully = False
    except Exception as e:
        msg = f"ERRORE FATALE inaspettato durante il processo di ripristino: {e}"
        logging.error(msg, exc_info=True)
        # Assicura di ritornare gli errori accumulati se presenti
        final_message = msg
        if error_messages:
            final_message += "\n\nErrori aggiuntivi riscontrati durante l'estrazione:\n" + "\n".join(error_messages)
        return False, final_message
    # --- FINE Estrazione Archivio ---

    # --- Risultato Finale ---
    if extracted_successfully:
        msg = f"Ripristino completato con successo per il profilo '{profile_name}'."
        logging.info(msg)
        final_message = msg
        if error_messages: # Aggiunge avvisi anche in caso di successo parziale
             final_message += "\n\nATTENZIONE: Sono stati riscontrati alcuni errori durante l'estrazione:\n" + "\n".join(error_messages)
        return True, final_message
    else:
        msg = f"Ripristino per il profilo '{profile_name}' fallito o completato con errori."
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

# <<< Function are_names_similar also uses sequence check >>>
def are_names_similar(name1, name2, min_match_words=2, fuzzy_threshold=88, game_title_words_for_seq=None):
    try:
        # --- Improved Cleaning ---
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

# <<< Function to guess save paths >>>
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

# <<< Function for detailed comparison cleaning >>>
def clean_for_comparison(name):
    """
    Cleans a name for more detailed comparisons, keeping numbers and spaces.
    Removes common symbols and normalizes separators.
    """
    if not isinstance(name, str): # Handles non-string input
        return ""
    # Rimuove simboli ™®©:, ma mantiene numeri, spazi, trattini
    name = re.sub(r'[™®©:]', '', name)
    # Sostituisci trattini/underscore con spazi per normalizzare i separatori
    name = re.sub(r'[-_]', ' ', name)
    # Rimuovi spazi multipli e trim
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()
    
    # <<< Funzione di ordinamento potenziata per dare priorità a match più precisi con il nome originale >>>

# <<< Final sorting function >>>
def final_sort_key(guess_tuple, outer_scope_data):
    """
    Assigns a score to a tuple (path, source, contains_saves) found by guess_save_path.
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

# --- Function to get display name from backup filename ---
def get_display_name_from_backup_filename(filename):
    """
    Removes the timestamp suffix (_YYYYMMDD_HHMMSS) from a backup file name
    for a cleaner display.

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