# save_path_finder.py
# Versione principale che gestisce l'importazione della versione corretta in base al sistema operativo

import platform
import os
import re
import logging
import config
import glob
import cancellation_utils  # Add import

# Importa thefuzz se disponibile
try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Library 'thefuzz' found and loaded.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    # Log the warning only once here at startup if missing
    logging.warning("Library 'thefuzz' not found. Fuzzy matching will be disabled.")
    logging.warning("Install it with: pip install thefuzz[speedup]")

# Determina il sistema operativo corrente
current_os = platform.system()

# Se siamo su Linux, importa la versione Linux-specific
if current_os == "Linux":
    try:
        from save_path_finder_linux import *
        logging.info("Utilizzando la versione Linux-specific del save_path_finder")
        # Termina l'esecuzione di questo file, poiché tutte le funzioni sono state importate da save_path_finder_linux
        __all__ = ['generate_abbreviations', 'matches_initial_sequence', 'are_names_similar', 
                  'guess_save_path', 'clean_for_comparison', 'final_sort_key']
    except ImportError as e:
        logging.error(f"Errore nell'importazione di save_path_finder_linux: {e}")
        logging.warning("Fallback alla versione Windows del save_path_finder")
        # In caso di errore, continua con la versione Windows come fallback

# Se non siamo su Linux o l'importazione è fallita, usa la versione Windows (default)

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
    abbreviations.add(re.sub(r'[^a-zA-Z0-9]', '', sanitized_name)) # Only alphanumeric

    # Ignore words (from config?)
    ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS',
                      {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                       'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                       'definitive', 'enhanced', 'complete', 'collection',
                       'hd', 'ultra', 'deluxe', 'game', 'year'})
    ignore_words_lower = {w.lower() for w in ignore_words}

    # --- Standard Acronym Logic ---
    words = re.findall(r'\b\w+\b', sanitized_name)
    significant_words = [w for w in words if w.lower() not in ignore_words_lower and len(w) > 1]
    significant_words_capitalized = [w for w in significant_words if w and w[0].isupper()] # Check w is not empty

    if significant_words:
        acr_all = "".join(w[0] for w in significant_words if w).upper()
        if len(acr_all) >= 2: abbreviations.add(acr_all)

    if significant_words_capitalized:
        acr_caps = "".join(w[0] for w in significant_words_capitalized if w).upper()
        if len(acr_caps) >= 2: abbreviations.add(acr_caps) # Ex: HMCC

    # --- NEW: Post-Colon Acronym Logic ---
    if ':' in name: # Use original name with :
        parts = name.split(':', 1)
        if len(parts) > 1 and parts[1].strip():
            name_after_colon = parts[1].strip()
            logging.debug(f"Found colon, analyzing part: '{name_after_colon}'")
            words_after_colon = re.findall(r'\b\w+\b', name_after_colon)
            sig_words_after_colon = [w for w in words_after_colon if w.lower() not in ignore_words_lower and len(w) > 1]
            sig_words_caps_after_colon = [w for w in sig_words_after_colon if w and w[0].isupper()]

            if sig_words_caps_after_colon:
                # Generate acronym only from capitalized words AFTER the colon
                acr_caps_after_colon = "".join(w[0] for w in sig_words_caps_after_colon if w).upper()
                if len(acr_caps_after_colon) >= 2:
                    logging.info(f"Derived abbreviation from capitalized words after colon: {acr_caps_after_colon}")
                    abbreviations.add(acr_caps_after_colon) # Ex: MCC da "Master Chief Collection"

    # --- NEW: Improved Executable Parsing ---
    if game_install_dir and os.path.isdir(game_install_dir):
        exe_base_name = None
        try:
            # ... (Logic to search for .exe as before using glob) ...
            common_suffixes = ['Win64-Shipping.exe', 'Win32-Shipping.exe', '.exe']
            found_exe_path = None
            # ... (glob loop to search for exe) ...
            # Assume it finds 'mcclauncher.exe' and puts it in found_exe_path

            # --- Executable Search Block ---
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
                     # Choose the most likely executable (e.g. not a small one?)
                     valid_exes = [e for e in executables if os.path.getsize(e) > 100*1024] # Ignore small exe?
                     if valid_exes: found_exe = os.path.basename(valid_exes[0])
                     elif executables: found_exe = os.path.basename(executables[0]) # Fallback to the first found
                     if found_exe: break
            # --- End search block ---

            if found_exe:
                logging.info(f"Found executable: {found_exe}")
                # Extract base name by removing known suffixes
                exe_base_name_temp = found_exe
                for suffix in common_suffixes + ['-Win64-Shipping', '-Win32-Shipping', '-Shipping']:
                     if exe_base_name_temp.lower().endswith(suffix.lower()): # Case insensitive
                          exe_base_name_temp = exe_base_name_temp[:-len(suffix)]
                          break
                exe_base_name_temp = re.sub(r'[-_]+$', '', exe_base_name_temp) # Remove trailing hyphens

                # <<< NEW: Remove common keywords like 'launcher' >>>
                common_exe_keywords = ['launcher', 'server', 'client', 'editor']
                processed_name = exe_base_name_temp
                keyword_removed = False
                for keyword in common_exe_keywords:
                     if processed_name.lower().endswith(keyword):
                          processed_name = processed_name[:-len(keyword)]
                          keyword_removed = True
                          break # Remove only the first occurrence found

                # Clean any remaining separators at the end
                processed_name = re.sub(r'[-_]+$', '', processed_name)

                if len(processed_name) >= 2:
                    exe_base_name = processed_name # Use processed name
                    logging.info(f"Derived abbreviation from executable: {exe_base_name}")
                    abbreviations.add(exe_base_name)
                elif len(exe_base_name_temp) >= 2:
                     # Fallback: if keyword removal made the name too short, use the original pre-removal name
                     exe_base_name = exe_base_name_temp
                     logging.info(f"Derived abbreviation from executable (fallback): {exe_base_name}")
                     abbreviations.add(exe_base_name)

        except Exception as e_exe:
            logging.warning(f"Could not derive name from executable: {e_exe}")

    # Remove None/empty and sort (optional)
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
             ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                      'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                      'definitive', 'enhanced', 'complete', 'collection',
                      'hd', 'ultra', 'deluxe', 'game', 'year'})
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
def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None, cancellation_manager=None):
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
        cancellation_manager (CancellationManager): Manager per la gestione della cancellazione.

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

    # --- Logica per Common Locations (Windows Only) ---
    user_profile = os.path.expanduser('~'); common_locations = {}
    # Assumiamo sempre Windows
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
    # Rimossa logica per Linux/macOS

    # Filtra solo percorsi validi e directory esistenti
    valid_locations = {}
    for name, path in common_locations.items():
        if path:
            try:
                # Normalizza il percorso base per un confronto sicuro
                norm_path = os.path.normpath(path)
                if os.path.isdir(norm_path):
                     valid_locations[name] = norm_path
            except (OSError, TypeError, ValueError) as e_path:
                logging.warning(f"Could not validate common location '{name}' path '{path}': {e_path}") # <-- Riga corretta

    logging.info(f"Valid common locations to search (Windows): {list(valid_locations.keys())}")
    logging.debug(f"Valid common location paths: {list(valid_locations.values())}")
    # --- FINE Logica Common Locations ---

    # --- Steam Userdata Check ---
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        logging.info(f"Checking Steam Userdata for AppID {appid} (User: {steam_id3_to_use})...")
        # Usa try-except perché os.path.join può fallire con input non validi
        # Questo è il TRY ESTERNO (livello 1 indentazione)
        try:
            user_data_folder_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
            if os.path.isdir(user_data_folder_for_id):
                base_userdata_appid = os.path.join(user_data_folder_for_id, appid)
                remote_path = os.path.join(base_userdata_appid, 'remote')
                # Chiama add_guess che gestisce controlli isdir ed errori interni
                if add_guess(remote_path, f"Steam Userdata/{steam_id3_to_use}/{appid}/remote"):
                    # Questo è il TRY INTERNO (livello 2 indentazione)
                    try: 
                        for entry in os.listdir(remote_path):
                            sub_path = os.path.join(remote_path, entry); sub_lower = entry.lower()
                            # Aggiungi check isdir qui per evitare chiamate inutili a are_names_similar
                            if os.path.isdir(sub_path) and (
                                sub_lower in common_save_subdirs_lower or
                                any(s in sub_lower for s in ['save', 'profile', 'user', 'slot']) or
                                are_names_similar(sanitized_name, entry, game_title_words_for_seq=game_title_sig_words) or
                                entry.upper() in [a.upper() for a in game_abbreviations] ):
                                    # (livello 4 indentazione)
                                    add_guess(sub_path, f"Steam Userdata/.../remote/{entry}")
                    # Questo è l'EXCEPT INTERNO (livello 2 indentazione)
                    except Exception as e_remote_sub:
                        # Logga errori durante la scansione della sottocartella 'remote'
                        # Escludi FileNotFoundError se 'remote' stessa non esiste (già gestito da add_guess)
                        if not isinstance(e_remote_sub, FileNotFoundError):
                             # (livello 4 indentazione)
                             logging.warning(f"Error scanning subfolders in Steam remote path '{remote_path}': {e_remote_sub}")
                             
                # Questa riga è DOPO il try/except interno (livello 3 indentazione)
                # Si esegue se 'remote' non esiste O dopo aver scansionato 'remote'
                add_guess(base_userdata_appid, f"Steam Userdata/{steam_id3_to_use}/{appid}/Base")
                
        # Questo è l'EXCEPT ESTERNO (livello 1 indentazione, corrisponde al TRY ESTERNO)
        except TypeError as e_join:
            # (livello 2 indentazione)
            logging.error(f"Error constructing Steam path (TypeError): {e_join}")
            
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

                # Check for cancellation
                if cancellation_manager and cancellation_manager.check_cancelled():
                    return []
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
    # Separate penalty for 'data'
    if basename_lower == 'data' and not contains_saves and not is_in_prime_user_location and not is_steam_remote:
        score -= 350 # Increased penalty specifically for 'data'
    # Penalty for other common non-save folders
    elif basename_lower in ['settings', 'config', 'cache', 'logs'] and not contains_saves and not is_in_prime_user_location and not is_steam_remote:
        score -= 150 # Keep original penalty for these

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