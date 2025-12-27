# launcher_utils/launcher_manager.py
# -*- coding: utf-8 -*-

import logging
import os
from typing import Dict, List, Any, Optional

# Import specific launcher profile finders
from .playnite_manager import find_playnite_profiles

# Configure basic logging for this module
log = logging.getLogger(__name__)

# Define a type alias for the profile finder function for clarity
ProfileFinder = type(lambda path: {})

# Lista di launcher supportati (whitelist)
# Questi launcher hanno implementazioni complete per estrarre i giochi
KNOWN_LAUNCHERS = [
    'playnite',
]

# Lista di launcher conosciuti ma non ancora supportati (blacklist)
# Quando un utente trascina uno di questi, mostrerà un popup informativo
# NOTA: Steam è GIÀ supportato tramite steam_utils.py, non va in questa lista
# NOTA: I giochi provenienti da questi launcher sono supportati al 100%,
#       solo i launcher stessi non sono ancora integrati per l'estrazione automatica
UNKNOWN_LAUNCHERS = [
    # Launcher principali
    'gog galaxy', 'goggalaxy',
    'epic games', 'epicgameslauncher',
    'ubisoft connect', 'upc', 'uplay',
    'ea app', 'eadesktop', 'origin',
    'amazon games', 'amazongames',
    'rockstar games', 'rockstargameslauncher',
    'battle.net', 'battlenet',
    # Launcher Linux
    'heroic', 'heroicgameslauncher',
    'lutris',
    'legendary',
    # Altri
    'itch', 'itchio',
    'indiegala',
    'prime gaming',
]

# Dictionary mapping launcher keys to their configuration
LAUNCHERS: Dict[str, Dict[str, Any]] = {
    'playnite': {
        'name': 'Playnite',
        'profile_finder': lambda path: find_playnite_profiles(path)
    },
}


def get_launcher_display_name(launcher_key: str) -> Optional[str]:
    """Returns the display name for a given launcher key."""
    return LAUNCHERS.get(launcher_key, {}).get('name')


def get_available_launchers() -> List[str]:
    """Returns a list of keys for the configured launchers."""
    return list(LAUNCHERS.keys())


def find_profiles_for_launcher(launcher_key: str, custom_path: Optional[str] = None) -> List[Dict]:
    """
    Finds profiles for a specific launcher using its registered finder function.

    Args:
        launcher_key (str): The key identifying the launcher (e.g., 'playnite').
        custom_path (Optional[str]): An optional custom path to search for profiles.

    Returns:
        List[Dict]: A list of profiles found.
                   Returns an empty list if the launcher key is invalid or no profiles are found.
    """
    launcher_config = LAUNCHERS.get(launcher_key)
    if not launcher_config:
        log.error(f"Invalid launcher key provided: {launcher_key}")
        return []

    profile_finder = launcher_config.get('profile_finder')
    if not profile_finder:
        log.error(f"No profile finder configured for launcher: {launcher_key}")
        return []

    try:
        profiles = profile_finder(custom_path)
        log.info(f"Found {len(profiles)} profiles for {launcher_config.get('name', launcher_key)}.")
        return profiles
    except Exception as e:
        log.exception(f"Error finding profiles for {launcher_config.get('name', launcher_key)}: {e}")
        return []


def is_known_launcher(file_path: str) -> tuple[str, str | None]:
    """
    Verifica se il file è un launcher conosciuto e il suo stato di supporto.

    Args:
        file_path: Il percorso del file da verificare.

    Returns:
        tuple[str, str | None]: Una tupla contenente lo stato ('supported',
        'unsupported', 'not_found') e il nome del launcher rilevato (o None).
    """
    try:
        if not file_path or not os.path.exists(file_path):
            return 'not_found', None
        
        # Risolvi il collegamento .lnk se necessario
        target_path = file_path
        if file_path.lower().endswith('.lnk') and os.name == 'nt':
            try:
                import winshell
                shortcut = winshell.shortcut(file_path)
                resolved_target = shortcut.path
                
                if resolved_target and os.path.exists(resolved_target):
                    target_path = resolved_target
                    log.info(f"is_known_launcher: Resolved .lnk target to: {target_path}")
                else:
                    return 'not_found', None
            except Exception as e:
                log.error(f"Error resolving shortcut in is_known_launcher: {e}")
                return 'not_found', None
        
        # Verifica se il percorso contiene uno dei launcher conosciuti
        target_path_lower = target_path.lower()
        file_name = os.path.basename(target_path_lower)
        file_name_no_ext = os.path.splitext(file_name)[0]
        
        # Controlla prima i launcher supportati
        for launcher in KNOWN_LAUNCHERS:
            if (file_name_no_ext == launcher or 
                file_name_no_ext.startswith(launcher + "-") or
                file_name_no_ext.startswith(launcher + "_") or
                file_name_no_ext.startswith(launcher + ".") or
                f"\\{launcher}\\" in target_path_lower or 
                f"/{launcher}/" in target_path_lower or
                # Controllo specifico per Playnite
                'playnite.desktopapp' in file_name_no_ext or
                'playnite.fullscreenapp' in file_name_no_ext):
                log.info(f"Detected supported launcher '{launcher}' in path: {target_path}")
                return 'supported', launcher

        # Controlla i launcher non supportati
        for launcher in UNKNOWN_LAUNCHERS:
            # Normalizza il nome del launcher (rimuovi spazi per il confronto)
            launcher_normalized = launcher.replace(' ', '')
            if (file_name_no_ext == launcher_normalized or 
                file_name_no_ext.startswith(launcher_normalized + "-") or
                file_name_no_ext.startswith(launcher_normalized + "_") or
                file_name_no_ext.startswith(launcher_normalized + ".") or
                f"\\{launcher_normalized}\\" in target_path_lower or 
                f"/{launcher_normalized}/" in target_path_lower or
                # Controllo con spazi
                launcher.replace(' ', '') in file_name_no_ext.replace(' ', '')):
                log.info(f"Detected unsupported launcher '{launcher}' in path: {target_path}")
                return 'unsupported', launcher

        return 'not_found', None
    except Exception as e:
        log.error(f"Error in is_known_launcher: {e}")
        return 'not_found', None


def detect_and_find_profiles(target_path: str | None) -> tuple[str, list[dict]] | None:
    """
    Detects if the target path belongs to a known launcher and finds its profiles.
    
    Args:
        target_path: Path to the launcher executable or directory.
        
    Returns:
        tuple[str, list[dict]]: (launcher_name, profiles_list) if launcher detected.
        None if no launcher detected.
    """
    if not target_path or not isinstance(target_path, str):
        log.debug("detect_and_find_profiles: Invalid target_path provided.")
        return None

    target_path_lower = target_path.lower()
    executable_dir = None
    if os.path.isfile(target_path):
        executable_dir = os.path.dirname(target_path)
        log.debug(f"Derived executable directory: {executable_dir}")

    # Iterate through the configured launchers
    for keyword, config in LAUNCHERS.items():
        # Check if the keyword is in the target path
        # Per Playnite, controlliamo anche nomi specifici
        is_match = False
        if keyword == 'playnite':
            is_match = ('playnite' in target_path_lower or
                       'playnite.desktopapp' in target_path_lower or
                       'playnite.fullscreenapp' in target_path_lower)
        else:
            is_match = keyword in target_path_lower
            
        if is_match:
            launcher_name = config['name']
            profile_finder = config['profile_finder']
            log.info(f"Detected known launcher '{launcher_name}' based on target path: {target_path}")

            # Determine the path to pass to the profile finder
            path_to_scan = target_path 
            if target_path and os.path.isfile(target_path):
                path_to_scan = os.path.dirname(target_path)
                log.debug(f"Target path is a file. Using directory: {path_to_scan}")

            try:
                profiles = profile_finder(path_to_scan) 
                
                if profiles is None:
                    log.warning(f"Profile finder for '{launcher_name}' returned None.")
                    return launcher_name, []

                log.info(f"Profile finder for {launcher_name} ran. Found {len(profiles)} profiles.")
                return launcher_name, profiles
                
            except Exception as e:
                log.error(f"Error calling profile finder for {launcher_name}: {e}", exc_info=True)
                return launcher_name, []
    
    log.debug(f"Target path '{target_path}' did not match any known launcher keywords.")
    return None
