# main.py
# -*- coding: utf-8 -*-
import sys
#import os
import logging
import argparse

# --- PySide6 Imports ---
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QSplashScreen
from PySide6.QtCore import QSharedMemory
#from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QLocalSocket, QLocalServer

# --- App Imports ---
import settings_manager
import backup_runner
from gui_utils import QtLogHandler
from SaveState_gui import MainWindow # , ENGLISH_TRANSLATOR, CURRENT_TRANSLATOR # Importa da SaveState_gui
from SaveState_gui import SHARED_MEM_KEY, LOCAL_SERVER_NAME # Importa costanti

try:
    import pyi_splash  # type: ignore # This module only exists when the app is packaged with PyInstaller
except ImportError:
    pyi_splash = None # Set to None if not found (e.g. when not running from a bundle)

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

    # Remove existing handlers if necessary (e.g. in PyInstaller)
    for handler in root_logger.handlers[:]:
        try:
            root_logger.removeHandler(handler)
            handler.close()
        except Exception as e_handler:
            logging.warning(f"Could not remove/close handler: {e_handler}") # Meno critico

    # Create and add new handlers
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO) # Console handler level
    root_logger.addHandler(console_handler)

    # Qt handler (logging in the GUI) - Now imported
    qt_log_handler = QtLogHandler()
    qt_log_handler.setFormatter(log_formatter)
    qt_log_handler.setLevel(logging.INFO) # Qt handler level
    root_logger.addHandler(qt_log_handler)

    logging.info("Logging configured.")

    # --- Parsing Arguments ---
    parser = argparse.ArgumentParser(description='SaveState GUI or Backup Runner.')
    parser.add_argument("--backup", help="Nome del profilo per cui eseguire un backup silenzioso.")
    args = parser.parse_args() # Handle exceptions if necessary

    # --- Execution Mode Check ---
    if args.backup:
        # === Silent Backup Mode ===
        profile_to_backup = args.backup
        logging.info(f"Detected argument --backup '{profile_to_backup}'. Starting silent backup...")
        # Execute backup logic directly (now includes notification)
        try:
            backup_success = backup_runner.run_silent_backup(profile_to_backup)
            logging.info(f"Silent backup completed successfully: {backup_success}")
            sys.exit(0 if backup_success else 1) # Exit immediately after backup
        except Exception as e_backup:
            logging.critical(f"Error during silent backup for '{profile_to_backup}': {e_backup}", exc_info=True)
            sys.exit(1)

    else:
        # === Normal GUI Mode ===
        logging.info("No --backup argument, starting GUI mode. Checking single instance...")

        # --- Single Instance Logic ---
        shared_memory = None # Initialize to None
        local_socket = None
        local_server = None
        app_should_run = True # Flag to decide whether to start the GUI

        try:
            shared_memory = QSharedMemory(SHARED_MEM_KEY)

            # Tries to create shared memory. If it fails because it already exists...
            if not shared_memory.create(1, QSharedMemory.AccessMode.ReadOnly):
                if shared_memory.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
                    logging.warning("Another instance of SaveState is already running. Attempting to activate it.")
                    app_should_run = False # Do not start this GUI instance

                    # Connect to the other instance
                    local_socket = QLocalSocket()
                    local_socket.connectToServer(LOCAL_SERVER_NAME)
                    if local_socket.waitForConnected(500):
                        logging.info("Connected to existing instance. Sending 'show' signal.")
                        # Send a recognizable signal, e.g. 'show\n'
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
                        # Release shared memory (only attached implicitly)
                        if shared_memory.isAttached(): shared_memory.detach()
                        sys.exit(0) # Exit successfully (the other instance has been activated)
                    else:
                        logging.error(f"Unable to connect to existing instance server '{LOCAL_SERVER_NAME}': {local_socket.errorString()}")
                        # Exit is more secure if we can't communicate
                        if shared_memory.isAttached(): shared_memory.detach()
                        sys.exit(1) # Exit with error
                else:
                    # Other recoverable shared memory error
                    logging.error(f"QSharedMemory fatal error (create): {shared_memory.errorString()}")
                    app_should_run = False # Do not start the GUI
                    if shared_memory.isAttached(): shared_memory.detach() # Try to clean up
                    sys.exit(1) # Exit with error

            # If we get here, the memory was created successfully (we are the first instance)
            logging.debug(f"Shared memory segment '{SHARED_MEM_KEY}' created successfully.")

        except Exception as e_shmem_init:
            logging.critical(f"Unexpected error during SharedMemory initialization: {e_shmem_init}", exc_info=True)
            app_should_run = False
            if shared_memory and shared_memory.isAttached(): shared_memory.detach() # Try to clean up
            sys.exit(1)


        # If app_should_run is still True, we are the first GUI instance
        if app_should_run:
            logging.info("First GUI instance. Starting application...")

            # --- Initialize QApplication and Splash Screen EARLY ---
            app = None # Initialize to None
            splash = None # Initialize splash to None
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
            # Ensure shared memory is attached (even though we created it)
            # This is more of a sanity check.
            if not shared_memory.isAttached():
                 logging.warning("Shared memory segment was created but not attached? Trying to attach...")
                 if not shared_memory.attach():
                      logging.critical(f"Failed to attach to own shared memory: {shared_memory.errorString()}")
                      # We cannot continue without shared memory
                      # if splash: splash.close() # Close splash before exit
                      sys.exit(1)

            # Create local server to receive signals from other instances
            local_server = QLocalServer()

            # Remove any previous orphaned servers with the same name
            if QLocalServer.removeServer(LOCAL_SERVER_NAME):
                logging.warning(f"Removed potentially orphaned local server '{LOCAL_SERVER_NAME}'")

            if not local_server.listen(LOCAL_SERVER_NAME):
                logging.error(f"Unable to start local server '{LOCAL_SERVER_NAME}': {local_server.errorString()}")
                # Clean up shared memory before exiting
                cleanup_instance_lock(local_server, shared_memory)
                # if splash: splash.close() # Close splash before exit
                sys.exit(1) # Exit if the server doesn't start
            else:
                logging.info(f"Local server listening on: {local_server.fullServerName()}")

                # --- Continue with the rest of the initialization ---
                window = None # Inizializza a None
                exit_code = 1 # Default exit code in caso di errore

                try:
                    # Connect cleanup to QApplication exit (DO THIS EARLY)
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
                    # Pass the handlers created here to MainWindow
                    window = MainWindow(current_settings, console_handler, qt_log_handler)
                    logging.debug("MainWindow instance created.")

                    # --- Apply language from loaded settings ---
                    initial_lang_code = current_settings.get("language", "en") # Use 'en' as fallback
                    logging.info(f"Applying initial language: {initial_lang_code}")
                    window.apply_translator(initial_lang_code)
                    window.retranslateUi() # <<< ADDED: Force UI update with the new translator
                    # --- END Apply language ---


                    if is_first_launch:
                        # if splash: # Update message
                        #      splash.showMessage("Configurazione iniziale...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                        #      app.processEvents()
                        logging.info("First launch detected, showing settings dialog.")
                        # Import SettingsDialog here to avoid circular module dependencies
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
                        else: # User cancelled the first launch dialog
                            reply = QMessageBox.question(window, "Impostazioni Predefinite",
                                                        "Nessuna impostazione specifica salvata. Usare quelle predefinite e continuare?",
                                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                                        QMessageBox.StandardButton.Yes)
                            if reply != QMessageBox.StandardButton.Yes:
                                logging.info("Exit requested by user on first launch cancel.")
                                # Cleanup before exiting
                                cleanup_instance_lock(local_server, shared_memory)
                                sys.exit(0)
                            else: # Save defaults if user accepts to continue
                                if not settings_manager.save_settings(current_settings): # Save the loaded defaults
                                     QMessageBox.warning(window, "Errore", "Impossibile salvare le impostazioni predefinite.")
                                # Continue with the loaded defaults in memory

                    # Connect the local server signal to the window slot
                    # The 'window' instance now definitely exists
                    # The slot `activateExistingInstance` is defined in MainWindow
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
                     # Try to close the splash if it exists
                     # if splash: splash.close()
                     QMessageBox.critical(None, "Errore Import", f"Errore critico: libreria mancante.\\n{e_imp}\\nL'applicazione non può avviarsi.")
                     exit_code = 1
                except Exception as e_gui_init: # Catch other errors during GUI initialization
                    logging.critical(f"Fatal error during GUI initialization: {e_gui_init}", exc_info=True)
                    # Try to close the splash if it exists
                    # if splash: splash.close()
                    # Try to show a basic error message if possible
                    try:
                        QMessageBox.critical(None, "Errore Avvio", f"Errore fatale durante l'inizializzazione della GUI:\\n{e_gui_init}")
                    except:
                        pass # Ignore errors in showing the error itself
                    exit_code = 1
                finally:
                    # The cleanup is already called from app.aboutToQuit.connect
                    # It's not necessary to call it again here unless app.exec() is never reached
                    # But in that case, the aboutToQuit connection would not be triggered.
                    # If the app was not created or exec was not called, perform cleanup manually.
                    if app is None or exit_code != 0 and not app.closingDown():
                         logging.warning("Performing manual cleanup due to early exit or error before event loop.")
                         cleanup_instance_lock(local_server, shared_memory)
                    sys.exit(exit_code) # Exit with the appropriate code
        else:
             # This case should not be reached if the logic above is correct
             logging.error("Reached unexpected state where app_should_run is False but execution continued.")
             sys.exit(1)