# gui_handlers.py
# -*- coding: utf-8 -*-

import os
import logging
import shutil
import zipfile
import tempfile
import config

from PySide6.QtWidgets import QMessageBox, QDialog, QInputDialog, QApplication, QFileDialog
from PySide6.QtCore import Slot, QUrl, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QDesktopServices

# Import dialogs
from dialogs.settings_dialog import SettingsDialog
from dialogs.restore_dialog import RestoreDialog
from dialogs.manage_backups_dialog import ManageBackupsDialog
from dialogs.steam_dialog import SteamDialog

# Import core logic, utils, managers
import core_logic
from emulator_utils.pcsx2_manager import backup_pcsx2_save, restore_pcsx2_save
import settings_manager
import shortcut_utils
import config
from gui_utils import WorkerThread, SteamSearchWorkerThread
from utils import sanitize_filename


class MainWindowHandlers:
    # Initializes the handler class, connecting it to the main window.
    def __init__(self, main_window):
        self.main_window = main_window
        self.tr = main_window.tr # Helper for translations

    # --- Log Handling ----
    # Shows or hides the log panel and updates the button's tooltip.
    @Slot()
    def handle_toggle_log(self):
        # Access main_window attributes
        if self.main_window.log_dock_widget:
            is_visible = not self.main_window.log_dock_widget.isVisible()
            self.main_window.log_dock_widget.setVisible(is_visible)
            # Update tooltip on the main window's button
            if is_visible:
                self.main_window.toggle_log_button.setToolTip("Hide Log")
            else:
                self.main_window.toggle_log_button.setToolTip("Show Log")

    # Starts the timer when the log button is pressed (for long press detection).
    @Slot()
    def handle_log_button_pressed(self):
        logging.debug(f"Entering handle_log_button_pressed. Timer is: {self.main_window.log_button_press_timer}")
        if not self.main_window.log_button_press_timer.isActive():
            logging.debug(">>> Log button PRESSED. Starting timer...")
            self.main_window.log_button_press_timer.start()
        else:
            logging.debug(">>> Log button PRESSED. Timer already active?")

    # Handles the release of the log button (toggles log on short press).
    @Slot()
    def handle_log_button_released(self):
        logging.debug(">>> Log button RELEASED.")
        if self.main_window.log_button_press_timer.isActive():
            logging.debug("   - Timer was active (Short press). Stopping timer and toggling log panel.")
            self.main_window.log_button_press_timer.stop()
            self.handle_toggle_log() # Call the handler method within this class
        else:
            logging.debug("   - Timer was NOT active (Long press detected). Doing nothing on release.")
            # Action is handled by the timer's timeout signal connection

    # --- Developer Mode --- (Triggered by timer timeout, connected in MainWindow.__init__)
    # Toggles developer mode, updates the icon, and adjusts the log level.
    @Slot()
    def handle_developer_mode_toggle(self):
        logging.debug(">>> Developer Mode Toggle TIMER TIMEOUT triggered.")
        # Access and modify main_window state
        self.main_window.developer_mode_enabled = not self.main_window.developer_mode_enabled
        root_logger = logging.getLogger()

        if self.main_window.developer_mode_enabled:
            new_level = logging.DEBUG
            logging.info(f"Developer Mode ENABLED (Log {logging.getLevelName(new_level)} enabled).")
            if self.main_window.log_icon_dev:
                self.main_window.toggle_log_button.setIcon(self.main_window.log_icon_dev)
            else:
                self.main_window.toggle_log_button.setText("D")
        else:
            new_level = logging.INFO
            logging.info(f"Developer Mode DISABLED (Log {logging.getLevelName(new_level)} disabled).")
            if self.main_window.log_icon_normal:
                self.main_window.toggle_log_button.setIcon(self.main_window.log_icon_normal)
            else:
                self.main_window.toggle_log_button.setText("L")

        logging.debug(f"   - Setting root logger level to {logging.getLevelName(new_level)}")
        root_logger.setLevel(new_level)

        # Access main_window's log handlers
        if self.main_window.console_log_handler:
            logging.debug(f"   - Setting console_handler level to {logging.getLevelName(new_level)}")
            self.main_window.console_log_handler.setLevel(new_level)
        if self.main_window.qt_log_handler:
            logging.debug(f"   - Setting qt_log_handler level to {logging.getLevelName(new_level)}")
            self.main_window.qt_log_handler.setLevel(new_level)

    # --- General Actions --- (Open Backup Folder, Settings)
    # Opens the base backup folder in the system's file explorer.
    @Slot()
    def handle_open_backup_folder(self):
        # Attempt to get the user-configured backup directory first
        backup_dir = self.main_window.current_settings.get("backup_base_dir") # CORRECTED KEY

        # If not found in settings, fall back to the default from config
        if not backup_dir:
            backup_dir = config.BACKUP_BASE_DIR
            # Optionally, log that we're using the default
            logging.info(f"'backup_base_dir' not in settings, using default: {backup_dir}")

        if not backup_dir: # If still no backup_dir (e.g., config.BACKUP_BASE_DIR was also None/empty, though unlikely)
            QMessageBox.warning(self.main_window, "Error", "Backup base directory not configured in settings or config file.")
            return

        backup_dir = os.path.normpath(backup_dir)

        if not os.path.isdir(backup_dir):
            reply = QMessageBox.question(self.main_window, "Folder Not Found",
                                         "The specified backup folder does not exist:\n'{0}'\n\nDo you want to try to create it?".format(backup_dir),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                    logging.info(f"Backup folder created: {backup_dir}")
                except Exception as e:
                    QMessageBox.critical(self.main_window, "Error Creation", "Unable to create folder:\n{0}".format(e))
                    return
            else:
                return

        logging.debug(f"Attempting to open folder: {backup_dir}")
        url = QUrl.fromLocalFile(backup_dir)
        logging.debug(f"Attempting to open URL: {url.toString()}")
        if not QDesktopServices.openUrl(url):
            logging.warning(f"QDesktopServices.openUrl failed for {url.toString()}, attempting os.startfile...")
            try:
                os.startfile(backup_dir)
            except Exception as e_start:
                QMessageBox.critical(self.main_window, "Error Opening", "Unable to open folder:\n{0}".format(e_start))

    # Import configuration (profiles, favorites, settings) from backup mirror
    @Slot()
    def handle_import_config_from_backup(self):
        backup_dir = self.main_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        if not backup_dir:
            QMessageBox.warning(self.main_window, "Import Error", "Backup base directory is not configured.")
            return
        mirror_dir = os.path.join(backup_dir, ".savestate")
        if not os.path.isdir(mirror_dir):
            QMessageBox.warning(self.main_window, "Import Error", f"Mirror folder not found:\n{mirror_dir}")
            return

        # Files to import
        candidates = {
            "game_save_profiles.json": (core_logic.PROFILES_FILE_PATH, "profiles"),
            "favorites_status.json": (os.path.join(config.get_app_data_folder(), "favorites_status.json"), "favorites"),
            "settings.json": (settings_manager.SETTINGS_FILE_PATH, "settings"),
            "cloud_settings.json": (os.path.join(settings_manager.get_active_config_dir(), "cloud_settings.json"), "cloud settings"),
        }

        imported = []
        for fname, (dest_path, label) in candidates.items():
            src_path = os.path.join(mirror_dir, fname)
            try:
                if os.path.isfile(src_path):
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    # Backup any existing file first
                    if os.path.exists(dest_path):
                        try:
                            import datetime
                            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            shutil.copy2(dest_path, dest_path + f".bak-{ts}")
                        except Exception:
                            pass
                    shutil.copy2(src_path, dest_path)
                    imported.append(label)
            except Exception as e:
                logging.error(f"Failed importing {fname}: {e}")

        if not imported:
            QMessageBox.information(self.main_window, "Import", "No mirror files found to import.")
            return

        # Reload runtime state when possible
        if "settings" in imported:
            self.main_window.current_settings, _first = settings_manager.load_settings()
            if hasattr(self.main_window, 'update_global_drag_listener_state'):
                self.main_window.update_global_drag_listener_state()
        if "profiles" in imported:
            self.main_window.profiles = core_logic.load_profiles()
            if hasattr(self.main_window, 'profile_table_manager'):
                self.main_window.profile_table_manager.update_profile_table()

        from gui_components import favorites_manager
        if "favorites" in imported:
            try:
                # Force reload of cache
                favorites_manager._cache_loaded = False
                favorites_manager.load_favorites()
            except Exception:
                pass

        QMessageBox.information(self.main_window, "Import", "Imported: " + ", ".join(imported) + "\nYou can now use Restore without creating a dummy profile.")

    # Opens the settings dialog and applies changes if confirmed.
    @Slot()
    def handle_settings(self, is_initial_setup=False):
        """
        Show settings UI.
        If is_initial_setup=True, show as popup dialog (first launch).
        If in cloud mode, show cloud settings instead of main settings.
        Otherwise, toggle inline panel (show if hidden, hide if visible).
        """
        if is_initial_setup:
            # Use popup dialog for initial setup
            dialog = SettingsDialog(self.main_window.current_settings.copy(), self.main_window, is_initial_setup=True)
            try:
                logging.debug("Updating dialog UI text before showing...")
                dialog.updateUiText()
            except Exception as e_update:
                logging.error(f"Error updating dialog UI text: {e_update}", exc_info=True)
            result = dialog.exec()
        else:
            # Check if we're in cloud mode
            if getattr(self.main_window, '_cloud_mode_active', False):
                # In cloud mode - toggle cloud settings
                if hasattr(self.main_window, 'cloud_panel') and self.main_window.cloud_panel:
                    # Check if cloud settings are currently shown
                    if self.main_window.cloud_panel.stacked_widget.currentIndex() == 1:
                        # Cloud settings are open, close them
                        self.main_window.cloud_panel.exit_cloud_settings()
                        logging.debug("Cloud settings panel toggled OFF (closed).")
                    else:
                        # Cloud settings are closed, open them
                        self.main_window.cloud_panel.show_cloud_settings()
                        logging.debug("Cloud settings panel toggled ON (opened).")
                return  # Exit early for cloud settings
            
            # Toggle inline settings panel (normal mode)
            if getattr(self.main_window, '_settings_mode_active', False):
                # Settings are open, close them (same as Exit button)
                self.main_window.exit_settings_panel()
                logging.debug("Settings panel toggled OFF (closed).")
            else:
                # Close profile editor if it's open before showing settings
                if getattr(self.main_window, '_edit_mode_active', False):
                    self.main_window.profile_editor_group.setVisible(False)
                    self.main_window.profile_group.setVisible(True)
                    self.main_window.exit_profile_edit_mode()
                    logging.debug("Profile editor closed before opening settings.")
                # Settings are closed, open them
                self.main_window.show_settings_panel()
                logging.debug("Settings panel toggled ON (opened).")
            return  # Exit early for inline mode
        
        # Dialog mode - handle result
        result_copy = result  # Keep for checking below
        
        # Handle the result immediately after dialog closes
        if result == QDialog.Accepted:
            new_settings = dialog.get_settings()
            logging.debug(f"New settings received from dialog: {new_settings}")

            # Settings Application Flow:

            # 1. Keep track of old portable flag to detect transition
            old_portable = bool(self.main_window.current_settings.get("portable_config_only", False)) if hasattr(self.main_window, "current_settings") and isinstance(self.main_window.current_settings, dict) else False
            # 1b. Update the main_window's internal settings object immediately.
            self.main_window.current_settings = new_settings

            # 2. Apply theme and update UI
            self.main_window.theme_manager.update_theme()
            self.main_window.updateUiText() # Update UI text

            # 3. Save the updated settings to the configuration file.
            if settings_manager.save_settings(self.main_window.current_settings):
                logging.info("Settings saved successfully after dialog confirmation.")
                self.main_window.status_label.setText("Settings saved.")
                # Decide whether to reload runtime modules/data
                new_portable = bool(self.main_window.current_settings.get("portable_config_only", False))
                need_runtime_reload = new_portable or (new_portable != old_portable)

                # Always reload settings from disk (ensures paths are normalized and persisted)
                try:
                    self.main_window.current_settings, _first = settings_manager.load_settings()
                except Exception as e_load:
                    logging.warning(f"Reloading settings after save failed: {e_load}")

                # If portable is enabled (or changed), point modules to the new active dir immediately and reload data
                if need_runtime_reload:
                    try:
                        import importlib
                        # Reload favorites manager so FAVORITES_FILE_PATH is recomputed using new active dir
                        from gui_components import favorites_manager as _fav
                        importlib.reload(_fav)
                        _fav._cache_loaded = False
                        _fav.load_favorites()
                    except Exception as e_fav:
                        logging.warning(f"Reload favorites after settings change failed: {e_fav}")

                    try:
                        import importlib
                        import core_logic as _cl
                        importlib.reload(_cl)
                        self.main_window.profiles = _cl.load_profiles()
                    except Exception as e_cl:
                        logging.warning(f"Reload profiles after settings change failed: {e_cl}")

                    # Refresh UI bits dependent on profiles/settings
                    try:
                        if hasattr(self.main_window, 'profile_table_manager') and self.main_window.profile_table_manager:
                            self.main_window.profile_table_manager.update_profile_table()
                    except Exception:
                        pass

                # Update the global drag listener state
                try:
                    if hasattr(self.main_window, 'update_global_drag_listener_state'):
                        logging.debug("Calling update_global_drag_listener_state after saving settings.")
                        self.main_window.update_global_drag_listener_state()
                except Exception:
                    logging.warning("Unable to update global drag listener state after settings save.")
            else:
                logging.error("Failed to save settings after dialog confirmation.")
                QMessageBox.warning(self.main_window, "Save Error",
                                   "Failed to save settings to file.")
        else:
            logging.debug("Settings dialog cancelled.")

    # --- Inline Settings Panel Handlers ---
    @Slot()
    def handle_settings_exit(self):
        """Exit the inline settings panel without saving."""
        self.main_window.exit_settings_panel()
        logging.debug("Settings panel closed without saving.")

    @Slot()
    def handle_settings_browse(self):
        """Opens dialog to select backup folder from inline settings panel."""
        directory = QFileDialog.getExistingDirectory(
            self.main_window, "Select Base Folder for Backups", 
            self.main_window.settings_path_edit.text()
        )
        if directory:
            self.main_window.settings_path_edit.setText(os.path.normpath(directory))

    @Slot()
    def handle_settings_save(self):
        """Save settings from the inline settings panel."""
        try:
            # Collect values from inline panel
            new_path = os.path.normpath(self.main_window.settings_path_edit.text())
            new_max_backups = self.main_window.settings_max_backups_spin.value()
            selected_size_index = self.main_window.settings_max_size_combo.currentIndex()
            new_compression_mode = self.main_window.settings_compression_combo.currentData()
            new_check_free_space = self.main_window.settings_space_check_checkbox.isChecked()
            new_portable_mode = self.main_window.settings_portable_checkbox.isChecked()
            new_global_drag = self.main_window.settings_global_drag_checkbox.isChecked()
            new_shorten_paths = self.main_window.settings_shorten_paths_checkbox.isChecked()
            new_minimize_to_tray = self.main_window.settings_minimize_to_tray_checkbox.isChecked()
            
            new_max_src_size_mb = -1
            if 0 <= selected_size_index < len(self.main_window.settings_size_options):
                _, new_max_src_size_mb = self.main_window.settings_size_options[selected_size_index]
            
            # Path validation and creation
            if new_path and not os.path.isdir(new_path):
                reply = QMessageBox.question(
                    self.main_window,
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
                            self.main_window,
                            "Creation Failed",
                            f"Failed to create directory '{new_path}'.\n\nError: {e}"
                        )
                        return
                else:
                    return
            
            # Validate path
            if not hasattr(self.main_window, 'profile_creation_manager') or \
               not self.main_window.profile_creation_manager or \
               not hasattr(self.main_window.profile_creation_manager, 'validate_save_path'):
                logging.error("Unable to validate path: profile_creation_manager missing.")
                QMessageBox.critical(self.main_window, "Internal Error", "Unable to validate path.")
                return
            
            validated_new_path = self.main_window.profile_creation_manager.validate_save_path(
                new_path, context_profile_name="Settings"
            )
            if validated_new_path is None:
                return
            
            # Save old portable flag
            old_portable = bool(self.main_window.current_settings.get("portable_config_only", False))
            
            # Update settings
            new_settings = self.main_window.current_settings.copy()
            new_settings["backup_base_dir"] = validated_new_path
            new_settings["max_backups"] = new_max_backups
            new_settings["max_source_size_mb"] = new_max_src_size_mb
            new_settings["compression_mode"] = new_compression_mode
            new_settings["check_free_space_enabled"] = new_check_free_space
            new_settings["enable_global_drag_effect"] = new_global_drag
            new_settings["shorten_paths_enabled"] = new_shorten_paths
            new_settings["minimize_to_tray_on_close"] = new_minimize_to_tray
            new_settings["portable_config_only"] = new_portable_mode
            
            # Show delete AppData popup only when enabling portable and AppData folder exists
            try:
                if (not old_portable) and new_portable_mode:
                    import config as _cfg
                    appdata_dir = _cfg.get_app_data_folder()
                    appdata_has_configs = False
                    if appdata_dir and os.path.isdir(appdata_dir):
                        # Consider folder existing with any of the known JSONs as present
                        known = ["settings.json", "game_save_profiles.json", "favorites_status.json", "cloud_settings.json"]
                        appdata_has_configs = any(os.path.exists(os.path.join(appdata_dir, n)) for n in known)
                    if appdata_has_configs:
                        reply = QMessageBox.question(
                            self.main_window,
                            "Remove AppData Configuration?",
                            ("You enabled portable mode and a configuration folder was found in AppData:\n\n"
                             f"{appdata_dir}\n\n"
                             "Do you want to delete the AppData configuration after migrating files to the backup folder?"),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            # Set flag - settings_manager.save_settings() will handle the deletion
                            new_settings["_delete_appdata_after_portable"] = True
            except Exception as e:
                logging.warning(f"Error showing AppData deletion prompt: {e}")
            
            # If enabling portable, force runtime override immediately (like settings_dialog.py does)
            if new_portable_mode:
                try:
                    target_dir = os.path.join(validated_new_path, ".savestate")
                    if hasattr(settings_manager, "_RUNTIME_CONFIG_DIR_OVERRIDE"):
                        settings_manager._RUNTIME_CONFIG_DIR_OVERRIDE = target_dir
                        logging.debug(f"Forced runtime config dir override to: {target_dir}")
                except Exception as e_override:
                    logging.warning(f"Error forcing runtime override: {e_override}")
            
            # Apply to main window
            self.main_window.current_settings = new_settings
            
            # Apply theme and update UI
            self.main_window.theme_manager.update_theme()
            self.main_window.updateUiText()
            
            # Save to file
            if settings_manager.save_settings(self.main_window.current_settings):
                logging.info("Settings saved successfully from inline panel.")
                self.main_window.status_label.setText("Settings saved.")
                
                # Reload if portable changed
                new_portable = bool(self.main_window.current_settings.get("portable_config_only", False))
                need_runtime_reload = new_portable or (new_portable != old_portable)
                
                # Reload settings from disk
                try:
                    self.main_window.current_settings, _first = settings_manager.load_settings()
                except Exception as e_load:
                    logging.warning(f"Reloading settings after save failed: {e_load}")
                
                # Reload modules if needed
                if need_runtime_reload:
                    try:
                        import importlib
                        from gui_components import favorites_manager as _fav
                        importlib.reload(_fav)
                        _fav._cache_loaded = False
                        _fav.load_favorites()
                    except Exception as e_fav:
                        logging.warning(f"Reload favorites after settings change failed: {e_fav}")
                    
                    try:
                        import importlib
                        import core_logic as _cl
                        importlib.reload(_cl)
                        self.main_window.profiles = _cl.load_profiles()
                    except Exception as e_cl:
                        logging.warning(f"Reload profiles after settings change failed: {e_cl}")
                    
                    try:
                        if hasattr(self.main_window, 'profile_table_manager') and self.main_window.profile_table_manager:
                            self.main_window.profile_table_manager.update_profile_table()
                    except Exception:
                        pass
                
                # Update global drag listener
                try:
                    if hasattr(self.main_window, 'update_global_drag_listener_state'):
                        logging.debug("Calling update_global_drag_listener_state after saving settings.")
                        self.main_window.update_global_drag_listener_state()
                except Exception:
                    logging.warning("Unable to update global drag listener state after settings save.")
                
                # Close settings panel
                self.main_window.exit_settings_panel()
            else:
                logging.error("Failed to save settings from inline panel.")
                QMessageBox.warning(self.main_window, "Save Error",
                                   "Failed to save settings to file.")
        except Exception as e:
            logging.error(f"Error saving settings from inline panel: {e}", exc_info=True)
            QMessageBox.critical(self.main_window, "Error",
                               f"An error occurred while saving settings:\n\n{str(e)}")

    # --- Profile Actions (Delete, Backup, Restore, Manage, Shortcut) ---
    # Handles the deletion of the selected profile after confirmation.
    @Slot()
    def handle_delete_profile(self):
        # Use the profile manager on the main window to get the name
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: return

        msg_box = QMessageBox(self.main_window)
        msg_box.setWindowTitle("Confirm Deletion")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(
            f"Are you sure you want to delete the profile '{profile_name}'?<br><br>"
            f"<b>This does not delete already created backup files.</b>"
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = msg_box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            # Access main_window.profiles and call core_logic
            if core_logic.delete_profile(self.main_window.profiles, profile_name):
                if core_logic.save_profiles(self.main_window.profiles):
                    # Try to delete the backup folder if it's empty
                    try:
                        backup_base_dir = self.main_window.current_settings.get('backup_base_dir', config.BACKUP_BASE_DIR)
                        profile_backup_folder = os.path.join(backup_base_dir, profile_name)
                        
                        if os.path.exists(profile_backup_folder) and os.path.isdir(profile_backup_folder):
                            # Check if folder is empty (no files, only .savestate folder allowed)
                            folder_contents = os.listdir(profile_backup_folder)
                            # Filter out .savestate folder
                            backup_files = [f for f in folder_contents if f != '.savestate']
                            
                            if not backup_files:
                                # Folder is empty (or only has .savestate), safe to delete
                                import shutil
                                shutil.rmtree(profile_backup_folder)
                                logging.info(f"Deleted empty backup folder: {profile_backup_folder}")
                                self.main_window.status_label.setText("Profile '{0}' deleted (empty backup folder removed).".format(profile_name))
                            else:
                                logging.info(f"Backup folder not empty, keeping it: {profile_backup_folder} ({len(backup_files)} files)")
                                self.main_window.status_label.setText("Profile '{0}' deleted (backup files preserved).".format(profile_name))
                        else:
                            self.main_window.status_label.setText("Profile '{0}' deleted.".format(profile_name))
                    except Exception as e:
                        logging.error(f"Error checking/deleting backup folder for '{profile_name}': {e}")
                        self.main_window.status_label.setText("Profile '{0}' deleted (could not check backup folder).".format(profile_name))
                    
                    self.main_window.profile_table_manager.update_profile_table()
                else:
                    QMessageBox.critical(self.main_window, "Error", "Profile deleted from memory but unable to save changes.")
                    # Reload profiles in main_window
                    self.main_window.profiles = core_logic.load_profiles()
                    self.main_window.profile_table_manager.update_profile_table()
            # else: delete_profile failed (already handled by core_logic likely)

    # Starts the backup process for the selected profile in a worker thread.
    @Slot()
    def handle_backup(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: return

        profile_data = self.main_window.profiles.get(profile_name)
        if not profile_data or not isinstance(profile_data, dict):
            QMessageBox.critical(self.main_window, "Internal Error", "Corrupted or missing profile data for '{0}'.".format(profile_name))
            logging.error(f"Invalid profile data for '{profile_name}': {profile_data}")
            return

        # Check for existing worker thread
        if hasattr(self.main_window, 'worker_thread') and self.main_window.worker_thread and self.main_window.worker_thread.isRunning():
            QMessageBox.information(self.main_window, "Operation in Progress", "Another operation is already in progress.")
            return

        self.main_window.status_label.setText("Starting backup for '{0}'...".format(profile_name))
        self.main_window.set_controls_enabled(False) # Disable controls

        # Determine effective settings (per-profile overrides or global)
        effective = {
            'backup_base_dir': self.main_window.current_settings.get('backup_base_dir', config.BACKUP_BASE_DIR),
            'max_backups': self.main_window.current_settings.get('max_backups', config.MAX_BACKUPS),
            'max_source_size_mb': self.main_window.current_settings.get('max_source_size_mb', 200),
            'compression_mode': self.main_window.current_settings.get('compression_mode', 'standard'),
            'check_free_space_enabled': self.main_window.current_settings.get('check_free_space_enabled', True),
        }
        try:
            if isinstance(profile_data, dict) and profile_data.get('use_profile_overrides') and isinstance(profile_data.get('overrides'), dict):
                ov = profile_data.get('overrides')
                # Do not override backup_base_dir here; base dir remains global unless later requested
                if 'max_backups' in ov: effective['max_backups'] = int(ov['max_backups'])
                if 'max_source_size_mb' in ov: effective['max_source_size_mb'] = int(ov['max_source_size_mb'])
                if 'compression_mode' in ov: effective['compression_mode'] = str(ov['compression_mode'])
                if 'check_free_space_enabled' in ov: effective['check_free_space_enabled'] = bool(ov['check_free_space_enabled'])
        except Exception as e:
            logging.warning(f"Error reading profile overrides, falling back to globals: {e}")

        # Determine which backup function to use
        is_pcsx2_selective_profile = (profile_data.get('emulator') == 'PCSX2' and
                                      'save_dir' in profile_data and
                                      'paths' in profile_data and
                                      isinstance(profile_data['paths'], list) and
                                      len(profile_data['paths']) > 0)

        if is_pcsx2_selective_profile:
            memcard_path = profile_data['paths'][0] # Assuming the first path is the memcard
            save_dir_on_mc = profile_data['save_dir'] # e.g., "BASLUS-12345F0"
            logging.info(f"Using selective PCSX2 backup for '{profile_name}', save_dir: '{save_dir_on_mc}' on memcard: '{memcard_path}'")

            def pcsx2_backup_task(p_name_worker, mc_path_worker, mc_save_dir_worker):
                try:
                    # Use the main window's current settings, don't reload from file
                    backup_dir = effective['backup_base_dir']
                    max_bks = effective['max_backups']
                    max_size_mb = effective['max_source_size_mb']
                    compress_mode = effective['compression_mode']
                    
                    logging.debug(f"pcsx2_backup_task: Calling backup_pcsx2_save with: profile='{p_name_worker}', mc_path='{mc_path_worker}', save_dir='{mc_save_dir_worker}', backup_base_dir='{backup_dir}', max_backups={max_bks}, max_source_size_mb={max_size_mb}, compression_mode='{compress_mode}'")

                    success_worker, result_message_worker = backup_pcsx2_save(
                        p_name_worker, 
                        mc_path_worker, 
                        mc_save_dir_worker,
                        backup_dir,         # backup_base_dir
                        max_bks,            # max_backups
                        max_size_mb,        # max_source_size_mb
                        compress_mode       # compression_mode
                    )
                    return success_worker, result_message_worker
                except Exception as e_bk_worker:
                    err_msg = f"Exception in PCSX2 backup task for '{p_name_worker}': {e_bk_worker}"
                    logging.error(err_msg, exc_info=True)
                    return False, err_msg

            self.main_window.worker_thread = WorkerThread(
                pcsx2_backup_task,
                profile_name, memcard_path, save_dir_on_mc
            )
        else: # Generic backup for other profiles
            source_paths = []
            paths_data = profile_data.get('paths')
            path_data = profile_data.get('path') # Legacy support

            if isinstance(paths_data, list) and paths_data and all(isinstance(p, str) for p in paths_data):
                source_paths = paths_data
            elif isinstance(path_data, str) and path_data:
                source_paths = [path_data]
            else:
                QMessageBox.critical(self.main_window, "Profile Data Error",
                                     "No valid source path ('paths' or 'path') found in profile '{0}'. Unable to backup.".format(profile_name))
                logging.error(f"Invalid source path data for profile '{profile_name}': paths={paths_data}, path={path_data}")
                self.main_window.set_controls_enabled(True)
                return
            
            # Settings needed for core_logic.perform_backup
            if not hasattr(self.main_window, 'current_settings') or not self.main_window.current_settings:
                QMessageBox.critical(self.main_window, self.tr("Internal Error"), self.tr("Settings not loaded correctly."))
                logging.error("current_settings not found on main_window or is empty.")
                self.main_window.set_controls_enabled(True)
                return

            backup_base_dir = effective['backup_base_dir']
            max_backups = effective['max_backups']
            max_source_size_mb = effective['max_source_size_mb']
            compression_mode = effective['compression_mode']
            check_space = effective['check_free_space_enabled']
            min_gb_required = config.MIN_FREE_SPACE_GB

            # Free space check
            if check_space:
                logging.debug(f"Free space check enabled. Threshold: {min_gb_required} GB.")
                min_bytes_required = min_gb_required * 1024 * 1024 * 1024
                try:
                    os.makedirs(backup_base_dir, exist_ok=True)
                    disk_usage = shutil.disk_usage(backup_base_dir)
                    free_bytes = disk_usage.free
                    free_gb = free_bytes / (1024 * 1024 * 1024)
                    logging.debug(f"Free space detected on disk for '{backup_base_dir}': {free_gb:.2f} GB")
                    if free_bytes < min_bytes_required:
                        msg = self.tr("Insufficient disk space for backup!\n\n" +
                                   "Free space: {0:.2f} GB\n" +
                                   "Minimum required space: {1} GB\n\n" +
                                   "Free up space on the destination disk ('{2}') or disable the check in settings.").format(free_gb, min_gb_required, backup_base_dir)
                        QMessageBox.warning(self.main_window, self.tr("Insufficient Disk Space"), msg)
                        self.main_window.set_controls_enabled(True)
                        return
                except FileNotFoundError:
                     msg = self.tr("Error checking space: the specified backup path does not seem to be valid or accessible:\n{0}").format(backup_base_dir)
                     QMessageBox.critical(self.main_window, self.tr("Backup Path Error"), msg)
                     self.main_window.set_controls_enabled(True)
                     return
                except Exception as e_space:
                     msg = self.tr("An error occurred while checking free disk space:\n{0}").format(e_space)
                     QMessageBox.critical(self.main_window, self.tr("Error Checking Space"), msg)
                     logging.error("Error while checking free disk space.", exc_info=True)
                     self.main_window.set_controls_enabled(True)
                     return
            else:
                 logging.debug("Free space check disabled.")

            # TODO: Xemu specialized backup - TEMPORARILY DISABLED
            # Xemu code is commented out until a working system for extracting/injecting
            # saves from the HDD is implemented. When ready, uncomment this block.
            
            # import core_logic  # Import here for both xemu and generic backup
            # profile_data = self.main_window.profiles.get(profile_name, {})
            # if isinstance(profile_data, dict) and profile_data.get('emulator') == 'xemu':
            #     logging.info(f"Using xemu specialized backup for '{profile_name}'")
            #     from emulator_utils.xemu_manager import backup_xbox_save
            #     
            #     # Create backup directory for this profile
            #     sanitized_folder_name = core_logic.sanitize_foldername(profile_name)
            #     profile_backup_dir = os.path.join(backup_base_dir, sanitized_folder_name)
            #     
            #     # Try to find executable path from profile paths
            #     executable_path = None
            #     if 'paths' in profile_data and profile_data['paths']:
            #         # For xemu, the path might be the HDD file, so get its directory
            #         first_path = profile_data['paths'][0]
            #         if first_path.endswith('.qcow2'):
            #             executable_path = os.path.dirname(first_path)
            #     
            #     self.main_window.worker_thread = WorkerThread(
            #         backup_xbox_save,
            #         profile_data.get('id', 'unknown'),
            #         profile_backup_dir,
            #         executable_path
            #     )
            # else:
            
            # Use generic backup for all profiles (including xemu until specialized handler is ready)
            import core_logic
            logging.info(f"Using generic backup for '{profile_name}' with source(s): {source_paths}")
            self.main_window.worker_thread = WorkerThread(
                core_logic.perform_backup,
                profile_name,
                source_paths,
                backup_base_dir,
                max_backups,
                max_source_size_mb,
                compression_mode,
                profile_data  # Pass profile data for emulator-specific handling (e.g., Ymir)
            )

        self.main_window.worker_thread.finished.connect(self.on_operation_finished)
        self.main_window.worker_thread.start()
        logging.info(f"Started backup worker thread for '{profile_name}'.")

    # Opens the restore dialog and starts the restore process if confirmed.
    @Slot()
    def handle_restore(self):
        """Handle restore operation - can work with or without a selected profile."""
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        
        # If we have a profile selected, validate it
        if profile_name:
            profile_data = self.main_window.profiles.get(profile_name)
            if not profile_data or not isinstance(profile_data, dict):
                QMessageBox.critical(self.main_window, "Internal Error", "Corrupted or missing profile data for '{0}'.".format(profile_name))
                logging.error(f"Invalid profile data for '{profile_name}': {profile_data}")
                return

            # Store profile data for later use in the slot
            self._restore_profile_data = {
                'name': profile_name,
                'data': profile_data
            }
        else:
            # No profile selected - will use standalone ZIP restore mode
            self._restore_profile_data = None

        # Create and show dialog (can be with or without profile_name)
        dialog = RestoreDialog(profile_name, self.main_window)
        dialog.finished.connect(lambda result, d=dialog: self.on_restore_dialog_finished(result, d))
        dialog.show()
        
    def on_restore_dialog_finished(self, result, dialog):
        """Handle restore dialog result."""
        if result != QDialog.Accepted:
            return
        
        # Check if we're restoring from a standalone ZIP (no profile selected)
        if not hasattr(self, '_restore_profile_data') or self._restore_profile_data is None:
            # Standalone ZIP restore mode
            self._handle_standalone_zip_restore(dialog)
            return
            
        profile_name = self._restore_profile_data['name']
        profile_data = self._restore_profile_data['data']
        
        if True:  # Changed from "if result == QDialog.Accepted:" since we already checked above
            archive_to_restore = dialog.get_selected_path()
            if archive_to_restore:
                if hasattr(self.main_window, 'worker_thread') and self.main_window.worker_thread and self.main_window.worker_thread.isRunning():
                    QMessageBox.information(self.main_window, "Operation in Progress", "Another operation is already in progress.")
                    return

                is_pcsx2_selective_profile = (profile_data.get('emulator') == 'PCSX2' and
                                              'save_dir' in profile_data and
                                              'paths' in profile_data and
                                              isinstance(profile_data['paths'], list) and
                                              len(profile_data['paths']) > 0)

                if is_pcsx2_selective_profile:
                    memcard_path = profile_data['paths'][0]
                    mc_target_save_dir_name = profile_data['save_dir'].strip('/')
                    archive_filename = os.path.basename(archive_to_restore)

                    confirm_msg = "WARNING!\nRestoring '{archive}' will overwrite the save folder '{save_folder}' on memory card '{memcard}'.\n\nProceed?".format(
                        archive=archive_filename,
                        save_folder=mc_target_save_dir_name,
                        memcard=os.path.basename(memcard_path)
                    )
                    confirm = QMessageBox.warning(self.main_window, "Confirm PCSX2 Restore", confirm_msg,
                                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                  QMessageBox.StandardButton.No)
                    if confirm == QMessageBox.StandardButton.Yes:
                        self.main_window.status_label.setText("Starting PCSX2 restore for '{0}'...".format(profile_name))
                        self.main_window.set_controls_enabled(False)

                        def pcsx2_restore_worker_task(p_name_worker, mc_path_worker, mc_save_dir_worker, archive_path_worker):
                            temp_extract_dir = None
                            try:
                                # Sanitize profile name for temp dir to avoid invalid characters
                                sanitized_p_name_worker = sanitize_filename(p_name_worker)
                                temp_extract_dir = tempfile.mkdtemp(prefix=f"ss_pcsx2_restore_{sanitized_p_name_worker}_") # Use sanitized name
                                logging.debug(f"Temporary extraction dir for PCSX2 restore: {temp_extract_dir}")
                                with zipfile.ZipFile(archive_path_worker, 'r') as zip_ref:
                                    zip_ref.extractall(temp_extract_dir)
                                logging.info(f"Extracted '{archive_path_worker}' to '{temp_extract_dir}'")
                                
                                local_save_data_root = os.path.join(temp_extract_dir, mc_save_dir_worker)
                                if not os.path.isdir(local_save_data_root):
                                    logging.warning(f"Expected save data folder '{local_save_data_root}' not found. Checking for single subfolder.")
                                    extracted_items = [item for item in os.listdir(temp_extract_dir) if os.path.isdir(os.path.join(temp_extract_dir, item))]
                                    if len(extracted_items) == 1:
                                        local_save_data_root = os.path.join(temp_extract_dir, extracted_items[0])
                                        logging.info(f"Using single subfolder '{extracted_items[0]}' as source: {local_save_data_root}")
                                    else:
                                        err_msg = f"Could not find the expected save data folder '{mc_save_dir_worker}' or a unique subfolder within '{temp_extract_dir}'. Found: {extracted_items}"
                                        logging.error(err_msg)
                                        return False, err_msg
                                else:
                                    logging.info(f"Found expected save data folder: {local_save_data_root}")
                                
                                return restore_pcsx2_save(p_name_worker, mc_path_worker, local_save_data_root, mc_save_dir_worker)
                            except Exception as e_worker:
                                error_message = f"Error in PCSX2 restore worker for '{p_name_worker}': {e_worker}"
                                logging.error(error_message, exc_info=True)
                                return False, error_message
                            finally:
                                if temp_extract_dir and os.path.isdir(temp_extract_dir):
                                    try:
                                        shutil.rmtree(temp_extract_dir)
                                        logging.debug(f"Cleaned up temp directory: {temp_extract_dir}")
                                    except Exception as e_cleanup:
                                        logging.error(f"Failed to clean up temp directory {temp_extract_dir}: {e_cleanup}")
                        
                        self.main_window.worker_thread = WorkerThread(
                            pcsx2_restore_worker_task,
                            profile_name, memcard_path, mc_target_save_dir_name, archive_to_restore
                        )
                        self.main_window.worker_thread.finished.connect(self.on_operation_finished)
                        self.main_window.worker_thread.start()
                        logging.info(f"Started PCSX2 restore worker thread for '{profile_name}'.")
                    else:
                        self.main_window.status_label.setText("PCSX2 restore cancelled.")
                else:
                    destination_paths = []
                    paths_data = profile_data.get('paths')
                    path_data = profile_data.get('path')

                    if isinstance(paths_data, list) and paths_data and all(isinstance(p, str) for p in paths_data):
                        destination_paths = paths_data
                    elif isinstance(path_data, str) and path_data:
                        destination_paths = [path_data]
                    else:
                        QMessageBox.critical(self.main_window, "Profile Data Error",
                                             "No valid destination path ('paths' or 'path') found in profile '{0}'. Unable to restore.".format(profile_name))
                        logging.error(f"Invalid destination path data for profile '{profile_name}': paths={paths_data}, path={path_data}")
                        self.main_window.set_controls_enabled(True)
                        return

                    destination_paths_str = "\n".join([f"- {p}" for p in destination_paths])
                    confirm = QMessageBox.warning(self.main_window,
                                                  "Confirm Final Restore",
                                                  "WARNING!\nRestoring '{0}' will overwrite files in the following destinations:\n{1}\n\nProceed?".format(os.path.basename(archive_to_restore), destination_paths_str),
                                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                  QMessageBox.StandardButton.No)

                    if confirm == QMessageBox.StandardButton.Yes:
                        self.main_window.status_label.setText("Starting restore for '{0}'...".format(profile_name))
                        self.main_window.set_controls_enabled(False)
                        self.main_window.worker_thread = WorkerThread(
                            core_logic.perform_restore,
                            profile_name, destination_paths, archive_to_restore, profile_data
                        )
                        self.main_window.worker_thread.finished.connect(self.on_operation_finished)
                        self.main_window.worker_thread.progress.connect(self.main_window.status_label.setText)
                        self.main_window.worker_thread.start()
                        logging.info(f"Started generic restore worker thread for '{profile_name}'.")
                    else:
                        self.main_window.status_label.setText("Restore cancelled.")
            else:
                self.main_window.status_label.setText("No backup selected for restore.")
        else:
            self.main_window.status_label.setText("Backup selection cancelled.")
            
        # Clean up temporary storage
        del self._restore_profile_data

    def _handle_standalone_zip_restore(self, dialog):
        """Handle restore from a standalone ZIP file (no profile selected)."""
        archive_to_restore = dialog.get_selected_path()
        manifest = dialog.get_manifest()
        
        if not archive_to_restore or not manifest:
            QMessageBox.warning(self.main_window, "Restore Error", "No valid backup ZIP selected.")
            return
        
        # Get info from manifest
        profile_name_from_zip = manifest.get("profile_name", "Unknown")
        paths_from_zip = manifest.get("paths", [])
        
        if not paths_from_zip:
            QMessageBox.warning(
                self.main_window, 
                "Invalid Backup", 
                "The backup ZIP does not contain valid path information."
            )
            return
        
        # Ask user for confirmation and destination
        msg = (
            f"This backup contains save data for:\n"
            f"Profile: {profile_name_from_zip}\n\n"
            f"The backup will be restored to the original location(s):\n"
        )
        
        for i, path in enumerate(paths_from_zip[:3]):  # Show max 3 paths
            msg += f"  • {path}\n"
        if len(paths_from_zip) > 3:
            msg += f"  ... and {len(paths_from_zip) - 3} more\n"
        
        msg += "\nDo you want to proceed with the restoration?"
        
        reply = QMessageBox.question(
            self.main_window,
            "Confirm Restore",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Perform the restore using core_logic
        if hasattr(self.main_window, 'worker_thread') and self.main_window.worker_thread and self.main_window.worker_thread.isRunning():
            QMessageBox.information(self.main_window, "Operation in Progress", "Another operation is already in progress.")
            return
        
        # Start restore in background thread
        self.main_window.set_controls_enabled(False)
        self.main_window.status_label.setText(f"Restoring backup from ZIP...")
        
        def do_restore_work():
            """Worker function for restore."""
            return core_logic.perform_restore(
                profile_name_from_zip,
                paths_from_zip,
                archive_to_restore
            )
        
        def on_restore_finished(result):
            """Callback when restore is finished."""
            self.main_window.set_controls_enabled(True)
            success, message = result
            if success:
                QMessageBox.information(self.main_window, "Restore Successful", message)
                self.main_window.status_label.setText("Restore completed successfully.")
            else:
                QMessageBox.critical(self.main_window, "Restore Failed", message)
                self.main_window.status_label.setText("Restore failed.")
        
        # Create and start worker thread
        self.main_window.worker_thread = WorkerThread(do_restore_work)
        self.main_window.worker_thread.result_ready.connect(on_restore_finished)
        self.main_window.worker_thread.start()
        logging.info(f"Started standalone ZIP restore from: {archive_to_restore}")

    # Opens the manage backups dialog for the selected profile.
    @Slot()
    def handle_manage_backups(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: QMessageBox.warning(self.main_window, "Error", "No profile selected."); return
        dialog = ManageBackupsDialog(profile_name, self.main_window) # Pass main_window as parent
        dialog.finished.connect(self.on_manage_backups_finished)
        dialog.show()
        
    def on_manage_backups_finished(self):
        """Handle manage backups dialog closing."""
        # Update table in main window after dialog closes
        self.main_window.profile_table_manager.update_profile_table()

    # Creates a desktop shortcut to backup the selected profile.
    @Slot(str) # Original had profile_name argument, but it wasn't used inside
    def handle_create_shortcut(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name:
             logging.warning("handle_create_shortcut called without selected profile.")
             QMessageBox.warning(self.main_window, "Failed Action", "No profile selected to create shortcut.")
             return

        logging.info(f"Request to create shortcut for profile: '{profile_name}'")
        # Call utility function
        success, message = shortcut_utils.create_backup_shortcut(profile_name=profile_name)
        if success:
            QMessageBox.information(self.main_window, "Shortcut Creation", message)
        else:
            QMessageBox.warning(self.main_window, "Error Creating Shortcut", message)

    # --- Inline Profile Editor Handlers ---
    @Slot()
    def handle_show_edit_profile(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name:
            QMessageBox.warning(self.main_window, "No Selection", "Select a profile to edit.")
            return
        try:
            # Hide side menu while editing
            if hasattr(self.main_window, 'profile_side_group'):
                self.main_window.profile_side_group.setVisible(False)
            self.main_window.show_profile_editor(profile_name)
        except Exception as e:
            logging.error(f"Error opening inline profile editor: {e}")

    @Slot()
    def handle_profile_edit_browse(self):
        try:
            current = self.main_window.edit_path_edit.text() if hasattr(self.main_window, 'edit_path_edit') else ""
            directory = QFileDialog.getExistingDirectory(self.main_window, "Select Save Folder", current)
            if directory:
                self.main_window.edit_path_edit.setText(os.path.normpath(directory))
        except Exception as e:
            logging.error(f"Error in browse for profile editor: {e}")

    @Slot()
    def handle_profile_edit_save(self):
        try:
            mw = self.main_window
            if not hasattr(mw, '_editing_profile_original_name'):
                QMessageBox.warning(mw, "Edit Error", "No profile is being edited.")
                return
            original_name = mw._editing_profile_original_name
            new_name_input = mw.edit_name_edit.text().strip()
            new_name = shortcut_utils.sanitize_profile_name(new_name_input)
            if not new_name:
                QMessageBox.warning(mw, "Name Error", f"Invalid or empty profile name: '{new_name_input}'.")
                return
            # Check name conflict
            if new_name != original_name and new_name in mw.profiles:
                QMessageBox.warning(mw, "Duplicate Name", f"A profile named '{new_name}' already exists.")
                return

            # Validate path
            new_path_input = mw.edit_path_edit.text().strip()
            if not new_path_input:
                QMessageBox.warning(mw, "Path Error", "The path cannot be empty.")
                return
            validator = None
            if hasattr(mw, 'profile_creation_manager') and hasattr(mw.profile_creation_manager, 'validate_save_path'):
                validator = mw.profile_creation_manager.validate_save_path
            else:
                validator = lambda p, _n: p if os.path.isdir(p) else None
            validated_path = validator(new_path_input, new_name)
            if not validated_path:
                return  # Validator shows message

            # Build new profile data preserving other keys
            old_data = mw.profiles.get(original_name, {}) if isinstance(mw.profiles.get(original_name), dict) else {}
            new_data = dict(old_data)
            new_data['path'] = validated_path
            if isinstance(new_data.get('paths'), list) and new_data['paths']:
                new_paths = list(new_data['paths'])
                new_paths[0] = validated_path
                new_data['paths'] = new_paths

            # Capture overrides UI state without applying to globals
            use_overrides = bool(mw.overrides_enable_checkbox.isChecked())
            new_data['use_profile_overrides'] = use_overrides
            overrides_dict = dict(new_data.get('overrides') or {})
            overrides_dict['max_backups'] = int(mw.override_max_backups_spin.value())
            overrides_dict['compression_mode'] = str(mw.override_compression_combo.currentText())
            # Read size from combo options (aligned with SettingsDialog options)
            try:
                size_index = mw.override_max_size_combo.currentIndex()
                size_value = -1
                if 0 <= size_index < len(mw.override_size_options):
                    _, size_value = mw.override_size_options[size_index]
                overrides_dict['max_source_size_mb'] = int(size_value)
            except Exception:
                overrides_dict['max_source_size_mb'] = int(mw.current_settings.get('max_source_size_mb', 500))
            overrides_dict['check_free_space_enabled'] = bool(mw.override_check_space_checkbox.isChecked())
            new_data['overrides'] = overrides_dict

            # Apply rename if needed
            if new_name != original_name:
                # Update favorites mapping if needed
                try:
                    from gui_components import favorites_manager
                    if favorites_manager.is_favorite(original_name):
                        favorites_manager.set_favorite_status(new_name, True)
                        favorites_manager.remove_profile(original_name)
                except Exception as e_fav:
                    logging.warning(f"Failed to migrate favorites on rename: {e_fav}")

                if original_name in mw.profiles:
                    del mw.profiles[original_name]
                mw.profiles[new_name] = new_data
            else:
                mw.profiles[original_name] = new_data

            if core_logic.save_profiles(mw.profiles):
                # Update UI back to profiles list
                if hasattr(mw, 'profile_editor_group'):
                    mw.profile_editor_group.setVisible(False)
                if hasattr(mw, 'profile_group'):
                    mw.profile_group.setVisible(True)
                if hasattr(mw, 'exit_profile_edit_mode'):
                    mw.exit_profile_edit_mode()
                mw.status_label.setText(f"Profile '{new_name}' updated.")
                if hasattr(mw, 'profile_table_manager'):
                    mw.profile_table_manager.update_profile_table()
                    mw.profile_table_manager.select_profile_in_table(new_name)
                QMessageBox.information(mw, "Profile Updated", f"Profile '{new_name}' saved successfully.")
                # Clear edit state
                mw._editing_profile_original_name = None
            else:
                QMessageBox.critical(mw, "Save Error", "Unable to save the profiles file.")
        except Exception as e:
            logging.error(f"Error saving profile edits: {e}", exc_info=True)
            QMessageBox.critical(self.main_window, "Edit Error", f"An error occurred: {e}")

    @Slot()
    def handle_profile_edit_cancel(self):
        try:
            mw = self.main_window
            if hasattr(mw, 'profile_editor_group'):
                mw.profile_editor_group.setVisible(False)
            if hasattr(mw, 'profile_group'):
                mw.profile_group.setVisible(True)
            if hasattr(mw, 'exit_profile_edit_mode'):
                mw.exit_profile_edit_mode()
            mw._editing_profile_original_name = None
        except Exception as e:
            logging.error(f"Error cancelling profile edit: {e}")

    @Slot(bool)
    def handle_profile_overrides_toggled(self, enabled):
        try:
            if hasattr(self.main_window, 'overrides_group'):
                self.main_window.overrides_group.setEnabled(bool(enabled))
        except Exception as e:
            logging.error(f"Error toggling overrides group: {e}")

    # --- Steam Handling ---
    # Scans Steam data and opens the Steam configuration dialog.
    @Slot()
    def handle_steam(self):
        try:
            logging.info("Scanning Steam data before opening dialog...")
            # Reset core_logic cached data before scanning
            core_logic._steam_install_path = None
            core_logic._steam_libraries = None
            core_logic._installed_steam_games = None
            core_logic._steam_userdata_path = None
            core_logic._steam_id3 = None
            core_logic._cached_possible_ids = None
            core_logic._cached_id_details = None

            steam_path = core_logic.get_steam_install_path()
            if not steam_path: raise ValueError("Steam installation not found.")

            # Store data directly on the main_window instance for access by start_steam_configuration
            self.main_window.steam_games_data = core_logic.find_installed_steam_games()
            udp, l_id, p_ids, d_ids = core_logic.find_steam_userdata_info()
            self.main_window.steam_userdata_info = {'path': udp, 'likely_id': l_id, 'possible_ids': p_ids, 'details': d_ids}
            logging.info("Steam data scan complete.")

        except Exception as e_scan:
            logging.error(f"Error scanning Steam data: {e_scan}", exc_info=True)
            QMessageBox.critical(self.main_window, "Steam Scan Error", "Unable to read Steam data:\n{0}".format(e_scan))
            return

        # Pass main_window reference and parent
        dialog = SteamDialog(main_window_ref=self.main_window, parent=self.main_window)
        # Connect dialog signal to the handler method in this class
        dialog.game_selected_for_config.connect(self.start_steam_configuration)
        dialog.exec()

    # Starts the configuration process after a Steam game is selected.
    @Slot(str, str) # Receives appid, profile_name
    def start_steam_configuration(self, appid, profile_name):
        logging.info(f"Starting configuration process for '{profile_name}' (AppID: {appid}) via handler.")

        # Access scanned data stored on main_window
        game_data = self.main_window.steam_games_data.get(appid)
        if not game_data:
            logging.error(f"Game data for {appid} not found in main_window.steam_games_data.")
            QMessageBox.critical(self.main_window, "Internal Error", f"Game data missing for AppID {appid}.")
            return
        install_dir = game_data.get('installdir')

        steam_userdata_path = self.main_window.steam_userdata_info.get('path')
        likely_id3 = self.main_window.steam_userdata_info.get('likely_id')
        possible_ids = self.main_window.steam_userdata_info.get('possible_ids', [])
        id_details = self.main_window.steam_userdata_info.get('details', {})
        steam_id_to_use = likely_id3

        # Ask for user ID if multiple found
        if len(possible_ids) > 1:
            id_choices_display = []
            display_to_id_map = {}
            index_to_select = 0
            for i, uid in enumerate(possible_ids):
                user_details = id_details.get(uid, {})
                display_name = user_details.get('display_name', uid)
                last_mod_str = user_details.get('last_mod_str', 'N/D')
                # Mark the likely (most recent) Steam ID
                is_likely_marker = "(Recent)" if uid == likely_id3 else ""
                choice_str = f"{display_name} {is_likely_marker} [{last_mod_str}]".strip().replace("  ", " ")
                id_choices_display.append(choice_str)
                display_to_id_map[choice_str] = uid
                if uid == likely_id3: index_to_select = i

            dialog_label_text = (
                "Multiple Steam profiles found.\n"
                "Select the correct one (usually the most recent):"
            )
            chosen_display_str, ok = QInputDialog.getItem(
                 self.main_window, "Select Steam Profile", dialog_label_text,
                 id_choices_display, index_to_select, False
            )
            if ok and chosen_display_str:
                selected_id3 = display_to_id_map.get(chosen_display_str)
                if selected_id3: steam_id_to_use = selected_id3
                else: logging.error("Error mapping choice back to Steam ID"); QMessageBox.warning(self.main_window, "Error", "Selected Steam ID is invalid."); return
            else:
                self.main_window.status_label.setText("Configuration cancelled (no Steam profile selected).")
                return
        elif not steam_id_to_use and len(possible_ids) == 1: steam_id_to_use = possible_ids[0]
        elif not possible_ids: logging.warning("No Steam user IDs found.")

        # Start Fade Effect on main_window
        can_show_effect = False
        try:
            has_overlay = hasattr(self.main_window, 'overlay_widget') and self.main_window.overlay_widget is not None
            has_label = hasattr(self.main_window, 'loading_label') and self.main_window.loading_label is not None
            has_center_func = hasattr(self.main_window, '_center_loading_label')
            has_fade_in = hasattr(self.main_window, 'fade_in_animation') and self.main_window.fade_in_animation is not None
            can_show_effect = (has_overlay and has_label and has_center_func and has_fade_in)
            logging.debug(f"Fade check results: overlay={has_overlay}, label={has_label}, center={has_center_func}, fade_in={has_fade_in}")
        except Exception as e: logging.error(f"Error checking fade components: {e}", exc_info=True)

        if can_show_effect:
            logging.info("Activating fade effect...")
            try:
                # Call methods on main_window to show overlay
                self.main_window.loading_label.setText("Searching...") # Set text for Steam search
                self.main_window.loading_label.adjustSize() # Ensure label resizes to content
                self.main_window.overlay_widget.resize(self.main_window.centralWidget().size())
                self.main_window.overlay_widget.show() # Show overlay first
                self.main_window.overlay_widget.raise_() # Ensure it's on top
                self.main_window._center_loading_label() # Center label on now-visible overlay
                self.main_window.loading_label.show() # Explicitly show the label
                self.main_window.fade_in_animation.start()
            except Exception as e_fade: logging.error(f"Error starting fade: {e_fade}", exc_info=True)
        else:
            logging.error("Cannot show fade effect (components missing or check failed).")

        # Start Search Thread
        self.main_window.status_label.setText("Searching for path for '{0}'...".format(profile_name))
        QApplication.processEvents()

        logging.info("Starting SteamSearchWorkerThread from handler...")
        # Assign thread to main_window's attribute
        thread = SteamSearchWorkerThread(
            game_name=profile_name,
            game_install_dir=install_dir,
            appid=appid,
            steam_userdata_path=steam_userdata_path,
            steam_id3_to_use=steam_id_to_use,
            installed_steam_games_dict=self.main_window.steam_games_data,
            profile_name_for_results=profile_name,
            cancellation_manager=self.main_window.cancellation_manager  # <-- FIX: passa il cancellation_manager
        )
        # Connect thread finished signal to handler method
        thread.finished.connect(self.handle_steam_search_results)
        self.main_window.current_search_thread = thread
        
        # Reset del cancellation_manager prima di avviare una nuova ricerca
        if hasattr(self.main_window, 'cancellation_manager') and self.main_window.cancellation_manager:
            self.main_window.cancellation_manager.reset()
            logging.debug("Cancellation manager reset before starting new search thread")
        
        self.main_window.set_controls_enabled(False)
        thread.start()

    # Handles the results from the Steam save path search worker thread.
    @Slot(bool, dict) # Receives success, results_dict
    def handle_steam_search_results(self, success, results_dict):
        guesses_with_scores = results_dict.get('path_data', [])
        profile_name_from_thread = results_dict.get('profile_name_suggestion', '')
        game_install_dir = results_dict.get('game_install_dir')
        logging.debug(f"Handling Steam search results for '{profile_name_from_thread}'. Guesses: {len(guesses_with_scores)}")

        # Reset thread reference on main_window
        self.main_window.current_search_thread = None
        self.main_window.set_controls_enabled(True)

        # Stop Fade Effect on main_window
        if hasattr(self.main_window, 'fade_out_animation') and self.main_window.fade_out_animation:
            if self.main_window.fade_out_animation.state() != QPropertyAnimation.State.Running:
                self.main_window.fade_out_animation.start()
                logging.debug("Fade-out animation started.")
            else:
                logging.debug("Fade-out animation already running or finished.")
        elif hasattr(self.main_window, 'overlay_widget') and self.main_window.overlay_widget.isVisible():
             self.main_window.overlay_widget.hide()
             logging.debug("Overlay hidden via fallback.")

        # Process results and ask user
        profile_name = profile_name_from_thread
        confirmed_path = None
        existing_path = self.main_window.profiles.get(profile_name, {}).get('path') # Get path from profile dict

        if not guesses_with_scores:
            logging.info(f"No paths guessed by search thread for '{profile_name}'.")
            if not existing_path:
                # Ask user to input path manually if none found and none exists
                QMessageBox.information(self.main_window, "Path Not Found",
                                        "Could not automatically find a path for '{0}'.\n" +
                                        "Please enter it manually.".format(profile_name))
                confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
            else:
                # Ask user if they want to keep the existing path or enter manually
                reply = QMessageBox.question(self.main_window, "No New Path Found",
                                             "Automatic search did not find new paths.\n" +
                                             "Do you want to keep the current path?\n'{0}'".format(existing_path),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes: confirmed_path = existing_path
                elif reply == QMessageBox.StandardButton.No: confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
        else:
            # Build model for custom selection dialog
            try:
                from gui_components.save_path_selection_dialog import SavePathSelectionDialog
            except Exception as e_imp:
                logging.error(f"Failed to import SavePathSelectionDialog: {e_imp}")
                QMessageBox.critical(self.main_window, "UI Error", "Internal UI component missing.")
                return

            items_for_dialog = []
            current_selection_index = 0
            norm_existing = os.path.normpath(existing_path) if existing_path else None
            for i, guess in enumerate(guesses_with_scores):
                try:
                    p = guess[0]
                    s = guess[1]
                    has = bool(guess[2]) if len(guess) > 2 else None
                except Exception:
                    continue
                items_for_dialog.append({"path": p, "score": s, "has_saves": has})
                if norm_existing and os.path.normpath(p) == norm_existing:
                    current_selection_index = i

            if existing_path and not any(os.path.normpath(d["path"]) == norm_existing for d in items_for_dialog):
                logging.warning(f"Existing path '{existing_path}' was not found in the suggested paths list.")

            dialog_label_text = (
                "These potential paths have been found for '{0}'.\n"
                "Select the correct one (sorted by probability) or choose manual input:"
            ).format(profile_name)

            shorten_flag = True
            try:
                shorten_flag = bool(self.main_window.current_settings.get("shorten_paths_enabled", True))
            except Exception:
                shorten_flag = True

            dlg = SavePathSelectionDialog(
                items=items_for_dialog,
                title="Confirm Save Path",
                prompt_text=dialog_label_text,
                show_scores=self.main_window.developer_mode_enabled,
                shorten_paths=shorten_flag,
                game_install_dir=game_install_dir,
                preselect_index=current_selection_index,
                parent=self.main_window,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.is_manual_selected():
                    confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
                else:
                    confirmed_path = dlg.get_selected_path()
            else:
                confirmed_path = None

        # Save profile if path confirmed
        if confirmed_path:
            # Use validation from the main window's profile creation manager
            validator_func = None
            if hasattr(self.main_window, 'profile_creation_manager') and self.main_window.profile_creation_manager and hasattr(self.main_window.profile_creation_manager, 'validate_save_path'):
                 validator_func = self.main_window.profile_creation_manager.validate_save_path
            else:
                logging.warning("ProfileCreationManager validator not found, using basic os.path.isdir validation.")
                def basic_validator(p, _name): return p if os.path.isdir(p) else None
                validator_func = basic_validator

            validated_path = validator_func(confirmed_path, profile_name)
            if validated_path:
                logging.info(f"Saving profile '{profile_name}' with path '{validated_path}' via handler.")
                # Update the profile dictionary and save all profiles
                self.main_window.profiles[profile_name] = {'path': validated_path}
                if core_logic.save_profiles(self.main_window.profiles):
                    self.main_window.status_label.setText("Profile '{0}' configured.".format(profile_name))
                    self.main_window.profile_table_manager.update_profile_table()
                    self.main_window.profile_table_manager.select_profile_in_table(profile_name)
                    QMessageBox.information(self.main_window, "Profile Configured", "Profile '{0}' saved successfully.".format(profile_name))
                else:
                    QMessageBox.critical(self.main_window, "Save Error", "Unable to save profiles file.")
                    if profile_name in self.main_window.profiles: del self.main_window.profiles[profile_name]
            # else: Validator already showed error message
        else:
             self.main_window.status_label.setText("Profile configuration cancelled or failed.")

    # Prompts the user to manually enter the save path for a profile.
    # Helper for manual path input (used by steam search results)
    def _ask_user_for_path_manually(self, profile_name, existing_path):
        input_path, ok = QInputDialog.getText(self.main_window, "Manual Path",
                                            "Enter the FULL path to the save game folder for '{0}':".format(profile_name),
                                            text=existing_path or "")
        if ok and input_path:
             # Use validation from the main window's profile creation manager
             if hasattr(self.main_window, 'profile_creation_manager') and self.main_window.profile_creation_manager:
                  validated = self.main_window.profile_creation_manager.validate_save_path(input_path, profile_name)
                  return validated
             else:
                  # Basic fallback validation
                  return input_path if os.path.isdir(input_path) else None
        return None

    # --- Worker Thread Callback ---
    # Callback slot for when the backup/restore worker thread finishes.
    @Slot(bool, str)
    def on_operation_finished(self, success, message):
        main_message = message.splitlines()[0] if message else "Operation finished without message."
        status_text = "Completed: {0}" if success else "ERROR: {0}"
        self.main_window.status_label.setText(status_text.format(main_message))
        self.main_window.set_controls_enabled(True)
        self.main_window.worker_thread = None # Clear worker thread reference on main window

        if not success:
            QMessageBox.critical(self.main_window, "Operation Error", message)
        else:
            logging.debug("Operation thread worker successful, updating profile table view.")

        # Always update the table to reflect changes (e.g., backup info)
        self.main_window.profile_table_manager.update_profile_table()

# --- FINE METODI HANDLERS ---

# --- End of MainWindowHandlers class --- 