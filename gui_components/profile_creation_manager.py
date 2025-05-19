# gui_components/profile_creation_manager.py
# -*- coding: utf-8 -*-
import os
#import sys
import logging
import platform
import string

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication, QFileDialog, QHBoxLayout, QDialog, QLineEdit, QPushButton, QVBoxLayout, QLabel, QStyle, QDialogButtonBox
from PySide6.QtCore import Qt, Slot

# Importa dialoghi specifici se servono (es. Minecraft)
from dialogs.minecraft_dialog import MinecraftWorldsDialog
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog

# Importa utility e logica
from gui_utils import DetectionWorkerThread
import minecraft_utils
import core_logic
import shortcut_utils # Importa l'intero modulo
from emulator_utils import emulator_manager # Updated import path
import config # Import the config module
import settings_manager # Importa settings_manager.py dalla root del progetto

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
            mw.status_label.setText("World selection cancelled.")
    # --- FINE handle_minecraft_button ---

    # --- Drag and Drop Management ---
    def dragEnterEvent(self, event):
        """Handles the drag-and-drop event."""
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            # Accept only if it's a SINGLE file
            if urls and len(urls) == 1 and urls[0].isLocalFile():
                file_path = urls[0].toLocalFile()
                # Windows: Accept .lnk files
                # Linux: Accept .desktop files and executables
                if platform.system() == "Windows" and file_path.lower().endswith('.lnk'):
                    event.acceptProposedAction()
                    logging.debug("DragEnterEvent: Accepted Windows .lnk file.")
                elif platform.system() == "Linux" and (file_path.lower().endswith('.desktop') or 
                                                     os.access(file_path, os.X_OK)):
                    event.acceptProposedAction()
                    logging.debug(f"DragEnterEvent: Accepted Linux file: {file_path}")
                else:
                    logging.debug(f"DragEnterEvent: Rejected file: {file_path}")
                    event.ignore()
            else:
                logging.debug("DragEnterEvent: Rejected (not a single file).")
                event.ignore()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Handles the movement of a dragged object over the widget."""
        # The acceptance logic is the same as dragEnterEvent
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if urls and len(urls) == 1 and urls[0].isLocalFile():
                file_path = urls[0].toLocalFile()
                # Windows: Accept .lnk files
                # Linux: Accept .desktop files and executables
                if platform.system() == "Windows" and file_path.lower().endswith('.lnk'):
                    event.acceptProposedAction()
                elif platform.system() == "Linux" and (file_path.lower().endswith('.desktop') or 
                                                     os.access(file_path, os.X_OK)):
                    event.acceptProposedAction()
                else:
                    event.ignore()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handles the release of a dragged object and starts the path search."""
        # Import winshell ONLY if on Windows and needed
        winshell = None
        if platform.system() == "Windows":
            try:
                import winshell
                from win32com.client import Dispatch # Needed by winshell
            except ImportError:
                logging.error("The 'winshell' or 'pywin32' library is not installed. Cannot read .lnk files.")
                QMessageBox.critical(self.main_window, "Dependency Error",
                                     "The 'winshell' and 'pywin32' libraries are required to read shortcuts (.lnk) on Windows.")
                event.ignore()
                return
        # --- End Conditional Import ---

        mw = self.main_window # Alias for main window
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        if not (urls and len(urls) == 1 and urls[0].isLocalFile()):
            event.ignore()
            return

        file_path = urls[0].toLocalFile()
        logging.info(f"DropEvent: Processing dropped file: {file_path}")

        target_path = file_path # Default: use the dropped path itself
        game_install_dir = None # Initialize install dir

        # --- Resolve .lnk if applicable (Windows only) ---
        is_windows_link = file_path.lower().endswith('.lnk') and platform.system() == "Windows" and winshell is not None
        is_linux_desktop = file_path.lower().endswith('.desktop') and platform.system() == "Linux"
        is_linux_executable = platform.system() == "Linux" and os.access(file_path, os.X_OK)
        
        if is_windows_link:
            logging.debug("Detected Windows .lnk file, attempting to resolve target...")
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

                target_path = resolved_target # Use the RESOLVED path for detection
                logging.info(f"Resolved .lnk target to: {target_path}")

                # Determine game_install_dir from resolved link
                if working_dir and os.path.isdir(working_dir):
                    game_install_dir = os.path.normpath(working_dir)
                elif os.path.isfile(target_path): # If target is a file
                    game_install_dir = os.path.normpath(os.path.dirname(target_path))
                elif os.path.isdir(target_path): # If target is a directory itself
                     game_install_dir = os.path.normpath(target_path)
                else:
                    logging.warning(f"Unable to determine game folder from resolved shortcut: {file_path}")
                logging.debug(f"Game folder derived from resolved shortcut: {game_install_dir}")
            except Exception as e_lnk:
                logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
                QMessageBox.critical(mw, "Shortcut Error", f"Unable to read the .lnk file:\n{e_lnk}")
                event.ignore()
                return
                
        # --- Parse .desktop file if applicable (Linux only) ---
        elif is_linux_desktop:
            logging.debug("Detected Linux .desktop file, parsing for executable path...")
            try:
                # Parse .desktop file to extract Exec and Path fields
                exec_path = None
                working_dir = None
                
                with open(file_path, 'r', encoding='utf-8') as desktop_file:
                    for line in desktop_file:
                        line = line.strip()
                        if line.startswith('Exec='):
                            # Extract the executable path, removing parameters
                            exec_cmd = line[5:].strip()
                            # Remove parameters (anything after space that starts with %)
                            exec_parts = exec_cmd.split()
                            exec_path = exec_parts[0]
                            # Handle quoted paths
                            if exec_path.startswith('"') and exec_path.endswith('"'):
                                exec_path = exec_path[1:-1]
                        elif line.startswith('Path='):
                            working_dir = line[5:].strip()
                            # Handle quoted paths
                            if working_dir.startswith('"') and working_dir.endswith('"'):
                                working_dir = working_dir[1:-1]
                
                if exec_path:
                    # If exec_path is not absolute, try to find it in PATH
                    if not os.path.isabs(exec_path):
                        # Try to find the executable in PATH
                        for path_dir in os.environ.get('PATH', '').split(os.pathsep):
                            full_path = os.path.join(path_dir, exec_path)
                            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                                exec_path = full_path
                                break
                    
                    target_path = exec_path
                    logging.info(f"Parsed .desktop file, found executable: {target_path}")
                    
                    # Determine game_install_dir
                    if working_dir and os.path.isdir(working_dir):
                        game_install_dir = os.path.normpath(working_dir)
                    elif os.path.isfile(target_path):
                        game_install_dir = os.path.normpath(os.path.dirname(target_path))
                    
                    logging.debug(f"Game folder derived from .desktop file: {game_install_dir}")
                else:
                    logging.error("Could not find Exec= line in .desktop file")
                    QMessageBox.critical(mw, "Desktop File Error", 
                                        f"Could not find executable path in .desktop file:\n{file_path}")
                    event.ignore()
                    return
                    
            except Exception as e_desktop:
                logging.error(f"Error parsing .desktop file: {e_desktop}", exc_info=True)
                QMessageBox.critical(mw, "Desktop File Error", 
                                    f"Error parsing .desktop file:\n{e_desktop}")
                event.ignore()
                return
                
        # --- Handle Linux executable ---
        elif is_linux_executable:
            logging.debug(f"Detected Linux executable: {file_path}")
            target_path = file_path
            
            # For executables, use the parent directory as the game install directory
            if os.path.isfile(target_path):
                game_install_dir = os.path.normpath(os.path.dirname(target_path))
            elif os.path.isdir(target_path):
                game_install_dir = os.path.normpath(target_path)
                
            logging.debug(f"Game folder derived from executable: {game_install_dir}")
            
        else:
            # If not a special file type, determine game_install_dir from the dropped path itself
            if os.path.isfile(target_path):
                game_install_dir = os.path.normpath(os.path.dirname(target_path))
            elif os.path.isdir(target_path):
                 game_install_dir = os.path.normpath(target_path)
            logging.debug(f"Dropped item is a regular file/folder. Using path: {target_path}, Derived install dir: {game_install_dir}")
        # --- End Link Resolution ---

        # --- NOW, call emulator detection using the RESOLVED target_path ---
        logging.debug(f"Calling detect_and_find_profiles with path: {target_path}")
        emulator_result = emulator_manager.detect_and_find_profiles(target_path)

        # --- Handle Emulator Result (IF found) ---
        if emulator_result is not None:
            emulator_key, profiles_data = emulator_result
            event.acceptProposedAction() # Ensure accepted

            if emulator_key == 'sameboy' and profiles_data is None:
                logging.info("SameBoy detected, but no save/ROM path found. Prompting user for ROM directory.")
                
                settings, _ = settings_manager.load_settings()
                initial_rom_path = settings.get('last_rom_folder', os.path.expanduser("~"))

                rom_path_dialog = SavePathDialog(
                    parent=self.main_window,
                    window_title=self.main_window.tr("Select SameBoy ROMs Folder"),
                    prompt_text=self.main_window.tr(
                        "SameBoy needs to know where your Game Boy / Game Boy Color ROMs are stored.\n"
                        "Please enter or browse to the folder containing your ROMs (.gb, .gbc files).\n"
                        "Save files (.sav) are usually in this same folder or a 'Saves' subfolder."
                    ),
                    initial_path=initial_rom_path,
                    browse_dialog_title=self.main_window.tr("Select ROMs Folder")
                )
                dialog_result = rom_path_dialog.exec()
                user_rom_dir = None
                if dialog_result == QDialog.DialogCode.Accepted:
                    user_rom_dir = rom_path_dialog.get_path()

                if user_rom_dir and os.path.isdir(user_rom_dir):
                    logging.info(f"User selected SameBoy ROM directory: {user_rom_dir}")
                    s, _ = settings_manager.load_settings() # Carica di nuovo per evitare sovrascritture se modificate altrove
                    s['sameboy_roms_path'] = user_rom_dir
                    s['last_rom_folder'] = user_rom_dir # Salva per usi futuri
                    settings_manager.save_settings(s) # Assicura che le impostazioni siano scritte
                    
                    # Ora che abbiamo il percorso ROM, proviamo di nuovo a trovare i profili
                    # find_sameboy_profiles userà questo percorso dalle impostazioni
                    log.info(f"Re-calling find_sameboy_profiles with user-defined ROM path: {user_rom_dir}")
                    # È importante passare il percorso effettivo dell'eseguibile di SameBoy qui, non la cartella ROM.
                    # get_sameboy_saves_path all'interno di find_sameboy_profiles leggerà il percorso ROM salvato.
                    path_for_finder = self.extract_path_from_event(event)
                    if os.path.isfile(path_for_finder):
                        path_for_finder = os.path.dirname(path_for_finder)
                        
                    updated_profiles = find_sameboy_profiles(path_for_finder) 
                    
                    if updated_profiles:
                        logging.info(f"Found {len(updated_profiles)} SameBoy profiles after user provided ROM directory.")
                        # Mostra il dialogo di selezione del gioco per questi profili
                        self.show_game_selection_dialog(updated_profiles, 'sameboy', executable_path)
                    elif updated_profiles == []: # Nessun salvataggio trovato MA la cartella ROM è valida
                        logging.warning(f"User provided ROM directory '{user_rom_dir}', but still no .sav/.srm files found by find_sameboy_profiles.")
                        QMessageBox.information(self.main_window, 
                                                self.main_window.tr("No Save Files Found"), 
                                                self.main_window.tr("The selected ROMs directory for SameBoy does not appear to contain any save files (.sav, .srm).\n" \
                                                  "Please ensure you have selected the correct folder where your ROMs and their corresponding saves are located."))
                    else: # updated_profiles is None (improbabile qui, ma per completezza)
                        logging.error("find_sameboy_profiles returned None unexpectedly after user provided ROM directory.")
                        QMessageBox.warning(self.main_window, 
                                            self.main_window.tr("Error Finding Saves"), 
                                            self.main_window.tr("An unexpected error occurred while trying to find save files in the selected SameBoy ROMs directory."))
                else:
                    if dialog_result != QDialog.DialogCode.Rejected:
                        logging.warning(f"Invalid SameBoy ROM directory selected or no path returned: {user_rom_dir}")
                        QMessageBox.warning(self.main_window, 
                                            self.main_window.tr("Invalid Folder"), 
                                            self.main_window.tr("The selected path is not a valid directory. Please select a valid folder for SameBoy ROMs."))
                    else:
                        logging.info("User cancelled SameBoy ROM directory selection.")
                        QMessageBox.information(self.main_window, 
                                                self.main_window.tr("SameBoy Setup Incomplete"),  
                                                self.main_window.tr("Profile creation for SameBoy cannot proceed without a ROMs directory.\n" \
                                                  "You can try adding the emulator again or set the path manually via settings (if available)."))
                event.accept()
                return # Stop further processing for this drop event
            # --- End SameBoy Specific ---

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
        mw.status_label.setText(f"Searching path for '{profile_name}'...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # --- Start Fade/Animation Effect ---
        try:
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                mw.overlay_widget.resize(mw.centralWidget().size())
                if hasattr(mw, '_center_loading_label'): mw._center_loading_label()
                mw.overlay_widget.show()
                if hasattr(mw, 'fade_in_animation'): mw.fade_in_animation.start()
                logging.debug("Fade-in animation started.")
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
            installed_steam_games_dict=None # Pass Steam games if available
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