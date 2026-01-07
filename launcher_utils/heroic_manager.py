# launcher_utils/heroic_manager.py
# -*- coding: utf-8 -*-

"""
Heroic Games Launcher manager for SaveState.

Heroic is an open-source game launcher primarily for Linux (also available on Windows/macOS)
that supports:
- Epic Games Store (via Legendary backend)
- GOG.com (via gogdl backend)
- Sideloaded games (manually added)
- Amazon Prime Gaming (via Nile backend)

Data locations (Windows - from Heroic source code):
- %APPDATA%/heroic/sideload_apps/library.json - Manually added games
- %APPDATA%/heroic/legendaryConfig/legendary/installed.json - Epic Games installed
- %APPDATA%/heroic/gog_store/installed.json - GOG games installed (electron-store format)
- %APPDATA%/heroic/nile_config/nile/installed.json - Amazon Prime Gaming installed
- %APPDATA%/heroic/GamesConfig/ - Per-game configuration

Data locations (Linux - Standard):
- ~/.config/heroic/sideload_apps/library.json
- ~/.config/heroic/legendaryConfig/legendary/installed.json
- ~/.config/heroic/gog_store/installed.json
- ~/.config/heroic/nile_config/nile/installed.json
- ~/.config/legendary/installed.json (standalone Legendary - fallback)

Data locations (Linux - Snap):
- $SNAP_REAL_HOME/.config/heroic/ (main heroic config)
- $XDG_CONFIG_HOME/legendary/ (Legendary config for Snap only)

Data locations (Linux - Flatpak):
- ~/.var/app/com.heroicgameslauncher.hgl/config/heroic/

Data locations (macOS):
- ~/Library/Application Support/heroic/

NOTE: The store_cache/*.json files contain the FULL library (owned games), 
not just installed games. We prioritize installed.json which only contains
actually installed games.
"""

import os
import json
import logging
import platform
from typing import Optional, List, Dict, Tuple

log = logging.getLogger(__name__)


def _detect_linux_environment() -> str:
    """
    Detects the Linux environment type for Heroic.
    
    Returns:
        'snap' if running as Snap, 'flatpak' if Flatpak, 'standard' otherwise.
    """
    if os.getenv('SNAP'):
        return 'snap'
    if os.getenv('FLATPAK_ID'):
        return 'flatpak'
    return 'standard'


def get_heroic_config_path() -> Tuple[Optional[str], str]:
    """
    Determines the Heroic Games Launcher configuration directory.
    
    Handles multiple Linux environments:
    - Standard: ~/.config/heroic
    - Snap: $SNAP_REAL_HOME/.config/heroic  
    - Flatpak: ~/.var/app/com.heroicgameslauncher.hgl/config/heroic
    
    Returns:
        Tuple of (path to heroic config directory, environment type).
        Path is None if not found.
    """
    system = platform.system()
    env_type = 'standard'
    
    if system == "Windows":
        # Windows: %APPDATA%/heroic
        appdata = os.getenv('APPDATA')
        if appdata:
            heroic_path = os.path.join(appdata, "heroic")
            if os.path.isdir(heroic_path):
                log.info(f"Found Heroic config directory (Windows): {heroic_path}")
                return heroic_path, 'windows'
    
    elif system == "Linux":
        env_type = _detect_linux_environment()
        home = os.path.expanduser("~")
        
        if env_type == 'snap':
            # Snap uses $SNAP_REAL_HOME for user's actual home
            snap_real_home = os.getenv('SNAP_REAL_HOME', home)
            heroic_path = os.path.join(snap_real_home, ".config", "heroic")
            if os.path.isdir(heroic_path):
                log.info(f"Found Heroic config directory (Snap): {heroic_path}")
                return heroic_path, 'snap'
        
        elif env_type == 'flatpak':
            # Flatpak uses ~/.var/app/...
            heroic_path = os.path.join(home, ".var", "app", 
                                       "com.heroicgameslauncher.hgl", "config", "heroic")
            if os.path.isdir(heroic_path):
                log.info(f"Found Heroic config directory (Flatpak): {heroic_path}")
                return heroic_path, 'flatpak'
        
        # Standard Linux location (also fallback for Snap/Flatpak)
        heroic_path = os.path.join(home, ".config", "heroic")
        if os.path.isdir(heroic_path):
            log.info(f"Found Heroic config directory (Linux): {heroic_path}")
            return heroic_path, 'standard'
        
        # Try Flatpak path even if not in Flatpak env (user might have it installed)
        flatpak_path = os.path.join(home, ".var", "app", 
                                    "com.heroicgameslauncher.hgl", "config", "heroic")
        if os.path.isdir(flatpak_path):
            log.info(f"Found Heroic config directory (Flatpak fallback): {flatpak_path}")
            return flatpak_path, 'flatpak'
    
    elif system == "Darwin":
        # macOS: ~/Library/Application Support/heroic
        home = os.path.expanduser("~")
        heroic_path = os.path.join(home, "Library", "Application Support", "heroic")
        if os.path.isdir(heroic_path):
            log.info(f"Found Heroic config directory (macOS): {heroic_path}")
            return heroic_path, 'macos'
    
    log.warning("Could not find Heroic config directory")
    return None, env_type


def _read_json_file(file_path: str) -> Optional[dict]:
    """
    Safely reads a JSON file.
    
    Args:
        file_path: Path to the JSON file.
        
    Returns:
        Parsed JSON data or None if error.
    """
    try:
        if not os.path.isfile(file_path):
            log.debug(f"JSON file not found: {file_path}")
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log.debug(f"Successfully read JSON from: {file_path}")
            return data
            
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {file_path}: {e}")
    except PermissionError:
        log.error(f"Permission denied reading: {file_path}")
    except Exception as e:
        log.error(f"Error reading {file_path}: {e}")
    
    return None


def read_sideload_library(heroic_path: str) -> List[Dict]:
    """
    Reads the sideload_apps library (manually added games).
    
    File: {heroic_path}/sideload_apps/library.json
    
    Structure:
    {
        "games": [
            {
                "runner": "sideload",
                "app_name": "unique_id",
                "title": "Game Title",
                "install": {
                    "executable": "path/to/game.exe",
                    "platform": "Windows",
                    "is_dlc": false
                },
                "folder_name": "install_directory",
                "is_installed": true,
                ...
            }
        ]
    }
    
    Args:
        heroic_path: Path to heroic config directory.
        
    Returns:
        List of game dictionaries.
    """
    games = []
    library_path = os.path.join(heroic_path, "sideload_apps", "library.json")
    
    data = _read_json_file(library_path)
    if not data:
        return games
    
    games_list = data.get('games', [])
    
    for game in games_list:
        try:
            title = game.get('title', '')
            app_name = game.get('app_name', '')
            is_installed = game.get('is_installed', False)
            
            # Skip if not installed or no title
            if not title or not is_installed:
                continue
            
            # Get installation path
            folder_name = game.get('folder_name', '')
            install_info = game.get('install', {})
            executable = install_info.get('executable', '')
            
            # Determine the best path to use
            install_path = folder_name
            if not install_path and executable:
                install_path = os.path.dirname(executable)
            
            games.append({
                'name': title,
                'id': app_name or title,
                'path': install_path,
                'runner': 'sideload',
                'executable': executable,
            })
            log.debug(f"Found sideload game: {title}")
            
        except Exception as e:
            log.debug(f"Error parsing sideload game entry: {e}")
            continue
    
    log.info(f"Found {len(games)} sideload games")
    return games


def read_legendary_library(heroic_path: str, env_type: str = 'standard') -> List[Dict]:
    """
    Reads the Epic Games library (via Legendary backend).
    
    Heroic stores Legendary data in multiple possible locations:
    - {heroic_path}/legendaryConfig/legendary/installed.json (standard)
    - $XDG_CONFIG_HOME/legendary/installed.json (Snap only)
    
    Additionally, we also check the standalone Legendary path on Linux:
    - ~/.config/legendary/installed.json
    
    Structure of installed.json:
    {
        "game_app_name": {
            "app_name": "game_id",
            "title": "Game Title",
            "install_path": "/path/to/game",
            "executable": "game.exe",
            "is_dlc": false,
            ...
        }
    }
    
    Args:
        heroic_path: Path to heroic config directory.
        env_type: Linux environment type ('standard', 'snap', 'flatpak').
        
    Returns:
        List of game dictionaries.
    """
    games = []
    
    # Possible paths for Legendary installed games
    legendary_paths = []
    
    # For Snap, Legendary config is in $XDG_CONFIG_HOME/legendary
    if env_type == 'snap':
        xdg_config = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        legendary_paths.append(os.path.join(xdg_config, "legendary", "installed.json"))
    
    # Standard Heroic path for Legendary
    legendary_paths.append(
        os.path.join(heroic_path, "legendaryConfig", "legendary", "installed.json")
    )
    
    # On Linux, also check standalone Legendary as fallback
    if platform.system() == "Linux":
        home = os.path.expanduser("~")
        legendary_paths.append(os.path.join(home, ".config", "legendary", "installed.json"))
    
    for legendary_path in legendary_paths:
        data = _read_json_file(legendary_path)
        if not data:
            continue
        
        # installed.json is a dict where keys are app_names
        for app_name, game_info in data.items():
            try:
                # Skip if it's not a dict (metadata fields)
                if not isinstance(game_info, dict):
                    continue
                
                title = game_info.get('title', '')
                is_dlc = game_info.get('is_dlc', False)
                
                # Skip DLCs and entries without title
                if not title or is_dlc:
                    continue
                
                install_path = game_info.get('install_path', '')
                executable = game_info.get('executable', '')
                
                # Check if already added (avoid duplicates from multiple sources)
                if any(g['id'] == app_name for g in games):
                    continue
                
                games.append({
                    'name': title,
                    'id': app_name,
                    'path': install_path,
                    'runner': 'legendary',
                    'executable': os.path.join(install_path, executable) if install_path and executable else '',
                })
                log.debug(f"Found Epic/Legendary game: {title}")
                
            except Exception as e:
                log.debug(f"Error parsing Legendary game entry '{app_name}': {e}")
                continue
    
    log.info(f"Found {len(games)} Epic/Legendary games")
    return games


def read_gog_library(heroic_path: str) -> List[Dict]:
    """
    Reads the GOG library.
    
    File: {heroic_path}/gog_store/installed.json
    
    GOG uses electron-store format with 'installed' key containing array:
    {
        "installed": [
            {
                "appName": "game_id",
                "title": "Game Title", 
                "install_path": "/path/to/game",
                "platform": "windows|linux|osx",
                ...
            }
        ]
    }
    
    NOTE: We only read installed.json. The library.json/gog_library.json cache
    files contain ALL owned games, not just installed ones.
    
    Args:
        heroic_path: Path to heroic config directory.
        
    Returns:
        List of game dictionaries.
    """
    games = []
    
    # Only read installed.json - GOG electron-store format
    gog_installed = os.path.join(heroic_path, "gog_store", "installed.json")
    
    data = _read_json_file(gog_installed)
    if not data:
        return games
    
    # GOG uses electron-store format: {"installed": [...]}
    if isinstance(data, dict) and 'installed' in data:
        games_list = data.get('installed', [])
        for game_info in games_list:
            try:
                if not isinstance(game_info, dict):
                    continue
                    
                title = game_info.get('title', '')
                app_name = game_info.get('appName', '') or game_info.get('app_name', '')
                install_path = game_info.get('install_path', '') or game_info.get('installPath', '')
                is_dlc = game_info.get('is_dlc', False)
                
                # Must have title and install path, skip DLCs
                if not title or not install_path or is_dlc:
                    continue
                
                # Avoid duplicates
                if any(g['id'] == app_name for g in games):
                    continue
                
                games.append({
                    'name': title,
                    'id': app_name or title,
                    'path': install_path,
                    'runner': 'gog',
                    'executable': '',
                })
                log.debug(f"Found GOG game: {title}")
                
            except Exception as e:
                log.debug(f"Error parsing GOG game entry: {e}")
                continue
    
    log.info(f"Found {len(games)} GOG games")
    return games


def read_nile_library(heroic_path: str) -> List[Dict]:
    """
    Reads the Amazon Prime Gaming library (via Nile backend).
    
    File (from Heroic source code - nile/constants.ts):
    - {heroic_path}/nile_config/nile/installed.json - Installed games only
    
    NOTE: library.json contains ALL owned games, we only read installed.json
    to get actually installed games.
    
    Args:
        heroic_path: Path to heroic config directory.
        
    Returns:
        List of game dictionaries.
    """
    games = []
    
    # Only read installed.json - it contains actually installed games
    # library.json contains ALL owned games (even not installed)
    nile_installed = os.path.join(heroic_path, "nile_config", "nile", "installed.json")
    
    data = _read_json_file(nile_installed)
    if not data:
        return games
    
    # installed.json is a dict where keys are app_names
    if isinstance(data, dict):
        for app_name, game_info in data.items():
            try:
                if not isinstance(game_info, dict):
                    continue
                
                title = game_info.get('title', '')
                install_path = game_info.get('install_path', '') or game_info.get('installPath', '')
                
                # Must have title and install path to be considered installed
                if not title or not install_path:
                    continue
                
                games.append({
                    'name': title,
                    'id': app_name,
                    'path': install_path,
                    'runner': 'nile',
                    'executable': '',
                })
                log.debug(f"Found Amazon/Nile game: {title}")
                
            except Exception as e:
                log.debug(f"Error parsing Nile game entry '{app_name}': {e}")
                continue
    
    log.info(f"Found {len(games)} Amazon/Nile games")
    return games


def find_heroic_profiles(executable_path: Optional[str] = None) -> List[Dict]:
    """
    Finds all installed games in the Heroic Games Launcher.
    
    Combines games from all sources:
    - Sideloaded games (manually added)
    - Epic Games Store (Legendary backend)
    - GOG.com (gogdl backend)
    - Amazon Prime Gaming (Nile backend)
    
    NOTE: We read from installed.json files directly, NOT from store_cache.
    The cache files contain ALL owned games (even uninstalled), while
    installed.json only contains actually installed games.
    
    Filters out:
    - Entries without a valid install path
    - DLCs
    - Duplicate entries
    
    Args:
        executable_path: Optional path to Heroic executable (not used, 
                        kept for API consistency with other managers).
        
    Returns:
        List of profile dictionaries with keys:
        - 'id': Game identifier
        - 'name': Game display name  
        - 'path': Installation directory (for save path detection)
        - 'paths': List containing the installation path
        - 'runner': Source of the game (sideload/legendary/gog/nile)
    """
    log.info("Attempting to find Heroic Games Launcher profiles...")
    
    heroic_path, env_type = get_heroic_config_path()
    
    if not heroic_path:
        log.error("Cannot find Heroic profiles: Config directory not found.")
        return []
    
    log.info(f"Reading Heroic library from: {heroic_path} (env: {env_type})")
    
    # Collect games from all sources
    all_games = []
    
    # 1. Sideloaded games (from library.json)
    sideload_games = read_sideload_library(heroic_path)
    all_games.extend(sideload_games)
    
    # 2. Epic Games (Legendary) - from installed.json
    legendary_games = read_legendary_library(heroic_path, env_type)
    all_games.extend(legendary_games)
    
    # 3. GOG games - from installed.json (electron-store format)
    gog_games = read_gog_library(heroic_path)
    all_games.extend(gog_games)
    
    # 4. Amazon Prime Gaming (Nile) - from installed.json
    nile_games = read_nile_library(heroic_path)
    all_games.extend(nile_games)
    
    # Convert to profile format and filter
    profiles = []
    seen_names = set()
    filtered_count = 0
    
    for game in all_games:
        game_name = game['name']
        game_path = game.get('path', '')
        
        # Filter: Must have a valid install directory
        if not game_path or not os.path.isdir(game_path):
            log.debug(f"Filtered out '{game_name}': No valid install directory ({game_path})")
            filtered_count += 1
            continue
        
        # Filter: Avoid duplicates by name (case-insensitive)
        name_key = game_name.lower().strip()
        if name_key in seen_names:
            log.debug(f"Filtered out '{game_name}': Duplicate entry")
            filtered_count += 1
            continue
        seen_names.add(name_key)
        
        profile = {
            'id': game.get('id', game_name),
            'name': game_name,
            'path': game_path,
            'paths': [game_path],
            'runner': game.get('runner', 'unknown'),
        }
        profiles.append(profile)
    
    log.info(f"Found {len(profiles)} valid Heroic profiles ({filtered_count} filtered out).")
    return profiles
