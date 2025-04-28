# gui_components/profile_creation_manager.py
# -*- coding: utf-8 -*-
import os
#import sys
import logging
import string

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication
from PySide6.QtCore import Qt, Slot

# Importa dialoghi specifici se servono (es. Minecraft)
from dialogs.minecraft_dialog import MinecraftWorldsDialog
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog

# Importa utility e logica
from gui_utils import DetectionWorkerThread
import minecraft_utils
import core_logic
from shortcut_utils import sanitize_profile_name # O importa shortcut_utils
import emulator_manager # <-- ADD IMPORT

class ProfileCreationManager:
    """
    Handles user profile creation through manual input,
    drag & drop of shortcuts (.lnk), or selection of Minecraft worlds.
    """
    def __init__(self, main_window):
        """
        Initializes the manager.

        Args:
            main_window: Reference to the MainWindow instance for accessing
                         UI elements, settings, profiles, methods, etc.
        """
        self.main_window = main_window
        self.detection_thread = None # Handles its own worker for detection

    # --- HELPER METHOD FOR PATH VALIDATION (Moved here) ---
    def validate_save_path(self, path_to_check, context_profile_name="profilo"):
        """
        Checks if a path is valid as a save folder.
        Verifies that it is not empty, not a drive root,
        and that it is a valid folder.
        Shows a QMessageBox in case of error using the parent main_window.
        Returns the normalized path if valid, otherwise None.
        """
        mw = self.main_window # Abbreviation for readability
        if not path_to_check:
            QMessageBox.warning(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso non può essere vuoto."))
            return None

        norm_path = os.path.normpath(path_to_check)

        # Controllo Percorso Radice
        try:
            # Get available drive letters (only Windows for now)
            available_drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
            # Create list of normalized root paths (e.g. C:\, D:\)
            known_roots = [os.path.normpath(d + os.sep) for d in available_drives]
            logging.debug(f"Path validation: Path='{norm_path}', KnownRoots='{known_roots}', IsRoot={norm_path in known_roots}")

            if norm_path in known_roots:
                QMessageBox.warning(mw, mw.tr("Errore Percorso"),
                                    mw.tr("Non è possibile usare una radice del drive ('{0}') come cartella dei salvataggi per '{1}'.\n"
                                        "Per favore, scegli o crea una sottocartella specifica.").format(norm_path, context_profile_name))
                return None
        except Exception as e_root:
            logging.warning(f"Root path check failed during validation: {e_root}", exc_info=True)
            # Non bloccare per questo errore, procedi con isdir

        # Controllo Esistenza e Tipo (Directory)
        if not os.path.isdir(norm_path):
            QMessageBox.warning(mw, mw.tr("Errore Percorso"),
                                mw.tr("Il percorso specificato non esiste o non è una cartella valida:\n'{0}'").format(norm_path))
            return None

        # Se tutti i controlli passano, restituisce il percorso normalizzato
        logging.debug(f"Path validation: '{norm_path}' is considered valid.")
        return norm_path
    # --- FINE validate_save_path ---

    # --- Manual Profile Management ---
    @Slot()
    def handle_new_profile(self):
        """Handles the creation of a new profile with manual input."""
        mw = self.main_window
        logging.debug("ProfileCreationManager.handle_new_profile - START")
        profile_name, ok = QInputDialog.getText(mw, mw.tr("Nuovo Profilo"), mw.tr("Inserisci un nome per il nuovo profilo:"))
        logging.debug(f"ProfileCreationManager.handle_new_profile - Name entered: '{profile_name}', ok={ok}")

        if ok and profile_name:
            # Clean the entered name
            profile_name_original = profile_name # Preserve original for messages
            profile_name = sanitize_profile_name(profile_name) # Apply sanitization
            if not profile_name:
                 QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                     mw.tr("Il nome del profilo ('{0}') contiene caratteri non validi o è vuoto dopo la pulizia.").format(profile_name_original))
                 return

            if profile_name in mw.profiles:
                logging.warning(f"Profile '{profile_name}' already exists.")
                QMessageBox.warning(mw, mw.tr("Errore"), mw.tr("Un profilo chiamato '{0}' esiste già.").format(profile_name))
                return

            logging.debug(f"ProfileCreationManager.handle_new_profile - Requesting path for '{profile_name}'...")
            path_prompt = mw.tr("Ora inserisci il percorso COMPLETO per i salvataggi del profilo:\n'{0}'").format(profile_name)
            input_path, ok2 = QInputDialog.getText(mw, mw.tr("Percorso Salvataggi"), path_prompt)
            logging.debug(f"ProfileCreationManager.handle_new_profile - Path entered: '{input_path}', ok2={ok2}")

            if ok2:
                # Use the validation function
                validated_path = self.validate_save_path(input_path, profile_name)

                if validated_path:
                    logging.debug(f"handle_new_profile - Valid path: '{validated_path}'.")
                    mw.profiles[profile_name] = {'path': validated_path} # Save as dictionary
                    logging.debug("handle_new_profile - Attempting to save profiles to file...")
                    save_success = core_logic.save_profiles(mw.profiles) # Save using core_logic
                    logging.debug(f"handle_new_profile - Result of core_logic.save_profiles: {save_success}")

                    if save_success:
                        logging.info(f"Profile '{profile_name}' created manually.")
                        # Update the table via the table manager in MainWindow
                        if hasattr(mw, 'profile_table_manager'):
                            mw.profile_table_manager.update_profile_table()
                            mw.profile_table_manager.select_profile_in_table(profile_name) # Select the new
                        QMessageBox.information(mw, mw.tr("Successo"), mw.tr("Profilo '{0}' creato e salvato.").format(profile_name))
                        mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                    else:
                        logging.error("handle_new_profile - core_logic.save_profiles returned False.")
                        QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili."))
                        # Remove from memory if saving fails
                        if profile_name in mw.profiles:
                            del mw.profiles[profile_name]
                # else: validate_save_path has already shown the error
            else:
                 logging.debug("handle_new_profile - Path input cancelled (ok2=False).")
        else:
            logging.debug("handle_new_profile - Name input cancelled (ok=False or empty name).")
        logging.debug("handle_new_profile - END")
    # --- FINE handle_new_profile ---

    # --- Minecraft Button Management ---
    @Slot()
    def handle_minecraft_button(self):
        """
        Finds Minecraft worlds, shows a selection dialog,
        and creates a new profile for the selected world.
        """
        mw = self.main_window
        logging.info("Starting Minecraft world search...")
        mw.status_label.setText(mw.tr("Ricerca cartella salvataggi Minecraft..."))
        QApplication.processEvents()

        try:
            saves_folder = minecraft_utils.find_minecraft_saves_folder()
        except Exception as e_find:
            logging.error(f"Unexpected error during find_minecraft_saves_folder: {e_find}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Minecraft"), mw.tr("Errore imprevisto durante la ricerca della cartella Minecraft."))
            mw.status_label.setText(mw.tr("Errore ricerca Minecraft."))
            return

        if not saves_folder:
            logging.warning("Minecraft saves folder not found.")
            QMessageBox.warning(mw, mw.tr("Cartella Non Trovata"),
                                mw.tr("Impossibile trovare la cartella dei salvataggi standard di Minecraft (.minecraft/saves).\nAssicurati che Minecraft Java Edition sia installato."))
            mw.status_label.setText(mw.tr("Cartella Minecraft non trovata."))
            return

        mw.status_label.setText(mw.tr("Lettura mondi Minecraft..."))
        QApplication.processEvents()
        try:
            worlds_data = minecraft_utils.list_minecraft_worlds(saves_folder)
        except Exception as e_list:
            logging.error(f"Unexpected error during list_minecraft_worlds: {e_list}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Minecraft"), mw.tr("Errore imprevisto durante la lettura dei mondi Minecraft."))
            mw.status_label.setText(mw.tr("Errore lettura mondi Minecraft."))
            return

        if not worlds_data:
            logging.warning("No worlds found in: %s", saves_folder)
            QMessageBox.information(mw, mw.tr("Nessun Mondo Trovato"),
                                    mw.tr("Nessun mondo trovato nella cartella:\n{0}").format(saves_folder))
            mw.status_label.setText(mw.tr("Nessun mondo Minecraft trovato."))
            return

        try:
            dialog = MinecraftWorldsDialog(worlds_data, mw) # Usa mw come parent
        except Exception as e_dialog_create:
            logging.error(f"Creation error MinecraftWorldsDialog: {e_dialog_create}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Interfaccia"), mw.tr("Impossibile creare la finestra di selezione dei mondi."))
            return

        mw.status_label.setText(mw.tr("Ready.")) # Reset status

        if dialog.exec(): # Use standard blocking exec() for modal dialogs
            selected_world = dialog.get_selected_world_info()
            if selected_world:
                profile_name = selected_world.get('world_name', selected_world.get('folder_name'))
                world_path = selected_world.get('full_path')

                if not profile_name:
                    logging.error("Name of selected Minecraft world invalid or missing.")
                    QMessageBox.critical(mw, mw.tr("Errore Interno"), mw.tr("Nome del mondo selezionato non valido."))
                    return

                # Sanitize also the Minecraft world name
                profile_name_original = profile_name
                profile_name = sanitize_profile_name(profile_name)
                if not profile_name:
                    QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                        mw.tr("Il nome del mondo ('{0}') contiene caratteri non validi o è vuoto dopo la pulizia.").format(profile_name_original))
                    return

                if not world_path or not os.path.isdir(world_path):
                    logging.error(f"World path '{world_path}' invalid for profile '{profile_name}'.")
                    QMessageBox.critical(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso del mondo selezionato ('{0}') non è valido.").format(world_path))
                    return

                logging.info(f"Minecraft world selected: '{profile_name}' - Path: {world_path}")

                if profile_name in mw.profiles:
                    QMessageBox.warning(mw, mw.tr("Profilo Esistente"),
                                        mw.tr("Un profilo chiamato '{0}' esiste già.\nScegli un altro mondo o rinomina il profilo esistente.").format(profile_name))
                    return

                # Create and save new profile
                mw.profiles[profile_name] = {'path': world_path} # Save as dictionary
                if core_logic.save_profiles(mw.profiles):
                    logging.info(f"Minecraft profile '{profile_name}' created.")
                    # Update the table via the table manager in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name) # Select the new
                    QMessageBox.information(mw, mw.tr("Profilo Creato"),
                                            mw.tr("Profilo '{0}' creato con successo per il mondo Minecraft.").format(profile_name))
                    mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili dopo aver aggiunto '{0}'.").format(profile_name))
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            else:
                logging.warning("Minecraft dialog accepted but no selected world data returned.")
                mw.status_label.setText(mw.tr("Selezione mondo annullata o fallita."))
        else:
            logging.info("Minecraft world selection cancelled by user.")
            mw.status_label.setText(mw.tr("Selezione mondo annullata."))
    # --- FINE handle_minecraft_button ---

    # --- Drag and Drop Management ---
    def dragEnterEvent(self, event):
        """Handles the drag-and-drop event."""
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            # Accept only if it's a SINGLE .lnk file
            if urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk'):
                event.acceptProposedAction()
                logging.debug("DragEnterEvent: Accepted .lnk file.")
            else:
                 logging.debug("DragEnterEvent: Rejected (not a single .lnk file).")
                 event.ignore()
        else:
             event.ignore()

    def dragMoveEvent(self, event):
        """Handles the movement of a dragged object over the widget."""
        # The acceptance logic is the same as dragEnterEvent
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk'):
                event.acceptProposedAction()
            else:
                 event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handles the release of a .lnk object and starts the path search."""
        import winshell # Necessary for .lnk
        mw = self.main_window
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        if not (urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk')):
            event.ignore()
            return

        event.acceptProposedAction()
        file_path = urls[0].toLocalFile()
        logging.info(f"DropEvent: Accepted .lnk file: {file_path}")

        # --- Reading .lnk ---
        shortcut = None
        game_install_dir = None
        target_path = None
        try:
            shortcut = winshell.shortcut(file_path)
            target_path = shortcut.path
            working_dir = shortcut.working_directory
            if working_dir and os.path.isdir(working_dir):
                game_install_dir = os.path.normpath(working_dir)
            elif target_path and os.path.isfile(target_path):
                game_install_dir = os.path.normpath(os.path.dirname(target_path))
            else:
                logging.warning(f"Unable to determine game folder from shortcut: {file_path}")
            logging.debug(f"Game folder detected (or assumed) from shortcut: {game_install_dir}")

            # --- Check for Known Emulator --- NEW BLOCK ---
            emulator_result = emulator_manager.detect_and_find_profiles(target_path)

            # --- If Emulator Detected, handle differently ---
            if emulator_result is not None:
                emulator_name, emulator_profiles_data = emulator_result
                event.acceptProposedAction() # Ensure accepted

                if emulator_profiles_data:
                    logging.info(f"Found {emulator_name} profiles: {emulator_profiles_data}")
                    
                    # --- Show Selection Dialog --- NEW ---
                    selection_dialog = EmulatorGameSelectionDialog(emulator_name, emulator_profiles_data, mw)
                    if selection_dialog.exec():
                        selected_data = selection_dialog.get_selected_profile_data()
                        if selected_data:
                            selected_id = selected_data.get('id')
                            selected_path = selected_data.get('path')

                            if not selected_id or not selected_path:
                                logging.error(f"Selected data from dialog is missing id or path: {selected_data}")
                                QMessageBox.critical(mw, mw.tr("Errore Interno"), mw.tr("Dati del profilo selezionato non validi."))
                                return

                            # Create a profile name (prioritize game name, fallback to ID)
                            selected_name = selected_data.get('name', selected_id)
                            profile_name_base = f"{emulator_name} - {selected_name}" # Use name/id
                            profile_name = sanitize_profile_name(profile_name_base)
                            if not profile_name:
                                QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                                    mw.tr("Impossibile generare un nome profilo valido per '{0}'.").format(profile_name_base))
                                return
                            
                            # Handle potential name conflicts
                            if profile_name in mw.profiles:
                                reply = QMessageBox.question(mw, mw.tr("Profilo Esistente"), 
                                                           mw.tr("Un profilo chiamato '{0}' esiste già. Sovrascriverlo?").format(profile_name),
                                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                           QMessageBox.StandardButton.No)
                                if reply == QMessageBox.StandardButton.No:
                                    mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                                    return 
                                else:
                                    logging.warning(f"Overwriting existing profile: {profile_name}")
                            
                            # Validate the selected path (should be valid, but good practice)
                            validated_path = self.validate_save_path(selected_path, profile_name)
                            if not validated_path:
                                # Error already shown by validate_save_path
                                return

                            # Add/update profile and save
                            mw.profiles[profile_name] = {'path': validated_path}
                            if core_logic.save_profiles(mw.profiles):
                                logging.info(f"Emulator game profile '{profile_name}' created/updated.")
                                if hasattr(mw, 'profile_table_manager'):
                                    mw.profile_table_manager.update_profile_table()
                                    mw.profile_table_manager.select_profile_in_table(profile_name)
                                QMessageBox.information(mw, mw.tr("Profilo Creato"), mw.tr("Profilo '{0}' creato con successo.").format(profile_name))
                                mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                            else:
                                QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili dopo aver aggiunto '{0}'.").format(profile_name))
                                if profile_name in mw.profiles: del mw.profiles[profile_name] # Revert if save failed
                        else:
                             logging.warning("Emulator selection dialog accepted, but no data returned.")
                    else:
                        # Dialog was cancelled
                        logging.info("Emulator game selection was cancelled by the user.")
                        mw.status_label.setText(mw.tr("Selezione gioco annullata."))
                    # --- End Selection Dialog Handling ---

                    # --- REMOVE OLD QMESSAGEBOX --- 
                    # profile_list_str = "\n- ".join(emulator_profiles_data)
                    # QMessageBox.information(mw, mw.tr("Rilevato Emulatore ({0})").format(emulator_name),
                    #                         mw.tr("Rilevato collegamento a {0}.\n\nProfili trovati (ID Titolo/Gioco):\n- {1}\n\n(Funzionalità per aggiungere giochi specifici in sviluppo.)")
                    #                         .format(emulator_name, profile_list_str))
                else:
                    logging.warning(f"{emulator_name} detected, but no profiles found in its standard directory.")
                    QMessageBox.warning(mw, mw.tr("Rilevato Emulatore ({0})").format(emulator_name),
                                        mw.tr("Rilevato collegamento a {0}, ma nessun profilo trovato nella sua cartella standard.\nVerifica la posizione dei salvataggi dell'emulatore.").format(emulator_name))
                return # Stop further processing for detected emulators for now

            # --- If NOT a known Emulator, proceed with existing logic ---
            logging.debug(f"Shortcut target '{target_path}' does not match known emulators, proceeding with standard path detection.")

        except ImportError:
            logging.error("The 'winshell' library is not installed. Cannot read .lnk files.")
            QMessageBox.critical(mw, mw.tr("Errore Dipendenza"), mw.tr("La libreria 'winshell' necessaria non è installata."))
            return
        except Exception as e_lnk:
            logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Collegamento"), mw.tr("Impossibile leggere il file .lnk:\n{0}").format(e_lnk))
            return

        # --- Get and Clean Profile Name ---
        base_name = os.path.basename(file_path)
        profile_name_temp, _ = os.path.splitext(base_name)
        profile_name_original = profile_name_temp.replace('™', '').replace('®', '').strip()
        profile_name = sanitize_profile_name(profile_name_original)
        logging.info(f"Original Name (basic clean): '{profile_name_original}', Sanitized Name: '{profile_name}'")

        if not profile_name:
            logging.error(f"Sanitized profile name for '{profile_name_original}' became empty!")
            QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                mw.tr("Impossibile generare un nome profilo valido dal collegamento trascinato."))
            return

        if profile_name in mw.profiles:
            QMessageBox.warning(mw, mw.tr("Profilo Esistente"), mw.tr("Profilo '{0}' esiste già.").format(profile_name))
            return

        # --- Start Path Search Thread (Only if NOT Ryujinx) ---
        if self.detection_thread and self.detection_thread.isRunning():
            QMessageBox.information(mw, mw.tr("Operazione in Corso"), mw.tr("Un'altra ricerca di percorso è già in corso. Attendi."))
            return

        mw.set_controls_enabled(False) # Disable controls in MainWindow
        mw.status_label.setText(mw.tr("Ricerca percorso per '{0}' in corso...").format(profile_name))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor) # Cursore di attesa

        # --- Start Fade/Animation Effect ---
        try:
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                # Ensure the overlay is sized correctly before showing it
                mw.overlay_widget.resize(mw.centralWidget().size())
                # Center the label with the GIF/Placeholder
                if hasattr(mw, '_center_loading_label'):
                    mw._center_loading_label() # Use the helper function we created

                # Show overlay and label (the label is a child of the overlay)
                mw.overlay_widget.show()

                # Start the fade-in animation for the overlay
                if hasattr(mw, 'fade_in_animation'):
                    mw.fade_in_animation.start()
                logging.debug("Fade-in animation started.")
            else:
                logging.warning("Overlay widget or fade animation not found in MainWindow.")
        except Exception as e_fade_start:
            logging.error(f"Error starting fade/animation effect: {e_fade_start}", exc_info=True)
        # --- FINE Start Fade/Animation Effect ---
        
        # Create and start the path detection thread
        self.detection_thread = DetectionWorkerThread(
            game_install_dir=game_install_dir,
            profile_name_suggestion=profile_name,
            current_settings=mw.current_settings.copy(),
            installed_steam_games_dict=None# Pass a copy of the settings
        )
        # Connect the signals to the methods of THIS CLASS (ProfileCreationManager)
        self.detection_thread.progress.connect(self.on_detection_progress)
        self.detection_thread.finished.connect(self.on_detection_finished)
        self.detection_thread.start()
        logging.debug("Path detection thread started.")
    # --- FINE dropEvent ---

    # --- Slot for Path Detection Progress ---
    @Slot(str)
    def on_detection_progress(self, message):
        """Updates the status bar of main_window with messages from the thread."""
        # It might be useful to filter/simplify the messages here
        self.main_window.status_label.setText(message)
    # --- FINE on_detection_progress ---

    # --- Slot for Path Detection Finished ---
    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Called when the path detection thread has finished."""
        mw = self.main_window
        logging.debug(f"Detection thread finished. Success: {success}, Results: {results}")
        
        # --- Stop Fade/Animation Effect ---
        try:
            # Start fade-out animation (will hide overlay and label at the end)
            if hasattr(mw, 'fade_out_animation'):
                mw.fade_out_animation.start()
                logging.debug("Fade-out animation started.")
            elif hasattr(mw, 'overlay_widget'):
                 # Fallback: hide immediately if the animation doesn't exist
                 mw.overlay_widget.hide()
                 if hasattr(mw, 'loading_label'): mw.loading_label.hide()
            else:
                 logging.warning("Overlay widget or fade animation not found in MainWindow for stopping.")

        except Exception as e_fade_stop:
            logging.error(f"Error stopping fade/animation effect: {e_fade_stop}", exc_info=True)
        # --- FINE Fade/Animation Effect ---
        
        QApplication.restoreOverrideCursor() # Restore cursor
        mw.set_controls_enabled(True)      # Reenable controls in MainWindow
        mw.status_label.setText(mw.tr("Path search completed."))

        self.detection_thread = None # Remove reference to completed thread

        profile_name = results.get('profile_name_suggestion', 'profilo_sconosciuto')

        if not success:
            error_msg = results.get('message', mw.tr("Errore sconosciuto durante la ricerca."))
            if "interrupted" not in error_msg.lower(): # Don't show popup if interrupted
                QMessageBox.critical(mw, mw.tr("Errore Ricerca Percorso"), error_msg)
            else:
                mw.status_label.setText(mw.tr("Ricerca interrotta."))
            return

        # --- Results handling logic ---
        final_path_to_use = None
        paths_found = results.get('path_data', []) # Get the list of (path, score) tuples
        status = results.get('status', 'error')

        if status == 'found':
            logging.debug(f"Path data found by detection thread: {paths_found}") # Updated log
            if len(paths_found) == 1:
                # One path found (now a tuple)
                single_path, single_score = paths_found[0] # Extract path and score
                reply = QMessageBox.question(mw, mw.tr("Conferma Percorso Automatico"),
                                             # Mostra solo il percorso nel messaggio
                                             mw.tr("È stato rilevato questo percorso:\n\n{0}\n\nVuoi usarlo per il profilo '{1}'?").format(single_path, profile_name),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    final_path_to_use = single_path # Usa solo il percorso
                elif reply == QMessageBox.StandardButton.No:
                    logging.info("User rejected single automatic path. Requesting manual input.")
                    final_path_to_use = None # Forza richiesta manuale
                else: # Cancel
                    mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                    return

            elif len(paths_found) > 1: 

                show_scores = mw.developer_mode_enabled
                logging.debug(f"Handling multiple paths. Developer mode active (show scores): {show_scores}")

                choices = []
                # Map to retrieve the original path from the displayed string
                display_str_to_path_map = {}

                logging.debug(f"Original path_data received (sorted by score desc): {paths_found}") # Log the received data

                # Create the strings for the dialog
                for path, score in paths_found: # Iterate over the (path, score) tuples
                    display_text = ""
                    if show_scores:
                        # Show path and score
                        # Optionally clean up the path for display if too long?
                        # display_path = path if len(path) < 60 else path[:25] + "..." + path[-30:]
                        display_path = path # For now we use the full path
                        display_text = f"{display_path} (Score: {score})"
                    else:
                        # Show only path
                        display_text = path

                    choices.append(display_text)
                    display_str_to_path_map[display_text] = path # Map displayed string -> original path

                # Add manual option
                manual_entry_text = mw.tr("[Inserisci Manualmente...]")
                choices.append(manual_entry_text)
                # Associate the manual option text to None in the map
                display_str_to_path_map[manual_entry_text] = None

                logging.debug(f"Choices prepared for QInputDialog: {choices}")

                # Show the QInputDialog.getItem dialog
                chosen_display_str, ok = QInputDialog.getItem(
                    mw,
                    mw.tr("Conferma Percorso Salvataggi"),
                    mw.tr("Sono stati trovati questi percorsi potenziali per '{0}'.\nSeleziona quello corretto (ordinati per probabilità) o scegli l'inserimento manuale:").format(profile_name),
                    choices, # List of strings (with or without score)
                    0,       # Initial index (the first, which has the highest score)
                    False    # Not editable
                )

                # Handle the user's choice
                if ok and chosen_display_str:
                    # Retrieve the corresponding path using the map
                    # This works whether the score was visible or not
                    selected_path_or_none = display_str_to_path_map.get(chosen_display_str)

                    if selected_path_or_none is None: # The user chose "[Insert Manually...]"
                        logging.info("User chose manual input from multiple paths list.")
                        final_path_to_use = None # Force manual request later in the code
                    else:
                        # The user chose a specific path from the list
                        final_path_to_use = selected_path_or_none # Save the actual path
                        logging.debug(f"User selected path: {final_path_to_use}")

                else: # The user pressed Cancel
                    mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                    return # Exit the on_detection_finished function

        elif status == 'not_found':
            # No automatic path found
            QMessageBox.information(mw, mw.tr("Percorso Non Rilevato"), mw.tr("Impossibile rilevare automaticamente il percorso dei salvataggi per '{0}'.\nPer favore, inseriscilo manualmente.").format(profile_name))
            final_path_to_use = None # Force manual request
        else: # status == 'error' or other unexpected case
            logging.error(f"Unexpected status '{status}' from detection thread with success=True")
            mw.status_label.setText(mw.tr("Internal error during result handling."))
            # We could ask for manual input here? Maybe better not.
            return # Exit if the status is not 'found' or 'not_found'

        # --- Manual Input Request (if necessary) ---
        if final_path_to_use is None:
            path_prompt = mw.tr("Insert the FULL path for the profile's saves:\n'{0}'").format(profile_name)
            input_path, ok_manual = QInputDialog.getText(mw, mw.tr("Percorso Salvataggi Manuale"), path_prompt)
            if ok_manual and input_path:
                final_path_to_use = input_path
            elif ok_manual and not input_path:
                QMessageBox.warning(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso non può essere vuoto."))
                mw.status_label.setText(mw.tr("Creazione profilo annullata (percorso vuoto)."))
                return
            else: # Cancelled
                mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                return

        # --- Final Validation and Profile Saving ---
        if final_path_to_use:
            # Use the validation function (now part of this class)
            validated_path = self.validate_save_path(final_path_to_use, profile_name)

            if validated_path:
                logging.debug(f"Final path validated: {validated_path}. Saving profile '{profile_name}'")
                mw.profiles[profile_name] = {'path': validated_path} # Salva come dizionario
                if core_logic.save_profiles(mw.profiles):
                    # Update the table via the table manager in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name)
                    QMessageBox.information(mw, mw.tr("Profilo Creato"), mw.tr("Profilo '{0}' creato con successo.").format(profile_name))
                    mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili."))
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            # else: validate_save_path has already shown the error
    # --- FINE on_detection_finished ---