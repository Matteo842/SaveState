# main.py
# -*- coding: utf-8 -*-
import sys
#import os
import logging
import argparse

# --- PySide6 Imports ---
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QSplashScreen
from PySide6.QtCore import QSharedMemory, Qt
from PySide6.QtGui import QPixmap
# from PySide6.QtGui import QDesktopServices # Rimosso perché non usato qui
# Aggiunto import per QtNetwork
from PySide6.QtNetwork import QLocalSocket, QLocalServer

# --- App Imports ---
import settings_manager
import backup_runner
from gui_utils import resource_path, QtLogHandler # Importa QtLogHandler e resource_path da gui_utils
from SaveState_gui import MainWindow # , ENGLISH_TRANSLATOR, CURRENT_TRANSLATOR # Importa da SaveState_gui
from SaveState_gui import SHARED_MEM_KEY, LOCAL_SERVER_NAME # Importa costanti

# --- NUOVO IMPORT ---
try:
    import pyi_splash  # type: ignore # Questo modulo esiste solo quando l'app è pacchettizzata con PyInstaller
except ImportError:
    pyi_splash = None # Imposta a None se non trovato (es. quando non si esegue da bundle)
# --- FINE NUOVO IMPORT ---

# --- Helper Function for Cleanup ---
def cleanup_instance_lock(local_server, shared_memory):
    """Closes the local server and releases the shared memory."""
    logging.debug("Executing instance cleanup (detach shared memory, close server)...")
    try:
        if local_server and local_server.isListening():
            local_server.close()
            logging.debug("Local server closed.")
        else:
            logging.debug("Local server was None or not listening.")
    except Exception as e_server:
        logging.error(f"Error closing local server: {e_server}")

    try:
        # Controlla se l'oggetto esiste ed è attached prima di detach
        if shared_memory and shared_memory.isAttached():
            if shared_memory.detach():
                logging.debug("Shared memory detached.")
            else:
                logging.error(f"Failed to detach shared memory: {shared_memory.errorString()}")
        elif shared_memory:
            logging.debug("Shared memory object exists but was not attached.")
        else:
            logging.debug("Shared memory object was None.")

    except Exception as e_mem:
        logging.error(f"Error detaching shared memory: {e_mem}")


# --- Main Execution Block ---
if __name__ == "__main__":
    # --- Configurazione Logging ---
    log_level = logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    log_datefmt = '%H:%M:%S'
    log_formatter = logging.Formatter(log_format, log_datefmt)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level) # Imposta livello sul root logger prima

    # Rimuovi handler esistenti se necessario (es. in PyInstaller)
    for handler in root_logger.handlers[:]:
        try:
            root_logger.removeHandler(handler)
            handler.close()
        except Exception as e_handler:
            logging.warning(f"Could not remove/close handler: {e_handler}") # Meno critico

    # Crea e aggiungi i nuovi handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO) # Livello handler console
    root_logger.addHandler(console_handler)

    # Handler Qt (logging nella GUI) - Ora importato
    qt_log_handler = QtLogHandler()
    qt_log_handler.setFormatter(log_formatter)
    qt_log_handler.setLevel(logging.INFO) # Livello handler Qt
    root_logger.addHandler(qt_log_handler)

    logging.info("Logging configured.")

    # --- Parsing Argomenti ---
    parser = argparse.ArgumentParser(description='SaveState GUI or Backup Runner.')
    parser.add_argument("--backup", help="Nome del profilo per cui eseguire un backup silenzioso.")
    args = parser.parse_args() # Gestisci eccezioni se necessario

    # --- Controllo Modalità Esecuzione ---
    if args.backup:
        # === Modalità Backup Silenzioso ===
        profile_to_backup = args.backup
        logging.info(f"Detected argument --backup '{profile_to_backup}'. Starting silent backup...")
        # Esegui direttamente la logica di backup (che ora include la notifica)
        try:
            backup_success = backup_runner.run_silent_backup(profile_to_backup)
            logging.info(f"Silent backup completed successfully: {backup_success}")
            sys.exit(0 if backup_success else 1) # Esci subito dopo il backup
        except Exception as e_backup:
            logging.critical(f"Error during silent backup for '{profile_to_backup}': {e_backup}", exc_info=True)
            sys.exit(1)

    else:
        # === Modalità GUI Normale ===
        logging.info("No --backup argument, starting GUI mode. Checking single instance...")

        # --- Logica Single Instance ---
        shared_memory = None # Inizializza a None
        local_socket = None
        local_server = None
        app_should_run = True # Flag per decidere se avviare la GUI

        try:
            shared_memory = QSharedMemory(SHARED_MEM_KEY)

            # Tenta di creare memoria condivisa. Se fallisce perché esiste già...
            if not shared_memory.create(1, QSharedMemory.AccessMode.ReadOnly):
                if shared_memory.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
                    logging.warning("Another instance of SaveState is already running. Attempting to activate it.")
                    app_should_run = False # Non avviare questa istanza GUI

                    # Connettiti all'altra istanza
                    local_socket = QLocalSocket()
                    local_socket.connectToServer(LOCAL_SERVER_NAME)
                    if local_socket.waitForConnected(500):
                        logging.info("Connected to existing instance. Sending 'show' signal.")
                        # Invia un segnale riconoscibile, es. 'show\n'
                        bytes_written = local_socket.write(b'show\n')
                        if bytes_written == -1:
                             logging.error(f"Failed to write to local socket: {local_socket.errorString()}")
                        elif not local_socket.waitForBytesWritten(500):
                             logging.warning("Timeout waiting for bytes written to local socket.")
                        else:
                             logging.debug("Signal 'show' sent successfully.")
                        local_socket.disconnectFromServer()
                        local_socket.close()
                        logging.info("Signal sent. Exiting this instance.")
                        # Rilascia la memoria condivisa (solo attaccata implicitamente)
                        if shared_memory.isAttached(): shared_memory.detach()
                        sys.exit(0) # Esci con successo (l'altra è stata attivata)
                    else:
                        logging.error(f"Unable to connect to existing instance server '{LOCAL_SERVER_NAME}': {local_socket.errorString()}")
                        # Uscire è più sicuro se non si riesce a comunicare
                        if shared_memory.isAttached(): shared_memory.detach()
                        sys.exit(1) # Esci con errore
                else:
                    # Altro errore con shared memory non recuperabile
                    logging.error(f"QSharedMemory fatal error (create): {shared_memory.errorString()}")
                    app_should_run = False # Non avviare la GUI
                    if shared_memory.isAttached(): shared_memory.detach() # Prova a pulire
                    sys.exit(1) # Esci con errore

            # Se arriva qui, la memoria è stata creata con successo (siamo la prima istanza)
            logging.debug(f"Shared memory segment '{SHARED_MEM_KEY}' created successfully.")

        except Exception as e_shmem_init:
            logging.critical(f"Unexpected error during SharedMemory initialization: {e_shmem_init}", exc_info=True)
            app_should_run = False
            if shared_memory and shared_memory.isAttached(): shared_memory.detach() # Prova a pulire
            sys.exit(1)


        # Se app_should_run è ancora True, siamo la prima istanza GUI
        if app_should_run:
            logging.info("First GUI instance. Starting application...")

            # --- Initialize QApplication and Splash Screen EARLY ---
            app = None # Inizializza a None
            splash = None # Inizializza splash a None
            try:
                app = QApplication(sys.argv)

                # === Splash Screen ===
                # Only show splash screen if running as a bundled executable
                # if getattr(sys, 'frozen', False):
                #     logging.debug("Creating and showing splash screen (frozen app)...")
                #     try:
                #         splash_image_path_relative = "SplashScreen/splash.png"
                #         splash_image_path_absolute = resource_path(splash_image_path_relative)
                #         logging.info(f"Attempting to load splash image from: {splash_image_path_absolute}") # Log del percorso calcolato

                #         splash_pixmap = QPixmap(splash_image_path_absolute)
                #         if splash_pixmap.isNull():
                #             logging.warning(f"QSplashScreen: Failed to load pixmap from {splash_image_path_absolute}. Image might be missing, corrupt, or path incorrect in bundle.")
                #         else:
                #             logging.info(f"QSplashScreen: Pixmap loaded successfully from {splash_image_path_absolute}.")
                #             # splash = QSplashScreen(splash_pixmap)
                #             # splash.setMask(splash_pixmap.mask()) # Per trasparenza, se l'immagine ha un canale alpha
                #             # splash.show()
                #             # # Show initial message IMMEDIATELY after showing splash
                #             # splash.showMessage("Inizializzazione applicazione...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                #             # app.processEvents() # Force display of splash screen NOW
                #             # logging.debug("QSplashScreen: Splash screen shown.")
                #     except Exception as e_splash_load:
                #         logging.error(f"QSplashScreen: Error during splash screen loading/showing: {e_splash_load}", exc_info=True)
                #         # Non fatale, l'app può continuare senza splash
                # else:
                #     logging.debug("Skipping splash screen (not a frozen app).")
                # === Fine Splash Screen ===

            except Exception as e_app_init:
                 # Critical error during QApplication init, cannot proceed
                 logging.critical(f"Fatal error initializing QApplication: {e_app_init}", exc_info=True)
                 # Try basic message box if possible, but might fail
                 try: QMessageBox.critical(None, "Errore Avvio Critico", f"Impossibile inizializzare l'ambiente grafico.\\n{e_app_init}")
                 except: pass
                 sys.exit(1) # Exit immediately

            # --- NOW Check Single Instance Lock and Start Local Server ---
            logging.info("Checking single instance lock and starting local server...")
            # Assicurati che la memoria condivisa sia attaccata (anche se l'abbiamo creata)
            # Questo è più un check di sanità.
            if not shared_memory.isAttached():
                 logging.warning("Shared memory segment was created but not attached? Trying to attach...")
                 if not shared_memory.attach():
                      logging.critical(f"Failed to attach to own shared memory: {shared_memory.errorString()}")
                      # Non possiamo continuare senza memoria condivisa
                      # if splash: splash.close() # Close splash before exit
                      sys.exit(1)

            # Crea server locale per ricevere segnali da altre istanze
            local_server = QLocalServer()

            # Rimuovi eventuali server orfani precedenti con lo stesso nome
            if QLocalServer.removeServer(LOCAL_SERVER_NAME):
                logging.warning(f"Removed potentially orphaned local server '{LOCAL_SERVER_NAME}'")

            if not local_server.listen(LOCAL_SERVER_NAME):
                logging.error(f"Unable to start local server '{LOCAL_SERVER_NAME}': {local_server.errorString()}")
                # Pulisci la memoria condivisa prima di uscire
                cleanup_instance_lock(local_server, shared_memory)
                # if splash: splash.close() # Close splash before exit
                sys.exit(1) # Esci se il server non parte
            else:
                logging.info(f"Local server listening on: {local_server.fullServerName()}")

                # --- Continue with the rest of the initialization ---
                window = None # Inizializza a None
                exit_code = 1 # Default exit code in caso di errore

                try:
                    # Connetti cleanup all'uscita di QApplication (DO THIS EARLY)
                    app.aboutToQuit.connect(lambda: cleanup_instance_lock(local_server, shared_memory))

                    # --- Caricamento Impostazioni (senza applicazione traduttore qui) ---
                    # if splash: # Aggiorna messaggio se lo splash è attivo
                    #     splash.showMessage("Caricamento impostazioni...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                    #     app.processEvents()
                    logging.info("Loading settings...")
                    current_settings, is_first_launch = settings_manager.load_settings()
                    logging.info("Settings loaded.")
                    # --- Fine Caricamento Impostazioni ---

                    # --- Creazione Finestra Principale e gestione primo avvio ---
                    # if splash: # Aggiorna messaggio
                    #      splash.showMessage("Creazione interfaccia utente...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                    #      app.processEvents()
                    # Crea la finestra principale, passando gli handler log
                    # qt_log_handler è già definito sopra
                    # console_handler è definito sopra
                    logging.debug("Creating MainWindow instance...")
                    # Passa gli handler creati qui alla MainWindow
                    window = MainWindow(current_settings, console_handler, qt_log_handler)
                    logging.debug("MainWindow instance created.")

                    # --- Apply language from loaded settings ---
                    initial_lang_code = current_settings.get("language", "en") # Use 'en' as fallback
                    logging.info(f"Applying initial language: {initial_lang_code}")
                    window.apply_translator(initial_lang_code)
                    window.retranslateUi() # <<< ADDED: Force UI update with the new translator
                    # --- END Apply language ---


                    if is_first_launch:
                        # if splash: # Aggiorna messaggio
                        #      splash.showMessage("Configurazione iniziale...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                        #      app.processEvents()
                        logging.info("First launch detected, showing settings dialog.")
                        # Importa SettingsDialog qui per evitare dipendenze circolari a livello di modulo
                        from dialogs.settings_dialog import SettingsDialog
                        settings_dialog = SettingsDialog(current_settings.copy(), window) # Passa copia e parent
                        if settings_dialog.exec() == QDialog.Accepted:
                            new_settings = settings_dialog.get_settings()
                            if settings_manager.save_settings(new_settings):
                                window.current_settings = new_settings # Aggiorna finestra
                                # Apply translator is now called *after* dialog on first launch as well,
                                # ensuring consistency if user changed lang in first dialog.
                                window.apply_translator(new_settings.get("language", "en")) # Applica lingua (use 'en' fallback)
                                window.theme_manager.update_theme() # Applica tema
                                window.retranslateUi() # Ri-traduce UI
                                window.profile_table_manager.update_profile_table() # Aggiorna tabella
                                logging.info("Initial settings configured and saved by user.")
                            else:
                                QMessageBox.critical(window, "Errore", "Impossibile salvare le impostazioni iniziali.")
                        else: # Utente ha annullato il dialogo primo avvio
                            reply = QMessageBox.question(window, "Impostazioni Predefinite",
                                                        "Nessuna impostazione specifica salvata. Usare quelle predefinite e continuare?",
                                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                                        QMessageBox.StandardButton.Yes)
                            if reply != QMessageBox.StandardButton.Yes:
                                logging.info("Exit requested by user on first launch cancel.")
                                # Cleanup prima di uscire
                                cleanup_instance_lock(local_server, shared_memory)
                                sys.exit(0)
                            else: # Salva i default se l'utente accetta di continuare
                                if not settings_manager.save_settings(current_settings): # Salva i default caricati
                                     QMessageBox.warning(window, "Errore", "Impossibile salvare le impostazioni predefinite.")
                                # Continua comunque con i default caricati in memoria

                    # Connetti il segnale del server locale allo slot della finestra
                    # L'istanza 'window' ora esiste sicuramente
                    # Lo slot `activateExistingInstance` è definito in MainWindow
                    local_server.newConnection.connect(window.activateExistingInstance)
                    logging.debug("Connected local server newConnection signal to window.activateExistingInstance slot.")


                    window.show()
                    logging.info("Starting Qt application event loop...")
                    if pyi_splash:
                        logging.debug("Closing PyInstaller splash screen...")
                        pyi_splash.close()
                        logging.debug("Splash screen close command sent.")
                    exit_code = app.exec() # Avvia loop eventi GUI
                    logging.info(f"Qt application event loop finished with exit code: {exit_code}")

                except ImportError as e_imp:
                     logging.critical(f"Import error during GUI setup: {e_imp}", exc_info=True)
                     # Prova a chiudere lo splash se esiste
                     # if splash: splash.close()
                     QMessageBox.critical(None, "Errore Import", f"Errore critico: libreria mancante.\\n{e_imp}\\nL'applicazione non può avviarsi.")
                     exit_code = 1
                except Exception as e_gui_init: # Cattura altri errori during l'init della GUI
                    logging.critical(f"Fatal error during GUI initialization: {e_gui_init}", exc_info=True)
                    # Prova a chiudere lo splash se esiste
                    # if splash: splash.close()
                    # Prova a mostrare un messaggio di errore base se possibile
                    try:
                        QMessageBox.critical(None, "Errore Avvio", f"Errore fatale during l'inizializzazione della GUI:\\n{e_gui_init}")
                    except:
                        pass # Ignora errori nel mostrare l'errore stesso
                    exit_code = 1
                finally:
                    # Il cleanup viene già chiamato da app.aboutToQuit.connect
                    # Non è necessario chiamarlo di nuovo qui a meno che app.exec() non sia mai stato raggiunto
                    # Ma in quel caso, la connessione aboutToQuit non verrebbe attivata.
                    # Se l'app non è stata creata o exec non è stato chiamato, esegui cleanup manualmente.
                    if app is None or exit_code != 0 and not app.closingDown():
                         logging.warning("Performing manual cleanup due to early exit or error before event loop.")
                         cleanup_instance_lock(local_server, shared_memory)
                    sys.exit(exit_code) # Esci con il codice appropriato
        else:
             # Questo caso non dovrebbe essere raggiunto se la logica sopra è corretta
             logging.error("Reached unexpected state where app_should_run is False but execution continued.")
             sys.exit(1)