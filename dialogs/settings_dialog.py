# dialogs/settings_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QSpinBox, QDialogButtonBox, QFileDialog, QStyle, QApplication,
    QCheckBox, QMessageBox, QLabel
)
from PySide6.QtCore import Slot, QEvent

# Import the module to save/load settings
import logging
# Import config to access the MIN_FREE_SPACE_GB constant
try:
    import config
except ImportError:
    # Fallback if config.py is not found (unlikely but safe)
    class config:
        MIN_FREE_SPACE_GB = 2
    logging.warning("Module config.py not found, using default value for MIN_FREE_SPACE_GB.")


class SettingsDialog(QDialog):

    def __init__(self, current_settings, parent=None, is_initial_setup: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Application Settings")
        self.setMinimumWidth(500)
        self.settings = current_settings.copy()
        # Flag: true only for the very first configuration dialog shown at app startup
        self.is_initial_setup = bool(is_initial_setup)

        # Get the style for standard icons
        style = QApplication.instance().style()

        layout = QVBoxLayout(self)

        # --- Backup Base Path Group ---
        self.path_group = QGroupBox("Backup Base Path") # Saved reference
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.settings.get("backup_base_dir", ""))
        self.browse_button = QPushButton() # Saved reference
        browse_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        self.browse_button.setIcon(browse_icon)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        self.path_group.setLayout(path_layout)
        layout.addWidget(self.path_group)

        # --- Portable Mode Group ---
        self.portable_group = QGroupBox()
        portable_layout = QHBoxLayout()
        self.portable_checkbox = QCheckBox()
        # Initialize from current settings (fallback False)
        self.portable_checkbox.setChecked(self.settings.get("portable_config_only", False))
        portable_layout.addWidget(self.portable_checkbox)
        portable_layout.addStretch()
        self.portable_group.setLayout(portable_layout)
        layout.addWidget(self.portable_group)

        # --- Maximum Source Size Group ---
        self.max_src_group = QGroupBox() # Saved reference
        max_src_layout = QHBoxLayout()
        self.size_options = [
            ("50 MB", 50), ("100 MB", 100), ("250 MB", 250), ("500 MB", 500),
            ("1 GB (1024 MB)", 1024), ("2 GB (2048 MB)", 2048),
            ("5 GB (5120 MB)", 5120),
            ("No Limit", -1)
        ]
        self.max_src_combobox = QComboBox()
        for display_text, _ in self.size_options:
            self.max_src_combobox.addItem(display_text)
        # ... (logic to select current value) ...
        current_mb_value = self.settings.get("max_source_size_mb", 500)
        current_index = next((i for i, (_, v) in enumerate(self.size_options) if v == current_mb_value), -1)
        if current_index != -1:
            self.max_src_combobox.setCurrentIndex(current_index)
        else: # Fallback if saved value is not among the options
            default_index = next((i for i, (_, v) in enumerate(self.size_options) if v == 500), 0)
            self.max_src_combobox.setCurrentIndex(default_index)

        max_src_layout.addWidget(self.max_src_combobox)
        max_src_layout.addStretch()
        self.max_src_group.setLayout(max_src_layout)
        layout.addWidget(self.max_src_group)

        # --- Maximum Number of Backups Group ---
        self.max_group = QGroupBox() # Saved reference
        max_layout = QHBoxLayout()
        self.max_spinbox = QSpinBox()
        self.max_spinbox.setMinimum(1)
        self.max_spinbox.setMaximum(99)
        self.max_spinbox.setValue(self.settings.get("max_backups", 3))
        max_layout.addWidget(self.max_spinbox)
        max_layout.addStretch()
        self.max_group.setLayout(max_layout)
        layout.addWidget(self.max_group)

        # --- Compression Group ---
        self.comp_group = QGroupBox() # Saved reference
        comp_layout = QHBoxLayout()
        self.comp_combobox = QComboBox()
        # (The self.compression_options map will be updated in updateUiText)
        current_comp_mode = self.settings.get("compression_mode", "standard")
        # (Selection will be restored in updateUiText after populating)
        comp_layout.addWidget(self.comp_combobox)
        comp_layout.addStretch()
        self.comp_group.setLayout(comp_layout)
        layout.addWidget(self.comp_group)

        # --- Free Space Check Group ---
        self.space_check_group = QGroupBox() # Saved reference
        space_check_layout = QHBoxLayout()
        self.space_check_checkbox = QCheckBox() # Saved reference
        self.space_check_checkbox.setChecked(self.settings.get("check_free_space_enabled", True))
        space_check_layout.addWidget(self.space_check_checkbox)
        space_check_layout.addStretch()
        self.space_check_group.setLayout(space_check_layout)
        layout.addWidget(self.space_check_group)

        # --- UI Settings Group ---
        self.ui_settings_group = QGroupBox() # Saved reference
        ui_settings_layout = QVBoxLayout()
        self.enable_global_drag_checkbox = QCheckBox() # Saved reference
        self.enable_global_drag_checkbox.setChecked(self.settings.get("enable_global_drag_effect", True))
        ui_settings_layout.addWidget(self.enable_global_drag_checkbox)
        self.ui_settings_group.setLayout(ui_settings_layout)
        layout.addWidget(self.ui_settings_group)

        # --- Restore JSON Backups Group ---
        self.restore_json_group = QGroupBox() # Saved reference
        restore_json_layout = QVBoxLayout()
        
        # Add info label
        info_label = QLabel("If you lose your profiles or settings, you can restore them from the backup directory.")
        info_label.setWordWrap(True)
        restore_json_layout.addWidget(info_label)
        
        # Add restore button
        self.restore_json_button = QPushButton()
        restore_icon = style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.restore_json_button.setIcon(restore_icon)
        self.restore_json_button.clicked.connect(self.handle_restore_json_backup)
        restore_json_layout.addWidget(self.restore_json_button)
        
        self.restore_json_group.setLayout(restore_json_layout)
        layout.addWidget(self.restore_json_group)

        layout.addStretch()

        # --- Dialog Buttons ---
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel) # Saved reference
        self.buttons.accepted.connect(self.accept_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Connect signals
        self.browse_button.clicked.connect(self.browse_backup_dir)
        # React to portable checkbox toggle
        self.portable_checkbox.toggled.connect(self._handle_portable_toggled)

        # Call updateUiText at the end to set initial texts
        self.updateUiText()
        # Apply initial toggle state rules (e.g., in first-launch flow)
        try:
            self._handle_portable_toggled(self.portable_checkbox.isChecked())
        except Exception:
            pass

    def get_settings(self):
        """Returns the internal dictionary of modified settings."""
        return self.settings

    def updateUiText(self):
        """Updates the text of translatable widgets in the dialog."""
        logging.debug("SettingsDialog.updateUiText() called")
        self.setWindowTitle("Application Settings")
        self.path_group.setTitle("Backup Base Path")
        self.max_src_group.setTitle("Maximum Source Size for Backup")
        self.max_group.setTitle("Maximum Number of Backups per Profile")
        self.comp_group.setTitle("Backup Compression (.zip)")
        self.space_check_group.setTitle("Free Disk Space Check")
        self.space_check_checkbox.setText(f"Enable space check before backup (minimum {config.MIN_FREE_SPACE_GB} GB)")

        # UI Settings Texts
        self.ui_settings_group.setTitle("UI Settings")
        self.enable_global_drag_checkbox.setText("Enable global mouse drag-to-show effect")
        # Portable Mode Texts
        self.portable_group.setTitle("Portable Mode")
        self.portable_checkbox.setText("Use only JSONs in backup folder (.savestate)")
        
        # Restore JSON Texts
        self.restore_json_group.setTitle("Restore Configuration Backups")
        self.restore_json_button.setText("Restore Profiles and Settings from Backup")

        # Update texts in the compression combobox
        current_key_comp = self.comp_combobox.currentData() # Save current key
        self.comp_combobox.clear()
        self.compression_options = { # Recreate map with translated texts
             "standard": "Standard (Recommended)",
             "maximum": "Maximum (Slower)",
             "stored": "None (Faster)"
        }
        for key, text in self.compression_options.items(): # Repopulate
            self.comp_combobox.addItem(text, key)
        index_to_select_comp = self.comp_combobox.findData(current_key_comp)
        if index_to_select_comp != -1: # Reselect
            self.comp_combobox.setCurrentIndex(index_to_select_comp)

        # Update button texts
        self.browse_button.setText("Browse...")
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button: save_button.setText("Save")
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button: cancel_button.setText("Cancel")

    # --- Event handling ---
    def changeEvent(self, event):
        """Handles events, including language change."""
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("SettingsDialog.changeEvent(LanguageChange) detected")
            self.updateUiText() # Call the correct function
        super().changeEvent(event) # Call the base implementation

    @Slot()
    def browse_backup_dir(self):
        """Opens dialog to select backup folder."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Base Folder for Backups", self.path_edit.text()
        )
        if directory:
             self.path_edit.setText(os.path.normpath(directory))

    @Slot()
    def accept_settings(self):
        """Validates and updates the settings dictionary."""
        new_path = os.path.normpath(self.path_edit.text())
        new_max_backups = self.max_spinbox.value()
        selected_size_index = self.max_src_combobox.currentIndex()
        new_compression_mode = self.comp_combobox.currentData()
        new_check_free_space = self.space_check_checkbox.isChecked()
        new_portable_mode = self.portable_checkbox.isChecked()

        new_max_src_size_mb = -1
        if 0 <= selected_size_index < len(self.size_options):
            _, new_max_src_size_mb = self.size_options[selected_size_index]

        # --- Path Creation ---
        # If the path does not exist, ask the user to create it
        if new_path and not os.path.isdir(new_path):
            reply = QMessageBox.question(
                self,
                "Create Directory?",
                f"The path '{new_path}' does not exist.\nDo you want to create it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(new_path, exist_ok=True)
                    logging.info(f"Created backup directory: {new_path}")
                except OSError as e:
                    QMessageBox.critical(
                        self,
                        "Creation Failed",
                        f"Failed to create directory '{new_path}'.\n\nError: {e}"
                    )
                    return  # Stop processing
            else:
                # User chose not to create. The validation below will fail and show a message.
                pass

        # --- PATH VALIDATION (Now uses ProfileCreationManager) ---
        main_window = self.parent()
        # Check if main_window and its profile_creation_manager exist,
        # and if the latter has the validate_save_path method.
        if not main_window or \
           not hasattr(main_window, 'profile_creation_manager') or \
           not main_window.profile_creation_manager or \
           not hasattr(main_window.profile_creation_manager, 'validate_save_path'):
            logging.error("Unable to validate path: main_window or profile_creation_manager or method missing.")
            QMessageBox.critical(self, "Internal Error", "Unable to validate path.")
            return

        context_name = "Settings"
        # Call the method via the manager
        validated_new_path = main_window.profile_creation_manager.validate_save_path(
            new_path, context_profile_name=context_name
        )
        if validated_new_path is None:
             return # Validation failed and already showed a message

        # Update the self.settings dictionary with the new validated values
        self.settings["backup_base_dir"] = validated_new_path
        self.settings["max_backups"] = new_max_backups
        self.settings["max_source_size_mb"] = new_max_src_size_mb
        self.settings["compression_mode"] = new_compression_mode
        self.settings["check_free_space_enabled"] = new_check_free_space
        self.settings["enable_global_drag_effect"] = self.enable_global_drag_checkbox.isChecked()
        # Handle portable mode and conditional AppData deletion prompt
        previous_portable = bool(self.settings.get("portable_config_only", False))
        self.settings["portable_config_only"] = new_portable_mode

        # Show delete AppData popup only when enabling portable and AppData folder exists
        try:
            if (not previous_portable) and new_portable_mode:
                import config as _cfg
                appdata_dir = _cfg.get_app_data_folder()
                appdata_has_configs = False
                if appdata_dir and os.path.isdir(appdata_dir):
                    # Consider folder existing with any of the known JSONs as present
                    known = ["settings.json", "game_save_profiles.json", "favorites_status.json"]
                    appdata_has_configs = any(os.path.exists(os.path.join(appdata_dir, n)) for n in known)
                if appdata_has_configs:
                    reply = QMessageBox.question(
                        self,
                        "Remove AppData Configuration?",
                        ("You enabled portable mode and a configuration folder was found in AppData:\n\n"
                         f"{appdata_dir}\n\n"
                         "Do you want to delete the AppData configuration after migrating files to the backup folder?"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        # Ephemeral flag consumed by settings_manager.save_settings
                        self.settings["_delete_appdata_after_portable"] = True
        except Exception:
            pass

        # If enabling portable and .savestate esiste, cambiamo immediatamente i percorsi e chiudiamo come Continue
        if new_portable_mode:
            try:
                # Forza override runtime subito, così gli import usano il nuovo path in questa sessione
                import settings_manager as _sm
                target_dir = os.path.join(validated_new_path, ".savestate")
                if hasattr(_sm, "_RUNTIME_CONFIG_DIR_OVERRIDE"):
                    _sm._RUNTIME_CONFIG_DIR_OVERRIDE = target_dir
            except Exception:
                pass
        # Accept the dialog
        super().accept()

    def _is_portable_ready(self) -> bool:
        try:
            base = os.path.normpath(self.path_edit.text())
            if not base:
                return False
            savestate_dir = os.path.join(base, ".savestate")
            if not os.path.isdir(savestate_dir):
                return False
            # Require at least settings.json and game_save_profiles.json to exist
            required = [
                os.path.join(savestate_dir, "settings.json"),
                os.path.join(savestate_dir, "game_save_profiles.json"),
            ]
            return all(os.path.isfile(p) for p in required)
        except Exception:
            return False

    def _handle_portable_toggled(self, enabled: bool):
        ready = self._is_portable_ready() if enabled else False
        # Only during initial setup we lock the rest of the UI when portable is ready
        if self.is_initial_setup:
            for g in (self.max_src_group, self.max_group, self.comp_group, self.space_check_group, self.ui_settings_group, self.restore_json_group):
                g.setEnabled(not (enabled and ready))
            self.path_group.setEnabled(not (enabled and ready))
        try:
            btn = self.buttons.button(QDialogButtonBox.StandardButton.Save)
            if btn:
                btn.setText("Continue" if (self.is_initial_setup and enabled and ready) else "Save")
        except Exception:
            pass
    
    @Slot()
    def handle_restore_json_backup(self):
        """Handle restoring JSON backups from the backup directory."""
        import core_logic
        # Lazy import to avoid potential cycles
        try:
            import settings_manager as _settings_manager
        except Exception:
            _settings_manager = None
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Restore Configuration Backups",
            "This will restore your profiles, settings, and favorites from the backup directory.\n\n"
            "Current files will be backed up before restoration.\n\n"
            "Do you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Attempt to restore
        try:
            success = core_logic.restore_json_from_backup_root()
            if success:
                # Reload settings and profiles immediately and apply to parent window
                try:
                    # Reload settings from disk
                    reloaded_settings = None
                    if _settings_manager is not None:
                        reloaded_settings, _first = _settings_manager.load_settings()
                    # Update internal dialog state
                    if isinstance(reloaded_settings, dict):
                        self.settings = reloaded_settings.copy()
                        # Reflect new base path in UI field
                        if hasattr(self, 'path_edit') and self.path_edit:
                            self.path_edit.setText(self.settings.get("backup_base_dir", ""))
                    # Update main window immediately (if available)
                    mw = self.parent()
                    if mw:
                        if isinstance(reloaded_settings, dict):
                            mw.current_settings = reloaded_settings
                        # Reload favorites cache after restore
                        try:
                            from gui_components import favorites_manager as _fav
                            _fav._cache_loaded = False
                            _fav.load_favorites()
                        except Exception:
                            pass
                        # Reload profiles from disk and refresh UI
                        mw.profiles = core_logic.load_profiles()
                        if hasattr(mw, 'profile_table_manager') and mw.profile_table_manager:
                            mw.profile_table_manager.update_profile_table()
                        if hasattr(mw, 'updateUiText'):
                            mw.updateUiText()
                        if hasattr(mw, 'update_global_drag_listener_state'):
                            mw.update_global_drag_listener_state()
                except Exception as e_apply:
                    logging.warning(f"Applied restore but failed to refresh UI/runtime state: {e_apply}")

                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Configuration files have been restored and applied."
                )

                # Close the dialog as 'Accepted' to continue normal startup
                # (we avoid triggering accept_settings to not overwrite restored files)
                self.accept()
                return
            else:
                QMessageBox.warning(
                    self,
                    "Restore Failed",
                    "Could not restore configuration files.\n\n"
                    "Please check that backup files exist in the .savestate folder."
                )
        except Exception as e:
            logging.error(f"Error restoring JSON backups: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred while restoring backups:\n\n{str(e)}"
            )