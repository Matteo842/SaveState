# backup_runner.py
# -*- coding: utf-8 -*-

import argparse
import sys
import os
import logging
import re

# Importa i moduli necessari per caricare dati ed eseguire backup
# Assumiamo che questi file siano trovabili (nella stessa cartella o nel python path)
# Import specifici per la notifica Qt
try:
    from PySide6.QtWidgets import QApplication # Serve anche solo per la notifica
    from PySide6.QtGui import QScreen     # Per posizionare la notifica
    from PySide6.QtCore import QTimer       # QTimer è usato dentro NotificationPopup
    QT_AVAILABLE = True
except ImportError as e_qt:
     QT_AVAILABLE = False
     logging.error(f"PySide6 not found, unable to show GUI notifications: {e_qt}")

# Importa i nostri moduli
try:
    import core_logic
    import settings_manager
    import config # Serve per caricare il QSS giusto
    from gui_utils import NotificationPopup # <-- Importa la nuova classe
except ImportError as e_mod:
    logging.error(f"Error importing modules ({e_mod}).")
    sys.exit(1)



# --- Funzione per Notifica ---
def show_notification(success, message):
    """
    Mostra una notifica popup personalizzata usando Qt.
    """
    logging.debug(">>> Entered show_notification <<<")
    # Se PySide6 non è disponibile, logga soltanto
    if not QT_AVAILABLE:
         log_level = logging.INFO if success else logging.ERROR
         logging.log(log_level, f"BACKUP RESULT (GUI Notification Unavailable): {message}")
         logging.debug("QT not available, exit from show_notification.")
         return

    app = None # Inizializza app a None
    try:
        logging.debug("Checking/Creating QApplication...")
        app = QApplication.instance()
        needs_exec = False # Rinominato da needs_exec a needs_quit_timer
        created_app = False # Flag per sapere se abbiamo creato noi l'app
        if app is None:
            logging.debug("No existing QApplication found, creating a new one.")
            app_args = sys.argv if hasattr(sys, 'argv') and sys.argv else ['backup_runner']
            app = QApplication(app_args)
            created_app = True # Abbiamo creato l'app
        else:
             logging.debug("Existing QApplication found.")

        # ... (codice per caricare tema e creare popup, rimane uguale) ...
        logging.debug("Loading theme settings...")
        try:
            settings, _ = settings_manager.load_settings()
            theme = settings.get('theme', 'dark')
            qss = config.DARK_THEME_QSS if theme == 'dark' else config.LIGHT_THEME_QSS
            logging.debug(f"Theme loaded: {theme}")
        except Exception as e_set:
             logging.error(f"Unable to load settings/theme for notification: {e_set}", exc_info=True)
             qss = "" # Fallback a stile vuoto

        logging.debug("Creating NotificationPopup...")
        title = "Backup Completato" if success else "Errore Backup"
        clean_message = re.sub(r'\n+', '\n', message).strip()

        try:
            popup = NotificationPopup(title, clean_message, success)
            # Impostiamo il QSS *prima* di adjustSize e show per coerenza
            logging.debug("Applico QSS...")
            try:
                 popup.setStyleSheet(qss)
            except Exception as e_qss:
                 logging.error(f"QSS application error at notification: {e_qss}", exc_info=True)

            popup.adjustSize() # Calcola dimensione dopo QSS
            logging.debug(f"Dimensione popup calcolata: {popup.size()}")

            # Calcolo posizione (rimane uguale)
            logging.debug("Calcolo posizione...")
            # ... (codice per calcolare popup_x, popup_y) ...
            primary_screen = QApplication.primaryScreen()
            if primary_screen:
                 screen_geometry = primary_screen.availableGeometry()
                 margin = 15
                 popup_x = screen_geometry.width() - popup.width() - margin
                 popup_y = screen_geometry.height() - popup.height() - margin
                 popup.move(popup_x, popup_y)
                 logging.debug(f"Posiziono notifica a: ({popup_x}, {popup_y})")
            else:
                 logging.warning("Schermo primario non trovato, impossibile posizionare notifica.")

        except Exception as e_popup_create:
             logging.error(f"Error while creating NotificationPopup: {e_popup_create}", exc_info=True)
             # Se non possiamo creare il popup, forse è meglio uscire?
             # Oltre a loggare, potremmo provare a chiudere l'app se l'abbiamo creata noi.
             if created_app and app:
                 app.quit()
             return # Esce se non possiamo creare il popup

        # Mostra il popup
        logging.debug("Mostro popup...")
        popup.show()

        # Se abbiamo creato noi l'applicazione Qt, impostiamo un timer per chiuderla
        # poco dopo che il popup dovrebbe essersi chiuso da solo.
        if created_app and app:
            popup_duration_ms = 6000 # Durata del popup (deve corrispondere a quella in NotificationPopup)
            quit_delay_ms = popup_duration_ms + 500 # Aggiungi mezzo secondo di margine
            logging.debug(f"Imposto QTimer per chiamare app.quit() tra {quit_delay_ms} ms.")
            QTimer.singleShot(quit_delay_ms, app.quit)
            # Avvia l'event loop, ma ora uscirà automaticamente grazie al timer
            logging.debug("Avvio app.exec() per notifica (con timer di uscita)...")
            app.exec()
            logging.debug("Uscito da app.exec() dopo timer o chiusura manuale popup.")
        else:
            logging.debug("QApplication preesistente, non avvio exec/timer qui. Mostro solo popup.")

    except Exception as e_main_show:
        logging.critical(f"Errore critico in show_notification: {e_main_show}", exc_info=True)
        # Prova a chiudere l'app se l'abbiamo creata noi e c'è stato un errore grave
        if created_app and app:
            app.quit()

    logging.debug("<<< Uscito da show_notification >>>")


# --- Funzione Principale Esecuzione Silenziosa ---
def run_silent_backup(profile_name):
    """
    Esegue la logica di backup per un dato profilo senza GUI.
    Restituisce True se successo, False altrimenti.
    """
    logging.info(f"Avvio backup silenzioso per il profilo: '{profile_name}'")

    # 1. Carica Impostazioni
    try:
        settings, _ = settings_manager.load_settings()
        if not settings: # Gestisce caso raro in cui load_settings restituisca None
             logging.error("Unable to load settings.")
             show_notification(False, "Error loading settings.")
             return False
    except Exception as e:
        logging.error(f"Critical error during loading settings: {e}", exc_info=True)
        show_notification(False, f"Critical settings error: {e}")
        return False

    # 2. Carica Profili
    try:
        profiles = core_logic.load_profiles()
    except Exception as e:
        logging.error(f"Critical error during profile loading: {e}", exc_info=True)
        show_notification(False, f"Errore critico profili: {e}")
        return False

    # 3. Verifica Esistenza Profilo
    if profile_name not in profiles:
        logging.error(f"Profile '{profile_name}' not found in '{config.PROFILE_FILE}'. Backup cancelled.")
        show_notification(False, f"Profile not found: {profile_name}")
        return False

    # 4. Recupera Dati Necessari
    profile_data = profiles.get(profile_name) # Ottieni il DIZIONARIO del profilo
    if not profile_data or not isinstance(profile_data, dict):
        # Se non troviamo un dizionario valido
        logging.error(f"Dati profilo non validi per '{profile_name}' in backup_runner. Backup annullato.")
        show_notification(False, f"Errore: Dati profilo non validi per {profile_name}.")
        return False

    # --- MODIFICA: Gestione 'paths' (lista) e 'path' (stringa) ---
    paths_to_backup = None
    if 'paths' in profile_data and isinstance(profile_data['paths'], list):
        paths_to_backup = profile_data['paths']
        logging.debug(f"Trovata chiave 'paths' (lista) per '{profile_name}': {paths_to_backup}")
    elif 'path' in profile_data and isinstance(profile_data['path'], str):
        paths_to_backup = [profile_data['path']] # Metti la stringa in una lista
        logging.debug(f"Trovata chiave 'path' (stringa) per '{profile_name}': {paths_to_backup}")

    # Se nessuno dei due percorsi è valido o trovato
    if paths_to_backup is None or not paths_to_backup: # Controlla anche se la lista è vuota
        logging.error(f"Nessun percorso ('paths' o 'path') valido trovato per '{profile_name}'. Backup annullato.")
        # Mostra un messaggio più specifico all'utente
        show_notification(False, f"Errore: Nessun percorso di salvataggio valido definito per {profile_name}.")
        return False
    # A questo punto, paths_to_backup contiene una lista (potenzialmente di un solo elemento) di percorsi
    # La validazione effettiva dell'esistenza dei percorsi avverrà dentro perform_backup
    # --- FINE MODIFICA ---

    backup_base_dir = settings.get("backup_base_dir")
    max_bk = settings.get("max_backups")
    max_src_size = settings.get("max_source_size_mb")
    compression_mode = settings.get("compression_mode", "standard")
    check_space = settings.get("check_free_space_enabled", True)
    min_gb_required = config.MIN_FREE_SPACE_GB

    # Validazione altre impostazioni (il check su save_path è già stato fatto sopra)
    if not backup_base_dir or max_bk is None or max_src_size is None:
         logging.error("Impostazioni necessarie (percorso base, max backup, max dimensione sorgente) non valide in backup_runner.")
         show_notification(False, "Errore: Impostazioni backup non valide.")
         return False

    # Controllo Spazio Libero
    if check_space:
        logging.info(f"Checking free disk space (Min: {min_gb_required} GB)...")
        min_bytes_required = min_gb_required * 1024 * 1024 * 1024
        try:
            os.makedirs(backup_base_dir, exist_ok=True)
            # Importa shutil solo se necessario
            import shutil
            disk_usage = shutil.disk_usage(backup_base_dir)
            free_bytes = disk_usage.free
            if free_bytes < min_bytes_required:
                free_gb = free_bytes / (1024*1024*1024)
                msg = f"Insufficient disk space! Free: {free_gb:.2f} GB, Required: {min_gb_required} GB."
                logging.error(msg)
                show_notification(False, msg)
                return False
            logging.info("Space control passed.")
        except Exception as e_space:
            msg = f"Disk space check error: {e_space}"
            logging.error(msg, exc_info=True)
            show_notification(False, msg)
            return False

    # 6. Esegui Backup Effettivo
    logging.info(f"Start core_logic.perform_backup for '{profile_name}'...")
    try:
        logging.debug(f"--->>> PRE-CALLING core_logic.perform_backup for '{profile_name}'")
        logging.debug(f"      Arguments: paths={paths_to_backup}, max_backups={max_bk}, backup_dir={backup_base_dir}, compression={compression_mode}")

        # --- MANUAL PRE-VALIDATION IN BACKUP_RUNNER --- 
        log.debug("--- Performing manual pre-validation in backup_runner ---")
        pre_validation_ok = True
        if not paths_to_backup: # Check if list is empty
             log.error(f"  MANUAL PRE-VALIDATION FAILED: paths_to_backup is empty for profile '{profile_name}'")
             pre_validation_ok = False
        else:
            for p_idx, p_val in enumerate(paths_to_backup):
                try:
                    # Ensure p_val is a string before checking
                    if not isinstance(p_val, str):
                        log.error(f"  MANUAL PRE-VALIDATION ERROR: Path item {p_idx} is not a string: {p_val} ({type(p_val).__name__})")
                        pre_validation_ok = False
                        continue
                        
                    exists = os.path.exists(p_val)
                    is_file = os.path.isfile(p_val)
                    is_dir = os.path.isdir(p_val)
                    log.debug(f"  Pre-check [{p_idx+1}/{len(paths_to_backup)}] '{p_val}' -> exists={exists}, is_file={is_file}, is_dir={is_dir}")
                    if not exists:
                        pre_validation_ok = False
                        log.error(f"  MANUAL PRE-VALIDATION FAILED for path: {p_val}")
                except Exception as e_preval:
                    log.error(f"  MANUAL PRE-VALIDATION EXCEPTION for path '{p_val}': {e_preval}")
                    pre_validation_ok = False
        log.debug(f"--- Manual pre-validation result: {pre_validation_ok} ---")
        # --------------------------------------------------

        success, message = core_logic.perform_backup(
            profile_name,
            paths_to_backup, # <<< USA LA NUOVA VARIABILE QUI
            backup_base_dir,
            max_bk,
            max_src_size,
            compression_mode
        )
        logging.debug(f"<<<--- POST-CALL core_logic.perform_backup for '{profile_name}'")
        logging.debug(f"      Result: success={success}, error_message='{message}'")

        # 7. Mostra Notifica
        show_notification(success, message)
        return success
    except Exception as e_backup:
         # Errore imprevisto DENTRO perform_backup non gestito? Logghiamolo qui.
         logging.error(f"Unexpected error during execution core_logic.perform_backup: {e_backup}", exc_info=True)
         show_notification(False, f"Unexpected backup error: {e_backup}")
         return False


# --- Blocco Esecuzione Principale dello Script Runner ---
if __name__ == "__main__":
    
    # --- Configurazione Logging (Runner con File) ---
    # Imposta il percorso del file di log nella stessa cartella dello script
    try:
        log_file_dir = os.path.dirname(os.path.abspath(__file__)) # Cartella dello script corrente
    except NameError:
        log_file_dir = os.getcwd() # Fallback se __file__ non è definito
    log_file = os.path.join(log_file_dir, "backup_runner.log")

    log_level = logging.INFO # USIAMO DEBUG per catturare tutto ora!
    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    log_datefmt = '%Y-%m-%d %H:%M:%S'
    log_formatter = logging.Formatter(log_format, log_datefmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Rimuovi vecchi handler se presenti
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # Gestore per Console (Lo teniamo, utile se eseguiamo backup_runner.py manualmente da cmd)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    logging.info("--- Starting Backup Runner (Console Log Only) ---")
    # logging.info(f"Logging configurato per File ('{log_file}') e Console.") # Commentato/Rimosso
    logging.info("Logging configured for Console.") # Nuovo messaggio
    logging.info(f"Received arguments: {' '.join(sys.argv)}")
    # --- FINE Logging ---

    parser = argparse.ArgumentParser(description="Esegue il backup per un profilo specifico di Game Saver.")
    parser.add_argument("--backup", required=True, help="Nome del profilo per cui eseguire il backup.")
    # Potremmo aggiungere altri argomenti in futuro (es. --force per sovrascrivere, ecc.)

    try:
        args = parser.parse_args()
        profile_to_backup = args.backup
        logging.info(f"Received argument --backup '{profile_to_backup}'")

        # Esegui la funzione principale
        backup_success = run_silent_backup(profile_to_backup)

        # Esci con codice appropriato (0 = successo, 1 = fallimento)
        sys.exit(0 if backup_success else 1)

    except SystemExit as e:
         # argparse esce con SystemExit (codice 2) se gli argomenti sono sbagliati
         # Lascia che esca normalmente in quel caso, o logga se preferisci
         if e.code != 0:
              logging.error(f"Error in arguments or required output. Code: {e.code}")
         sys.exit(e.code) # Propaga il codice di uscita
    except Exception as e_main:
         # Errore generico non catturato prima
         logging.critical(f"Fatal error in backup_runner: {e_main}", exc_info=True)
         # Prova a mostrare una notifica anche per errori fatali?
         show_notification(False, f"Fatal mistake: {e_main}")
         sys.exit(1)