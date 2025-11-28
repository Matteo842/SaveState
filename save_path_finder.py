"""
save_path_finder_improved.py
Versione migliorata del modulo per la ricerca dei percorsi di salvataggio dei giochi.
"""

import platform
import os
import re
import logging
import glob
from typing import List, Dict, Set, Tuple, Optional, Union, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import config
import cancellation_utils

# Importa thefuzz se disponibile
try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
    logging.info("Library 'thefuzz' found and loaded.")
except ImportError:
    THEFUZZ_AVAILABLE = False
    logging.warning("Library 'thefuzz' not found. Fuzzy matching will be disabled.")
    logging.warning("Install it with: pip install thefuzz[speedup]")


class ScoreWeight(Enum):
    """Pesi per il calcolo del punteggio dei percorsi."""
    STEAM_REMOTE = 1500
    STEAM_BASE_NO_SAVES = 150
    STEAM_BASE_WITH_SAVES = 650
    PRIME_USER_LOCATION = 1000
    DOCUMENTS_GENERIC = 300
    INSTALL_DIR_WALK = -500
    DEFAULT_LOCATION = 100
    CONTAINS_SAVES = 600
    COMMON_SAVE_SUBDIR = 400  # Aumentato da 350 a 500 per dare più priorità alle cartelle save/saves
    DIRECT_MATCH = 100
    PARENT_MATCH = 100
    EXACT_NAME_MATCH = 400
    DATA_FOLDER_PENALTY = -500
    GENERIC_FOLDER_PENALTY = -150
    SHORT_NAME_PENALTY = -30
    INSTALL_DIR_NO_SAVES_PENALTY = -300
    

class PathScore:
    """Gestisce il calcolo del punteggio per un percorso."""
    MAX_USERDATA_SCORE = 1100
    MIN_PREFIX_LENGTH = 3
    MIN_FUZZY_RATIO = 85
    HIGH_FUZZY_RATIO = 95
    
    def __init__(self, game_context: 'GameContext'):
        self.game_context = game_context
        
    def calculate(self, path: str, source: str, contains_saves: bool) -> int:
        """Calcola il punteggio per un dato percorso."""
        score = 0
        path_lower = path.lower()
        basename = os.path.basename(path)
        basename_lower = basename.lower()
        source_lower = source.lower()
        
        # Identifica tipi di percorso
        path_type = self._identify_path_type(path_lower, source_lower)
        
        # Punteggio base per locazione
        score += self._get_location_score(path_type, contains_saves)
        
        # Bonus indicatori positivi
        score += self._get_positive_indicators_score(
            basename, basename_lower, source_lower, contains_saves
        )
        
        # Bonus similarità nome
        score += self._get_name_similarity_score(basename_lower)
        
        # Malus specifici
        score += self._get_penalties(
            basename_lower, contains_saves, path_type['is_in_prime_location'],
            path_type['is_steam_remote'], path_type['is_install_dir_walk']
        )
        
        # Applica cap per userdata (ma non per Steam remote che ha priorità speciale)
        if self._is_in_userdata(path_lower) and not path_type['is_steam_remote']:
            score = min(score, self.MAX_USERDATA_SCORE)
            
        # NUOVO: Applica cap anche alla cartella remote per "ucciderla" come nel vecchio codice
        if path_type['is_steam_remote']:
            # La cartella remote riceve 1500 punti ma viene limitata dal cap
            # Questo la "uccide" e la fa scendere sotto i percorsi corretti
            score = min(score, self.MAX_USERDATA_SCORE)
            
        return score
    
    def _identify_path_type(self, path_lower: str, source_lower: str) -> Dict[str, bool]:
        """Identifica il tipo di percorso."""
        # Controlla se è un percorso Steam remote
        is_steam_remote = False
        if self.game_context.steam_userdata_path:
            # Normalizza source_lower e path per confronto cross-platform
            source_check = source_lower.replace('\\', '/').lower()
            path_check = path_lower.replace('\\', '/')
            # Controlla sia nel source che nel path stesso
            is_steam_remote = (('steam userdata' in source_check and '/remote' in source_check) or
                             (self.game_context.steam_userdata_path.lower() in path_check and
                              '/remote' in path_check))
        is_steam_base = False
        if self.game_context.steam_userdata_path:
            source_check = source_lower.replace('\\', '/').lower()
            path_check = path_lower.replace('\\', '/')
            is_steam_base = (('steam userdata' in source_check and source_check.endswith('/base')) or
                           (self.game_context.steam_userdata_path.lower() in path_check and
                            path_check.endswith('/base')))
        is_in_prime_location = self._is_prime_location(path_lower) and not (is_steam_remote or is_steam_base)
        is_install_dir_walk = 'installdirwalk' in source_lower
        
        return {
            'is_steam_remote': is_steam_remote,
            'is_steam_base': is_steam_base,
            'is_in_prime_location': is_in_prime_location,
            'is_install_dir_walk': is_install_dir_walk
        }
    
    def _is_prime_location(self, path_lower: str) -> bool:
        """Verifica se il percorso è in una locazione primaria."""
        prime_locations = self._get_prime_locations()
        return any(path_lower.startswith(loc + os.sep) for loc in prime_locations)
    
    def _get_prime_locations(self) -> List[str]:
        """Ottiene le locazioni primarie per i salvataggi."""
        try:
            user_profile = os.path.expanduser('~')
            locations = [
                os.path.join(user_profile, 'Saved Games'),
                os.getenv('APPDATA', ''),
                os.getenv('LOCALAPPDATA', ''),
                os.path.join(user_profile, 'Documents', 'My Games'),
            ]
            localappdata = os.getenv('LOCALAPPDATA')
            if localappdata:
                locations.append(os.path.join(localappdata, '..', 'LocalLow'))
                
            return [os.path.normpath(loc).lower() for loc in locations if loc and os.path.isdir(loc)]
        except Exception as e:
            logging.warning(f"Error determining prime locations: {e}")
            return []
    
    def _get_location_score(self, path_type: Dict[str, bool], contains_saves: bool) -> int:
        """Calcola il punteggio base per la locazione."""
        if path_type['is_steam_remote']:
            return ScoreWeight.STEAM_REMOTE.value
        elif path_type['is_steam_base']:
            base_score = ScoreWeight.STEAM_BASE_NO_SAVES.value
            if contains_saves:
                base_score += ScoreWeight.STEAM_BASE_WITH_SAVES.value - ScoreWeight.STEAM_BASE_NO_SAVES.value
            return base_score
        elif path_type['is_in_prime_location']:
            return ScoreWeight.PRIME_USER_LOCATION.value
        elif path_type['is_install_dir_walk']:
            return ScoreWeight.INSTALL_DIR_WALK.value
        else:
            return ScoreWeight.DEFAULT_LOCATION.value
    
    def _get_positive_indicators_score(
        self, basename: str, basename_lower: str, source_lower: str, contains_saves: bool
    ) -> int:
        """Calcola il bonus per indicatori positivi."""
        score = 0
        
        if contains_saves:
            score += ScoreWeight.CONTAINS_SAVES.value
            
        if basename_lower in self.game_context.common_save_subdirs_lower:
            score += ScoreWeight.COMMON_SAVE_SUBDIR.value
            
        if (basename_lower in self.game_context.game_abbreviations_lower or
            self._matches_initial_sequence(basename) or
            'direct' in source_lower or 'gamenamelvl' in source_lower):
            score += ScoreWeight.DIRECT_MATCH.value
            
        return score
    
    def _matches_initial_sequence(self, folder_name: str) -> bool:
        """Verifica se il nome della cartella corrisponde alla sequenza di iniziali."""
        if not folder_name or not self.game_context.game_title_sig_words:
            return False
        try:
            word_initials = [word[0].upper() for word in self.game_context.game_title_sig_words if word]
            expected_sequence = "".join(word_initials)
            return folder_name.upper() == expected_sequence
        except Exception as e:
            logging.error(f"Error in matches_initial_sequence: {e}")
            return False
    
    def _get_name_similarity_score(self, basename_lower: str) -> int:
        """Calcola il bonus per similarità del nome."""
        cleaned_folder = self._clean_for_comparison(basename_lower)
        cleaned_original = self._clean_for_comparison(self.game_context.game_name)
        
        if not cleaned_folder or not cleaned_original:
            return 0
            
        if cleaned_folder == cleaned_original:
            return ScoreWeight.EXACT_NAME_MATCH.value
            
        if THEFUZZ_AVAILABLE:
            set_ratio = fuzz.token_set_ratio(cleaned_original, cleaned_folder)
            if set_ratio > self.MIN_FUZZY_RATIO:
                return int(((set_ratio - self.MIN_FUZZY_RATIO) / 15) * 300)
                
        return 0
    
    def _clean_for_comparison(self, name: str) -> str:
        """Pulisce un nome per il confronto."""
        if not isinstance(name, str):
            return ""
        name = re.sub(r'[™®©:]', '', name)
        name = re.sub(r'[-_]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name.lower()
    
    def _get_penalties(
        self, basename_lower: str, contains_saves: bool, 
        is_prime_location: bool, is_steam_remote: bool, is_install_dir_walk: bool
    ) -> int:
        """Calcola le penalità."""
        penalty = 0
        
        # Penalità per cartella 'data'
        if (basename_lower == 'data' and not contains_saves and 
            not is_prime_location and not is_steam_remote):
            penalty += ScoreWeight.DATA_FOLDER_PENALTY.value
            
        # Penalità per altre cartelle generiche
        elif (basename_lower in ['settings', 'config', 'cache', 'logs'] and 
              not contains_saves and not is_prime_location and not is_steam_remote):
            penalty += ScoreWeight.GENERIC_FOLDER_PENALTY.value
            
        # Penalità per nomi corti
        if (len(basename_lower) <= 3 and 
            basename_lower not in self.game_context.common_save_subdirs_lower and 
            not contains_saves):
            penalty += ScoreWeight.SHORT_NAME_PENALTY.value
            
        # Penalità per install dir walk senza saves
        if is_install_dir_walk and not contains_saves:
            penalty += ScoreWeight.INSTALL_DIR_NO_SAVES_PENALTY.value
            
        return penalty
    
    def _is_in_userdata(self, path_lower: str) -> bool:
        """Verifica se il percorso è nella cartella userdata di Steam."""
        if not self.game_context.steam_userdata_path:
            return False
        try:
            norm_userdata = os.path.normpath(self.game_context.steam_userdata_path).lower()
            return path_lower.startswith(norm_userdata + os.sep)
        except Exception:
            return False


@dataclass
class GameContext:
    """Contesto del gioco per la ricerca dei salvataggi."""
    game_name: str
    game_install_dir: Optional[str] = None
    appid: Optional[str] = None
    steam_userdata_path: Optional[str] = None
    steam_id3_to_use: Optional[str] = None
    is_steam_game: bool = True
    installed_steam_games_dict: Optional[Dict] = None
    
    def __post_init__(self):
        """Inizializza i dati derivati."""
        self.sanitized_name_base = re.sub(r'^(Play |Launch )', '', self.game_name, flags=re.IGNORECASE)
        self.sanitized_name = re.sub(r'[™®©:]', '', self.sanitized_name_base).strip()
        # Prima carica la configurazione
        self._load_config()
        # Poi genera abbreviazioni e altri dati che dipendono dalla config
        self.game_abbreviations = self._generate_abbreviations()
        self.game_abbreviations_upper = set(a.upper() for a in self.game_abbreviations if a)
        self.game_abbreviations_lower = set(a.lower() for a in self.game_abbreviations if a)
        self.game_title_sig_words = self._get_significant_words()
        
    def _load_config(self):
        """Carica la configurazione dal modulo config."""
        try:
            # Assicurati che le parole da ignorare siano quelle corrette
            default_ignore = {
                'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                'definitive', 'enhanced', 'complete', 'collection',
                'hd', 'ultra', 'deluxe', 'year'  # Rimosso 'game' dalla lista
            }
            self.ignore_words = getattr(config, 'SIMILARITY_IGNORE_WORDS', default_ignore)
            self.common_save_extensions = getattr(config, 'COMMON_SAVE_EXTENSIONS', set())
            self.common_save_filenames = getattr(config, 'COMMON_SAVE_FILENAMES', set())
            self.common_save_subdirs = getattr(config, 'COMMON_SAVE_SUBDIRS', [])
            self.common_publishers = getattr(config, 'COMMON_PUBLISHERS', [])
            self.banned_folder_names_lower = getattr(config, 'BANNED_FOLDER_NAMES_LOWER', {
                "microsoft", "nvidia corporation", "intel", "amd", "google", "mozilla",
                "common files", "internet explorer", "windows", "system32", "syswow64",
                "program files", "program files (x86)", "programdata", "drivers",
                "perflogs", "dell", "hp", "lenovo", "avast software", "avg",
                "kaspersky lab", "mcafee", "adobe", "python", "java", "oracle", "steam",
                "$recycle.bin", "config.msi", "system volume information",
                "default", "all users", "public", "vortex", "soundtrack", 
                "artbook", "extras", "dlc", "ost", "digital Content"
            })
        except AttributeError as e:
            logging.error(f"Error loading config: {e}. Using defaults.")
            self._set_default_config()
            
        self.ignore_words_lower = {w.lower() for w in self.ignore_words}
        self.common_save_subdirs_lower = {s.lower() for s in self.common_save_subdirs}
        self.common_publishers_set = set(p.lower() for p in self.common_publishers if p)
        
    def _set_default_config(self):
        """Imposta valori di configurazione di default."""
        self.ignore_words = {'a', 'an', 'the', 'of', 'and'}
        self.common_save_extensions = {'.sav', '.save', '.dat'}
        self.common_save_filenames = {'save', 'user', 'profile', 'settings', 'config', 'game', 'player'}
        self.common_save_subdirs = ['Saves', 'Save', 'SaveGame', 'Saved', 'SaveGames']
        self.common_publishers = []
        self.banned_folder_names_lower = {"windows", "program files", "program files (x86)", "system32"}
        
    def _generate_abbreviations(self) -> List[str]:
        """Genera abbreviazioni per il nome del gioco."""
        abbreviations = set()
        if not self.sanitized_name:
            return []
            
        # Aggiungi variazioni base
        abbreviations.add(self.sanitized_name)
        abbreviations.add(re.sub(r'\s+', '', self.sanitized_name))
        abbreviations.add(re.sub(r'[^a-zA-Z0-9]', '', self.sanitized_name))
        
        # Genera acronimi - usa nome originale per preservare numeri
        words = re.findall(r'\b\w+\b', self.game_name)
        
        # Acronimo completo (include tutte le parole, anche quelle ignorate per l'acronimo)
        acr_full = "".join(w[0] for w in words if w).upper()
        if len(acr_full) >= 2:
            abbreviations.add(acr_full)
        
        # Acronimo solo parole significative (esclude ignore_words)
        acr_sig = None
        significant_words = [w for w in words if w.lower() not in self.ignore_words_lower and len(w) > 1]
        if significant_words:
            acr_sig = "".join(w[0] for w in significant_words if w).upper()
            if len(acr_sig) >= 2 and acr_sig != acr_full:
                abbreviations.add(acr_sig)
                
        # Acronimo solo da parole maiuscole e numeri (per casi come "The Elder Scrolls V")
        capitalized_words = [w for w in words if (w and w[0].isupper()) or w.isdigit()]
        if capitalized_words:
            acr_caps = "".join(w[0] for w in capitalized_words if w).upper()
            # Controlla che non sia già presente
            existing = {acr_full}
            if acr_sig:
                existing.add(acr_sig)
            if len(acr_caps) >= 2 and acr_caps not in existing:
                abbreviations.add(acr_caps)
                
        # Gestisci nomi con due punti
        if ':' in self.game_name:
            self._add_colon_abbreviations(abbreviations)
            
        # Aggiungi abbreviazioni da executable
        if self.game_install_dir:
            self._add_exe_abbreviations(abbreviations)
        
        # Se il nome rilevato sembra un diminutivo (<= 5 caratteri),
        # arricchisci le varianti usando i nomi delle cartelle di installazione
        try:
            if self.game_install_dir and isinstance(self.sanitized_name, str) and len(self.sanitized_name) <= 5:
                self._add_install_dir_abbreviations(abbreviations)
        except Exception as e:
            logging.warning(f"Error expanding abbreviations from install dir: {e}")
            
        return sorted(list(filter(lambda x: x and len(x) >= 2, abbreviations)), key=len, reverse=True)
    
    def _add_colon_abbreviations(self, abbreviations: Set[str]):
        """Aggiunge abbreviazioni per giochi con due punti nel nome."""
        parts = self.game_name.split(':', 1)
        if len(parts) > 1:
            # Parte prima dei due punti
            name_before_colon = parts[0].strip()
            if name_before_colon:
                words_before = re.findall(r'\b\w+\b', name_before_colon)
                
                # Acronimo da tutte le parole maiuscole prima dei due punti
                caps_words_before = [w for w in words_before if (w and w[0].isupper()) or w.isdigit()]
                if caps_words_before:
                    acr_before = "".join(w[0] for w in caps_words_before if w).upper()
                    if len(acr_before) >= 2:
                        abbreviations.add(acr_before)
            
            # Parte dopo i due punti
            if parts[1].strip():
                name_after_colon = parts[1].strip()
                words_after = re.findall(r'\b\w+\b', name_after_colon)
                
                # Acronimo da tutte le parole maiuscole dopo i due punti (esclude articoli)
                caps_words_after = [w for w in words_after if w and w[0].isupper() and w.lower() not in {'the', 'a', 'an'}]
                if caps_words_after:
                    acr_caps_after = "".join(w[0] for w in caps_words_after if w).upper()
                    if len(acr_caps_after) >= 2:
                        abbreviations.add(acr_caps_after)
                        
                # Acronimo da parole significative dopo i due punti
                sig_words = [w for w in words_after if w.lower() not in self.ignore_words_lower and len(w) > 1]
                sig_words_caps = [w for w in sig_words if w and w[0].isupper()]
                
                if sig_words_caps:
                    acr = "".join(w[0] for w in sig_words_caps if w).upper()
                    if len(acr) >= 2 and acr != acr_caps_after:
                        abbreviations.add(acr)
                
                # Aggiungi anche acronimo completo della parte dopo i due punti
                all_words_after = [w for w in words_after if w]
                if all_words_after:
                    acr_all_after = "".join(w[0] for w in all_words_after if w).upper()
                    if len(acr_all_after) >= 2 and acr_all_after not in abbreviations:
                        abbreviations.add(acr_all_after)
                    
    def _add_exe_abbreviations(self, abbreviations: Set[str]):
        """Aggiunge abbreviazioni derivate dai file eseguibili."""
        exe_name = self._find_game_executable()
        if exe_name:
            # Rimuovi suffissi comuni
            common_suffixes = ['-Win64-Shipping', '-Win32-Shipping', '-Shipping', '.exe']
            for suffix in common_suffixes:
                if exe_name.lower().endswith(suffix.lower()):
                    exe_name = exe_name[:-len(suffix)]
                    break
                    
            # Rimuovi keyword comuni
            common_keywords = ['launcher', 'server', 'client', 'editor']
            for keyword in common_keywords:
                if exe_name.lower().endswith(keyword):
                    exe_name = exe_name[:-len(keyword)]
                    break
                    
            exe_name = re.sub(r'[-_]+$', '', exe_name)
            if len(exe_name) >= 2:
                abbreviations.add(exe_name)
    
    def _add_install_dir_abbreviations(self, abbreviations: Set[str]) -> None:
        """Aggiunge varianti del nome derivate dalle cartelle di installazione quando il titolo è molto corto.
        
        Esempio: se `game_name` è 'LOP' e `game_install_dir` è '.../Lies Of P (2023)/Lies of P',
        aggiunge 'Lies of P' e varianti pulite per potenziare la ricerca.
        """
        try:
            if not (self.game_install_dir and os.path.isdir(self.game_install_dir)):
                return
            base = os.path.basename(self.game_install_dir)
            parent_dir = os.path.dirname(self.game_install_dir) or ''
            parent = os.path.basename(parent_dir) if parent_dir else ''
            candidates = []
            for name in (base, parent):
                if not name:
                    continue
                # Rimuove contenuti tra parentesi/quadre/graffe (spesso anni o tag)
                name_clean = re.sub(r'[\(\[\{].*?[\)\]\}]', '', name).strip()
                # Rimuove eventuali suffissi di separatori
                name_clean = re.sub(r'[-_]+$', '', name_clean).strip()
                if len(name_clean) < 2:
                    continue
                # Escludi contenitori generici
                generic_names = {
                    'bin', 'binaries', 'win64', 'win32', 'x64', 'x86', 'game', 'games',
                    'steam', 'steamapps', 'common', 'program files', 'program files (x86)'
                }
                if name_clean.lower() in generic_names:
                    continue
                candidates.append(name_clean)
            
            added: Set[str] = set()
            for cand in candidates:
                # Versione originale (case-preserving)
                abbreviations.add(cand)
                added.add(cand)
                # Variante senza spazi
                no_space = cand.replace(' ', '')
                if len(no_space) >= 2:
                    abbreviations.add(no_space)
                    added.add(no_space)
                # Variante alfanumerica
                alnum_only = re.sub(r'[^A-Za-z0-9]', '', cand)
                if len(alnum_only) >= 2:
                    abbreviations.add(alnum_only)
                    added.add(alnum_only)
            if added:
                logging.info(f"Abbreviation expansion from install dir for short title '{self.sanitized_name}': {sorted(added)}")
        except Exception as e:
            logging.warning(f"_add_install_dir_abbreviations error: {e}")
                
    def _find_game_executable(self) -> Optional[str]:
        """Trova l'eseguibile principale del gioco."""
        if not self.game_install_dir or not os.path.isdir(self.game_install_dir):
            return None
            
        common_suffixes = ['Win64-Shipping.exe', 'Win32-Shipping.exe', '.exe']
        search_patterns = [
            os.path.join(self.game_install_dir, f"*{suffix}")
            for suffix in common_suffixes
        ] + [
            os.path.join(self.game_install_dir, "Binaries", "Win64", f"*{suffix}")
            for suffix in common_suffixes
        ] + [
            os.path.join(self.game_install_dir, "bin", f"*{suffix}")
            for suffix in common_suffixes
        ]
        
        for pattern in search_patterns:
            executables = glob.glob(pattern)
            if executables:
                # Filtra eseguibili troppo piccoli
                valid_exes = [e for e in executables if os.path.getsize(e) > 100 * 1024]
                if valid_exes:
                    return os.path.basename(valid_exes[0])
                elif executables:
                    return os.path.basename(executables[0])
                    
        return None
    
    def _get_significant_words(self) -> List[str]:
        """Ottiene le parole significative dal nome del gioco."""
        words = re.findall(r'\b\w+\b', self.sanitized_name)
        # Mantieni parole significative, incluso "game" se presente
        result = []
        for w in words:
            w_lower = w.lower()
            # Includi la parola se:
            # 1. Non è nelle ignore_words, O
            # 2. È un numero, O
            # 3. È "game" (caso speciale)
            if w_lower not in self.ignore_words_lower or w.isdigit() or w_lower == 'game':
                if len(w) >= 1:
                    result.append(w)
        return result


class SavePathFinder:
    """Classe principale per la ricerca dei percorsi di salvataggio."""
    
    def __init__(self, game_context: GameContext, cancellation_manager=None):
        self.context = game_context
        self.cancellation_manager = cancellation_manager
        self.path_scorer = PathScore(game_context)
        self.checked_paths: Set[str] = set()
        self.guesses_data: Dict[str, Tuple[str, str, bool]] = {}
        
    def find_save_paths(self) -> List[Tuple[str, int]]:
        """Trova i possibili percorsi di salvataggio per il gioco."""
        logging.info(f"Heuristic save search for '{self.context.game_name}' (AppID: {self.context.appid})")
        
        # Controlla cancellazione all'inizio
        if self.cancellation_manager and self.cancellation_manager.check_cancelled():
            logging.info(f"SavePathFinder: Search cancelled at start for '{self.context.game_name}'")
            return []
        
        # Ottieni locazioni comuni
        common_locations = self._get_common_locations()
        
        # Cerca nei vari percorsi
        self._check_steam_userdata()
        if self.cancellation_manager and self.cancellation_manager.check_cancelled():
            logging.info(f"SavePathFinder: Search cancelled after Steam userdata check for '{self.context.game_name}'")
            return []
            
        self._perform_direct_path_checks(common_locations)
        if self.cancellation_manager and self.cancellation_manager.check_cancelled():
            logging.info(f"SavePathFinder: Search cancelled after direct path checks for '{self.context.game_name}'")
            return []
            
        self._perform_exploratory_search(common_locations)
        if self.cancellation_manager and self.cancellation_manager.check_cancelled():
            logging.info(f"SavePathFinder: Search cancelled after exploratory search for '{self.context.game_name}'")
            return []
            
        self._search_install_directory()
        if self.cancellation_manager and self.cancellation_manager.check_cancelled():
            logging.info(f"SavePathFinder: Search cancelled after install directory search for '{self.context.game_name}'")
            return []
        
        # Ordina e restituisci i risultati
        return self._finalize_results()
    
    def _get_common_locations(self) -> Dict[str, str]:
        """Ottiene le locazioni comuni per i salvataggi su Windows."""
        user_profile = os.path.expanduser('~')
        appdata = os.getenv('APPDATA')
        localappdata = os.getenv('LOCALAPPDATA')
        public_docs = os.path.join(os.getenv('PUBLIC', 'C:\\Users\\Public'), 'Documents')
        saved_games = os.path.join(user_profile, 'Saved Games')
        documents = os.path.join(user_profile, 'Documents')
        
        locations = {
            "Saved Games": saved_games,
            "Documents": documents,
            "My Games": os.path.join(documents, 'My Games'),
            "AppData/Roaming": appdata,
            "AppData/Local": localappdata,
            "AppData/LocalLow": os.path.join(localappdata, '..', 'LocalLow') if localappdata else None,
            "Public Documents": public_docs,
        }
        
        programdata = os.getenv('ProgramData')
        if programdata:
            locations["ProgramData"] = programdata
            
        # Filtra solo percorsi validi
        valid_locations = {}
        for name, path in locations.items():
            if path:
                try:
                    norm_path = os.path.normpath(path)
                    if os.path.isdir(norm_path):
                        valid_locations[name] = norm_path
                except (OSError, TypeError, ValueError) as e:
                    logging.warning(f"Could not validate location '{name}': {e}")
                    
        return valid_locations
    
    def _add_guess(self, path: str, source_description: str) -> bool:
        """Aggiunge un percorso candidato se valido."""
        if not path:
            return False
            
        try:
            # Normalizza il percorso
            norm_path = os.path.normpath(path).strip()
            if not norm_path:
                return False
                
            norm_path_lower = norm_path.lower()
            
            # Verifica se già controllato
            if norm_path_lower in self.checked_paths:
                return False
                
            self.checked_paths.add(norm_path_lower)
            
            # Verifica se è una directory
            if not self._is_valid_directory(norm_path):
                return False
                
            # Filtra percorsi non validi
            if self._should_filter_path(norm_path):
                return False
                
            # Verifica match con altri giochi
            if not self._check_other_games_match(norm_path):
                return False
                
            # Controlla contenuto
            contains_saves = self._check_save_content(norm_path)
            
            # Aggiungi al dizionario
            self.guesses_data[norm_path_lower] = (norm_path, source_description, contains_saves)
            logging.info(f"Added path: '{norm_path}' (Source: {source_description})")
            
            return True
            
        except Exception as e:
            logging.error(f"Error adding guess '{path}': {e}")
            return False
    
    def _is_valid_directory(self, path: str) -> bool:
        """Verifica se il percorso è una directory valida."""
        try:
            return os.path.isdir(path)
        except OSError:
            return False
    
    def _should_filter_path(self, path: str) -> bool:
        """Determina se il percorso deve essere filtrato."""
        # Filtra remotecache.vdf
        try:
            items = os.listdir(path)
            if len(items) == 1 and items[0].lower() == "remotecache.vdf":
                return True
        except OSError:
            pass
            
        # Filtra root drive
        try:
            drive, tail = os.path.splitdrive(path)
            if not tail or tail == os.sep:
                return True
        except Exception:
            pass
            
        return False
    
    def _check_other_games_match(self, path: str) -> bool:
        """Verifica che il percorso non corrisponda ad altri giochi."""
        if not (self.context.installed_steam_games_dict and 
                self.context.appid and THEFUZZ_AVAILABLE):
            return True
            
        path_basename = os.path.basename(path)
        cleaned_folder = self._clean_for_comparison(path_basename)
        
        if not cleaned_folder:
            return True
            
        for other_appid, other_game_info in self.context.installed_steam_games_dict.items():
            if other_appid == self.context.appid:
                continue
                
            other_game_name = other_game_info.get('name', '')
            if not other_game_name:
                continue
                
            cleaned_other = self._clean_for_comparison(other_game_name)
            ratio = fuzz.token_set_ratio(cleaned_other, cleaned_folder)
            
            if ratio > 95:
                logging.warning(
                    f"Path rejected: '{path}' matches other game '{other_game_name}' "
                    f"(AppID: {other_appid}, Ratio: {ratio})"
                )
                return False
                
        return True
    
    def _clean_for_comparison(self, name: str) -> str:
        """Pulisce un nome per il confronto."""
        if not isinstance(name, str):
            return ""
        name = re.sub(r'[™®©:]', '', name)
        name = re.sub(r'[-_]', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name.lower()
    
    def _check_save_content(self, path: str) -> bool:
        """Verifica se la directory contiene file di salvataggio."""
        try:
            for item in os.listdir(path):
                item_lower = item.lower()
                item_path = os.path.join(path, item)
                
                if os.path.isfile(item_path):
                    _, ext = os.path.splitext(item_lower)
                    if ext in self.context.common_save_extensions:
                        return True
                        
                    for fname_part in self.context.common_save_filenames:
                        if fname_part in item_lower:
                            return True
                            
            return False
            
        except OSError:
            return False
    
    def _check_steam_userdata(self):
        """Controlla la cartella userdata di Steam."""
        if not (self.context.is_steam_game and self.context.appid and 
                self.context.steam_userdata_path and self.context.steam_id3_to_use):
            return
            
        logging.info(f"Checking Steam Userdata for AppID {self.context.appid}")
        
        try:
            user_folder = os.path.join(self.context.steam_userdata_path, self.context.steam_id3_to_use)
            if not os.path.isdir(user_folder):
                return
                
            base_path = os.path.join(user_folder, self.context.appid)
            remote_path = os.path.join(base_path, 'remote')
            
            # Aggiungi percorso remote
            if self._add_guess(remote_path, f"Steam Userdata/{self.context.steam_id3_to_use}/{self.context.appid}/remote"):
                # Cerca sottocartelle in remote
                try:
                    for entry in os.listdir(remote_path):
                        sub_path = os.path.join(remote_path, entry)
                        if os.path.isdir(sub_path) and self._is_relevant_subfolder(entry):
                            self._add_guess(sub_path, f"Steam Userdata/.../remote/{entry}")
                except Exception as e:
                    logging.warning(f"Error scanning Steam remote subfolders: {e}")
                    
            # Aggiungi percorso base
            self._add_guess(base_path, f"Steam Userdata/{self.context.steam_id3_to_use}/{self.context.appid}/Base")
            
        except Exception as e:
            logging.error(f"Error checking Steam userdata: {e}")
    
    def _is_relevant_subfolder(self, folder_name: str) -> bool:
        """Verifica se una sottocartella è rilevante per i salvataggi."""
        folder_lower = folder_name.lower()
        
        # Controlla se è una cartella di salvataggio comune
        if folder_lower in self.context.common_save_subdirs_lower:
            return True
            
        # Controlla parole chiave
        save_keywords = ['save', 'profile', 'user', 'slot']
        if any(keyword in folder_lower for keyword in save_keywords):
            return True
            
        # Controlla similarità nome
        if self._are_names_similar(self.context.sanitized_name, folder_name):
            return True
            
        # Controlla abbreviazioni
        if folder_name.upper() in self.context.game_abbreviations_upper:
            return True
            
        return False
    
    def _are_names_similar(self, name1: str, name2: str) -> bool:
        """Verifica se due nomi sono simili."""
        # Pulisci i nomi
        clean1 = re.sub(r'[^a-zA-Z0-9\s]', '', name1).lower()
        clean2 = re.sub(r'[^a-zA-Z0-9\s]', '', name2).lower()
        clean1 = re.sub(r'\s+', ' ', clean1).strip()
        clean2 = re.sub(r'\s+', ' ', clean2).strip()
        
        # Controlla uguaglianza senza spazi
        if clean1.replace(' ', '') == clean2.replace(' ', ''):
            return True
            
        # Controlla prefisso
        no_space1 = clean1.replace(' ', '')
        no_space2 = clean2.replace(' ', '')
        if len(no_space1) >= 3 and len(no_space2) >= 3:
            if no_space1.startswith(no_space2) or no_space2.startswith(no_space1):
                return True
        
        # Controlla se un nome corto (singola parola) è contenuto come parola completa nell'altro
        # Questo aiuta con casi come "isaac" in "Binding of Isaac Repentance+"
        words1 = clean1.split()
        words2 = clean2.split()
        
        # Se uno dei nomi è una singola parola di almeno 4 caratteri, controlla se è una parola nell'altro
        if len(words1) == 1 and len(words1[0]) >= 4:
            if words1[0] in words2:
                logging.debug(f"Word containment match: '{words1[0]}' found in {words2}")
                return True
        if len(words2) == 1 and len(words2[0]) >= 4:
            if words2[0] in words1:
                logging.debug(f"Word containment match: '{words2[0]}' found in {words1}")
                return True
                
        # Controlla fuzzy matching
        if THEFUZZ_AVAILABLE:
            ratio = fuzz.token_sort_ratio(clean1, clean2)
            if ratio >= 88:
                return True
            
            # Usa anche token_set_ratio per matching parziale migliore
            # Questo gestisce meglio i casi dove un nome è un sottoinsieme dell'altro
            set_ratio = fuzz.token_set_ratio(clean1, clean2)
            if set_ratio >= 92:
                logging.debug(f"Token set ratio match: '{clean1}' vs '{clean2}' = {set_ratio}")
                return True
                
        return False
    
    def _perform_direct_path_checks(self, locations: Dict[str, str]):
        """Esegue controlli diretti sui percorsi."""
        logging.info("Performing direct path checks...")
        
        for loc_name, base_folder in locations.items():
            # Controlla cancellazione
            if self.cancellation_manager and self.cancellation_manager.check_cancelled():
                return
                
            for variation in self.context.game_abbreviations:
                if not variation:
                    continue
                    
                try:
                    # Percorso diretto
                    direct_path = os.path.join(base_folder, variation)
                    self._add_guess(direct_path, f"{loc_name}/Direct/{variation}")
                    
                    # Percorsi con publisher
                    for publisher in self.context.common_publishers:
                        pub_path = os.path.join(base_folder, publisher, variation)
                        self._add_guess(pub_path, f"{loc_name}/{publisher}/Direct/{variation}")
                        
                    # Sottocartelle comuni
                    if os.path.isdir(direct_path):
                        for save_subdir in self.context.common_save_subdirs:
                            sub_path = os.path.join(direct_path, save_subdir)
                            self._add_guess(sub_path, f"{loc_name}/Direct/{variation}/{save_subdir}")
                            
                except Exception as e:
                    logging.warning(f"Error in direct path check: {e}")
    
    def _perform_exploratory_search(self, locations: Dict[str, str]):
        """Esegue una ricerca esplorativa nelle locazioni."""
        logging.info("Performing exploratory search...")
        
        for loc_name, base_folder in locations.items():
            # Controlla cancellazione
            if self.cancellation_manager and self.cancellation_manager.check_cancelled():
                return
            self._explore_location(loc_name, base_folder)
            
    def _explore_location(self, loc_name: str, base_folder: str):
        """Esplora una singola locazione."""
        try:
            for lvl1_name in os.listdir(base_folder):
                if lvl1_name.lower() in self.context.banned_folder_names_lower:
                    continue
                    
                lvl1_path = os.path.join(base_folder, lvl1_name)
                if not os.path.isdir(lvl1_path):
                    continue
                    
                # Verifica se è rilevante
                is_publisher = lvl1_name.lower() in self.context.common_publishers_set
                is_related = is_publisher or self._are_names_similar(self.context.sanitized_name, lvl1_name)
                
                # Controlla livello 1
                if self._is_game_match(lvl1_name):
                    self._add_guess(lvl1_path, f"{loc_name}/GameNameLvl1/{lvl1_name}")
                    self._check_save_subdirs(lvl1_path, f"{loc_name}/GameNameLvl1/{lvl1_name}")
                    
                # Controlla livello 2
                self._explore_level2(loc_name, lvl1_path, lvl1_name, is_related)
                
                # Controlla cancellazione
                if self.cancellation_manager and self.cancellation_manager.check_cancelled():
                    return
                    
        except OSError as e:
            logging.warning(f"Error exploring location '{base_folder}': {e}")
    
    def _is_game_match(self, folder_name: str) -> bool:
        """Verifica se il nome della cartella corrisponde al gioco."""
        folder_upper = folder_name.upper()
        
        if folder_upper in self.context.game_abbreviations_upper:
            return True
            
        if self._are_names_similar(self.context.sanitized_name, folder_name):
            return True
        
        # Controlla anche similarità con le abbreviazioni lunghe (es. nome espanso dalla cartella di install)
        # Questo aiuta quando il nome del gioco è corto ma abbiamo un'espansione dalla directory
        for abbrev in self.context.game_abbreviations:
            # Salta abbreviazioni corte, già controllate sopra
            if not abbrev or len(abbrev) <= len(self.context.sanitized_name):
                continue
            if self._are_names_similar(abbrev, folder_name):
                logging.debug(f"Match found via abbreviation '{abbrev}' for folder '{folder_name}'")
                return True
            
        return False
    
    def _check_save_subdirs(self, parent_path: str, parent_source: str):
        """Controlla le sottocartelle di salvataggio comuni."""
        try:
            for subdir in os.listdir(parent_path):
                if subdir.lower() in self.context.common_save_subdirs_lower:
                    sub_path = os.path.join(parent_path, subdir)
                    if os.path.isdir(sub_path):
                        self._add_guess(sub_path, f"{parent_source}/{subdir}")
        except OSError:
            pass
    
    def _explore_level2(self, loc_name: str, lvl1_path: str, lvl1_name: str, is_parent_related: bool):
        """Esplora il secondo livello di cartelle."""
        try:
            for lvl2_name in os.listdir(lvl1_path):
                # Controlla cancellazione durante l'iterazione
                if self.cancellation_manager and self.cancellation_manager.check_cancelled():
                    return
                    
                lvl2_path = os.path.join(lvl1_path, lvl2_name)
                if not os.path.isdir(lvl2_path):
                    continue
                    
                lvl2_lower = lvl2_name.lower()
                
                # Verifica match
                is_match = False
                if is_parent_related:
                    is_match = (self._are_names_similar(self.context.sanitized_name, lvl2_name) or
                               lvl2_name.upper() in self.context.game_abbreviations_upper)
                else:
                    is_match = self._are_names_similar(self.context.sanitized_name, lvl2_name)
                    
                if is_match:
                    self._add_guess(lvl2_path, f"{loc_name}/{lvl1_name}/GameNameLvl2/{lvl2_name}")
                    self._check_save_subdirs(lvl2_path, f"{loc_name}/.../GameNameLvl2/{lvl2_name}")
                    
                elif lvl2_lower in self.context.common_save_subdirs_lower:
                    if is_parent_related or self._is_game_match(lvl1_name):
                        self._add_guess(lvl2_path, f"{loc_name}/{lvl1_name}/SaveSubdirLvl2/{lvl2_name}")
                        
        except OSError:
            pass
    
    def _search_install_directory(self):
        """Cerca nella directory di installazione del gioco."""
        if not self.context.game_install_dir or not os.path.isdir(self.context.game_install_dir):
            return
            
        logging.info(f"Searching in install directory: {self.context.game_install_dir}")
        
        max_depth = 3
        install_depth = self.context.game_install_dir.rstrip(os.sep).count(os.sep)
        
        try:
            for root, dirs, _ in os.walk(self.context.game_install_dir, topdown=True):
                # Controlla cancellazione ad ogni iterazione
                if self.cancellation_manager and self.cancellation_manager.check_cancelled():
                    return
                    
                # Calcola profondità
                current_depth = root.rstrip(os.sep).count(os.sep)
                relative_depth = current_depth - install_depth
                
                if relative_depth >= max_depth:
                    dirs[:] = []
                    continue
                    
                # Filtra cartelle bannate
                dirs[:] = [d for d in dirs if d.lower() not in self.context.banned_folder_names_lower]
                
                # Controlla ogni directory
                for dir_name in list(dirs):
                    dir_path = os.path.join(root, dir_name)
                    
                    if not os.path.isdir(dir_path):
                        continue
                        
                    dir_lower = dir_name.lower()
                    relative_path = os.path.relpath(dir_path, self.context.game_install_dir)
                    
                    # Controlla se è rilevante
                    if dir_lower in self.context.common_save_subdirs_lower:
                        self._add_guess(dir_path, f"InstallDirWalk/SaveSubdir/{relative_path}")
                    elif self._is_game_match(dir_name):
                        self._add_guess(dir_path, f"InstallDirWalk/GameMatch/{relative_path}")
                    
        except Exception as e:
            logging.error(f"Error walking install directory: {e}")
    
    def _finalize_results(self) -> List[Tuple[str, int]]:
        """Finalizza e ordina i risultati."""
        logging.info("Finalizing results...")
        
        results = []
        for path_data in self.guesses_data.values():
            path, source, contains_saves = path_data
            score = self.path_scorer.calculate(path, source, contains_saves)
            # Restituisci anche un hint su eventuali salvataggi rilevati nella directory
            results.append((path, score, bool(contains_saves)))
            
        # Ordina per punteggio decrescente
        results.sort(key=lambda x: (-x[1], x[0].lower()))
        
        logging.info(f"Found {len(results)} potential save paths")
        
        return results


# Funzioni di compatibilità per mantenere l'interfaccia esistente
def generate_abbreviations(name: str, game_install_dir: Optional[str] = None) -> List[str]:
    """Wrapper per compatibilità con il codice esistente."""
    context = GameContext(name, game_install_dir)
    return context.game_abbreviations


def matches_initial_sequence(folder_name: str, game_title_words: List[str]) -> bool:
    """Wrapper per compatibilità con il codice esistente."""
    if not folder_name or not game_title_words:
        return False
    try:
        word_initials = [word[0].upper() for word in game_title_words if word]
        expected_sequence = "".join(word_initials)
        return folder_name.upper() == expected_sequence
    except Exception as e:
        logging.error(f"Error in matches_initial_sequence: {e}")
        return False


def are_names_similar(name1: str, name2: str, min_match_words: int = 2, 
                     fuzzy_threshold: int = 88, game_title_words_for_seq: Optional[List[str]] = None) -> bool:
    """Wrapper per compatibilità con il codice esistente."""
    finder = SavePathFinder(GameContext(name1))
    return finder._are_names_similar(name1, name2)


def clean_for_comparison(name: str) -> str:
    """Wrapper per compatibilità con il codice esistente."""
    if not isinstance(name, str):
        return ""
    name = re.sub(r'[™®©:]', '', name)
    name = re.sub(r'[-_]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()


def final_sort_key(guess_tuple: Tuple[str, str, bool], outer_scope_data: Dict) -> Tuple[int, str]:
    """Wrapper per compatibilità con il codice esistente."""
    game_context = GameContext(
        game_name=outer_scope_data.get('game_name', ''),
        steam_userdata_path=outer_scope_data.get('steam_userdata_path'),
        installed_steam_games_dict=outer_scope_data.get('installed_steam_games_dict')
    )
    
    # Aggiorna il contesto con i dati forniti
    game_context.common_save_subdirs_lower = outer_scope_data.get('common_save_subdirs_lower', set())
    game_context.game_abbreviations = outer_scope_data.get('game_abbreviations', [])
    game_context.game_abbreviations_lower = outer_scope_data.get('game_abbreviations_lower', set())
    game_context.game_title_sig_words = outer_scope_data.get('game_title_sig_words', [])
    
    scorer = PathScore(game_context)
    path, source, contains_saves = guess_tuple
    score = scorer.calculate(path, source, contains_saves)
    
    return (-score, path.lower())


def guess_save_path(game_name: str, game_install_dir: Optional[str] = None, 
                   appid: Optional[str] = None, steam_userdata_path: Optional[str] = None,
                   steam_id3_to_use: Optional[str] = None, is_steam_game: bool = True,
                   installed_steam_games_dict: Optional[Dict] = None, 
                   cancellation_manager=None) -> List[Tuple[str, int]]:
    """Wrapper per compatibilità con il codice esistente."""
    context = GameContext(
        game_name=game_name,
        game_install_dir=game_install_dir,
        appid=appid,
        steam_userdata_path=steam_userdata_path,
        steam_id3_to_use=steam_id3_to_use,
        is_steam_game=is_steam_game,
        installed_steam_games_dict=installed_steam_games_dict
    )
    
    finder = SavePathFinder(context, cancellation_manager)
    return finder.find_save_paths()


# Gestione importazione Linux
current_os = platform.system()
if current_os == "Linux":
    try:
        from save_path_finder_linux import *
        logging.info("Using Linux-specific save_path_finder")
        __all__ = ['generate_abbreviations', 'matches_initial_sequence', 'are_names_similar', 
                  'guess_save_path', 'clean_for_comparison', 'final_sort_key']
    except ImportError as e:
        logging.error(f"Error importing save_path_finder_linux: {e}")
        logging.warning("Falling back to Windows save_path_finder")