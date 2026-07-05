# steam_utils.py
# -*- coding: utf-8 -*-
"""
Steam detection and management utilities.

This module provides functions to:
- Find Steam installation path across Windows, Linux, and macOS
- Parse VDF (Valve Data Format) configuration files
- Discover Steam library folders
- List installed Steam games
- Find Steam userdata and user profile information
"""

import logging
import os
import platform
from datetime import datetime

# --- Cache Variables ---
# These cache the results of expensive operations to avoid repeated filesystem scans

_steam_install_path = None
_steam_libraries = None
_installed_steam_games = None
_steam_userdata_path = None
_steam_id3 = None
_cached_possible_ids = None
_cached_id_details = None

# Constant for SteamID3 <-> SteamID64 conversion
STEAM_ID64_BASE = 76561197960265728


def clear_steam_cache():
    """
    Clear all cached Steam data.
    
    Call this function when Steam installation may have changed,
    or when you need to force a rescan of Steam data.
    """
    global _steam_install_path, _steam_libraries, _installed_steam_games
    global _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details
    
    _steam_install_path = None
    _steam_libraries = None
    _installed_steam_games = None
    _steam_userdata_path = None
    _steam_id3 = None
    _cached_possible_ids = None
    _cached_id_details = None
    
    logging.info("Steam cache cleared.")


def _parse_vdf(file_path: str) -> dict:
    """
    Parse a Valve Data Format (VDF) file.
    
    VDF is used by Steam for configuration files like libraryfolders.vdf,
    appmanifest files, and loginusers.vdf.
    
    Args:
        file_path: Path to the VDF file
        
    Returns:
        Parsed dictionary, or None if parsing fails
    """
    try:
        import vdf
    except ImportError:
        vdf = None

    if vdf is None:
        logging.error("Library 'vdf' not found. Cannot parse VDF files.")
        return None
    
    if not os.path.isfile(file_path):
        return None
   
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Remove C-style comments if present
        content = '\n'.join(line for line in content.splitlines() if not line.strip().startswith('//'))
        return vdf.loads(content, mapper=dict)
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        logging.warning(f"Encoding error reading VDF '{os.path.basename(file_path)}'. Trying fallback encoding...")
        try:
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


def get_steam_install_path() -> str:
    """
    Find the Steam installation path.
    
    Searches for Steam installation in:
    - Windows: Registry (HKCU and HKLM)
    - Linux: Common installation paths (~/.local/share/Steam, ~/.steam/steam, Flatpak)
    - macOS: ~/Library/Application Support/Steam
    
    Results are cached for performance.
    
    Returns:
        Steam installation path as string, or None if not found
    """
    global _steam_install_path
    
    if _steam_install_path is not None:
        return _steam_install_path

    current_os = platform.system()
    found_path = None

    if current_os == "Windows":
        found_path = _find_steam_windows()
    elif current_os == "Linux":
        found_path = _find_steam_linux()
    elif current_os == "Darwin":
        found_path = _find_steam_macos()
    else:
        logging.info(f"Steam path detection for OS '{current_os}' is not specifically implemented.")

    if found_path:
        _steam_install_path = found_path
        return _steam_install_path
    
    logging.warning("Steam installation path could not be determined.")
    return None


def _find_steam_windows() -> str:
    """Find Steam installation on Windows via registry."""
    winreg_module = None
    try:
        import winreg as wr
        winreg_module = wr
    except ImportError:
        logging.info("winreg module not available (normal for non-Windows).")
        return None
    
    if not winreg_module:
        logging.warning("winreg not imported correctly on Windows, cannot search Steam in registry.")
        return None
    
    try:
        key_path = r"Software\\Valve\\Steam"
        potential_hives = [
            (winreg_module.HKEY_CURRENT_USER, "HKCU"),
            (winreg_module.HKEY_LOCAL_MACHINE, "HKLM")
        ]
        
        for hive, hive_name in potential_hives:
            try:
                with winreg_module.OpenKey(hive, key_path) as hkey:
                    path_value, _ = winreg_module.QueryValueEx(hkey, "SteamPath")
                
                norm_path = os.path.normpath(path_value.replace('/', '\\\\'))
                if os.path.isdir(norm_path):
                    logging.info(f"Found Steam installation ({hive_name}) via registry: {norm_path}")
                    return norm_path
            except (FileNotFoundError, OSError):
                logging.debug(f"SteamPath not found in registry hive: {hive_name}\\{key_path}")
                continue
            except Exception as e:
                logging.warning(f"Error reading registry ({hive_name}): {e}")
        
        logging.warning("Steam installation not found in Windows registry.")
    except Exception as e:
        logging.error(f"Unexpected error searching for Steam on Windows via registry: {e}")
    
    return None


def _find_steam_linux() -> str:
    """Find Steam installation on Linux."""
    logging.info("Attempting to find Steam on Linux...")
    
    common_linux_paths = [
        os.path.expanduser("~/.local/share/Steam"),
        os.path.expanduser("~/.steam/steam"),
        os.path.expanduser("~/.steam/root"),
        os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam")  # Flatpak
    ]
    
    for path_to_check in common_linux_paths:
        if not os.path.isdir(path_to_check):
            logging.debug(f"Path does not exist or is not a directory: {path_to_check}")
            continue

        logging.debug(f"Checking for Steam indicators in: {path_to_check}")
        
        # Check for Steam installation indicators
        has_steam_sh = os.path.exists(os.path.join(path_to_check, "steam.sh"))
        has_steamapps = os.path.isdir(os.path.join(path_to_check, "steamapps"))
        has_userdata = os.path.isdir(os.path.join(path_to_check, "userdata"))
        has_config_vdf = os.path.exists(os.path.join(path_to_check, "config", "config.vdf"))
        has_libraryfolders_vdf = os.path.exists(os.path.join(path_to_check, "steamapps", "libraryfolders.vdf"))

        if (has_steamapps and has_userdata) or has_config_vdf or has_libraryfolders_vdf or has_steam_sh:
            found_path = os.path.normpath(path_to_check)
            logging.info(f"Found Steam installation on Linux at: {found_path} "
                        f"(Indicators: sh:{has_steam_sh}, apps:{has_steamapps}, "
                        f"user:{has_userdata}, conf_vdf:{has_config_vdf}, lib_vdf:{has_libraryfolders_vdf})")
            return found_path
        else:
            logging.debug(f"No clear Steam indicators found in {path_to_check}")
    
    logging.warning("Steam installation not found in common Linux paths.")
    return None


def _find_steam_macos() -> str:
    """Find Steam installation on macOS."""
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

        if has_steamapps and has_userdata:
            found_path = os.path.normpath(path_to_check)
            logging.info(f"Found Steam installation on macOS at: {found_path}")
            return found_path
    
    logging.warning("Steam installation not found in common macOS paths.")
    return None


def find_steam_libraries() -> list:
    """
    Find all Steam library folders.
    
    Reads libraryfolders.vdf to discover additional library locations
    beyond the main Steam installation directory.
    
    Results are cached for performance.
    
    Returns:
        List of Steam library paths
    """
    global _steam_libraries
    
    if _steam_libraries is not None:
        return _steam_libraries

    steam_path = get_steam_install_path()
    libs = []
    
    if not steam_path:
        _steam_libraries = []
        return libs

    # Main library (where Steam is installed)
    main_lib_steamapps = os.path.join(steam_path, 'steamapps')
    if os.path.isdir(main_lib_steamapps):
        libs.append(steam_path)

    # Read libraryfolders.vdf for additional libraries
    vdf_path = os.path.join(steam_path, 'config', 'libraryfolders.vdf')
    logging.info(f"Reading libraries from: {vdf_path}")
    data = _parse_vdf(vdf_path)
    added_libs_count = 0

    if data:
        lib_folders_data = data.get('libraryfolders', data)
        if isinstance(lib_folders_data, dict):
            for key, value in lib_folders_data.items():
                if key.isdigit() or isinstance(value, dict):
                    lib_info = value if isinstance(value, dict) else lib_folders_data.get(key)
                    if isinstance(lib_info, dict) and 'path' in lib_info:
                        lib_path_raw = lib_info['path']
                        lib_path = os.path.normpath(lib_path_raw.replace('\\\\', '\\'))
                        lib_steamapps_path = os.path.join(lib_path, 'steamapps')
                        if os.path.isdir(lib_steamapps_path) and lib_path not in libs:
                            libs.append(lib_path)
                            added_libs_count += 1

    logging.info(f"Found {len(libs)} total Steam libraries ({added_libs_count} from VDF).")
    _steam_libraries = list(dict.fromkeys(libs))  # Remove duplicates
    return _steam_libraries


def find_installed_steam_games() -> dict:
    """
    Find all installed Steam games.
    
    Scans all Steam library folders for appmanifest files and
    extracts game information.
    
    Results are cached for performance.
    
    Returns:
        Dictionary mapping appid to {'name': str, 'installdir': str}
    """
    global _installed_steam_games
    
    if _installed_steam_games is not None:
        return _installed_steam_games

    library_paths = find_steam_libraries()
    games = {}
    
    if not library_paths:
        _installed_steam_games = {}
        return games

    logging.info("Scanning libraries for installed Steam games...")
    total_games_found = 0
    processed_appids = set()

    for lib_path in library_paths:
        steamapps_path = os.path.join(lib_path, 'steamapps')
        if not os.path.isdir(steamapps_path):
            continue

        try:
            for filename in os.listdir(steamapps_path):
                if filename.startswith('appmanifest_') and filename.endswith('.acf'):
                    acf_path = os.path.join(steamapps_path, filename)
                    data = _parse_vdf(acf_path)
                    
                    if not data or 'AppState' not in data:
                        continue
                    
                    app_state = data['AppState']
                    game_info = _process_app_manifest(app_state, steamapps_path, lib_path, processed_appids)
                    
                    if game_info:
                        appid, name, installdir = game_info
                        games[appid] = {'name': name, 'installdir': installdir}
                        processed_appids.add(appid)
                        total_games_found += 1
                        logging.debug(f"  Added game: {name} (AppID: {appid})")
                        
        except Exception as e:
            logging.error(f"Error scanning games in '{steamapps_path}': {e}")

    logging.info(f"Found {total_games_found} installed Steam games.")
    _installed_steam_games = games
    return games


def _process_app_manifest(app_state: dict, steamapps_path: str, lib_path: str, 
                          processed_appids: set) -> tuple:
    """
    Process a single app manifest and extract game information.
    
    Args:
        app_state: Parsed AppState dictionary from manifest
        steamapps_path: Path to steamapps folder
        lib_path: Path to library root
        processed_appids: Set of already processed app IDs
        
    Returns:
        Tuple (appid, name, installdir) if valid game, None otherwise
    """
    required_fields = ['appid', 'name', 'installdir', 'StateFlags']
    if not all(k in app_state for k in required_fields):
        return None
    
    appid = app_state['appid']
    if appid in processed_appids:
        return None
    
    installdir_relative = app_state['installdir']
    installdir_absolute = os.path.normpath(os.path.join(steamapps_path, 'common', installdir_relative))
    name = app_state.get('name', f"Unknown Game {appid}").replace('™', '').replace('®', '').strip()
    
    # Check installation state
    state_flags = int(app_state.get('StateFlags', 0))
    is_installed_by_flag = (state_flags in [4, 6, 1026]) or \
                           (state_flags == 2 and os.path.isdir(installdir_absolute))
    
    if not is_installed_by_flag:
        logging.debug(f"  Skipping AppID {appid} ('{name}'): Not installed (StateFlags={state_flags}).")
        return None
    
    if not os.path.isdir(installdir_absolute):
        logging.debug(f"  Skipping AppID {appid} ('{name}'): Install directory not found.")
        return None
    
    # Filter out Steam Runtime and similar tools
    name_lower = name.lower()
    if "steam" in name_lower and "runtime" in name_lower:
        logging.info(f"Skipping '{name}' (AppID: {appid}) as it appears to be a Steam Runtime tool.")
        return None
    
    if not installdir_absolute or not isinstance(installdir_absolute, str):
        return None
    
    return appid, name, installdir_absolute


def find_steam_userdata_info() -> tuple:
    """
    Find Steam userdata information including user profiles.
    
    Scans the userdata folder to find Steam user IDs and their
    display names from loginusers.vdf.
    
    Results are cached for performance.
    
    Returns:
        Tuple (userdata_path, likely_id, possible_ids_list, id_details_dict)
        - userdata_path: Path to userdata folder
        - likely_id: Most recently used SteamID3
        - possible_ids: List of all found SteamID3s
        - id_details: Dict mapping ID to {'mtime', 'last_mod_str', 'display_name'}
    """
    try:
        import vdf
    except ImportError:
        vdf = None
    
    global _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details
    
    # Check cache
    if (_steam_userdata_path and _steam_id3 and
            _cached_possible_ids is not None and _cached_id_details is not None and
            all('display_name' in v for v in _cached_id_details.values())):
        logging.debug("Using cached Steam userdata info (with display names).")
        return _steam_userdata_path, _steam_id3, _cached_possible_ids, _cached_id_details

    # Reset cache
    _steam_userdata_path = None
    _steam_id3 = None
    _cached_possible_ids = None
    _cached_id_details = None

    logging.info("Starting new Steam userdata scan (including profile names)...")
    steam_path = get_steam_install_path()
    if not steam_path:
        logging.error("ERROR: Unable to find Steam installation path for userdata scan.")
        return None, None, [], {}

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        logging.warning(f"Steam 'userdata' folder not found in '{steam_path}'.")
        return None, None, [], {}

    # Read loginusers.vdf for display names
    user_persona_names = _read_login_users(steam_path, vdf)

    possible_ids = []
    last_modified_time = 0
    likely_id = None
    id_details = {}

    logging.info(f"Searching Steam user IDs in: {userdata_base}")
    try:
        for entry in os.listdir(userdata_base):
            user_path = os.path.join(userdata_base, entry)
            if entry.isdigit() and entry != '0' and os.path.isdir(user_path):
                user_info = _process_user_folder(entry, user_path, user_persona_names)
                possible_ids.append(entry)
                id_details[entry] = user_info
                
                if user_info['mtime'] > last_modified_time:
                    last_modified_time = user_info['mtime']
                    likely_id = entry

    except Exception as e:
        logging.error(f"ERROR scanning 'userdata': {e}")
        return None, None, [], {}

    # Update cache
    _steam_userdata_path = userdata_base
    _steam_id3 = likely_id
    _cached_possible_ids = possible_ids
    _cached_id_details = id_details

    logging.info(f"Found {len(possible_ids)} IDs in userdata. Most likely ID: {likely_id}")
    for uid, details in id_details.items():
        logging.info(f"  - ID: {uid}, Name: {details.get('display_name', '?')}, Last Mod: {details.get('last_mod_str', '?')}")

    return userdata_base, likely_id, possible_ids, id_details


def _read_login_users(steam_path: str, vdf_module) -> dict:
    """
    Read persona names from loginusers.vdf.
    
    Args:
        steam_path: Path to Steam installation
        vdf_module: Imported vdf module, or None if not available
        
    Returns:
        Dictionary mapping SteamID64 to PersonaName
    """
    user_persona_names = {}
    
    if not vdf_module:
        logging.warning("Library 'vdf' not available, unable to read Steam profile names.")
        return user_persona_names
    
    loginusers_path = os.path.join(steam_path, 'config', 'loginusers.vdf')
    logging.info(f"Reading profile names from: {loginusers_path}")
    
    loginusers_data = _parse_vdf(loginusers_path)
    if loginusers_data and 'users' in loginusers_data:
        for steam_id64_str, user_data in loginusers_data['users'].items():
            if isinstance(user_data, dict) and 'PersonaName' in user_data:
                user_persona_names[steam_id64_str] = user_data['PersonaName']
        logging.info(f"Found {len(user_persona_names)} profile names in loginusers.vdf.")
    else:
        logging.warning("Format 'loginusers.vdf' not recognized or file empty/corrupted.")
    
    return user_persona_names


def _process_user_folder(entry: str, user_path: str, user_persona_names: dict) -> dict:
    """
    Process a single user folder and extract user information.
    
    Args:
        entry: SteamID3 as string
        user_path: Path to user folder
        user_persona_names: Dictionary of SteamID64 -> PersonaName
        
    Returns:
        Dictionary with 'mtime', 'last_mod_str', 'display_name'
    """
    current_mtime = 0
    last_mod_str = "N/D"
    display_name = f"ID: {entry}"

    # Find PersonaName using ID3 -> ID64 conversion
    try:
        steam_id3_int = int(entry)
        steam_id64 = steam_id3_int + STEAM_ID64_BASE
        steam_id64_str = str(steam_id64)
        if steam_id64_str in user_persona_names:
            display_name = user_persona_names[steam_id64_str]
            logging.debug(f"Matched ID3 {entry} to Name: {display_name}")
    except ValueError:
        logging.warning(f"User ID found in userdata is not numeric: {entry}")
    except Exception as e_name:
        logging.error(f"ERROR retrieving name for ID {entry}: {e_name}")

    # Find last modification time
    config_vdf_path = os.path.join(user_path, 'config', 'localconfig.vdf')
    check_paths = [config_vdf_path, user_path]
    
    for check_path in check_paths:
        try:
            if os.path.exists(check_path):
                mtime = os.path.getmtime(check_path)
                if mtime > current_mtime:
                    current_mtime = mtime
                    try:
                        last_mod_str = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M')
                    except ValueError:
                        last_mod_str = "Invalid Date"
        except Exception:
            pass

    return {
        'mtime': current_mtime,
        'last_mod_str': last_mod_str,
        'display_name': display_name
    }
