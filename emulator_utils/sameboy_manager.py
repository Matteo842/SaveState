# emulator_utils/sameboy_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import glob
import re

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())  # Avoid 'No handler found' warnings

def get_sameboy_saves_path():
    """
    Gets the SameBoy save directory based on platform.
    SameBoy typically stores save files (.sav) in the same directory as the ROM files.
    """
    # SameBoy non ha una cartella specifica per i salvataggi, ma li salva nella stessa cartella delle ROM
    # Dobbiamo cercare le cartelle delle ROM comuni
    
    system = platform.system()
    user_home = os.path.expanduser("~")
    
    # Definiamo le cartelle comuni delle ROM di Game Boy/Game Boy Color
    rom_paths = []
    
    if system == "Windows":
        # Percorsi comuni per ROM su Windows
        rom_paths = [
            # Percorsi standard per ROM
            os.path.join(user_home, "Documents", "ROMs", "GameBoy"),
            os.path.join(user_home, "Documents", "ROMs", "GameBoyColor"),
            os.path.join(user_home, "Documents", "ROMs", "GB"),
            os.path.join(user_home, "Documents", "ROMs", "GBC"),
            # Percorsi con lettera di unità
            "E:\\ROM\\GameBoyColor",  # Come mostrato nello screenshot
            "E:\\ROMs\\GameBoyColor",
            "E:\\ROM\\GameBoy",
            "E:\\ROMs\\GameBoy",
            "D:\\ROM\\GameBoyColor",
            "D:\\ROMs\\GameBoyColor",
            "D:\\ROM\\GameBoy",
            "D:\\ROMs\\GameBoy",
            "C:\\ROM\\GameBoyColor",
            "C:\\ROMs\\GameBoyColor",
            "C:\\ROM\\GameBoy",
            "C:\\ROMs\\GameBoy"
        ]
        
        # Aggiungi anche i percorsi di fallback
        fallback_paths = [
            os.path.join(os.getenv('APPDATA'), "SameBoy", "Saves"),
            os.path.join(os.getenv('LOCALAPPDATA'), "SameBoy", "Saves"),
            os.path.join(user_home, "Documents", "SameBoy", "Saves")
        ]
        rom_paths.extend(fallback_paths)
        
    elif system == "Darwin":  # macOS
        rom_paths = [
            os.path.join(user_home, "Documents", "ROMs", "GameBoy"),
            os.path.join(user_home, "Documents", "ROMs", "GameBoyColor"),
            os.path.join(user_home, "Documents", "ROMs", "GB"),
            os.path.join(user_home, "Documents", "ROMs", "GBC"),
            # Fallback
            os.path.join(user_home, "Library", "Application Support", "SameBoy", "Saves")
        ]
    elif system == "Linux":
        rom_paths = [
            os.path.join(user_home, "ROMs", "GameBoy"),
            os.path.join(user_home, "ROMs", "GameBoyColor"),
            os.path.join(user_home, "ROMs", "GB"),
            os.path.join(user_home, "ROMs", "GBC"),
            # Fallback
            os.path.join(user_home, ".local", "share", "SameBoy", "Saves"),
            os.path.join(user_home, ".config", "SameBoy", "Saves"),
            os.path.join(user_home, ".sameboy", "Saves")
        ]
    else:
        log.error(f"Unsupported operating system for SameBoy path detection: {system}")
        return None
    
    # Verifica se esiste almeno un file .sav in una delle cartelle delle ROM
    for path in rom_paths:
        if os.path.isdir(path):
            # Verifica se ci sono file .sav nella cartella
            save_files = glob.glob(os.path.join(path, "*.sav"))
            if save_files:
                log.info(f"Found SameBoy saves in ROM directory: {path}")
                return path
            else:
                log.debug(f"Directory exists but no .sav files found: {path}")
    
    # Se non troviamo cartelle con salvataggi, restituiamo la prima cartella ROM esistente
    # anche se non contiene salvataggi, in modo da poter comunque visualizzare la cartella
    for path in rom_paths:
        if os.path.isdir(path):
            log.info(f"No saves found, but returning valid ROM directory: {path}")
            return path
    
    # Se non troviamo nessuna cartella, restituiamo None
    log.warning(f"Could not find any valid ROM directories. Checked: {rom_paths}")
    return None

def find_sameboy_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds SameBoy save files (.sav) in the standard save directory.
    
    Args:
        executable_path: Optional path to the SameBoy executable, currently ignored.
        
    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'save_name', 'paths': [full_path]}, ...]
    """
    profiles = []
    log.info("Attempting to find SameBoy profiles in standard save directory...")
    
    saves_dir = get_sameboy_saves_path()
    if not saves_dir:
        log.warning("Could not determine or find standard SameBoy saves directory. No profiles found via this method.")
        return profiles  # Empty list
    
    try:
        # Look for .sav files in the saves directory
        search_pattern = os.path.join(saves_dir, "*.sav")
        save_files = glob.glob(search_pattern)
        
        # Also look for .srm files which are sometimes used for Game Boy saves
        search_pattern_srm = os.path.join(saves_dir, "*.srm")
        save_files.extend(glob.glob(search_pattern_srm))
        
        log.info(f"Found {len(save_files)} save files in {saves_dir}")
        
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
    except Exception as e:
        log.error(f"Unexpected error finding SameBoy profiles: {e}", exc_info=True)
    
    log.info(f"Found {len(profiles)} SameBoy profiles in standard directory.")
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
