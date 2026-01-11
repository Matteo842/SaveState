# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QLineEdit, QCheckBox, QWidget, QHeaderView
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer, QEvent, QSize
from PySide6.QtGui import QColor

# Import necessary logic
import core_logic
import logging
import os

# --- Steam Game Management Dialog ---
class SteamDialog(QDialog):
    """
    Dialog for displaying installed Steam games, selecting one to configure its save path.
    """
    # Signal emitted when a single game is selected (appid, profile_name)
    game_selected_for_config = Signal(str, str)
    # Signal emitted when multiple games are selected for batch configuration
    # Emits list of dicts: [{'appid': str, 'name': str, 'installdir': str}, ...]
    games_selected_for_batch_config = Signal(list)

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

        # Track checked items for multi-selection
        self.checked_items = set()  # Set of appids that are checked
        
        # --- Create UI Widgets ---
        # TreeWidget with 3 columns: Checkbox, Game Name, AppID
        self.game_list_widget = QTreeWidget()
        self.game_list_widget.setHeaderLabels(["Select", "Game Name", "AppID"])
        self.game_list_widget.setColumnCount(3)
        
        # Configure columns
        header = self.game_list_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Checkbox column
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Game name stretches
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # AppID fixed
        header.resizeSection(0, 36)  # Checkbox column width - compact to save space
        header.resizeSection(2, 130)  # AppID column width
        header.setStretchLastSection(False)
        
        self.game_list_widget.setHeaderHidden(True)  # Hide header for clean look
        self.game_list_widget.setIndentation(0)  # Remove tree indentation to prevent text clipping
        
        # Styling: larger font, increased row height for checkboxes, horizontal separators
        self.game_list_widget.setStyleSheet("""
            QTreeWidget {
                font-size: 11pt;
                border: none;
            }
            QTreeWidget::item {
                padding: 4px 8px;
                padding-left: 8px;
                min-height: 32px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QTreeWidget::item:selected {
                background-color: rgba(180, 40, 40, 0.8);
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background-color: rgba(255, 255, 255, 0.08);
            }
        """)

        self.status_label = QLabel("Select a game and click Configure.")
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setVisible(False)

        # Single configure button - text changes based on selection (single vs batch)
        self.configure_button = QPushButton("Configure Selected Profile")
        self.configure_button.setEnabled(False)
        self._is_batch_mode = False  # Track current mode
        
        self.refresh_button = QPushButton("Refresh Games List")
        self.close_button = QPushButton("Close")

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
        self.configure_button.clicked.connect(self._on_configure_clicked)
        self.refresh_button.clicked.connect(self.start_steam_scan)
        self.close_button.clicked.connect(self.reject)
        self.search_bar.textChanged.connect(self.filter_game_list)
        
        # Handle row selection - update button state
        self.game_list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.game_list_widget.itemDoubleClicked.connect(self._handle_double_click)
        
        # Handle item clicks to toggle checkboxes (click on column 0 or checkbox widget)
        self.game_list_widget.itemClicked.connect(self._on_item_clicked)

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
        """Populate the game list with checkbox widgets for multi-selection."""
        self.game_list_widget.clear()
        self.checked_items.clear()  # Reset checked items
        self._is_batch_mode = False
        
        if not self.steam_games_data:
            # Add a dummy item if no games found
            item = QTreeWidgetItem(["", "No games found.", ""])
            self.game_list_widget.addTopLevelItem(item)
            self.configure_button.setEnabled(False)
            self.configure_button.setText("Configure Selected Profile")
            return

        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        
        for appid, game_data in sorted_games:
            profile_exists_marker = "[EXISTING PROFILE]" if game_data['name'] in self.profiles else ""
            # Display name without AppID
            display_text = f"{game_data['name']} {profile_exists_marker}".strip()
            
            # Create TreeItem with empty first column (for checkbox), Name in Col 1, AppID in Col 2
            item = QTreeWidgetItem(["", display_text, f"AppID: {appid}"])
            
            # Store appid in both column 0 (for checkbox handling) and column 1 (for selection handling)
            item.setData(0, Qt.ItemDataRole.UserRole, appid)
            item.setData(1, Qt.ItemDataRole.UserRole, appid)
            
            # Align the AppID column (column 2) to the left for better readability
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            
            self.game_list_widget.addTopLevelItem(item)
            
            # Create checkbox widget for column 0 with fixed dimensions
            checkbox_widget = QWidget()
            checkbox_widget.setStyleSheet("background-color: transparent;")
            checkbox_widget.setFixedSize(36, 36)  # Compact size to save space
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            checkbox = QCheckBox()
            checkbox.setFixedSize(28, 28)  # Fixed size for the checkbox itself
            checkbox.setProperty("appid", appid)  # Store appid for later retrieval
            # Custom checkbox styling - match cloud panel style
            checkbox.setStyleSheet("""
                QCheckBox {
                    spacing: 0px;
                }
                QCheckBox::indicator {
                    width: 24px;
                    height: 24px;
                    border-radius: 4px;
                    border: 2px solid #555555;
                    background-color: #2b2b2b;
                }
                QCheckBox::indicator:hover {
                    border: 2px solid #888888;
                    background-color: #353535;
                }
                QCheckBox::indicator:checked {
                    border: 2px solid #4CAF50;
                    background-color: #4CAF50;
                }
                QCheckBox::indicator:checked:hover {
                    border: 2px solid #66BB6A;
                    background-color: #66BB6A;
                }
            """)
            checkbox.stateChanged.connect(lambda state, aid=appid: self._on_checkbox_changed(aid, state))
            checkbox_layout.addWidget(checkbox)
            
            self.game_list_widget.setItemWidget(item, 0, checkbox_widget)
        
        # Clear selection and disable configure button until user explicitly selects a game
        self.game_list_widget.clearSelection()
        self.game_list_widget.setCurrentItem(None)
        self.configure_button.setEnabled(False)
    
    def _on_checkbox_changed(self, appid, state):
        """Handle checkbox state change for multi-selection."""
        if state == Qt.CheckState.Checked.value:
            self.checked_items.add(appid)
        else:
            self.checked_items.discard(appid)
        self._update_configure_button()
    
    def _on_selection_changed(self, current, previous):
        """Handle row selection change - update button state."""
        self._update_configure_button()
    
    def _update_configure_button(self):
        """Update configure button text and state based on checkbox/row selection."""
        count = len(self.checked_items)
        
        if count >= 2:
            # Batch mode: 2+ checkboxes selected - use MultiProfileDialog
            self._is_batch_mode = True
            self.configure_button.setText(f"Configure Selected ({count})")
            self.configure_button.setEnabled(True)
        elif count == 1:
            # Single checkbox selected - use normal single-profile flow
            self._is_batch_mode = False
            self.configure_button.setText("Configure Selected (1)")
            self.configure_button.setEnabled(True)
        else:
            # No checkboxes - use row selection for single mode
            self._is_batch_mode = False
            current_item = self.game_list_widget.currentItem()
            has_valid_selection = (
                current_item is not None and 
                current_item.data(1, Qt.ItemDataRole.UserRole) is not None
            )
            self.configure_button.setText("Configure Selected Profile")
            self.configure_button.setEnabled(has_valid_selection)
    
    @Slot()
    def _on_configure_clicked(self):
        """Handle configure button click - route to single or batch based on mode."""
        if self._is_batch_mode:
            self._emit_batch_selection_and_accept()
        else:
            # Single mode - check if we have a checkbox or row selection
            if len(self.checked_items) == 1:
                # Use the checked item
                appid = list(self.checked_items)[0]
                game_data = self.steam_games_data.get(appid)
                if game_data:
                    profile_name = game_data.get('name', 'Unknown')
                    logging.info(f"[SteamDialog] Single checkbox selected: '{profile_name}' (AppID: {appid})")
                    self.game_selected_for_config.emit(appid, profile_name)
                    self.accept()
                    return
            # Fall back to row selection
            self._emit_selection_and_accept()
    
    def _on_item_clicked(self, item, column):
        """Handle click on item - toggle checkbox if clicking outside checkbox area."""
        # Only handle clicks on non-checkbox columns that should toggle checkbox
        # Column 0 has the checkbox widget, clicks there are handled by the checkbox itself
        # For columns 1 and 2, we don't toggle checkbox - user must click the checkbox directly
        pass  # Let the checkbox handle its own clicks
    
    @Slot()
    def _emit_selection_and_accept(self):
        """Emit signal for single game selection and close dialog."""
        current_item = self.game_list_widget.currentItem()
        if not current_item:
            return

        # AppID is stored in column 0 or 1 UserRole
        appid = current_item.data(1, Qt.ItemDataRole.UserRole)
        if not appid:
            appid = current_item.data(0, Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)

        if not game_data or not appid:
            # Handle case where "No games found" item is selected or similar
            if "No games found" in current_item.text(1):
                return
            QMessageBox.warning(self, "Error", "Unable to get data for the selected game.")
            return

        profile_name = game_data['name']
        logging.info(f"[SteamDialog] Game selected: '{profile_name}' (AppID: {appid}). Emitting signal and closing.")
        self.game_selected_for_config.emit(appid, profile_name)
        self.accept()
    
    @Slot()
    def _emit_batch_selection_and_accept(self):
        """Emit signal for batch game selection and close dialog."""
        if not self.checked_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one game using the checkboxes.")
            return
        
        # Build list of selected games data
        selected_games = []
        for appid in self.checked_items:
            game_data = self.steam_games_data.get(appid)
            if game_data:
                selected_games.append({
                    'appid': appid,
                    'name': game_data.get('name', 'Unknown'),
                    'installdir': game_data.get('installdir', '')
                })
        
        if not selected_games:
            QMessageBox.warning(self, "Error", "Could not retrieve data for selected games.")
            return
        
        logging.info(f"[SteamDialog] Batch selection: {len(selected_games)} games. Emitting signal and closing.")
        self.games_selected_for_batch_config.emit(selected_games)
        self.accept() 
        
    # --- METHOD to handle double-click on game list ---
    @Slot(QTreeWidgetItem, int)
    def _handle_double_click(self, item, column):
        """Handle double-click on a game in the list to automatically select it."""
        if not item:
            return
            
        # Get the AppID from the item's user data
        appid = item.data(0, Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)
        
        if not game_data or not appid:
            # Handle "No games found"
            return
            
        profile_name = game_data['name']
        logging.info(f"[SteamDialog] Game double-clicked: '{profile_name}' (AppID: {appid}). Emitting signal and closing.")
        self.status_label.setText(f"Selected: {profile_name}")
        
        # Emit the signal and close the dialog, just like clicking the Configure button
        self.game_selected_for_config.emit(appid, profile_name)
        self.accept() 
        
    @Slot(bool, dict)
    def on_steam_search_finished(self, success, results_dict):
        """Slot called when SteamSearchWorkerThread has finished the search."""
        guesses_with_scores = results_dict.get('path_data', [])
        game_install_dir = results_dict.get('game_install_dir')
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
            # Read shorten flag from settings if available
            shorten_flag = True
            try:
                if hasattr(main_window, 'current_settings') and isinstance(main_window.current_settings, dict):
                    shorten_flag = bool(main_window.current_settings.get('shorten_paths_enabled', True))
            except Exception:
                shorten_flag = True

            dlg = SavePathSelectionDialog(
                items=items_for_dialog,
                title="Confirm Save Path",
                prompt_text=dialog_text,
                show_scores=show_scores,
                shorten_paths=shorten_flag,
                game_install_dir=game_install_dir,
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
            # Fallback to a very simple validation (exists - accepts both files and directories)
            logging.warning("[SteamDialog] MainWindow validator not found, using basic os.path.exists validation.")
            def basic_validator(path_to_validate, _profile_name):
                if not path_to_validate or not os.path.exists(path_to_validate):
                     QMessageBox.warning(self, "Path Error", 
                                         "The specified path does not exist.") 
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

        for i in range(self.game_list_widget.topLevelItemCount()):
            item = self.game_list_widget.topLevelItem(i)
            # Make item visible if text is found in the item's text, case-insensitive
            item.setHidden(text.lower() not in item.text(0).lower())

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