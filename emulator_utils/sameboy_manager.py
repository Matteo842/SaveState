# emulator_utils/sameboy_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import glob
import re
from settings_manager import load_settings

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())  # Avoid 'No handler found' warnings

def get_sameboy_prefs_path():
    """
    Gets the default SameBoy prefs.bin path based on the platform.
    """
    system = platform.system()
    
    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            return os.path.join(appdata, "SameBoy", "prefs.bin")
        log.warning("APPDATA environment variable not found on Windows.")
    elif system == "Darwin":  # macOS
        user_home = os.path.expanduser("~")
        return os.path.join(user_home, "Library", "Application Support", "SameBoy", "prefs.bin")
    elif system == "Linux":
        user_home = os.path.expanduser("~")
        # First check the lowercase path as specified by the user
        linux_path = os.path.join(user_home, ".config", "sameboy", "prefs.bin")
        if os.path.exists(linux_path):
            return linux_path
            
        # Then try with uppercase 'SameBoy' as a fallback
        linux_path_alt = os.path.join(user_home, ".config", "SameBoy", "prefs.bin")
        if os.path.exists(linux_path_alt):
            return linux_path_alt
            
        # Also try XDG_CONFIG_HOME if set
        xdg_config = os.getenv('XDG_CONFIG_HOME')
        if xdg_config:
            xdg_path = os.path.join(xdg_config, "sameboy", "prefs.bin")
            if os.path.exists(xdg_path):
                return xdg_path
            xdg_path_alt = os.path.join(xdg_config, "SameBoy", "prefs.bin")
            if os.path.exists(xdg_path_alt):
                return xdg_path_alt
                
        # Return the most likely path even if it doesn't exist yet
        return linux_path
    
    log.warning(f"Unsupported platform {system} for SameBoy prefs.bin path detection.")
    return None

def find_potential_rom_paths_in_prefs(prefs_path):
    """
    Tries to find path-like strings within prefs.bin.
    This is a heuristic approach and might not be 100% accurate.
    """
    potential_paths = set()
    if not os.path.isfile(prefs_path):
        log.warning(f"prefs.bin file not found at: {prefs_path}")
        return list(potential_paths)

    try:
        with open(prefs_path, 'rb') as f:
            content = f.read()

        # Look for byte sequences that could be path strings
        # This is a very generic regex to find path-like strings
        # It looks for printable character sequences that include \ or / and end with .gb, .gbc, .zip etc.
        # or simply directories containing keywords like "ROM" or "Game".
        for match in re.finditer(rb"[ -~]{5,512}", content):
            try:
                potential_string = match.group(0).decode('latin-1')  # Try latin-1 for maximum ASCII-like compatibility
                # Filter for strings that look like paths
                if '\\' in potential_string or '/' in potential_string:
                    if any(ext in potential_string.lower() for ext in ['.gb', '.gbc', '.zip', 'rom', 'game', 'save']):
                        # Extract the directory containing this potential file/subfolder
                        path_part = potential_string
                        # Remove any null characters or garbage at the end
                        path_part = path_part.split('\x00')[0].strip()

                        # Try to normalize and get the directory
                        try:
                            # If it's a file, get the directory
                            if os.path.isfile(path_part) or any(path_part.lower().endswith(ext) for ext in ['.gb', '.gbc', '.sgb', '.zip']):
                                dir_path = os.path.dirname(path_part)
                            # If it's already a plausible directory
                            elif os.path.isdir(path_part):
                                dir_path = path_part
                            else:
                                # Maybe it's part of a longer or malformed path, let's try to see if part of it is a directory
                                parts = re.split(r'[\\\/]', path_part)
                                found_valid_parent = False
                                for i in range(len(parts), 0, -1):
                                    try:
                                        temp_path_try = os.path.join(*parts[:i])
                                        if os.path.isdir(temp_path_try):
                                            dir_path = temp_path_try
                                            found_valid_parent = True
                                            break
                                    except Exception:
                                        continue
                                if not found_valid_parent:
                                    continue  # We couldn't extract a valid directory
                            
                            # Normalize and add only existing directories
                            normalized_dir = os.path.normpath(dir_path)
                            if os.path.isdir(normalized_dir):
                                potential_paths.add(normalized_dir)
                        except Exception as e:
                            log.debug(f"Error parsing path {path_part}: {e}")
                            pass  # Ignore errors in individual path parsing
            except UnicodeDecodeError:
                pass  # Not a valid latin-1 string
            except Exception as e:
                log.debug(f"Error processing potential path: {e}")
                pass  # Other errors

    except Exception as e:
        log.error(f"Error reading or parsing {prefs_path}: {e}")
    
    return list(potential_paths)

def get_sameboy_saves_path(executable_path: str | None = None):
    """
    Gets the SameBoy save directory based on platform.
    SameBoy typically stores save files (.sav) in the same directory as the ROM files.
    Checks for a user-defined path in settings first, then executable directory for portable installations, then common hardcoded paths.
    
    Args:
        executable_path: Optional path to the SameBoy executable for portable installations.
    """
    system = platform.system()
    user_home = os.path.expanduser("~")

    current_settings, _ = load_settings()
    custom_paths = current_settings.get("custom_paths", {})
    custom_sameboy_rom_path = custom_paths.get("sameboy_rom_dir")

    # 0. Try to find paths from SameBoy prefs.bin first
    prefs_path = get_sameboy_prefs_path()
    if prefs_path:
        log.info(f"Checking SameBoy prefs.bin at: {prefs_path}")
        rom_folders = find_potential_rom_paths_in_prefs(prefs_path)
        
        if rom_folders:
            # Filter further to folders that actually contain ROM or save files
            actual_rom_or_save_holding_dirs = set()
            for folder in rom_folders:
                try:
                    if os.path.isdir(folder):
                        # Look for .gb, .gbc, .sav, .srm files
                        has_relevant_files = False
                        for root, _, files_in_folder in os.walk(folder):
                            for fname in files_in_folder:
                                if fname.lower().endswith(('.gb', '.gbc', '.sav', '.srm')):
                                    actual_rom_or_save_holding_dirs.add(folder)  # Add the parent folder
                                    has_relevant_files = True
                                    break
                            if has_relevant_files:  # Found in a subfolder, this parent folder is good
                                break
                except Exception as e_walk:
                    log.warning(f"Error scanning folder {folder}: {e_walk}")

            if actual_rom_or_save_holding_dirs:
                log.info(f"Found {len(actual_rom_or_save_holding_dirs)} folders with ROM/Save files from prefs.bin")
                # Return the first folder that contains save files, or if none have saves, return the first with ROMs
                for folder in actual_rom_or_save_holding_dirs:
                    if glob.glob(os.path.join(folder, "*.sav")) or glob.glob(os.path.join(folder, "*.srm")):
                        log.info(f"Found save files in folder from prefs.bin: {folder}")
                        return folder
                
                # If we didn't find any folder with saves, return the first with ROMs
                for folder in actual_rom_or_save_holding_dirs:
                    if glob.glob(os.path.join(folder, "*.gb")) or glob.glob(os.path.join(folder, "*.gbc")):
                        log.info(f"Found ROM files (but no saves yet) in folder from prefs.bin: {folder}")
                        return folder
            else:
                log.info("No folders with ROM/Save files found among extracted paths from prefs.bin")
        else:
            log.info("No path-like strings found in prefs.bin, or the file is empty/corrupted")
    
    # If we couldn't find anything from prefs.bin, fall back to the existing methods
    log.info("Falling back to custom settings and hardcoded paths")
    
    # 1. Controlla il percorso personalizzato nelle impostazioni
    if custom_sameboy_rom_path and os.path.isdir(custom_sameboy_rom_path):
        log.info(f"Checking user-defined SameBoy ROM path: {custom_sameboy_rom_path}")
        if glob.glob(os.path.join(custom_sameboy_rom_path, "*.sav")) or glob.glob(os.path.join(custom_sameboy_rom_path, "*.srm")):
            log.info(f"Found save files in user-defined SameBoy ROM path: {custom_sameboy_rom_path}")
            return custom_sameboy_rom_path
        # Anche se non ci sono .sav, se ci sono ROM, potrebbe essere il posto giusto
        if glob.glob(os.path.join(custom_sameboy_rom_path, "*.gb")) or glob.glob(os.path.join(custom_sameboy_rom_path, "*.gbc")):
            log.info(f"Found ROM files (but no saves yet) in user-defined SameBoy ROM path: {custom_sameboy_rom_path}")
            return custom_sameboy_rom_path
        log.warning(f"User-defined SameBoy ROM path '{custom_sameboy_rom_path}' is a directory, but no saves or ROMs found there.")
        
    # 2. Controlla la directory dell'eseguibile per installazioni portable
    if executable_path:
        executable_dir = os.path.dirname(executable_path) if os.path.isfile(executable_path) else executable_path
        log.info(f"Checking SameBoy executable directory for portable installation: {executable_dir}")
        
        # Controlla direttamente nella directory dell'eseguibile
        if os.path.isdir(executable_dir):
            if glob.glob(os.path.join(executable_dir, "*.sav")) or glob.glob(os.path.join(executable_dir, "*.srm")):
                log.info(f"Found save files in SameBoy executable directory: {executable_dir}")
                return executable_dir
            if glob.glob(os.path.join(executable_dir, "*.gb")) or glob.glob(os.path.join(executable_dir, "*.gbc")):
                log.info(f"Found ROM files (but no saves yet) in SameBoy executable directory: {executable_dir}")
                return executable_dir
                
        # Controlla nelle sottodirectory comuni per ROM/salvataggi
        for rom_subfolder in ["ROMs", "Saves", "roms", "saves", "GB", "GBC", "GameBoy"]:
            subdir_path = os.path.join(executable_dir, rom_subfolder)
            if os.path.isdir(subdir_path):
                if glob.glob(os.path.join(subdir_path, "*.sav")) or glob.glob(os.path.join(subdir_path, "*.srm")):
                    log.info(f"Found save files in SameBoy executable subdirectory: {subdir_path}")
                    return subdir_path
                if glob.glob(os.path.join(subdir_path, "*.gb")) or glob.glob(os.path.join(subdir_path, "*.gbc")):
                    log.info(f"Found ROM files (but no saves yet) in SameBoy executable subdirectory: {subdir_path}")
                    return subdir_path

    # 2. Definisci una lista più estesa di percorsi hardcoded
    hardcoded_paths = []
    common_rom_folders = ["ROMs", "ROM", "Games", "Emulation", "Emulator ROMs", "My ROMs", "Game Roms"]
    gameboy_folders = ["GameBoy", "GB", "GameBoyColor", "GBC", "Game Boy Color", "Nintendo GameBoy", "Nintendo GBC"]
    sameboy_app_folders = ["SameBoy", "sameboy"]

    # Percorsi basati sulla home dell'utente
    for doc_type in ["Documents", "Downloads", "Desktop"] :
        base_user_path = os.path.join(user_home, doc_type)
        for rom_folder in common_rom_folders + [""]:
            for gb_folder in gameboy_folders:
                hardcoded_paths.append(os.path.join(base_user_path, rom_folder, gb_folder))
                hardcoded_paths.append(os.path.join(base_user_path, gb_folder)) # Senza cartella ROM intermedia

    if system == "Windows":
        possible_drives = []
        for letter_code in range(ord('C'), ord('Z') + 1):
            drive = chr(letter_code) + ":\\"
            if os.path.exists(drive):
                possible_drives.append(drive)
        if not possible_drives:
             possible_drives = ['C:\\', 'D:\\', 'E:\\', 'F:\\'] # Fallback se nessun drive viene rilevato
        log.debug(f"Windows drives to check: {possible_drives}")

        for drive in possible_drives:
            for rom_folder in common_rom_folders + [""]:
                for gb_folder in gameboy_folders:
                    hardcoded_paths.append(os.path.join(drive, rom_folder, gb_folder))
                    hardcoded_paths.append(os.path.join(drive, gb_folder))
            # Percorsi specifici per l'emulatore SameBoy
            for app_folder_base in ['Program Files', 'Program Files (x86)', 'Games', 'Emulators', '']:
                for sb_app_folder in sameboy_app_folders:
                    base_path = os.path.join(drive, app_folder_base, sb_app_folder)
                    hardcoded_paths.append(base_path)
                    for rom_subfolder in ["ROMs", "Saves", "roms", "saves"] + gameboy_folders:
                        hardcoded_paths.append(os.path.join(base_path, rom_subfolder))

        # Fallback paths specifici di Windows (AppData, etc.)
        if os.getenv('APPDATA'):
            hardcoded_paths.append(os.path.join(os.getenv('APPDATA'), "SameBoy", "Saves"))
            hardcoded_paths.append(os.path.join(os.getenv('APPDATA'), "SameBoy"))
        if os.getenv('LOCALAPPDATA'):
            hardcoded_paths.append(os.path.join(os.getenv('LOCALAPPDATA'), "SameBoy", "Saves"))
            hardcoded_paths.append(os.path.join(os.getenv('LOCALAPPDATA'), "SameBoy"))
        hardcoded_paths.append(os.path.join(user_home, "Documents", "SameBoy", "Saves"))
        hardcoded_paths.append(os.path.join(user_home, "Documents", "SameBoy"))

    elif system == "Darwin":  # macOS
        for rom_folder in common_rom_folders + [""]:
            for gb_folder in gameboy_folders:
                hardcoded_paths.append(os.path.join(user_home, "Documents", rom_folder, gb_folder))
                hardcoded_paths.append(os.path.join(user_home, "Applications", rom_folder, gb_folder))
        hardcoded_paths.append(os.path.join(user_home, "Library", "Application Support", "SameBoy", "Saves"))
        hardcoded_paths.append(os.path.join(user_home, "Library", "Application Support", "SameBoy"))
        hardcoded_paths.append(os.path.join("/Applications", "SameBoy.app", "Contents", "Resources", "ROMs")) # Dentro l'app bundle

    elif system == "Linux":
        for base_dir in [user_home, os.path.join(user_home, ".local", "share"), os.path.join(user_home, ".config"), "/usr/share", "/usr/local/share"]:
            for rom_folder in common_rom_folders + [""]:
                for gb_folder in gameboy_folders:
                    hardcoded_paths.append(os.path.join(base_dir, rom_folder, gb_folder))
            for sb_app_folder in sameboy_app_folders:
                 hardcoded_paths.append(os.path.join(base_dir, sb_app_folder, "Saves"))
                 hardcoded_paths.append(os.path.join(base_dir, sb_app_folder))
        hardcoded_paths.append(os.path.join(user_home, ".var", "app", "io.github.sameboy", "data", "Saves")) # Flatpak
        hardcoded_paths.append(os.path.join(user_home, ".var", "app", "io.github.sameboy", "data", "ROMs")) # Flatpak
        hardcoded_paths.append(os.path.join(user_home, ".var", "app", "io.github.sameboy", "data")) # Flatpak

    # Rimuovi duplicati e normalizza i percorsi
    unique_paths = []
    for p in hardcoded_paths:
        norm_p = os.path.normpath(p)
        if norm_p not in unique_paths:
            unique_paths.append(norm_p)
    
    log.debug(f"Expanded SameBoy search paths ({len(unique_paths)} unique): {unique_paths[:10]}...")

    # 3. Verifica i percorsi hardcoded per file .sav o .srm
    for path in unique_paths:
        if os.path.isdir(path):
            if glob.glob(os.path.join(path, "*.sav")) or glob.glob(os.path.join(path, "*.srm")):
                log.info(f"Found save files in hardcoded path: {path}")
                return path
    
    # 4. Se non ci sono salvataggi, verifica i percorsi hardcoded per file ROM (.gb, .gbc)
    #    Questo aiuta a suggerire una directory ROM valida anche se i salvataggi non sono ancora stati creati.
    if custom_sameboy_rom_path and os.path.isdir(custom_sameboy_rom_path): # Ricontrolla il custom path per le ROM se non c'erano save
        if glob.glob(os.path.join(custom_sameboy_rom_path, "*.gb")) or glob.glob(os.path.join(custom_sameboy_rom_path, "*.gbc")):
            log.info(f"Found ROMs (no saves) in user-defined path: {custom_sameboy_rom_path}. Using this path.")
            return custom_sameboy_rom_path
            
    for path in unique_paths:
        if os.path.isdir(path):
            if glob.glob(os.path.join(path, "*.gb")) or glob.glob(os.path.join(path, "*.gbc")):
                log.info(f"Found ROMs (no saves) in hardcoded path: {path}. Suggesting this path.")
                return path

    log.warning("Could not find any valid SameBoy save or ROM directories after checking custom and hardcoded paths.")
    return None # Segnala che bisogna chiedere all'utente

def find_sameboy_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds SameBoy save files (.sav, .srm) using get_sameboy_saves_path.
    If get_sameboy_saves_path returns None, this function will also return None
    to indicate that the user should be prompted for a directory.
    
    Args:
        executable_path: Optional path to the SameBoy executable (currently used by get_sameboy_saves_path if settings path is not set).
        
    Returns:
        List of profile dicts if a directory is found, otherwise None.
    """
    profiles = []
    try:
        # Only look for actual save files here.
        saves_dir = get_sameboy_saves_path(executable_path) 

        if saves_dir is None:
            log.info("get_sameboy_saves_path returned None. User prompt for ROM directory is likely needed.")
            return None # Segnala che bisogna chiedere all'utente
        
        if not os.path.isdir(saves_dir):
            log.warning(f"Determined SameBoy directory '{saves_dir}' is not a valid directory. No profiles found.")
            return [] # Directory non valida, restituisce lista vuota

        save_files = glob.glob(os.path.join(saves_dir, "*.sav")) + glob.glob(os.path.join(saves_dir, "*.srm"))

        if not save_files:
            # Check for save files in subdirectories
            for root, _, files in os.walk(saves_dir):
                for file in files:
                    if file.lower().endswith(('.sav', '.srm')):
                        save_files.append(os.path.join(root, file))
                        
            # If we still don't have any save files, create profiles from ROM files instead
            if not save_files:
                log.info(f"No .sav or .srm files found in '{saves_dir}' or its subdirectories. Creating profiles from ROM files.")
                rom_files = []
                for root, _, files in os.walk(saves_dir):
                    for file in files:
                        if file.lower().endswith(('.gb', '.gbc')):
                            rom_files.append(os.path.join(root, file))
                
                if rom_files:
                    log.info(f"Found {len(rom_files)} ROM files in '{saves_dir}' and its subdirectories.")
                    # Create profiles from ROM files
                    for file_path in rom_files:
                        if os.path.isfile(file_path):
                            # Use the filename without extension as both ID and Name
                            base_name = os.path.splitext(os.path.basename(file_path))[0]
                            profile_id = base_name  # Keep full name for ID
                            
                            # Clean the name for display by removing trailing language codes
                            profile_name = re.sub(r'\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$', '', base_name).strip()
                            if not profile_name:
                                profile_name = base_name
                            
                            # Create a profile with the ROM path (no save file yet)
                            profile = {
                                'id': profile_id,
                                'name': profile_name,
                                'paths': [file_path]  # Using ROM path since no save exists yet
                            }
                            profiles.append(profile)
                            log.debug(f"  Added SameBoy ROM profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")
                    
                    if profiles:
                        log.info(f"Created {len(profiles)} profiles from ROM files in '{saves_dir}'.")
                        return profiles
                    
                # If we still don't have any profiles, signal for user prompt
                log.info(f"No ROM files found in '{saves_dir}'. Signalling for user prompt.")
                return None # Restituisce None per attivare il prompt utente

        game_names_processed = set() # Per evitare duplicati basati solo sull'estensione

        for file_path in save_files:
            if os.path.isfile(file_path):
                # Use the filename without extension as both ID and Name initially
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                profile_id = base_name  # Keep full name for ID
                
                # Clean the name for display by removing trailing language codes like (En,Fr,De,...)
                profile_name = re.sub(r'\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$', '', base_name).strip()
                # If cleaning didn't change anything (maybe different pattern), use original
                if not profile_name:
                    profile_name = base_name
                
                profile = {
                    'id': profile_id,
                    'name': profile_name,  # Use the cleaned name for display
                    'paths': [file_path]  # Standard format with list of paths
                }
                profiles.append(profile)
                log.debug(f"  Added SameBoy profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")
    
    except OSError as e:
        log.error(f"Error accessing SameBoy saves directory '{saves_dir}': {e}")
        return None 
    except Exception as e:
        log.error(f"Unexpected error finding SameBoy profiles: {e}", exc_info=True)
        return None 
    
    log.info(f"Found {len(profiles)} SameBoy profiles in directory '{saves_dir}'.")
    return profiles

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    found_profiles = find_sameboy_profiles()
    if found_profiles:
        print("Found SameBoy Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print("No SameBoy profiles found in standard directory.")