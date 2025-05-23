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
            # Se saves_dir è stato fornito (cioè, get_sameboy_saves_path ha trovato una cartella, probabilmente con ROMs),
            # ma non ci sono file .sav o .srm, dobbiamo chiedere all'utente.
            log.info(f"No .sav or .srm files found in '{saves_dir}'. This path was likely identified due to ROMs. Signalling for user prompt.")
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