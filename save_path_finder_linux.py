# save_path_finder_linux.py
"""
Linux save path finder - Refactored to use LinuxSearchState as single source of truth.
No more global variables or thread-local storage.
"""
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Tuple, List, Set
import cancellation_utils

# Importazione robusta di thefuzz
_fuzz_module = None
_THEFUZZ_AVAILABLE = False
try:
    from thefuzz import fuzz as _fuzz_module
    _THEFUZZ_AVAILABLE = True
    logging.info("Successfully imported 'thefuzz'. Fuzzy matching will be available for Linux path finding.")
except ImportError:
    _THEFUZZ_AVAILABLE = False
    logging.warning("'thefuzz' library not found. Fuzzy matching will be disabled for Linux path finding.")

import config


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class LinuxSearchState:
    """Single source of truth for all search state and configuration."""
    # Game identification
    game_name_cleaned: str
    game_abbreviations: List[str] = field(default_factory=list)
    game_abbreviations_lower: Set[str] = field(default_factory=set)
    game_title_original_sig_words_for_seq: List[str] = field(default_factory=list)
    
    # Configuration from config.py
    known_companies_lower: List[str] = field(default_factory=list)
    linux_common_save_subdirs_lower: Set[str] = field(default_factory=set)
    linux_banned_path_fragments_lower: Set[str] = field(default_factory=set)
    common_save_extensions: Set[str] = field(default_factory=set)
    common_save_extensions_nodot: Set[str] = field(default_factory=set)
    common_save_filenames_lower: Set[str] = field(default_factory=set)
    proton_user_path_fragments: List[str] = field(default_factory=list)
    linux_known_save_locations: Dict[str, str] = field(default_factory=dict)
    
    # Other games (for filtering)
    installed_steam_games_dict: Optional[Dict] = None
    other_cleaned_game_names: Set[str] = field(default_factory=set)
    other_game_abbreviations: Set[str] = field(default_factory=set)
    
    # Steam/Proton specific
    current_steam_app_id: Optional[str] = None
    steam_userdata_path: Optional[str] = None
    
    # Search limits
    max_files_to_scan_linux_hint: int = 100
    min_save_files_for_bonus_linux: int = 2
    max_sub_items_to_scan_linux: int = 50
    max_shallow_explore_depth_linux: int = 1
    max_search_depth_linux: int = 10
    
    # Fuzzy matching
    fuzzy_threshold_basename_match: int = 85
    fuzzy_threshold_path_match: int = 75
    THEFUZZ_AVAILABLE: bool = False
    fuzz: Optional[Any] = None
    
    # Scoring caps
    MAX_USERDATA_SCORE: int = 1100
    
    # Runtime state (mutable during search)
    is_exploring_install_dir: bool = False
    install_dir_root: Optional[str] = None
    directories_explored: int = 0
    
    # Results containers
    guesses_data: Dict[str, Dict] = field(default_factory=dict)
    checked_paths: Set[str] = field(default_factory=set)


class LinuxGameContext:
    """Input context for a game search."""
    def __init__(self, game_name, game_install_dir=None, appid=None, steam_userdata_path=None,
                 steam_id3_to_use=None, is_steam_game=True, installed_steam_games_dict=None):
        self.game_name = game_name
        self.game_install_dir = game_install_dir
        self.appid = appid
        self.steam_userdata_path = steam_userdata_path
        self.steam_id3_to_use = steam_id3_to_use
        self.is_steam_game = is_steam_game
        self.installed_steam_games_dict = installed_steam_games_dict


class LinuxSavePathFinder:
    """High-level API for finding save paths."""
    def __init__(self, context: LinuxGameContext, cancellation_manager=None):
        self.context = context
        self.cancellation_manager = cancellation_manager

    def find_save_paths(self):
        return guess_save_path(
            game_name=self.context.game_name,
            game_install_dir=self.context.game_install_dir,
            appid=self.context.appid,
            steam_userdata_path=self.context.steam_userdata_path,
            steam_id3_to_use=self.context.steam_id3_to_use,
            is_steam_game=self.context.is_steam_game,
            installed_steam_games_dict=self.context.installed_steam_games_dict,
            cancellation_manager=self.cancellation_manager,
        )


class LinuxPathSearchEngine:
    """Compatibility wrapper - delegates to guess_save_path."""
    def __init__(self, context: LinuxGameContext):
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


# =============================================================================
# SCORING CONSTANTS
# =============================================================================

SCORE_GAME_NAME_MATCH = 1200
SCORE_COMPANY_NAME_MATCH = 150
SCORE_SAVE_DIR_MATCH = 800
SCORE_HAS_SAVE_FILES = 1500
SCORE_PERFECT_MATCH_BONUS = 600
SCORE_XDG_DATA_HOME_BONUS = 500
SCORE_XDG_CONFIG_HOME_BONUS = 600

DATA_FOLDER_PENALTY = -800
GENERIC_FOLDER_PENALTY = -400
INSTALL_DIR_NO_SAVES_PENALTY = -800
INSTALL_DIR_GENERIC_PENALTY = -600
INSTALL_DIR_MCC_PENALTY = -1000
BACKUP_DIRECTORY_PENALTY = -9999


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clean_for_comparison(name: str) -> str:
    """Clean a name for comparison - removes symbols, normalizes separators, lowercase."""
    if not isinstance(name, str):
        return ""
    name_cleaned = re.sub(r'[™®©:]', '', name)
    name_cleaned = re.sub(r'[-_]', ' ', name_cleaned)
    name_cleaned = re.sub(r'\s+', ' ', name_cleaned).strip()
    return name_cleaned.lower()


def generate_abbreviations(game_name_raw: str, game_install_dir_raw: str = None) -> List[str]:
    """Generate possible abbreviations/alternative names for a game."""
    abbreviations = set()
    if not game_name_raw:
        return []

    base_name_cleaned = clean_for_comparison(game_name_raw)
    if base_name_cleaned:
        abbreviations.add(base_name_cleaned)
        name_no_space = base_name_cleaned.replace(' ', '')
        if name_no_space != base_name_cleaned and len(name_no_space) > 1:
            abbreviations.add(name_no_space)
        name_alphanum_only = re.sub(r'[^a-z0-9]', '', base_name_cleaned)
        if name_alphanum_only != name_no_space and name_alphanum_only != base_name_cleaned and len(name_alphanum_only) > 1:
            abbreviations.add(name_alphanum_only)

    ignore_words_default = {
        'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty',
        'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete',
        'collection', 'hd', 'ultra', 'deluxe', 'game', 'year', 'directors', 'cut'
    }
    ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default)
    ignore_words_lower = {w.lower() for w in ignore_words}

    words = base_name_cleaned.split(' ')
    significant_words = [w for w in words if w and w not in ignore_words_lower and len(w) > 1]

    name_for_caps_check = re.sub(r'[™®©:]', '', game_name_raw)
    name_for_caps_check = re.sub(r'[-_]', ' ', name_for_caps_check)
    name_for_caps_check = re.sub(r'\s+', ' ', name_for_caps_check).strip()
    
    camel_case_words = [w for w in name_for_caps_check.split(' ') 
                       if w and w.lower() not in ignore_words_lower and len(w) > 1]
    significant_words_capitalized = [
        w for w in camel_case_words if w and w.lower() not in ignore_words_lower and len(w) > 1 and w[0].isupper()
    ]

    if significant_words:
        acr_all = "".join(w[0] for w in significant_words)
        if len(acr_all) >= 2:
            abbreviations.add(acr_all)

    if significant_words_capitalized:
        acr_caps = "".join(w[0] for w in significant_words_capitalized).upper()
        if len(acr_caps) >= 2:
            abbreviations.add(acr_caps)
            abbreviations.add(acr_caps.lower())

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

    # Add install directory name as abbreviation, but filter out system directories
    SYSTEM_DIRS_BLACKLIST = {'bin', 'usr', 'lib', 'lib64', 'opt', 'etc', 'var', 'tmp', 'home', 
                             'root', 'dev', 'proc', 'sys', 'run', 'snap', 'flatpak', 'share',
                             'local', 'config', 'cache', 'data', 'games', 'steam', 'proton',
                             'wine', 'prefix', 'pfx', 'drive_c', 'program files', 'appdata',
                             'documents', 'desktop', 'downloads', 'pictures', 'videos', 'music'}
    
    if game_install_dir_raw and os.path.isdir(game_install_dir_raw):
        install_dir_basename = os.path.basename(game_install_dir_raw)
        cleaned_install_dir_name = clean_for_comparison(install_dir_basename)
        # Only add if it's not a system directory and is meaningfully different from game name
        if (cleaned_install_dir_name and 
            len(cleaned_install_dir_name) > 3 and  # Require at least 4 chars
            cleaned_install_dir_name != base_name_cleaned and
            cleaned_install_dir_name not in SYSTEM_DIRS_BLACKLIST):
            abbreviations.add(cleaned_install_dir_name)
            no_spaces_install_dir = cleaned_install_dir_name.replace(" ", "")
            if no_spaces_install_dir != cleaned_install_dir_name and len(no_spaces_install_dir) > 3:
                abbreviations.add(no_spaces_install_dir)

    if significant_words and len(significant_words[0]) > 1:
        abbreviations.add(significant_words[0])

    if camel_case_words:
        camel_case_variant = ''.join(w[0].upper() + w[1:].lower() for w in camel_case_words)
        if len(camel_case_variant) >= 2:
            abbreviations.add(camel_case_variant)
            abbreviations.add(camel_case_variant.lower())
        if len(camel_case_words) > 1 and len(camel_case_words[0]) <= 4:
            first_word = camel_case_words[0]
            if first_word.isupper() or len(first_word) <= 4:
                camel_case_no_prefix = ''.join(w[0].upper() + w[1:].lower() for w in camel_case_words[1:])
                if len(camel_case_no_prefix) >= 2:
                    abbreviations.add(camel_case_no_prefix)
                    abbreviations.add(camel_case_no_prefix.lower())

    final_abbreviations = {abbr for abbr in abbreviations if abbr and len(abbr) >= 2}
    return sorted(list(final_abbreviations), key=lambda x: (-len(x), x))


def matches_initial_sequence(folder_name: str, game_title_words: List[str]) -> bool:
    """Check if folder_name matches the initial sequence of game_title_words."""
    if not folder_name or not game_title_words:
        return False
    try:
        word_initials = [word[0].upper() for word in game_title_words if word and word[0].isascii()]
        expected_sequence = "".join(word_initials)
        return folder_name.upper() == expected_sequence
    except Exception as e:
        logging.error(f"Error in matches_initial_sequence: {e}")
        return False


def are_names_similar(name1_game_variant: str, name2_path_component: str,
                      min_match_words: int = 2, fuzzy_threshold: int = 88,
                      game_title_sig_words_for_seq: List[str] = None,
                      fuzz_engine=None, thefuzz_available: bool = None) -> bool:
    """Compare two names for similarity."""
    if thefuzz_available is None:
        thefuzz_available = (fuzz_engine is not None)

    pattern_alphanum_space = r'[^a-zA-Z0-9\s]'
    temp_clean_name1 = re.sub(pattern_alphanum_space, '', str(name1_game_variant)).lower()
    temp_clean_name1 = re.sub(r'\s+', ' ', temp_clean_name1).strip()
    temp_clean_name2 = re.sub(pattern_alphanum_space, '', str(name2_path_component)).lower()
    temp_clean_name2 = re.sub(r'\s+', ' ', temp_clean_name2).strip()

    if not temp_clean_name1 or not temp_clean_name2:
        return False

    ignore_words_default = {'a', 'an', 'the', 'of', 'and'}
    similarity_ignore_words_config = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default)
    ignore_words_lower = {w.lower() for w in similarity_ignore_words_config}

    pattern_words = r'\b[a-zA-Z0-9]+\b'
    words1 = {w for w in re.findall(pattern_words, temp_clean_name1) if w not in ignore_words_lower and len(w) > 1}
    words2 = {w for w in re.findall(pattern_words, temp_clean_name2) if w not in ignore_words_lower and len(w) > 1}

    common_words = words1.intersection(words2)
    if len(common_words) >= min_match_words:
        return True

    name1_no_space = temp_clean_name1.replace(' ', '')
    name2_no_space = temp_clean_name2.replace(' ', '')
    MIN_PREFIX_LEN = 3

    if len(name1_no_space) >= MIN_PREFIX_LEN and len(name2_no_space) >= MIN_PREFIX_LEN:
        if name1_no_space == name2_no_space:
            return True
        if len(name1_no_space) > len(name2_no_space) and name1_no_space.startswith(name2_no_space) and len(name2_no_space) >= max(MIN_PREFIX_LEN, len(name1_no_space) // 2):
            return True
        if len(name2_no_space) > len(name1_no_space) and name2_no_space.startswith(name1_no_space) and len(name1_no_space) >= max(MIN_PREFIX_LEN, len(name2_no_space) // 2):
            return True

    if game_title_sig_words_for_seq and len(temp_clean_name2) <= 5:
        if matches_initial_sequence(name2_path_component, game_title_sig_words_for_seq):
            return True

    try:
        name1_upper = temp_clean_name1.replace(' ', '').upper()
        if 2 <= len(name1_upper) <= 6 and name1_upper.isalnum():
            raw2 = str(name2_path_component)
            parts = re.split(r'[\s_\-]+', raw2)
            initials = ""
            if len(parts) > 1:
                initials = ''.join(p[0] for p in parts if p and p[0].isascii())
            else:
                camel_tokens = re.findall(r'[A-Z0-9][a-z0-9]*', raw2)
                if camel_tokens:
                    initials = ''.join(t[0] for t in camel_tokens if t and t[0].isascii())
            if initials and initials.upper() == name1_upper:
                return True
    except Exception:
        pass

    if thefuzz_available and fuzzy_threshold > 0 and fuzzy_threshold <= 100:
        try:
            ratio = fuzz_engine.token_set_ratio(temp_clean_name1, temp_clean_name2)
            if ratio >= fuzzy_threshold:
                return True
            partial_ratio = fuzz_engine.partial_ratio(temp_clean_name1, temp_clean_name2)
            if partial_ratio >= fuzzy_threshold:
                return True
            if len(temp_clean_name1) >= 4 and len(temp_clean_name2) >= 4:
                if temp_clean_name1 in temp_clean_name2 or temp_clean_name2 in temp_clean_name1:
                    if ratio >= (fuzzy_threshold - 20):
                        return True
        except Exception as e_fuzz:
            logging.error(f"Error during fuzzy matching: {e_fuzz}")

    if not thefuzz_available and temp_clean_name1 == temp_clean_name2:
        return True

    return False


# =============================================================================
# STATE INITIALIZATION
# =============================================================================

def _build_search_state(game_name_raw: str, game_install_dir_raw: str,
                        installed_steam_games_dict: Dict = None,
                        steam_app_id_raw: str = None,
                        steam_userdata_path: str = None) -> LinuxSearchState:
    """Build a complete LinuxSearchState from input parameters."""
    
    game_name_cleaned = clean_for_comparison(game_name_raw)
    
    # Build game_title_original_sig_words_for_seq
    temp_name_for_seq = re.sub(r'[™®©:]', '', game_name_raw)
    temp_name_for_seq = re.sub(r'[-_]', ' ', temp_name_for_seq)
    temp_name_for_seq = re.sub(r'\s+', ' ', temp_name_for_seq).strip()
    original_game_words_with_case = temp_name_for_seq.split(' ')

    ignore_words_default_for_seq = {
        'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty',
        'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete',
        'collection', 'hd', 'ultra', 'deluxe', 'game', 'year', 'directors', 'cut'
    }
    ignore_words_for_seq_config = getattr(config, 'SIMILARITY_IGNORE_WORDS', ignore_words_default_for_seq)
    ignore_words_for_seq_lower = {w.lower() for w in ignore_words_for_seq_config}

    game_title_original_sig_words_for_seq = [
        word for word in original_game_words_with_case 
        if word and word.lower() not in ignore_words_for_seq_lower
    ]
    if not game_title_original_sig_words_for_seq and game_name_cleaned:
        game_title_original_sig_words_for_seq = game_name_cleaned.split(' ')

    # Generate abbreviations
    game_abbreviations = generate_abbreviations(game_name_raw, game_install_dir_raw)
    if game_name_cleaned not in game_abbreviations:
        game_abbreviations.append(game_name_cleaned)
    game_abbreviations_lower = {clean_for_comparison(abbr) for abbr in game_abbreviations}

    logging.info(f"DEBUG: Generated abbreviations for '{game_name_raw}': {game_abbreviations}")

    # Load config values
    known_companies_lower = [kc.lower() for kc in getattr(config, 'COMMON_PUBLISHERS', [])]
    linux_common_save_subdirs_lower = {csd.lower() for csd in getattr(config, 'LINUX_COMMON_SAVE_SUBDIRS', [])}
    linux_banned_path_fragments_lower = {bps.lower() for bps in getattr(config, 'LINUX_BANNED_PATH_FRAGMENTS', getattr(config, 'BANNED_FOLDER_NAMES_LOWER', []))}
    common_save_extensions = {e.lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    common_save_extensions_nodot = {e.lstrip('.').lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    common_save_filenames_lower = {f.lower() for f in getattr(config, 'COMMON_SAVE_FILENAMES', set())}
    proton_user_path_fragments = getattr(config, 'PROTON_USER_PATH_FRAGMENTS', [])

    # Load known save locations
    linux_known_save_locations = {}
    raw_locations = getattr(config, 'LINUX_KNOWN_SAVE_LOCATIONS', [])
    if isinstance(raw_locations, dict):
        for desc, path_val in raw_locations.items():
            linux_known_save_locations[desc] = os.path.expanduser(path_val)
    elif isinstance(raw_locations, list):
        for item in raw_locations:
            if isinstance(item, tuple) and len(item) == 2:
                desc, path_val = item
                linux_known_save_locations[desc] = os.path.expanduser(path_val)
            elif isinstance(item, str):
                desc = item.replace("~", "Home").replace("/.", "/").strip("/").replace("/", "_")
                linux_known_save_locations[desc if desc else "UnknownLocation"] = os.path.expanduser(item)

    # Build other games sets
    other_cleaned_game_names = set()
    other_game_abbreviations = set()
    all_known_games_raw_list = getattr(config, 'ALL_KNOWN_GAME_NAMES_RAW', [])
    current_game_name_cleaned_lower = game_name_cleaned.lower()
    current_game_abbreviations_lower = {abbr.lower() for abbr in game_abbreviations}

    for other_game_name_raw_entry in all_known_games_raw_list:
        if not isinstance(other_game_name_raw_entry, str):
            continue
        other_game_cleaned = clean_for_comparison(other_game_name_raw_entry)
        other_game_cleaned_lower = other_game_cleaned.lower()
        if other_game_cleaned_lower == current_game_name_cleaned_lower:
            continue
        other_cleaned_game_names.add(other_game_cleaned_lower)
        temp_other_abbrs = generate_abbreviations(other_game_name_raw_entry)
        for other_abbr in temp_other_abbrs:
            other_abbr_lower = other_abbr.lower()
            if other_abbr_lower not in current_game_abbreviations_lower and other_abbr_lower != current_game_name_cleaned_lower:
                other_game_abbreviations.add(other_abbr_lower)

    return LinuxSearchState(
        game_name_cleaned=game_name_cleaned,
        game_abbreviations=game_abbreviations,
        game_abbreviations_lower=game_abbreviations_lower,
        game_title_original_sig_words_for_seq=game_title_original_sig_words_for_seq,
        known_companies_lower=known_companies_lower,
        linux_common_save_subdirs_lower=linux_common_save_subdirs_lower,
        linux_banned_path_fragments_lower=linux_banned_path_fragments_lower,
        common_save_extensions=common_save_extensions,
        common_save_extensions_nodot=common_save_extensions_nodot,
        common_save_filenames_lower=common_save_filenames_lower,
        proton_user_path_fragments=proton_user_path_fragments,
        linux_known_save_locations=linux_known_save_locations,
        installed_steam_games_dict=installed_steam_games_dict,
        other_cleaned_game_names=other_cleaned_game_names,
        other_game_abbreviations=other_game_abbreviations,
        current_steam_app_id=steam_app_id_raw,
        steam_userdata_path=steam_userdata_path,
        max_files_to_scan_linux_hint=getattr(config, 'MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT', 100),
        min_save_files_for_bonus_linux=getattr(config, 'MIN_SAVE_FILES_FOR_BONUS_LINUX', 2),
        max_sub_items_to_scan_linux=getattr(config, 'MAX_SUB_ITEMS_TO_SCAN_LINUX', 50),
        max_shallow_explore_depth_linux=getattr(config, 'MAX_SHALLOW_EXPLORE_DEPTH_LINUX', 1),
        max_search_depth_linux=getattr(config, 'MAX_SEARCH_DEPTH_LINUX', 10),
        fuzzy_threshold_basename_match=getattr(config, 'FUZZY_THRESHOLD_BASENAME_MATCH', 85),
        fuzzy_threshold_path_match=getattr(config, 'FUZZY_THRESHOLD_PATH_MATCH', 75),
        THEFUZZ_AVAILABLE=_THEFUZZ_AVAILABLE,
        fuzz=_fuzz_module,
        MAX_USERDATA_SCORE=getattr(config, 'MAX_USERDATA_SCORE', 1100),
    )


# =============================================================================
# DIRECTORY SCANNING HELPERS
# =============================================================================

def _scan_dir_for_save_evidence(dir_path: str, state: LinuxSearchState) -> Tuple[bool, int]:
    """Scan a directory for save file evidence."""
    has_evidence = False
    save_file_count = 0
    files_scanned_count = 0

    try:
        for item_name in os.listdir(dir_path):
            if files_scanned_count >= state.max_files_to_scan_linux_hint:
                break

            item_path = os.path.join(dir_path, item_name)
            if os.path.isfile(item_path):
                files_scanned_count += 1
                item_name_lower = item_name.lower()
                _, ext_lower = os.path.splitext(item_name_lower)
                ext_lower = ext_lower.lstrip('.')

                is_matching_file = False
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
                    if ext_lower in state.common_save_extensions_nodot:
                        is_matching_file = True
                    elif item_name_lower in state.common_save_filenames_lower:
                        is_matching_file = True

                if is_matching_file:
                    has_evidence = True
                    save_file_count += 1

    except OSError as e:
        logging.warning(f"_scan_dir_for_save_evidence: OSError in '{dir_path}': {e}")
        return False, 0

    return has_evidence, save_file_count


def _is_potential_save_dir(dir_path: str, state: LinuxSearchState) -> Tuple[bool, bool]:
    """Determine if a directory is a potential save path."""
    is_potential = False
    has_actual_save_files_for_bonus = False

    name_match_game_or_common_save_dir = False
    for abbr in state.game_abbreviations_lower:
        if abbr in dir_path.lower():
            name_match_game_or_common_save_dir = True
            break
        if '_' in abbr:
            abbr_with_spaces = abbr.replace('_', ' ')
            if abbr_with_spaces in dir_path.lower():
                name_match_game_or_common_save_dir = True
                break

    if not name_match_game_or_common_save_dir:
        if os.path.basename(dir_path).lower() in state.linux_common_save_subdirs_lower:
            name_match_game_or_common_save_dir = True

    has_save_files_evidence, save_file_count_for_bonus = _scan_dir_for_save_evidence(dir_path, state)

    if name_match_game_or_common_save_dir:
        is_potential = True
        if save_file_count_for_bonus >= state.min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True
    elif has_save_files_evidence:
        is_potential = True
        if save_file_count_for_bonus >= state.min_save_files_for_bonus_linux:
            has_actual_save_files_for_bonus = True

    return is_potential, has_actual_save_files_for_bonus


def _is_in_userdata(path_lower: str, steam_userdata_path: str = None) -> bool:
    """Check if a path is within Steam userdata."""
    if not steam_userdata_path:
        return False
    userdata_check = steam_userdata_path.lower().replace('\\', '/')
    path_check = path_lower.replace('\\', '/')
    return path_check.startswith(userdata_check)


def _identify_path_type(path_lower: str, source_lower: str, steam_userdata_path: str = None) -> Dict[str, bool]:
    """Identify path type for penalty calculation."""
    is_steam_remote = False
    if steam_userdata_path:
        source_check = source_lower.replace('\\', '/').lower()
        path_check = path_lower.replace('\\', '/')
        is_steam_remote = (('steam userdata' in source_check and '/remote' in source_check) or
                         (steam_userdata_path.lower() in path_check and '/remote' in path_check))

    is_steam_base = False
    if steam_userdata_path:
        path_check = path_lower.replace('\\', '/')
        userdata_base = steam_userdata_path.lower().replace('\\', '/')
        is_steam_base = (path_check.startswith(userdata_base) and not is_steam_remote)

    is_prime_location = any(loc in path_lower for loc in [
        '/home/', '/.local/share/', '/.config/', '/.steam/steam/userdata/',
        'appdata', 'documents', 'saved games'
    ])

    is_install_dir_walk = any(loc in path_lower for loc in [
        '/usr/local/', '/opt/', '/snap/', '/var/', '/usr/share/', 'steamapps/common'
    ])

    return {
        'is_steam_remote': is_steam_remote,
        'is_steam_base': is_steam_base,
        'is_prime_location': is_prime_location,
        'is_install_dir_walk': is_install_dir_walk
    }


def _get_penalties(basename_lower: str, contains_saves: bool, is_prime_location: bool,
                   is_steam_remote: bool, is_install_dir_walk: bool, path_lower: str = None) -> int:
    """Calculate aggressive penalties for problematic folders."""
    penalty = 0

    if path_lower:
        try:
            backup_base_dir = config.get_default_backup_dir()
            if backup_base_dir and backup_base_dir.lower() in path_lower:
                return BACKUP_DIRECTORY_PENALTY
        except Exception:
            pass

    if basename_lower == 'data' and not contains_saves and not is_prime_location and not is_steam_remote:
        penalty += DATA_FOLDER_PENALTY
    elif basename_lower in ['settings', 'config', 'cache', 'logs'] and not contains_saves and not is_prime_location and not is_steam_remote:
        penalty += GENERIC_FOLDER_PENALTY

    if is_install_dir_walk:
        penalty += -500
        if not contains_saves:
            penalty += INSTALL_DIR_NO_SAVES_PENALTY
        if basename_lower in ['data', 'config', 'settings', 'cache']:
            penalty += INSTALL_DIR_GENERIC_PENALTY
        if basename_lower in ['mcc', 'halo', 'minecraft']:
            penalty += INSTALL_DIR_MCC_PENALTY

    return penalty


# =============================================================================
# GUESS MANAGEMENT
# =============================================================================

def _add_guess(state: LinuxSearchState, path_found: str, source_description: str,
               has_saves_hint_from_scan: bool) -> None:
    """Add a found path to state.guesses_data after applying strict filter."""
    normalized_path = os.path.normpath(os.path.abspath(path_found))
    path_found_lower = normalized_path.lower()
    path_lower_no_space = re.sub(r'\s+', '', path_found_lower)

    # Check for backup directory
    try:
        backup_base_dir = config.get_default_backup_dir()
        if backup_base_dir and backup_base_dir.lower() in path_found_lower:
            state.checked_paths.add(normalized_path)
            return
    except Exception:
        pass

    passes_strict_filter = False
    reason_for_pass = ""
    current_game_name_explicitly_in_path = False

    is_proton_path = ("proton" in source_description.lower() or "pfx" in source_description.lower())

    # Check Proton path for game keywords
    if is_proton_path and not passes_strict_filter:
        for abbr in state.game_abbreviations_lower:
            if abbr.lower() in source_description.lower():
                passes_strict_filter = True
                reason_for_pass = f"Proton path with game keyword '{abbr}' in source"
                break

        if not passes_strict_filter and state.game_name_cleaned:
            source_clean = re.sub(r'[^a-zA-Z0-9\s]', '', source_description).lower()
            source_clean = re.sub(r'\s+', ' ', source_clean).strip()
            if state.game_name_cleaned in source_clean:
                passes_strict_filter = True
                reason_for_pass = f"Proton path with game name in source"
            elif not passes_strict_filter:
                game_words = state.game_name_cleaned.split()
                matching_words = sum(1 for word in game_words if len(word) > 2 and word in source_clean)
                if matching_words >= 2:
                    passes_strict_filter = True
                    reason_for_pass = f"Proton path with {matching_words} matching game words"

    # Check game abbreviations in path
    for abbr in state.game_abbreviations_lower:
        if len(abbr) <= 2:
            continue
        if abbr in path_found_lower or abbr in path_lower_no_space:
            current_game_name_explicitly_in_path = True
            passes_strict_filter = True
            reason_for_pass = f"Game name/abbr '{abbr}' in path"
            break

    # Check basename acronym match
    if not passes_strict_filter:
        try:
            base_raw = os.path.basename(normalized_path)
            parts = re.split(r'[\s_\-]+', base_raw)
            initials = ''
            if len(parts) > 1:
                initials = ''.join(p[0] for p in parts if p and p[0].isascii())
            else:
                camel_tokens = re.findall(r'[A-Z0-9][a-z0-9]*', base_raw)
                if camel_tokens:
                    initials = ''.join(t[0] for t in camel_tokens if t and t[0].isascii())
            if initials:
                initials_lower = initials.lower()
                game_compact = (state.game_name_cleaned or '').replace(' ', '')
                if initials_lower in state.game_abbreviations_lower or initials_lower == game_compact:
                    passes_strict_filter = True
                    reason_for_pass = f"Basename acronym '{initials}' matches game"
        except Exception:
            pass

    # Check common save subdirectories with game context
    if not passes_strict_filter:
        basename_lower = os.path.basename(path_found_lower)
        if basename_lower in state.linux_common_save_subdirs_lower:
            path_has_game_context = False
            for abbr in state.game_abbreviations_lower:
                if len(abbr) > 2 and (abbr in path_found_lower or abbr in path_lower_no_space):
                    path_has_game_context = True
                    break
            if not path_has_game_context and state.game_name_cleaned and state.game_name_cleaned in path_found_lower:
                path_has_game_context = True
            if path_has_game_context:
                passes_strict_filter = True
                reason_for_pass = "Common save subdirectory with game context"

    # Check container directories
    if not passes_strict_filter:
        basename_lower = os.path.basename(path_found_lower)
        common_container_dirs = {'unity3d', 'unreal', 'gamemaker', 'construct', 'godot'}
        if basename_lower in common_container_dirs:
            path_contains_game = any(len(abbr) > 2 and abbr in path_found_lower for abbr in state.game_abbreviations_lower)
            if path_contains_game:
                passes_strict_filter = True
                reason_for_pass = f"Container directory '{basename_lower}' with game name"

    # NOTE: We intentionally do NOT add paths just because they contain other game names.
    # That would cause false positives (e.g., "binding of isaac" matching because of "bin").
    # The other_cleaned_game_names and other_game_abbreviations are used later for EXCLUSION,
    # not inclusion.

    # Check Steam AppID
    if not passes_strict_filter and state.current_steam_app_id:
        appid_str = str(state.current_steam_app_id)
        if appid_str in path_found_lower:
            passes_strict_filter = True
            reason_for_pass = f"Steam AppID '{appid_str}' in path"

    # Final check for cleaned game name
    if not passes_strict_filter and state.game_name_cleaned:
        if state.game_name_cleaned in path_found_lower or state.game_name_cleaned in path_lower_no_space:
            passes_strict_filter = True
            reason_for_pass = f"Cleaned game name in path"
        else:
            try:
                base_lower = os.path.basename(path_found_lower)
                if state.fuzz and state.THEFUZZ_AVAILABLE:
                    ratio = state.fuzz.token_set_ratio(state.game_name_cleaned, base_lower)
                    if ratio >= max(80, state.fuzzy_threshold_basename_match - 5):
                        passes_strict_filter = True
                        reason_for_pass = f"Fuzzy basename match {ratio}%"
            except Exception:
                pass

    # Proton path similarity check
    if not passes_strict_filter and is_proton_path:
        if state.fuzz and state.THEFUZZ_AVAILABLE:
            try:
                path_basename = os.path.basename(normalized_path)
                cleaned_folder = re.sub(r'[^a-zA-Z0-9\s]', '', path_basename).lower()
                cleaned_folder = re.sub(r'\s+', ' ', cleaned_folder).strip()
                if cleaned_folder:
                    similarity = state.fuzz.ratio(state.game_name_cleaned, cleaned_folder)
                    if similarity >= 70:
                        passes_strict_filter = True
                        reason_for_pass = f"Proton path similarity ({similarity}%)"
            except Exception:
                pass

    # Fuzzy filter against other installed games
    if passes_strict_filter and state.installed_steam_games_dict and state.fuzz and state.THEFUZZ_AVAILABLE:
        if getattr(config, 'LINUX_ENABLE_FUZZY_FILTER_OTHER_GAMES', True):
            try:
                path_basename = os.path.basename(normalized_path)
                cleaned_folder = re.sub(r'[^a-zA-Z0-9\s]', '', path_basename).lower()
                cleaned_folder = re.sub(r'\s+', ' ', cleaned_folder).strip()
                if cleaned_folder:
                    for other_appid, other_info in state.installed_steam_games_dict.items():
                        if other_appid == str(state.current_steam_app_id):
                            continue
                        other_name = (other_info or {}).get('name', '')
                        if not other_name:
                            continue
                        cleaned_other = re.sub(r'[^a-zA-Z0-9\s]', '', other_name).lower()
                        cleaned_other = re.sub(r'\s+', ' ', cleaned_other).strip()
                        ratio = state.fuzz.token_set_ratio(cleaned_other, cleaned_folder)
                        if ratio >= 95:
                            passes_strict_filter = False
                            reason_for_pass = f"Rejected: matches other game '{other_name}'"
                            break
            except Exception:
                pass

    if passes_strict_filter:
        state.guesses_data[normalized_path] = {
            "source": source_description,
            "sources": {source_description},
            "reason": reason_for_pass,
            "has_saves_hint": has_saves_hint_from_scan,
            "explicit_name_match": current_game_name_explicitly_in_path,
            "steam_app_id": str(state.current_steam_app_id) if state.current_steam_app_id else None
        }

    state.checked_paths.add(normalized_path)


# =============================================================================
# RECURSIVE SEARCH
# =============================================================================

def _search_recursive(start_dir: str, depth: int, state: LinuxSearchState,
                      cancellation_manager: cancellation_utils.CancellationManager = None) -> None:
    """Recursively search for save directories."""
    
    # Performance limit
    state.directories_explored += 1
    MAX_DIRECTORIES_TO_EXPLORE = getattr(config, 'LINUX_MAX_DIRECTORIES_TO_EXPLORE', 200)
    
    if state.directories_explored > MAX_DIRECTORIES_TO_EXPLORE:
        logging.info(f"PERFORMANCE: Stopping after {MAX_DIRECTORIES_TO_EXPLORE} directories")
        return
    
    if cancellation_manager and cancellation_manager.check_cancelled():
        return

    if depth > state.max_search_depth_linux:
        return

    try:
        if not os.path.isdir(start_dir):
            return
    except OSError:
        return

    basename_current_path_lower = os.path.basename(start_dir.lower())
    basename_current_path_raw = os.path.basename(start_dir)
    
    is_potential_current, has_saves_hint_current = _is_potential_save_dir(start_dir, state)

    current_path_name_match_game = False
    current_path_name_match_company = False
    current_path_is_common_save_dir_flag = basename_current_path_lower in state.linux_common_save_subdirs_lower

    for abbr in state.game_abbreviations_lower:
        if are_names_similar(abbr, basename_current_path_raw,
                            game_title_sig_words_for_seq=state.game_title_original_sig_words_for_seq,
                            fuzzy_threshold=state.fuzzy_threshold_basename_match,
                            fuzz_engine=state.fuzz, thefuzz_available=state.THEFUZZ_AVAILABLE):
            current_path_name_match_game = True
            break

    if not current_path_name_match_game:
        for company_name_clean in state.known_companies_lower:
            if are_names_similar(company_name_clean, basename_current_path_lower,
                                fuzzy_threshold=state.fuzzy_threshold_basename_match,
                                fuzz_engine=state.fuzz, thefuzz_available=state.THEFUZZ_AVAILABLE):
                current_path_name_match_company = True
                break

    should_add_current_path = False
    if is_potential_current or current_path_name_match_game:
        if current_path_name_match_game or current_path_name_match_company or current_path_is_common_save_dir_flag:
            should_add_current_path = True

    if should_add_current_path:
        if state.is_exploring_install_dir:
            specific_source_desc = f"InstallDirWalk/{os.path.relpath(start_dir, state.install_dir_root) if state.install_dir_root else start_dir} (Depth={depth})"
        else:
            specific_source_desc = f"{start_dir} (Depth={depth})"

        if current_path_name_match_game:
            specific_source_desc += " (GameMatch)"
        elif current_path_name_match_company:
            specific_source_desc += " (CompanyMatch)"
        elif current_path_is_common_save_dir_flag:
            specific_source_desc += " (CommonSaveDir)"
        elif is_potential_current:
            specific_source_desc += " (PotentialDirEvidence)"

        _add_guess(state, start_dir, specific_source_desc, has_saves_hint_current)

    # List directory contents
    try:
        dir_contents = os.listdir(start_dir)
    except OSError:
        return

    linux_skip_directories = getattr(config, 'LINUX_SKIP_DIRECTORIES', set())
    filtered_dir_contents = [name for name in dir_contents if name.lower() not in linux_skip_directories]
    dir_contents_limited = filtered_dir_contents[:state.max_sub_items_to_scan_linux]

    for item_name in dir_contents_limited:
        if cancellation_manager and cancellation_manager.check_cancelled():
            return

        item_path = os.path.join(start_dir, item_name)
        normalized_item_path = os.path.normpath(item_path)

        if normalized_item_path in state.checked_paths:
            continue
        state.checked_paths.add(normalized_item_path)

        try:
            if not os.path.isdir(item_path):
                continue

            item_name_lower = item_name.lower()
            if item_name_lower in linux_skip_directories:
                continue

            sub_is_potential, _ = _is_potential_save_dir(item_path, state)

            item_is_game_match = False
            for abbr in state.game_abbreviations_lower:
                if abbr in item_name_lower or item_name_lower in abbr:
                    item_is_game_match = True
                    break
                elif are_names_similar(abbr, item_name,
                                      game_title_sig_words_for_seq=state.game_title_original_sig_words_for_seq,
                                      fuzzy_threshold=state.fuzzy_threshold_basename_match,
                                      fuzz_engine=state.fuzz, thefuzz_available=state.THEFUZZ_AVAILABLE):
                    item_is_game_match = True
                    break

            item_is_company_match = False
            if not item_is_game_match:
                if item_name_lower in state.known_companies_lower:
                    item_is_company_match = True
                else:
                    common_companies = {'steam', 'valve', 'ea', 'ubisoft', 'activision', 'blizzard',
                                       'bethesda', 'cd projekt red', 'square enix', 'capcom', 'sega',
                                       'bandai namco', 'paradox interactive', 'devolver digital'}
                    for company_name_clean in state.known_companies_lower:
                        if len(company_name_clean) <= 3:
                            continue
                        if company_name_clean in common_companies:
                            if are_names_similar(company_name_clean, item_name_lower, fuzzy_threshold=95,
                                               fuzz_engine=state.fuzz, thefuzz_available=state.THEFUZZ_AVAILABLE):
                                item_is_company_match = True
                                break

            item_is_common_save_dir = item_name_lower in state.linux_common_save_subdirs_lower
            item_is_container_dir = item_name_lower in {'unity3d', 'unreal', 'gamemaker', 'construct', 'godot'}

            should_recurse_strong = (item_is_game_match or item_is_company_match or 
                                    item_is_common_save_dir or item_is_container_dir or
                                    'unity3d' in start_dir.lower() or sub_is_potential)

            if should_recurse_strong:
                _search_recursive(item_path, depth + 1, state, cancellation_manager)
            elif depth < state.max_shallow_explore_depth_linux:
                _search_recursive(item_path, depth + 1, state, cancellation_manager)

        except OSError:
            pass


# =============================================================================
# PROTON SEARCH FUNCTIONS
# =============================================================================

def _search_proton_prefix_deep(compatdata_path: str, appid: str, state: LinuxSearchState,
                               cancellation_manager=None) -> None:
    """Deep search in Wine prefix structure for Windows save paths."""
    try:
        windows_standard_paths = [
            "drive_c/users/steamuser/AppData/Local",
            "drive_c/users/steamuser/AppData/Roaming",
            "drive_c/users/steamuser/Documents",
            "drive_c/users/steamuser/Saved Games",
            "drive_c/users/steamuser/My Documents",
            "drive_c/users/steamuser/AppData/LocalLow",
            "drive_c/users/steamuser/My Games",
            "drive_c/users/steamuser/My Documents/My Games"
        ]

        wine_user_variants = ["steamuser", "steam", "user", "default", "wine"]

        for user_variant in wine_user_variants:
            for windows_path in windows_standard_paths:
                path_with_variant = windows_path.replace("steamuser", user_variant)
                full_path = os.path.join(compatdata_path, path_with_variant)

                if os.path.isdir(full_path):
                    _add_guess(state, full_path, f"Proton Windows Path/{path_with_variant} ({appid})", False)
                    
                    # Standard recursive search
                    _search_recursive(full_path, 0, state, cancellation_manager)
                    
                    # Direct game name search
                    for abbr_or_name in state.game_abbreviations:
                        game_specific_path = os.path.join(full_path, abbr_or_name)
                        if os.path.isdir(game_specific_path):
                            _add_guess(state, game_specific_path,
                                      f"Proton Windows Path/{path_with_variant}/{abbr_or_name} ({appid})", False)
                            _search_recursive(game_specific_path, 0, state, cancellation_manager)
                    
                    # DEEP SEARCH: For AppData paths, search ALL subdirectories for game name
                    # This handles cases like HelloGames/NMS or Unknown Worlds/Subnautica
                    if 'appdata' in path_with_variant.lower():
                        _search_appdata_deep(full_path, path_with_variant, appid, state, cancellation_manager)

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
                    for abbr_or_name in state.game_abbreviations:
                        game_path = os.path.join(full_location, abbr_or_name)
                        if os.path.isdir(game_path):
                            _add_guess(state, game_path,
                                      f"Proton Game Location/{location_with_variant}/{abbr_or_name} ({appid})", False)
                            _search_recursive(game_path, 0, state, cancellation_manager)

    except Exception as e:
        logging.error(f"Error in _search_proton_prefix_deep: {e}")


def _search_appdata_deep(appdata_path: str, path_variant: str, appid: str,
                         state: LinuxSearchState, cancellation_manager=None) -> None:
    """
    Deep search inside AppData directories for game saves.
    Handles cases where saves are in Publisher/GameName structure (e.g., HelloGames/NMS).
    Also handles Unreal Engine games that use internal project names (e.g., FSD for Deep Rock Galactic).
    Uses the known publishers list from config for targeted search.
    """
    try:
        # List all folders in AppData
        for folder_name in os.listdir(appdata_path):
            if cancellation_manager and cancellation_manager.check_cancelled():
                return
                
            folder_path = os.path.join(appdata_path, folder_name)
            if not os.path.isdir(folder_path):
                continue
            
            folder_lower = folder_name.lower()
            is_known_publisher = folder_lower in state.known_companies_lower
            
            # Check if folder matches game name/abbreviation directly
            matches_game = False
            for abbr in state.game_abbreviations_lower:
                if len(abbr) >= 3 and (abbr == folder_lower or abbr in folder_lower):
                    _add_guess(state, folder_path,
                              f"Proton AppData/{path_variant}/{folder_name} ({appid})", False)
                    _search_recursive(folder_path, 0, state, cancellation_manager)
                    matches_game = True
                    break
            
            # UNREAL ENGINE PATTERN: Check for Saved/SaveGames structure
            # Many Unreal games use internal project names (e.g., FSD for Deep Rock Galactic)
            # Pattern: AppData/Local/[ProjectName]/Saved/SaveGames
            saved_path = os.path.join(folder_path, 'Saved')
            if os.path.isdir(saved_path):
                savegames_path = os.path.join(saved_path, 'SaveGames')
                if os.path.isdir(savegames_path):
                    # Found Unreal Engine save structure - add it
                    _add_guess(state, savegames_path,
                              f"Proton AppData/{path_variant}/{folder_name}/Saved/SaveGames (Unreal) ({appid})", True)
                    _search_recursive(savegames_path, 0, state, cancellation_manager)
                    # Also add the Saved folder itself as some games save there
                    _add_guess(state, saved_path,
                              f"Proton AppData/{path_variant}/{folder_name}/Saved (Unreal) ({appid})", False)
            
            # If it's a known publisher OR we haven't found a direct match yet,
            # search inside for game-named subfolders
            if is_known_publisher or not matches_game:
                try:
                    for subfolder in os.listdir(folder_path):
                        subfolder_path = os.path.join(folder_path, subfolder)
                        if not os.path.isdir(subfolder_path):
                            continue
                        
                        subfolder_lower = subfolder.lower()
                        
                        # Check if subfolder matches any game abbreviation
                        for abbr in state.game_abbreviations_lower:
                            if len(abbr) < 2:
                                continue
                            
                            # Match: exact, substring, or reverse substring
                            if (subfolder_lower == abbr or 
                                (len(abbr) >= 3 and abbr in subfolder_lower) or
                                (len(subfolder_lower) >= 3 and subfolder_lower in abbr)):
                                
                                _add_guess(state, subfolder_path,
                                          f"Proton AppData/{path_variant}/{folder_name}/{subfolder} ({appid})", False)
                                _search_recursive(subfolder_path, 0, state, cancellation_manager)
                                break
                        
                        # Fuzzy matching for longer names
                        if state.THEFUZZ_AVAILABLE and state.fuzz:
                            cleaned = clean_for_comparison(subfolder)
                            if len(cleaned) >= 4:
                                ratio = state.fuzz.ratio(state.game_name_cleaned, cleaned)
                                if ratio >= 75:
                                    _add_guess(state, subfolder_path,
                                              f"Proton AppData/{path_variant}/{folder_name}/{subfolder} (fuzzy {ratio}%) ({appid})", False)
                                    _search_recursive(subfolder_path, 0, state, cancellation_manager)
                                
                except OSError:
                    continue
                
    except OSError as e:
        logging.debug(f"Error in _search_appdata_deep for {appdata_path}: {e}")


def _search_snap_games(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search for save paths in Snap games."""
    try:
        user_home = os.path.expanduser('~')
        snap_base = os.path.join(user_home, 'snap')

        if not os.path.isdir(snap_base):
            return

        for game_variant in state.game_abbreviations:
            if cancellation_manager and cancellation_manager.check_cancelled():
                return

            snap_game_path = os.path.join(snap_base, game_variant)
            if os.path.isdir(snap_game_path):
                current_path = os.path.join(snap_game_path, 'current')
                if os.path.isdir(current_path):
                    snap_save_paths = [
                        os.path.join(current_path, '.local', 'share', game_variant),
                        os.path.join(current_path, '.config', game_variant),
                        os.path.join(current_path, '.local', 'share'),
                        os.path.join(current_path, '.config'),
                    ]
                    for snap_path in snap_save_paths:
                        if os.path.isdir(snap_path):
                            _add_guess(state, snap_path,
                                      f"Snap Game/{game_variant}/{os.path.relpath(snap_path, current_path)}", False)
                            _search_recursive(snap_path, 0, state, cancellation_manager)

        try:
            snap_dirs = [d for d in os.listdir(snap_base) if os.path.isdir(os.path.join(snap_base, d))]
            for snap_dir in snap_dirs:
                if cancellation_manager and cancellation_manager.check_cancelled():
                    return

                is_similar = any(
                    are_names_similar(game_variant, snap_dir,
                                     game_title_sig_words_for_seq=state.game_title_original_sig_words_for_seq,
                                     fuzzy_threshold=state.fuzzy_threshold_basename_match,
                                     fuzz_engine=state.fuzz, thefuzz_available=state.THEFUZZ_AVAILABLE)
                    for game_variant in state.game_abbreviations
                )

                if is_similar:
                    current_path = os.path.join(snap_base, snap_dir, 'current')
                    if os.path.isdir(current_path):
                        snap_save_paths = [
                            os.path.join(current_path, '.local', 'share', snap_dir),
                            os.path.join(current_path, '.config', snap_dir),
                            os.path.join(current_path, '.local', 'share'),
                            os.path.join(current_path, '.config'),
                        ]
                        for snap_path in snap_save_paths:
                            if os.path.isdir(snap_path):
                                _add_guess(state, snap_path,
                                          f"Snap Game/{snap_dir}/{os.path.relpath(snap_path, current_path)}", False)
                                _search_recursive(snap_path, 0, state, cancellation_manager)
        except OSError:
            pass

    except Exception as e:
        logging.error(f"Error in _search_snap_games: {e}")


def _search_proton_for_non_steam_games(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search Proton paths for non-Steam games."""
    logging.info(f"_search_proton_for_non_steam_games: Starting search for '{state.game_name_cleaned}'")
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
            
            logging.info(f"_search_proton_for_non_steam_games: Found compatdata at {compatdata_base}")

            try:
                compatdata_folders = [d for d in os.listdir(compatdata_base)
                                     if d.isdigit() and os.path.isdir(os.path.join(compatdata_base, d))]
                logging.info(f"_search_proton_for_non_steam_games: Found {len(compatdata_folders)} compatdata folders")
            except (OSError, PermissionError):
                continue

            # For non-Steam games, we need to search more compatdata folders
            # since we don't know which one contains the game
            max_appids = getattr(config, 'LINUX_MAX_COMPATDATA_APPIDS_NONSTEAM', 50)
            scanned = 0
            for appid_folder in compatdata_folders:
                if cancellation_manager and cancellation_manager.check_cancelled():
                    return

                pfx_path = os.path.join(compatdata_base, appid_folder, 'pfx')
                if os.path.isdir(pfx_path):
                    _search_proton_prefix_deep(pfx_path, appid_folder, state, cancellation_manager)
                    _search_game_specific_in_proton(pfx_path, appid_folder, state, cancellation_manager)
                    scanned += 1
                    if scanned >= max_appids:
                        logging.info(f"_search_proton_for_non_steam_games: Reached max {max_appids} appids")
                        break
            
            logging.info(f"_search_proton_for_non_steam_games: Scanned {scanned} compatdata folders")

    except Exception as e:
        logging.error(f"Error in _search_proton_for_non_steam_games: {e}")


def _search_game_specific_in_proton(pfx_path: str, appid: str, state: LinuxSearchState,
                                    cancellation_manager=None) -> None:
    """Search specifically for the current game in a Proton prefix."""
    try:
        game_search_paths = [
            "drive_c/users/steamuser/AppData/Local",
            "drive_c/users/steamuser/AppData/Roaming",
            "drive_c/users/steamuser/Documents",
            "drive_c/users/steamuser/Saved Games",
            "drive_c/users/steamuser/My Games",
            "drive_c/Program Files",
            "drive_c/Program Files (x86)"
        ]

        user_variants = ["steamuser", "steam", "user", "default", "wine"]

        for user_variant in user_variants:
            for base_path in game_search_paths:
                path_with_variant = base_path.replace("steamuser", user_variant)
                full_base_path = os.path.join(pfx_path, path_with_variant)

                if not os.path.isdir(full_base_path):
                    continue

                for game_name_variant in state.game_abbreviations:
                    game_path = os.path.join(full_base_path, game_name_variant)
                    if os.path.isdir(game_path):
                        _add_guess(state, game_path,
                                  f"Proton Non-Steam Game/{path_with_variant}/{game_name_variant} ({appid})", False)
                        _search_recursive(game_path, 0, state, cancellation_manager)

                        common_save_subdirs = ['Saves', 'Save', 'Savegames', 'SaveGames', 'PlayerProfiles', 'Profiles']
                        for save_subdir in common_save_subdirs:
                            save_path = os.path.join(game_path, save_subdir)
                            if os.path.isdir(save_path):
                                _add_guess(state, save_path,
                                          f"Proton Non-Steam Game/{path_with_variant}/{game_name_variant}/{save_subdir} ({appid})", False)
                                _search_recursive(save_path, 0, state, cancellation_manager)

                _search_fuzzy_matches_in_proton_dir(full_base_path, path_with_variant, appid, state, cancellation_manager)

    except Exception as e:
        logging.error(f"Error in _search_game_specific_in_proton: {e}")


def _search_fuzzy_matches_in_proton_dir(base_path: str, path_variant: str, appid: str,
                                        state: LinuxSearchState, cancellation_manager=None) -> None:
    """Helper for fuzzy search in Proton directories."""
    if not state.THEFUZZ_AVAILABLE or not state.fuzz:
        return

    try:
        items_found = os.listdir(base_path)

        for item in items_found:
            item_path = os.path.join(base_path, item)
            if not os.path.isdir(item_path):
                continue

            best_match_score = 0
            for game_name_variant in state.game_abbreviations:
                normalized_item = item.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                normalized_game = game_name_variant.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                similarity = state.fuzz.ratio(normalized_item, normalized_game)
                if similarity > best_match_score:
                    best_match_score = similarity

            if best_match_score > 70:
                _add_guess(state, item_path,
                          f"Proton Fuzzy Match/{path_variant}/{item} ({appid}, {best_match_score}%)", False)
                _search_recursive(item_path, 0, state, cancellation_manager)

                for save_subdir in state.linux_common_save_subdirs_lower:
                    save_path = os.path.join(item_path, save_subdir)
                    if os.path.isdir(save_path):
                        _add_guess(state, save_path,
                                  f"Proton Fuzzy Match/{path_variant}/{item}/{save_subdir} ({appid})", False)
                        _search_recursive(save_path, 0, state, cancellation_manager)

            try:
                sub_items = os.listdir(item_path)
                for sub_item in sub_items:
                    sub_item_path = os.path.join(item_path, sub_item)
                    if os.path.isdir(sub_item_path):
                        best_sub_match_score = 0
                        for game_name_variant in state.game_abbreviations:
                            normalized_sub_item = sub_item.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                            normalized_game = game_name_variant.lower().replace(' ', '').replace('-', '').replace('_', '').replace("'", '')
                            sub_similarity = state.fuzz.ratio(normalized_sub_item, normalized_game)
                            if sub_similarity > best_sub_match_score:
                                best_sub_match_score = sub_similarity

                        if best_sub_match_score > 70:
                            _add_guess(state, sub_item_path,
                                      f"Proton Sub-Dir Match/{path_variant}/{item}/{sub_item} ({appid}, {best_sub_match_score}%)", False)
                            _search_recursive(sub_item_path, 0, state, cancellation_manager)
            except OSError:
                continue

    except OSError:
        pass


# =============================================================================
# SCORING AND SORTING
# =============================================================================

def _score_location_bonus(path_lower: str, source_description: str) -> int:
    """Calculate score bonus based on path location."""
    home_dir = os.path.expanduser("~")
    xdg_config_home = os.getenv('XDG_CONFIG_HOME', os.path.join(home_dir, ".config")).lower()
    xdg_data_home = os.getenv('XDG_DATA_HOME', os.path.join(home_dir, ".local", "share")).lower()
    
    if xdg_config_home in path_lower:
        return SCORE_XDG_CONFIG_HOME_BONUS
    elif xdg_data_home in path_lower:
        return SCORE_XDG_DATA_HOME_BONUS
    elif "steamapps/compatdata" in path_lower and "pfx" in path_lower:
        return 600
    elif "userdata" in path_lower:
        return 500
    elif "documents" in path_lower:
        return 200
    elif "InstallDirWalk" in source_description:
        return -500
    return 100


def _score_name_match_bonus(basename_lower: str, parent_basename_lower: str, 
                            state: LinuxSearchState) -> Tuple[int, bool]:
    """Calculate score bonus for name matches. Returns (score, awarded_parent_bonus)."""
    score = 0
    awarded_parent_bonus = False
    
    # Common save directory bonus
    if basename_lower in state.linux_common_save_subdirs_lower:
        score += SCORE_SAVE_DIR_MATCH
        parent_stripped = parent_basename_lower.lstrip('.')
        
        if parent_basename_lower in state.game_abbreviations_lower or parent_stripped in state.game_abbreviations_lower:
            score += SCORE_PERFECT_MATCH_BONUS
            awarded_parent_bonus = True
        elif parent_basename_lower in state.known_companies_lower:
            score += SCORE_COMPANY_NAME_MATCH
            awarded_parent_bonus = True
    
    # Abbreviation match
    if basename_lower in state.game_abbreviations_lower:
        score += 350
    
    # Company match
    if basename_lower in state.known_companies_lower:
        score += 200
    if not awarded_parent_bonus and parent_basename_lower in state.known_companies_lower:
        score += 100
    
    # Parent game match
    if not awarded_parent_bonus:
        parent_stripped = parent_basename_lower.lstrip('.')
        if parent_basename_lower in state.game_abbreviations_lower or parent_stripped in state.game_abbreviations_lower:
            score += 150
    
    return score, awarded_parent_bonus


def _score_fuzzy_similarity(basename: str, state: LinuxSearchState) -> int:
    """Calculate score bonus for fuzzy name similarity."""
    cleaned_folder = clean_for_comparison(basename)
    
    if state.game_name_cleaned == cleaned_folder:
        return 400
    
    if state.THEFUZZ_AVAILABLE and state.fuzz:
        ratio = state.fuzz.ratio(state.game_name_cleaned, cleaned_folder)
        if ratio > 85:
            return 300
        elif ratio > 70:
            return 150
    return 0


def _score_proton_bonus(path_lower: str, source_description: str) -> int:
    """Calculate score bonus for Proton paths."""
    score = 0
    source_lower = source_description.lower()
    
    if "proton" in source_lower or "pfx" in path_lower:
        score += 200
        windows_paths = ['appdata/local', 'appdata/roaming', 'appdata/locallow',
                        'documents', 'saved games', 'my games', 'my documents']
        if any(wp in path_lower for wp in windows_paths):
            score += 150
    
    if "Proton" in source_description:
        score += 100
    elif "Steam" in source_description:
        score += 80
    elif "Manual" in source_description:
        score += 50
    
    return score


def _calculate_penalties(path: str, path_lower: str, source_description: str,
                        has_saves: bool, state: LinuxSearchState) -> int:
    """Calculate all penalties for a path."""
    penalty = 0
    
    # Install dir walk penalty
    if "InstallDirWalk" in source_description and not has_saves:
        penalty -= 300
    
    # Banned fragments
    for banned in state.linux_banned_path_fragments_lower:
        if banned in path_lower:
            penalty -= 1000
            break
    
    # Path length penalty
    if len(path) > 200:
        penalty -= 50 * (len(path) - 200) // 10
    
    # Path depth penalty
    depth = path.count(os.sep)
    if depth > 10:
        penalty -= 20 * (depth - 10)
    
    return penalty


def _final_sort_key_linux(item_tuple: Tuple, state: LinuxSearchState) -> Tuple:
    """Generate a sort key for found paths."""
    path, data = item_tuple
    source = next(iter(data.get('sources', set())), "UnknownSource")
    has_saves = data.get('has_saves_hint', False)
    path_lower = path.lower()

    try:
        basename = os.path.basename(path)
        basename_lower = basename.lower()
        parent_basename_lower = os.path.basename(os.path.dirname(path).lower())
    except Exception:
        return (0, path_lower)

    # Calculate score components
    score = _score_location_bonus(path_lower, source)
    
    if has_saves:
        score += SCORE_HAS_SAVE_FILES
    
    name_bonus, _ = _score_name_match_bonus(basename_lower, parent_basename_lower, state)
    score += name_bonus
    
    score += _score_fuzzy_similarity(basename, state)
    
    # Path contains game name bonus
    if state.game_name_cleaned and state.game_name_cleaned.lower() in path_lower:
        score += 250
    
    # Steam AppID bonus
    steam_app_id = data.get('steam_app_id')
    if steam_app_id and steam_app_id in path_lower:
        score += 300
    
    # Path type penalties
    path_type = _identify_path_type(path_lower, source.lower(), state.steam_userdata_path)
    score += _get_penalties(basename_lower, has_saves, path_type['is_prime_location'],
                           path_type['is_steam_remote'], path_type['is_install_dir_walk'], path_lower)
    
    # Additional penalties
    score += _calculate_penalties(path, path_lower, source, has_saves, state)
    
    # Proton bonus
    score += _score_proton_bonus(path_lower, source)
    
    # Steam userdata cap
    if _is_in_userdata(path_lower, state.steam_userdata_path):
        score = min(score, state.MAX_USERDATA_SCORE)

    return (-score, path_lower)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def _search_steam_userdata(state: LinuxSearchState, appid: str, steam_userdata_path: str,
                           steam_id3_to_use: str, cancellation_manager=None) -> None:
    """Search Steam userdata for save paths."""
    try:
        user_data_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
        if not os.path.isdir(user_data_for_id):
            return
            
        app_specific_userdata = os.path.join(user_data_for_id, appid)
        if not os.path.isdir(app_specific_userdata):
            return
            
        _add_guess(state, app_specific_userdata, "Steam Userdata/AppID_Base", False)
        
        remote_path = os.path.join(app_specific_userdata, 'remote')
        if os.path.isdir(remote_path) and getattr(config, 'LINUX_ENABLE_STEAM_USERDATA_REMOTE_SCAN', True):
            _add_guess(state, remote_path, "Steam Userdata/AppID_Base/remote", False)
            if not (cancellation_manager and cancellation_manager.check_cancelled()):
                _search_recursive(remote_path, 0, state, cancellation_manager)
    except Exception as e:
        logging.error(f"Error processing Steam Userdata: {e}")


def _search_proton_steam(state: LinuxSearchState, appid: str, cancellation_manager=None) -> None:
    """Search Proton compatdata for Steam games."""
    steam_base_paths = [
        os.path.join(os.path.expanduser("~"), ".steam", "steam"),
        os.path.join(os.path.expanduser("~"), ".local", "share", "Steam"),
        os.path.join(os.path.expanduser("~"), ".steam", "root"),
        os.path.join(os.path.expanduser("~"), ".steam", "debian-installation"),
        os.path.join(os.path.expanduser("~"), ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")
    ]
    
    for steam_base in steam_base_paths:
        compatdata_path = os.path.join(steam_base, 'steamapps', 'compatdata', appid, 'pfx')
        if not os.path.isdir(compatdata_path):
            continue
            
        _add_guess(state, compatdata_path, f"Proton Prefix ({appid})", False)

        if not getattr(config, 'LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM', True):
            continue
            
        if not (cancellation_manager and cancellation_manager.check_cancelled()):
            _search_proton_prefix_deep(compatdata_path, appid, state, cancellation_manager)

        for fragment in state.proton_user_path_fragments:
            if cancellation_manager and cancellation_manager.check_cancelled():
                break
            proton_save_path = os.path.join(compatdata_path, fragment)
            if os.path.isdir(proton_save_path):
                _add_guess(state, proton_save_path, f"Proton Prefix/{fragment} ({appid})", False)
                _search_recursive(proton_save_path, 0, state, cancellation_manager)


def _search_install_directory(state: LinuxSearchState, game_install_dir: str, cancellation_manager=None) -> None:
    """Search game installation directory for save paths."""
    if not game_install_dir or not os.path.isdir(game_install_dir):
        return
        
    state.is_exploring_install_dir = True
    state.install_dir_root = os.path.normpath(game_install_dir).lower()
    _search_recursive(game_install_dir, 0, state, cancellation_manager)
    state.is_exploring_install_dir = False
    state.install_dir_root = None


def _search_xdg_locations(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search XDG and common Linux paths for save paths."""
    for loc_desc, base_path in state.linux_known_save_locations.items():
        if cancellation_manager and cancellation_manager.check_cancelled():
            break
        if not os.path.isdir(base_path):
            continue
            
        _add_guess(state, base_path, loc_desc, True)

        # Search for direct game name subdirectories
        for abbr_or_name in state.game_abbreviations:
            direct_game_path = os.path.join(base_path, abbr_or_name)
            _add_guess(state, direct_game_path, f"{loc_desc}/DirectGameName/{abbr_or_name}", False)

        # Skip if already covered by Proton scan
        skip_double_compat = False
        try:
            if getattr(config, 'LINUX_SKIP_KNOWN_LOCATIONS_COMPAT_RECURSE_IF_PROTON_ENABLED', True):
                proton_enabled = (getattr(config, 'LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM', True) or
                                 getattr(config, 'LINUX_ENABLE_PROTON_SCAN_NONSTEAM', True))
                if proton_enabled and 'steamapps' in base_path and 'compatdata' in base_path:
                    skip_double_compat = True
        except Exception:
            pass

        if not skip_double_compat:
            _search_recursive(base_path, 0, state, cancellation_manager)


def _search_home_fallback(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search user's home directory as fallback."""
    if getattr(config, 'LINUX_SKIP_HOME_FALLBACK', False):
        return
        
    user_home = os.path.expanduser('~')
    try:
        home_in_known = any(os.path.normpath(base) == os.path.normpath(user_home)
                          for base in state.linux_known_save_locations.values())
    except Exception:
        home_in_known = False

    if not home_in_known:
        _search_recursive(user_home, 0, state, cancellation_manager)


def _rank_and_sort_results(state: LinuxSearchState, game_name: str) -> List[Tuple]:
    """Rank and sort the found paths, return final results."""
    if not state.guesses_data:
        logging.warning(f"LINUX_GUESS_SAVE_PATH: No potential save paths found for '{game_name}'.")
        return []

    sorted_guesses = sorted(state.guesses_data.items(), key=lambda item: _final_sort_key_linux(item, state))

    # Log top results
    logging.info(f"LINUX_GUESS_SAVE_PATH: Found {len(sorted_guesses)} potential paths for '{game_name}'. Top 5:")
    for i, (path, data) in enumerate(sorted_guesses[:5]):
        source = next(iter(data.get('sources', set())), "UnknownSource")
        has_saves = data.get('has_saves_hint', False)
        score = -_final_sort_key_linux((path, data), state)[0]
        logging.info(f"  {i+1}. {path} (Source: {source}, HasSaves: {has_saves}, Score: {score})")

    return [
        (path, -_final_sort_key_linux((path, data), state)[0], bool(data.get('has_saves_hint', False)))
        for path, data in sorted_guesses
    ]


def guess_save_path(game_name: str, game_install_dir: str, appid: str = None,
                    steam_userdata_path: str = None, steam_id3_to_use: str = None,
                    is_steam_game: bool = True, installed_steam_games_dict: Dict = None,
                    cancellation_manager: cancellation_utils.CancellationManager = None) -> List[Tuple]:
    """
    Main entry point for finding save paths on Linux.
    Returns a list of (path, score, has_saves_hint) tuples sorted by score.
    """
    logging.info(f"LINUX_GUESS_SAVE_PATH: Starting search for '{game_name}' (AppID: {appid})")

    # Build state - single source of truth
    state = _build_search_state(
        game_name_raw=game_name,
        game_install_dir_raw=game_install_dir,
        installed_steam_games_dict=installed_steam_games_dict,
        steam_app_id_raw=appid,
        steam_userdata_path=steam_userdata_path
    )

    # 1. Steam Userdata (High Priority)
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        _search_steam_userdata(state, appid, steam_userdata_path, steam_id3_to_use, cancellation_manager)

    # 2. Proton Compatdata (for Steam games)
    if is_steam_game and appid:
        _search_proton_steam(state, appid, cancellation_manager)

    # 3. Proton for non-Steam games
    if (not is_steam_game or not appid) and getattr(config, 'LINUX_ENABLE_PROTON_SCAN_NONSTEAM', True):
        _search_proton_for_non_steam_games(state, cancellation_manager)

    # 4. Snap games search
    if getattr(config, 'LINUX_ENABLE_SNAP_SEARCH', True):
        if not (cancellation_manager and cancellation_manager.check_cancelled()):
            _search_snap_games(state, cancellation_manager)

    # 5. Game Install Directory
    _search_install_directory(state, game_install_dir, cancellation_manager)

    # 6. XDG and Common Linux Paths
    _search_xdg_locations(state, cancellation_manager)

    # 7. User's Home Directory (fallback)
    _search_home_fallback(state, cancellation_manager)

    # Rank and return results
    return _rank_and_sort_results(state, game_name)
