# gui_components/profile_creation_manager.py
# -*- coding: utf-8 -*-
import os
#import sys
import logging
import platform
import string
import re # Added for Steam URL parsing
from pathlib import Path # Added for Path().stem usage

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication, QFileDialog, QHBoxLayout, QDialog, QLineEdit, QPushButton, QVBoxLayout, QLabel, QStyle, QDialogButtonBox
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QDropEvent

from dialogs.minecraft_dialog import MinecraftWorldsDialog
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog

# Importa utility e logica
from gui_utils import DetectionWorkerThread
import minecraft_utils
import core_logic
import shortcut_utils # Importa l'intero modulo
from emulator_utils import emulator_manager # Updated import path
#import config # Import the config module
import settings_manager # Importa settings_manager.py dalla root del progetto
import configparser # For parsing .url files

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

    def _get_steam_game_details(self, app_id):
        """
        Retrieves game name and install directory for a given Steam AppID
        from main_window.installed_steam_games_dict.
        Returns a dictionary {'name': game_name, 'install_dir': install_dir} or None.
        """
        mw = self.main_window
        if not hasattr(mw, 'installed_steam_games_dict') or not mw.installed_steam_games_dict:
            logger.warning(f"Cannot get Steam game details: main_window.installed_steam_games_dict is not available or empty.")
            return None
            
        game_info = mw.installed_steam_games_dict.get(str(app_id)) # Ensure app_id is string for dict key
        if game_info and isinstance(game_info, dict) and 'name' in game_info:
            return {'name': game_info.get('name'), 'install_dir': game_info.get('install_dir')}
        else:
            logger.warning(f"Details for Steam AppID {app_id} not found or incomplete in installed_steam_games_dict.")
            return None

    # --- Method to handle Steam URL drop ---
    def handle_steam_url_drop(self, steam_url_str):
        """
        Handles a dropped Steam URL string.
        Parses the AppID, checks if the game is installed, and starts detection.
        """
        logger.info(f"Handling Steam URL drop: {steam_url_str}")
        self.reset_internal_state()

        mw = self.main_window

        app_id_match = re.search(r'steam://rungameid/(\d+)', steam_url_str)
        if not app_id_match:
            QMessageBox.warning(mw, "Invalid Steam URL", "The provided Steam URL is not valid or could not be parsed.")
            mw.status_label.setText("Invalid Steam URL detected.")
            logger.warning(f"Could not parse AppID from Steam URL: {steam_url_str}")
            self._hide_overlay_if_visible(mw)
            return

        app_id = app_id_match.group(1)
        logger.debug(f"Extracted AppID: {app_id} from URL.")

        game_details = self._get_steam_game_details(app_id)

        if game_details:
            self.game_name_suggestion = game_details['name']
            self.game_install_dir = game_details['install_dir'] 
            self.is_steam_game = True
            self.steam_app_id = app_id
            
            logger.info(f"Steam game found: '{self.game_name_suggestion}' (AppID: {self.steam_app_id}), Install Dir: {self.game_install_dir}")
            mw.status_label.setText(f"Processing Steam game: {self.game_name_suggestion}...")

            # Disabilitiamo i controlli e impostiamo il cursore di attesa
            # come facciamo nel metodo dropEvent normale
            mw.set_controls_enabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

            if not hasattr(mw, 'current_settings'):
                logger.error("MainWindow is missing 'current_settings'. Cannot proceed with detection.")
                QMessageBox.critical(mw, "Internal Error", "Required application settings are missing. Cannot start game detection.")
                self._hide_overlay_if_visible(mw)
                # Ripristiniamo i controlli e il cursore normale in caso di errore
                mw.set_controls_enabled(True)
                QApplication.restoreOverrideCursor()
                return
            
            # Utilizziamo lo stesso approccio del metodo start_steam_configuration
            # che funziona correttamente con il fade effect
            if hasattr(mw, 'loading_label') and mw.loading_label:
                mw.loading_label.setText("Searching...") # Set text for search
                mw.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                mw.loading_label.adjustSize() # Ensure label resizes to content
            
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                mw.overlay_widget.resize(mw.centralWidget().size())
                # Assicuriamoci che l'overlay non sia già attivo
                if hasattr(mw, 'overlay_active'):
                    mw.overlay_active = False
                mw.overlay_widget.show() # Show overlay first
                mw.overlay_widget.raise_() # Ensure it's on top
            
            if hasattr(mw, '_center_loading_label'):
                mw._center_loading_label() # Center label on now-visible overlay
            
            if hasattr(mw, 'loading_label') and mw.loading_label:
                mw.loading_label.show() # Explicitly show the label
            
            if hasattr(mw, 'fade_in_animation') and mw.fade_in_animation:
                mw.fade_in_animation.stop() # Stop if already running
                mw.fade_in_animation.start() # Start the animation
                logging.debug("Fade-in animation started for overlay in handle_steam_url_drop.")

            # Per i link Steam, passiamo la lista dei giochi installati di Steam
            # Questo è necessario solo per i link Steam, non per i giochi normali o gli emulatori
            steam_games_dict = None
            if hasattr(mw, 'installed_steam_games_dict') and mw.installed_steam_games_dict:
                steam_games_dict = mw.installed_steam_games_dict
                logging.debug(f"Using Steam games list with {len(steam_games_dict)} entries for detection")
            else:
                logging.debug("No Steam games list available for detection")
                
            self.detection_thread = DetectionWorkerThread(
                profile_name_suggestion=self.game_name_suggestion,
                game_install_dir=self.game_install_dir,
                current_settings=mw.current_settings,
                installed_steam_games_dict=steam_games_dict
            )
            self.detection_thread.progress.connect(self.on_detection_progress)
            self.detection_thread.finished.connect(self.on_detection_finished)
            self.detection_thread.start()
            
        else:
            QMessageBox.warning(
                mw, 
                "Steam Game Not Found", 
                f"The Steam game with AppID {app_id} does not appear to be installed, "
                "or its details could not be retrieved from your Steam library.\\n\\n"
                "Please ensure the game is installed and that SaveState has correctly "
                "identified your Steam installation."
            )
            mw.status_label.setText(f"Steam game (AppID: {app_id}) not found or not installed.")
            logger.warning(f"Steam game with AppID {app_id} not found in installed_steam_games_dict.")
            self._hide_overlay_if_visible(mw)

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

    # --- Drag and Drop Management ---
    def dragEnterEvent(self, event):
        """Handles the drag-and-drop event. Accepts if mimeData has URLs or text."""
        mime_data = event.mimeData()
        mw = self.main_window

        # Log detailed MIME data information
        logging.debug(f"PCM.dragEnterEvent: MimeData formats: {mime_data.formats()}")
        if mime_data.hasUrls():
            urls_debug_list = []
            for url_obj_debug in mime_data.urls():
                urls_debug_list.append(
                    f"URL: {url_obj_debug.toString()}, "
                    f"Scheme: {url_obj_debug.scheme()}, "
                    f"IsLocal: {url_obj_debug.isLocalFile()}, "
                    f"LocalPath: {url_obj_debug.toLocalFile() if url_obj_debug.isLocalFile() else 'N/A'}"
                )
            logging.debug(f"  PCM.dragEnterEvent: MimeData has URLs: [{', '.join(urls_debug_list)}]")
        if mime_data.hasText():
            logging.debug(f"  PCM.dragEnterEvent: MimeData has Text (first 200 chars): '{mime_data.text()[:200]}'")

        if mime_data.hasUrls() or mime_data.hasText():
            event.acceptProposedAction()
            logging.debug("PCM.dragEnterEvent: Accepted event due to presence of URLs or Text.")

            # Overlay Management
            if hasattr(mw, 'enable_global_drag_effect') and mw.settings_manager.get_setting('enable_global_drag_effect'):
                logging.debug("PCM.dragEnterEvent: Global drag effect is ON. MainWindow should handle overlay.")
            elif hasattr(mw, 'overlay_active') and mw.overlay_active:
                logging.debug("PCM.dragEnterEvent: Overlay already active (by MainWindow), PCM skipping local overlay.")
            else:
                if hasattr(mw, 'loading_label') and mw.loading_label and \
                   hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                    
                    logging.debug("PCM.dragEnterEvent: Managing local overlay indication.")
                    mw.loading_label.setText("Drop Here to Create Profile")
                    if hasattr(mw, '_center_loading_label'):
                        mw._center_loading_label()
                    
                    mw.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 200); }")
                    
                    if hasattr(mw, 'overlay_active'):
                        mw.overlay_active = True
                        logging.debug("PCM.dragEnterEvent: setting MainWindow.overlay_active = True for local overlay.")
                    
                    if hasattr(mw, 'overlay_opacity_effect'):
                        mw.overlay_opacity_effect.setOpacity(1.0)
                    
                    mw.overlay_widget.show()
                    mw.loading_label.show()
                else:
                    logging.debug("PCM.dragEnterEvent: MainWindow overlay components not found.")
        else:
            logging.debug("PCM.dragEnterEvent: Rejected event, no URLs or Text.")
            event.ignore()

    def dragMoveEvent(self, event):
        """Handles the movement of a dragged object over the widget."""
        # This event should generally accept if dragEnterEvent accepted.
        # The main purpose is to allow dropEvent to occur.
        # Specific logic for visual feedback during move can be added if needed.
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Handles the drag leave event."""
        # NON nascondiamo più l'overlay quando il drag esce dalla finestra
        # Ora il MainWindow gestisce il rilevamento globale del drag
        logging.debug("dragLeaveEvent: il cursore è uscito dalla finestra ma l'overlay rimane visibile")
        
        # Impostiamo una variabile per indicare che il drag è attivo
        mw = self.main_window
        
        # Manteniamo il flag overlay_active se esiste
        # Questo è importante per evitare che l'overlay venga mostrato di nuovo quando il cursore rientra
        if hasattr(mw, 'overlay_active') and mw.overlay_active:
            logging.debug("dragLeaveEvent: mantengo MainWindow.overlay_active = True")
            # Non facciamo nulla, il flag rimane True
        
        if hasattr(mw, 'is_drag_operation_active'):
            mw.is_drag_operation_active = True
            logging.debug("Impostato is_drag_operation_active = True in dragLeaveEvent")
            
        event.accept()

    def dropEvent(self, event: QDropEvent):
        """Handles the release of a dragged object. Prioritizes Steam URLs, then local files/shortcuts."""
        self.reset_internal_state() # Reset state at the beginning
        mw = self.main_window # Alias for main window
        mime_data = event.mimeData()

        # --- Log MIME Data --- 
        logging.debug(f"PCM.dropEvent: MimeData formats: {mime_data.formats()}")
        if mime_data.hasUrls():
            urls_debug_list = []
            for url_obj_debug in mime_data.urls():
                urls_debug_list.append(
                    f"URL: {url_obj_debug.toString()}, "
                    f"Scheme: {url_obj_debug.scheme()}, "
                    f"IsLocal: {url_obj_debug.isLocalFile()}, "
                    f"LocalPath: {url_obj_debug.toLocalFile() if url_obj_debug.isLocalFile() else 'N/A'}"
                )
            logging.debug(f"  PCM.dropEvent: MimeData has URLs: [{', '.join(urls_debug_list)}]")
        if mime_data.hasText():
            logging.debug(f"  PCM.dropEvent: MimeData has Text (first 200 chars): '{mime_data.text()[:200]}'")
        # --- End Log MIME Data ---

        # --- Overlay Fade-out --- 
        if hasattr(mw, 'overlay_widget') and mw.overlay_widget and mw.overlay_widget.isVisible():
            if hasattr(mw, 'fade_out_animation'):
                try:
                    if hasattr(mw, 'on_fade_out_finished'):
                        mw.fade_out_animation.finished.disconnect(mw.on_fade_out_finished)
                except RuntimeError: 
                    logging.debug("PCM.dropEvent: Error disconnecting on_fade_out_finished (possibly not connected or already disconnected).")
                # No explicit AttributeError catch for disconnect here, as hasattr should prevent it.

                if hasattr(mw, 'on_fade_out_finished'):
                    mw.fade_out_animation.finished.connect(mw.on_fade_out_finished)
                else:
                    logging.debug("PCM.dropEvent: MainWindow.on_fade_out_finished not found for connection. Animation will run without this specific callback.")
                
                mw.fade_out_animation.start()
                logging.debug("PCM.dropEvent: Overlay fade-out animation started.")
            else:
                # If no animation, hide directly and reset flag
                if hasattr(mw, 'overlay_widget'): mw.overlay_widget.hide()
                if hasattr(mw, 'loading_label'): mw.loading_label.hide()
                if hasattr(mw, 'overlay_active'): mw.overlay_active = False 
                logging.debug("PCM.dropEvent: Overlay hidden directly (no animation found).")
        # --- End Overlay Fade-out ---

        # --- Priority 1: Handle Steam URLs from QUrls --- 
        if mime_data.hasUrls():
            for url_obj in mime_data.urls():
                url_str = url_obj.toString()
                # Check for direct Steam URL (e.g., steam://rungameid/xxxx)
                if url_obj.scheme() == 'steam' and url_obj.host() == 'rungameid':
                    logging.info(f"PCM.dropEvent: Detected direct Steam URL: {url_str}")
                    self.handle_steam_url_drop(url_str)
                    event.acceptProposedAction()
                    return # Steam URL handled

                # Check for .url files pointing to Steam games
                if url_obj.isLocalFile():
                    local_file_path = url_obj.toLocalFile()
                    if local_file_path.lower().endswith('.url'):
                        logging.info(f"PCM.dropEvent: Detected .url file: {local_file_path}")
                        parser = configparser.ConfigParser()
                        try:
                            parser.read(local_file_path, encoding='utf-8')
                            if 'InternetShortcut' in parser and 'URL' in parser['InternetShortcut']:
                                extracted_url = parser['InternetShortcut']['URL']
                                logging.debug(f"  PCM.dropEvent: Extracted URL from .url file: {extracted_url}")
                                if extracted_url.startswith('steam://rungameid/'):
                                    logging.info(f"PCM.dropEvent: .url file points to Steam URL: {extracted_url}")
                                    self.handle_steam_url_drop(extracted_url)
                                    event.acceptProposedAction()
                                    return # Steam URL from .url file handled
                                else:
                                    logging.info(f"PCM.dropEvent: .url file does not point to a Steam game: {extracted_url}")
                            else:
                                logging.warning(f"PCM.dropEvent: .url file is missing [InternetShortcut] or URL key: {local_file_path}")
                        except configparser.Error as e_cfg:
                            logging.error(f"PCM.dropEvent: Error parsing .url file '{local_file_path}': {e_cfg}")
                        except Exception as e_file:
                            logging.error(f"PCM.dropEvent: Could not read .url file '{local_file_path}': {e_file}")
                        # If it was a .url file, accept and return, regardless of whether it was a Steam link.
                        event.acceptProposedAction()
                        return # .url file processed (or attempted)

        # --- Priority 2: Handle Steam URLs from plain text --- 
        if mime_data.hasText():
            text_content = mime_data.text()
            if text_content.startswith('steam://rungameid/'):
                logging.info(f"PCM.dropEvent: Detected Steam URL in plain text: {text_content}")
                self.handle_steam_url_drop(text_content)
                event.acceptProposedAction()
                return # Steam URL from text handled

        # --- Fallback to existing logic for local files/shortcuts --- 
        logging.debug("PCM.dropEvent: No Steam URL detected directly, proceeding with local file/shortcut logic.")

        winshell = None
        if platform.system() == "Windows":
            try:
                import winshell
                from win32com.client import Dispatch # Needed by winshell
            except ImportError:
                logging.error("The 'winshell' or 'pywin32' library is not installed. Cannot read .lnk files.")
                QMessageBox.critical(self.main_window, "Dependency Error",
                                     "The 'winshell' and 'pywin32' libraries are required to read shortcuts (.lnk) on Windows.")
                return

        file_path = None
        if mime_data.hasUrls(): # Re-check for local file URLs if Steam specific URLs weren't found
            urls = mime_data.urls()
            if urls and len(urls) == 1 and urls[0].isLocalFile(): # Ensure it's a single local file
                file_path = urls[0].toLocalFile()
                logging.info(f"PCM.dropEvent (Fallback): Processing dropped local file: {file_path}")
            else:
                # This case handles multiple files or non-local URLs not caught by Steam checks.
                logging.debug("PCM.dropEvent (Fallback): No single local file URL found for fallback. Ignoring.")
                event.ignore()
                return
        elif not mime_data.hasText(): # If no URLs and no text, nothing to process
            logging.debug("PCM.dropEvent (Fallback): No URLs or text. Ignoring.")
            event.ignore()
            return
        # If only text was present and it wasn't a Steam URL, it's ignored by this point.

        if not file_path: # Should only be true if only non-Steam text was dropped.
            logging.debug("PCM.dropEvent (Fallback): No file_path to process. Likely unhandled text. Ignoring.")
            event.ignore()
            return

        target_path = file_path
        game_install_dir = None

        is_windows_link = file_path.lower().endswith('.lnk') and platform.system() == "Windows" and winshell is not None
        is_linux_desktop = file_path.lower().endswith('.desktop') and platform.system() == "Linux"
        # Ensure it's a file and executable, not a directory
        is_linux_executable = platform.system() == "Linux" and os.access(file_path, os.X_OK) and os.path.isfile(file_path)
        
        if is_windows_link:
            logging.debug("PCM.dropEvent (Fallback): Detected Windows .lnk file, attempting to resolve target...")
            try:
                shortcut = winshell.shortcut(file_path)
                resolved_target = shortcut.path
                working_dir = shortcut.working_directory

                if not resolved_target or not os.path.exists(resolved_target):
                     logging.error(f"Could not resolve .lnk target or target does not exist: {resolved_target}")
                     QMessageBox.critical(mw, "Shortcut Error",
                                          f"Unable to resolve the shortcut path or the target file/folder does not exist:\n'{resolved_target or 'N/A'}'")
                     event.ignore()
                     return

                target_path = resolved_target
                logging.info(f"PCM.dropEvent (Fallback): Resolved .lnk target to: {target_path}")

                if working_dir and os.path.isdir(working_dir):
                    game_install_dir = os.path.normpath(working_dir)
                elif os.path.isfile(target_path):
                    game_install_dir = os.path.normpath(os.path.dirname(target_path))
                elif os.path.isdir(target_path):
                     game_install_dir = os.path.normpath(target_path)
                logging.debug(f"PCM.dropEvent (Fallback): Game folder from resolved shortcut: {game_install_dir}")
            except Exception as e_lnk:
                logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
                QMessageBox.critical(mw, "Shortcut Error", f"Unable to read the .lnk file:\n{e_lnk}")
                event.ignore()
                return
            
        elif is_linux_desktop:
            try:
                # --- BEGIN INLINE .desktop PARSING (Adattato da v1.4, SENZA ICONE) ---
                logging.debug("PCM.dropEvent (Fallback): Parsing Linux .desktop file inline...")
                parsed_exec = None
                parsed_path = None # Corrisponde a 'Path=' nel file .desktop
                # Nessuna variabile parsed_icon qui, perché hai detto che non ti serve

                with open(file_path, 'r', encoding='utf-8') as desktop_file:
                    for line in desktop_file:
                        line = line.strip()
                        if line.startswith('Exec='):
                            exec_cmd = line[5:].strip()
                            if exec_cmd.startswith('"'):
                                end_quote_idx = exec_cmd.find('"', 1)
                                if end_quote_idx != -1:
                                    parsed_exec = exec_cmd[1:end_quote_idx]
                                else: 
                                    parsed_exec = exec_cmd.split()[0]
                            else:
                                parsed_exec = exec_cmd.split()[0]

                        elif line.startswith('Path='):
                            parsed_path = line[5:].strip()
                            if parsed_path.startswith('"') and parsed_path.endswith('"'):
                                parsed_path = parsed_path[1:-1]
                
                if parsed_exec:
                    if not os.path.isabs(parsed_exec):
                        resolved_in_custom_path = False
                        if parsed_path and os.path.isdir(parsed_path):
                            potential_full_path = os.path.join(parsed_path, parsed_exec)
                            if os.path.isfile(potential_full_path) and os.access(potential_full_path, os.X_OK):
                                parsed_exec = os.path.normpath(potential_full_path)
                                resolved_in_custom_path = True
                                logging.debug(f".desktop 'Exec' ('{os.path.basename(parsed_exec)}') resolved using 'Path=' field to: {parsed_exec}")
                        
                        if not resolved_in_custom_path:
                            logging.debug(f".desktop 'Exec' ('{parsed_exec}') is relative. Searching in system PATH...")
                            system_path_dirs = os.environ.get('PATH', '').split(os.pathsep)
                            for path_dir_env in system_path_dirs:
                                full_path_env = os.path.join(path_dir_env, parsed_exec)
                                if os.path.isfile(full_path_env) and os.access(full_path_env, os.X_OK):
                                    parsed_exec = os.path.normpath(full_path_env)
                                    logging.debug(f".desktop 'Exec' resolved via system PATH to: {parsed_exec}")
                                    break 
                            else: 
                                logging.warning(f".desktop 'Exec' ('{parsed_exec}') could not be resolved to an absolute path via 'Path=' field or system PATH.")
                # --- FINE INLINE .desktop PARSING ---

                if not parsed_exec or not os.path.exists(parsed_exec):
                    logging.error(f"Could not parse 'Exec' from .desktop or resolved path does not exist: {parsed_exec}")
                    QMessageBox.critical(mw, "Desktop File Error", f"Unable to parse executable path from .desktop or the path doesn't exist:\n'{parsed_exec or 'N/A'}'")
                    event.ignore(); return

                target_path = parsed_exec 
                logging.info(f"PCM.dropEvent (Fallback): Parsed .desktop 'Exec' to target: {target_path}")

                if parsed_path and os.path.isdir(parsed_path): 
                    game_install_dir = os.path.normpath(parsed_path)
                elif os.path.isfile(target_path): 
                    game_install_dir = os.path.normpath(os.path.dirname(target_path))
                
                logging.debug(f"PCM.dropEvent (Fallback): Game install directory from .desktop: {game_install_dir}")

            except Exception as e_desktop: 
                logging.error(f"Error processing .desktop file '{file_path}': {e_desktop}", exc_info=True)
                QMessageBox.critical(mw, "Desktop File Error", f"Unable to process .desktop file:\n{file_path}\nError: {e_desktop}")
                event.ignore(); return

        elif is_linux_executable: # Already checked it's not a .desktop and is a file
            logging.debug(f"PCM.dropEvent (Fallback): Detected Linux executable: {file_path}")
            target_path = file_path
            game_install_dir = os.path.normpath(os.path.dirname(file_path))
            logging.debug(f"PCM.dropEvent (Fallback): Game folder from Linux executable: {game_install_dir}")

        # Se è un file ma non è un collegamento di Windows (.lnk), un file desktop di Linux (.desktop) o un file eseguibile di Linux
        # lo rifiutiamo per motivi di sicurezza (per evitare che l'applicazione accetti file non validi come immagini)
        elif os.path.isfile(file_path):
            logging.warning(f"PCM.dropEvent: File type not allowed: {file_path}")
            QMessageBox.warning(mw, "File Type Not Supported", 
                              f"Only Windows shortcuts (.lnk), Linux desktop files (.desktop), Linux executables, or Steam links are supported.\n\n"
                              f"The file '{os.path.basename(file_path)}' is not a valid shortcut or executable.")
            event.ignore()
            return
        elif os.path.isdir(file_path):
            logging.debug(f"PCM.dropEvent (Fallback): Processing direct folder drop: {file_path}")
            target_path = file_path # Could be the game folder itself or a folder containing the executable
            game_install_dir = os.path.normpath(file_path)
            # For directories, we might need to search for an executable later if target_path is this directory
            logging.debug(f"PCM.dropEvent (Fallback): Game folder from direct directory: {game_install_dir}")
        
        # Fallback for game_install_dir if not set by specific handlers
        if not game_install_dir and target_path and os.path.exists(target_path):
            if os.path.isfile(target_path):
                potential_dir = os.path.dirname(target_path)
                if os.path.isdir(potential_dir): game_install_dir = os.path.normpath(potential_dir)
            elif os.path.isdir(target_path): # If target_path itself is a directory
                game_install_dir = os.path.normpath(target_path)
            if game_install_dir: logging.debug(f"PCM.dropEvent (Fallback): Game install dir set by general fallback: {game_install_dir}")

        if target_path and os.path.exists(target_path):
            game_name = Path(target_path).stem
            if platform.system() == "Windows" and game_name.lower().endswith('.exe'): game_name = game_name[:-4]
            # Utilizziamo clean_for_comparison da save_path_finder invece di clean_game_name da core_logic
            from save_path_finder import clean_for_comparison
            game_name = clean_for_comparison(game_name)
            logging.info(f"PCM.dropEvent (Fallback): Extracted game name: {game_name} from target: {target_path}")
            
            # --- NOW, call emulator detection using the RESOLVED target_path ---
            # This should happen BEFORE we start the heuristic search
            emulator_result = emulator_manager.detect_and_find_profiles(target_path)
            
            # If an emulator was detected, handle it accordingly
            if emulator_result is not None:
                emulator_key, profiles_data = emulator_result
                
                # Special handling for SameBoy emulator
                if emulator_key == 'sameboy' and profiles_data is None:
                    # Try to find SameBoy profiles manually
                    try:
                        from emulator_utils import sameboy_manager
                        rom_dir = sameboy_manager.get_sameboy_saves_path()
                        if rom_dir:
                            profiles_data = sameboy_manager.find_sameboy_profiles(rom_dir)
                            if profiles_data:
                                logging.info(f"Found save files in hardcoded path: {rom_dir}")
                                logging.info(f"Found {len(profiles_data)} SameBoy profiles in directory '{rom_dir}'.")
                            else:
                                logging.warning(f"No SameBoy profiles found in directory '{rom_dir}'.")
                        else:
                            logging.warning("Could not determine SameBoy ROM directory.")
                    except Exception as e:
                        logging.error(f"Error finding SameBoy profiles: {e}")
                        QMessageBox.warning(
                            mw, "SameBoy Detection Error",
                            f"An error occurred while trying to detect SameBoy profiles: {e}\n"
                            "You can try adding the emulator again or set the path manually via settings (if available).")
                
                # Handle emulator profiles if found
                if emulator_key and profiles_data is not None: # Check if profiles_data is not None (it could be an empty list)
                    logging.info(f"Found {emulator_key} profiles: {len(profiles_data)}")
                    
                    # Show dialog for selecting which emulator game to create a profile for
                    selection_dialog = EmulatorGameSelectionDialog(emulator_key, profiles_data, mw)
                    if selection_dialog.exec():
                        selected_profile = selection_dialog.get_selected_profile_data()
                        if selected_profile:
                            # Extract details from the selected profile
                            profile_id = selected_profile.get('id', '')
                            selected_name = selected_profile.get('name', profile_id)
                            save_paths = selected_profile.get('paths', [])
                            
                            # Create a profile name based on the emulator and game
                            profile_name_base = f"{emulator_key} - {selected_name}"
                            profile_name = profile_name_base
                            
                            # Ensure unique profile name
                            counter = 1
                            while profile_name in mw.profiles:
                                profile_name = f"{profile_name_base} ({counter})"
                                counter += 1
                            
                            # Create the profile with the appropriate data
                            if emulator_key == "PPSSPP": # Specific check for multi-path emulator
                                new_profile = {
                                    'name': profile_name,
                                    'paths': save_paths,
                                    'emulator': emulator_key
                                }
                            else: # For all other emulators or no emulator detected
                                new_profile = {
                                    'name': profile_name,
                                    'paths': save_paths,
                                    'emulator': emulator_key
                                }
                            
                            # Add the profile to the main window's profiles dictionary
                            mw.profiles[profile_name] = new_profile
                            
                            # Save the profiles to disk
                            if mw.core_logic.save_profiles(mw.profiles):
                                mw.profile_table_manager.update_profile_table()
                                mw.status_label.setText(f"Profile '{profile_name}' created successfully.")
                                logging.info(f"Emulator game profile '{profile_name}' created/updated with emulator '{emulator_key}'.")
                                
                                # Select the newly created profile in the table
                                mw.profile_table_manager.select_profile_in_table(profile_name)
                            else:
                                logging.error(f"Failed to save profiles after adding '{profile_name}'.")
                                QMessageBox.critical(mw, "Save Error", "Failed to save the profiles. Check the log for details.")
                    else:
                        logging.info("User cancelled emulator game selection.")
                    
                    # Hide the overlay if it's visible
                    self._hide_overlay_if_visible(mw)
                    mw.set_controls_enabled(True)
                    QApplication.restoreOverrideCursor()
                    event.acceptProposedAction()
                    return # Return after handling emulator profiles
                elif emulator_key: # Emulator detected but no profiles found
                    logging.warning(f"{emulator_key} detected, but no profiles found in its standard directory.")
                    QMessageBox.warning(mw, f"Emulator Detected ({emulator_key})",
                                    f"Detected link to {emulator_key}, but no profiles found in its standard folder.\nCheck the emulator's save location.")
                return # IMPORTANT: Stop further processing if an emulator was detected
            
            logging.debug(f"Path '{target_path}' did not match known emulators, proceeding with standard heuristic path detection.")

            # self.game_name_input.setText(game_name) # Temporarily commented out
            # self.executable_path_input.setText(os.path.normpath(target_path)) # Temporarily commented out
            
            if game_install_dir: 
                # self.game_install_dir_input.setText(os.path.normpath(game_install_dir)) # Temporarily commented out
                pass # Added to satisfy linter for empty if-block
            else: # Final fallback for install directory if still not set
                final_fallback_dir = os.path.dirname(target_path) if os.path.isfile(target_path) else target_path
                # self.game_install_dir_input.setText(os.path.normpath(final_fallback_dir)) # Temporarily commented out
                logging.debug(f"PCM.dropEvent (Fallback): Install dir set to absolute final fallback: {final_fallback_dir}")

            # Icon handling - Temporarily commented out due to missing attributes/methods
            # if not self.current_game_icon_path: # If not set by .desktop parsing
            #     if game_install_dir: self.find_and_set_game_icon(game_install_dir, game_name)
            #     else: self.find_and_set_game_icon(os.path.dirname(self.executable_path_input.text()), game_name)
            # elif self.current_game_icon_path: # Icon was found (e.g. from .desktop)
            #     self.update_icon_preview(self.current_game_icon_path)
            # # If no icon found by any means, it will use the default
            
            # Store values in internal state variables for potential later use
            self.game_name_suggestion = game_name
            self.game_install_dir = game_install_dir
            self.executable_path = target_path
            
            # self.start_detection_process(game_name, os.path.normpath(target_path), game_install_dir) # Method doesn't exist
            logging.info(f"PCM.dropEvent: Successfully processed non-Steam game: {game_name}. Ready for detection.")
            event.acceptProposedAction()
        else:
            logging.warning(f"PCM.dropEvent (Fallback): Target path '{target_path or 'N/A'}' invalid or non-existent. Ignoring drop.")
            QMessageBox.warning(mw, "Path Error", f"Dropped item or target ('{target_path or 'N/A'}') is invalid/not found.")
            event.ignore()



            if emulator_key and profiles_data is not None: # Check if profiles_data is not None (it could be an empty list)
                logging.info(f"Found {emulator_key} profiles: {len(profiles_data)}")
                # --- Show Selection Dialog ---
                selection_dialog = EmulatorGameSelectionDialog(emulator_key, profiles_data, mw)
                if selection_dialog.exec():
                    selected_data = selection_dialog.get_selected_profile_data()
                    if selected_data:
                        selected_id = selected_data.get('id')
                        # --- Handle both single 'path' and multiple 'paths' --- START ---
                        selected_paths_list = selected_data.get('paths') # For multi-path (e.g., PPSSPP)
                        selected_path_single = selected_data.get('path')  # For single-path
                        # --- Handle both single 'path' and multiple 'paths' --- END ---

                        # --- Updated Check --- START ---
                        if not selected_id or (not selected_path_single and not selected_paths_list):
                            logging.error(f"Selected data from dialog is missing id or path(s): {selected_data}")
                        # --- Updated Check --- END ---
                            QMessageBox.critical(mw, "Internal Error", "Invalid selected profile data.")
                            return

                        selected_name = selected_data.get('name', selected_id)
                        profile_name_base = f"{emulator_key} - {selected_name}"
                        profile_name = shortcut_utils.sanitize_profile_name(profile_name_base)
                        if not profile_name:
                            QMessageBox.warning(mw, "Profile Name Error",
                                                f"Unable to generate a valid profile name for '{profile_name_base}'.")
                            return

                        if profile_name in mw.profiles:
                            reply = QMessageBox.question(mw, "Existing Profile",
                                                       f"A profile named '{profile_name}' already exists. Overwrite it?",
                                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                       QMessageBox.StandardButton.No)
                            if reply == QMessageBox.StandardButton.No:
                                mw.status_label.setText("Profile creation cancelled.")
                                return
                            else:
                                logging.warning(f"Overwriting existing profile: {profile_name}")

                        # --- Determine path data and prepare profile dictionary --- START ---
                        path_data_for_profile_list = None
                        profile_data_to_save = {}

                        if emulator_key == "PPSSPP": # Specific check for multi-path emulator
                             profile_data_to_save = {
                                 'paths': selected_paths_list, # Use the list for PPSSPP
                                 'emulator': emulator_key
                             }
                             logging.info(f"Saving profile '{profile_name}' with multiple paths (PPSSPP).")
                        else: # For all other emulators or no emulator detected
                             if selected_paths_list: # Ensure list is not empty
                                 profile_data_to_save = {
                                     'paths': selected_paths_list, # Use the ENTIRE list
                                     'emulator': emulator_key
                                 }
                                 logging.info(f"Saving profile '{profile_name}' with {len(selected_paths_list)} paths.")
                             else:
                                 # This case should ideally not be reached due to earlier checks
                                 logging.error(f"Cannot save profile '{profile_name}', path list is unexpectedly empty.")
                                 QMessageBox.critical(mw, "Internal Error", "Unable to save the profile, no valid paths available.")
                                 return
                        # --- Determine path data and prepare profile dictionary --- END ---

                        # --- Save Profile and Update UI --- START ---
                        mw.profiles[profile_name] = profile_data_to_save # Add/Update profile in memory

                        if core_logic.save_profiles(mw.profiles): # Save all profiles to file
                            logging.info(f"Emulator game profile '{profile_name}' created/updated with emulator '{emulator_key}'.")
                            if hasattr(mw, 'profile_table_manager'):
                                mw.profile_table_manager.update_profile_table()
                                mw.profile_table_manager.select_profile_in_table(profile_name) # Select the new/updated one
                            # No success message box here, status bar is enough
                            mw.status_label.setText(f"Profile '{profile_name}' created/updated.")
                        else:
                            # Error saving file
                            QMessageBox.critical(mw, "Save Error",
                                                 f"Unable to save the profiles file after adding/modifying '{profile_name}'. "
                                                       "The changes may have been lost.")
                            # Attempt to revert the change in memory if save failed
                            if profile_name in mw.profiles:
                                # Ideally, revert to previous state, but simple removal is fallback
                                del mw.profiles[profile_name]
                                logging.warning(f"Reverted profile '{profile_name}' from memory due to save failure.")
                                if hasattr(mw, 'profile_table_manager'):
                                    mw.profile_table_manager.update_profile_table() # Update table again
                        # --- Save Profile and Update UI --- END ---
            else:
                logging.warning(f"{emulator_key} detected, but no profiles found in its standard directory.")
                QMessageBox.warning(mw, f"Emulator Detected ({emulator_key})",
                                    f"Detected link to {emulator_key}, but no profiles found in its standard folder.\nCheck the emulator's save location.")
            return # IMPORTANT: Stop further processing if an emulator was detected

        # --- If NOT a known Emulator, proceed with heuristic search ---
        logging.debug(f"Path '{target_path}' did not match known emulators, proceeding with standard heuristic path detection.")
        event.acceptProposedAction() # Accept drop for heuristic

        # --- Get and Clean Profile Name (from original dropped file name) ---
        base_name = os.path.basename(file_path) # Use original file_path for name
        profile_name_temp, _ = os.path.splitext(base_name)
        profile_name_original = profile_name_temp.replace('™', '').replace('®', '').strip()
        profile_name = shortcut_utils.sanitize_profile_name(profile_name_original)
        logging.info(f"Original Name (basic clean): '{profile_name_original}', Sanitized Name: '{profile_name}'")

        if not profile_name:
            logging.error(f"Sanitized profile name for '{profile_name_original}' became empty!")
            QMessageBox.warning(mw, "Profile Name Error",
                                "Unable to generate a valid profile name from the dragged shortcut.")
            return

        if profile_name in mw.profiles:
            QMessageBox.warning(mw, "Existing Profile", f"Profile '{profile_name}' already exists.")
            return

        # --- Start Heuristic Path Search Thread ---
        if self.detection_thread and self.detection_thread.isRunning():
            QMessageBox.information(mw, "Operation in Progress", "Another path search is already in progress. Please wait.")
            return

        mw.set_controls_enabled(False)
        mw.status_label.setText(f"Searching...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # --- Start Fade/Animation Effect ---
        try:
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                mw.overlay_widget.resize(mw.centralWidget().size())
                # Utilizziamo lo stesso approccio del metodo start_steam_configuration
                # che funziona correttamente con il fade effect
                if hasattr(mw, 'loading_label') and mw.loading_label:
                    mw.loading_label.setText("Searching...") # Set text for search
                    mw.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                    mw.loading_label.adjustSize() # Ensure label resizes to content
                
                if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                    mw.overlay_widget.resize(mw.centralWidget().size())
                    # Assicuriamoci che l'overlay non sia già attivo
                    if hasattr(mw, 'overlay_active'):
                        mw.overlay_active = False
                    mw.overlay_widget.show() # Show overlay first
                    mw.overlay_widget.raise_() # Ensure it's on top
                
                if hasattr(mw, '_center_loading_label'):
                    mw._center_loading_label() # Center label on now-visible overlay
                
                if hasattr(mw, 'loading_label') and mw.loading_label:
                    mw.loading_label.show() # Explicitly show the label
                
                if hasattr(mw, 'fade_in_animation') and mw.fade_in_animation:
                    mw.fade_in_animation.stop() # Stop if already running
                    mw.fade_in_animation.start() # Start the animation
                    logging.debug("Fade-in animation started for overlay in dropEvent.")
                
                # Non impostiamo più un timer per nascondere l'overlay
                # L'overlay rimarrà visibile fino al completamento della ricerca
                # e verrà nascosto nel metodo on_detection_finished
                
                logging.debug("Fade-in animation started with 'Searching...' text.")
            else:
                logging.warning("Overlay widget or fade animation not found in MainWindow.")
        except Exception as e_fade_start:
            logging.error(f"Error starting fade/animation effect: {e_fade_start}", exc_info=True)
        # --- FINE Start Fade/Animation Effect ---

        # Create and start the path detection thread
        self.detection_thread = DetectionWorkerThread(
            game_install_dir=game_install_dir, # Use derived install dir
            profile_name_suggestion=profile_name,
            current_settings=mw.current_settings.copy(),
            installed_steam_games_dict=None # Non-Steam game, no need to pass Steam games list
        )
        self.detection_thread.progress.connect(self.on_detection_progress)
        self.detection_thread.finished.connect(self.on_detection_finished)
        self.detection_thread.start()
        logging.debug("Heuristic path detection thread started.")
    # --- FINE dropEvent ---

    # --- Slot for Path Detection Progress ---
    @Slot(str)
    def on_detection_progress(self, message):
        """Updates the status bar of main_window with messages from the thread."""
        if message and self.main_window:
            self.main_window.status_label.setText(message)
            
    def _hide_overlay_if_visible(self, main_window):
        """Nasconde l'overlay se è visibile usando l'animazione fade-out."""
        if hasattr(main_window, 'overlay_widget') and main_window.overlay_widget and main_window.overlay_widget.isVisible():
            if hasattr(main_window, 'fade_out_animation') and main_window.fade_out_animation:
                main_window.fade_out_animation.start()
                logging.debug("Animazione fade-out avviata dal timer di sicurezza")
            else:
                # Fallback se l'animazione non è disponibile
                main_window.overlay_widget.hide()
                if hasattr(main_window, 'loading_label') and main_window.loading_label:
                    main_window.loading_label.hide()
                logging.debug("Overlay nascosto direttamente (senza animazione) dal timer di sicurezza")
    # --- FINE on_detection_progress ---

    # --- Slot for Path Detection Finished ---
    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Called when the path detection thread has finished."""
        mw = self.main_window
        logging.debug(f"Detection thread finished. Success: {success}, Results: {results}")
        
        # Nascondiamo l'overlay appena prima di mostrare i dialoghi di conferma
        # Questo garantisce che l'overlay non rimanga visibile durante l'interazione con i dialoghi
        # ma che la transizione sia comunque fluida
        
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
                manual_entry_text = "[Enter Manually...]"
                choices.append(manual_entry_text)
                # Associate the manual option text to None in the map
                display_str_to_path_map[manual_entry_text] = None

                logging.debug(f"Choices prepared for QInputDialog: {choices}")

                # Show the QInputDialog.getItem dialog
                chosen_display_str, ok = QInputDialog.getItem(
                    mw,
                    "Confirm Save Path",
                    f"These potential paths have been found for '{profile_name}'.\nSelect the correct one (sorted by probability) or choose manual input:",
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
                    mw.status_label.setText("Profile creation cancelled.")
                    return # Exit the on_detection_finished function

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
            input_path, ok_manual = QInputDialog.getText(mw, "Manual Save Path", path_prompt)
            if ok_manual and input_path:
                final_path_to_use = input_path
            elif ok_manual and not input_path:
                QMessageBox.warning(mw, "Path Error", "The path cannot be empty.")
                mw.status_label.setText("Profile creation cancelled (empty path).")
                return
            else: # Cancelled
                mw.status_label.setText("Profile creation cancelled.")
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
                    QMessageBox.information(mw, "Profile Created", f"Profile '{profile_name}' successfully created.")
                    mw.status_label.setText(f"Profile '{profile_name}' created.")
                else:
                    QMessageBox.critical(mw, "Error", "Unable to save the profiles file.")
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            # else: validate_save_path has already shown the error
    # --- FINE on_detection_finished ---