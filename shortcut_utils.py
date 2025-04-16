# shortcut_utils.py
# -*- coding: utf-8 -*-

import os
import sys
import logging
import re
from gui_utils import resource_path
from core_logic import sanitize_foldername

# Importa winshell SOLO se su Windows
try:
    import winshell
    from win32com.client import Dispatch # Necessario per alcuni metodi winshell
    WINSHELL_AVAILABLE = True
except ImportError:
    WINSHELL_AVAILABLE = False
    logging.warning("Library 'winshell' or 'pywin32' not found. Shortcut creation disabled on Windows.")

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

# Funzione principale per creare lo shortcut (Versione Finale per Script e EXE)
def create_backup_shortcut(profile_name):
    """
    Crea un collegamento sul desktop per eseguire il backup di un profilo.
    Funziona sia eseguendo lo script .py sia l'eseguibile .exe pacchettizzato.
    """
    if not WINSHELL_AVAILABLE:
        msg = "Librerie necessarie (winshell, pywin32) non trovate per creare collegamenti."
        logging.error(msg)
        return False, msg

    try:
        # --- 1. Prepara i percorsi e i nomi ---
        logging.debug("Phase 1: Preparing paths...")
        desktop_path = winshell.desktop()
        if not desktop_path or not os.path.isdir(desktop_path):
             logging.error("Unable to find Desktop folder.")
             return False, "Unable to find Desktop folder."
        safe_link_name = sanitize_shortcut_filename(profile_name)
        link_filepath = os.path.join(desktop_path, f"Backup - {safe_link_name}.lnk")
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

        # --- 4. Crea e configura l'oggetto shortcut ---
        logging.debug("Phase 4: Creating WScript.Shell object...")
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(link_filepath)
        logging.debug("Phase 4: Setting shortcut properties...")
        shortcut.Targetpath = target_exe
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = working_dir
        shortcut.Description = f"Esegue il backup Game Saver per il profilo '{profile_name}'"

        # --- 5. Trova e imposta l'icona specifica (o fallback) ---
        logging.debug("Phase 5: Searching and setting icon...")
        # (Il blocco per trovare icon_location_string e impostare shortcut.IconLocation rimane identico a prima)
        icon_location_string = None
        try:
            icon_relative_path = os.path.join("icons", "SaveStateIconBK.ico")
            icon_absolute_path = resource_path(icon_relative_path)
            if not os.path.exists(icon_absolute_path):
                logging.error(f"Specific shortcut icon NOT FOUND in: {icon_absolute_path}")
                icon_location_string = f"{target_exe},0"
                logging.warning(f"Use fallback icon from the executable: {icon_location_string}")
            else:
                icon_location_string = f"{icon_absolute_path},0"
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

        # --- 6. Salva lo shortcut ---
        logging.debug("Phase 6: Attempting to save shortcut...")
        shortcut.save()
        logging.debug("Phase 6: Shortcut save completed.")

        msg = f"Collegamento per '{profile_name}' creato con successo sul desktop."
        logging.info(msg)
        return True, msg

    except Exception as e:
        # ... (Blocco except migliorato come prima) ...
        logging.error(f"Error in create_backup_shortcut function for '{profile_name}': {type(e).__name__} - {e}", exc_info=True)
        error_message = f"Shortcut creation error: {type(e).__name__}."
        if isinstance(e, AttributeError) and 'Dispatch' in str(e):
             error_message = f"Shortcut creation error: missing dependency (pywin32?).\n{e}"
        else:
             error_message = f"Shortcut creation error: {e}"
        return False, error_message