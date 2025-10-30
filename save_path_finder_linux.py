# save_path_finder_linux.py
import os
import re
import logging
from dataclasses import dataclass, field
import platform
from typing import Dict # Aggiunto import per Dict
import cancellation_utils  # Add import
import threading
from typing import Optional, Any

# Thread-local storage for per-thread state
_thread_local = threading.local()

# --- Class-based facade (additive, no behavior change) ---
class LinuxGameContext:
    def __init__(self, game_name, game_install_dir=None, appid=None, steam_userdata_path=None,
                 steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None):
        self.game_name = game_name
        self.game_install_dir = game_install_dir
        self.appid = appid
        self.steam_userdata_path = steam_userdata_path
        self.steam_id3_to_use = steam_id3_to_use
        self.is_steam_game = is_steam_game
        self.installed_steam_games_dict = installed_steam_games_dict

    def to_params(self):
        return {
            "game_name": self.game_name,
            "game_install_dir": self.game_install_dir,
            "appid": self.appid,
            "steam_userdata_path": self.steam_userdata_path,
            "steam_id3_to_use": self.steam_id3_to_use,
            "is_steam_game": self.is_steam_game,
            "installed_steam_games_dict": self.installed_steam_games_dict,
        }

class LinuxSavePathFinder:
    def __init__(self, context: 'LinuxGameContext', cancellation_manager=None):
        self.context = context
        self.cancellation_manager = cancellation_manager

    def find_save_paths(self):
        engine = LinuxPathSearchEngine(self.context)
        return engine.run(self.cancellation_manager)

class LinuxPathSearchEngine:
    """
    Thin, compatibility-preserving engine wrapper for Linux save-path discovery.
    For now it simply delegates to the existing module function `guess_save_path`.
    This provides an instance-oriented seam for future refactors without changing behavior.
    """
    def __init__(self, context: 'LinuxGameContext'):
        self.context = context

    def run(self, cancellation_manager=None):
        return guess_save_path(
            game_name=self.context.game_name,
            game_install_dir=self.context.game_install_dir,
            appid=self.context.appid,
            steam_userdata_path=self.context.steam_userdata_path,
            steam_id3_to_use=self.context.steam_id3_to_use,
            is_steam_game=self.context.is_steam_game,
            installed_steam_games_dict=self.context.installed_steam_games_dict,
            cancellation_manager=cancellation_manager,
        )

# Lightweight container for configured state (created during initialization phase).
@dataclass
class LinuxSearchState:
    game_name_cleaned: str
    game_abbreviations_lower: set = field(default_factory=set)
    game_title_original_sig_words_for_seq: list = field(default_factory=list)
    known_companies_lower: list = field(default_factory=list)
    linux_common_save_subdirs_lower: set = field(default_factory=set)
    linux_banned_path_fragments_lower: set = field(default_factory=set)
    common_save_extensions: set = field(default_factory=set)
    common_save_extensions_nodot: set = field(default_factory=set)
    common_save_filenames_lower: set = field(default_factory=set)
    proton_user_path_fragments: list = field(default_factory=list)
    # Campi per gestire la directory di installazione
    is_exploring_install_dir: bool = False
    install_dir_root: str = None
    linux_known_save_locations: dict = field(default_factory=dict)
    installed_steam_games_dict: Optional[Dict] = None
    other_cleaned_game_names: set = field(default_factory=set)
    other_game_abbreviations: set = field(default_factory=set)
    current_steam_app_id: Optional[str] = None
    max_files_to_scan_linux_hint: int = 0
    min_save_files_for_bonus_linux: int = 0
    max_sub_items_to_scan_linux: int = 0
    max_shallow_explore_depth_linux: int = 0
    max_search_depth_linux: int = 0
    fuzzy_threshold_basename_match: int = 0
    fuzzy_threshold_path_match: int = 0
    THEFUZZ_AVAILABLE: bool = False
    fuzz: Optional[Any] = None
    MAX_USERDATA_SCORE: int = 1100  # Cap per Steam userdata (come Windows)

def _build_state_from_thread_locals() -> LinuxSearchState:
    """Create an immutable snapshot of the current thread-local configuration."""
    return LinuxSearchState(
        game_name_cleaned=_thread_local._game_name_cleaned,
        game_abbreviations_lower=_thread_local._game_abbreviations_lower,
        game_title_original_sig_words_for_seq=_thread_local._game_title_original_sig_words_for_seq,
        known_companies_lower=_thread_local._known_companies_lower,
        linux_common_save_subdirs_lower=_thread_local._linux_common_save_subdirs_lower,
        linux_banned_path_fragments_lower=_thread_local._linux_banned_path_fragments_lower,
        common_save_extensions=_thread_local._common_save_extensions,
        common_save_extensions_nodot=_thread_local._common_save_extensions_nodot,
        common_save_filenames_lower=_thread_local._common_save_filenames_lower,
        proton_user_path_fragments=_thread_local._proton_user_path_fragments,
        linux_known_save_locations=_thread_local._linux_known_save_locations,
        installed_steam_games_dict=getattr(_thread_local, '_installed_steam_games_dict', None),
        other_cleaned_game_names=_thread_local._other_cleaned_game_names,
        other_game_abbreviations=_thread_local._other_game_abbreviations,
        current_steam_app_id=_thread_local._current_steam_app_id,
        max_files_to_scan_linux_hint=_thread_local._max_files_to_scan_linux_hint,
        min_save_files_for_bonus_linux=_thread_local._min_save_files_for_bonus_linux,
        max_sub_items_to_scan_linux=_thread_local._max_sub_items_to_scan_linux,
        max_shallow_explore_depth_linux=_thread_local._max_shallow_explore_depth_linux,
        max_search_depth_linux=_thread_local._max_search_depth_linux,
        fuzzy_threshold_basename_match=_thread_local._fuzzy_threshold_basename_match,
        fuzzy_threshold_path_match=_thread_local._fuzzy_threshold_path_match,
        THEFUZZ_AVAILABLE=_thread_local._THEFUZZ_AVAILABLE,
        fuzz=_thread_local._fuzz,
        MAX_USERDATA_SCORE=_thread_local._MAX_USERDATA_SCORE,
    )

if 'generate_abbreviations' not in globals():
    def generate_abbreviations(name, install_dir): return [name]
if 'are_names_similar' not in globals():
    def are_names_similar(s1, s2, **kwargs): return s1.lower() == s2.lower()
if 'clean_for_comparison' not in globals():
    def clean_for_comparison(s): return s.lower()


# Importazione robusta di thefuzz
fuzz = None
try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Successfully imported 'thefuzz'. Fuzzy matching will be available for Linux path finding.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    logging.warning("'thefuzz' library not found. Fuzzy matching will be disabled for Linux path finding. Path accuracy may be affected for some games.")

# Simplified logging - removed verbose debug system

# Importa il modulo config effettivo
import config # CORRETTO: import diretto
import re

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

        # Solo alfanumerico (stile Windows)
        name_alphanum_only = re.sub(r'[^a-z0-9]', '', base_name_cleaned)
        if name_alphanum_only != name_no_space and name_alphanum_only != base_name_cleaned and len(name_alphanum_only) > 1:
            abbreviations.add(name_alphanum_only)

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

    # 2.5. Acronimo da CamelCase e cifre finali (es. ElectronicSuperJoy2 -> ESJ2)
    # Suddivide il nome originale in token CamelCase e numerici, quindi costruisce l'acronimo
    try:
        tokens = re.findall(r'[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+', name_for_caps_check)
        tokens_filtered = [t for t in tokens if t and t.lower() not in ignore_words_lower]
        if tokens_filtered:
            acr_cam = ''.join([t if t.isdigit() else t[0].upper() for t in tokens_filtered])
            if len(acr_cam) >= 2:
                abbreviations.add(acr_cam)
                abbreviations.add(acr_cam.lower())
    except Exception:
        pass

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

    # 3.5. Acronym vs CamelCase or spaced name (FLT -> FasterThanLight)
    try:
        name1_upper = temp_clean_name1.replace(' ', '').upper()
        # Consider acronyms of 2..6 letters/digits
        if 2 <= len(name1_upper) <= 6 and name1_upper.isalnum():
            # Derive initials from CamelCase or separators in name2
            raw2 = str(name2_path_component)
            # First split on separators
            parts = re.split(r'[\s_\-]+', raw2)
            initials = ""
            if len(parts) > 1:
                initials = ''.join(p[0] for p in parts if p and p[0].isascii())
            else:
                # Try CamelCase tokenization
                camel_tokens = re.findall(r'[A-Z0-9][a-z0-9]*', raw2)
                if camel_tokens:
                    initials = ''.join(t[0] for t in camel_tokens if t and t[0].isascii())
            if initials and initials.upper() == name1_upper:
                return True
    except Exception:
        pass

    # 4. Fuzzy Matching (migliorato)
    if THEFUZZ_AVAILABLE and fuzzy_threshold > 0 and fuzzy_threshold <= 100:
        try:
            # Prova diversi tipi di fuzzy matching
            ratio = fuzz.token_set_ratio(temp_clean_name1, temp_clean_name2)
            if ratio >= fuzzy_threshold:
                return True
            
            # NUOVO: Prova anche partial_ratio per casi come "rimworld" vs "RimWorld by Ludeon Studios"
            partial_ratio = fuzz.partial_ratio(temp_clean_name1, temp_clean_name2)
            if partial_ratio >= fuzzy_threshold:
                return True
                
            # NUOVO: Controllo speciale per nomi contenuti (soglia più bassa)
            # Se name1 è contenuto in name2 o viceversa con alta similarità
            if len(temp_clean_name1) >= 4 and len(temp_clean_name2) >= 4:
                if temp_clean_name1 in temp_clean_name2 or temp_clean_name2 in temp_clean_name1:
                    # Se uno è contenuto nell'altro, usa soglia più bassa
                    if ratio >= (fuzzy_threshold - 20):  # Soglia ridotta di 20 punti
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
                # Strict mode: only accept strong indicators to avoid false positives in generic folders
                if getattr(config, 'LINUX_STRICT_EVIDENCE_MODE', True):
                    strict_exts = getattr(config, 'LINUX_STRICT_SAVE_EXTENSIONS', set())
                    strict_keywords = getattr(config, 'LINUX_STRICT_SAVE_FILENAME_KEYWORDS', set())
                    if ext_lower in strict_exts:
                        is_matching_file = True
                    else:
                        for kw in strict_keywords:
                            if kw in item_name_lower:
                                is_matching_file = True
                                break
                else:
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
    
    return has_evidence, save_file_count


def _is_potential_save_dir(
    dir_path: str,
    game_name_clean: str,
    game_abbreviations_lower: set,
    linux_common_save_subdirs_lower: set,
    min_save_files_for_bonus_linux: int,
    max_files_to_scan_linux_hint: int,
    common_save_extensions_nodot: set,
    common_save_filenames_lower: set,
):
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
            break
        
        # Controllo 2: Se abbr contiene underscore, prova a confrontarlo con spazi in dir_path
        # Esempio: abbr="cyberpunk_2077", dir_path="cyberpunk 2077"
        if '_' in abbr:
            abbr_with_spaces = abbr.replace('_', ' ')
            if abbr_with_spaces in dir_path.lower():
                name_match_game_or_common_save_dir = True
                break

    if not name_match_game_or_common_save_dir:
        # Compare only the basename against known common save directory names
        if os.path.basename(dir_path).lower() in linux_common_save_subdirs_lower:
            name_match_game_or_common_save_dir = True
    
    # 2. Controllo basato sull'evidenza dei file (eseguito se il nome matcha o come fallback)
    #    Scansiona la directory per file che sembrano salvataggi.
    has_save_files_evidence, save_file_count_for_bonus = _scan_dir_for_save_evidence_linux(
        dir_path,
        max_files_to_scan_linux_hint,
        common_save_extensions_nodot,
        common_save_filenames_lower,
    )

    if name_match_game_or_common_save_dir:
        is_potential = True # Se il nome matcha, è potenziale indipendentemente dai file (per ora, lo score lo gestirà)
        if save_file_count_for_bonus >= min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True
    elif has_save_files_evidence: # Se il nome non matcha, ma ci sono file sospetti
        is_potential = True # È potenziale grazie ai file
        if save_file_count_for_bonus >= min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True

    return is_potential, has_actual_save_files_for_bonus

def _is_in_userdata(path_lower: str, steam_userdata_path: str = None) -> bool:
    """
    Controlla se un percorso è all'interno di Steam userdata.
    """
    if not steam_userdata_path:
        return False
    
    # Normalizza i percorsi per confronto cross-platform
    userdata_check = steam_userdata_path.lower().replace('\\', '/')
    path_check = path_lower.replace('\\', '/')
    
    return path_check.startswith(userdata_check)

def _identify_path_type(path_lower: str, source_lower: str, steam_userdata_path: str = None) -> Dict[str, bool]:
    """
    Identifica il tipo di percorso per applicare le penalità appropriate.
    """
    # Controlla se è un percorso Steam remote
    is_steam_remote = False
    if steam_userdata_path:
        # Normalizza source_lower e path per confronto cross-platform
        source_check = source_lower.replace('\\', '/').lower()
        path_check = path_lower.replace('\\', '/')
        # Controlla sia nel source che nel path stesso
        is_steam_remote = (('steam userdata' in source_check and '/remote' in source_check) or
                         (steam_userdata_path.lower() in path_check and
                          '/remote' in path_check))
    
    # Controlla se è un percorso Steam base (non remote)
    is_steam_base = False
    if steam_userdata_path:
        path_check = path_lower.replace('\\', '/')
        userdata_base = steam_userdata_path.lower().replace('\\', '/')
        is_steam_base = (path_check.startswith(userdata_base) and not is_steam_remote)
    
    # Controlla se è in una posizione privilegiata (AppData, Documents, etc.)
    is_prime_location = any(loc in path_lower for loc in [
        '/home/', '/.local/share/', '/.config/', '/.steam/steam/userdata/',
        'appdata', 'documents', 'saved games'
    ])
    
    # Controlla se è un percorso di installazione (walk)
    is_install_dir_walk = any(loc in path_lower for loc in [
        '/usr/local/', '/opt/', '/snap/', '/var/', '/usr/share/',
        'steamapps/common'
    ])
    
    return {
        'is_steam_remote': is_steam_remote,
        'is_steam_base': is_steam_base,
        'is_prime_location': is_prime_location,
        'is_install_dir_walk': is_install_dir_walk
    }

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
_score_save_dir_match = 800
_score_has_save_files = 1500
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
_score_xdg_data_home_bonus = 500
_score_xdg_config_home_bonus = 600
_score_publisher_match_bonus = 10
_score_wine_prefix_generic_bonus = 15 

# Set di nomi di altri giochi installati (puliti)
_other_cleaned_game_names = set()

# Variabile per i percorsi noti, caricata da config
_linux_known_save_locations: Dict[str, str] = {} 

# Costanti per le penalità aggressive (come Windows)
DATA_FOLDER_PENALTY = -800  # Penalità per cartella 'data'
GENERIC_FOLDER_PENALTY = -400  # Penalità per altre cartelle generiche
INSTALL_DIR_NO_SAVES_PENALTY = -800  # Penalità per install dir senza saves
INSTALL_DIR_GENERIC_PENALTY = -600  # Penalità per cartelle generiche nell'install dir
INSTALL_DIR_MCC_PENALTY = -1000  # Penalità specifica per cartelle problematiche come MCC
BACKUP_DIRECTORY_PENALTY = -9999  # Penalità massima per cartelle dei backup del programma

def _initialize_globals_from_config(game_name_raw, game_install_dir_raw, installed_steam_games_dict=None, steam_app_id_raw=None):
    """Carica le configurazioni e inizializza le variabili globali del modulo."""
    # Instead of global variables, we use thread-local storage
    _thread_local._game_name_cleaned = clean_for_comparison(game_name_raw)
    
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
    _thread_local._game_title_original_sig_words_for_seq = [
        word for word in original_game_words_with_case 
        if word and word.lower() not in ignore_words_for_seq_lower # Confronto in minuscolo per ignore
    ]
    if not _thread_local._game_title_original_sig_words_for_seq and _thread_local._game_name_cleaned: # Fallback se tutto viene filtrato
        _thread_local._game_title_original_sig_words_for_seq = _thread_local._game_name_cleaned.split(' ')

    # logging.debug(f"Calculated _game_title_original_sig_words_for_seq: {_thread_local._game_title_original_sig_words_for_seq}")
    # --- FINE Logica per _game_title_original_sig_words_for_seq ---
    
    _thread_local._game_abbreviations = generate_abbreviations(game_name_raw)
    if _thread_local._game_name_cleaned not in _thread_local._game_abbreviations:
        _thread_local._game_abbreviations.append(_thread_local._game_name_cleaned)
    _thread_local._game_abbreviations_lower = {clean_for_comparison(abbr) for abbr in _thread_local._game_abbreviations}
    
    # Debug: show generated abbreviations
    logging.info(f"DEBUG: Generated abbreviations for '{game_name_raw}': {_thread_local._game_abbreviations}")
    logging.info(f"DEBUG: Game abbreviations (lowercase): {_thread_local._game_abbreviations_lower}")
    _thread_local._game_abbreviations_upper = {abbr.upper() for abbr in _thread_local._game_abbreviations}

    _thread_local._known_companies_lower = [kc.lower() for kc in getattr(config, 'COMMON_PUBLISHERS', [])]
    
    # Debug: show known companies
    logging.info(f"DEBUG: Known companies (lowercase): {len(_thread_local._known_companies_lower)} companies loaded")
    _thread_local._linux_common_save_subdirs_lower = {csd.lower() for csd in getattr(config, 'LINUX_COMMON_SAVE_SUBDIRS', [])}
    _thread_local._linux_banned_path_fragments_lower = {bps.lower() for bps in getattr(config, 'LINUX_BANNED_PATH_FRAGMENTS', getattr(config, 'BANNED_FOLDER_NAMES_LOWER', []))}
    _thread_local._common_save_extensions = {e.lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    _thread_local._common_save_extensions_nodot = {e.lstrip('.').lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    _thread_local._common_save_filenames_lower = {f.lower() for f in getattr(config, 'COMMON_SAVE_FILENAMES', set())}
    _thread_local._proton_user_path_fragments = getattr(config, 'PROTON_USER_PATH_FRAGMENTS', [])
    
    # Caricamento di _linux_known_save_locations
    _thread_local._linux_known_save_locations = {}
    raw_locations = getattr(config, 'LINUX_KNOWN_SAVE_LOCATIONS', []) 
    if isinstance(raw_locations, dict):
        for desc, path_val in raw_locations.items():
            _thread_local._linux_known_save_locations[desc] = os.path.expanduser(path_val)
    elif isinstance(raw_locations, list):
        for item in raw_locations:
            if isinstance(item, tuple) and len(item) == 2:
                desc, path_val = item
                _thread_local._linux_known_save_locations[desc] = os.path.expanduser(path_val)
            elif isinstance(item, str):
                desc = item.replace("~", "Home").replace("/.", "/").strip("/").replace("/", "_")
                _thread_local._linux_known_save_locations[desc if desc else "UnknownLocation"] = os.path.expanduser(item)

    # Carica le penalità da config.py
    _thread_local._penalty_no_game_name_in_path = getattr(config, 'PENALTY_NO_GAME_NAME_IN_PATH', -600)
    _thread_local._penalty_unrelated_game_in_path = getattr(config, 'PENALTY_UNRELATED_GAME_IN_PATH', -800)

    # Popola i set per "altri giochi"
    _thread_local._other_cleaned_game_names = set()
    _thread_local._other_game_abbreviations = set()

    all_known_games_raw_list = getattr(config, 'ALL_KNOWN_GAME_NAMES_RAW', [])
    current_game_name_cleaned_lower = _thread_local._game_name_cleaned.lower()
    current_game_abbreviations_lower = {abbr.lower() for abbr in _thread_local._game_abbreviations}

    for other_game_name_raw_entry in all_known_games_raw_list:
        if not isinstance(other_game_name_raw_entry, str):
            continue
        other_game_cleaned = clean_for_comparison(other_game_name_raw_entry)
        other_game_cleaned_lower = other_game_cleaned.lower()
        if other_game_cleaned_lower == current_game_name_cleaned_lower:
            continue
        _thread_local._other_cleaned_game_names.add(other_game_cleaned_lower)
        temp_other_abbrs = generate_abbreviations(other_game_name_raw_entry)
        for other_abbr in temp_other_abbrs:
            other_abbr_lower = other_abbr.lower()
            if other_abbr_lower not in current_game_abbreviations_lower and other_abbr_lower != current_game_name_cleaned_lower:
                _thread_local._other_game_abbreviations.add(other_abbr_lower)

    # Nuovi globali caricati da config
    _thread_local._max_files_to_scan_linux_hint = getattr(config, 'MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT', 100)
    _thread_local._min_save_files_for_bonus_linux = getattr(config, 'MIN_SAVE_FILES_FOR_BONUS_LINUX', 2)
    _thread_local._max_sub_items_to_scan_linux = getattr(config, 'MAX_SUB_ITEMS_TO_SCAN_LINUX', 50)
    _thread_local._max_shallow_explore_depth_linux = getattr(config, 'MAX_SHALLOW_EXPLORE_DEPTH_LINUX', 1)
    _thread_local._max_search_depth_linux = getattr(config, 'MAX_SEARCH_DEPTH_LINUX', 10) # Default a 10 se non definito

    _thread_local._current_steam_app_id = steam_app_id_raw
    _thread_local._installed_steam_games_dict = installed_steam_games_dict

    # Add fuzzy thresholds to thread-local storage
    _thread_local._fuzzy_threshold_basename_match = getattr(config, 'FUZZY_THRESHOLD_BASENAME_MATCH', 85)
    _thread_local._fuzzy_threshold_path_match = getattr(config, 'FUZZY_THRESHOLD_PATH_MATCH', 75)

    _thread_local._THEFUZZ_AVAILABLE = THEFUZZ_AVAILABLE
    _thread_local._fuzz = fuzz
    _thread_local._MAX_USERDATA_SCORE = getattr(config, 'MAX_USERDATA_SCORE', 1100) # Carica il valore da config

    # logging.debug(f"Linux Path Finder Initialized. Game: '{_thread_local._game_name_cleaned}', Abbreviations: {_thread_local._game_abbreviations_lower}")

def guess_save_path(game_name, game_install_dir, appid=None, steam_userdata_path=None, steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None, cancellation_manager: cancellation_utils.CancellationManager = None):
    # Reset thread-local configuration variables at start of each search
    _thread_local._game_name_cleaned = None
    _thread_local._game_abbreviations = []
    _thread_local._game_abbreviations_lower = set()
    _thread_local._game_abbreviations_upper = set()
    _thread_local._known_companies_lower = set()
    _thread_local._linux_common_save_subdirs_lower = set()
    _thread_local._linux_banned_path_fragments_lower = set()
    _thread_local._common_save_extensions = set()
    _thread_local._common_save_filenames_lower = set()
    _thread_local._proton_user_path_fragments = []
    _thread_local._other_cleaned_game_names = set()
    _thread_local._other_game_abbreviations = set()
    _thread_local._max_files_to_scan_linux_hint = 0
    _thread_local._min_save_files_for_bonus_linux = 0
    _thread_local._THEFUZZ_AVAILABLE = False
    _thread_local._fuzz = None
    _thread_local._max_sub_items_to_scan_linux = 0
    _thread_local._max_shallow_explore_depth_linux = 0
    _thread_local._linux_known_save_locations = {}
    _thread_local._current_steam_app_id = None
    _thread_local._game_title_original_sig_words_for_seq = []
    # NON inizializzare guesses_data qui - viene gestita separatamente per mantenere i percorsi Proton
    # _thread_local._guesses_data = {}
    _thread_local._checked_paths = set()
    
    # Initialize fresh state for this search
    _initialize_globals_from_config(game_name, game_install_dir, installed_steam_games_dict, appid)
    # Persist Steam userdata base for scoring/caps
    _thread_local._steam_userdata_path = steam_userdata_path
    
    logging.info(f"LINUX_GUESS_SAVE_PATH: Starting search for '{game_name}' (AppID: {appid})")

    # Inizializza guesses_data per tutti i giochi (Steam e non-Steam) - DEVE ESSERE PRIMA DI TUTTO
    if not hasattr(_thread_local, '_guesses_data') or _thread_local._guesses_data is None:
        _thread_local._guesses_data = {}
    # logging.info(f"LINUX_GUESS_SAVE_PATH: At start, guesses_data has {len(_thread_local._guesses_data)} items")
    
    # Build a snapshot of state once and reuse it through the search
    state = _build_state_from_thread_locals()

    # 1. Steam Userdata (Priorità Alta)
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        try:
            user_data_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
            if os.path.isdir(user_data_for_id):
                app_specific_userdata = os.path.join(user_data_for_id, appid)
                if os.path.isdir(app_specific_userdata):
                    _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, app_specific_userdata, "Steam Userdata/AppID_Base", False, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
                    remote_path = os.path.join(app_specific_userdata, 'remote')
                    if os.path.isdir(remote_path):
                        # Gate remote scan for performance if desired
                        if getattr(config, 'LINUX_ENABLE_STEAM_USERDATA_REMOTE_SCAN', True):
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, remote_path, f"Steam Userdata/AppID_Base/remote", False, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
                            if not (cancellation_manager and cancellation_manager.check_cancelled()):
                                # Esplora un livello dentro 'remote'
                                _search_recursive(remote_path, 0, _thread_local._guesses_data, _thread_local._checked_paths, cancellation_manager, state)
        except Exception as e:
            logging.error(f"LINUX_GUESS_SAVE_PATH: Error processing Steam Userdata: {e}")

    # 2. Proton Compatdata (per giochi Windows via Proton) - MIGLIORATO
    if is_steam_game and appid:
        steam_base_paths_for_compat = [
            os.path.join(os.path.expanduser("~"), ".steam", "steam"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "Steam"),
            os.path.join(os.path.expanduser("~"), ".steam", "root"),
            os.path.join(os.path.expanduser("~"), ".steam", "debian-installation"),
            os.path.join(os.path.expanduser("~"), ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")
        ]
        for steam_base in steam_base_paths_for_compat:
            compatdata_path = os.path.join(steam_base, 'steamapps', 'compatdata', appid, 'pfx')
            if os.path.isdir(compatdata_path):
                _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, compatdata_path, f"Proton Prefix ({appid})", False, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
                
                if getattr(config, 'LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM', True):
                    # NUOVO: Ricerca più profonda nella struttura Wine prefix
                    if not (cancellation_manager and cancellation_manager.check_cancelled()):
                        _search_proton_prefix_deep(compatdata_path, appid, state, cancellation_manager)
                    
                    # Ricerca standard per i frammenti esistenti
                    for fragment in state.proton_user_path_fragments:
                        if cancellation_manager and cancellation_manager.check_cancelled():
                            break
                        proton_save_path = os.path.join(compatdata_path, fragment)
                        if os.path.isdir(proton_save_path):
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, proton_save_path, f"Proton Prefix/{fragment} ({appid})", False, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
                            _search_recursive(proton_save_path, 0, _thread_local._guesses_data, _thread_local._checked_paths, cancellation_manager, state)

    # NUOVO: Ricerca Proton per giochi non-Steam (cerca in tutti i compatdata disponibili)
    if (not is_steam_game or not appid) and getattr(config, 'LINUX_ENABLE_PROTON_SCAN_NONSTEAM', True):
        # Inizializza guesses_data PRIMA della ricerca Proton
        if not hasattr(_thread_local, '_guesses_data') or _thread_local._guesses_data is None:
            _thread_local._guesses_data = {}
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Before Proton search, guesses_data has {len(_thread_local._guesses_data)} items")
            
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Starting Proton search for non-Steam game '{game_name}' (is_steam_game={is_steam_game}, appid={appid})")
        _search_proton_for_non_steam_games(state, cancellation_manager)
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Completed Proton search for non-Steam game '{game_name}'")
        # logging.info(f"LINUX_GUESS_SAVE_PATH: After Proton search, found {len(_thread_local._guesses_data)} total paths")
    # else:
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Skipping Proton search for Steam game '{game_name}' (is_steam_game={is_steam_game}, appid={appid})")

    # 2.5. Ricerca giochi Snap
    if getattr(config, 'LINUX_ENABLE_SNAP_SEARCH', True):
        if not (cancellation_manager and cancellation_manager.check_cancelled()):
            _search_snap_games(state, cancellation_manager)

    # 3. Directory di Installazione del Gioco
    if game_install_dir and os.path.isdir(game_install_dir):
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Before install_dir search, guesses_data has {len(_thread_local._guesses_data)} items")
        # logging.info(f"LINUX_GUESS_SAVE_PATH: Searching in install_dir '{game_install_dir}' (max_depth={_max_depth_generic})")
        
        # IMPORTANTE: Marca che stiamo esplorando la directory di installazione
        state.is_exploring_install_dir = True
        state.install_dir_root = os.path.normpath(game_install_dir).lower()
        
        _search_recursive(game_install_dir, 0, _thread_local._guesses_data, _thread_local._checked_paths, cancellation_manager, state)
        
        # Reset flag dopo l'esplorazione
        state.is_exploring_install_dir = False
        state.install_dir_root = None
        
        # logging.info(f"LINUX_GUESS_SAVE_PATH: After install_dir search, guesses_data has {len(_thread_local._guesses_data)} items")
    
    # 4. Percorsi XDG e Comuni Linux
    # logging.info(f"LINUX_GUESS_SAVE_PATH: Before XDG search, guesses_data has {len(_thread_local._guesses_data)} items")
    for loc_desc, base_path in state.linux_known_save_locations.items():
        if cancellation_manager and cancellation_manager.check_cancelled():
            break
        if os.path.isdir(base_path):
            # Add the base path itself as a guess
            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, base_path, loc_desc, True, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
            
            # Also search for direct game name/abbreviation subdirectories
            for abbr_or_name in _thread_local._game_abbreviations:
                direct_game_path = os.path.join(base_path, abbr_or_name)
                _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, direct_game_path, f"{loc_desc}/DirectGameName/{abbr_or_name}", False, state.game_abbreviations_lower, state.current_steam_app_id, state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, state.other_game_abbreviations, state.game_name_cleaned, state)
            
            # Recursively search within the base path, unless it would duplicate Proton scans
            skip_double_compat = False
            try:
                if getattr(config, 'LINUX_SKIP_KNOWN_LOCATIONS_COMPAT_RECURSE_IF_PROTON_ENABLED', True):
                    proton_enabled = getattr(config, 'LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM', True) or getattr(config, 'LINUX_ENABLE_PROTON_SCAN_NONSTEAM', True)
                    if proton_enabled and 'steamapps' in base_path and 'compatdata' in base_path:
                        skip_double_compat = True
            except Exception:
                skip_double_compat = False

            if not skip_double_compat:
                _search_recursive(base_path, 0, _thread_local._guesses_data, _thread_local._checked_paths, cancellation_manager, state)
    # logging.info(f"LINUX_GUESS_SAVE_PATH: After XDG search, guesses_data has {len(_thread_local._guesses_data)} items")

    # 5. User's Home Directory (fallback)
    # logging.info(f"LINUX_GUESS_SAVE_PATH: Before home search, guesses_data has {len(_thread_local._guesses_data)} items")
    user_home = os.path.expanduser('~')
    # Avoid scanning home if disabled or already included in known locations
    try:
        home_in_known = any(os.path.normpath(base) == os.path.normpath(user_home) for base in state.linux_known_save_locations.values())
    except Exception:
        home_in_known = False
    if not getattr(config, 'LINUX_SKIP_HOME_FALLBACK', False) and not home_in_known:
        _search_recursive(user_home, 0, _thread_local._guesses_data, _thread_local._checked_paths, cancellation_manager, state)
    # logging.info(f"LINUX_GUESS_SAVE_PATH: After home search, guesses_data has {len(_thread_local._guesses_data)} items")

    
    if not _thread_local._guesses_data:
        logging.warning(f"LINUX_GUESS_SAVE_PATH: No potential save paths found for '{game_name}'.")
        return []

    sorted_guesses = sorted(_thread_local._guesses_data.items(), key=lambda item: _final_sort_key_linux(item, state))
    
    globals()['logging'].info(f"LINUX_GUESS_SAVE_PATH: Found {len(sorted_guesses)} potential paths for '{game_name}'. Top 5 (or less):")
    for i, item_tuple in enumerate(sorted_guesses[:5]):
        original_path = item_tuple[0]
        data_dict = item_tuple[1]
        source_description_set = data_dict.get('sources', set())
        source = next(iter(source_description_set)) if source_description_set else "UnknownSource"
        has_saves = data_dict.get('has_saves_hint', False)
        actual_score = -_final_sort_key_linux(item_tuple, state)[0]
        globals()['logging'].info(f"  {i+1}. {original_path} (Source: {source}, HasSaves: {has_saves}, Score: {actual_score})")

    return [
        (item[0], -_final_sort_key_linux(item, state)[0], bool(item[1].get('has_saves_hint', False)))
        for item in sorted_guesses
    ]

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
    game_name_cleaned: str,
    state: Optional[LinuxSearchState] = None
) -> None:
    """
    Adds a found path to the guesses_data dictionary after applying a strict filter.
    This version is self-contained and receives all dependencies as arguments.
    """
    normalized_path = os.path.normpath(os.path.abspath(path_found))
    path_found_lower = normalized_path.lower()
    path_lower_no_space = re.sub(r'\s+', '', path_found_lower)
    
    # logging.info(f"_add_guess: Processing path '{normalized_path}' with source '{source_description}'")

    # NUOVO: Controllo immediato per cartelle dei backup del programma
    try:
        import config
        backup_base_dir = config.get_default_backup_dir()
        if backup_base_dir and backup_base_dir.lower() in path_found_lower:
            logging.debug(f"Rejecting backup directory path: {normalized_path}")
            # Aggiungi solo ai checked_paths per evitare di riprocessarlo
            checked_paths.add(normalized_path)
            return  # Esci immediatamente, non aggiungere ai risultati
    except ImportError:
        logging.warning("Could not import config for backup directory check")
    except Exception as e:
        logging.warning(f"Error checking backup directory: {e}")

    passes_strict_filter = False
    reason_for_pass = ""
    current_game_name_explicitly_in_path = False

    # NUOVO: Controllo speciale per percorsi Proton - essere più permissivi
    is_proton_path = ("proton" in source_description.lower() or "pfx" in source_description.lower())
    # logging.info(f"_add_guess: Is Proton path: {is_proton_path}")
    
    # NUOVO: Controllo aggiuntivo per percorsi Proton con parole chiave specifiche del gioco
    if is_proton_path and not passes_strict_filter:
        # logging.info(f"_add_guess: Checking Proton path for game keywords...")
        # logging.info(f"_add_guess: Game abbreviations: {game_abbreviations_lower}")
        # logging.info(f"_add_guess: Game name cleaned: {game_name_cleaned}")
        # logging.info(f"_add_guess: Source description: {source_description}")
        
        # Se il source_description contiene parole chiave del gioco, aggiungi sempre
        for abbr in game_abbreviations_lower:
            # Controlla sia l'abbreviazione pulita che la versione originale
            if abbr.lower() in source_description.lower():
                passes_strict_filter = True
                reason_for_pass = f"Proton path with game keyword '{abbr}' in source description"
                # logging.info(f"Proton path '{normalized_path}' passed filter due to game keyword '{abbr}' in source")
                break
        
        # NUOVO: Controllo aggiuntivo per nomi con spazi e caratteri speciali
        if not passes_strict_filter and game_name_cleaned:
            # logging.info(f"_add_guess: Checking cleaned game name in source...")
            # Normalizza il source_description per il confronto
            source_clean = re.sub(r'[^a-zA-Z0-9\s]', '', source_description).lower()
            source_clean = re.sub(r'\s+', ' ', source_clean).strip()
            # logging.info(f"_add_guess: Cleaned source: '{source_clean}'")
            # logging.info(f"_add_guess: Game name cleaned: '{game_name_cleaned}'")
            
            # Controlla se il nome del gioco pulito è nel source_description pulito
            if game_name_cleaned in source_clean:
                passes_strict_filter = True
                reason_for_pass = f"Proton path with game name '{game_name_cleaned}' in source description"
                # logging.info(f"Proton path '{normalized_path}' passed filter due to game name '{game_name_cleaned}' in source")
            
            # NUOVO: Controlla anche se le parole del nome del gioco sono nel source
            elif not passes_strict_filter:
                # logging.info(f"_add_guess: Checking individual words from game name...")
                # Dividi il nome del gioco in parole
                game_words = game_name_cleaned.split()
                # logging.info(f"_add_guess: Game words: {game_words}")
                
                # Controlla se almeno 2 parole del gioco sono nel source
                matching_words = 0
                for word in game_words:
                    if len(word) > 2 and word in source_clean:  # Solo parole significative (>2 caratteri)
                        matching_words += 1
                        # logging.info(f"_add_guess: Found matching word '{word}' in source")
                
                if matching_words >= 2:  # Richiedi almeno 2 parole per evitare falsi positivi
                    passes_strict_filter = True
                    reason_for_pass = f"Proton path with {matching_words} matching game words in source description"
                    # logging.info(f"Proton path '{normalized_path}' passed filter due to {matching_words} matching game words")
            
            # Controlla anche le abbreviazioni pulite
            elif not passes_strict_filter:
                # logging.info(f"_add_guess: Checking cleaned abbreviations...")
                for abbr in game_abbreviations_lower:
                    abbr_clean = re.sub(r'[^a-zA-Z0-9\s]', '', abbr).lower()
                    abbr_clean = re.sub(r'\s+', ' ', abbr_clean).strip()
                    # logging.info(f"_add_guess: Checking abbreviation '{abbr}' -> cleaned '{abbr_clean}'")
                    if abbr_clean in source_clean:
                        passes_strict_filter = True
                        reason_for_pass = f"Proton path with cleaned game keyword '{abbr_clean}' in source description"
                        # logging.info(f"Proton path '{normalized_path}' passed filter due to cleaned game keyword '{abbr_clean}' in source")
                        break
    
    # Use passed argument instead of global variable
    for abbr in game_abbreviations_lower:
        # NUOVO: Evita di aggiungere percorsi solo perché contengono numeri o parole troppo corte
        if len(abbr) <= 2:
            continue  # Salta abbreviazioni troppo corte (numeri, parole singole)
            
        if abbr in path_found_lower or abbr in path_lower_no_space:
            current_game_name_explicitly_in_path = True
            passes_strict_filter = True
            reason_for_pass = f"Current game name/abbr '{abbr}' in path."
            # logging.info(f"_add_guess: Path passed filter due to game name/abbr '{abbr}' in path")
            break

    # NUOVO: Consenti match tramite acronimo del basename (es. 'FasterThanLight' -> 'FTL')
    if not passes_strict_filter:
        try:
            base_raw = os.path.basename(normalized_path)
            # Prima prova tokenizzazione su separatori
            parts = re.split(r'[\s_\-]+', base_raw)
            initials = ''
            if len(parts) > 1:
                initials = ''.join(p[0] for p in parts if p and p[0].isascii())
            else:
                # CamelCase tokens
                camel_tokens = re.findall(r'[A-Z0-9][a-z0-9]*', base_raw)
                if camel_tokens:
                    initials = ''.join(t[0] for t in camel_tokens if t and t[0].isascii())
            if initials:
                initials_lower = initials.lower()
                game_compact = (game_name_cleaned or '').replace(' ', '')
                if initials_lower in game_abbreviations_lower or initials_lower == game_compact:
                    passes_strict_filter = True
                    reason_for_pass = f"Basename acronym '{initials}' matches game"
        except Exception:
            pass
    
    # NUOVO: Controllo aggiuntivo per percorsi Proton - controlla le variazioni del nome del gioco
    if not passes_strict_filter and is_proton_path:
        # logging.info(f"_add_guess: Checking for game name variations in Proton source...")
        
        # Controlla se il source_description contiene variazioni del nome del gioco
        # Per "Baldur's Gate 3", cerca "baldur", "gate", "3" separatamente
        game_name_variations = []
        if game_name_cleaned:
            # Dividi il nome pulito in parole
            words = game_name_cleaned.split()
            for word in words:
                if len(word) > 2:  # Solo parole significative
                    game_name_variations.append(word)
        
        # logging.info(f"_add_guess: Game name variations to check: {game_name_variations}")
        
        # Controlla se almeno 2 parole del gioco sono nel source_description
        matching_variations = 0
        for variation in game_name_variations:
            if variation in source_description.lower():
                matching_variations += 1
                # logging.info(f"_add_guess: Found matching variation '{variation}' in source")
        
        if matching_variations >= 2:  # Richiedi almeno 2 parole per evitare falsi positivi
            passes_strict_filter = True
            reason_for_pass = f"Proton path with {matching_variations} matching game name variations in source"
            # logging.info(f"Proton path '{normalized_path}' passed filter due to {matching_variations} matching variations")
    
    # Check for common save subdirectories - MA SOLO con contesto del gioco
    if not passes_strict_filter:
        basename_lower = os.path.basename(path_found_lower)
        if basename_lower in linux_common_save_subdirs_lower:
            # NUOVO: Controlla se il percorso ha contesto del gioco
            path_has_game_context = False
            
            # Controlla se il percorso contiene il nome del gioco
            for abbr in game_abbreviations_lower:
                if len(abbr) > 2 and abbr in path_found_lower:
                    path_has_game_context = True
                    break
                # Controlla anche ignorando spazi nel path
                if len(abbr) > 2 and abbr in path_lower_no_space:
                    path_has_game_context = True
                    break
            
            # Controlla se il percorso contiene il nome del gioco pulito
            if not path_has_game_context and game_name_cleaned and game_name_cleaned in path_found_lower:
                path_has_game_context = True
            
            # SOLO se ha contesto del gioco, accetta la directory comune
            if path_has_game_context:
                passes_strict_filter = True
                reason_for_pass = "Common save subdirectory with game context."
                # logging.info(f"_add_guess: Path passed filter due to common save subdirectory with game context")
            else:
                # logging.debug(f"_add_guess: Rejecting common save subdirectory without game context: {normalized_path}")
                pass
    
    # NUOVO: Controllo speciale per directory comuni che potrebbero contenere publisher
    # MA SOLO se il percorso contiene effettivamente il nome del gioco
    if not passes_strict_filter:
        basename_lower = os.path.basename(path_found_lower)
        # Directory comuni che spesso contengono publisher/giochi
        common_container_dirs = {'unity3d', 'unreal', 'gamemaker', 'construct', 'godot'}
        if basename_lower in common_container_dirs:
            # IMPORTANTE: Accetta SOLO se il percorso contiene effettivamente il nome del gioco
            path_contains_game = False
            for abbr in game_abbreviations_lower:
                if len(abbr) > 2 and abbr in path_found_lower:
                    path_contains_game = True
                    break
            
            if path_contains_game:
                passes_strict_filter = True
                reason_for_pass = f"Common game engine directory '{basename_lower}' with game name in path"
            else:
                # NON aggiungere directory container generiche senza il nome del gioco
                logging.debug(f"_add_guess: Rejecting container directory without game name: {normalized_path}")
                passes_strict_filter = False
    
    # Check for other cleaned game names
    if not passes_strict_filter:
        for other_name in other_cleaned_game_names:
            if other_name in path_found_lower:
                passes_strict_filter = True
                reason_for_pass = f"Other game name '{other_name}' in path."
                # logging.info(f"_add_guess: Path passed filter due to other game name '{other_name}' in path")
                break
    
    # Check for other game abbreviations
    if not passes_strict_filter:
        for other_abbr in other_game_abbreviations:
            if other_abbr in path_found_lower:
                passes_strict_filter = True
                reason_for_pass = f"Other game abbreviation '{other_abbr}' in path."
                # logging.info(f"_add_guess: Path passed filter due to other game abbreviation '{other_abbr}' in path")
                break
    
    # Check for Steam AppID
    if not passes_strict_filter and current_steam_app_id:
        appid_str = str(current_steam_app_id)
        if appid_str in path_found_lower:
            passes_strict_filter = True
            reason_for_pass = f"Steam AppID '{appid_str}' in path."
            # logging.info(f"_add_guess: Path passed filter due to Steam AppID '{appid_str}' in path")
    
    # Final check for cleaned game name
    if not passes_strict_filter and game_name_cleaned:
        if game_name_cleaned in path_found_lower or game_name_cleaned in path_lower_no_space:
            passes_strict_filter = True
            reason_for_pass = f"Cleaned game name '{game_name_cleaned}' in path."
            # logging.info(f"_add_guess: Path passed filter due to cleaned game name '{game_name_cleaned}' in path")
        else:
            # Ultimo tentativo: confronto fuzzy sul basename per casi 'Hollow Knight' vs 'hollowknight'
            try:
                base_lower = os.path.basename(path_found_lower)
                if state and state.fuzz and state.THEFUZZ_AVAILABLE:
                    ratio = state.fuzz.token_set_ratio(game_name_cleaned, base_lower)
                    if ratio >= max(80, state.fuzzy_threshold_basename_match - 5):
                        passes_strict_filter = True
                        reason_for_pass = f"Fuzzy basename match {ratio}% between '{game_name_cleaned}' and '{base_lower}'"
            except Exception:
                pass
    
    # NUOVO: Per percorsi Proton, essere più permissivi se non abbiamo ancora passato il filtro
    if not passes_strict_filter and is_proton_path:
        # logging.info(f"_add_guess: Proton path '{normalized_path}' didn't pass initial filters, checking similarity...")
        # Controlla se il basename del percorso ha una similarità decente con il nome del gioco
        if state and state.fuzz and state.THEFUZZ_AVAILABLE:
            try:
                path_basename = os.path.basename(normalized_path)
                cleaned_folder = re.sub(r'[^a-zA-Z0-9\s]', '', path_basename).lower()
                cleaned_folder = re.sub(r'\s+', ' ', cleaned_folder).strip()
                if cleaned_folder:
                    # Calcola similarità con il nome del gioco pulito
                    similarity = state.fuzz.ratio(game_name_cleaned, cleaned_folder)
                    # logging.info(f"_add_guess: Proton path similarity: {similarity}% for '{cleaned_folder}' vs '{game_name_cleaned}'")
                    if similarity >= 70:  # Soglia più bassa per Proton
                        passes_strict_filter = True
                        reason_for_pass = f"Proton path with game name similarity ({similarity}%)"
                        # logging.debug(f"Proton path '{normalized_path}' passed filter with similarity {similarity}%")
                    
                    # NUOVO: Per percorsi Proton con alta similarità (>90%), aggiungi sempre
                    if similarity >= 90:
                        passes_strict_filter = True
                        reason_for_pass = f"Proton path with HIGH similarity ({similarity}%) - ALWAYS ADD"
                        # logging.info(f"Proton path '{normalized_path}' ALWAYS ADDED with HIGH similarity {similarity}%")
            except Exception as e:
                logging.warning(f"Error calculating Proton path similarity for '{normalized_path}': {e}")
        # else:
            # logging.info(f"_add_guess: Fuzzy matching not available for Proton path '{normalized_path}'")
    
    # logging.info(f"_add_guess: Final filter result for '{normalized_path}': {passes_strict_filter} (Reason: {reason_for_pass})")
    
    # Conservative fuzzy filter against other installed games (like Windows)
    if (passes_strict_filter and state and state.installed_steam_games_dict and state.fuzz and state.THEFUZZ_AVAILABLE
        and getattr(config, 'LINUX_ENABLE_FUZZY_FILTER_OTHER_GAMES', True)):
        try:
            path_basename = os.path.basename(normalized_path)
            cleaned_folder = re.sub(r'[^a-zA-Z0-9\s]', '', path_basename).lower()
            cleaned_folder = re.sub(r'\s+', ' ', cleaned_folder).strip()
            if cleaned_folder:
                for other_appid, other_info in state.installed_steam_games_dict.items():
                    if other_appid == str(current_steam_app_id):
                        continue
                    other_name = (other_info or {}).get('name', '')
                    if not other_name:
                        continue
                    cleaned_other = re.sub(r'[^a-zA-Z0-9\s]', '', other_name).lower()
                    cleaned_other = re.sub(r'\s+', ' ', cleaned_other).strip()
                    ratio = state.fuzz.token_set_ratio(cleaned_other, cleaned_folder)
                    if ratio >= 95:
                        # Reject this guess as it very likely belongs to another game
                        passes_strict_filter = False
                        reason_for_pass = f"Rejected: fuzzy matches other game '{other_name}' (ratio {ratio})"
                        # logging.info(f"_add_guess: Path rejected due to fuzzy match with other game '{other_name}' (ratio {ratio})")
                        break
        except Exception as e:
            logging.warning(f"Other-games fuzzy filter error for '{normalized_path}': {e}")

    # Add to guesses_data if passed filter
    if passes_strict_filter:
        guesses_data[normalized_path] = {
            "source": source_description,
            "sources": {source_description},
            "reason": reason_for_pass,
            "has_saves_hint": has_saves_hint_from_scan,
            "explicit_name_match": current_game_name_explicitly_in_path,
            "steam_app_id": str(current_steam_app_id) if current_steam_app_id else None
        }
        # logging.info(f"Added Proton path to guesses: {normalized_path} (Reason: {reason_for_pass})")
        pass
    # else:
        # logging.info(f"Proton path rejected by filter: {normalized_path} (Source: {source_description})")
    
    # Add to checked paths regardless of filter
    checked_paths.add(normalized_path)

def _search_recursive(
    start_dir: str,
    depth: int,
    guesses_data: dict,
    checked_paths: set,
    cancellation_manager: cancellation_utils.CancellationManager = None,
    state: Optional[LinuxSearchState] = None,
) -> None:
    # Access state (prefer passed state; fallback to thread-local for compatibility)
    if state is None:
        state = _build_state_from_thread_locals()

    linux_common_save_subdirs_lower = state.linux_common_save_subdirs_lower
    min_save_files_for_bonus_linux = state.min_save_files_for_bonus_linux
    known_companies_lower = state.known_companies_lower
    fuzzy_threshold_basename_match = state.fuzzy_threshold_basename_match
    fuzzy_threshold_path_match = state.fuzzy_threshold_path_match
    game_title_original_sig_words_for_seq = state.game_title_original_sig_words_for_seq
    max_sub_items_to_scan_linux = state.max_sub_items_to_scan_linux
    max_search_depth = state.max_search_depth_linux
    max_shallow_explore_depth_linux = state.max_shallow_explore_depth_linux
    
    # PERFORMANCE: Limite globale di directory esplorate per evitare ricorsioni eccessive
    if not hasattr(state, 'directories_explored'):
        state.directories_explored = 0
    
    state.directories_explored += 1
    try:
        MAX_DIRECTORIES_TO_EXPLORE = getattr(config, 'LINUX_MAX_DIRECTORIES_TO_EXPLORE', 200)
    except Exception:
        MAX_DIRECTORIES_TO_EXPLORE = 200
    
    if state.directories_explored > MAX_DIRECTORIES_TO_EXPLORE or (cancellation_manager and cancellation_manager.check_cancelled()):
        logging.info(f"PERFORMANCE: Stopping search after exploring {MAX_DIRECTORIES_TO_EXPLORE} directories")
        return

    # Base case 1: Profondita massima raggiunta
    if depth > max_search_depth:
        # logging.debug(f"EXIT _search_recursive (Max Depth): Path='{start_dir}', Depth={depth} > MaxDepthLimit={max_search_depth}.")
        return

    # Base case 2: Il percorso non e una directory o non e accessibile
    try:
        if not os.path.isdir(start_dir):
            # logging.debug(f"EXIT _search_recursive (Not Dir): Path='{start_dir}' is not a directory.")
            return
    except OSError as e:
        logging.warning(f"EXIT _search_recursive (OSERROR isdir): Path='{start_dir}', Error: {e}")
        return
    except Exception as e_generic_isdir: 
        logging.error(f"EXIT _search_recursive (EXCEPTION isdir): Path='{start_dir}', Error: {e_generic_isdir}", exc_info=True)
        return

    # Tentativo di aggiungere la directory corrente se rilevante
    basename_current_path_lower = os.path.basename(start_dir.lower()) 
    basename_current_path_raw = os.path.basename(start_dir)
    is_potential_current, has_saves_hint_current = _is_potential_save_dir(
        start_dir,
        state.game_name_cleaned,
        state.game_abbreviations_lower,
        linux_common_save_subdirs_lower,
        min_save_files_for_bonus_linux,
        state.max_files_to_scan_linux_hint,
        state.common_save_extensions_nodot,
        state.common_save_filenames_lower,
    )
    
    current_path_name_match_game = False
    current_path_name_match_company = False
    current_path_is_common_save_dir_flag = basename_current_path_lower in linux_common_save_subdirs_lower

    for abbr in state.game_abbreviations_lower: 
        if are_names_similar(abbr, basename_current_path_raw, 
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
    if is_potential_current or current_path_name_match_game:
        if current_path_name_match_game or current_path_name_match_company or current_path_is_common_save_dir_flag:
            should_add_current_path = True

    if should_add_current_path:
        # IMPORTANTE: Marca se questo percorso proviene dalla directory di installazione
        if hasattr(state, 'is_exploring_install_dir') and state.is_exploring_install_dir:
            specific_source_desc = f"InstallDirWalk/{os.path.relpath(start_dir, state.install_dir_root) if state.install_dir_root else start_dir} (Depth={depth})"
        else:
            specific_source_desc = f"{start_dir} (Depth={depth})"
            
        if current_path_name_match_game: specific_source_desc += " (GameMatch)"
        elif current_path_name_match_company: specific_source_desc += " (CompanyMatch)"
        elif current_path_is_common_save_dir_flag: specific_source_desc += " (CommonSaveDir)"
        elif is_potential_current: specific_source_desc += " (PotentialDirEvidence)"
        
        _add_guess(
            guesses_data,
            checked_paths,
            start_dir,
            specific_source_desc,
            has_saves_hint_current,
            state.game_abbreviations_lower,
            state.current_steam_app_id,
            linux_common_save_subdirs_lower,
            state.other_cleaned_game_names,
            state.other_game_abbreviations,
            state.game_name_cleaned,
            state,
        )

    # logging.debug(f"LISTDIR_ATTEMPT _search_recursive: Listing sub-items of '{start_dir}'")
    dir_contents = []
    try:
        dir_contents = os.listdir(start_dir)
        # log_items_display = dir_contents[:15] if len(dir_contents) > 15 else dir_contents
        # extra_items_count = len(dir_contents) - 15 if len(dir_contents) > 15 else 0
        # logging.debug(f"LISTDIR_SUCCESS _search_recursive: Found {len(dir_contents)} items in '{start_dir}'. Items (up to 15): {log_items_display}" + 
        #              (f" ...and {extra_items_count} more." if extra_items_count > 0 else ""))
    except OSError as e_listdir:
        logging.error(f"LISTDIR_ERROR _search_recursive: OSError listing '{start_dir}': {e_listdir}")
        # logging.debug(f"EXITING _search_recursive due to listdir error on '{start_dir}'")
        return

    # PERFORMANCE: Limita il numero di elementi processati per directory
    # Filtra via directory note da saltare per ridurre rumore
    linux_skip_directories = getattr(config, 'LINUX_SKIP_DIRECTORIES', set())
    filtered_dir_contents = []
    for name in dir_contents:
        try:
            if name.lower() in linux_skip_directories:
                continue
            filtered_dir_contents.append(name)
        except Exception:
            filtered_dir_contents.append(name)

    # Ordina per priorità: prima le directory che potrebbero contenere salvataggi
    dir_contents_limited = filtered_dir_contents[:max_sub_items_to_scan_linux] if len(filtered_dir_contents) > max_sub_items_to_scan_linux else filtered_dir_contents
    
    if len(dir_contents) > max_sub_items_to_scan_linux:
        logging.debug(f"PERFORMANCE: Limiting scan to {max_sub_items_to_scan_linux} items out of {len(dir_contents)} in {start_dir}")
    
    # Process each item in directory
    for item_name in dir_contents_limited:
        if cancellation_manager and cancellation_manager.check_cancelled():
            logging.debug(f"_search_recursive: Cancellation requested. Stopping search at '{start_dir}'")
            return
            
        item_path = os.path.join(start_dir, item_name)
        normalized_item_path = os.path.normpath(item_path)
        
        # Skip if already checked
        if normalized_item_path in checked_paths:
            continue
            
        checked_paths.add(normalized_item_path)
        
        try:
            # Skip non-directories
            if not os.path.isdir(item_path):
                continue
            
            # PERFORMANCE: Skip directories that are obviously irrelevant
            item_name_lower = item_name.lower()
            if item_name_lower in linux_skip_directories:
                logging.debug(f"Skipping irrelevant directory: {item_name}")
                continue
                
            # Check if this subdirectory is potentially a save directory
            sub_is_potential, _ = _is_potential_save_dir(
                item_path,
                state.game_name_cleaned,
                state.game_abbreviations_lower,
                linux_common_save_subdirs_lower,
                min_save_files_for_bonus_linux,
                state.max_files_to_scan_linux_hint,
                state.common_save_extensions_nodot,
                state.common_save_filenames_lower,
            )
            
            # Check name matches (item_name_lower already defined above for skip check)
            item_is_game_match = False
            for abbr in state.game_abbreviations_lower:
                
                # First try simple substring match
                if abbr in item_name_lower or item_name_lower in abbr:
                    item_is_game_match = True
                    logging.info(f"FOUND GAME MATCH: '{item_name}' matches abbreviation '{abbr}' (substring)")
                    break
                # Then try fuzzy/acronym-CamelCase matching using RAW name
                elif are_names_similar(abbr, item_name, 
                                       game_title_sig_words_for_seq=game_title_original_sig_words_for_seq,
                                       fuzzy_threshold=fuzzy_threshold_basename_match):
                    item_is_game_match = True
                    logging.info(f"FOUND GAME MATCH: '{item_name}' matches abbreviation '{abbr}' (fuzzy)")
                    break
            
            item_is_company_match = False
            if not item_is_game_match:
                # PERFORMANCE: Prima prova match esatti veloci
                if item_name_lower in known_companies_lower:
                    item_is_company_match = True
                    logging.info(f"FOUND COMPANY MATCH: '{item_name}' (exact)")
                else:
                    # PERFORMANCE: Fuzzy matching solo per company più comuni e con soglia più alta
                    common_companies = {'steam', 'valve', 'ea', 'ubisoft', 'activision', 'blizzard', 
                                      'bethesda', 'cd projekt red', 'square enix', 'capcom', 'sega',
                                      'bandai namco', 'paradox interactive', 'devolver digital'}
                    
                    for company_name_clean in known_companies_lower:
                        # Evita fuzzy per nomi publisher molto corti (<=3) per ridurre falsi positivi (es. 'ea')
                        if len(company_name_clean) <= 3:
                            continue
                        # Fuzzy SOLO per un sottoinsieme whitelist di publisher comuni
                        if company_name_clean in common_companies:
                            if are_names_similar(company_name_clean, item_name_lower, fuzzy_threshold=95):
                                item_is_company_match = True
                                logging.info(f"FOUND COMPANY MATCH: '{item_name}' matches '{company_name_clean}' (fuzzy)")
                                break
            
            item_is_common_save_dir = item_name_lower in linux_common_save_subdirs_lower
            # Temporary debug for Saves directory
            if item_is_common_save_dir and item_name_lower == 'saves':
                logging.info(f"FOUND COMMON SAVE DIR: '{item_name}' recognized as common save directory")
            
            # NUOVO: Controllo per directory container comuni (come unity3d)
            item_is_container_dir = False
            common_container_dirs = {'unity3d', 'unreal', 'gamemaker', 'construct', 'godot'}
            if item_name_lower in common_container_dirs:
                item_is_container_dir = True
            
            # Decision logic for recursion
            should_recurse_strong = False
            recursion_decision_reason = ""
            
            if item_is_game_match:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_game_match"
            elif item_is_company_match:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_company_match"
            elif item_is_common_save_dir:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_common_save_dir"
            elif item_is_container_dir:
                should_recurse_strong = True
                recursion_decision_reason = "item_is_container_dir"
            # NEW: Under Unity3D container (Company/Game structure), always go one level deeper
            elif 'unity3d' in start_dir.lower():
                should_recurse_strong = True
                recursion_decision_reason = "under_unity3d_container"
            elif sub_is_potential: 
                should_recurse_strong = True
                recursion_decision_reason = "sub_is_potential_itself"
            
            if should_recurse_strong:
                logging.info(f"RECURSION: STRONG into '{item_name}' (reason: {recursion_decision_reason}) at depth {depth + 1}")
                _search_recursive(
                    item_path, depth + 1, guesses_data, checked_paths, cancellation_manager, state
                )
            elif depth < max_shallow_explore_depth_linux:
                logging.info(f"RECURSION: SHALLOW into '{item_name}' at depth {depth + 1} (max_shallow: {max_shallow_explore_depth_linux})")
                _search_recursive(
                    item_path, depth + 1, guesses_data, checked_paths, cancellation_manager, state
                )
            else:
                logging.info(f"NO RECURSION into '{item_name}' - depth={depth}, max_shallow={max_shallow_explore_depth_linux}, game_match={item_is_game_match}, company_match={item_is_company_match}, container={item_is_container_dir}, common_save={item_is_common_save_dir}")

        except OSError as e_os_loop:
            logging.warning(f"_search_recursive OS Loop Error: Path='{start_dir}', Error processing item '{item_name}': {e_os_loop}")
        except Exception as e_generic_loop:
            logging.error(f"_search_recursive GENERIC Loop Error: Path='{start_dir}', Error processing item '{item_name}': {e_generic_loop}", exc_info=True)
    
    # logging.debug(f"EXITING _search_recursive: Path='{start_dir}', Depth={depth}")

# Funzione principale di ordinamento per i percorsi trovati
def _final_sort_key_linux(item_tuple, state: Optional[LinuxSearchState] = None):
    """
    Genera una chiave di ordinamento per i percorsi trovati
    """
    # Access state (prefer passed state; fallback to thread-local compatibility)
    if state is None:
        state = _build_state_from_thread_locals()

    game_name_cleaned = state.game_name_cleaned
    game_abbreviations_lower = state.game_abbreviations_lower
    game_title_original_sig_words_for_seq = state.game_title_original_sig_words_for_seq
    linux_common_save_subdirs_lower = state.linux_common_save_subdirs_lower
    known_companies_lower = state.known_companies_lower
    THEFUZZ_AVAILABLE = state.THEFUZZ_AVAILABLE
    fuzz = state.fuzz if THEFUZZ_AVAILABLE else None
    linux_banned_path_fragments_lower = state.linux_banned_path_fragments_lower

    normalized_path_key, data_dict = item_tuple
    original_path = normalized_path_key 
    source_description_set = data_dict.get('sources', set())
    source_description = next(iter(source_description_set)) if source_description_set else "UnknownSource"
    has_saves_hint_from_scan = data_dict.get('has_saves_hint', False)
    steam_userdata_path = getattr(_thread_local, '_steam_userdata_path', None)

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

    # Identifica il tipo di percorso per le penalità
    path_type = _identify_path_type(path_lower_for_sorting, source_description.lower(), steam_userdata_path)
    
    # Calcola le penalità aggressive
    penalties = _get_penalties(
        basename_lower, has_saves_hint_from_scan,
        path_type['is_prime_location'], path_type['is_steam_remote'], 
        path_type['is_install_dir_walk'], path_lower_for_sorting
    )

    # --- 1. PUNTEGGIO BASE PER LOCAZIONE ---
    in_xdg_config = xdg_config_home.lower() in path_lower_for_sorting
    in_xdg_data = xdg_data_home.lower() in path_lower_for_sorting
    in_steam_compat = (steam_compatdata_generic_part in path_lower_for_sorting and "pfx" in path_lower_for_sorting)
    in_steam_userdata = (steam_userdata_generic_part in path_lower_for_sorting)
    if xdg_config_home.lower() in path_lower_for_sorting:
        score += _score_xdg_config_home_bonus
    elif xdg_data_home.lower() in path_lower_for_sorting:
        score += _score_xdg_data_home_bonus
    elif steam_compatdata_generic_part in path_lower_for_sorting and "pfx" in path_lower_for_sorting:
        score += 600 
    elif steam_userdata_generic_part in path_lower_for_sorting:
        score += 500
    elif "documents" in path_lower_for_sorting: 
        score += 200
    elif "InstallDirWalk" in source_description: 
        score -= 500  # Penalità per directory di installazione (come Windows) 
    else:
        score += 100 

    # --- 2. BONUS PER CONTENUTO DI SALVATAGGIO (has_saves_hint_from_scan) ---
    if has_saves_hint_from_scan: 
        score += _score_has_save_files

    # --- 3. BONUS PER NOMI DI CARTELLE RILEVANTI (BASENAME) ---
    is_common_save_subdir_basename = basename_lower in linux_common_save_subdirs_lower
    awarded_parent_bonus_in_common_save = False
    if is_common_save_subdir_basename:
        # Stronger base for actual 'saves' directories
        score += _score_save_dir_match

        # Evaluate parent folder context; handle hidden dot-folders gracefully
        parent_basename_stripped = parent_basename_lower.lstrip('.')
        parent_is_game_abbr = (
            parent_basename_lower in game_abbreviations_lower or
            parent_basename_stripped in game_abbreviations_lower
        )
        parent_is_company = parent_basename_lower in known_companies_lower

        if parent_is_game_abbr:
            score += _score_perfect_match_bonus
            awarded_parent_bonus_in_common_save = True
        elif parent_is_company:
            score += _score_company_name_match
            awarded_parent_bonus_in_common_save = True

    # --- 4. BONUS PER SIMILARITÀ NOME GIOCO (SUL BASENAME) ---
    cleaned_folder_basename = clean_for_comparison(basename)
    exact_match_bonus = 0
    fuzzy_bonus = 0

    if game_name_cleaned == cleaned_folder_basename:
        exact_match_bonus = 400
    elif THEFUZZ_AVAILABLE and fuzz:
        similarity_ratio_basename = fuzz.ratio(game_name_cleaned, cleaned_folder_basename)
        if similarity_ratio_basename > 85: 
            fuzzy_bonus = 300
        elif similarity_ratio_basename > 70:
            fuzzy_bonus = 150
    score += exact_match_bonus + fuzzy_bonus

    # --- 4.5. PENALITÀ GENERICA PER CARTELLE "NUDE" NELLA HOME (senza evidenza saves) ---
    # Evita di favorire cartelle chiamate esattamente come il gioco sparse nella home
    # se non sono in XDG/Steam e non hanno evidenza file di salvataggio
    try:
        in_home_but_not_xdg = (path_lower_for_sorting.startswith(home_dir.lower()) and not in_xdg_config and not in_xdg_data and not in_steam_compat and not in_steam_userdata)
        basename_is_game = (
            cleaned_folder_basename == game_name_cleaned or
            basename_lower in game_abbreviations_lower
        )
        # Inoltre, se l'acronimo delle iniziali del basename corrisponde esattamente al nome breve (es. 'FTL'), considera "nuda"
        acronym_basename = ''.join([w[0] for w in re.findall(r'[A-Za-z0-9]+', os.path.basename(original_path)) if w])
        acronym_matches_game = False
        try:
            if game_name_cleaned and 2 <= len(acronym_basename) <= 6:
                acronym_matches_game = (acronym_basename.upper() == game_name_cleaned.replace(' ', '').upper())
        except Exception:
            acronym_matches_game = False
        if in_home_but_not_xdg and (basename_is_game or acronym_matches_game) and not has_saves_hint_from_scan:
            score -= 700
    except Exception:
        pass

    # --- 5. BONUS PER MATCH CON ABBREVIAZIONI ---
    if basename_lower in game_abbreviations_lower:
        score += 350

    # --- 6. BONUS PER MATCH CON AZIENDA (BASENAME) ---
    if basename_lower in known_companies_lower:
        score += 200

    # --- 7. BONUS PER MATCH CON AZIENDA (PARENT BASENAME) ---
    if not awarded_parent_bonus_in_common_save and parent_basename_lower in known_companies_lower:
        score += 100

    # --- 8. BONUS PER MATCH CON GIOCO (PARENT BASENAME) ---
    if not awarded_parent_bonus_in_common_save:
        parent_basename_stripped = parent_basename_lower.lstrip('.')
        if parent_basename_lower in game_abbreviations_lower or parent_basename_stripped in game_abbreviations_lower:
            score += 150

    # --- 9. BONUS PER PATH CONTENENTE GAME_NAME_CLEANED ---
    if game_name_cleaned and game_name_cleaned.lower() in path_lower_for_sorting:
        score += 250

    # --- 10. BONUS PER PATH CONTENENTE STEAM APPID (se presente) ---
    steam_app_id = data_dict.get('steam_app_id', None)
    if steam_app_id and steam_app_id in path_lower_for_sorting:
        score += 300

    # --- 11. APPLICA PENALITÀ AGGRESSIVE ---
    score += penalties

    # --- 11.5. PENALITÀ AGGIUNTIVA PER INSTALL DIR WALK SENZA SAVES (come Windows) ---
    if "InstallDirWalk" in source_description and not has_saves_hint_from_scan:
        score -= 300  # Penalità aggiuntiva per install dir senza saves

    # --- 12. MALUS PER PATH CONTENENTE FRAMMENTI BANNATI ---
    for banned_fragment in linux_banned_path_fragments_lower:
        if banned_fragment in path_lower_for_sorting:
            score -= 1000
            break

    # --- 13. MALUS PER PATH TROPPO LUNGO ---
    path_length = len(original_path)
    if path_length > 200:
        score -= 50 * (path_length - 200) // 10

    # --- 14. MALUS PER PATH TROPPO PROFONDO ---
    path_depth = original_path.count(os.sep)
    if path_depth > 10:
        score -= 20 * (path_depth - 10)

    # --- 15. APPLICA CAP PER STEAM USERDATA (come Windows) ---
    if _is_in_userdata(path_lower_for_sorting, steam_userdata_path):
        # Applica cap per userdata (ma non per Steam remote che ha priorità speciale)
        if not path_type['is_steam_remote']:
            score = min(score, state.MAX_USERDATA_SCORE)
            
        # NUOVO: Applica cap anche alla cartella remote per "ucciderla" come nel vecchio codice
        if path_type['is_steam_remote']:
            # La cartella remote riceve punti ma viene limitata dal cap
            # Questo la "uccide" e la fa scendere sotto i percorsi corretti
            score = min(score, state.MAX_USERDATA_SCORE)

    # --- 16. BONUS PER PERCORSI PROTON (NUOVO) ---
    if "proton" in source_description.lower() or "pfx" in path_lower_for_sorting:
        score += 200  # Bonus per percorsi Proton
        # logging.debug(f"Applied Proton bonus (+200) to: {original_path}")
        
        # Bonus extra per percorsi Windows standard trovati in Proton
        if any(windows_path in path_lower_for_sorting for windows_path in [
            'appdata/local', 'appdata/roaming', 'appdata/locallow',
            'documents', 'saved games', 'my games', 'my documents'
        ]):
            score += 150  # Bonus per percorsi Windows standard
            # logging.debug(f"Applied Windows standard path bonus (+150) to: {original_path}")

    # --- 17. BONUS PER SOURCE DESCRIPTION ---
    if "Proton" in source_description:
        score += 100
    elif "Steam" in source_description:
        score += 80
    elif "Manual" in source_description:
        score += 50

    return (-score, path_lower_for_sorting)

def _get_penalties(
    basename_lower: str, contains_saves: bool, 
    is_prime_location: bool, is_steam_remote: bool, is_install_dir_walk: bool,
    path_lower: str = None
) -> int:
    """
    Calcola le penalità aggressive per cartelle problematiche (come Windows).
    """
    penalty = 0
    
    # NUOVO: Penalità massima per cartelle dei backup del programma
    if path_lower:
        try:
            # Importa config solo quando necessario per evitare dipendenze circolari
            import config
            backup_base_dir = config.get_default_backup_dir()
            if backup_base_dir and backup_base_dir.lower() in path_lower:
                penalty += BACKUP_DIRECTORY_PENALTY
                # logging.debug(f"Applied backup directory penalty (-9999) to: {path_lower}")
                return penalty  # Ritorna subito, non serve controllare altro
        except ImportError:
            logging.warning("Could not import config for backup directory check")
        except Exception as e:
            logging.warning(f"Error checking backup directory: {e}")
    
    # Penalità per cartella 'data'
    if (basename_lower == 'data' and not contains_saves and 
        not is_prime_location and not is_steam_remote):
        penalty += DATA_FOLDER_PENALTY
        
    # Penalità per altre cartelle generiche
    elif (basename_lower in ['settings', 'config', 'cache', 'logs'] and 
          not contains_saves and not is_prime_location and not is_steam_remote):
        penalty += GENERIC_FOLDER_PENALTY
        
    # Penalità per cartelle di installazione
    if is_install_dir_walk:
        penalty += -500  # Penalità base per install dir walk
        
        # Penalità aggiuntiva se non contiene saves
        if not contains_saves:
            penalty += INSTALL_DIR_NO_SAVES_PENALTY
            
        # Penalità per cartelle generiche nell'install dir
        if basename_lower in ['data', 'config', 'settings', 'cache']:
            penalty += INSTALL_DIR_GENERIC_PENALTY
            
        # Penalità specifica per cartelle problematiche note
        if basename_lower in ['mcc', 'halo', 'minecraft']:
            penalty += INSTALL_DIR_MCC_PENALTY
    
    return penalty

def _search_proton_prefix_deep(compatdata_path: str, appid: str, state: LinuxSearchState, cancellation_manager=None):
    """
    Ricerca profonda nella struttura Wine prefix per trovare percorsi di salvataggio Windows.
    """
    try:
        # Percorsi Windows standard da cercare nel Wine prefix
        windows_standard_paths = [
            "drive_c/users/steamuser/AppData/Local",
            "drive_c/users/steamuser/AppData/Roaming", 
            "drive_c/users/steamuser/Documents",
            "drive_c/users/steamuser/Saved Games",
            "drive_c/users/steamuser/My Documents",
            "drive_c/users/steamuser/AppData/LocalLow",
            "drive_c/users/steamuser/AppData/Roaming",
            "drive_c/users/steamuser/My Games",
            "drive_c/users/steamuser/My Documents/My Games"
        ]
        
        # Cerca anche varianti del nome utente
        wine_user_variants = ["steamuser", "steam", "user", "default", "wine"]
        
        for user_variant in wine_user_variants:
            for windows_path in windows_standard_paths:
                # Sostituisci 'steamuser' con la variante corrente
                path_with_variant = windows_path.replace("steamuser", user_variant)
                full_path = os.path.join(compatdata_path, path_with_variant)
                
                if os.path.isdir(full_path):
                    # logging.debug(f"Found Windows path in Proton: {full_path}")
                    
                    # Aggiungi il percorso base
                    _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                              full_path, f"Proton Windows Path/{path_with_variant} ({appid})", 
                              False, state.game_abbreviations_lower, state.current_steam_app_id, 
                              state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                              state.other_game_abbreviations, state.game_name_cleaned, state)
                    
                    # Ricerca ricorsiva più profonda per questo percorso Windows
                    _search_recursive(full_path, 0, _thread_local._guesses_data, 
                                   _thread_local._checked_paths, cancellation_manager, state)
                    
                    # Cerca direttamente per il nome del gioco in questo percorso
                    for abbr_or_name in _thread_local._game_abbreviations:
                        game_specific_path = os.path.join(full_path, abbr_or_name)
                        if os.path.isdir(game_specific_path):
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                      game_specific_path, f"Proton Windows Path/{path_with_variant}/{abbr_or_name} ({appid})", 
                                      False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                      state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                      state.other_game_abbreviations, state.game_name_cleaned, state)
                            
                            # Ricerca ricorsiva anche nella cartella specifica del gioco
                            _search_recursive(game_specific_path, 0, _thread_local._guesses_data, 
                                           _thread_local._checked_paths, cancellation_manager, state)
        
        # Ricerca aggiuntiva per cartelle specifiche del gioco in posizioni comuni
        common_game_locations = [
            "drive_c/Program Files",
            "drive_c/Program Files (x86)", 
            "drive_c/Users/steamuser/AppData/Local",
            "drive_c/Users/steamuser/AppData/Roaming",
            "drive_c/Users/steamuser/Documents",
            "drive_c/Users/steamuser/Saved Games"
        ]
        
        for location in common_game_locations:
            for user_variant in wine_user_variants:
                location_with_variant = location.replace("steamuser", user_variant)
                full_location = os.path.join(compatdata_path, location_with_variant)
                
                if os.path.isdir(full_location):
                    # Cerca per il nome del gioco in questa posizione
                    for abbr_or_name in _thread_local._game_abbreviations:
                        game_path = os.path.join(full_location, abbr_or_name)
                        if os.path.isdir(game_path):
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                      game_path, f"Proton Game Location/{location_with_variant}/{abbr_or_name} ({appid})", 
                                      False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                      state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                      state.other_game_abbreviations, state.game_name_cleaned, state)
                            
                            # Ricerca ricorsiva nella cartella del gioco
                            _search_recursive(game_path, 0, _thread_local._guesses_data, 
                                           _thread_local._checked_paths, cancellation_manager, state)
                            
    except Exception as e:
        logging.error(f"Error in _search_proton_prefix_deep for {compatdata_path}: {e}")

def _search_snap_games(state: LinuxSearchState, cancellation_manager=None):
    """Cerca percorsi di salvataggio per giochi Snap."""
    try:
        user_home = os.path.expanduser('~')
        snap_base = os.path.join(user_home, 'snap')
        
        if not os.path.isdir(snap_base):
            return
            
        # Cerca per ogni abbreviazione/nome del gioco
        for game_variant in _thread_local._game_abbreviations:
            if cancellation_manager and cancellation_manager.check_cancelled():
                return
                
            # Percorso base del gioco Snap
            snap_game_path = os.path.join(snap_base, game_variant)
            if os.path.isdir(snap_game_path):
                # Cerca nella directory 'current'
                current_path = os.path.join(snap_game_path, 'current')
                if os.path.isdir(current_path):
                    # Percorsi standard Snap per i salvataggi
                    snap_save_paths = [
                        os.path.join(current_path, '.local', 'share', game_variant),
                        os.path.join(current_path, '.config', game_variant),
                        os.path.join(current_path, '.local', 'share'),
                        os.path.join(current_path, '.config'),
                    ]
                    
                    for snap_path in snap_save_paths:
                        if os.path.isdir(snap_path):
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                      snap_path, f"Snap Game/{game_variant}/{os.path.relpath(snap_path, current_path)}", 
                                      False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                      state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                      state.other_game_abbreviations, state.game_name_cleaned, state)
                            
                            # Ricerca ricorsiva nella directory Snap
                            _search_recursive(snap_path, 0, _thread_local._guesses_data, 
                                           _thread_local._checked_paths, cancellation_manager, state)
        
        # Ricerca generica in tutte le directory Snap (per nomi di giochi che non corrispondono esattamente)
        try:
            snap_dirs = [d for d in os.listdir(snap_base) if os.path.isdir(os.path.join(snap_base, d))]
            for snap_dir in snap_dirs:
                if cancellation_manager and cancellation_manager.check_cancelled():
                    return
                    
                # Controlla se il nome della directory Snap è simile al gioco
                is_similar = False
                for game_variant in _thread_local._game_abbreviations:
                    if are_names_similar(game_variant, snap_dir, 
                                        game_title_sig_words_for_seq=state.game_title_original_sig_words_for_seq,
                                        fuzzy_threshold=state.fuzzy_threshold_basename_match):
                        is_similar = True
                        break
                
                if is_similar:
                    current_path = os.path.join(snap_base, snap_dir, 'current')
                    if os.path.isdir(current_path):
                        # Percorsi standard Snap
                        snap_save_paths = [
                            os.path.join(current_path, '.local', 'share', snap_dir),
                            os.path.join(current_path, '.config', snap_dir),
                            os.path.join(current_path, '.local', 'share'),
                            os.path.join(current_path, '.config'),
                        ]
                        
                        for snap_path in snap_save_paths:
                            if os.path.isdir(snap_path):
                                _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                          snap_path, f"Snap Game/{snap_dir}/{os.path.relpath(snap_path, current_path)}", 
                                          False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                          state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                          state.other_game_abbreviations, state.game_name_cleaned, state)
                                
                                _search_recursive(snap_path, 0, _thread_local._guesses_data, 
                                               _thread_local._checked_paths, cancellation_manager, state)
        except OSError:
            pass  # Ignora errori di accesso alle directory
            
    except Exception as e:
        logging.error(f"Error in _search_snap_games: {e}")


def _search_proton_for_non_steam_games(state: LinuxSearchState, cancellation_manager=None):
    """
    Cerca percorsi Proton per giochi non-Steam, esplorando tutti i compatdata disponibili.
    """
    try:
        steam_base_paths_for_compat = [
            os.path.join(os.path.expanduser("~"), ".steam", "steam"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "Steam"),
            os.path.join(os.path.expanduser("~"), ".steam", "root"),
            os.path.join(os.path.expanduser("~"), ".steam", "debian-installation"),
            os.path.join(os.path.expanduser("~"), ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")
        ]
        
        for steam_base in steam_base_paths_for_compat:
            compatdata_base = os.path.join(steam_base, 'steamapps', 'compatdata')
            if not os.path.isdir(compatdata_base):
                continue
                
            # Lista tutti i compatdata disponibili
            try:
                compatdata_folders = [d for d in os.listdir(compatdata_base) 
                                    if d.isdigit() and os.path.isdir(os.path.join(compatdata_base, d))]
            except (OSError, PermissionError):
                continue
                
            # Limit how many compatdata appids to scan for performance
            max_appids = getattr(config, 'LINUX_MAX_COMPATDATA_APPIDS_NONSTEAM', 8)
            scanned = 0
            for appid_folder in compatdata_folders:
                if cancellation_manager and cancellation_manager.check_cancelled():
                    return
                    
                pfx_path = os.path.join(compatdata_base, appid_folder, 'pfx')
                if os.path.isdir(pfx_path):
                    # Cerca percorsi Windows standard in questo prefix
                    _search_proton_prefix_deep(pfx_path, appid_folder, state, cancellation_manager)
                    
                    # Cerca anche direttamente per il nome del gioco corrente
                    _search_game_specific_in_proton(pfx_path, appid_folder, state, cancellation_manager)
                    scanned += 1
                    if scanned >= max_appids:
                        break
                
    except Exception as e:
        logging.error(f"Error in _search_proton_for_non_steam_games: {e}")

def _search_fuzzy_matches_in_proton_dir(base_path: str, path_variant: str, appid: str, state: LinuxSearchState, cancellation_manager=None):
    """Helper function per la ricerca fuzzy in directory Proton (versione ottimizzata)."""
    try:
        import thefuzz
        items_found = os.listdir(base_path)
        
        for item in items_found:
            item_path = os.path.join(base_path, item)
            if not os.path.isdir(item_path):
                continue
                
            # Calcola similarità con tutte le varianti del nome del gioco
            best_match_score = 0
            for game_name_variant in _thread_local._game_abbreviations:
                normalized_item = item.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                normalized_game = game_name_variant.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                similarity = thefuzz.fuzz.ratio(normalized_item, normalized_game)
                if similarity > best_match_score:
                    best_match_score = similarity
            
            # Se la similarità è alta (>70%), considera una corrispondenza
            if best_match_score > 70:
                _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                          item_path, f"Proton Fuzzy Match/{path_variant}/{item} (AppID: {appid}, Score: {best_match_score}%)", 
                          False, state.game_abbreviations_lower, state.current_steam_app_id, 
                          state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                          state.other_game_abbreviations, state.game_name_cleaned, state)
                
                _search_recursive(item_path, 0, _thread_local._guesses_data, 
                               _thread_local._checked_paths, cancellation_manager, state)
                
                # Cerca sottocartelle di salvataggio
                for save_subdir in state.linux_common_save_subdirs_lower:
                    save_path = os.path.join(item_path, save_subdir)
                    if os.path.isdir(save_path):
                        _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                  save_path, f"Proton Fuzzy Match/{path_variant}/{item}/{save_subdir} (AppID: {appid})", 
                                  False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                  state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                  state.other_game_abbreviations, state.game_name_cleaned, state)
                        _search_recursive(save_path, 0, _thread_local._guesses_data, 
                                       _thread_local._checked_paths, cancellation_manager, state)
            
            # Cerca anche nelle sottocartelle (per casi come "Larian Studios/Baldur's Gate 3")
            try:
                sub_items = os.listdir(item_path)
                for sub_item in sub_items:
                    sub_item_path = os.path.join(item_path, sub_item)
                    if os.path.isdir(sub_item_path):
                        best_sub_match_score = 0
                        for game_name_variant in _thread_local._game_abbreviations:
                            normalized_sub_item = sub_item.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                            normalized_game = game_name_variant.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                            sub_similarity = thefuzz.fuzz.ratio(normalized_sub_item, normalized_game)
                            if sub_similarity > best_sub_match_score:
                                best_sub_match_score = sub_similarity
                        
                        if best_sub_match_score > 70:
                            _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                      sub_item_path, f"Proton Sub-Dir Match/{path_variant}/{item}/{sub_item} (AppID: {appid}, Score: {best_sub_match_score}%)", 
                                      False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                      state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                      state.other_game_abbreviations, state.game_name_cleaned, state)
                            _search_recursive(sub_item_path, 0, _thread_local._guesses_data, 
                                           _thread_local._checked_paths, cancellation_manager, state)
            except OSError:
                continue
                
    except ImportError:
        pass  # thefuzz non disponibile
    except OSError:
        pass  # Errore nell'accesso alla directory

def _search_game_specific_in_proton(pfx_path: str, appid: str, state: LinuxSearchState, cancellation_manager=None):
    """
    Cerca specificamente per il gioco corrente in un prefix Proton.
    """
    try:
        # Ricerca specifica del gioco nel prefix Proton
        # Percorsi Windows dove cercare il gioco specifico
        game_search_paths = [
            "drive_c/users/steamuser/AppData/Local",
            "drive_c/users/steamuser/AppData/Roaming",
            "drive_c/users/steamuser/Documents",
            "drive_c/users/steamuser/Saved Games",
            "drive_c/users/steamuser/My Games",
            "drive_c/Program Files",
            "drive_c/Program Files (x86)"
        ]
        
        # Varianti del nome utente
        user_variants = ["steamuser", "steam", "user", "default", "wine"]
        
        for user_variant in user_variants:
            for base_path in game_search_paths:
                path_with_variant = base_path.replace("steamuser", user_variant)
                full_base_path = os.path.join(pfx_path, path_with_variant)
                
                if not os.path.isdir(full_base_path):
                    continue
                
                # Cerca per il nome del gioco corrente
                for game_name_variant in _thread_local._game_abbreviations:
                    game_path = os.path.join(full_base_path, game_name_variant)
                    if os.path.isdir(game_path):
                        # Aggiungi il percorso principale del gioco
                        _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                  game_path, f"Proton Non-Steam Game/{path_with_variant}/{game_name_variant} (AppID: {appid})", 
                                  False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                  state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                  state.other_game_abbreviations, state.game_name_cleaned, state)
                        
                        # Ricerca ricorsiva nella cartella del gioco
                        _search_recursive(game_path, 0, _thread_local._guesses_data, 
                                       _thread_local._checked_paths, cancellation_manager, state)
                        
                        # Cerca anche sottocartelle comuni di salvataggio
                        common_save_subdirs = ['Saves', 'Save', 'Savegames', 'SaveGames', 'PlayerProfiles', 'Profiles']
                        for save_subdir in common_save_subdirs:
                            save_path = os.path.join(game_path, save_subdir)
                            if os.path.isdir(save_path):
                                _add_guess(_thread_local._guesses_data, _thread_local._checked_paths, 
                                          save_path, f"Proton Non-Steam Game/{path_with_variant}/{game_name_variant}/{save_subdir} (AppID: {appid})", 
                                          False, state.game_abbreviations_lower, state.current_steam_app_id, 
                                          state.linux_common_save_subdirs_lower, state.other_cleaned_game_names, 
                                          state.other_game_abbreviations, state.game_name_cleaned, state)
                                
                                # Ricerca ricorsiva anche nelle sottocartelle di salvataggio
                                _search_recursive(save_path, 0, _thread_local._guesses_data, 
                                               _thread_local._checked_paths, cancellation_manager, state)
                
                # Cerca anche per corrispondenze fuzzy
                _search_fuzzy_matches_in_proton_dir(full_base_path, path_with_variant, appid, state, cancellation_manager)
    except Exception as e:
        logging.error(f"Error in _search_game_specific_in_proton for {pfx_path}: {e}")
