# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QListWidgetItem, QLineEdit
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer, QEvent

# Import necessary logic
import core_logic
import logging
import os

# --- Steam Game Management Dialog ---
class SteamDialog(QDialog):
    """
    Dialog for displaying installed Steam games, selecting one to configure its save path.
    """
    #profile_configured = Signal(str, str) # Signal emitted when a profile is configured (name, path)
    game_selected_for_config = Signal(str, str)

    def __init__(self, main_window_ref, parent=None):
        super().__init__(parent)
        self.main_window_ref = main_window_ref
        self.setWindowTitle("Steam Games Management")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # Internal references
        self.steam_search_thread = None 
        self.profiles = parent.profiles if parent and hasattr(parent, 'profiles') else {}
        self.steam_games_data = parent.steam_games_data if parent and hasattr(parent, 'steam_games_data') else {} 
        self.steam_userdata_info = parent.steam_userdata_info if parent and hasattr(parent, 'steam_userdata_info') else {} 

        # --- Create UI Widgets ---
        self.game_list_widget = QListWidget()
        self.status_label = QLabel("Select a game and click Configure.")
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setVisible(False)

        self.configure_button = QPushButton("Configure Selected Profile")
        self.refresh_button = QPushButton("Refresh Games List")
        self.close_button = QPushButton("Close")
        self.configure_button.setEnabled(False)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Installed Steam Games:"))
        layout.addWidget(self.game_list_widget)
        layout.addWidget(self.status_label)
        
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.refresh_button)
        h_layout.addWidget(self.search_bar)
        h_layout.addStretch()
        h_layout.addWidget(self.configure_button)
        h_layout.addWidget(self.close_button)
        layout.addLayout(h_layout)

        # --- Signal/Slot connections ---
        self.configure_button.clicked.connect(self._emit_selection_and_accept)
        self.refresh_button.clicked.connect(self.start_steam_scan)
        self.close_button.clicked.connect(self.reject)
        self.search_bar.textChanged.connect(self.filter_game_list)
        self.game_list_widget.currentItemChanged.connect(
            lambda item: self.configure_button.setEnabled(item is not None)
        )
        self.game_list_widget.itemDoubleClicked.connect(self._handle_double_click)

        # Install event filter to capture key presses on the list widget
        self.game_list_widget.installEventFilter(self)

        # Populate the list
        self.populate_game_list()
    
    @Slot()
    def start_steam_scan(self):
         # Update the data in the parent (MainWindow) if you refresh here!
         parent_window = self.parent()
         if parent_window:
             parent_window.steam_games_data = self.steam_games_data
             parent_window.steam_userdata_info = self.steam_userdata_info
         self.populate_game_list() 
         self.status_label.setText(f"List updated. {len(self.steam_games_data)} games found.")


    def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data:
             self.game_list_widget.addItem("No games found.")
             self.configure_button.setEnabled(False) 
             return

        self.configure_button.setEnabled(self.game_list_widget.currentItem() is not None) 
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        for appid, game_data in sorted_games:
            profile_exists_marker = "[EXISTING PROFILE]" if game_data['name'] in self.profiles else ""
            item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists_marker}".strip()
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, appid)
            self.game_list_widget.addItem(item)
    
    # --- METHOD to emit signal and close ---
    @Slot()
    def _emit_selection_and_accept(self):
        current_item = self.game_list_widget.currentItem()
        if not current_item:
            return

        appid = current_item.data(Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)

        if not game_data or not appid:
             QMessageBox.warning(self, "Error", "Unable to get data for the selected game.")
             return

        profile_name = game_data['name']
        logging.info(f"[SteamDialog] Game selected: '{profile_name}' (AppID: {appid}). Emitting signal and closing.")
        self.game_selected_for_config.emit(appid, profile_name)
        self.accept() 
        
    # --- METHOD to handle double-click on game list ---
    @Slot(QListWidgetItem)
    def _handle_double_click(self, item):
        """Handle double-click on a game in the list to automatically select it."""
        if not item:
            return
            
        # Get the AppID from the item's user data
        appid = item.data(Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)
        
        if not game_data or not appid:
            QMessageBox.warning(self, "Error", "Unable to get data for the selected game.")
            return
            
        profile_name = game_data['name']
        logging.info(f"[SteamDialog] Game double-clicked: '{profile_name}' (AppID: {appid}). Emitting signal and closing.")
        self.status_label.setText(f"Selected: {profile_name}")
        
        # Emit the signal and close the dialog, just like clicking the Configure button
        self.game_selected_for_config.emit(appid, profile_name)
        self.accept() 
        
    @Slot(list, bool)
    def on_steam_search_finished(self, guesses_with_scores, effect_was_shown):
        """Slot called when SteamSearchWorkerThread has finished the search."""
        # Import necessary here
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        import os
        main_window = self.main_window_ref

        # Try to import MainWindow for type checking and developer mode
        try:
             from SaveState_gui import MainWindow
        except ImportError:
             MainWindow = None

        # --- LOG INPUT RAW ---
        logging.debug(f"ON_SEARCH_FINISHED: Received {len(guesses_with_scores)} raw guesses from core_logic:")
        if not guesses_with_scores:
             logging.debug("  (List is empty)")
        else:
             max_raw_to_log = 20
             for idx, (raw_p, raw_s) in enumerate(guesses_with_scores[:max_raw_to_log]):
                 logging.debug(f"  Raw Guess {idx}: Path='{raw_p}', Score={raw_s}")
             if len(guesses_with_scores) > max_raw_to_log:
                 logging.debug(f"  (Plus {len(guesses_with_scores) - max_raw_to_log} more raw guesses)")
        # --- END LOG INPUT RAW ---

        main_window = self.main_window_ref
        if effect_was_shown and MainWindow is not None and isinstance(main_window, MainWindow):
             logging.debug("[SteamDialog] Deactivating fade effect on MainWindow...")
             try:
                  if hasattr(main_window, 'fade_out_animation'): main_window.fade_out_animation.start()
                  elif hasattr(main_window, 'overlay_widget'): main_window.overlay_widget.hide()
             except Exception as e_fade_stop:
                  logging.error(f"Error stopping fade effect: {e_fade_stop}", exc_info=True)
                  if hasattr(main_window, 'overlay_widget'): main_window.overlay_widget.hide()

        # --- HANDLE SEARCH RESULTS ---
        self.setEnabled(True)

        profile_name = getattr(self, 'current_configuring_profile_name', None)
        if not profile_name:
            logging.error("[SteamDialog] Could not retrieve profile name in on_steam_search_finished. Aborting config.")
            QMessageBox.critical(self, "Internal Error",
                                 "Unable to retrieve the profile name being configured.")
            self.reject() 
            return

        confirmed_path = None 
        existing_path = self.profiles.get(profile_name)
        logging.debug(f"ON_SEARCH_FINISHED: Existing path for '{profile_name}' is '{existing_path}'")

        # --- Logic to choose/confirm the path ---
        if not guesses_with_scores: 
            logging.info("ON_SEARCH_FINISHED: No paths guessed by core_logic.")
            if not existing_path:
                # No suggestions and no existing profile -> Force manual input
                logging.debug("  No existing path found. Forcing manual input.")
                QMessageBox.information(self, "Path Not Found",
                                        f"Unable to automatically find a path for '{profile_name}'.\n"
                                        "Please enter it manually.")
                confirmed_path = self._ask_for_manual_path(profile_name, existing_path) 
            else:
                # No suggestions, but profile exists -> Ask if to keep or enter manually
                logging.debug(f"  Existing path '{existing_path}' found. Asking user.")
                reply = QMessageBox.question(self, "No New Path Found",
                                             f"The automatic search did not find any new paths.\n"
                                             f"Do you want to keep the current path?\n'{existing_path}'",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    logging.debug("  User chose to keep existing path.")
                    confirmed_path = existing_path
                elif reply == QMessageBox.StandardButton.No:
                     logging.debug("  User chose to enter path manually.")
                     confirmed_path = self._ask_for_manual_path(profile_name, existing_path) 
                else: 
                    logging.debug("  User cancelled.")
                    self.status_label.setText("Configuration cancelled.")
                    self.reject()
                    return 
        # --- END RESTORED BLOCK ---

        else: 
            # Prepare items for custom dialog
            show_scores = False
            if MainWindow is not None and isinstance(main_window, MainWindow) and hasattr(main_window, 'developer_mode_enabled'):
                show_scores = main_window.developer_mode_enabled

            items_for_dialog = []
            added_normalized = set()
            current_selection_index = 0
            for i, guess in enumerate(guesses_with_scores):
                try:
                    p = guess[0]
                    s = guess[1]
                    has = bool(guess[2]) if len(guess) > 2 else None
                except Exception:
                    continue
                norm_lower = os.path.normpath(p).lower()
                if norm_lower in added_normalized:
                    continue
                added_normalized.add(norm_lower)
                items_for_dialog.append({"path": p, "score": s, "has_saves": has})
                if existing_path and os.path.normpath(p) == existing_path:
                    current_selection_index = len(items_for_dialog) - 1

            try:
                from gui_components.save_path_selection_dialog import SavePathSelectionDialog
            except Exception as e_imp:
                logging.error(f"Failed to import SavePathSelectionDialog: {e_imp}")
                QMessageBox.critical(self, "UI Error", "Internal UI component missing.")
                self.reject(); return

            dialog_text = (
                f"These potential paths have been found for '{profile_name}'.\n"
                "Select the correct one (sorted by probability) or choose manual entry:"
            )
            dlg = SavePathSelectionDialog(
                items=items_for_dialog,
                title="Confirm Save Path",
                prompt_text=dialog_text,
                show_scores=show_scores,
                preselect_index=current_selection_index,
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.is_manual_selected():
                    confirmed_path = self._ask_for_manual_path(profile_name, existing_path)
                else:
                    confirmed_path = dlg.get_selected_path()
                    if not confirmed_path:
                        self.reject(); return
            else:
                self.status_label.setText("Configuration cancelled.")
                self.reject(); return

        # --- Save Profile  ---
        if confirmed_path:
             logging.info(f"Saving profile '{profile_name}' with path '{confirmed_path}'")
             self.profiles[profile_name] = confirmed_path
             if core_logic.save_profiles(self.profiles):
                  self.status_label.setText(f"Profile '{profile_name}' configured.")
                  self.profile_configured.emit(profile_name, confirmed_path)
                  self.accept() 
             else:
                  QMessageBox.critical(self, "Save Error",
                                         "Unable to save the profiles file.")
                  self.status_label.setText("Error while saving profiles.")
                  self.reject() 
        else:
             # confirmed_path è None (manuale annullato o errore validazione nel blocco 'if not guesses')
             logging.warning(f"Configuration cancelled or failed for profile '{profile_name}' (confirmed_path is empty/None).")
             # The status label is already set in the blocks above in case of cancellation
             self.reject() 

    def _get_validator_func(self):
        """Returns the path validation function, taking it from MainWindow if possible."""
        main_window = self.main_window_ref
        validator_func = None
        if main_window and hasattr(main_window, 'profile_creation_manager') and \
           hasattr(main_window.profile_creation_manager, 'validate_save_path'):
            validator_func = main_window.profile_creation_manager.validate_save_path
            logging.debug("[SteamDialog] Using MainWindow's profile path validator.")
        else:
            # Fallback to a very simple validation (exists and is a directory?)
            logging.warning("[SteamDialog] MainWindow validator not found, using basic os.path.isdir validation.")
            def basic_validator(path_to_validate, _profile_name):
                if not path_to_validate or not os.path.isdir(path_to_validate):
                     QMessageBox.warning(self, "Path Error", 
                                         "The specified path does not exist or is not a valid folder.") 
                     return None
                return path_to_validate 
            validator_func = basic_validator
        return validator_func

    def _ask_for_manual_path(self, profile_name, existing_path):
        """Ask the user to enter a path manually and validate it."""
        validator_func = self._get_validator_func()
        manual_path, ok = QInputDialog.getText(
            self, "Manual Path", 
            f"Enter the COMPLETE save path for '{profile_name}':", 
            text=existing_path if existing_path else "" 
        )

        if ok and manual_path:
            # Use the validator to check the entered path
            validated_path = validator_func(manual_path, profile_name) 
            if validated_path:
                return validated_path 
            else:
                # The validator has failed (and should have shown a message)
                return None
        elif ok and not manual_path: 
             QMessageBox.warning(self, "Path Error", "The path cannot be empty.") 
             return None 
        else: 
            return None 

    def eventFilter(self, source, event):
        """
        Event filter to capture key presses on child widgets (like the list)
        to activate the search bar.
        """
        if source is self.game_list_widget and event.type() == QEvent.Type.KeyPress:
            if not self.search_bar.isVisible() and len(event.text()) > 0 and event.text().isalnum():
                self.search_bar.setVisible(True)
                self.search_bar.setFocus()
                self.search_bar.setText(event.text())
                return True  # Event handled, don't pass it to the list widget

        return super().eventFilter(source, event)

    def filter_game_list(self, text):
        """Filters the game list based on the search text."""
        if not text:
            self.search_bar.setVisible(False)
            self.game_list_widget.setFocus()

        for i in range(self.game_list_widget.count()):
            item = self.game_list_widget.item(i)
            # Make item visible if text is found in the item's text, case-insensitive
            item.setHidden(text.lower() not in item.text().lower())

    def reject(self):
        logging.debug("[SteamDialog] Dialog rejected.")
        
        # Cancella tutti i thread di ricerca in corso quando la dialog viene chiusa
        if self.main_window_ref and hasattr(self.main_window_ref, 'cancellation_manager'):
            logging.info("[SteamDialog] Cancelling all running search threads...")
            self.main_window_ref.cancellation_manager.cancel()
            
            # Ferma il thread di ricerca corrente se esiste
            if hasattr(self.main_window_ref, 'current_search_thread') and self.main_window_ref.current_search_thread:
                if self.main_window_ref.current_search_thread.isRunning():
                    logging.info("[SteamDialog] Waiting for current search thread to finish...")
                    self.main_window_ref.current_search_thread.wait(3000)  # Aspetta max 3 secondi
        
        super().reject()

    def accept(self):
        super().accept() 

# --- FINE CLASSE SteamDialog ---

# Block for standalone testing (optional)
if __name__ == '__main__':
    import sys
    # Configure base logging to see output during testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    # Simulate some data that the MainWindow would pass
    class MockMainWindow:
        def __init__(self):
            self.profiles = {"Existing Game": "C:/Saves/ExistingGame"}
            # Simulate components for fade effect (but not the effect itself)
            self.overlay_widget = None # QLabel("Overlay") # You could create fake widgets if needed
            self.loading_label = None # QLabel("Loading...")
            self.fade_in_animation = None # QPropertyAnimation()
            self.fade_out_animation = None # QPropertyAnimation()
            self.developer_mode_enabled = True # For testing scores

        def centralWidget(self): # Necessary for resize overlay
             return self # Or another fake widget

        def _center_loading_label(self): pass # Fake function

        # Simulate validator (in a real ProfileCreationManager)
        class MockProfileManager:
             def validate_save_path(self, path, name):
                 print(f"MockValidator: Validating '{path}' for '{name}'")
                 if os.path.isdir(path):
                     print("MockValidator: Path is valid.")
                     return path
                 else:
                     print("MockValidator: Path is invalid.")
                     QMessageBox.warning(None, "Path Error", f"Mock Validator: Path '{path}' is not a valid directory.")
                     return None
        profile_creation_manager = MockProfileManager()


    # Simulate core_logic if not available
    try:
        import core_logic
    except ImportError:
        print("WARNING: core_logic not found, using mock functions.")
        class MockCoreLogic:
            def get_steam_install_path(self): return "C:/FakeSteam"
            def find_steam_libraries(self): return ["C:/FakeSteam"]
            def find_installed_steam_games(self):
                return {
                    "12345": {"name": "Test Game 1", "installdir": "C:/FakeSteam/steamapps/common/GiocoProva1"},
                    "67890": {"name": "Another Game", "installdir": "C:/FakeSteam/steamapps/common/AltroGioco"},
                    "11111": {"name": "Existing Game", "installdir": "C:/FakeSteam/steamapps/common/GiocoEsistente"}
                }
            def find_steam_userdata_info(self):
                # Simula 2 possibili ID utente
                return (
                    "C:/FakeSteam/userdata", # userdata_path
                    "12345678", # likely_id
                    ["12345678", "87654321"], # possible_ids
                    { # id_details
                        "12345678": {"display_name": "Main User", "last_mod_str": "2025-04-19"},
                        "87654321": {"display_name": "Secondary User", "last_mod_str": "2024-11-01"}
                    }
                )
            def save_profiles(self, profiles_dict):
                 print("MockCoreLogic: Saving profiles:", profiles_dict)
                 return True # Simulate success
        core_logic = MockCoreLogic()

    # Simulate gui_utils if not available
    try:
         from gui_utils import SteamSearchWorkerThread
    except ImportError:
         print("WARNING: gui_utils.SteamSearchWorkerThread not found, using mock thread.")
         from PySide6.QtCore import QThread, Signal, QTimer
         class SteamSearchWorkerThread(QThread):
            finished = Signal(list) # Signal emits a list of tuples (path, score)
            def __init__(self, game_name, game_install_dir, appid, steam_userdata_path, steam_id3_to_use, parent=None):
                 super().__init__(parent)
                 self.game_name = game_name
                 # Save other parameters if necessary for simulation
                 print(f"MockThread: Init for {game_name} (AppID: {appid}, UserID: {steam_id3_to_use})")

            def run(self):
                 print(f"MockThread: Simulating search for {self.game_name}...")
                 QThread.msleep(2500) # Simulate work
                 # Simulate found results
                 mock_results = [
                     (f"C:/Users/Test/Documents/My Games/{self.game_name}/Saves", 90),
                     (f"C:/Users/Test/AppData/Local/{self.game_name}", 75),
                 ]
                 # If the game is the existing one, add the real path as an option
                 if self.game_name == "Existing Game":
                     mock_results.insert(0, ("C:/Saves/ExistingGame", 100)) # Simulate high score for the correct one

                 print(f"MockThread: Search finished for {self.game_name}. Emitting results.")
                 self.finished.emit(mock_results)


    app = QApplication(sys.argv)
    # Create a fake main window (necessary as parent for the dialog)
    mock_main = MockMainWindow()
    dialog = SteamDialog(parent=mock_main) # Pass the mock main window as parent

    # Connect the dialog signal to see the output
    dialog.profile_configured.connect(lambda name, path: print(f"SIGNAL profile_configured received: {name} -> {path}"))

    dialog.show()
    sys.exit(app.exec())