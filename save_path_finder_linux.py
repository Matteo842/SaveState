# save_path_finder_linux.py
import os
import re
import logging
import platform
from typing import Dict # Aggiunto import per Dict
import cancellation_utils  # Add import

if 'generate_abbreviations' not in globals():
    def generate_abbreviations(name, install_dir): return [name]
if 'are_names_similar' not in globals():
    def are_names_similar(s1, s2, **kwargs): return s1.lower() == s2.lower()
if 'clean_for_comparison' not in globals():
    def clean_for_comparison(s): return s.lower()


# Placeholder per THEFUZZ_AVAILABLE, dovrebbe essere importato o definito globalmente
# THEFUZZ_AVAILABLE = True # Rimuovi la definizione statica

# Importazione robusta di thefuzz
fuzz = None
THEFUZZ_AVAILABLE = False
try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Successfully imported 'thefuzz'. Fuzzy matching will be available for Linux path finding.")
except ImportError:
    logging.warning("'thefuzz' library not found. Fuzzy matching will be disabled for Linux path finding. Path accuracy may be affected for some games.")
    pass

# Importa il modulo config effettivo
import config # CORRETTO: import diretto
import re # Aggiunto per clean_for_comparison

# HELPER FUNCTIONS (Definite qui per garantire che siano disponibili)

def clean_for_comparison(name):
    """
    Pulisce un nome per confronti più dettagliati, mantenendo numeri e spazi.
    Rimuove simboli comuni (™, ®, ©, :) e normalizza i separatori (trattini/underscore a spazi).
    Converte in minuscolo e normalizza gli spazi.
    Questo approccio è allineato con la versione Windows per una maggiore coerenza.
    """
    if not isinstance(name, str):  # Gestisce input non stringa
        return ""
    
    # Rimuove simboli ™®©:, ma mantiene numeri, spazi, trattini, ecc.
    # Questo è meno aggressivo della precedente versione Linux.
    name_cleaned = re.sub(r'[™®©:]', '', name)
    
    # Sostituisci trattini/underscore con spazi per normalizzare i separatori
    name_cleaned = re.sub(r'[-_]', ' ', name_cleaned)
    
    # Rimuovi spazi multipli e applica strip() per spazi iniziali/finali
    name_cleaned = re.sub(r'\s+', ' ', name_cleaned).strip()
    
    # Converte in minuscolo come ultimo passo
    return name_cleaned.lower()

def generate_abbreviations(game_name_raw, game_install_dir_raw=None):
    """
    Genera una lista di possibili abbreviazioni/nomi alternativi per il gioco,
    allineandosi maggiormente alla logica della versione Windows.
    Utilizza la funzione clean_for_comparison (stile Windows) definita in questo modulo.
    """
    abbreviations = set()
    if not game_name_raw:
        return []

    # 1. Pulizia iniziale e variazioni di base del nome
    
    # Nome base pulito secondo la logica Windows (tramite la nostra clean_for_comparison aggiornata)
    base_name_cleaned = clean_for_comparison(game_name_raw)
    if base_name_cleaned:
        abbreviations.add(base_name_cleaned)

        # Nome senza spazi (es. "grandtheftauto")
        name_no_space = base_name_cleaned.replace(' ', '')
        if name_no_space != base_name_cleaned and len(name_no_space) > 1:
            abbreviations.add(name_no_space)

        # Solo alfanumerico (es. "grandtheftautoiv" -> "grandtheftautoiv")
        # La nostra clean_for_comparison attuale non rimuove tutti i non-alphanum,
        # ma solo ™®©:. Se volessimo una versione solo alfanumerica qui,
        # dovremmo aggiungerla. Windows fa: re.sub(r'[^a-zA-Z0-9]', '', sanitized_name)
        # Per ora, la omettiamo per mantenere la modifica più semplice e vedere l'effetto
        # delle altre modifiche. Potremo aggiungerla se necessario.
        # name_alphanum_only = re.sub(r'[^a-z0-9]', '', base_name_cleaned) # base_name_cleaned è già lower
        # if name_alphanum_only != name_no_space and name_alphanum_only != base_name_cleaned and len(name_alphanum_only) > 1:
        # abbreviations.add(name_alphanum_only)

    # 2. Logica per Acronimi basata su parole significative (stile Windows)
    ignore_words_default = {
        'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty',
        'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete',
        'collection', 'hd', 'ultra', 'deluxe', 'game', 'year', 'directors', 'cut'
    }
    ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default)
    # Assicuriamoci che ignore_words siano in minuscolo per il confronto
    ignore_words_lower = {w.lower() for w in ignore_words}

    # Usiamo base_name_cleaned che è già stato processato (spazi normalizzati, minuscolo)
    words = base_name_cleaned.split(' ') # Splitta per spazio singolo

    significant_words = [w for w in words if w and w not in ignore_words_lower and len(w) > 1]
    
    # Per 'significant_words_capitalized', dovremmo lavorare sul nome prima della conversione in minuscolo
    # fatta da clean_for_comparison.
    # Facciamo una pulizia parziale del nome originale per questo scopo:
    name_for_caps_check = re.sub(r'[™®©:]', '', game_name_raw) # Rimuovi simboli base
    name_for_caps_check = re.sub(r'[-_]', ' ', name_for_caps_check) # Normalizza separatori
    name_for_caps_check = re.sub(r'\s+', ' ', name_for_caps_check).strip() # Normalizza spazi
    
    # Dividi in parole e mantieni solo quelle significative
    camel_case_words = [w for w in name_for_caps_check.split(' ') 
                       if w and w.lower() not in ignore_words_lower and len(w) > 1]
    
    significant_words_capitalized = [
        w for w in camel_case_words if w and w.lower() not in ignore_words_lower and len(w) > 1 and w[0].isupper()
    ]

    if significant_words:
        acr_all = "".join(w[0] for w in significant_words) # Sarà già minuscolo
        if len(acr_all) >= 2:
            abbreviations.add(acr_all)

    if significant_words_capitalized:
        # L'acronimo da parole capitalizzate dovrebbe essere MAIUSCOLO come in Windows
        acr_caps = "".join(w[0] for w in significant_words_capitalized).upper()
        if len(acr_caps) >= 2:
            abbreviations.add(acr_caps)
            abbreviations.add(acr_caps.lower()) # Aggiungiamo anche la versione minuscola per Linux

    # 3. Abbreviazione dalla directory di installazione (logica Linux esistente, leggermente adattata)
    if game_install_dir_raw and os.path.isdir(game_install_dir_raw): # Aggiunto check os.path.isdir
        install_dir_basename = os.path.basename(game_install_dir_raw)
        # Pulisci il basename della directory di installazione nello stesso modo del nome del gioco
        cleaned_install_dir_name = clean_for_comparison(install_dir_basename)
        
        if cleaned_install_dir_name and len(cleaned_install_dir_name) > 1 and cleaned_install_dir_name != base_name_cleaned:
            abbreviations.add(cleaned_install_dir_name)
            
            # Versione senza spazi del nome della directory di installazione
            no_spaces_install_dir = cleaned_install_dir_name.replace(" ", "")
            if no_spaces_install_dir != cleaned_install_dir_name and len(no_spaces_install_dir) > 1:
                abbreviations.add(no_spaces_install_dir)

    # 4. Logica per la prima parola (dalla versione Linux, ma su significant_words)
    if significant_words and len(significant_words[0]) > 1 : # Assicura che la prima parola significativa sia abbastanza lunga
        abbreviations.add(significant_words[0])


    # 5. Aggiungi variante CamelCase (senza spazi, mantenendo maiuscole iniziali)
    # Questo aiuta con casi come "FTL__Faster_Than_Light" -> "FasterThanLight"
    name_for_camel_case = re.sub(r'[™®©:]', '', game_name_raw)  # Rimuovi simboli
    name_for_camel_case = re.sub(r'[-_]', ' ', name_for_camel_case)  # Normalizza separatori
    name_for_camel_case = re.sub(r'\s+', ' ', name_for_camel_case).strip()  # Normalizza spazi
    
    # Dividi in parole e mantieni solo quelle significative
    camel_case_words = [w for w in name_for_camel_case.split(' ') 
                       if w and w.lower() not in ignore_words_lower and len(w) > 1]
    
    # Crea versione CamelCase: prima lettera maiuscola di ogni parola, resto minuscolo
    if camel_case_words:
        # Versione 1: Con tutte le parole (es. "FtlFasterThanLight")
        camel_case_variant = ''.join(w[0].upper() + w[1:].lower() for w in camel_case_words)
        if len(camel_case_variant) >= 2:
            abbreviations.add(camel_case_variant)
            # Aggiungi anche una versione tutta minuscola
            abbreviations.add(camel_case_variant.lower())
            
        # Versione 2: Senza la prima parola se sembra un acronimo (es. "FasterThanLight" senza "Ftl")
        # Questo aiuta con giochi come "FTL__Faster_Than_Light" dove il salvataggio è in "FasterThanLight"
        if len(camel_case_words) > 1 and len(camel_case_words[0]) <= 4:  # Potenziale acronimo
            # Controlla se la prima parola è un acronimo (tutte maiuscole o 2-4 caratteri)
            first_word = camel_case_words[0]
            if first_word.isupper() or len(first_word) <= 4:
                # Crea versione senza la prima parola
                camel_case_no_prefix = ''.join(w[0].upper() + w[1:].lower() for w in camel_case_words[1:])
                if len(camel_case_no_prefix) >= 2:
                    abbreviations.add(camel_case_no_prefix)
                    # Aggiungi anche una versione tutta minuscola
                    abbreviations.add(camel_case_no_prefix.lower())
    
    # 6. Filtro finale e ordinamento (come in Windows)
    # Rimuovi None/stringhe vuote e abbreviazioni troppo corte (es. < 2 caratteri)
    final_abbreviations = {abbr for abbr in abbreviations if abbr and len(abbr) >= 2}
    
    # Ordina per lunghezza (più lunghe prima), poi alfabeticamente come tie-breaker
    # Aggiungere un ordinamento alfabetico secondario può aiutare per la consistenza nei test.
    sorted_list = sorted(list(final_abbreviations), key=lambda x: (-len(x), x))

    # logging.debug(f"Generated abbreviations for '{game_name_raw}' (cleaned: '{base_name_cleaned}'): {sorted_list}")
    return sorted_list


def matches_initial_sequence(folder_name, game_title_words):
    """
    Controlla se folder_name (es. "ME") CORRISPONDE ESATTAMENTE alla sequenza
    delle iniziali di game_title_words (es. ["Metro", "Exodus"]).
    Questa è una funzione di supporto per are_names_similar, stile Windows.
    """
    if not folder_name or not game_title_words:
        return False
    try:
        # Estrai iniziali MAIUSCOLE dalle parole significative del titolo del gioco
        word_initials = [word[0].upper() for word in game_title_words if word and word[0].isascii()] # Aggiunto isascii per sicurezza
        expected_sequence = "".join(word_initials)
        
        # Confronta (insensibile al maiuscolo/minuscolo) il nome della cartella con la sequenza attesa
        return folder_name.upper() == expected_sequence
    except Exception as e:
        logging.error(f"Error in matches_initial_sequence ('{folder_name}', {game_title_words}): {e}")
        return False

def are_names_similar(name1_game_variant, name2_path_component, 
                      min_match_words=2, # Dalla versione Windows
                      fuzzy_threshold=88, # Dalla versione Windows
                      game_title_sig_words_for_seq=None): # Dalla versione Windows, parole per il check sequenza iniziali
    """
    Confronta due nomi per similarità usando una logica più vicina alla versione Windows.
    name1_game_variant: Una variante del nome del gioco (già pulita o un'abbreviazione).
    name2_path_component: Un componente del percorso (verrà pulito internamente).
    game_title_sig_words_for_seq: Lista di parole significative del titolo del gioco originale 
                                   per il controllo della sequenza delle iniziali.
    """
    global THEFUZZ_AVAILABLE, fuzz # Assicurati che siano accessibili

    # 0. Pulizia dei nomi
    # name1_game_variant è assunto essere già pulito (es. da generate_abbreviations) o essere una forma base.
    # name2_path_component deve essere pulito.
    # Usiamo la clean_for_comparison allineata a Windows.
    
    pattern_alphanum_space = r'[^a-zA-Z0-9\s]'
    
    temp_clean_name1 = re.sub(pattern_alphanum_space, '', str(name1_game_variant)).lower()
    temp_clean_name1 = re.sub(r'\s+', ' ', temp_clean_name1).strip()

    temp_clean_name2 = re.sub(pattern_alphanum_space, '', str(name2_path_component)).lower()
    temp_clean_name2 = re.sub(r'\s+', ' ', temp_clean_name2).strip()

    if not temp_clean_name1 or not temp_clean_name2:
        return False

    # Carica ignore_words da config, come fa la versione Windows
    ignore_words_default = {'a', 'an', 'the', 'of', 'and'} # Default più piccolo per questo specifico confronto
    similarity_ignore_words_config = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default)
    ignore_words_lower = {w.lower() for w in similarity_ignore_words_config}

    # Estrai parole significative (solo lettere/numeri)
    pattern_words = r'\b[a-zA-Z0-9]+\b' # Modificato per includere numeri e non underscore
    words1 = {w for w in re.findall(pattern_words, temp_clean_name1) if w not in ignore_words_lower and len(w) > 1}
    words2 = {w for w in re.findall(pattern_words, temp_clean_name2) if w not in ignore_words_lower and len(w) > 1}

    # 1. Check parole comuni
    common_words = words1.intersection(words2)
    if len(common_words) >= min_match_words:
        return True

    # 2. Check prefix (starts_with) / uguaglianza senza spazi
    name1_no_space = temp_clean_name1.replace(' ', '')
    name2_no_space = temp_clean_name2.replace(' ', '')
    MIN_PREFIX_LEN = 3 # Dalla versione Windows

    if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
        if name1_no_space == name2_no_space:
            # logging.debug(f"ARE_NAMES_SIMILAR (Linux): No-space exact match for '{name1_no_space}' -> True")
            return True
        # Verifica se uno è prefisso dell'altro (con una lunghezza minima ragionevole per il prefisso)
        # La versione Windows controlla if name1_no_space.startswith(name2_no_space) OR viceversa.
        # E anche len(nameX_no_space) > len(nameY_no_space) per evitare match parziali troppo corti
        if len(name1_no_space) > len(name2_no_space) and name1_no_space.startswith(name2_no_space) and len(name2_no_space) >= max(MIN_PREFIX_LEN, len(name1_no_space) // 2):
            # logging.debug(f"ARE_NAMES_SIMILAR (Linux): Prefix match (1 starts with 2) for '{name1_no_space}' vs '{name2_no_space}' -> True")
            return True
        if len(name2_no_space) > len(name1_no_space) and name2_no_space.startswith(name1_no_space) and len(name1_no_space) >= max(MIN_PREFIX_LEN, len(name2_no_space) // 2):
            return True
            
    # 3. Check Sequenza Iniziali (logica Windows)
    if game_title_sig_words_for_seq and len(temp_clean_name2) <= 5: # Applica solo a nomi di cartella corti (tipici acronimi)
        if matches_initial_sequence(name2_path_component, game_title_sig_words_for_seq):
            return True

    # 4. Fuzzy Matching
    if THEFUZZ_AVAILABLE and fuzzy_threshold > 0 and fuzzy_threshold <= 100:
        try:
            ratio = fuzz.token_set_ratio(temp_clean_name1, temp_clean_name2)
            if ratio >= fuzzy_threshold:
                return True
        except Exception as e_fuzz:
            logging.error(f"Error during fuzzy matching with thefuzz: {e_fuzz}")

    # Fallback se THEFUZZ non è disponibile (la versione Linux aveva un confronto esatto)
    # Manteniamo un confronto esatto dei nomi puliti come ultima risorsa.
    if not THEFUZZ_AVAILABLE and temp_clean_name1 == temp_clean_name2:
        # logging.debug(f"ARE_NAMES_SIMILAR (Linux): THEFUZZ UNAVAILABLE. Exact match for '{temp_clean_name1}' -> True")
        return True
        
    # logging.debug(f"ARE_NAMES_SIMILAR (Linux): No similarity found for '{name1_game_variant}' vs '{name2_path_component}' (Cleaned: '{temp_clean_name1}' vs '{temp_clean_name2}')")
    return False


def _scan_dir_for_save_evidence_linux(dir_path: str, max_files_to_scan: int, common_save_extensions: set, common_save_filenames_lower: set) -> tuple[bool, int]:
    """
    Scansiona una directory per trovare prove di file di salvataggio.
    Limita il numero di file scansionati per performance.

    Args:
        dir_path: Il percorso completo della directory da scansionare.
        max_files_to_scan: Il numero massimo di file da scansionare nella directory.
        common_save_extensions: Un set di estensioni di file di salvataggio comuni.
        common_save_filenames_lower: Un set di nomi di file di salvataggio comuni in minuscolo.

    Returns:
        Tuple[bool, int]: (has_evidence, save_file_count_for_bonus)
                          has_evidence è True se almeno un file sospetto è trovato.
                          save_file_count_for_bonus è il numero di file che corrispondono.
    """
    has_evidence = False
    save_file_count = 0
    files_scanned_count = 0

    try:
        for item_name in os.listdir(dir_path):
            if files_scanned_count >= max_files_to_scan:
                logging.debug(f"_scan_dir_for_save_evidence_linux: Reached max files to scan ({max_files_to_scan}) in '{dir_path}'")
                break

            item_path = os.path.join(dir_path, item_name)
            if os.path.isfile(item_path):
                files_scanned_count += 1
                item_name_lower = item_name.lower()
                _, ext_lower = os.path.splitext(item_name_lower)
                ext_lower = ext_lower.lstrip('.')

                is_matching_file = False
                if ext_lower in common_save_extensions:
                    is_matching_file = True
                elif item_name_lower in common_save_filenames_lower:
                    is_matching_file = True
                
                if is_matching_file:
                    has_evidence = True
                    save_file_count += 1
                    # Non uscire subito, conta tutti i file corrispondenti fino al limite
                    # per avere un'idea migliore se la cartella è 'piena' di salvataggi.

    except OSError as e:
        logging.warning(f"_scan_dir_for_save_evidence_linux: OSError while listing dir '{dir_path}': {e}")
        return False, 0
    
    # logging.debug(f"_scan_dir_for_save_evidence_linux: Path '{dir_path}', Evidence: {has_evidence}, CountForBonus: {save_file_count}")
    return has_evidence, save_file_count


def _is_potential_save_dir(dir_path, game_name_clean, game_abbreviations_lower, linux_common_save_subdirs_lower, min_save_files_for_bonus_linux):
    """
    Determina se una directory è un potenziale percorso di salvataggio.
    Più restrittivo: richiede una corrispondenza del nome del gioco/abbreviazione, 
    o una corrispondenza con nomi comuni di directory di salvataggio, o forte evidenza da file.

    Args:
        dir_path: Il percorso completo della directory.
        game_name_clean: Il nome del gioco pulito.
        game_abbreviations_lower: Un set di abbreviazioni del gioco in minuscolo.
        linux_common_save_subdirs_lower: Un set di nomi di directory di salvataggio comuni in minuscolo.
        min_save_files_for_bonus_linux: Il numero minimo di file di salvataggio per il bonus.

    Returns:
        Tuple[bool, bool]: (is_potential, has_actual_save_files_for_bonus)
    """
    is_potential = False
    has_actual_save_files_for_bonus = False

    # 1. Controllo basato sul nome della directory e del gioco
    #    Un nome di directory è promettente se contiene un'abbreviazione del gioco
    #    o se è una directory di salvataggio comune nota.
    name_match_game_or_common_save_dir = False
    for abbr in game_abbreviations_lower: 
        # Controllo 1: Corrispondenza esatta del frammento o se abbr ha già spazi
        if abbr in dir_path.lower(): # Controllo di sottostringa
            name_match_game_or_common_save_dir = True
            logging.debug(f"_is_potential_save_dir: Name match (game fragment '{abbr}') for '{dir_path}'")
            break
        
        # Controllo 2: Se abbr contiene underscore, prova a confrontarlo con spazi in dir_path
        # Esempio: abbr="cyberpunk_2077", dir_path="cyberpunk 2077"
        if '_' in abbr:
            abbr_with_spaces = abbr.replace('_', ' ')
            if abbr_with_spaces in dir_path.lower():
                name_match_game_or_common_save_dir = True
                logging.debug(f"_is_potential_save_dir: Name match (game fragment '{abbr}' as '{abbr_with_spaces}') for '{dir_path}'")
                break

    if not name_match_game_or_common_save_dir:
        if dir_path.lower() in linux_common_save_subdirs_lower:
            name_match_game_or_common_save_dir = True
            logging.debug(f"_is_potential_save_dir: Name match (common save dir '{dir_path.lower()}') for '{dir_path}'")
    
    # 2. Controllo basato sull'evidenza dei file (eseguito se il nome matcha o come fallback)
    #    Scansiona la directory per file che sembrano salvataggi.
    has_save_files_evidence, save_file_count_for_bonus = _scan_dir_for_save_evidence_linux(dir_path, 100, set(), set())

    if name_match_game_or_common_save_dir:
        is_potential = True # Se il nome matcha, è potenziale indipendentemente dai file (per ora, lo score lo gestirà)
        if save_file_count_for_bonus >= min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True
    elif has_save_files_evidence: # Se il nome non matcha, ma ci sono file sospetti
        is_potential = True # È potenziale grazie ai file
        if save_file_count_for_bonus >= min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True

    # Logica di log più chiara
    if is_potential:
        log_msg = f"_is_potential_save_dir: Determined '{dir_path}' as POTENTIAL. "
        if name_match_game_or_common_save_dir:
            log_msg += "Reason: Name Match. "
        if has_save_files_evidence:
            log_msg += f"Reason: File Evidence (bonus files: {save_file_count_for_bonus}). "
        logging.debug(log_msg.strip())
    else:
        logging.debug(f"_is_potential_save_dir: Determined '{dir_path}' as NOT potential.")
    return is_potential, has_actual_save_files_for_bonus

# Variabili globali per il modulo (caricate da config)
_guesses_data = {}
_checked_paths = set()
_game_name_cleaned = ""
_game_abbreviations = []
_game_abbreviations_lower = set()
_game_abbreviations_upper = set()
_other_cleaned_game_names = set()
_other_game_abbreviations = set()
_penalty_no_game_name_in_path = -600
_current_steam_app_id = None
_game_title_original_sig_words_for_seq = []

# Costanti di punteggio e profondità (internalizzate)
_score_game_name_match = 1200
_score_company_name_match = 150
_score_save_dir_match = 400
_score_has_save_files = 700
_score_perfect_match_bonus = 600
_score_steam_userdata_bonus = 1000
_score_proton_path_bonus = 800
_score_wine_generic_bonus = 200 

_penalty_generic_engine_dir = -250
_penalty_unrelated_game_in_path = -800
_penalty_depth_base = -25
_penalty_banned_path_segment = -1000
_penalty_known_irrelevant_company = -200 # Penalità per aziende note ma non per il gioco corrente
 
_max_depth_steam_userdata = 5
_max_depth_proton_compatdata = 7
_max_depth_generic = 4
_min_save_files_for_bonus_linux = 2
_fuzzy_threshold_path_match = 85
_fuzzy_threshold_basename_match = 90

# Bonus specifici per tipo di sorgente (internalizzati)
_score_installdir_bonus = 50 
_score_xdg_data_home_bonus = 30
_score_xdg_config_home_bonus = 20
_score_publisher_match_bonus = 10
_score_wine_prefix_generic_bonus = 15 

# Set di nomi di altri giochi installati (puliti)
_other_cleaned_game_names = set()

# Variabile per i percorsi noti, caricata da config
_linux_known_save_locations: Dict[str, str] = {} 

def _initialize_globals_from_config(game_name_raw, game_install_dir_raw, installed_steam_games_dict=None, steam_app_id_raw=None):
    """Carica le configurazioni e inizializza le variabili globali del modulo."""
    global _game_name_cleaned, _game_abbreviations, _game_abbreviations_lower, _game_abbreviations_upper
    global _known_companies_lower, _linux_common_save_subdirs_lower, _linux_banned_path_fragments_lower
    global _common_save_extensions, _common_save_filenames_lower, _proton_user_path_fragments
    global _other_cleaned_game_names # Aggiunto _other_cleaned_game_names
    global _max_files_to_scan_linux_hint, _min_save_files_for_bonus_linux # Nuovi globali
    global _max_sub_items_to_scan_linux, _max_shallow_explore_depth_linux # Nuovi globali
    global _linux_known_save_locations # << RIPRISTINATA
    global _current_steam_app_id # Added
    global _game_title_original_sig_words_for_seq

    _game_name_cleaned = clean_for_comparison(game_name_raw)
    
    # --- INIZIO Logica per _game_title_original_sig_words_for_seq ---
    # Per 'game_title_original_sig_words_for_seq', abbiamo bisogno delle parole con le maiuscole originali (o quasi)
    # e senza le 'ignore_words'.
    # 1. Pulizia leggera del nome raw, mantenendo le maiuscole
    temp_name_for_seq = re.sub(r'[™®©:]', '', game_name_raw)
    temp_name_for_seq = re.sub(r'[-_]', ' ', temp_name_for_seq)
    temp_name_for_seq = re.sub(r'\s+', ' ', temp_name_for_seq).strip()
    original_game_words_with_case = temp_name_for_seq.split(' ')

    # 2. Carica ignore_words (le stesse usate in generate_abbreviations)
    ignore_words_default_for_seq = { # Potrebbe essere lo stesso set di generate_abbreviations
        'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty',
        'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete',
        'collection', 'hd', 'ultra', 'deluxe', 'game', 'year', 'directors', 'cut'
    }
    ignore_words_for_seq_config = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default_for_seq)
    ignore_words_for_seq_lower = {w.lower() for w in ignore_words_for_seq_config}

    # 3. Filtra per ottenere le parole significative, mantenendo il case originale
    _game_title_original_sig_words_for_seq = [
        word for word in original_game_words_with_case 
        if word and word.lower() not in ignore_words_for_seq_lower # Confronto in minuscolo per ignore
        # and len(word) > 1 # La versione Windows non ha questo len > 1 per le parole per la sequenza
    ]
    if not _game_title_original_sig_words_for_seq and _game_name_cleaned: # Fallback se tutto viene filtrato
        _game_title_original_sig_words_for_seq = _game_name_cleaned.split(' ')

    logging.debug(f"Calculated _game_title_original_sig_words_for_seq: {_game_title_original_sig_words_for_seq}")
    # --- FINE Logica per _game_title_original_sig_words_for_seq ---
    
    _game_abbreviations = generate_abbreviations(game_name_raw)
    if _game_name_cleaned not in _game_abbreviations:
        _game_abbreviations.append(_game_name_cleaned)
    _game_abbreviations_lower = {clean_for_comparison(abbr) for abbr in _game_abbreviations}
    _game_abbreviations_upper = {abbr.upper() for abbr in _game_abbreviations}

    _known_companies_lower = [kc.lower() for kc in getattr(config, 'COMMON_PUBLISHERS', [])]
    _linux_common_save_subdirs_lower = {csd.lower() for csd in getattr(config, 'LINUX_COMMON_SAVE_SUBDIRS', [])}
    _linux_banned_path_fragments_lower = {bps.lower() for bps in getattr(config, 'LINUX_BANNED_PATH_FRAGMENTS', getattr(config, 'BANNED_FOLDER_NAMES_LOWER', []))}
    _common_save_extensions = {e.lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    _common_save_filenames_lower = {f.lower() for f in getattr(config, 'COMMON_SAVE_FILENAMES', set())}
    _proton_user_path_fragments = getattr(config, 'PROTON_USER_PATH_FRAGMENTS', [])
    
    # Ripristino caricamento di _linux_known_save_locations
    _linux_known_save_locations.clear() # Assicurati che sia vuoto prima di ricaricare
    raw_locations = getattr(config, 'LINUX_KNOWN_SAVE_LOCATIONS', []) 
    if isinstance(raw_locations, dict):
        for desc, path_val in raw_locations.items():
            _linux_known_save_locations[desc] = os.path.expanduser(path_val)
    elif isinstance(raw_locations, list):
        for item in raw_locations:
            if isinstance(item, tuple) and len(item) == 2:
                desc, path_val = item
                _linux_known_save_locations[desc] = os.path.expanduser(path_val)
            elif isinstance(item, str):
                # Crea una descrizione di fallback se non fornita
                desc = item.replace("~", "Home").replace("/.", "/").strip("/").replace("/", "_")
                _linux_known_save_locations[desc if desc else "UnknownLocation"] = os.path.expanduser(item)
    # Fine ripristino caricamento

    # Carica le penalità da config.py
    global _penalty_no_game_name_in_path, _penalty_unrelated_game_in_path
    _penalty_no_game_name_in_path = getattr(config, 'PENALTY_NO_GAME_NAME_IN_PATH', -600)
    _penalty_unrelated_game_in_path = getattr(config, 'PENALTY_UNRELATED_GAME_IN_PATH', -800)

    # Popola i set per "altri giochi"
    global _other_cleaned_game_names, _other_game_abbreviations
    _other_cleaned_game_names = set()
    _other_game_abbreviations = set()

    all_known_games_raw_list = getattr(config, 'ALL_KNOWN_GAME_NAMES_RAW', [])
    current_game_name_cleaned_lower = _game_name_cleaned.lower() # Assumendo che _game_name_cleaned sia già definito sopra
    current_game_abbreviations_lower = {abbr.lower() for abbr in _game_abbreviations} # Assumendo _game_abbreviations definito sopra

    logging.debug(f"Initializing 'other games' lists. Current game: '{current_game_name_cleaned_lower}', Current abbrs: {current_game_abbreviations_lower}")
    logging.debug(f"ALL_KNOWN_GAME_NAMES_RAW from config: {all_known_games_raw_list}")

    for other_game_name_raw_entry in all_known_games_raw_list:
        if not isinstance(other_game_name_raw_entry, str):
            logging.warning(f"Skipping non-string entry in ALL_KNOWN_GAME_NAMES_RAW: {other_game_name_raw_entry}")
            continue

        other_game_cleaned = clean_for_comparison(other_game_name_raw_entry)
        other_game_cleaned_lower = other_game_cleaned.lower()

        if other_game_cleaned_lower == current_game_name_cleaned_lower:
            continue # Non aggiungere il gioco corrente alla lista degli "altri giochi"

        _other_cleaned_game_names.add(other_game_cleaned_lower)
        
        temp_other_abbrs = generate_abbreviations(other_game_name_raw_entry) # Non c'è bisogno dell'install_dir qui
        for other_abbr in temp_other_abbrs:
            other_abbr_lower = other_abbr.lower()
            if other_abbr_lower not in current_game_abbreviations_lower and \
               other_abbr_lower != current_game_name_cleaned_lower:
                _other_game_abbreviations.add(other_abbr_lower)

    logging.debug(f"_other_cleaned_game_names initialized to: {_other_cleaned_game_names}")
    logging.debug(f"_other_game_abbreviations initialized to: {_other_game_abbreviations}")

    # Le righe seguenti (caricamento di _max_files_to_scan_linux_hint, ecc.) dovrebbero rimanere invariate
    
    # Nuovi globali caricati da config
    _max_files_to_scan_linux_hint = getattr(config, 'MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT', 100)
    _min_save_files_for_bonus_linux = getattr(config, 'MIN_SAVE_FILES_FOR_BONUS_LINUX', 2)
    _max_sub_items_to_scan_linux = getattr(config, 'MAX_SUB_ITEMS_TO_SCAN_LINUX', 50)
    _max_shallow_explore_depth_linux = getattr(config, 'MAX_SHALLOW_EXPLORE_DEPTH_LINUX', 1)

    _current_steam_app_id = steam_app_id_raw # Added

    logging.debug(f"Linux Path Finder Initialized. Game: '{_game_name_cleaned}', Abbreviations: {_game_abbreviations_lower}")

def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None, cancellation_manager=None):
    # Reset global configuration variables at start of each search
    global _game_name_cleaned, _game_abbreviations, _game_abbreviations_lower, _game_abbreviations_upper
    global _known_companies_lower, _linux_common_save_subdirs_lower, _linux_banned_path_fragments_lower
    global _common_save_extensions, _common_save_filenames_lower, _proton_user_path_fragments
    global _other_cleaned_game_names, _other_game_abbreviations
    global _max_files_to_scan_linux_hint, _min_save_files_for_bonus_linux
    global _max_sub_items_to_scan_linux, _max_shallow_explore_depth_linux
    global _linux_known_save_locations
    global _current_steam_app_id
    global _game_title_original_sig_words_for_seq
    global _guesses_data, _checked_paths
    
    _game_name_cleaned = None
    _game_abbreviations = []
    _game_abbreviations_lower = set()
    _game_abbreviations_upper = set()
    _known_companies_lower = set()
    _linux_common_save_subdirs_lower = set()
    _linux_banned_path_fragments_lower = set()
    _common_save_extensions = set()
    _common_save_filenames_lower = set()
    _proton_user_path_fragments = []
    _other_cleaned_game_names = set()
    _other_game_abbreviations = set()
    _max_files_to_scan_linux_hint = 0
    _min_save_files_for_bonus_linux = 0
    _max_sub_items_to_scan_linux = 0
    _max_shallow_explore_depth_linux = 0
    _linux_known_save_locations = {}
    _current_steam_app_id = None
    _game_title_original_sig_words_for_seq = []
    _guesses_data = {}
    _checked_paths = set()
    
    # Initialize fresh state for this search
    _initialize_globals_from_config(game_name, game_install_dir, installed_steam_games_dict, appid)
    
    logging.info(f"LINUX_GUESS_SAVE_PATH: Starting search for '{game_name}' (AppID: {appid})")

    # 1. Steam Userdata (Priorità Alta)
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        try:
            user_data_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
            if os.path.isdir(user_data_for_id):
                app_specific_userdata = os.path.join(user_data_for_id, appid)
                if os.path.isdir(app_specific_userdata):
                    _add_guess(_guesses_data, _checked_paths, app_specific_userdata, "Steam Userdata/AppID_Base", False, _game_abbreviations_lower, _current_steam_app_id, _linux_common_save_subdirs_lower, _other_cleaned_game_names, _other_game_abbreviations, _game_name_cleaned)
                    remote_path = os.path.join(app_specific_userdata, 'remote')
                    if os.path.isdir(remote_path):
                        _add_guess(_guesses_data, _checked_paths, remote_path, f"Steam Userdata/AppID_Base/remote", False, _game_abbreviations_lower, _current_steam_app_id, _linux_common_save_subdirs_lower, _other_cleaned_game_names, _other_game_abbreviations, _game_name_cleaned)
                        # Esplora un livello dentro 'remote'
                        _search_recursive(_guesses_data, _checked_paths, remote_path, 0, _max_depth_steam_userdata, "Steam Userdata/AppID_Base/remote", cancellation_manager,
                          game_abbreviations_lower=_game_abbreviations_lower,
                          linux_common_save_subdirs_lower=_linux_common_save_subdirs_lower,
                          min_save_files_for_bonus_linux=_min_save_files_for_bonus_linux,
                          game_name_cleaned=_game_name_cleaned,
                          known_companies_lower=_known_companies_lower,
                          fuzzy_threshold_basename_match=_fuzzy_threshold_basename_match,
                          fuzzy_threshold_path_match=_fuzzy_threshold_path_match,
                          game_title_original_sig_words_for_seq=_game_title_original_sig_words_for_seq,
                          max_sub_items_to_scan_linux=_max_sub_items_to_scan_linux,
                          current_steam_app_id=_current_steam_app_id,
                          other_cleaned_game_names=_other_cleaned_game_names,
                          other_game_abbreviations=_other_game_abbreviations)
        except Exception as e:
            logging.error(f"LINUX_GUESS_SAVE_PATH: Error processing Steam Userdata: {e}")

    # 2. Proton Compatdata (per giochi Windows via Proton)
    if is_steam_game and appid:
        # Questi percorsi base dovrebbero essere in config.LINUX_KNOWN_SAVE_LOCATIONS
        # o costruiti dinamicamente se steam_path è noto
        steam_base_paths_for_compat = [
            os.path.join(os.path.expanduser("~"), ".steam", "steam"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "Steam"), # Percorso alternativo
            # Considera anche percorsi Flatpak per Steam se necessario
            # os.path.join(os.path.expanduser("~"), ".var/app/com.valvesoftware.Steam/data/Steam")
        ]
        for steam_base in steam_base_paths_for_compat:
            compatdata_path = os.path.join(steam_base, 'steamapps', 'compatdata', appid, 'pfx')
            if os.path.isdir(compatdata_path):
                _add_guess(_guesses_data, _checked_paths, compatdata_path, f"Proton Prefix ({appid})", False, _game_abbreviations_lower, _current_steam_app_id, _linux_common_save_subdirs_lower, _other_cleaned_game_names, _other_game_abbreviations, _game_name_cleaned)
                for fragment in _proton_user_path_fragments: # Da config
                    proton_save_path = os.path.join(compatdata_path, fragment)
                    if os.path.isdir(proton_save_path):
                        _add_guess(_guesses_data, _checked_paths, proton_save_path, f"Proton Prefix/{fragment} ({appid})", False, _game_abbreviations_lower, _current_steam_app_id, _linux_common_save_subdirs_lower, _other_cleaned_game_names, _other_game_abbreviations, _game_name_cleaned)
                        # Potremmo fare una ricerca limitata anche qui dentro
                        _search_recursive(_guesses_data, _checked_paths, proton_save_path, 0, _max_depth_proton_compatdata, f"Proton Prefix/{fragment}", cancellation_manager,
                          game_abbreviations_lower=_game_abbreviations_lower,
                          linux_common_save_subdirs_lower=_linux_common_save_subdirs_lower,
                          min_save_files_for_bonus_linux=_min_save_files_for_bonus_linux,
                          game_name_cleaned=_game_name_cleaned,
                          known_companies_lower=_known_companies_lower,
                          fuzzy_threshold_basename_match=_fuzzy_threshold_basename_match,
                          fuzzy_threshold_path_match=_fuzzy_threshold_path_match,
                          game_title_original_sig_words_for_seq=_game_title_original_sig_words_for_seq,
                          max_sub_items_to_scan_linux=_max_sub_items_to_scan_linux,
                          current_steam_app_id=_current_steam_app_id,
                          other_cleaned_game_names=_other_cleaned_game_names,
                          other_game_abbreviations=_other_game_abbreviations)
    # 3. Directory di Installazione del Gioco
    if game_install_dir and os.path.isdir(game_install_dir):
        logging.info(f"LINUX_GUESS_SAVE_PATH: Searching in install_dir '{game_install_dir}' (max_depth={_max_depth_generic})")
        _search_recursive(_guesses_data, _checked_paths, game_install_dir, 0, _max_depth_generic, "InstallDir", cancellation_manager,
                          game_abbreviations_lower=_game_abbreviations_lower,
                          linux_common_save_subdirs_lower=_linux_common_save_subdirs_lower,
                          min_save_files_for_bonus_linux=_min_save_files_for_bonus_linux,
                          game_name_cleaned=_game_name_cleaned,
                          known_companies_lower=_known_companies_lower,
                          fuzzy_threshold_basename_match=_fuzzy_threshold_basename_match,
                          fuzzy_threshold_path_match=_fuzzy_threshold_path_match,
                          game_title_original_sig_words_for_seq=_game_title_original_sig_words_for_seq,
                          max_sub_items_to_scan_linux=_max_sub_items_to_scan_linux,
                          current_steam_app_id=_current_steam_app_id,
                          other_cleaned_game_names=_other_cleaned_game_names,
                          other_game_abbreviations=_other_game_abbreviations)
    # 4. Percorsi XDG e Comuni Linux
    # _linux_known_save_locations è un dict { "DescrizioneAmichevole": "/percorso/base", ... }
    for loc_desc, base_path in _linux_known_save_locations.items():
        if os.path.isdir(base_path):
            logging.info(f"LINUX_GUESS_SAVE_PATH: Searching in known location '{loc_desc}' ({base_path}) (max_depth={_max_depth_generic})")
            # Tentativo di match diretto del nome del gioco/abbreviazione
            for abbr_or_name in _game_abbreviations: # Usiamo la lista con case originale per join
                direct_game_path = os.path.join(base_path, abbr_or_name) # Usa case originale per join
                _add_guess(_guesses_data, _checked_paths, direct_game_path, f"{loc_desc}/DirectGameName/{abbr_or_name}", False, _game_abbreviations_lower, _current_steam_app_id, _linux_common_save_subdirs_lower, _other_cleaned_game_names, _other_game_abbreviations, _game_name_cleaned)
            
            # Ricerca ricorsiva generale
            _search_recursive(_guesses_data, _checked_paths, base_path, 0, _max_depth_generic, loc_desc, cancellation_manager,
                              game_abbreviations_lower=_game_abbreviations_lower,
                              linux_common_save_subdirs_lower=_linux_common_save_subdirs_lower,
                              min_save_files_for_bonus_linux=_min_save_files_for_bonus_linux,
                              game_name_cleaned=_game_name_cleaned,
                              known_companies_lower=_known_companies_lower,
                              fuzzy_threshold_basename_match=_fuzzy_threshold_basename_match,
                              fuzzy_threshold_path_match=_fuzzy_threshold_path_match,
                              game_title_original_sig_words_for_seq=_game_title_original_sig_words_for_seq,
                              max_sub_items_to_scan_linux=_max_sub_items_to_scan_linux,
                              current_steam_app_id=_current_steam_app_id,
                              other_cleaned_game_names=_other_cleaned_game_names,
                              other_game_abbreviations=_other_game_abbreviations)
    
    # Logica aggiuntiva per Lutris, Bottles, Heroic etc. potrebbe essere aggiunta qui,
    # idealmente guidata da configurazioni in config.py per i loro percorsi base.

    if not _guesses_data:
        logging.warning(f"LINUX_GUESS_SAVE_PATH: No potential save paths found for '{game_name}'.")
        return []

    # Ordina i risultati
    # La chiave di ordinamento _final_sort_key_linux restituisce (-score, path_lower)
    # quindi l'ordinamento standard è già corretto (punteggio più alto prima, poi alfabetico).
    sorted_guesses = sorted(_guesses_data.items(), key=_final_sort_key_linux)
    
    globals()['logging'].info(f"LINUX_GUESS_SAVE_PATH: Found {len(sorted_guesses)} potential paths for '{game_name}'. Top 5 (or less):")
    for i, item_tuple in enumerate(sorted_guesses[:5]):
        # item_tuple is (normalized_path_key, data_dict)
        original_path = item_tuple[0]  # This is normalized_path_key
        data_dict = item_tuple[1]
        
        source_description_set = data_dict.get('sources', set())
        source = next(iter(source_description_set)) if source_description_set else "UnknownSource"
        
        has_saves = data_dict.get('has_saves_hint', False)
        
        # Recalculate score for logging, _final_sort_key_linux now expects (path, data_dict) item_tuple
        actual_score = -_final_sort_key_linux(item_tuple)[0] 
        
        globals()['logging'].info(f"  {i+1}. {original_path} (Source: {source}, HasSaves: {has_saves}, Score: {actual_score})")

    # Restituisce una lista di tuple (percorso_stringa, punteggio_calcolato)
    # Ogni 'item' in sorted_guesses è (normalized_path_key, data_dict)
    # normalized_path_key è la stringa del percorso.
    # il punteggio è -_final_sort_key_linux(item)[0]
    return [(item[0], -_final_sort_key_linux(item)[0]) for item in sorted_guesses]

def _add_guess(
    guesses_data: dict,
    checked_paths: set,
    path_found: str,
    source_description: str,
    has_saves_hint_from_scan: bool,
    game_abbreviations_lower: set,
    current_steam_app_id: str,
    linux_common_save_subdirs_lower: set,
    other_cleaned_game_names: set,
    other_game_abbreviations: set,
    game_name_cleaned: str
) -> None:
    """
    Adds a found path to the guesses_data dictionary after applying a strict filter.
    This version is self-contained and receives all dependencies as arguments.
    """
    normalized_path = os.path.normpath(os.path.abspath(path_found))
    path_found_lower = normalized_path.lower()

    passes_strict_filter = False
    reason_for_pass = ""
    current_game_name_explicitly_in_path = False

    # Use passed argument instead of global variable
    for abbr in game_abbreviations_lower:
        if abbr in path_found_lower:
            current_game_name_explicitly_in_path = True
            passes_strict_filter = True
            reason_for_pass = f"Current game name/abbr '{abbr}' in path."
            break
    
    # Check for common save subdirectories
    if not passes_strict_filter:
        if path_found_lower in linux_common_save_subdirs_lower:
            passes_strict_filter = True
            reason_for_pass = "Common save subdirectory."
    
    # Check for other cleaned game names
    if not passes_strict_filter:
        for other_name in other_cleaned_game_names:
            if other_name in path_found_lower:
                passes_strict_filter = True
                reason_for_pass = f"Other game name '{other_name}' in path."
                break
    
    # Check for other game abbreviations
    if not passes_strict_filter:
        for other_abbr in other_game_abbreviations:
            if other_abbr in path_found_lower:
                passes_strict_filter = True
                reason_for_pass = f"Other game abbreviation '{other_abbr}' in path."
                break
    
    # Check for Steam AppID
    if not passes_strict_filter and current_steam_app_id:
        appid_str = str(current_steam_app_id)
        if appid_str in path_found_lower:
            passes_strict_filter = True
            reason_for_pass = f"Steam AppID '{appid_str}' in path."
    
    # Final check for cleaned game name
    if not passes_strict_filter and game_name_cleaned:
        if game_name_cleaned in path_found_lower:
            passes_strict_filter = True
            reason_for_pass = f"Cleaned game name '{game_name_cleaned}' in path."
    
    # Add to guesses_data if passed filter
    if passes_strict_filter:
        guesses_data[normalized_path] = {
            "source": source_description,
            "reason": reason_for_pass,
            "has_saves_hint": has_saves_hint_from_scan,
            "explicit_name_match": current_game_name_explicitly_in_path
        }
    
    # Add to checked paths regardless of filter
    checked_paths.add(normalized_path)

def _search_recursive(guesses_data, checked_paths, current_path, current_depth, max_search_depth, source_prefix_desc, cancellation_manager=None,
                      game_abbreviations_lower=None,
                      linux_common_save_subdirs_lower=None,
                      min_save_files_for_bonus_linux=None,
                      game_name_cleaned=None,
                      known_companies_lower=None,
                      fuzzy_threshold_basename_match=None,
                      fuzzy_threshold_path_match=None,
                      game_title_original_sig_words_for_seq=None,
                      max_sub_items_to_scan_linux=None,
                      current_steam_app_id=None,
                      other_cleaned_game_names=None,
                      other_game_abbreviations=None):
    """
    Esplora ricorsivamente le directory per trovare potenziali percorsi di salvataggio.
    CON LOGGING DI DEBUG DETTAGLIATO.
    """
    # LOG SUBITO ALL'INGRESSO DELLA FUNZIONE
    logging.debug(f"ENTERED _search_recursive: Path='{current_path}', Depth={current_depth}, MaxDepthLimit={max_search_depth}, SourcePrefix='{source_prefix_desc}'")

    # Base case 1: Profondita massima raggiunta
    if current_depth > max_search_depth:
        logging.debug(f"EXIT _search_recursive (Max Depth): Path='{current_path}', Depth={current_depth} > MaxDepthLimit={max_search_depth}.")
        return

    # Base case 2: Il percorso non e una directory o non e accessibile
    try:
        if not os.path.isdir(current_path):
            logging.debug(f"EXIT _search_recursive (Not Dir): Path='{current_path}' is not a directory.")
            return
    except OSError as e:
        logging.warning(f"EXIT _search_recursive (OSERROR isdir): Path='{current_path}', Error: {e}")
        return
    except Exception as e_generic_isdir: 
        logging.error(f"EXIT _search_recursive (EXCEPTION isdir): Path='{current_path}', Error: {e_generic_isdir}", exc_info=True)
        return


    # Tentativo di aggiungere la directory corrente se rilevante
    basename_current_path_lower = os.path.basename(current_path.lower()) 
    is_potential_current, has_saves_hint_current = _is_potential_save_dir(current_path, game_name_cleaned, game_abbreviations_lower, linux_common_save_subdirs_lower, min_save_files_for_bonus_linux)
    
    current_path_name_match_game = False
    current_path_name_match_company = False
    current_path_is_common_save_dir_flag = basename_current_path_lower in linux_common_save_subdirs_lower

    for abbr in game_abbreviations_lower: 
        if are_names_similar(abbr, basename_current_path_lower, 
                             game_title_sig_words_for_seq=game_title_original_sig_words_for_seq,
                             fuzzy_threshold=fuzzy_threshold_basename_match): 
            current_path_name_match_game = True
            break
    if not current_path_name_match_game:
        for company_name_clean in known_companies_lower:
            if are_names_similar(company_name_clean, basename_current_path_lower,
                                 game_title_sig_words_for_seq=None,
                                 fuzzy_threshold=fuzzy_threshold_basename_match):
                current_path_name_match_company = True
                break
                
    should_add_current_path = False
    if is_potential_current:
        if current_path_name_match_game or current_path_name_match_company or current_path_is_common_save_dir_flag:
            should_add_current_path = True

    if should_add_current_path:
        specific_source_desc = f"{source_prefix_desc}/{basename_current_path_lower}"
        if current_path_name_match_game: specific_source_desc += " (GameMatch)"
        elif current_path_name_match_company: specific_source_desc += " (CompanyMatch)"
        elif current_path_is_common_save_dir_flag: specific_source_desc += " (CommonSaveDir)"
        elif is_potential_current: specific_source_desc += " (PotentialDirEvidence)"
        _add_guess(guesses_data, checked_paths, current_path, specific_source_desc, has_saves_hint_current, game_abbreviations_lower, current_steam_app_id, linux_common_save_subdirs_lower, other_cleaned_game_names, other_game_abbreviations, game_name_cleaned)

    logging.debug(f"LISTDIR_ATTEMPT _search_recursive: Listing sub-items of '{current_path}'")
    dir_contents = []
    try:
        dir_contents = os.listdir(current_path)
        log_items_display = dir_contents[:15] if len(dir_contents) > 15 else dir_contents
        extra_items_count = len(dir_contents) - 15 if len(dir_contents) > 15 else 0
        logging.debug(f"LISTDIR_SUCCESS _search_recursive: Found {len(dir_contents)} items in '{current_path}'. Items (up to 15): {log_items_display}" + (f" ...and {extra_items_count} more." if extra_items_count > 0 else ""))
    except OSError as e_listdir:
        logging.error(f"LISTDIR_ERROR _search_recursive: OSError listing '{current_path}': {e_listdir}")
        logging.debug(f"EXITING _search_recursive due to LISTDIR_ERROR: Path='{current_path}', Depth={current_depth}")
        return 
    except Exception as e_listdir_generic:
        logging.error(f"LISTDIR_EXCEPTION _search_recursive: Unexpected error listing '{current_path}': {e_listdir_generic}", exc_info=True)
        logging.debug(f"EXITING _search_recursive due to LISTDIR_EXCEPTION: Path='{current_path}', Depth={current_depth}")
        return

    if not dir_contents:
        logging.debug(f"EMPTY_DIR _search_recursive: Directory '{current_path}' is empty. No sub-items to process for recursion further down this branch.")

    try:
        sub_item_scan_limit = max_sub_items_to_scan_linux
        items_scanned = 0
        for item_name in dir_contents:
            logging.debug(f"LOOP_ITEM _search_recursive: Processing item '{item_name}' in '{current_path}'")
            
            if items_scanned >= sub_item_scan_limit:
                logging.debug(f"Reached sub_item_scan_limit ({sub_item_scan_limit}) in '{current_path}'. Stopping scan of this directory for further recursion.")
                break
            items_scanned += 1

            item_path = os.path.join(current_path, item_name)
            item_name_lower = item_name.lower()

            if not os.path.isdir(item_path):
                logging.debug(f"SKIP_ITEM _search_recursive: Item '{item_path}' is not a directory.")
                continue
            
            if item_name_lower in _linux_banned_path_fragments_lower:
                logging.debug(f"BANNED_SUB_ITEM _search_recursive: Sub-item name '{item_name_lower}' is in banned list. Skipping path '{item_path}'.")
                continue
            
            item_is_game_match = False
            item_is_company_match = False
            item_is_common_save_dir = item_name_lower in linux_common_save_subdirs_lower

            # --- Calcolo di item_is_game_match ---
            for abbr in game_abbreviations_lower:
                threshold_value = fuzzy_threshold_path_match if fuzzy_threshold_path_match is not None else 85
                threshold_value -= 10
                if are_names_similar(abbr, item_name, 
                                     game_title_sig_words_for_seq=game_title_original_sig_words_for_seq,
                                     fuzzy_threshold=threshold_value): 
                    item_is_game_match = True
                    break
            
            # Calcolo di item_is_company_match (NUOVA VERSIONE)
            if not item_is_game_match: # Esegui solo se non abbiamo già un game_match
                item_is_company_match = False # Assicurati che sia False all'inizio di questo check

                # Pulisci item_name (nome della sottocartella attuale, es. "Team Cherry") una volta
                cleaned_item_name_for_company_check = clean_for_comparison(item_name) 

                # Log per debug mirato a "Team Cherry"
                if item_name_lower == "team cherry": 
                    logging.debug(f"COMPANY_MATCH_LOOP_START: Iterating _known_companies_lower for item_name_lower='{item_name_lower}' (original item_name='{item_name}', cleaned_item_name_for_company_check='{cleaned_item_name_for_company_check}')")

                for company_name_in_list in known_companies_lower: # _known_companies_lower è già minuscola e pulita
                    # Log per ogni comparazione se stiamo tracciando "Team Cherry"
                    if item_name_lower == "team cherry": # item_name_lower è item_name.lower()
                        logging.debug(f"COMPANY_MATCH_LOOP_ITERATION: Comparing cleaned_item_name='{cleaned_item_name_for_company_check}' with company_in_list='{company_name_in_list}')")

                    # Tentativo 1: Confronto diretto dei nomi puliti
                    if company_name_in_list == cleaned_item_name_for_company_check:
                        item_is_company_match = True
                        logging.debug(f"COMPANY_MATCH_DIRECT: Item '{item_name}' (cleaned: '{cleaned_item_name_for_company_check}') matched known company '{company_name_in_list}'. Setting item_is_company_match=True.")
                        break  # Trovato un match, esci dal loop delle aziende

                    # Tentativo 2 (Fallback): Usa are_names_similar (se il match diretto fallisce)
                    # Questo è opzionale, ma potrebbe aiutare per nomi di aziende con lievi variazioni
                    # che clean_for_comparison non normalizza completamente.
                    # Assicurati che are_names_similar abbia i log interni attivati se usi questo.
                    elif are_names_similar(company_name_in_list, item_name, # item_name originale con case
                                         min_match_words=2, # O il valore che ritieni più opportuno
                                         game_title_sig_words_for_seq=None,
                                         fuzzy_threshold=(fuzzy_threshold_path_match if fuzzy_threshold_path_match is not None else 85) - 10): # Soglia leggermente più bassa
                        item_is_company_match = True
                        logging.debug(f"COMPANY_MATCH_FUZZY: Item '{item_name}' fuzzy matched company '{company_name_in_list}'. Setting item_is_company_match=True.")
                        break
            # Dopo questo, item_is_company_match sarà True o False.

            sub_is_potential, sub_has_saves_hint = _is_potential_save_dir(item_path, game_name_cleaned, game_abbreviations_lower, linux_common_save_subdirs_lower, min_save_files_for_bonus_linux)

            logging.debug(f"PATH_ITEM_EVAL FOR RECURSION: Current Depth: {current_depth}, Item: '{item_path}'")
            logging.debug(f"PATH_ITEM_EVAL Conditions: sub_is_potential={sub_is_potential}, item_is_game_match={item_is_game_match}, item_is_company_match={item_is_company_match}, item_is_common_save_dir={item_is_common_save_dir}")
            logging.debug(f"PATH_ITEM_EVAL ShallowExplore: current_depth({current_depth}) < _max_shallow_explore_depth_linux({_max_shallow_explore_depth_linux}) is {current_depth < _max_shallow_explore_depth_linux}")

            should_recurse_strong = False
            recursion_decision_reason = "No strong criteria met" 

            if item_is_game_match:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_game_match"
            elif item_is_company_match:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_company_match"
            elif item_is_common_save_dir and sub_is_potential: 
                should_recurse_strong = True
                recursion_decision_reason = "item_is_common_save_dir_and_sub_is_potential"
            elif sub_is_potential: 
                should_recurse_strong = True
                recursion_decision_reason = "sub_is_potential_itself"
            
            if should_recurse_strong:
                logging.debug(f"DECISION: RECURSING (STRONG - {recursion_decision_reason}) into: '{item_path}' (new_depth {current_depth + 1}) from '{current_path}'")
                _search_recursive(guesses_data, checked_paths, item_path, current_depth + 1, max_search_depth, f"{source_prefix_desc}/{item_name}", cancellation_manager,
                                  game_abbreviations_lower=game_abbreviations_lower,
                                  linux_common_save_subdirs_lower=linux_common_save_subdirs_lower,
                                  min_save_files_for_bonus_linux=min_save_files_for_bonus_linux,
                                  game_name_cleaned=game_name_cleaned,
                                  known_companies_lower=known_companies_lower,
                                  fuzzy_threshold_basename_match=fuzzy_threshold_basename_match,
                                  fuzzy_threshold_path_match=fuzzy_threshold_path_match,
                                  game_title_original_sig_words_for_seq=game_title_original_sig_words_for_seq,
                                  max_sub_items_to_scan_linux=max_sub_items_to_scan_linux,
                                  current_steam_app_id=current_steam_app_id,
                                  other_cleaned_game_names=other_cleaned_game_names,
                                  other_game_abbreviations=other_game_abbreviations)
            elif current_depth < _max_shallow_explore_depth_linux:
                logging.debug(f"DECISION: RECURSING (SHALLOW explore) into: '{item_path}' (new_depth {current_depth + 1}) from '{current_path}'")
                _search_recursive(guesses_data, checked_paths, item_path, current_depth + 1, max_search_depth, f"{source_prefix_desc}/{item_name}", cancellation_manager,
                                  game_abbreviations_lower=game_abbreviations_lower,
                                  linux_common_save_subdirs_lower=linux_common_save_subdirs_lower,
                                  min_save_files_for_bonus_linux=min_save_files_for_bonus_linux,
                                  game_name_cleaned=game_name_cleaned,
                                  known_companies_lower=known_companies_lower,
                                  fuzzy_threshold_basename_match=fuzzy_threshold_basename_match,
                                  fuzzy_threshold_path_match=fuzzy_threshold_path_match,
                                  game_title_original_sig_words_for_seq=game_title_original_sig_words_for_seq,
                                  max_sub_items_to_scan_linux=max_sub_items_to_scan_linux,
                                  current_steam_app_id=current_steam_app_id,
                                  other_cleaned_game_names=other_cleaned_game_names,
                                  other_game_abbreviations=other_game_abbreviations)
            else:
                logging.debug(f"DECISION: NOT RECURSING into: '{item_path}'. from_parent: '{current_path}'. sub_is_potential={sub_is_potential}, item_is_game_match={item_is_game_match}, item_is_company_match={item_is_company_match}, item_is_common_save_dir={item_is_common_save_dir}, current_depth={current_depth}, _max_shallow_explore_depth_linux={_max_shallow_explore_depth_linux}. Reason for no strong: {recursion_decision_reason}")

    except OSError as e_os_loop:
        logging.warning(f"_search_recursive OS Loop Error: Path='{current_path}', Error processing an item: {e_os_loop}")
    except Exception as e_generic_loop:
        logging.error(f"_search_recursive GENERIC Loop Error: Path='{current_path}', Error: {e_generic_loop}", exc_info=True)
    
    logging.debug(f"EXITING _search_recursive: Path='{current_path}', Depth={current_depth}")

    if cancellation_manager and cancellation_manager.check_cancelled():
        logging.debug(f"_search_recursive: Cancellation requested. Stopping search.")
        return

# Funzione principale di ordinamento per i percorsi trovati
def _final_sort_key_linux(item_tuple):
    """
    Genera una chiave di ordinamento per i percorsi trovati, ispirata alla logica Windows,
    CON MAGGIORE ENFASI SU BASENAME ESPLICITAMENTE DI SALVATAGGIO e HAS_SAVES_HINT.
    Un punteggio più alto significa una maggiore probabilità.
    """
    global _game_name_cleaned, _game_abbreviations_lower, _game_title_original_sig_words_for_seq
    global _linux_common_save_subdirs_lower, _known_companies_lower # Aggiunto _known_companies_lower
    global THEFUZZ_AVAILABLE, fuzz

    normalized_path_key, data_dict = item_tuple
    original_path = normalized_path_key 
    source_description_set = data_dict.get('sources', set())
    source_description = next(iter(source_description_set)) if source_description_set else "UnknownSource"
    has_saves_hint_from_scan = data_dict.get('has_saves_hint', False)

    score = 0
    path_lower_for_sorting = original_path.lower()
    
    try:
        basename = os.path.basename(original_path)
        basename_lower = basename.lower()
        parent_dir_path = os.path.dirname(original_path)
        parent_basename_lower = os.path.basename(parent_dir_path.lower())
    except Exception as e:
        logging.error(f"Error getting basename/dirname for '{original_path}' in _final_sort_key_linux: {e}")
        return (0, path_lower_for_sorting)

    home_dir = os.path.expanduser("~")
    xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(home_dir, ".config"))
    xdg_data_home = os.getenv('XDG_DATA_HOME', os.path.join(home_dir, ".local", "share"))
    steam_compatdata_generic_part = os.path.join("steamapps", "compatdata") 
    steam_userdata_generic_part = "userdata"

    # --- 1. PUNTEGGIO BASE PER LOCAZIONE ---
    if xdg_config_home.lower() in path_lower_for_sorting:
        score += 800 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +800 (in XDG_CONFIG_HOME)")
    elif xdg_data_home.lower() in path_lower_for_sorting:
        score += 700 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +700 (in XDG_DATA_HOME)")
    elif steam_compatdata_generic_part in path_lower_for_sorting and "pfx" in path_lower_for_sorting:
        score += 600 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +600 (Proton compatdata path)")
    elif steam_userdata_generic_part in path_lower_for_sorting:
        score += 500
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +500 (Steam userdata path)")
    elif "documents" in path_lower_for_sorting: 
        score += 200
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +200 (in Documents-like path)")
    elif "InstallDir" in source_description: 
        score += 50 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +50 (InstallDir source)")
    else:
        score += 100 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): +100 (Generic base)")

    # --- 2. BONUS PER CONTENUTO DI SALVATAGGIO (has_saves_hint_from_scan) ---
    # AUMENTATO SIGNIFICATIVAMENTE QUESTO BONUS
    if has_saves_hint_from_scan: 
        score += 800 # Era 600. Un percorso con file di salvataggio è un forte indicatore.
        logging.debug(f"SCORE_LINUX ('{original_path}'): +800 (has_saves_hint_from_scan)")

    # --- 3. BONUS PER NOMI DI CARTELLE RILEVANTI (BASENAME) ---
    is_common_save_subdir_basename = basename_lower in _linux_common_save_subdirs_lower
    if is_common_save_subdir_basename:
        # AUMENTATO SIGNIFICATIVAMENTE QUESTO BONUS se il basename è una cartella di salvataggio esplicita
        score += 600 # Era 350. Priorità alta se il nome stesso della cartella è "saves", "profile", ecc.
        logging.debug(f"SCORE_LINUX ('{original_path}'): +600 (basename '{basename_lower}' IS common save subdir)")
        
        # Bonus aggiuntivo se il genitore è il nome del gioco/azienda
        # (Manteniamo questo bonus, ma quello sopra è più importante per il caso Factorio)
        parent_matches_game_or_company = False
        if parent_basename_lower in _game_abbreviations_lower:
             parent_matches_game_or_company = True
        elif parent_basename_lower in _known_companies_lower: # Assicurati che _known_companies_lower sia accessibile
             parent_matches_game_or_company = True
        # Potresti anche usare are_names_similar qui per il parent, se necessario, ma aumenta la complessità
        # elif are_names_similar(_game_name_cleaned, parent_basename_lower, fuzzy_threshold=80, game_title_sig_words_for_seq=_game_title_original_sig_words_for_seq ):
        #      parent_matches_game_or_company = True


        if parent_matches_game_or_company:
            score += 150 
            logging.debug(f"SCORE_LINUX ('{original_path}'): +150 (parent '{parent_basename_lower}' matches game/company AND basename is common save subdir)")

    # --- 4. BONUS PER SIMILARITÀ NOME GIOCO (SUL BASENAME) ---
    cleaned_folder_basename = clean_for_comparison(basename)
    exact_match_bonus = 0
    fuzzy_bonus = 0

    if _game_name_cleaned and cleaned_folder_basename:
        if cleaned_folder_basename == _game_name_cleaned:
            exact_match_bonus = 500 
        elif THEFUZZ_AVAILABLE:
            set_ratio = fuzz.token_set_ratio(_game_name_cleaned, cleaned_folder_basename)
            if set_ratio > 88: 
                fuzzy_bonus = int(((set_ratio - 88) / 12) * 350) 
        
        if basename_lower in _game_abbreviations_lower and not exact_match_bonus: # Solo se non è già un exact match del nome completo
            fuzzy_bonus += 200 
            
        if _game_title_original_sig_words_for_seq and len(basename) <= 5 and matches_initial_sequence(basename, _game_title_original_sig_words_for_seq):
            fuzzy_bonus += 150 
            
    score += exact_match_bonus + fuzzy_bonus
    if exact_match_bonus > 0 or fuzzy_bonus > 0:
         logging.debug(f"SCORE_LINUX ('{original_path}'): Total from basename game name match: +{exact_match_bonus + fuzzy_bonus}")


    # --- 5. PENALITÀ SPECIFICHE (SUL BASENAME PRINCIPALMENTE) ---
    generic_folder_names_to_penalize = {"data", "config", "settings", "cache", "logs", "common", "default", "user", "users"} 
    # "profile" e "profiles" sono spesso cartelle di salvataggio valide, quindi rimosse da qui.
    # "unity3d", "unrealengine", ecc., sono gestite da common_save_subdir se presenti lì.
    
    if basename_lower in generic_folder_names_to_penalize and \
       not has_saves_hint_from_scan and \
       exact_match_bonus == 0 and fuzzy_bonus < 100 and \
       not is_common_save_subdir_basename: # Non penalizzare se è già stata identificata come common save subdir (es. config)
        score -= 200
        logging.debug(f"SCORE_LINUX ('{original_path}'): -200 (generic basename '{basename_lower}' with no strong game match/saves/common_subdir_match)")

    if len(basename_lower) <= 2 and not is_common_save_subdir_basename and not has_saves_hint_from_scan and not (exact_match_bonus > 0 or fuzzy_bonus > 0):
        score -= 100 
        # logging.debug(f"SCORE_LINUX ('{original_path}'): -100 (basename too short and not otherwise significant)")

    depth = len(original_path.split(os.sep)) - len(home_dir.split(os.sep)) 
    if depth > 4: # Penalizza solo per profondità > 4 relativa a home (era > 3)
        # Se il basename è una cartella di salvataggio esplicita o ha salvataggi, la penalità per profondità è meno rilevante
        depth_penalty_multiplier = 1
        if is_common_save_subdir_basename or has_saves_hint_from_scan:
            depth_penalty_multiplier = 0.5 # Riduci la penalità per profondità se il target è buono
        
        applied_depth_penalty = getattr(config, 'PENALTY_LINUX_DEPTH_BASE', -5) * (depth - 4) * depth_penalty_multiplier
        score += applied_depth_penalty
        # logging.debug(f"SCORE_LINUX ('{original_path}'): Depth penalty {applied_depth_penalty} for depth {depth}")

    # Penalità se il percorso contiene "engine" o nomi simili ma NON è la cartella del gioco
    # e non è una common_save_subdir esplicita e non ha salvataggi.
    generic_engine_terms_in_path = ["unity3d", "unrealengine", "godot", "cryengine", "gamemaker"] # Rimuovi ".config/unity3d" da qui perché troppo specifico per un check 'in path'
    # Il nome base 'basename_lower' è già stato controllato da is_common_save_subdir_basename
    # Questa penalità si applica se questi termini sono in parti *superiori* del percorso,
    # e il percorso finale non è chiaramente il gioco o una cartella di salvataggi.
    if not (exact_match_bonus > 0 or fuzzy_bonus > 150) and not has_saves_hint_from_scan and not is_common_save_subdir_basename:
        for term in generic_engine_terms_in_path:
            # Controlla se il termine è un componente del percorso, escludendo il basename stesso
            path_components_for_engine_check = original_path.lower().split(os.sep)
            if basename_lower in path_components_for_engine_check: # Non dovrebbe succedere, ma per sicurezza
                path_components_for_engine_check.remove(basename_lower)

            if term in path_components_for_engine_check:
                score += getattr(config, 'PENALTY_LINUX_GENERIC_ENGINE_DIR', -100) # Era _penalty_generic_engine_dir
                logging.debug(f"SCORE_LINUX ('{original_path}'): PENALTY_GENERIC_ENGINE_DIR for term '{term}' in parent path (final basename '{basename_lower}' not strong game match/saves/common_subdir) -> {score}")
                break # Applica solo una volta


    logging.info(f"SCORE_LINUX_FINAL_CALC: Path='{original_path}', Final Score={score}, Source='{source_description}', HasSavesHint={has_saves_hint_from_scan}, Basename='{basename_lower}', isCommonSubdir={is_common_save_subdir_basename}")
    return (-score, path_lower_for_sorting)
