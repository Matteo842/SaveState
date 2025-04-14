# shortcut_utils.py
# -*- coding: utf-8 -*-

import os
import sys
import logging
import re
from gui_utils import resource_path

# Importa winshell SOLO se su Windows
try:
    import winshell
    from win32com.client import Dispatch # Necessario per alcuni metodi winshell
    WINSHELL_AVAILABLE = True
except ImportError:
    WINSHELL_AVAILABLE = False
    logging.warning("Libreria 'winshell' o 'pywin32' non trovata. Creazione shortcut disabilitata su Windows.")


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

# Funzione principale per creare lo shortcut
def create_backup_shortcut(profile_name):
    """
    Crea un collegamento sul desktop per eseguire il backup di un profilo.
    Trova backup_runner.py e l'icona usando resource_path.
    Richiede winshell e pywin32 su Windows.

    Args:
        profile_name (str): Nome del profilo.

    Returns:
        tuple[bool, str]: (Successo, Messaggio)
    """
    if not WINSHELL_AVAILABLE:
        msg = "Librerie necessarie (winshell, pywin32) non trovate per creare collegamenti."
        logging.error(msg)
        return False, msg

    try:
        # --- 1. Prepara i percorsi e i nomi ---
        desktop_path = winshell.desktop()
        if not desktop_path or not os.path.isdir(desktop_path):
             logging.error("Impossibile trovare la cartella Desktop.")
             return False, "Impossibile trovare la cartella Desktop."

        safe_link_name = sanitize_shortcut_filename(profile_name)
        link_filepath = os.path.join(desktop_path, f"Backup - {safe_link_name}.lnk")
        logging.info(f"Creazione collegamento in: '{link_filepath}'")

        # --- 2. Trova lo script runner usando resource_path ---
        try:
            runner_script_path = resource_path("backup_runner.py")
            logging.debug(f"Percorso script runner trovato da resource_path: {runner_script_path}")
            if not os.path.exists(runner_script_path):
                 logging.error(f"Script 'backup_runner.py' NON TROVATO nel percorso atteso del bundle: {runner_script_path}. Verifica il file .spec!")
                 raise FileNotFoundError(f"backup_runner.py not found at {runner_script_path}")
        except Exception as e_path:
            logging.error(f"Errore nel determinare il percorso dello script runner 'backup_runner.py': {e_path}", exc_info=True)
            msg = f"Impossibile determinare/trovare lo script ('backup_runner.py') necessario per lo shortcut.\nVerifica che sia incluso nella build.\n({e_path})"
            return False, msg

        # --- 3. Trova l'eseguibile Python (preferibilmente pythonw.exe) ---
        python_exe = sys.executable
        pythonw_exe = os.path.join(os.path.dirname(python_exe), 'pythonw.exe')
        target_exe = pythonw_exe if os.path.exists(pythonw_exe) else python_exe
        if target_exe == python_exe:
            logging.warning("pythonw.exe non trovato, uso python.exe (potrebbe apparire una console).")
        logging.debug(f"Eseguibile target per shortcut: {target_exe}")

        # --- 4. Prepara argomenti e directory di lavoro ---
        quoted_script_path = f'"{runner_script_path}"'
        quoted_profile_name = f'"{profile_name}"'
        arguments = f'{quoted_script_path} --backup {quoted_profile_name}'
        working_dir = os.path.dirname(runner_script_path) # Directory dello script runner
        logging.debug(f"Argomenti shortcut: {arguments}")
        logging.debug(f"Directory lavoro shortcut: {working_dir}")

        # --- 5. Crea e configura l'oggetto shortcut ---
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(link_filepath)
        shortcut.Targetpath = target_exe
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = working_dir
        shortcut.Description = f"Esegue il backup Game Saver per il profilo '{profile_name}'"

        # --- 6. Trova e imposta l'icona specifica (o fallback) ---
        icon_location_string = None
        try:
            icon_relative_path = os.path.join("icons", "SaveStateIconBK.ico") # Icona specifica shortcut
            icon_absolute_path = resource_path(icon_relative_path)
            if not os.path.exists(icon_absolute_path):
                logging.error(f"Icona specifica per shortcut NON TROVATA in: {icon_absolute_path}")
                icon_location_string = f"{target_exe},0" # Fallback all'icona dell'eseguibile python/app
                logging.warning(f"Uso icona fallback dall'eseguibile: {icon_location_string}")
            else:
                icon_location_string = f"{icon_absolute_path},0" # Usa icona specifica trovata
        except Exception as e_icon_path:
            logging.error(f"Errore nel determinare il percorso dell'icona dello shortcut: {e_icon_path}", exc_info=True)
            icon_location_string = f"{target_exe},0" # Fallback
            logging.warning(f"Errore ricerca icona, uso icona fallback dall'eseguibile: {icon_location_string}")

        if icon_location_string:
            try:
                shortcut.IconLocation = icon_location_string
                logging.info(f"  Icona shortcut impostata su: {icon_location_string}")
            except Exception as e_icon_set:
                logging.warning(f"  Impossibile impostare l'icona ({icon_location_string}): {e_icon_set}")

        # --- 7. Salva lo shortcut ---
        shortcut.save()

        msg = f"Collegamento per '{profile_name}' creato con successo sul desktop."
        logging.info(msg)
        return True, msg

    except Exception as e: # Errore generico durante tutta l'operazione
        logging.error(f"Errore imprevisto creazione shortcut per '{profile_name}': {e}", exc_info=True)
        if isinstance(e, AttributeError) and 'Dispatch' in str(e):
             return False, f"Errore creazione shortcut: dipendenza mancante (pywin32?).\n{e}"
        return False, f"Errore imprevisto creazione shortcut.\n{e}"

        