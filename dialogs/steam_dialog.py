# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer

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
        self.steam_search_thread = None # Not used here anymore
        # Get profiles and steam_games_data from parent to populate the list
        self.profiles = parent.profiles if parent and hasattr(parent, 'profiles') else {}
        self.steam_games_data = parent.steam_games_data if parent and hasattr(parent, 'steam_games_data') else {} # Assume MainWindow has it
        self.steam_userdata_info = parent.steam_userdata_info if parent and hasattr(parent, 'steam_userdata_info') else {} # Assume MainWindow has it

        # --- Create UI Widgets ---
        self.game_list_widget = QListWidget()
        self.status_label = QLabel("Select a game and click Configure.")
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
        h_layout.addStretch()
        h_layout.addWidget(self.configure_button)
        h_layout.addWidget(self.close_button)
        layout.addLayout(h_layout)


        # # --- Signal/Slot connections ---
        # configure_button now calls a different method or directly emits+accepts
        self.configure_button.clicked.connect(self._emit_selection_and_accept)
        self.refresh_button.clicked.connect(self.start_steam_scan)
        self.close_button.clicked.connect(self.reject)
        self.game_list_widget.currentItemChanged.connect(
            lambda item: self.configure_button.setEnabled(item is not None)
        )

        # Populate the list immediately with the data passed from the parent
        self.populate_game_list()
    
    @Slot()
    def start_steam_scan(self):
         # Update the data in the parent (MainWindow) if you refresh here!
         parent_window = self.parent()
         if parent_window:
             parent_window.steam_games_data = self.steam_games_data
             parent_window.steam_userdata_info = self.steam_userdata_info
         self.populate_game_list() # Update the list in this dialog
         self.status_label.setText(f"List updated. {len(self.steam_games_data)} games found.")


    def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data:
             self.game_list_widget.addItem("No games found.")
             self.configure_button.setEnabled(False) # Disable if no games
             return

        self.configure_button.setEnabled(self.game_list_widget.currentItem() is not None) # Enable if there is a selection
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
        self.accept() # Close the dialog immediately

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
            self.reject() # Close the Steam dialog with 'reject'
            return

        confirmed_path = None # Final path that will be saved
        existing_path = self.profiles.get(profile_name)
        logging.debug(f"ON_SEARCH_FINISHED: Existing path for '{profile_name}' is '{existing_path}'")

        # --- Logic to choose/confirm the path ---
        if not guesses_with_scores: # The search found nothing
            logging.info("ON_SEARCH_FINISHED: No paths guessed by core_logic.")
            if not existing_path:
                # No suggestions and no existing profile -> Force manual input
                logging.debug("  No existing path found. Forcing manual input.")
                QMessageBox.information(self, "Path Not Found",
                                        f"Unable to automatically find a path for '{profile_name}'.\n"
                                        "Please enter it manually.")
                confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Call helper for manual input
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
                     confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Call helper
                else: # Cancel
                    logging.debug("  User cancelled.")
                    self.status_label.setText("Configuration cancelled.")
                    self.reject()
                    return # Exit the function
        # --- END RESTORED BLOCK ---

        else: # Found one or more suggestions (Block with deduplication)
            path_choices = []
            display_text_to_original_path = {}
            added_normalized_paths_for_display = set()
            original_path_order = [p for p, s in guesses_with_scores]

            show_scores = False
            if MainWindow is not None and isinstance(main_window, MainWindow) and hasattr(main_window, 'developer_mode_enabled'):
                 show_scores = main_window.developer_mode_enabled
            logging.debug(f"ON_SEARCH_FINISHED: Developer mode (show scores): {show_scores}")

            logging.debug(f"ON_SEARCH_FINISHED: --- Start UI Choice Deduplication ---")
            # Deduplication loop...
            for i, (p, score) in enumerate(guesses_with_scores):
                logging.debug(f"ON_SEARCH_FINISHED: Processing guess {i}: Path='{p}', Score={score}")
                try:
                    normalized_path_check = os.path.normpath(p).lower()
                    logging.debug(f"  Normalized path for check: '{normalized_path_check}'")
                except Exception as e_norm:
                    logging.error(f"  Error normalizing path '{p}': {e_norm}. Skipping this guess.")
                    continue

                if normalized_path_check not in added_normalized_paths_for_display:
                    logging.debug(f"  Path '{normalized_path_check}' is NEW for display list.")
                    added_normalized_paths_for_display.add(normalized_path_check)
                    is_current_marker = "[CURRENT]" if p == existing_path else ""
                    score_str = f"(Score: {score})" if show_scores else ""
                    display_text = f"{p} {score_str} {is_current_marker}".strip().replace("  ", " ")
                    path_choices.append(display_text)
                    display_text_to_original_path[display_text] = p
                    logging.debug(f"  Added unique UI choice: '{display_text}' (maps to '{p}')")
                else:
                     logging.debug(f"  Path '{normalized_path_check}' ALREADY ADDED. Skipping UI duplicate for: '{p}'")
            logging.debug(f"ON_SEARCH_FINISHED: --- End UI Choice Deduplication ---")
            logging.debug(f"ON_SEARCH_FINISHED: Final unique path_choices list for dialog ({len(path_choices)} items): {path_choices}")

            # Determine preselection index...
            current_selection_index = 0
            if existing_path:
                 display_str_for_existing = None
                 for disp_text, orig_path in display_text_to_original_path.items():
                     if orig_path == existing_path: display_str_for_existing = disp_text; break
                 if display_str_for_existing in path_choices:
                      try: current_selection_index = path_choices.index(display_str_for_existing)
                      except ValueError: current_selection_index = 0
                 else: logging.debug(f"  Existing path was likely deduplicated, not preselecting.")

            # Add manual option
            manual_option_str = "--- Enter path manually ---"
            path_choices.append(manual_option_str)

            dialog_text = f"These potential paths have been found for '{profile_name}'.\n" \
                          "Select the correct one (sorted by probability) or choose manual entry:"

            # Show choice dialog
            logging.debug(f"ON_SEARCH_FINISHED: Showing QInputDialog with {len(path_choices)} choices.")
            chosen_display_str, ok = QInputDialog.getItem(
                self, "Confirm Save Path", dialog_text,
                path_choices, current_selection_index, False
            )

            # Handle user choice...
            if ok and chosen_display_str:
                if chosen_display_str == manual_option_str:
                    confirmed_path = self._ask_for_manual_path(profile_name, existing_path)
                else:
                    confirmed_path = display_text_to_original_path.get(chosen_display_str)
                    if confirmed_path is None:
                        logging.error(f"Error mapping selected choice '{chosen_display_str}' back to path.")
                        QMessageBox.critical(self, "Internal Error", "Error in path selection.")
                        self.reject(); return
            else: # User cancelled
                self.status_label.setText("Configuration cancelled.")
                self.reject(); return

        # --- Save Profile  ---
        if confirmed_path:
             logging.info(f"Saving profile '{profile_name}' with path '{confirmed_path}'")
             self.profiles[profile_name] = confirmed_path
             if core_logic.save_profiles(self.profiles):
                  self.status_label.setText(f"Profile '{profile_name}' configured.")
                  self.profile_configured.emit(profile_name, confirmed_path)
                  self.accept() # Close this dialog with success
             else:
                  QMessageBox.critical(self, "Save Error",
                                         "Unable to save the profiles file.")
                  self.status_label.setText("Error while saving profiles.")
                  self.reject() # Close if it fails
        else:
             # confirmed_path è None (manuale annullato o errore validazione nel blocco 'if not guesses')
             logging.warning(f"Configuration cancelled or failed for profile '{profile_name}' (confirmed_path is empty/None).")
             # The status label is already set in the blocks above in case of cancellation
             self.reject() # Close without saving

    def _get_validator_func(self):
        """Returns the path validation function, taking it from MainWindow if possible."""
        main_window = self.main_window_ref
        #main_window = self.parent()
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
                     QMessageBox.warning(self, "Path Error", # Translate
                                         "The specified path does not exist or is not a valid folder.") # Translate
                     return None
                return path_to_validate # Return the path if valid
            validator_func = basic_validator
        return validator_func

    def _ask_for_manual_path(self, profile_name, existing_path):
        """Ask the user to enter a path manually and validate it."""
        validator_func = self._get_validator_func()
        manual_path, ok = QInputDialog.getText(
            self, "Manual Path", # Translate
            f"Enter the COMPLETE save path for '{profile_name}':", # Translate
            text=existing_path if existing_path else "" # Precompile with the current path if it exists
        )

        if ok and manual_path:
            # Use the validator to check the entered path
            validated_path = validator_func(manual_path, profile_name) # Also pass the profile name
            if validated_path:
                return validated_path # Return the validated path
            else:
                # The validator has failed (and should have shown a message)
                return None
        elif ok and not manual_path: # Empty input
             QMessageBox.warning(self, "Path Error", "The path cannot be empty.") # Translate
             return None # Indicate failure/cancellation
        else: # User pressed Cancel on QInputDialog
            return None # Indicate cancellation

    # Override reject to ensure the thread is handled if active
    def reject(self):
        logging.debug("[SteamDialog] Dialog rejected.")
        super().reject()

    # Override accept to log
    def accept(self):
        logging.debug("[SteamDialog] Dialog accepted (configuration successful).")
        super().accept() # Call the base implementation of accept

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