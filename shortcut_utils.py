# shortcut_utils.py
# -*- coding: utf-8 -*-

import os
import sys
import logging
import re
import platform
import shutil
from utils import resource_path
from core_logic import sanitize_foldername

# Determina il sistema operativo
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'

# Importa winshell SOLO se su Windows
WINSHELL_AVAILABLE = False
if IS_WINDOWS:
    try:
        import winshell
        from win32com.client import Dispatch # Necessario per alcuni metodi winshell
        WINSHELL_AVAILABLE = True
    except ImportError:
        logging.warning("Library 'winshell' or 'pywin32' not found. Shortcut creation disabled on Windows.")

# Supporto per desktop file su Linux
LINUX_DESKTOP_SUPPORT = False
if IS_LINUX:
    try:
        # Non sono necessarie librerie aggiuntive per creare .desktop files
        LINUX_DESKTOP_SUPPORT = True
        logging.info("Linux desktop file support enabled.")
    except Exception as e:
        logging.warning(f"Error initializing Linux desktop file support: {e}")

PROFILE_NAME_STRIP_LIST = [
    '.exe',
    'play',
    'start',
    'launch',
    'launcher',
    'game',
    # Aggiungi qui altre parole se serve
]

_PROFILE_NAME_STRIP_REGEX = re.compile(
    r'\s*\b(' + '|'.join(re.escape(word) for word in PROFILE_NAME_STRIP_LIST if word != '.exe') + r')\b\s*|' +
    r'\s*' + re.escape('.exe') + r'\s*',
    re.IGNORECASE
)

def sanitize_profile_name(name: str) -> str:
    """Pulisce un nome profilo da parole comuni e caratteri non validi."""
    if not name:
        return ""

    # 1. Rimuove le parole dalla lista PROFILE_NAME_STRIP_LIST
    cleaned_name = _PROFILE_NAME_STRIP_REGEX.sub(' ', name)

    # 2. Pulisce spazi extra
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()

    # 3. Rimuove caratteri non validi usando la funzione esistente
    #    (ora usa il nome corretto!)
    sanitized_name = sanitize_foldername(cleaned_name)

    return sanitized_name

# Funzione helper per pulire il nome file del collegamento
def sanitize_shortcut_filename(name):
    """Rimuove caratteri non validi per un nome file, mantenendo spazi/underscore/trattini."""
    # Rimuovi caratteri non permessi in nomi file Windows
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Rimuovi spazi iniziali/finali
    safe_name = name.strip()
    # Limita lunghezza se necessario (opzionale)
    # MAX_LEN = 50
    # if len(safe_name) > MAX_LEN:
    #     safe_name = safe_name[:MAX_LEN] + '...'
    if not safe_name:
        safe_name = "profilo_backup" # Nome di fallback
    return safe_name

def is_packaged():
    """ Controlla se stiamo girando da un eseguibile PyInstaller. """
    # Questi attributi vengono impostati da PyInstaller
    return hasattr(sys, 'frozen') or hasattr(sys, '_MEIPASS')

def ensure_persistent_icon():
    """
    Ensures the shortcut icon is available at a persistent path.
    
    In script mode: returns the original resource path.
    In packaged mode: copies the icon from the temporary _MEIPASS folder
    to a persistent location inside <backup_base_dir>/.savestate/icons/
    and returns that persistent path.
    
    This is necessary because PyInstaller OneFile extracts files to a
    temporary folder that gets deleted when the exe exits, causing
    shortcuts to lose their icons.
    
    Returns:
        str: Path to the icon file, or None if not found/failed.
    """
    icon_relative_path = os.path.join("icons", "SaveStateIconBK.ico")
    icon_source = resource_path(icon_relative_path)
    
    # In script mode, use the original path directly
    if not is_packaged():
        if os.path.exists(icon_source):
            return icon_source
        logging.warning(f"Shortcut icon not found at: {icon_source}")
        return None
    
    # In packaged mode, we need to copy the icon to a persistent location
    # Use the backup directory's .savestate folder (works with portable mode too)
    try:
        import settings_manager
        import config
        
        settings, _ = settings_manager.load_settings()
        backup_base_dir = settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        
        if not backup_base_dir:
            logging.error("Cannot determine backup_base_dir for persistent icon storage.")
            return None
        
        # Target: <backup_base_dir>/.savestate/icons/SaveStateIconBK.ico
        savestate_folder = os.path.join(backup_base_dir, ".savestate")
        icons_folder = os.path.join(savestate_folder, "icons")
        persistent_icon_path = os.path.join(icons_folder, "SaveStateIconBK.ico")
        
        # If icon already exists at persistent location, use it
        if os.path.exists(persistent_icon_path):
            logging.debug(f"Using existing persistent icon: {persistent_icon_path}")
            return persistent_icon_path
        
        # Copy icon from temporary _MEIPASS to persistent location
        if os.path.exists(icon_source):
            try:
                os.makedirs(icons_folder, exist_ok=True)
                shutil.copy2(icon_source, persistent_icon_path)
                logging.info(f"Shortcut icon copied to persistent location: {persistent_icon_path}")
                return persistent_icon_path
            except Exception as e:
                logging.error(f"Failed to copy icon to persistent location: {e}")
                return None
        else:
            logging.warning(f"Source icon not found in bundle: {icon_source}")
            return None
            
    except Exception as e:
        logging.error(f"Error in ensure_persistent_icon: {e}", exc_info=True)
        return None

# Funzione principale per creare lo shortcut (Versione Finale per Script e EXE)
def get_desktop_path():
    """
    Restituisce il percorso della directory del desktop in modo cross-platform.
    """
    if IS_WINDOWS and WINSHELL_AVAILABLE:
        return winshell.desktop()
    elif IS_LINUX:
        # Su Linux, il desktop è tipicamente in ~/Desktop o nella versione localizzata
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        # Prova anche la versione localizzata se quella inglese non esiste
        if not os.path.isdir(desktop_path):
            # Prova a ottenere il percorso localizzato tramite xdg-user-dir
            try:
                import subprocess
                result = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
                if result.returncode == 0:
                    desktop_path = result.stdout.strip()
                    logging.info(f"Found localized desktop path: {desktop_path}")
            except Exception as e:
                logging.warning(f"Error getting localized desktop path: {e}")
        return desktop_path
    else:
        # Fallback generico per altri sistemi operativi
        return os.path.join(os.path.expanduser("~"), "Desktop")

def create_backup_shortcut(profile_name):
    """
    Crea un collegamento sul desktop per eseguire il backup di un profilo.
    Funziona sia eseguendo lo script .py sia l'eseguibile .exe pacchettizzato.
    Supporta sia Windows (.lnk) che Linux (.desktop).
    """
    if IS_WINDOWS and not WINSHELL_AVAILABLE:
        msg = "Librerie necessarie (winshell, pywin32) non trovate per creare collegamenti su Windows."
        logging.error(msg)
        return False, msg
    
    if IS_LINUX and not LINUX_DESKTOP_SUPPORT:
        msg = "Supporto per file .desktop non disponibile su questo sistema Linux."
        logging.error(msg)
        return False, msg

    try:
        # --- 1. Prepara i percorsi e i nomi ---
        logging.debug("Phase 1: Preparing paths...")
        desktop_path = get_desktop_path()
        if not desktop_path or not os.path.isdir(desktop_path):
             logging.error("Unable to find Desktop folder.")
             return False, "Unable to find Desktop folder."
        safe_link_name = sanitize_shortcut_filename(profile_name)
        
        # Crea il percorso del collegamento in base al sistema operativo
        if IS_WINDOWS:
            link_filepath = os.path.join(desktop_path, f"Backup - {safe_link_name}.lnk")
        else:  # Linux
            link_filepath = os.path.join(desktop_path, f"SaveState-Backup-{safe_link_name}.desktop")
        
        logging.info(f"Creating shortcut in: '{link_filepath}'")

        # --- 2. Trova lo script runner (serve sempre) ---
        logging.debug("Phase 2: Searching for runner script...")
        runner_script_path = "" # Inizializza
        try:
            runner_script_path = resource_path("backup_runner.py")
            if not os.path.exists(runner_script_path):
                 raise FileNotFoundError(f"backup_runner.py not found at {runner_script_path}")
            logging.info(f"Runner script path found: {runner_script_path}")
        except Exception as e_path:
            logging.error(f"Error in determining runner script path 'backup_runner.py': {e_path}", exc_info=True)
            msg = f"Unable to determine/find the script ('backup_runner.py') needed for the shortcut.\nVerify that it is included in the build.\n({e_path})"
            return False, msg

        # --- 3. Determina Target, Argomenti e Working Dir in base alla modalità ---
        logging.debug("Phase 3: Determining Target/Arguments/WorkingDir...")
        target_exe = ""
        arguments = ""
        working_dir = os.path.dirname(runner_script_path) # Directory comune sicura

        if is_packaged():
            # Modalità Pacchettizzata (.exe)
            logging.info("Packaged mode (exe) detected.")
            target_exe = sys.executable # L'eseguibile SaveState.exe stesso
            arguments = f'--backup "{profile_name}"' # Passa solo l'argomento che capisce __main__
            # working_dir può rimanere quella del runner o essere quella dell'exe
            working_dir = os.path.dirname(target_exe)
        else:
            # Modalità Script (.py)
            logging.info("Script mode (py) detected.")
            # Trova l'interprete pythonw.exe o python.exe
            python_exe = sys.executable
            pythonw_exe = os.path.join(os.path.dirname(python_exe), 'pythonw.exe')
            interpreter_exe = pythonw_exe if os.path.exists(pythonw_exe) else python_exe
            if interpreter_exe == python_exe:
                logging.warning("pythonw.exe not found, I use python.exe (a console might appear).")
            target_exe = interpreter_exe # L'interprete Python
            # L'interprete Python ha bisogno dello script runner come primo argomento
            arguments = f'"{runner_script_path}" --backup "{profile_name}"'

        logging.debug(f"  Target EXE: {target_exe}")
        logging.debug(f"  Argomenti: {arguments}")
        logging.debug(f"  Directory Lavoro: {working_dir}")

        # --- 4. Crea e configura il collegamento in base al sistema operativo ---
        if IS_WINDOWS:
            logging.debug("Phase 4: Creating WScript.Shell object...")
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(link_filepath)
            logging.debug("Phase 4: Setting shortcut properties...")
            shortcut.Targetpath = target_exe
            shortcut.Arguments = arguments
            shortcut.WorkingDirectory = working_dir
            shortcut.Description = f"Esegue il backup Game Saver per il profilo '{profile_name}'"
        else:  # Linux
            logging.debug("Phase 4: Creating Linux .desktop file...")
            # Crea il contenuto del file .desktop
            desktop_content = [
                "[Desktop Entry]",
                "Type=Application",
                f"Name=Backup {safe_link_name}",
                f"Comment=Esegue il backup Game Saver per il profilo '{profile_name}'",
                f"Exec={target_exe} {arguments}",
                f"Path={working_dir}",
                "Terminal=false",
                "Categories=Utility;"
            ]

        # --- 5. Trova e imposta l'icona specifica (o fallback) ---
        logging.debug("Phase 5: Searching and setting icon...")
        # Use ensure_persistent_icon() to get a stable path that survives exe termination
        icon_absolute_path = ensure_persistent_icon()
        
        if IS_WINDOWS:
            icon_location_string = None
            try:
                if not icon_absolute_path or not os.path.exists(icon_absolute_path):
                    logging.warning(f"Persistent shortcut icon not available, using fallback from executable")
                    icon_location_string = f"{target_exe},0"
                else:
                    icon_location_string = f"{icon_absolute_path},0"
                    logging.info(f"Using persistent icon path: {icon_absolute_path}")
            except Exception as e_icon_path:
                logging.error(f"Error in determining the path of the shortcut icon: {e_icon_path}", exc_info=True)
                icon_location_string = f"{target_exe},0"
                logging.warning(f"Icon search error, use fallback icon from executable: {icon_location_string}")

            if icon_location_string:
                try:
                    shortcut.IconLocation = icon_location_string
                    logging.info(f"  Shortcut icon set to: {icon_location_string}")
                except Exception as e_icon_set:
                    logging.warning(f"  Unable to set icon ({icon_location_string}): {e_icon_set}")
        else:  # Linux
            # Per Linux, aggiungi l'icona al file .desktop
            try:
                if icon_absolute_path and os.path.exists(icon_absolute_path):
                    # Su Linux, possiamo usare direttamente il percorso dell'icona
                    desktop_content.append(f"Icon={icon_absolute_path}")
                    logging.info(f"  Desktop file icon set to: {icon_absolute_path}")
                else:
                    # Cerca un'icona alternativa o usa un'icona di sistema
                    logging.warning(f"Persistent icon not available, using system icon")
                    desktop_content.append("Icon=document-save")
            except Exception as e_icon_set:
                logging.warning(f"  Unable to set icon for desktop file: {e_icon_set}")
                desktop_content.append("Icon=document-save")

        # --- 6. Salva il collegamento ---
        logging.debug("Phase 6: Attempting to save shortcut...")
        if IS_WINDOWS:
            shortcut.save()
            logging.debug("Phase 6: Windows shortcut save completed.")
        else:  # Linux
            # Scrivi il file .desktop
            try:
                with open(link_filepath, 'w') as desktop_file:
                    desktop_file.write('\n'.join(desktop_content))
                
                # Rendi il file .desktop eseguibile
                os.chmod(link_filepath, 0o755)
                logging.debug("Phase 6: Linux desktop file created and made executable.")
            except Exception as e_desktop:
                logging.error(f"Error creating desktop file: {e_desktop}", exc_info=True)
                return False, f"Error creating desktop file: {e_desktop}"

        if IS_WINDOWS:
            msg = f"Collegamento per '{profile_name}' creato con successo sul desktop."
        else:  # Linux
            msg = f"File desktop per '{profile_name}' creato con successo sul desktop."
        logging.info(msg)
        return True, msg

    except Exception as e:
        logging.error(f"Error in create_backup_shortcut function for '{profile_name}': {type(e).__name__} - {e}", exc_info=True)
        error_message = f"Shortcut creation error: {type(e).__name__}."
        
        if IS_WINDOWS:
            if isinstance(e, AttributeError) and 'Dispatch' in str(e):
                error_message = f"Shortcut creation error: missing dependency (pywin32?).\n{e}"
            else:
                error_message = f"Shortcut creation error: {e}"
        else:  # Linux
            error_message = f"Desktop file creation error: {e}"
            
        return False, error_message