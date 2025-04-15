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

# Gestore per File ('w' sovrascrive il log ad ogni esecuzione)
# --- Blocco FileHandler COMMENTATO ---
# # Gestore per File ('w' sovrascrive il log ad ogni esecuzione)
# try:
#     file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
#     file_handler.setFormatter(log_formatter)
#     root_logger.addHandler(file_handler) # <-- COMMENTATO ANCHE QUESTO
# except Exception as e_log_file:
#      print(f"ERRORE CRITICO: Impossibile creare/scrivere file di log {log_file}: {e_log_file}")
# --- FINE Blocco FileHandler COMMENTATO ---

# Gestore per Console (Lo teniamo, utile se eseguiamo backup_runner.py manualmente da cmd)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

logging.info("--- Avvio Backup Runner (Solo Log Console) ---")
# logging.info(f"Logging configurato per File ('{log_file}') e Console.") # Commentato/Rimosso
logging.info("Logging configurato per Console.") # Nuovo messaggio
logging.info(f"Argomenti ricevuti: {' '.join(sys.argv)}")
# --- FINE Logging ---

# --- Funzione per Notifica ---
def show_notification(success, message):
    """
    Mostra una notifica popup personalizzata usando Qt.
    """
    logging.debug(">>> Entrato in show_notification <<<")
    # Se PySide6 non è disponibile, logga soltanto
    if not QT_AVAILABLE:
         log_level = logging.INFO if success else logging.ERROR
         logging.log(log_level, f"BACKUP RESULT (GUI Notification Unavailable): {message}")
         logging.debug("QT not available, exit from show_notification.")
         return

    app = None # Inizializza app a None
    try:
        logging.debug("Controllo/Creo QApplication...")
        app = QApplication.instance()
        needs_exec = False # Rinominato da needs_exec a needs_quit_timer
        created_app = False # Flag per sapere se abbiamo creato noi l'app
        if app is None:
            logging.debug("Nessuna QApplication esistente, ne creo una nuova.")
            app_args = sys.argv if hasattr(sys, 'argv') and sys.argv else ['backup_runner']
            app = QApplication(app_args)
            created_app = True # Abbiamo creato l'app
        else:
             logging.debug("QApplication già esistente trovata.")

        # ... (codice per caricare tema e creare popup, rimane uguale) ...
        logging.debug("Carico impostazioni per tema...")
        try:
            settings, _ = settings_manager.load_settings()
            theme = settings.get('theme', 'dark')
            qss = config.DARK_THEME_QSS if theme == 'dark' else config.LIGHT_THEME_QSS
            logging.debug(f"Tema caricato: {theme}")
        except Exception as e_set:
             logging.error(f"Unable to load settings/theme for notification: {e_set}", exc_info=True)
             qss = "" # Fallback a stile vuoto

        logging.debug("Creo NotificationPopup...")
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
    save_path = profiles[profile_name]
    backup_base_dir = settings.get("backup_base_dir")
    max_bk = settings.get("max_backups")
    max_src_size = settings.get("max_source_size_mb")
    compression_mode = settings.get("compression_mode", "standard")
    # Aggiungiamo anche il check spazio qui? Forse sì per coerenza.
    check_space = settings.get("check_free_space_enabled", True)
    min_gb_required = config.MIN_FREE_SPACE_GB

    # Validazione dati recuperati
    if not backup_base_dir or max_bk is None or max_src_size is None:
         logging.error("Required settings (base path, max backup, max source size) invalid.")
         show_notification(False, "Error: Invalid backup settings.")
         return False
    if not save_path or not os.path.isdir(save_path):
         logging.error(f"Savings path for '{profile_name}' invalid: '{save_path}'")
         show_notification(False, f"Error: Invalid save path for {profile_name}.")
         return False

    # 5. (Opzionale ma Consigliato) Controllo Spazio Libero
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
        success, message = core_logic.perform_backup(
            profile_name,
            save_path,
            backup_base_dir,
            max_bk,
            max_src_size,
            compression_mode
        )
        logging.info(f"Result perform_backup: Success={success}, Message='{message}'")
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