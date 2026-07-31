# save_path_finder_linux.py
"""
Linux save path finder - Refactored to use LinuxSearchState as single source of truth.
No more global variables or thread-local storage.
"""
import os
import re
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Tuple, List, Set, Iterable
from common import cancellation_utils
import config

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
__all__ = [
    'LinuxSearchState',
    'LinuxGameContext',
    'LinuxSavePathFinder',
    'LinuxPathSearchEngine',
    'generate_abbreviations',
    'matches_initial_sequence',
    'are_names_similar',
    'clean_for_comparison',
    'final_sort_key',
    'guess_save_path',
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class LinuxSearchState:
    """Single source of truth for all search state and configuration."""
    # Game identification
    game_name_raw: str
    game_name_cleaned: str
    game_install_dir: Optional[str] = None
    is_steam_game: bool = True
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
    steam_id3_to_use: Optional[str] = None
    steam_userdata_roots: Set[str] = field(default_factory=set)
    
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
    explored_paths: Set[str] = field(default_factory=set)
    
    # Results containers
    guesses_data: Dict[str, Dict] = field(default_factory=dict)
    checked_paths: Set[str] = field(default_factory=set)
    candidate_paths_by_key: Dict[str, str] = field(default_factory=dict)


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
SCORE_SPECIFIC_SAVE_DIR_BONUS = 700
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


# Roman numerals and path semantics are deliberately kept local to this module.
# The Linux finder can be imported directly by core_logic, so importing the
# Windows finder here would create a circular import on Linux.
ROMAN_TO_ARABIC = {
    'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5',
    'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10',
    'XI': '11', 'XII': '12', 'XIII': '13', 'XIV': '14', 'XV': '15',
    'XVI': '16', 'XVII': '17', 'XVIII': '18', 'XIX': '19', 'XX': '20',
}
ARABIC_TO_ROMAN = {value: key for key, value in ROMAN_TO_ARABIC.items()}

SPECIFIC_SAVE_FOLDERS = {
    'save', 'saves', 'savegame', 'savegames', 'save_data', 'savedata',
    'saved', 'gamesave', 'gamesaves', 'saved games', 'gamedata',
    'profiles', 'slots',
}

GENERIC_CONTAINER_FOLDERS = {
    '', '.', 'home', '.config', '.local', 'share', '.var', 'app', 'data',
    'config', 'pfx', 'drive_c', 'users', 'steamuser', 'user', 'default',
    'appdata', 'local', 'locallow', 'roaming', 'documents', 'my documents',
    'program files', 'program files (x86)', 'steamapps', 'compatdata',
    'common', 'games', 'snap', 'current',
}

INSTALL_CONTAINER_FOLDERS = {
    'bin', 'binaries', 'content', 'engine', 'game', 'games', 'lib', 'lib64',
    'linux', 'linux64', 'resources', 'win32', 'win64', 'x64', 'x86',
}

ENGINE_CONTAINER_FOLDERS = {
    'unity3d', 'unreal', 'unrealengine', 'godot', 'gamemaker', 'construct',
}

MANDATORY_TITLE_QUALIFIERS = {
    'edition', 'ultimate', 'complete', 'remastered', 'remaster', 'remake',
    'definitive', 'enhanced', 'deluxe', 'goty', 'directors', 'director',
    'cut',
}

GRAMMATICAL_TITLE_WORDS = {'a', 'an', 'the', 'of', 'and'}

# A small directional allow-list for titles whose common store/desktop name is
# the base game while the save directory includes a non-numbered release name.
# This must stay narrow: generic suffix matching confuses distinct games such
# as Resident Evil and Resident Evil Village.
OPTIONAL_ON_DISK_VARIANT_SUFFIXES = {'afterbirth'}

STRICT_SAVE_EXTENSIONS_FALLBACK = {
    'sav', 'save', 'slot', 'sl2', 'ess', 'fos', 'lsf', 'lsb', 'profile',
    'state', 'srm', 'gci', 'mcr', 'mc', 'eep', 'fla', 'ark', 'rws',
}

DATABASE_SAVE_KEYWORDS = {
    'save', 'state', 'profile', 'progress', 'player', 'world',
}

NON_SAVE_FILENAME_EXTENSIONS = {
    'log', 'ini', 'cfg', 'txt', 'html', 'htm', 'css', 'js', 'dll', 'exe',
    'so', 'pak', 'cache', 'tmp', 'vdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp',
    'gif', 'svg', 'ogg', 'wav', 'mp3', 'mp4', 'mkv', 'ttf', 'otf', 'md',
    'yaml', 'yml',
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _normalise_path_text(path: str) -> str:
    """Return a separator-independent representation for path comparisons."""
    return os.path.normpath(path).replace('\\', '/')


def _similarity_ignore_words() -> Set[str]:
    configured = getattr(
        config,
        'SIMILARITY_IGNORE_WORDS',
        {'a', 'an', 'the', 'of', 'and'},
    )
    return {
        str(word).casefold()
        for word in configured
    } | MANDATORY_TITLE_QUALIFIERS


def _path_key(path: str) -> str:
    """Canonical key without collapsing distinct case-sensitive Linux paths."""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except (OSError, TypeError, ValueError):
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _path_parts(path: str) -> List[str]:
    return [part for part in _normalise_path_text(path).split('/') if part]


def _is_path_within(path: str, parent: str) -> bool:
    """Safely test containment, avoiding substring matches such as game/game2."""
    if not path or not parent:
        return False
    try:
        path_key = _path_key(path)
        parent_key = _path_key(parent)
        return os.path.commonpath([path_key, parent_key]) == parent_key
    except (OSError, TypeError, ValueError):
        path_text = _normalise_path_text(path).rstrip('/')
        parent_text = _normalise_path_text(parent).rstrip('/')
        return path_text == parent_text or path_text.startswith(parent_text + '/')


def _tokenize_name(name: str) -> List[str]:
    """Split display names, compact CamelCase names and numeric suffixes."""
    if not isinstance(name, str):
        return []
    cleaned = unicodedata.normalize('NFKC', name)
    cleaned = re.sub(r'[™®©]', '', cleaned)
    cleaned = re.sub(r"['’]", '', cleaned)
    chunks = re.split(r'[^\w]+', cleaned, flags=re.UNICODE)
    tokens: List[str] = []
    token_pattern = re.compile(
        r'[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|[A-Za-z]+(?=\d)|\d+'
    )
    for chunk in chunks:
        if not chunk:
            continue
        split = token_pattern.findall(chunk) if chunk.isascii() else [chunk]
        tokens.extend(split if split else [chunk])
    return tokens


def _normalised_name_tokens(name: str) -> List[str]:
    result: List[str] = []
    for token in _tokenize_name(name):
        upper = token.upper()
        normalized = ROMAN_TO_ARABIC.get(upper, token.casefold())
        # Apostrophe-free directory names commonly spell "Don't" as either
        # "Dont" or CamelCase "DoNot".  Give both forms the same token stream.
        if normalized == 'dont':
            result.extend(('do', 'not'))
        else:
            result.append(normalized)
    return result


def _version_tokens(name: str) -> Set[str]:
    versions: Set[str] = set()
    for token in _tokenize_name(name):
        upper = token.upper()
        if upper in ROMAN_TO_ARABIC:
            versions.add(ROMAN_TO_ARABIC[upper])
        elif token.isdigit() and (
            len(token) <= 2
            or (len(token) == 4 and 1900 <= int(token) <= 2099)
        ):
            versions.add(str(int(token)))
    return versions


def _compact_name(name: str) -> str:
    return ''.join(_normalised_name_tokens(name))


def _add_alias(aliases: Set[str], value: str) -> None:
    if not value:
        return
    value = re.sub(r'\s+', ' ', value).strip()
    alphanumeric = ''.join(character for character in value if character.isalnum())
    if len(alphanumeric) < 2:
        return
    aliases.add(value)
    aliases.add(re.sub(r'\s+', '', value))
    aliases.add(alphanumeric)


def _acronym_variants(tokens: Iterable[str]) -> Set[str]:
    """Build acronyms while preserving complete numeric/roman tokens."""
    token_list = [token for token in tokens if token]
    if len(token_list) < 2:
        return set()

    raw_parts: List[str] = []
    numeric_parts: List[str] = []
    roman_parts: List[str] = []
    for token in token_list:
        upper = token.upper()
        if upper in ROMAN_TO_ARABIC:
            raw_parts.append(upper)
            numeric_parts.append(ROMAN_TO_ARABIC[upper])
            roman_parts.append(upper)
        elif token.isdigit():
            raw_parts.append(token)
            numeric_parts.append(token)
            roman_parts.append(ARABIC_TO_ROMAN.get(token, token))
        else:
            initial = token[0].upper()
            raw_parts.append(initial)
            numeric_parts.append(initial)
            roman_parts.append(initial)
    return {
        ''.join(parts)
        for parts in (raw_parts, numeric_parts, roman_parts)
        if len(''.join(parts)) >= 2
    }


def _strip_executable_suffix(stem: str) -> str:
    suffixes = (
        '-Win64-Shipping', '-Win32-Shipping', '-Linux-Shipping',
        '-Shipping', '.x86_64', '.x86',
    )
    result = stem
    for suffix in suffixes:
        if result.lower().endswith(suffix.lower()):
            result = result[:-len(suffix)]
            break
    result = re.sub(r'(?i)(launcher|server|client|editor)$', '', result)
    return re.sub(r'[-_]+$', '', result).strip()


def _iter_install_name_hints(
    game_install_dir: Optional[str], game_name: Optional[str] = None
) -> Iterable[str]:
    """Yield a bounded set of useful directory/executable names."""
    if (
        not game_install_dir
        or not os.path.isdir(game_install_dir)
        or _is_unsafe_install_root(game_install_dir)
    ):
        return

    # Directory components are compared to the requested title directly.
    # Turning an arbitrary install directory (or its parent launcher/library
    # container) into a title alias makes that directory game-related by
    # definition and defeats the strict candidate filter.  Only executable
    # names are useful additional hints here.

    base_depth = os.path.normpath(game_install_dir).count(os.sep)
    files_seen = 0
    executable_hints: Dict[str, int] = {}
    try:
        for root, dirs, files in os.walk(game_install_dir, topdown=True):
            relative_depth = os.path.normpath(root).count(os.sep) - base_depth
            if relative_depth >= 2:
                dirs[:] = []
            dirs[:] = [
                directory for directory in dirs
                if directory.lower() not in {
                    'engine', 'redist', '_commonredist', 'thirdparty',
                }
            ][:40]
            for filename in files[:80]:
                files_seen += 1
                lower = filename.lower()
                is_executable = (
                    lower.endswith((
                        '.exe', '.x86', '.x86_64', '.bin', '.run', '.sh',
                        '.appimage',
                    ))
                    or ('.' not in filename and os.access(os.path.join(root, filename), os.X_OK))
                )
                if is_executable:
                    stem = os.path.splitext(filename)[0]
                    hint = _strip_executable_suffix(stem)
                    hint_lower = hint.lower()
                    if (
                        len(hint) >= 3
                        and hint_lower not in {
                            'launcher', 'start', 'steam', 'proton', 'unitycrashhandler64',
                        }
                        and not any(
                            marker in hint_lower
                            for marker in {
                                'anticheat', 'crashhandler', 'unins', 'setup',
                                'installer', 'prerequisite', 'redistributable',
                            }
                        )
                    ):
                        try:
                            size = os.path.getsize(os.path.join(root, filename))
                        except OSError:
                            size = 0
                        executable_hints[hint] = max(
                            size, executable_hints.get(hint, 0)
                        )
                if files_seen >= 160:
                    dirs[:] = []
                    break
            if files_seen >= 160:
                break
    except OSError:
        pass

    for hint, _ in sorted(
        executable_hints.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    )[:3]:
        yield hint

def clean_for_comparison(name: str) -> str:
    """Clean a name for comparison - removes symbols, normalizes separators, lowercase."""
    if not isinstance(name, str):
        return ""
    name_cleaned = unicodedata.normalize('NFKC', name)
    name_cleaned = re.sub(r'[™®©:]', '', name_cleaned)
    name_cleaned = re.sub(r'[-_]', ' ', name_cleaned)
    name_cleaned = re.sub(r'\s+', ' ', name_cleaned).strip()
    return name_cleaned.casefold()


def generate_abbreviations(game_name_raw: str, game_install_dir_raw: str = None) -> List[str]:
    """Generate conservative title aliases without broad single-word matches."""
    abbreviations: Set[str] = set()
    if not game_name_raw:
        return []

    display_name = re.sub(r'^(Play |Launch )', '', game_name_raw, flags=re.IGNORECASE)
    display_name = re.sub(r'[™®©]', '', display_name).strip()
    _add_alias(abbreviations, display_name)

    raw_tokens = _tokenize_name(display_name)
    normalised_tokens = [
        ROMAN_TO_ARABIC.get(token.upper(), token) for token in raw_tokens
    ]
    if normalised_tokens != raw_tokens:
        _add_alias(abbreviations, ' '.join(normalised_tokens))

    # Also generate the inverse numeral spelling ("DOOM 2" <-> "DOOM II").
    inverse_tokens = [
        ARABIC_TO_ROMAN.get(token, token) for token in raw_tokens
    ]
    if inverse_tokens != raw_tokens:
        _add_alias(abbreviations, ' '.join(inverse_tokens))

    ignore_words = _similarity_ignore_words()
    significant_tokens = [
        token for token in raw_tokens
        if token.lower() not in ignore_words and (len(token) > 1 or token.isdigit())
    ]

    # Full acronym and significant-word acronym, matching the mature Windows
    # finder while refusing one-letter aliases.
    abbreviations.update(_acronym_variants(raw_tokens))
    abbreviations.update(_acronym_variants(significant_tokens))

    # A title prefix ending in a version token is often the on-disk series
    # name: "Dark Souls II: Scholar..." stores saves under "DarkSoulsII".
    for index, token in enumerate(raw_tokens):
        if token.upper() in ROMAN_TO_ARABIC or token.isdigit():
            prefix_tokens = raw_tokens[:index + 1]
            if len(prefix_tokens) >= 2:
                _add_alias(abbreviations, ' '.join(prefix_tokens))
                abbreviations.update(_acronym_variants(prefix_tokens))
                numeric_prefix = [
                    ROMAN_TO_ARABIC.get(part.upper(), part)
                    for part in prefix_tokens
                ]
                _add_alias(abbreviations, ' '.join(numeric_prefix))
                abbreviations.update(_acronym_variants(numeric_prefix))
            break

    # A colon usually separates the stable game title from an edition/subtitle.
    if ':' in display_name:
        before_colon = display_name.split(':', 1)[0].strip()
        if len(_tokenize_name(before_colon)) >= 2:
            _add_alias(abbreviations, before_colon)

    for hint in _iter_install_name_hints(game_install_dir_raw, display_name):
        _add_alias(abbreviations, hint)

    final_abbreviations = {
        abbreviation for abbreviation in abbreviations
        if abbreviation
        and sum(character.isalnum() for character in abbreviation) >= 2
        and clean_for_comparison(abbreviation) not in GENERIC_CONTAINER_FOLDERS
    }
    return sorted(final_abbreviations, key=lambda value: (-len(value), value.lower(), value))


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
                      fuzz_engine=None, thefuzz_available: bool = None,
                      game_title_words_for_seq: List[str] = None) -> bool:
    """Compare game and folder names without permissive substring matching."""
    if game_title_sig_words_for_seq is None:
        game_title_sig_words_for_seq = game_title_words_for_seq
    if thefuzz_available is None:
        thefuzz_available = (fuzz_engine is not None)

    tokens1 = _normalised_name_tokens(str(name1_game_variant))
    tokens2 = _normalised_name_tokens(str(name2_path_component))
    if not tokens1 or not tokens2:
        return False

    compact1 = ''.join(tokens1)
    compact2 = ''.join(tokens2)
    if compact1 == compact2:
        return True

    versions1 = _version_tokens(str(name1_game_variant))
    versions2 = _version_tokens(str(name2_path_component))
    version_mismatch = versions1 != versions2 and bool(versions1 or versions2)

    ignore_words = _similarity_ignore_words()
    significant1 = [
        token for token in tokens1
        if token not in ignore_words and (len(token) > 1 or token.isdigit())
    ]
    significant2 = [
        token for token in tokens2
        if token not in ignore_words and (len(token) > 1 or token.isdigit())
    ]

    grammatical1 = [
        token for token in tokens1
        if token not in GRAMMATICAL_TITLE_WORDS
    ]
    grammatical2 = [
        token for token in tokens2
        if token not in GRAMMATICAL_TITLE_WORDS
    ]

    # Articles and conjunctions are frequently present only in the on-disk
    # title ("Witcher3" -> "The Witcher 3"). Edition qualifiers deliberately
    # remain significant here so matching stays directional.
    if (
        not version_mismatch
        and grammatical1
        and grammatical1 == grammatical2
    ):
        return True

    # Handle the few established base-title -> on-disk-variant spellings
    # without permitting arbitrary sequel subtitles.
    on_disk_suffix = grammatical2[len(grammatical1):]
    if (
        not version_mismatch
        and len(grammatical1) >= 2
        and grammatical2[:len(grammatical1)] == grammatical1
        and on_disk_suffix
        and all(
            token in OPTIONAL_ON_DISK_VARIANT_SUFFIXES
            for token in on_disk_suffix
        )
    ):
        return True

    # The on-disk folder may omit a suffix from the requested game title, but
    # only when a shared version number anchors it (DarkSoulsII) or the omitted
    # suffix consists exclusively of edition words.
    if (
        not version_mismatch
        and len(compact2) >= 5
        and compact1.startswith(compact2)
    ):
        version_anchored = bool(versions1) and versions1 == versions2
        token_prefix = tokens1[:len(tokens2)] == tokens2
        omitted_tokens = tokens1[len(tokens2):] if token_prefix else []
        edition_only_suffix = bool(omitted_tokens) and all(
            token in ignore_words for token in omitted_tokens
        )
        if version_anchored or edition_only_suffix:
            return True

    # Directional short-folder alias. Do not let a longer path component extend
    # a one-word game title (DOOM -> DOOM Eternal). A middle word such as
    # "Isaac" can still abbreviate a title with at least three core words.
    if (
        not version_mismatch
        and len(significant2) == 1
        and len(significant1) >= 3
        and len(significant2[0]) >= 4
        and significant2[0] in significant1[1:-1]
    ):
        return True

    if game_title_sig_words_for_seq and len(compact2) <= 6:
        if matches_initial_sequence(name2_path_component, game_title_sig_words_for_seq):
            return True

    # Acronym support that keeps complete version tokens (FFXIV/FF14, DSII/DS2).
    expected_for_folder = {
        acronym.casefold()
        for acronym in (
            _acronym_variants(_tokenize_name(str(name1_game_variant)))
            | _acronym_variants(significant1)
        )
    }
    if compact2.casefold() in expected_for_folder:
        return True

    expected_for_game = {
        acronym.casefold()
        for acronym in (
            _acronym_variants(_tokenize_name(str(name2_path_component)))
            | _acronym_variants(significant2)
        )
    }
    if compact1.casefold() in expected_for_game:
        return True

    if thefuzz_available and fuzz_engine and not version_mismatch and 0 < fuzzy_threshold <= 100:
        try:
            clean1 = ' '.join(tokens1)
            clean2 = ' '.join(tokens2)
            if fuzz_engine.token_sort_ratio(clean1, clean2) >= fuzzy_threshold:
                return True
        except Exception as error:
            logging.debug(f"Linux name matching failed for '{name1_game_variant}'/'{name2_path_component}': {error}")

    return False


# =============================================================================
# STATE INITIALIZATION
# =============================================================================

def _build_search_state(game_name_raw: str, game_install_dir_raw: str,
                        installed_steam_games_dict: Dict = None,
                        steam_app_id_raw: str = None,
                        steam_userdata_path: str = None,
                        steam_id3_to_use: str = None,
                        is_steam_game: bool = True) -> LinuxSearchState:
    """Build a complete LinuxSearchState from input parameters."""
    
    game_name_cleaned = clean_for_comparison(game_name_raw)
    
    # Build game_title_original_sig_words_for_seq
    temp_name_for_seq = re.sub(r'[™®©:]', '', game_name_raw)
    temp_name_for_seq = re.sub(r'[-_]', ' ', temp_name_for_seq)
    temp_name_for_seq = re.sub(r'\s+', ' ', temp_name_for_seq).strip()
    original_game_words_with_case = temp_name_for_seq.split(' ')

    ignore_words_for_seq_lower = _similarity_ignore_words()

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
    game_abbreviations_lower = {
        clean_for_comparison(abbr)
        for abbr in game_abbreviations
        if clean_for_comparison(abbr)
    }

    logging.debug(
        f"Generated Linux search aliases for '{game_name_raw}': "
        f"{game_abbreviations}"
    )

    # Load config values
    known_companies_lower = [
        str(kc).strip().casefold()
        for kc in getattr(config, 'COMMON_PUBLISHERS', [])
        if str(kc).strip()
    ]
    linux_common_save_subdirs_lower = {csd.lower() for csd in getattr(config, 'LINUX_COMMON_SAVE_SUBDIRS', [])}
    linux_banned_path_fragments_lower = {bps.lower() for bps in getattr(config, 'LINUX_BANNED_PATH_FRAGMENTS', getattr(config, 'BANNED_FOLDER_NAMES_LOWER', []))}
    common_save_extensions = {e.lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    common_save_extensions_nodot = {e.lstrip('.').lower() for e in getattr(config, 'COMMON_SAVE_EXTENSIONS', set())}
    common_save_filenames_lower = {f.lower() for f in getattr(config, 'COMMON_SAVE_FILENAMES', set())}
    proton_user_path_fragments = getattr(config, 'PROTON_USER_PATH_FRAGMENTS', [])

    # Load known save locations. XDG environment overrides are authoritative and
    # are added explicitly even if config.py still contains the default paths.
    linux_known_save_locations = {}
    home_dir = os.path.expanduser('~')
    xdg_data_home = os.getenv('XDG_DATA_HOME') or os.path.join(home_dir, '.local', 'share')
    xdg_config_home = os.getenv('XDG_CONFIG_HOME') or os.path.join(home_dir, '.config')
    linux_known_save_locations['XDG Data'] = os.path.expanduser(xdg_data_home)
    linux_known_save_locations['XDG Config'] = os.path.expanduser(xdg_config_home)
    linux_known_save_locations['Godot App Userdata'] = os.path.join(
        os.path.expanduser(xdg_data_home), 'godot', 'app_userdata'
    )

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
        game_name_raw=game_name_raw,
        game_name_cleaned=game_name_cleaned,
        game_install_dir=game_install_dir_raw,
        is_steam_game=is_steam_game,
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
        steam_id3_to_use=steam_id3_to_use,
        steam_userdata_roots=(
            {os.path.normpath(os.path.abspath(steam_userdata_path))}
            if steam_userdata_path
            else set()
        ),
        max_files_to_scan_linux_hint=getattr(config, 'MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT', 100),
        min_save_files_for_bonus_linux=getattr(config, 'MIN_SAVE_FILES_FOR_BONUS_LINUX', 2),
        max_sub_items_to_scan_linux=getattr(config, 'MAX_SUB_ITEMS_TO_SCAN_LINUX', 50),
        max_shallow_explore_depth_linux=getattr(config, 'MAX_SHALLOW_EXPLORE_DEPTH_LINUX', 1),
        max_search_depth_linux=getattr(
            config,
            'MAX_SEARCH_DEPTH_LINUX',
            max(
                getattr(config, 'MAX_DEPTH_PROTON_COMPATDATA_LINUX', 5),
                getattr(config, 'MAX_DEPTH_GAME_INSTALL_DIR_LINUX', 4),
                getattr(config, 'MAX_DEPTH_COMMON_LINUX_LOCATIONS', 3),
            ),
        ),
        fuzzy_threshold_basename_match=getattr(config, 'FUZZY_THRESHOLD_BASENAME_MATCH', 85),
        fuzzy_threshold_path_match=getattr(config, 'FUZZY_THRESHOLD_PATH_MATCH', 75),
        THEFUZZ_AVAILABLE=_THEFUZZ_AVAILABLE,
        fuzz=_fuzz_module,
        MAX_USERDATA_SCORE=getattr(config, 'MAX_USERDATA_SCORE', 1100),
    )


def _component_matches_game(component: str, state: LinuxSearchState) -> bool:
    """Return True only for a complete component-level title/alias match."""
    if not component:
        return False
    cleaned_component = clean_for_comparison(component)
    stripped_component = cleaned_component.lstrip('.')
    if not stripped_component or stripped_component in GENERIC_CONTAINER_FOLDERS:
        return False

    comparison_components = [component]
    unity_product_match = re.match(
        r'^(?P<game>.+?)\s+by\s+(?P<publisher>.+)$',
        component,
        flags=re.IGNORECASE,
    )
    if unity_product_match:
        comparison_components.append(
            unity_product_match.group('game').strip()
        )

    for comparison_component in comparison_components:
        cleaned_comparison = clean_for_comparison(comparison_component)
        stripped_comparison = cleaned_comparison.lstrip('.')
        compact_component = _compact_name(comparison_component)
        for abbreviation in state.game_abbreviations:
            cleaned_abbreviation = clean_for_comparison(abbreviation)
            if (
                cleaned_comparison == cleaned_abbreviation
                or stripped_comparison == cleaned_abbreviation
                or compact_component == _compact_name(abbreviation)
            ):
                return True

        if are_names_similar(
            state.game_name_raw,
            comparison_component,
            game_title_sig_words_for_seq=state.game_title_original_sig_words_for_seq,
            fuzzy_threshold=state.fuzzy_threshold_basename_match,
            fuzz_engine=state.fuzz,
            thefuzz_available=state.THEFUZZ_AVAILABLE,
        ):
            return True
    return False


def _component_matches_company(component: str, state: LinuxSearchState) -> bool:
    """Match publisher folders, including conventional hidden variants."""
    cleaned = str(component or '').strip().casefold()
    return bool(
        cleaned
        and (
            cleaned in state.known_companies_lower
            or cleaned.lstrip('.') in state.known_companies_lower
        )
    )


def _flatpak_package_matches_game(component: str, state: LinuxSearchState) -> bool:
    """Use only the application part of a reverse-DNS Flatpak package ID."""
    package_parts = [
        part for part in component.split('.') if part
    ]
    if len(package_parts) < 3:
        return False
    return _component_matches_game(package_parts[-1], state)


def _is_flatpak_app_base(path: str) -> bool:
    parts = [part.casefold() for part in _path_parts(path)]
    return len(parts) >= 2 and parts[-2:] == ['.var', 'app']


def _is_renpy_base(path: str) -> bool:
    return (
        os.path.basename(os.path.normpath(path)).casefold() == '.renpy'
    )


def _renpy_directory_matches_game(
    component: str,
    state: LinuxSearchState,
) -> bool:
    """Match Ren'Py's configured save directory with its numeric suffix."""
    without_identifier = re.sub(r'[-_ ]\d{5,}$', '', component).strip()
    return (
        without_identifier != component
        and _component_matches_game(without_identifier, state)
    )


def _contains_direct_game_child(
    directory: str,
    state: LinuxSearchState,
    max_children: int = 200,
) -> bool:
    """Peek below an engine publisher folder for an exact game directory."""
    try:
        child_names = sorted(os.listdir(directory), key=str.casefold)
    except OSError:
        return False

    for child_name in child_names[:max_children]:
        child_path = os.path.join(directory, child_name)
        if not os.path.isdir(child_path):
            continue
        if _component_matches_game(child_name, state):
            return True
    return False


def _path_has_game_context(path: str, state: LinuxSearchState) -> bool:
    """Look for game components inside the typed search scope.

    Host components (username, mount point, library name) must not make every
    descendant look related merely because one happens to equal the game name.
    """
    path_parts = _path_parts(path)

    # For Proton, only components inside the AppID prefix can describe the save
    # layout. This also ignores game-like mount/library names.
    appid = str(state.current_steam_app_id) if state.current_steam_app_id else None
    proton_scope_found = False
    if appid:
        for index in range(max(0, len(path_parts) - 2)):
            if (
                path_parts[index].casefold() == 'compatdata'
                and path_parts[index + 1] == appid
                and path_parts[index + 2].casefold() == 'pfx'
            ):
                path_parts = path_parts[index + 3:]
                proton_scope_found = True
                break
    if not proton_scope_found:
        scope_candidates: List[str] = [os.path.expanduser('~')]
        scope_candidates.extend(state.linux_known_save_locations.values())
        if state.game_install_dir:
            scope_candidates.append(
                os.path.dirname(os.path.abspath(state.game_install_dir))
            )

        containing_scopes = [
            scope
            for scope in scope_candidates
            if scope and _is_path_within(path, scope)
        ]
        if containing_scopes:
            scope = max(
                containing_scopes,
                key=lambda candidate: len(_normalise_path_text(candidate)),
            )
            try:
                path_parts = _path_parts(os.path.relpath(path, scope))
            except (OSError, TypeError, ValueError):
                pass
            if (
                _is_flatpak_app_base(scope)
                and path_parts
                and _flatpak_package_matches_game(path_parts[0], state)
            ):
                return True
            if (
                _is_renpy_base(scope)
                and path_parts
                and _renpy_directory_matches_game(path_parts[0], state)
            ):
                return True

    for component in reversed(path_parts):
        if _component_matches_game(component, state):
            return True
    return False


def _path_has_appid_context(path: str, state: LinuxSearchState) -> bool:
    if not state.current_steam_app_id:
        return False
    appid = str(state.current_steam_app_id)
    return appid in _path_parts(path)


def _is_generic_container(path: str) -> bool:
    return os.path.basename(os.path.normpath(path)).lower() in GENERIC_CONTAINER_FOLDERS


def _is_unsafe_install_root(path: str) -> bool:
    """Reject launcher/system locations that cannot be a game's install tree."""
    if not path:
        return True
    try:
        normalized = _normalise_path_text(
            os.path.realpath(os.path.abspath(path))
        ).rstrip('/').casefold()
    except (OSError, TypeError, ValueError):
        normalized = _normalise_path_text(path).rstrip('/').casefold()

    basename = os.path.basename(os.path.normpath(path)).casefold()
    if basename in {'bin', 'sbin', 'lib', 'lib64', 'usr', 'etc'}:
        return True

    return normalized in {
        '/bin', '/sbin', '/usr', '/usr/bin', '/usr/sbin', '/usr/lib',
        '/usr/lib64', '/lib', '/lib64', '/etc', '/var', '/boot', '/dev',
        '/proc', '/sys', '/run',
    }


def _is_cancelled(cancellation_manager) -> bool:
    try:
        return bool(cancellation_manager and cancellation_manager.check_cancelled())
    except Exception:
        return False


def _has_named_save_subdir(path: str, max_depth: int = 2) -> bool:
    """Bounded structural evidence for roots whose save files are nested."""
    try:
        base_depth = os.path.normpath(path).count(os.sep)
        for root, dirs, _ in os.walk(path, topdown=True):
            relative_depth = os.path.normpath(root).count(os.sep) - base_depth
            if relative_depth >= max_depth:
                dirs[:] = []
                continue
            dirs[:] = sorted(dirs, key=str.casefold)[:60]
            if any(directory.lower() in SPECIFIC_SAVE_FOLDERS for directory in dirs):
                return True
    except OSError:
        return False
    return False


def _deep_scan_save_evidence(
    path: str,
    state: LinuxSearchState,
    max_depth: int = 3,
    cancellation_manager=None,
) -> Tuple[bool, int]:
    """Find strict save evidence in a small descendant tree."""
    found = 0
    try:
        base_depth = os.path.normpath(path).count(os.sep)
        for root, dirs, _ in os.walk(path, topdown=True):
            if _is_cancelled(cancellation_manager):
                return found > 0, found
            relative_depth = os.path.normpath(root).count(os.sep) - base_depth
            if relative_depth > max_depth:
                dirs[:] = []
                continue
            dirs[:] = sorted(
                (
                    directory for directory in dirs
                    if directory.lower()
                    not in {
                        '.cache', 'cache', 'logs', 'log', 'shadercache',
                        'gpucache', 'screenshots',
                    }
                ),
                key=str.casefold,
            )[:60]
            has_saves, count = _scan_dir_for_save_evidence(root, state)
            if has_saves:
                found += count
                if found >= 5:
                    return True, found
    except OSError:
        return found > 0, found
    return found > 0, found


# =============================================================================
# DIRECTORY SCANNING HELPERS
# =============================================================================

def _scan_dir_for_save_evidence(dir_path: str, state: LinuxSearchState) -> Tuple[bool, int]:
    """Scan a directory for save file evidence."""
    has_evidence = False
    save_file_count = 0
    files_scanned_count = 0

    strict_exts = {
        extension.lower().lstrip('.')
        for extension in getattr(
            config,
            'LINUX_STRICT_SAVE_EXTENSIONS',
            STRICT_SAVE_EXTENSIONS_FALLBACK,
        )
    }
    strict_keywords = {
        str(keyword).casefold()
        for keyword in getattr(
            config,
            'LINUX_STRICT_SAVE_FILENAME_KEYWORDS',
            set(),
        )
    }

    def evidence_priority(item_name: str) -> Tuple[int, str]:
        item_lower = item_name.casefold()
        _, extension = os.path.splitext(item_lower)
        extension = extension.lstrip('.')
        database_save = (
            extension == 'db'
            and any(
                keyword in item_lower
                for keyword in DATABASE_SAVE_KEYWORDS
            )
        )
        shaped_name = bool(
            item_lower == 'steam_autocloud.vdf'
            or re.match(
                r'^(?:user|profile|slot|save|player)\d*\.(?:dat|bin)$',
                item_lower,
            )
            or extension in strict_exts
            or database_save
            or (
                extension not in NON_SAVE_FILENAME_EXTENSIONS
                and any(keyword in item_lower for keyword in strict_keywords)
            )
        )
        return (0 if shaped_name else 1, item_lower)

    try:
        for item_name in sorted(os.listdir(dir_path), key=evidence_priority):
            if files_scanned_count >= state.max_files_to_scan_linux_hint:
                break

            item_path = os.path.join(dir_path, item_name)
            if os.path.isfile(item_path):
                files_scanned_count += 1
                item_name_lower = item_name.lower()
                _, ext_lower = os.path.splitext(item_name_lower)
                ext_lower = ext_lower.lstrip('.')

                is_matching_file = False
                if item_name_lower == 'steam_autocloud.vdf':
                    is_matching_file = True
                elif (
                    ext_lower == 'db'
                    and any(
                        keyword in item_name_lower
                        for keyword in DATABASE_SAVE_KEYWORDS
                    )
                ):
                    is_matching_file = True
                elif re.match(
                    r'^(?:user|profile|slot|save|player)\d*\.(?:dat|bin)$',
                    item_name_lower,
                ):
                    is_matching_file = True
                elif item_name_lower == 'remotecache.vdf':
                    is_matching_file = False
                elif ext_lower in NON_SAVE_FILENAME_EXTENSIONS:
                    is_matching_file = False
                elif getattr(config, 'LINUX_STRICT_EVIDENCE_MODE', True):
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
    basename = os.path.basename(os.path.normpath(dir_path))
    basename_lower = basename.lower()
    name_matches_game = _component_matches_game(basename, state)
    is_common_save_dir = (
        basename_lower in state.linux_common_save_subdirs_lower
        or basename_lower in SPECIFIC_SAVE_FOLDERS
    )
    has_save_files_evidence, save_file_count_for_bonus = _scan_dir_for_save_evidence(dir_path, state)
    has_actual_save_files_for_bonus = (
        has_save_files_evidence
        and save_file_count_for_bonus >= state.min_save_files_for_bonus_linux
    )
    return (
        name_matches_game or is_common_save_dir or has_save_files_evidence,
        has_actual_save_files_for_bonus,
    )


def _is_in_userdata(path_lower: str, steam_userdata_path: str = None) -> bool:
    """Check if a path is within Steam userdata."""
    if not steam_userdata_path:
        return False
    return _is_path_within(path_lower, steam_userdata_path)


def _identify_path_type(path_lower: str, source_lower: str, steam_userdata_path: str = None) -> Dict[str, bool]:
    """Identify path type for penalty calculation."""
    path_check = _normalise_path_text(path_lower).lower()
    source_check = source_lower.replace('\\', '/').lower()
    is_steam_remote = (
        'steam userdata' in source_check
        and '/remote' in source_check
    )
    if steam_userdata_path:
        is_steam_remote = (
            is_steam_remote
            or (
                _is_path_within(path_lower, steam_userdata_path)
                and '/remote' in path_check
            )
        )

    is_steam_base = (
        'steam userdata' in source_check
        and not is_steam_remote
    )
    if steam_userdata_path:
        is_steam_base = (
            is_steam_base
            or (
                _is_path_within(path_lower, steam_userdata_path)
                and not is_steam_remote
            )
        )

    home_dir = os.path.expanduser('~')
    xdg_data_home = (
        os.getenv('XDG_DATA_HOME')
        or os.path.join(home_dir, '.local', 'share')
    )
    xdg_config_home = (
        os.getenv('XDG_CONFIG_HOME')
        or os.path.join(home_dir, '.config')
    )
    prime_roots = [
        xdg_data_home,
        xdg_config_home,
        os.path.join(home_dir, '.var', 'app'),
    ]
    is_prime_location = any(_is_path_within(path_lower, root) for root in prime_roots)

    user_data_roots = prime_roots + [
        home_dir,
        os.path.join(home_dir, 'snap'),
    ]
    is_user_data = any(
        root and _is_path_within(path_lower, root)
        for root in user_data_roots
    )
    system_install_roots = [
        '/opt',
        '/snap',
        '/usr/local',
        '/usr/share',
        '/var/games',
        '/var/lib',
    ]
    is_install_dir_walk = (
        'installdirwalk' in source_check
        or 'steamapps/common' in path_check
    )
    if not is_install_dir_walk and not is_user_data:
        is_install_dir_walk = (
            any(
                _is_path_within(path_lower, root)
                for root in system_install_roots
            )
        )

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
            if backup_base_dir and _is_path_within(path_lower, backup_base_dir):
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
               has_saves_hint_from_scan: bool) -> bool:
    """Validate and add one real, game-related directory.

    AppID/source strings locate the search scope; they are intentionally not
    sufficient evidence for returning generic Proton containers.
    """
    if not path_found:
        return False
    try:
        normalized_path = os.path.normpath(os.path.abspath(path_found))
        canonical_key = _path_key(normalized_path)
    except (OSError, TypeError, ValueError):
        return False

    if not os.path.isdir(normalized_path):
        state.checked_paths.add(canonical_key)
        return False

    existing_path = state.candidate_paths_by_key.get(canonical_key)
    if existing_path:
        existing = state.guesses_data[existing_path]
        existing.setdefault('sources', set()).add(source_description)
        existing['has_saves_hint'] = bool(
            existing.get('has_saves_hint') or has_saves_hint_from_scan
        )
        existing['has_saves_direct'] = bool(
            existing.get('has_saves_direct') or has_saves_hint_from_scan
        )
        return False

    try:
        backup_base_dir = config.get_default_backup_dir()
        if backup_base_dir and _is_path_within(normalized_path, backup_base_dir):
            state.checked_paths.add(canonical_key)
            return False
    except Exception:
        pass

    basename = os.path.basename(normalized_path)
    basename_lower = basename.lower()
    source_lower = source_description.lower()
    basename_matches_game = _component_matches_game(basename, state)
    path_has_game_context = _path_has_game_context(normalized_path, state)
    path_has_appid_context = _path_has_appid_context(normalized_path, state)
    is_common_save_dir = (
        basename_lower in state.linux_common_save_subdirs_lower
        or basename_lower in SPECIFIC_SAVE_FOLDERS
    )
    is_specific_save_dir = basename_lower in SPECIFIC_SAVE_FOLDERS

    scanned_has_saves, _ = _scan_dir_for_save_evidence(normalized_path, state)
    has_saves = bool(has_saves_hint_from_scan or scanned_has_saves)
    has_save_structure = _has_named_save_subdir(normalized_path)

    is_steam_userdata_candidate = (
        source_lower.startswith('steam userdata/')
        and path_has_appid_context
        and (
            basename == str(state.current_steam_app_id)
            or basename_lower == 'remote'
            or is_common_save_dir
            or has_saves
        )
    )
    is_proton_scope = (
        path_has_appid_context
        and ('proton' in source_lower or '/compatdata/' in _normalise_path_text(normalized_path).lower())
    )
    is_related_wine_scope = 'relatedwineprefix' in source_lower
    is_install_scope = 'installdirwalk' in source_lower

    accepted = False
    reason = ''
    if is_steam_userdata_candidate:
        accepted = True
        reason = 'Steam userdata AppID path'
    elif has_saves and (
        path_has_game_context
        or is_proton_scope
        or is_related_wine_scope
    ):
        accepted = True
        reason = 'Save files with game-specific search context'
    elif is_specific_save_dir and (
        path_has_game_context
        or is_proton_scope
        or is_related_wine_scope
    ):
        accepted = True
        reason = 'Specific save directory with game context'
    elif (
        is_common_save_dir
        and path_has_game_context
        and not _is_generic_container(normalized_path)
    ):
        accepted = True
        reason = 'Save-like directory below a matched game path'
    elif has_save_structure and (
        path_has_game_context
        or is_proton_scope
        or is_related_wine_scope
    ):
        accepted = True
        reason = 'Nested save-directory structure with game context'
    elif basename_matches_game and not is_install_scope and not _is_generic_container(normalized_path):
        accepted = True
        reason = 'Game title matches the directory name'

    # Generic roots such as pfx/AppData/Roaming are never useful backup
    # targets unless they contain save files directly.
    if _is_generic_container(normalized_path) and not has_saves and not is_steam_userdata_candidate:
        accepted = False

    if (
        accepted
        and state.installed_steam_games_dict
        and state.fuzz
        and state.THEFUZZ_AVAILABLE
        and not basename.isdigit()
        and not is_common_save_dir
        and getattr(config, 'LINUX_ENABLE_FUZZY_FILTER_OTHER_GAMES', True)
    ):
        cleaned_folder = clean_for_comparison(basename)
        for other_appid, other_info in state.installed_steam_games_dict.items():
            if str(other_appid) == str(state.current_steam_app_id):
                continue
            other_name = (other_info or {}).get('name', '')
            if not other_name:
                continue
            if (
                state.fuzz.token_set_ratio(
                    clean_for_comparison(other_name), cleaned_folder
                ) >= 95
                and not are_names_similar(
                    state.game_name_raw,
                    basename,
                    fuzz_engine=state.fuzz,
                    thefuzz_available=True,
                )
            ):
                accepted = False
                reason = f"Rejected: matches other game '{other_name}'"
                break

    state.checked_paths.add(canonical_key)
    if not accepted:
        return False

    state.guesses_data[normalized_path] = {
        'source': source_description,
        'sources': {source_description},
        'reason': reason,
        'has_saves_hint': has_saves,
        'has_saves_direct': has_saves,
        'has_save_structure': has_save_structure,
        'explicit_name_match': basename_matches_game,
        'steam_app_id': str(state.current_steam_app_id) if state.current_steam_app_id else None,
        'canonical_key': canonical_key,
    }
    state.candidate_paths_by_key[canonical_key] = normalized_path
    logging.info(
        f"Linux save candidate: '{normalized_path}' "
        f"(source={source_description}, reason={reason}, saves={has_saves})"
    )
    return True


# =============================================================================
# RECURSIVE SEARCH
# =============================================================================

def _search_recursive(start_dir: str, depth: int, state: LinuxSearchState,
                      cancellation_manager: cancellation_utils.CancellationManager = None) -> None:
    """Recursively search a bounded, relevance-prioritised directory tree."""
    if _is_cancelled(cancellation_manager):
        return

    if depth > state.max_search_depth_linux:
        return

    try:
        if not os.path.isdir(start_dir):
            return
    except OSError:
        return

    canonical_key = _path_key(start_dir)
    if canonical_key in state.explored_paths:
        return
    max_directories = getattr(config, 'LINUX_MAX_DIRECTORIES_TO_EXPLORE', 200)
    if state.directories_explored >= max_directories:
        logging.debug(f"Linux search root budget reached ({max_directories} directories)")
        return
    state.directories_explored += 1
    state.explored_paths.add(canonical_key)

    basename_current_path_raw = os.path.basename(os.path.normpath(start_dir))
    basename_current_path_lower = basename_current_path_raw.lower()
    is_potential_current, has_saves_hint_current = _is_potential_save_dir(start_dir, state)
    current_path_name_match_game = (
        _component_matches_game(basename_current_path_raw, state)
        or (
            _is_renpy_base(os.path.dirname(start_dir))
            and _renpy_directory_matches_game(
                basename_current_path_raw, state
            )
        )
    )
    current_path_name_match_company = _component_matches_company(
        basename_current_path_raw, state
    )
    current_path_is_common_save_dir = (
        basename_current_path_lower in state.linux_common_save_subdirs_lower
        or basename_current_path_lower in SPECIFIC_SAVE_FOLDERS
    )
    path_has_context = _path_has_game_context(start_dir, state)
    path_has_appid = _path_has_appid_context(start_dir, state)

    should_add_current_path = (
        current_path_name_match_game
        or (
            current_path_is_common_save_dir
            and (path_has_context or path_has_appid)
        )
        or (
            has_saves_hint_current
            and (path_has_context or path_has_appid or state.is_exploring_install_dir)
        )
    )
    if state.is_exploring_install_dir and not (
        current_path_is_common_save_dir or has_saves_hint_current
    ):
        should_add_current_path = False

    if should_add_current_path and is_potential_current:
        if state.is_exploring_install_dir:
            specific_source_desc = f"InstallDirWalk/{os.path.relpath(start_dir, state.install_dir_root) if state.install_dir_root else start_dir} (Depth={depth})"
        else:
            specific_source_desc = f"{start_dir} (Depth={depth})"

        if current_path_name_match_game:
            specific_source_desc += " (GameMatch)"
        elif current_path_name_match_company:
            specific_source_desc += " (CompanyMatch)"
        elif current_path_is_common_save_dir:
            specific_source_desc += " (CommonSaveDir)"
        elif has_saves_hint_current:
            specific_source_desc += " (PotentialDirEvidence)"

        _add_guess(state, start_dir, specific_source_desc, has_saves_hint_current)

    try:
        dir_contents = os.listdir(start_dir)
    except OSError:
        return

    linux_skip_directories = {
        name.lower() for name in getattr(config, 'LINUX_SKIP_DIRECTORIES', set())
    }
    filtered_dir_contents = [
        name for name in dir_contents
        if name.lower() not in linux_skip_directories
        and os.path.isdir(os.path.join(start_dir, name))
    ]
    current_is_engine_container = (
        basename_current_path_lower in ENGINE_CONTAINER_FOLDERS
    )
    engine_child_matches: Dict[str, bool] = {}
    # At the top of a known save root, peek one directory below otherwise
    # unknown publisher/container names.  This finds
    # XDG_ROOT/UnknownPublisher/Game without broadly crawling every subtree.
    if current_is_engine_container or depth < state.max_shallow_explore_depth_linux:
        for name in sorted(filtered_dir_contents, key=str.casefold)[:200]:
            engine_child_matches[name] = _contains_direct_game_child(
                os.path.join(start_dir, name),
                state,
            )

    def traversal_priority(name: str) -> Tuple[int, str]:
        lower = name.lower()
        if (
            _component_matches_game(name, state)
            or engine_child_matches.get(name, False)
            or (
                _is_renpy_base(start_dir)
                and _renpy_directory_matches_game(name, state)
            )
            or (
                _is_flatpak_app_base(start_dir)
                and _flatpak_package_matches_game(name, state)
            )
        ):
            priority = 0
        elif lower in state.linux_common_save_subdirs_lower or lower in SPECIFIC_SAVE_FOLDERS:
            priority = 1
        elif _component_matches_company(name, state):
            priority = 2
        elif lower in {'unity3d', 'unreal', 'unrealengine', 'godot', 'gamemaker'}:
            priority = 3
        else:
            priority = 4
        return priority, name.casefold()

    dir_contents_limited = sorted(
        filtered_dir_contents, key=traversal_priority
    )[:state.max_sub_items_to_scan_linux]

    for item_name in dir_contents_limited:
        if _is_cancelled(cancellation_manager):
            return

        item_path = os.path.join(start_dir, item_name)
        try:
            if not os.path.isdir(item_path):
                continue

            item_name_lower = item_name.lower()
            sub_is_potential, sub_has_saves = _is_potential_save_dir(item_path, state)
            item_is_game_match = (
                _component_matches_game(item_name, state)
                or (
                    _is_renpy_base(start_dir)
                    and _renpy_directory_matches_game(
                        item_name, state
                    )
                )
            )
            item_is_flatpak_package_match = (
                _is_flatpak_app_base(start_dir)
                and _flatpak_package_matches_game(item_name, state)
            )
            item_contains_direct_game_child = engine_child_matches.get(
                item_name, False
            )
            item_is_company_match = _component_matches_company(
                item_name, state
            )
            item_is_common_save_dir = (
                item_name_lower in state.linux_common_save_subdirs_lower
                or item_name_lower in SPECIFIC_SAVE_FOLDERS
            )
            item_is_container_dir = (
                item_name_lower in ENGINE_CONTAINER_FOLDERS
            )

            should_recurse = (
                depth < state.max_shallow_explore_depth_linux
                or item_is_game_match
                or item_is_flatpak_package_match
                or item_contains_direct_game_child
                or item_is_company_match
                or item_is_common_save_dir
                or item_is_container_dir
                or sub_has_saves
                or path_has_context
                or current_path_name_match_company
                or current_is_engine_container
            )
            if should_recurse and (
                sub_is_potential
                or depth < state.max_shallow_explore_depth_linux
                or item_is_flatpak_package_match
                or item_contains_direct_game_child
                or item_is_company_match
                or item_is_container_dir
                or path_has_context
                or current_path_name_match_company
                or current_is_engine_container
            ):
                _search_recursive(item_path, depth + 1, state, cancellation_manager)

        except OSError:
            pass


# =============================================================================
# PROTON SEARCH FUNCTIONS
# =============================================================================

def _search_proton_prefix_deep(
    compatdata_path: str,
    appid: str,
    state: LinuxSearchState,
    cancellation_manager=None,
    trusted_game_scope: bool = False,
) -> None:
    """Search only user save roots inside one AppID-owned Proton prefix."""
    try:
        source_scope = (
            "RelatedWinePrefix"
            if trusted_game_scope
            else f"Proton AppID {appid}"
        )
        users_root = os.path.join(compatdata_path, 'drive_c', 'users')
        user_dirs = []
        if os.path.isdir(users_root):
            user_dirs = [
                os.path.join(users_root, name)
                for name in sorted(os.listdir(users_root), key=str.casefold)
                if os.path.isdir(os.path.join(users_root, name))
                and name.lower() not in {'public', 'all users'}
            ]
        for user_dir in user_dirs:
            if _is_cancelled(cancellation_manager):
                return
            relative_roots = [
                os.path.join('AppData', 'Local'),
                os.path.join('AppData', 'LocalLow'),
                os.path.join('AppData', 'Roaming'),
                'Documents',
                'My Documents',
                'Saved Games',
                'My Games',
                os.path.join('Documents', 'My Games'),
                os.path.join('My Documents', 'My Games'),
            ]
            for relative_root in relative_roots:
                if _is_cancelled(cancellation_manager):
                    return
                save_root = os.path.join(user_dir, relative_root)
                if not os.path.isdir(save_root):
                    continue

                source_root = (
                    f"{source_scope}/"
                    f"{os.path.relpath(save_root, compatdata_path)}"
                )
                for alias in state.game_abbreviations:
                    direct_path = os.path.join(save_root, alias)
                    if os.path.isdir(direct_path):
                        _add_guess(
                            state,
                            direct_path,
                            f"{source_root}/Direct/{alias}",
                            False,
                        )
                        _search_recursive(
                            direct_path, 0, state, cancellation_manager
                        )

                state.directories_explored = 0
                _search_recursive(save_root, 0, state, cancellation_manager)
                if 'appdata' in relative_root.lower():
                    _search_appdata_deep(
                        save_root,
                        os.path.relpath(save_root, compatdata_path),
                        appid,
                        state,
                        cancellation_manager,
                        trusted_game_scope=trusted_game_scope,
                    )

        # Some Windows games use the machine-wide ProgramData tree rather than
        # a user profile. The AppID/related-prefix scope keeps this targeted.
        program_data_root = os.path.join(
            compatdata_path, 'drive_c', 'ProgramData'
        )
        if os.path.isdir(program_data_root):
            source_root = f"{source_scope}/ProgramData"
            for alias in state.game_abbreviations:
                direct_path = os.path.join(program_data_root, alias)
                if os.path.isdir(direct_path):
                    _add_guess(
                        state,
                        direct_path,
                        f"{source_root}/Direct/{alias}",
                        False,
                    )
            state.directories_explored = 0
            _search_recursive(
                program_data_root, 0, state, cancellation_manager
            )
    except Exception as e:
        logging.error(f"Error in _search_proton_prefix_deep: {e}")


def _search_appdata_deep(appdata_path: str, path_variant: str, appid: str,
                         state: LinuxSearchState, cancellation_manager=None,
                         trusted_game_scope: bool = False) -> None:
    """
    Deep search inside AppData directories for game saves.
    Handles cases where saves are in Publisher/GameName structure (e.g., HelloGames/NMS).
    Also handles Unreal Engine games that use internal project names (e.g., FSD for Deep Rock Galactic).
    Uses the known publishers list from config for targeted search.
    """
    source_scope = (
        "RelatedWinePrefix AppData"
        if trusted_game_scope
        else "Proton AppData"
    )
    try:
        # List all first-level folders in AppData. The prefix is already tied to
        # this AppID, but a folder still needs title/structure/file evidence.
        for folder_name in sorted(os.listdir(appdata_path), key=str.casefold)[:250]:
            if _is_cancelled(cancellation_manager):
                return
                
            folder_path = os.path.join(appdata_path, folder_name)
            if not os.path.isdir(folder_path):
                continue
            
            folder_lower = folder_name.lower()
            is_known_publisher = folder_lower in state.known_companies_lower
            
            matches_game = _component_matches_game(folder_name, state)
            if matches_game:
                _add_guess(
                    state,
                    folder_path,
                    f"{source_scope}/{path_variant}/{folder_name} ({appid})",
                    False,
                )
                _search_recursive(folder_path, 0, state, cancellation_manager)
            
            # UNREAL ENGINE PATTERN: Check for Saved/SaveGames structure
            # Many Unreal games use internal project names (e.g., FSD for Deep Rock Galactic)
            # Pattern: AppData/Local/[ProjectName]/Saved/SaveGames
            saved_path = os.path.join(folder_path, 'Saved')
            if os.path.isdir(saved_path):
                savegames_path = os.path.join(saved_path, 'SaveGames')
                if os.path.isdir(savegames_path):
                    savegames_has_saves, _ = _scan_dir_for_save_evidence(
                        savegames_path, state
                    )
                    _add_guess(state, savegames_path,
                              f"{source_scope}/{path_variant}/{folder_name}/Saved/SaveGames (Unreal) ({appid})",
                              savegames_has_saves)
                    _search_recursive(savegames_path, 0, state, cancellation_manager)
                    _add_guess(state, saved_path,
                              f"{source_scope}/{path_variant}/{folder_name}/Saved (Unreal) ({appid})", False)
            
            # If it's a known publisher OR we haven't found a direct match yet,
            # search inside for game-named subfolders
            if is_known_publisher or not matches_game:
                try:
                    for subfolder in sorted(os.listdir(folder_path), key=str.casefold)[:100]:
                        if _is_cancelled(cancellation_manager):
                            return
                        subfolder_path = os.path.join(folder_path, subfolder)
                        if not os.path.isdir(subfolder_path):
                            continue
                        if _component_matches_game(subfolder, state):
                            _add_guess(
                                state,
                                subfolder_path,
                                f"{source_scope}/{path_variant}/{folder_name}/{subfolder} ({appid})",
                                False,
                            )
                            _search_recursive(
                                subfolder_path, 0, state, cancellation_manager
                            )
                                
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

        try:
            snap_dirs = [
                directory
                for directory in sorted(os.listdir(snap_base), key=str.casefold)
                if os.path.isdir(os.path.join(snap_base, directory))
            ]
            for snap_dir in snap_dirs:
                if _is_cancelled(cancellation_manager):
                    return

                if not _component_matches_game(snap_dir, state):
                    continue

                snap_game_path = os.path.join(snap_base, snap_dir)
                for scope_name in ('common', 'current'):
                    scope_path = os.path.join(snap_game_path, scope_name)
                    if not os.path.isdir(scope_path):
                        continue
                    search_roots = [
                        scope_path,
                        os.path.join(scope_path, '.local', 'share'),
                        os.path.join(scope_path, '.config'),
                        os.path.join(scope_path, 'data'),
                    ]
                    for search_root in search_roots:
                        if not os.path.isdir(search_root):
                            continue
                        state.directories_explored = 0
                        _search_recursive(
                            search_root, 0, state, cancellation_manager
                        )
        except OSError:
            pass

    except Exception as e:
        logging.error(f"Error in _search_snap_games: {e}")


def _discover_related_heroic_prefixes(
    state: LinuxSearchState,
) -> List[str]:
    """Find title-matching Heroic prefixes beside a Heroic install."""
    install_dir = state.game_install_dir
    if not install_dir or not os.path.isdir(install_dir):
        return []

    heroic_root = None
    current = os.path.abspath(install_dir)
    for _ in range(8):
        if os.path.basename(current).casefold() == 'heroic':
            heroic_root = current
            break
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    if not heroic_root:
        return []

    try:
        prefixes_name = next(
            (
                name for name in os.listdir(heroic_root)
                if name.casefold() == 'prefixes'
                and os.path.isdir(os.path.join(heroic_root, name))
            ),
            None,
        )
    except OSError:
        return []
    if not prefixes_name:
        return []

    prefixes_root = os.path.join(heroic_root, prefixes_name)
    discovered: Dict[str, str] = {}
    base_depth = os.path.normpath(prefixes_root).count(os.sep)
    visited = 0
    try:
        for root, dirs, _ in os.walk(prefixes_root, topdown=True):
            relative_depth = os.path.normpath(root).count(os.sep) - base_depth
            if relative_depth > 3 or visited >= 250:
                dirs[:] = []
                continue
            visited += 1

            dirs[:] = sorted(
                dirs,
                key=lambda name: (
                    0 if _component_matches_game(name, state) else 1,
                    name.casefold(),
                ),
            )[:100]

            if (
                root != prefixes_root
                and _component_matches_game(
                    os.path.basename(os.path.normpath(root)),
                    state,
                )
            ):
                prefix = None
                if os.path.isdir(os.path.join(root, 'drive_c')):
                    prefix = root
                elif os.path.isdir(os.path.join(root, 'pfx', 'drive_c')):
                    prefix = os.path.join(root, 'pfx')
                if prefix:
                    discovered[_path_key(prefix)] = prefix
                    dirs[:] = []
    except OSError:
        return list(discovered.values())
    return list(discovered.values())


def _discover_unowned_compatdata_prefixes(
    state: LinuxSearchState,
) -> List[Tuple[str, str]]:
    """Find Proton prefixes when a shortcut does not provide an AppID.

    The returned prefixes are not trusted game scopes. Candidates found inside
    them still need an explicit title/alias component in their path, preventing
    an unrelated compatdata prefix from being attributed to the current game.
    """
    home_dir = os.path.expanduser('~')
    xdg_data_home = (
        os.getenv('XDG_DATA_HOME')
        or os.path.join(home_dir, '.local', 'share')
    )
    compatdata_roots = [
        os.path.join(
            home_dir, '.steam', 'steam', 'steamapps', 'compatdata'
        ),
        os.path.join(
            home_dir, '.steam', 'root', 'steamapps', 'compatdata'
        ),
        os.path.join(
            home_dir, '.steam', 'debian-installation',
            'steamapps', 'compatdata',
        ),
        os.path.join(
            home_dir, '.local', 'share', 'Steam',
            'steamapps', 'compatdata',
        ),
        os.path.join(
            xdg_data_home, 'Steam', 'steamapps', 'compatdata'
        ),
        os.path.join(
            home_dir, '.var', 'app', 'com.valvesoftware.Steam',
            '.local', 'share', 'Steam', 'steamapps', 'compatdata',
        ),
        os.path.join(
            home_dir, '.var', 'app', 'com.valvesoftware.Steam',
            'data', 'Steam', 'steamapps', 'compatdata',
        ),
        os.path.join(
            home_dir, 'snap', 'steam', 'common', '.local', 'share',
            'Steam', 'steamapps', 'compatdata',
        ),
    ]
    for known_location in state.linux_known_save_locations.values():
        if (
            known_location
            and os.path.basename(
                os.path.normpath(known_location)
            ).casefold() == 'compatdata'
        ):
            compatdata_roots.append(known_location)

    roots_by_key: Dict[str, str] = {}
    for root in compatdata_roots:
        if os.path.isdir(root):
            roots_by_key[_path_key(root)] = root

    prefixes_by_key: Dict[str, Tuple[str, str]] = {}
    for root in roots_by_key.values():
        try:
            appid_names = sorted(os.listdir(root), key=str.casefold)
        except OSError:
            continue
        for appid_name in appid_names:
            if not appid_name.isdigit():
                continue
            prefix = os.path.join(root, appid_name, 'pfx')
            if not os.path.isdir(os.path.join(prefix, 'drive_c')):
                continue
            prefixes_by_key[_path_key(prefix)] = (prefix, appid_name)

    def has_title_signal(prefix: str) -> bool:
        """Prioritise prefixes with a title-shaped AppData/Documents path."""
        users_root = os.path.join(prefix, 'drive_c', 'users')
        try:
            user_names = sorted(os.listdir(users_root), key=str.casefold)
        except OSError:
            return False

        relative_roots = [
            os.path.join('AppData', 'Local'),
            os.path.join('AppData', 'LocalLow'),
            os.path.join('AppData', 'Roaming'),
            'Documents',
            'Saved Games',
            os.path.join('Documents', 'My Games'),
        ]
        for user_name in user_names[:20]:
            user_dir = os.path.join(users_root, user_name)
            if (
                not os.path.isdir(user_dir)
                or user_name.casefold() in {'public', 'all users'}
            ):
                continue
            for relative_root in relative_roots:
                search_root = os.path.join(user_dir, relative_root)
                try:
                    first_level = sorted(
                        os.listdir(search_root), key=str.casefold
                    )[:250]
                except OSError:
                    continue
                for name in first_level:
                    path = os.path.join(search_root, name)
                    if not os.path.isdir(path):
                        continue
                    if (
                        _component_matches_game(name, state)
                        or _contains_direct_game_child(path, state)
                    ):
                        return True
        return False

    prefixes = list(prefixes_by_key.values())
    relevance = {
        _path_key(prefix): has_title_signal(prefix)
        for prefix, _ in prefixes
    }
    prefixes.sort(
        key=lambda item: (
            0 if relevance.get(_path_key(item[0]), False) else 1,
            int(item[1]),
            item[0].casefold(),
        )
    )

    max_prefixes = max(
        0,
        int(
            getattr(
                config, 'LINUX_MAX_COMPATDATA_APPIDS_NONSTEAM', 100
            )
        ),
    )
    selected = prefixes[:max_prefixes]
    logging.info(
        "Discovered %d Proton compatdata prefixes without an AppID; "
        "scanning %d (%d contain a title-shaped path)",
        len(prefixes),
        len(selected),
        sum(
            1
            for prefix, _ in selected
            if relevance.get(_path_key(prefix), False)
        ),
    )
    return selected


def _search_proton_for_non_steam_games(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search related Wine prefixes and strictly filtered Proton compatdata.

    Compatdata discovered without an AppID is always untrusted: a result must
    still contain the requested title/alias. This supports .desktop launchers
    that expose only a generic command while avoiding cross-game candidates.
    """
    logging.info(
        f"Searching related Wine prefixes for non-Steam game "
        f"'{state.game_name_cleaned}'"
    )
    try:
        prefixes: Dict[str, Tuple[str, bool]] = {}

        def remember_prefix(path: str, trusted: bool) -> None:
            key = _path_key(path)
            existing = prefixes.get(key)
            prefixes[key] = (
                path,
                trusted or bool(existing and existing[1]),
            )

        def is_dedicated_prefix(path: str) -> bool:
            normalized = os.path.normpath(path)
            return any(
                _component_matches_game(component, state)
                for component in (
                    os.path.basename(normalized),
                    os.path.basename(os.path.dirname(normalized)),
                )
            )

        install_dir = state.game_install_dir
        if install_dir and os.path.isdir(install_dir):
            current = os.path.abspath(install_dir)
            for _ in range(8):
                if os.path.isdir(os.path.join(current, 'drive_c')):
                    remember_prefix(
                        current, is_dedicated_prefix(current)
                    )
                if os.path.basename(current).lower() == 'drive_c':
                    parent = os.path.dirname(current)
                    remember_prefix(
                        parent, is_dedicated_prefix(parent)
                    )
                parent = os.path.dirname(current)
                if not parent or parent == current:
                    break
                current = parent

        for heroic_prefix in _discover_related_heroic_prefixes(state):
            remember_prefix(heroic_prefix, True)

        default_wine = os.path.join(os.path.expanduser('~'), '.wine')
        if os.path.isdir(default_wine):
            remember_prefix(default_wine, False)

        discovered_compatdata = _discover_unowned_compatdata_prefixes(state)
        compatdata_appids = {
            _path_key(compat_prefix): compat_appid
            for compat_prefix, compat_appid in discovered_compatdata
        }
        for compat_prefix, _ in discovered_compatdata:
            remember_prefix(compat_prefix, False)

        for prefix, trusted_game_scope in prefixes.values():
            if _is_cancelled(cancellation_manager):
                return
            prefix_appid = compatdata_appids.get(
                _path_key(prefix), 'nonsteam'
            )
            state.directories_explored = 0
            _search_proton_prefix_deep(
                prefix,
                prefix_appid,
                state,
                cancellation_manager,
                trusted_game_scope=trusted_game_scope,
            )
    except Exception as e:
        logging.error(f"Error in _search_proton_for_non_steam_games: {e}")


# =============================================================================
# SCORING AND SORTING
# =============================================================================

def _score_location_bonus(path_lower: str, source_description: str) -> int:
    """Calculate score bonus based on path location."""
    home_dir = os.path.expanduser("~")
    xdg_config_home = os.getenv('XDG_CONFIG_HOME') or os.path.join(home_dir, ".config")
    xdg_data_home = os.getenv('XDG_DATA_HOME') or os.path.join(home_dir, ".local", "share")
    path_text = _normalise_path_text(path_lower).lower()

    if _is_path_within(path_lower, xdg_config_home):
        return SCORE_XDG_CONFIG_HOME_BONUS
    elif _is_path_within(path_lower, xdg_data_home):
        return SCORE_XDG_DATA_HOME_BONUS
    elif "steamapps/compatdata" in path_text and "/pfx/" in path_text + '/':
        return 600
    elif "/userdata/" in path_text + '/':
        return 500
    elif "/documents/" in path_text + '/':
        return 200
    elif "installdirwalk" in source_description.lower():
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
        if basename_lower in SPECIFIC_SAVE_FOLDERS:
            score += SCORE_SPECIFIC_SAVE_DIR_BONUS
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

    if _component_matches_game(basename, state):
        return 400

    if (
        state.THEFUZZ_AVAILABLE
        and state.fuzz
        and not (
            _version_tokens(state.game_name_raw)
            != _version_tokens(basename)
            and (_version_tokens(state.game_name_raw) or _version_tokens(basename))
        )
    ):
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
    path_text = _normalise_path_text(path_lower).lower()

    if "proton" in source_lower or "/pfx/" in path_text + '/':
        score += 200
        windows_paths = ['appdata/local', 'appdata/roaming', 'appdata/locallow',
                        'documents', 'saved games', 'my games', 'my documents']
        if any(wp in path_text for wp in windows_paths):
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
    
    # High-confidence irrelevant trees. The legacy config list also contains
    # valid Wine/XDG locations, so it cannot safely be applied wholesale.
    irrelevant_fragments = {
        'steamapps/shadercache', 'steamapps/temp', 'steamapps/downloading',
        '/.cache/', '/logs/', '/gpucache/', '/code cache/',
    }
    path_text = '/' + _normalise_path_text(path).lower().strip('/') + '/'
    if not has_saves:
        for banned in irrelevant_fragments:
            if banned in path_text:
                penalty -= 1000
                break

    if _is_generic_container(path) and not has_saves:
        penalty -= 1000
    
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
    sources = data.get('sources', set())
    source = data.get('source') or (
        sorted(sources, key=str.casefold)[0] if sources else "UnknownSource"
    )
    has_saves = data.get('has_saves_hint', False)
    path_lower = path.lower()

    try:
        basename = os.path.basename(path)
        basename_lower = basename.lower()
        parent_basename_lower = os.path.basename(os.path.dirname(path).lower())
    except Exception:
        return (0, path_lower, path)

    # Calculate score components
    score = _score_location_bonus(path, source)
    
    if has_saves:
        score += SCORE_HAS_SAVE_FILES
    
    name_bonus, _ = _score_name_match_bonus(basename_lower, parent_basename_lower, state)
    score += name_bonus
    
    score += _score_fuzzy_similarity(basename, state)
    
    # Path contains game name bonus
    if data.get('explicit_name_match') or _path_has_game_context(path, state):
        score += 250
    
    # Steam AppID bonus
    steam_app_id = data.get('steam_app_id')
    if steam_app_id and steam_app_id in _path_parts(path):
        score += 300
    
    # Path type penalties
    userdata_roots = set(state.steam_userdata_roots)
    if state.steam_userdata_path:
        userdata_roots.add(state.steam_userdata_path)
    matched_userdata_root = next(
        (
            root for root in userdata_roots
            if _is_path_within(path, root)
        ),
        None,
    )
    path_type = _identify_path_type(
        path,
        source.lower(),
        matched_userdata_root,
    )
    score += _get_penalties(basename_lower, has_saves, path_type['is_prime_location'],
                           path_type['is_steam_remote'], path_type['is_install_dir_walk'], path_lower)
    
    # Additional penalties
    score += _calculate_penalties(path, path_lower, source, has_saves, state)
    
    # Proton bonus
    score += _score_proton_bonus(path_lower, source)
    
    # Steam userdata cap
    if (
        path_type['is_steam_remote']
        or path_type['is_steam_base']
        or matched_userdata_root is not None
    ):
        score = min(score, state.MAX_USERDATA_SCORE)

    return (-score, path_lower, path)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def _search_steam_userdata(state: LinuxSearchState, appid: str, steam_userdata_path: str,
                           steam_id3_to_use: str, cancellation_manager=None) -> None:
    """Search Steam userdata for save paths."""
    try:
        normalized_userdata = os.path.normpath(
            os.path.abspath(steam_userdata_path)
        )
        state.steam_userdata_roots.add(normalized_userdata)
        user_data_for_id = os.path.join(steam_userdata_path, steam_id3_to_use)
        if not os.path.isdir(user_data_for_id):
            return
            
        app_specific_userdata = os.path.join(user_data_for_id, appid)
        if not os.path.isdir(app_specific_userdata):
            return

        remote_path = os.path.join(app_specific_userdata, 'remote')
        if os.path.isdir(remote_path) and getattr(config, 'LINUX_ENABLE_STEAM_USERDATA_REMOTE_SCAN', True):
            try:
                remote_has_content = any(
                    name.lower() != 'remotecache.vdf'
                    for name in os.listdir(remote_path)
                )
            except OSError:
                remote_has_content = False
            remote_has_saves, _ = _scan_dir_for_save_evidence(
                remote_path, state
            )
            if remote_has_content:
                _add_guess(
                    state,
                    remote_path,
                    "Steam Userdata/AppID_Base/remote",
                    remote_has_saves,
                )
            if not _is_cancelled(cancellation_manager):
                state.directories_explored = 0
                _search_recursive(remote_path, 0, state, cancellation_manager)

        # Some titles place files directly in <userid>/<appid>. Do not surface
        # that base when it only wraps remote/remotecache.vdf.
        try:
            base_entries = [
                name for name in os.listdir(app_specific_userdata)
                if name.lower() not in {'remote', 'remotecache.vdf'}
            ]
        except OSError:
            base_entries = []
        base_has_saves, _ = _scan_dir_for_save_evidence(
            app_specific_userdata, state
        )
        if base_entries or base_has_saves:
            _add_guess(
                state,
                app_specific_userdata,
                "Steam Userdata/AppID_Base",
                base_has_saves,
            )
    except Exception as e:
        logging.error(f"Error processing Steam Userdata: {e}")


def _search_proton_steam(state: LinuxSearchState, appid: str, cancellation_manager=None) -> None:
    """Search Proton compatdata for Steam games."""
    home_dir = os.path.expanduser('~')
    xdg_data_home = (
        os.getenv('XDG_DATA_HOME')
        or os.path.join(home_dir, '.local', 'share')
    )
    steam_base_candidates = [
        os.path.join(home_dir, '.steam', 'steam'),
        os.path.join(home_dir, '.local', 'share', 'Steam'),
        os.path.join(xdg_data_home, 'Steam'),
        os.path.join(home_dir, '.steam', 'root'),
        os.path.join(home_dir, '.steam', 'debian-installation'),
        os.path.join(
            home_dir, '.var', 'app', 'com.valvesoftware.Steam',
            '.local', 'share', 'Steam',
        ),
        os.path.join(
            home_dir, '.var', 'app', 'com.valvesoftware.Steam',
            'data', 'Steam',
        ),
        os.path.join(
            home_dir, 'snap', 'steam', 'common', '.local', 'share', 'Steam',
        ),
    ]

    if state.steam_userdata_path:
        userdata_parent = os.path.dirname(
            os.path.normpath(state.steam_userdata_path)
        )
        if os.path.basename(os.path.normpath(state.steam_userdata_path)).lower() == 'userdata':
            steam_base_candidates.append(userdata_parent)

    install_dir = state.game_install_dir
    if install_dir:
        current = os.path.abspath(install_dir)
        for _ in range(8):
            if os.path.basename(current).lower() == 'steamapps':
                steam_base_candidates.append(os.path.dirname(current))
                break
            parent = os.path.dirname(current)
            if not parent or parent == current:
                break
            current = parent

    steam_bases: Dict[str, str] = {}
    for candidate in steam_base_candidates:
        if os.path.isdir(candidate):
            steam_bases[_path_key(candidate)] = candidate

    for steam_base in steam_bases.values():
        if _is_cancelled(cancellation_manager):
            return

        discovered_userdata = os.path.join(steam_base, 'userdata')
        if os.path.isdir(discovered_userdata):
            try:
                if state.steam_id3_to_use:
                    candidate_user_ids = [state.steam_id3_to_use]
                else:
                    candidate_user_ids = sorted(
                        os.listdir(discovered_userdata)
                    )
                user_ids = [
                    str(name)
                    for name in candidate_user_ids
                    if str(name).isdigit()
                    and os.path.isdir(
                        os.path.join(
                            discovered_userdata, str(name), appid
                        )
                    )
                ]
            except OSError:
                user_ids = []
            for user_id in user_ids:
                if _is_cancelled(cancellation_manager):
                    return
                _search_steam_userdata(
                    state,
                    appid,
                    discovered_userdata,
                    user_id,
                    cancellation_manager,
                )

        compatdata_path = os.path.join(steam_base, 'steamapps', 'compatdata', appid, 'pfx')
        if not os.path.isdir(compatdata_path):
            continue

        if not getattr(config, 'LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM', True):
            continue
        state.directories_explored = 0
        _search_proton_prefix_deep(
            compatdata_path, appid, state, cancellation_manager
        )


def _search_install_directory(state: LinuxSearchState, game_install_dir: str, cancellation_manager=None) -> None:
    """Search game installation directory for save paths."""
    if not game_install_dir or not os.path.isdir(game_install_dir):
        return
    if _is_unsafe_install_root(game_install_dir):
        logging.info(
            "Skipping unsafe Linux install directory for save discovery: %s",
            game_install_dir,
        )
        return

    state.is_exploring_install_dir = True
    state.install_dir_root = os.path.normpath(game_install_dir)
    state.directories_explored = 0
    try:
        _search_recursive(game_install_dir, 0, state, cancellation_manager)
    finally:
        state.is_exploring_install_dir = False
        state.install_dir_root = None


def _search_xdg_locations(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Search XDG and common Linux paths for save paths."""
    expanded_home = os.path.expanduser('~')
    home_dir = _path_key(expanded_home)
    install_container_roots = {
        _path_key(os.path.join(expanded_home, 'Games')),
        _path_key(os.path.join(expanded_home, 'snap')),
    }
    searched_roots: Set[str] = set()
    for loc_desc, base_path in state.linux_known_save_locations.items():
        if _is_cancelled(cancellation_manager):
            break
        if not os.path.isdir(base_path):
            continue

        root_key = _path_key(base_path)
        root_text = _normalise_path_text(base_path).lower()
        if (
            root_key == home_dir
            or root_key in install_container_roots
            or '/steamapps/compatdata' in root_text
            or '/.wine/' in root_text + '/'
        ):
            continue
        if root_key in searched_roots:
            continue
        searched_roots.add(root_key)

        # Search for direct game name subdirectories
        direct_names: Set[str] = set(state.game_abbreviations)
        for abbreviation in state.game_abbreviations:
            compact = ''.join(character for character in abbreviation if character.isalnum())
            if compact:
                direct_names.add('.' + compact.casefold())
        for direct_name in sorted(direct_names, key=lambda value: (-len(value), value.casefold())):
            direct_game_path = os.path.join(base_path, direct_name)
            if os.path.isdir(direct_game_path):
                _add_guess(
                    state,
                    direct_game_path,
                    f"{loc_desc}/DirectGameName/{direct_name}",
                    False,
                )

        state.directories_explored = 0
        _search_recursive(base_path, 0, state, cancellation_manager)


def _search_home_fallback(state: LinuxSearchState, cancellation_manager=None) -> None:
    """Check title/publisher-shaped home folders without crawling the home."""
    if getattr(config, 'LINUX_SKIP_HOME_FALLBACK', False):
        return

    user_home = os.path.expanduser('~')
    try:
        entries = sorted(os.listdir(user_home), key=str.casefold)
    except OSError:
        return

    for entry in entries:
        if _is_cancelled(cancellation_manager):
            return
        path = os.path.join(user_home, entry)
        if not os.path.isdir(path):
            continue
        matches_game = _component_matches_game(entry, state)
        matches_company = _component_matches_company(entry, state)
        if not matches_game and not matches_company:
            continue
        if matches_game:
            _add_guess(state, path, f"Home/ExactGameName/{entry}", False)
        state.directories_explored = 0
        _search_recursive(path, 0, state, cancellation_manager)


def _rank_and_sort_results(
    state: LinuxSearchState, game_name: str, cancellation_manager=None
) -> List[Tuple]:
    """Rank and sort the found paths, return final results."""
    if not state.guesses_data:
        logging.warning(f"LINUX_GUESS_SAVE_PATH: No potential save paths found for '{game_name}'.")
        return []

    valid_items: List[Tuple[str, Dict]] = []
    seen_keys: Set[str] = set()
    for path, data in state.guesses_data.items():
        if _is_cancelled(cancellation_manager):
            return []
        if not os.path.isdir(path):
            continue
        canonical_key = _path_key(path)
        if canonical_key in seen_keys:
            continue
        seen_keys.add(canonical_key)

        if not data.get('has_saves_direct'):
            found_deep, count = _deep_scan_save_evidence(
                path, state, cancellation_manager=cancellation_manager
            )
            if found_deep:
                data['has_saves_hint'] = True
                data['has_saves_deep'] = True
                data['deep_save_count'] = count
        valid_items.append((path, data))

    scored_items: List[Tuple[str, Dict, int]] = []
    for path, data in valid_items:
        score = int(-_final_sort_key_linux((path, data), state)[0])
        if score > 0:
            scored_items.append((path, data, score))

    # Collapse overlapping candidates. A sole confirmed leaf is the precise
    # target; multiple independent leaves are better represented by their
    # common game parent so one profile covers all of them.
    dominated_paths: Set[str] = set()
    for ancestor_path, ancestor_data, _ in scored_items:
        confirmed_descendants = [
            descendant_path
            for descendant_path, descendant_data, _ in scored_items
            if descendant_path != ancestor_path
            and descendant_data.get('has_saves_direct')
            and _is_path_within(descendant_path, ancestor_path)
        ]
        if not confirmed_descendants:
            continue
        if (
            len(confirmed_descendants) == 1
            and not ancestor_data.get('has_saves_direct')
        ):
            dominated_paths.add(ancestor_path)
        else:
            dominated_paths.update(confirmed_descendants)

    scored_items = [
        item for item in scored_items if item[0] not in dominated_paths
    ]
    scored_items.sort(key=lambda item: (-item[2], item[0].casefold()))

    max_results = max(1, int(getattr(config, 'LINUX_MAX_RESULTS', 20)))
    scored_items = scored_items[:max_results]

    logging.info(
        f"LINUX_GUESS_SAVE_PATH: Returning {len(scored_items)} validated paths "
        f"for '{game_name}'. Top 5:"
    )
    for index, (path, data, score) in enumerate(scored_items[:5]):
        sources = data.get('sources', set())
        source = data.get('source') or (
            sorted(sources, key=str.casefold)[0] if sources else 'UnknownSource'
        )
        logging.info(
            f"  {index + 1}. {path} "
            f"(Source: {source}, HasSaves: {data.get('has_saves_hint', False)}, "
            f"Score: {score})"
        )

    return [
        (path, score, bool(data.get('has_saves_hint', False)))
        for path, data, score in scored_items
    ]


def final_sort_key(guess_tuple: Tuple, outer_scope_data: Dict) -> Tuple:
    """Compatibility wrapper matching the cross-platform finder API."""
    path = guess_tuple[0]
    source = (
        guess_tuple[1]
        if len(guess_tuple) > 1 and isinstance(guess_tuple[1], str)
        else 'Compatibility'
    )
    has_saves = bool(guess_tuple[2]) if len(guess_tuple) > 2 else False
    state = _build_search_state(
        game_name_raw=outer_scope_data.get('game_name', ''),
        game_install_dir_raw=outer_scope_data.get('game_install_dir'),
        installed_steam_games_dict=outer_scope_data.get(
            'installed_steam_games_dict'
        ),
        steam_app_id_raw=outer_scope_data.get('appid'),
        steam_userdata_path=outer_scope_data.get('steam_userdata_path'),
        steam_id3_to_use=outer_scope_data.get('steam_id3_to_use'),
        is_steam_game=outer_scope_data.get('is_steam_game', True),
    )
    data = {
        'source': source,
        'sources': {source},
        'has_saves_hint': has_saves,
        'has_saves_direct': has_saves,
        'explicit_name_match': _component_matches_game(
            os.path.basename(os.path.normpath(path)), state
        ),
        'steam_app_id': (
            str(state.current_steam_app_id)
            if state.current_steam_app_id is not None
            else None
        ),
    }
    sort_key = _final_sort_key_linux((path, data), state)
    return sort_key[:2]


def guess_save_path(game_name: str, game_install_dir: str = None, appid: str = None,
                    steam_userdata_path: str = None, steam_id3_to_use: str = None,
                    is_steam_game: bool = True, installed_steam_games_dict: Dict = None,
                    cancellation_manager: cancellation_utils.CancellationManager = None) -> List[Tuple]:
    """
    Main entry point for finding save paths on Linux.
    Returns a list of (path, score, has_saves_hint) tuples sorted by score.
    """
    logging.info(f"LINUX_GUESS_SAVE_PATH: Starting search for '{game_name}' (AppID: {appid})")
    if not isinstance(game_name, str) or not game_name.strip():
        return []
    if _is_cancelled(cancellation_manager):
        return []

    appid = str(appid) if appid is not None else None
    steam_id3_to_use = (
        str(steam_id3_to_use) if steam_id3_to_use is not None else None
    )

    # Build state - single source of truth
    state = _build_search_state(
        game_name_raw=game_name,
        game_install_dir_raw=game_install_dir,
        installed_steam_games_dict=installed_steam_games_dict,
        steam_app_id_raw=appid,
        steam_userdata_path=steam_userdata_path,
        steam_id3_to_use=steam_id3_to_use,
        is_steam_game=is_steam_game,
    )

    # 1. Steam Userdata (High Priority)
    if is_steam_game and appid and steam_userdata_path and steam_id3_to_use:
        _search_steam_userdata(state, appid, steam_userdata_path, steam_id3_to_use, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 2. Proton Compatdata (for Steam games)
    if is_steam_game and appid:
        _search_proton_steam(state, appid, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 3. Proton for non-Steam games
    if (not is_steam_game or not appid) and getattr(config, 'LINUX_ENABLE_PROTON_SCAN_NONSTEAM', True):
        _search_proton_for_non_steam_games(state, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 4. Snap games search
    if getattr(config, 'LINUX_ENABLE_SNAP_SEARCH', True):
        if not _is_cancelled(cancellation_manager):
            _search_snap_games(state, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 5. Game Install Directory
    _search_install_directory(state, game_install_dir, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 6. XDG and Common Linux Paths
    _search_xdg_locations(state, cancellation_manager)
    if _is_cancelled(cancellation_manager):
        return []

    # 7. User's Home Directory (fallback)
    _search_home_fallback(state, cancellation_manager)

    # Rank and return results
    return _rank_and_sort_results(state, game_name, cancellation_manager)
