# gui_components/profile_creation_manager.py
# -*- coding: utf-8 -*-
import os
#import sys
import logging
#import platform
import string
#import re # Added for Steam URL parsing
#from pathlib import Path # Added for Path().stem usage

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication, QFileDialog, QHBoxLayout, QDialog, QLineEdit, QPushButton, QVBoxLayout, QLabel, QStyle, QDialogButtonBox
from PySide6.QtCore import Slot
#from PySide6.QtGui import QDropEvent

from dialogs.minecraft_dialog import MinecraftWorldsDialog
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog

# Importa utility e logica
#from gui_utils import DetectionWorkerThread
import minecraft_utils
import core_logic
import shortcut_utils # Importa l'intero modulo
#from emulator_utils import emulator_manager # Updated import path
#import config # Import the config module
import settings_manager # Importa settings_manager.py dalla root del progetto
#import configparser # For parsing .url files

# Setup logging for this module
logger = logging.getLogger(__name__)

class SavePathDialog(QDialog):
    """Custom dialog for entering a path with a browse button."""
    
    def __init__(self, parent=None, window_title="Enter Path", prompt_text="Enter the FULL path:", initial_path="", browse_dialog_title="Select Folder"):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumWidth(500)
        self.browse_dialog_title = browse_dialog_title # Memorizza per l'uso in browse_path
        
        # Get the style for standard icons
        style = QApplication.instance().style()
        
        # Main layout
        layout = QVBoxLayout(self)
        
        # Add prompt label
        layout.addWidget(QLabel(prompt_text))
        
        # Path input with browse button
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(initial_path)
        self.browse_button = QPushButton()
        # Set the folder icon for the browse button (no text)
        self.browse_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        layout.addLayout(path_layout)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # Connect browse button
        self.browse_button.clicked.connect(self.browse_path)
    
    def browse_path(self):
        """Opens dialog to select a folder."""
        directory = QFileDialog.getExistingDirectory(
            self, self.browse_dialog_title, self.path_edit.text() # Usa il titolo memorizzato
        )
        if directory:
            self.path_edit.setText(os.path.normpath(directory))
    
    def get_path(self):
        """Returns the entered path."""
        return self.path_edit.text()

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
        
        # Initialize state variables that will be managed by reset_internal_state
        self.game_name_suggestion = None
        self.game_install_dir = None 
        self.is_steam_game = False
        self.steam_app_id = None
        self.executable_path = None 
        self.shortcut_target_path = None
        self.shortcut_game_name = None
        logger.debug("ProfileCreationManager initialized with internal state variables.")

    def reset_internal_state(self):
        """Resets internal state variables before processing a new item."""
        logger.debug("Resetting ProfileCreationManager internal state.")
        self.game_name_suggestion = None
        self.game_install_dir = None
        self.is_steam_game = False
        self.steam_app_id = None
        self.executable_path = None
        self.shortcut_target_path = None
        self.shortcut_game_name = None
        if self.detection_thread and self.detection_thread.isRunning():
            logger.warning("Resetting state while detection thread might be running. Ensure it's handled.")
        self.detection_thread = None

    # Il metodo _get_steam_game_details è stato spostato nel DragDropHandler


    # --- HELPER METHOD FOR PATH VALIDATION (Moved here) ---
    def validate_save_path(self, path_to_check, context_profile_name="profile"):
        """
        Checks if a path is valid as a save folder.
        Verifies that it is not empty, not a drive root,
        and that it is a valid folder.
        Shows a QMessageBox in case of error using the parent main_window.
        Returns the normalized path if valid, otherwise None.
        """
        mw = self.main_window # Abbreviation for readability
        if not path_to_check:
            QMessageBox.warning(mw, "Path Error", f"The path cannot be empty.")
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
                QMessageBox.warning(mw, "Path Error",
                                    f"Cannot use a drive root ('{norm_path}') as the save folder for '{context_profile_name}'.\n"
                                        "Please choose or create a specific subfolder.")
                return None
        except Exception as e_root:
            logging.warning(f"Root path check failed during validation: {e_root}", exc_info=True)
            # Non bloccare per questo errore, procedi con isdir

        # Controllo Esistenza e Tipo (Directory)
        if not os.path.isdir(norm_path):
            QMessageBox.warning(mw, "Path Error",
                                f"The specified path does not exist or is not a valid folder:\n'{norm_path}'")
            return None

        # Se tutti i controlli passano, restituisce il percorso normalizzato
        logging.debug(f"Path validation: '{norm_path}' is considered valid.")
        return norm_path
    # --- FINE validate_save_path ---

    # --- Manual Profile Management ---
    @Slot()
    def handle_new_profile(self):
        """Handles the creation of a new profile with manual input."""
        self.reset_internal_state() # Reset state at the beginning
        mw = self.main_window
        logging.debug("ProfileCreationManager.handle_new_profile - START")
        profile_name, ok = QInputDialog.getText(mw, "New Profile", "Enter a name for the new profile:")
        logging.debug(f"ProfileCreationManager.handle_new_profile - Name entered: '{profile_name}', ok={ok}")

        if ok and profile_name:
            # Clean the entered name
            profile_name_original = profile_name # Preserve original for messages
            profile_name = shortcut_utils.sanitize_profile_name(profile_name) # Apply sanitization
            if not profile_name:
                 QMessageBox.warning(mw, "Profile Name Error",
                                     f"The profile name ('{profile_name_original}') contains invalid characters or is empty after cleaning.")
                 return

            if profile_name in mw.profiles:
                logging.warning(f"Profile '{profile_name}' already exists.")
                QMessageBox.warning(mw, "Error", f"A profile named '{profile_name}' already exists.")
                return

            logging.debug(f"ProfileCreationManager.handle_new_profile - Requesting path for '{profile_name}'...")
            
            # Use custom dialog with browse button instead of QInputDialog
            settings, _ = settings_manager.load_settings()
            path_dialog = SavePathDialog(
                parent=mw, 
                window_title=mw.tr("Save Path for '{0}'").format(profile_name),
                prompt_text=mw.tr("Now enter the FULL path for the profile's saves:\n'{0}'").format(profile_name),
                initial_path=settings.get(f"last_save_path_{profile_name}", ""), 
                browse_dialog_title=mw.tr("Select Save Folder")
            )
            result = path_dialog.exec()
            
            if result == QDialog.DialogCode.Accepted:
                input_path = path_dialog.get_path()
                logging.debug(f"ProfileCreationManager.handle_new_profile - Path entered: '{input_path}'")
                
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
                        QMessageBox.information(mw, "Success", f"Profile '{profile_name}' created and saved.")
                        mw.status_label.setText(f"Profile '{profile_name}' created.")
                    else:
                        logging.error("handle_new_profile - core_logic.save_profiles returned False.")
                        QMessageBox.critical(mw, "Error", "Unable to save the profiles file.")
                        # Remove from memory if saving fails
                        if profile_name in mw.profiles:
                            del mw.profiles[profile_name]
                # else: validate_save_path has already shown the error
            else:
                 logging.debug("handle_new_profile - Path input cancelled.")
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
        mw.status_label.setText("Searching for Minecraft saves folder...")
        QApplication.processEvents()

        try:
            saves_folder = minecraft_utils.find_minecraft_saves_folder()
        except Exception as e_find:
            logging.error(f"Unexpected error during find_minecraft_saves_folder: {e_find}", exc_info=True)
            QMessageBox.critical(mw, "Minecraft Error", "Unexpected error while searching for the Minecraft folder.")
            mw.status_label.setText("Error searching for Minecraft.")
            return

        if not saves_folder:
            logging.warning("Minecraft saves folder not found.")
            QMessageBox.warning(mw, "Folder Not Found",
                                "Could not find the standard Minecraft saves folder (.minecraft/saves).\nMake sure that Minecraft Java Edition is installed.")
            mw.status_label.setText("Minecraft folder not found.")
            return

        mw.status_label.setText("Reading Minecraft worlds...")
        QApplication.processEvents()
        try:
            worlds_data = minecraft_utils.list_minecraft_worlds(saves_folder)
        except Exception as e_list:
            logging.error(f"Unexpected error during list_minecraft_worlds: {e_list}", exc_info=True)
            QMessageBox.critical(mw, "Minecraft Error", "Unexpected error while reading Minecraft worlds.")
            mw.status_label.setText("Error reading Minecraft worlds.")
            return

        if not worlds_data:
            logging.warning("No worlds found in: %s", saves_folder)
            QMessageBox.information(mw, "No Worlds Found",
                                    f"No worlds found in folder:\n{saves_folder}")
            mw.status_label.setText("No Minecraft worlds found.")
            return

        try:
            dialog = MinecraftWorldsDialog(worlds_data, mw) # Usa mw come parent
        except Exception as e_dialog_create:
            logging.error(f"Creation error MinecraftWorldsDialog: {e_dialog_create}", exc_info=True)
            QMessageBox.critical(mw, "Interface Error", "Unable to create the world selection window.")
            return

        mw.status_label.setText("Ready.") # Reset status

        if dialog.exec(): # Use standard blocking exec() for modal dialogs
            selected_world = dialog.get_selected_world_info()
            if selected_world:
                profile_name = selected_world.get('world_name', selected_world.get('folder_name'))
                world_path = selected_world.get('full_path')

                if not profile_name:
                    logging.error("Name of selected Minecraft world invalid or missing.")
                    QMessageBox.critical(mw, "Internal Error", "Invalid selected world name.")
                    return

                # Sanitize also the Minecraft world name
                profile_name_original = profile_name
                profile_name = shortcut_utils.sanitize_profile_name(profile_name)
                if not profile_name:
                    QMessageBox.warning(mw, "Profile Name Error",
                                        f"The world name ('{profile_name_original}') contains invalid characters or is empty after cleaning.")
                    return

                if not world_path or not os.path.isdir(world_path):
                    logging.error(f"World path '{world_path}' invalid for profile '{profile_name}'.")
                    QMessageBox.critical(mw, "Path Error", f"The path of the selected world ('{world_path}') is not valid.")
                    return

                logging.info(f"Minecraft world selected: '{profile_name}' - Path: {world_path}")

                if profile_name in mw.profiles:
                    QMessageBox.warning(mw, "Existing Profile",
                                        f"A profile named '{profile_name}' already exists.\nChoose another world or rename the existing profile.")
                    return

                # Create and save new profile
                mw.profiles[profile_name] = {'path': world_path} # Save as dictionary
                if core_logic.save_profiles(mw.profiles):
                    logging.info(f"Minecraft profile '{profile_name}' created.")
                    # Update the table via the table manager in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name) # Select the new
                    QMessageBox.information(mw, "Profile Created",
                                            f"Profile '{profile_name}' successfully created for the Minecraft world.")
                    mw.status_label.setText(f"Profile '{profile_name}' created.")
                else:
                    QMessageBox.critical(mw, "Error", f"Unable to save the profiles file after adding '{profile_name}'.")
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            else:
                logging.warning("Minecraft dialog accepted but no selected world data returned.")
                mw.status_label.setText("World selection cancelled or failed.")
        else:
            logging.info("Minecraft world selection cancelled by user.")

    # --- FINE handle_minecraft_button ---

    # --- Slot for Path Detection Finished ---
    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Called when the path detection thread has finished."""
        mw = self.main_window
        logging.debug(f"Detection thread finished. Success: {success}, Results: {results}")
        
        # Nascondiamo l'overlay appena prima di mostrare i dialoghi di conferma
        # --- Stop Fade/Animation Effect ---
        try:
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget.isVisible():
                # Ripristina il testo "Drop Here" prima di nascondere l'overlay
                if hasattr(mw, 'loading_label') and mw.loading_label:
                    mw.loading_label.setText("Drop Here")
                    mw.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                    mw.loading_label.adjustSize() # Ensure label resizes to content
                    logging.debug("Overlay text reset to 'Drop Here'")
                
                # Utilizziamo lo stesso comportamento di fade-out per tutti i tipi di file
                if hasattr(mw, 'fade_out_animation') and mw.fade_out_animation:
                    # Use fade-out animation to hide the overlay
                    mw.fade_out_animation.start()
                    logging.debug("Fade-out animation started BEFORE showing dialogs")
                else:
                    # Fallback if animation not available
                    mw.overlay_widget.hide()
                    if hasattr(mw, 'loading_label'):
                        mw.loading_label.hide()
                    logging.debug("Overlay and loading label hidden BEFORE showing dialogs")
            else:
                logging.warning("Overlay widget not found or already hidden in MainWindow.")
        except Exception as e_fade_stop:
            logging.error(f"Error stopping fade/animation effect: {e_fade_stop}", exc_info=True)
        # --- FINE Fade/Animation Effect ---
            
        QApplication.restoreOverrideCursor() # Restore cursor
        mw.set_controls_enabled(True)      # Reenable controls in MainWindow
        mw.status_label.setText("Path search completed.")

        self.detection_thread = None # Remove reference to completed thread

        profile_name = results.get('profile_name_suggestion', 'unknown_profile')

        if not success:
            error_msg = results.get('message', "Unknown error during search.")
            if "interrupted" not in error_msg.lower(): # Don't show popup if interrupted
                QMessageBox.critical(mw, "Path Search Error", error_msg)
            else:
                mw.status_label.setText("Search interrupted.")
            return

        # --- Results handling logic ---
        final_path_to_use = None
        paths_found = results.get('path_data', []) # Get the list of (path, score) tuples
        status = results.get('status', 'error')
        
        # --- NUOVO: Estrai emulator_name --- 
        emulator_name_from_results = results.get('emulator_name') # Potrebbe essere None
        logging.debug(f"PCM.on_detection_finished: Emulator name from results: {emulator_name_from_results}")
        # --- Log per il controllo della condizione PCSX2 --- 
        is_pcsx2_profile_creation = emulator_name_from_results == 'PCSX2'
        logging.debug(f"PCM.on_detection_finished: Is this a PCSX2 profile creation? {is_pcsx2_profile_creation} (Emulator name: '{emulator_name_from_results}')")
        
        # Nascondiamo l'overlay appena prima di mostrare i dialoghi di conferma
        # --- Stop Fade/Animation Effect ---
        
        if status == 'found':
            logging.debug(f"Path data found by detection thread: {paths_found}") # Updated log
            if len(paths_found) == 1:
                # One path found (now a tuple)
                single_path, single_score = paths_found[0] # Extract path and score
                reply = QMessageBox.question(mw, "Confirm Automatic Path",
                                              # Mostra solo il percorso nel messaggio
                                              f"This path has been detected:\n\n{single_path}\n\nDo you want to use it for the profile '{profile_name}'?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                              QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    final_path_to_use = single_path # Usa solo il percorso
                elif reply == QMessageBox.StandardButton.No:
                    logging.info("User rejected single automatic path. Requesting manual input.")
                    final_path_to_use = None # Forza richiesta manuale
                else: # Cancel
                    mw.status_label.setText("Profile creation cancelled.")
                    return

            elif len(paths_found) > 1: 

                show_scores = mw.developer_mode_enabled
                logging.debug(f"Handling multiple paths. Developer mode active (show scores): {show_scores}")

                # Normalize to dictionaries with optional has_saves flag (third element)
                items_for_dialog = []
                for guess in paths_found:
                    try:
                        p = guess[0]
                        s = guess[1]
                        has = bool(guess[2]) if len(guess) > 2 else None
                    except Exception:
                        continue
                    items_for_dialog.append({"path": p, "score": s, "has_saves": has})

                try:
                    from gui_components.save_path_selection_dialog import SavePathSelectionDialog
                except Exception as e_imp:
                    logging.error(f"Failed to import SavePathSelectionDialog: {e_imp}")
                    QMessageBox.critical(mw, "UI Error", "Internal UI component missing.")
                    return

                dlg = SavePathSelectionDialog(
                    items=items_for_dialog,
                    title="Confirm Save Path",
                    prompt_text=f"These potential paths have been found for '{profile_name}'.\nSelect the correct one (sorted by probability) or choose manual input:",
                    show_scores=show_scores,
                    preselect_index=0,
                    parent=mw,
                )

                if dlg.exec() == QDialog.DialogCode.Accepted:
                    if dlg.is_manual_selected():
                        logging.info("User chose manual input from multiple paths list.")
                        final_path_to_use = None
                    else:
                        final_path_to_use = dlg.get_selected_path()
                        logging.debug(f"User selected path: {final_path_to_use}")
                else:
                    mw.status_label.setText("Profile creation cancelled.")
                    return

        elif status == 'not_found':
            # No automatic path found
            QMessageBox.information(mw, "Path Not Detected", f"Unable to automatically detect the save path for '{profile_name}'.\nPlease enter it manually.")
            final_path_to_use = None # Force manual request
        else: # status == 'error' or other unexpected case
            logging.error(f"Unexpected status '{status}' from detection thread with success=True")
            mw.status_label.setText("Internal error during result handling.")
            # We could ask for manual input here? Maybe better not.
            return # Exit if the status is not 'found' or 'not_found'

        # --- Manual Input Request (if necessary) ---
        if final_path_to_use is None:
            path_prompt = f"Insert the FULL path for the profile's saves:\n'{profile_name}'"
            # Sostituisci QInputDialog.getText con la classe SavePathDialog personalizzata
            path_dialog_manual = SavePathDialog(
                parent=mw,
                window_title=mw.tr("Manual Save Path for '{0}'").format(profile_name),
                prompt_text=path_prompt,
                browse_dialog_title=mw.tr("Select Save Folder")
            )
            result_manual = path_dialog_manual.exec()
            if result_manual == QDialog.DialogCode.Accepted:
                input_path = path_dialog_manual.get_path()
                if input_path:
                    final_path_to_use = input_path
                else:
                    QMessageBox.warning(mw, "Path Error", "The path cannot be empty.")
                    mw.status_label.setText("Profile creation cancelled (empty path).")
                    return
            else: # Cancelled or rejected
                mw.status_label.setText("Profile creation cancelled.")
                return

        # --- Final Validation and Profile Saving --- 
        if final_path_to_use:
            # Use the validation function (now part of this class)
            validated_path = self.validate_save_path(final_path_to_use, profile_name)

            if validated_path:
                logging.debug(f"Final path validated: {validated_path}. Preparing to save profile '{profile_name}'")
                profile_data = {'path': validated_path}

                # --- NUOVO: Logica per PCSX2 save_dir ---
                if emulator_name_from_results == 'PCSX2':
                    logging.info(f"PCM.on_detection_finished: Detected PCSX2 profile ('{profile_name}'). Prompting for save_dir.") # ADDED LOG
                    ps2_save_dir_name, ok_ps2 = QInputDialog.getText(mw, 
                                                                     "PCSX2 Save Directory Name", 
                                                                     f"Enter the EXACT PS2 save directory name for '{profile_name}'\n(e.g., BASLUS-20314):")
                    logging.debug(f"PCM.on_detection_finished: QInputDialog for PCSX2 save_dir - ok: {ok_ps2}, name: '{ps2_save_dir_name}'") # ADDED LOG
                    if ok_ps2 and ps2_save_dir_name:
                        profile_data['save_dir'] = ps2_save_dir_name.strip()
                        logging.info(f"PCSX2 save_dir '{ps2_save_dir_name}' added for profile '{profile_name}'.")
                    elif ok_ps2 and not ps2_save_dir_name:
                        QMessageBox.warning(mw, "PCSX2 Save Dir Skipped", 
                                            "No PS2 save directory name entered. Selective backup/restore for this profile will require manual configuration or may not work as expected.")
                        logging.warning(f"User skipped PCSX2 save_dir for profile '{profile_name}'.")
                    # else: User cancelled, save_dir not added, which is fine, it's optional for now.
                # --- FINE Logica PCSX2 ---

                logging.debug(f"Saving profile '{profile_name}' with data: {profile_data}")
                mw.profiles[profile_name] = profile_data # Salva come dizionario
                if core_logic.save_profiles(mw.profiles):
                    # Update the table via the table manager in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name)
                    QMessageBox.information(mw, "Profile Created", f"Profile '{profile_name}' successfully created.")
                    mw.status_label.setText(f"Profile '{profile_name}' created.")
                else:
                    QMessageBox.critical(mw, "Error", "Unable to save the profiles file.")
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            # else: validate_save_path has already shown the error
    # --- FINE on_detection_finished ---