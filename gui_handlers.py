# gui_handlers.py
# -*- coding: utf-8 -*-

import os
import logging
import shutil

from PySide6.QtWidgets import QMessageBox, QDialog, QInputDialog, QApplication
from PySide6.QtCore import Slot, QUrl, QPropertyAnimation, QTimer
from PySide6.QtGui import QDesktopServices

# Import dialogs
from dialogs.settings_dialog import SettingsDialog
from dialogs.restore_dialog import RestoreDialog
from dialogs.manage_backups_dialog import ManageBackupsDialog
from dialogs.steam_dialog import SteamDialog

# Import core logic, utils, managers
import core_logic
import settings_manager
import shortcut_utils
import config
from gui_utils import WorkerThread, SteamSearchWorkerThread


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
        backup_dir = self.main_window.current_settings.get("backup_base_dir")

        if not backup_dir:
            QMessageBox.warning(self.main_window, "Error", "Backup base directory not configured in settings.")
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

    # Opens the settings dialog and applies changes if confirmed.
    @Slot()
    def handle_settings(self):
        # Language handling removed - application is now English-only
        # Pass a copy and the main window as parent
        dialog = SettingsDialog(self.main_window.current_settings.copy(), self.main_window)
        try:
            logging.debug("Updating dialog UI text before showing...")
            dialog.updateUiText() # Force update text
        except Exception as e_update:
            logging.error(f"Error updating dialog UI text: {e_update}", exc_info=True)

        if dialog.exec() == QDialog.Accepted:
            new_settings = dialog.get_settings()
            logging.debug(f"New settings received from dialog: {new_settings}")

            # Settings Application Flow:

            # 1. Update the main_window's internal settings object immediately.
            self.main_window.current_settings = new_settings

            # 2. Apply theme and update UI
            self.main_window.theme_manager.update_theme()
            self.main_window.updateUiText() # Update UI text

            # 3. Save the updated settings to the configuration file.
            if settings_manager.save_settings(self.main_window.current_settings):
                logging.info("Settings saved successfully after dialog confirmation.")
                self.main_window.status_label.setText("Settings saved.")
            else:
                logging.error("Failed to save settings after dialog confirmation.")
                QMessageBox.warning(self.main_window, "Save Error",
                                   "Failed to save settings to file.")
        else:
            logging.debug("Settings dialog cancelled.")

    # --- Profile Actions (Delete, Backup, Restore, Manage, Shortcut) ---
    # Handles the deletion of the selected profile after confirmation.
    @Slot()
    def handle_delete_profile(self):
        # Use the profile manager on the main window to get the name
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: return

        reply = QMessageBox.warning(self.main_window, "Confirm Deletion",
                                    "Are you sure you want to delete the profile '{0}'?\n(This does not delete already created backup files).".format(profile_name),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # Access main_window.profiles and call core_logic
            if core_logic.delete_profile(self.main_window.profiles, profile_name):
                if core_logic.save_profiles(self.main_window.profiles):
                    self.main_window.profile_table_manager.update_profile_table()
                    self.main_window.status_label.setText("Profile '{0}' deleted.".format(profile_name))
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

        # --- Modified Path Handling START ---
        source_paths = [] # Initialize empty list
        paths_data = profile_data.get('paths')
        path_data = profile_data.get('path')

        if isinstance(paths_data, list) and paths_data and all(isinstance(p, str) for p in paths_data):
            source_paths = paths_data
            logging.debug(f"Using 'paths' key for profile '{profile_name}': {source_paths}")
        elif isinstance(path_data, str) and path_data:
            source_paths = [path_data] # Create a list from the single path
            logging.debug(f"Using 'path' key for profile '{profile_name}': {source_paths}")
        else:
            QMessageBox.critical(self.main_window, "Profile Data Error",
                                 "No valid source path ('paths' or 'path') found in profile '{0}'. Check profile.".format(profile_name))
            logging.error(f"Invalid path data for profile '{profile_name}': paths={paths_data}, path={path_data}")
            return

        # Validate each path in the determined list
        invalid_paths = []
        for path in source_paths:
            # Use os.path.exists to validate both files and directories
            if not os.path.exists(path):
                invalid_paths.append(path)

        if invalid_paths:
            # Use parentheses for cleaner multi-line string concatenation
            error_message = ("One or more source paths do not exist or are invalid:" + "\n" +
                             "\n".join(invalid_paths))
            QMessageBox.critical(self.main_window, "Source Path Error", error_message)
            return
        # --- Modified Path Handling END ---

        # Access main_window's settings
        backup_dir = self.main_window.current_settings.get("backup_base_dir")
        max_bk = self.main_window.current_settings.get("max_backups")
        max_src_size = self.main_window.current_settings.get("max_source_size_mb")
        compression_mode = self.main_window.current_settings.get("compression_mode", "standard")
        check_space = self.main_window.current_settings.get("check_free_space_enabled", True)
        min_gb_required = config.MIN_FREE_SPACE_GB

        if not backup_dir or max_bk is None or max_src_size is None:
            QMessageBox.critical(self.main_window, "Configuration Error", "Required settings (backup base dir, max backup, max source size) not found or invalid!")
            return

        # Free space check
        if check_space:
            logging.debug(f"Free space check enabled. Threshold: {min_gb_required} GB.")
            min_bytes_required = min_gb_required * 1024 * 1024 * 1024
            try:
                os.makedirs(backup_dir, exist_ok=True)
                disk_usage = shutil.disk_usage(backup_dir)
                free_bytes = disk_usage.free
                free_gb = free_bytes / (1024 * 1024 * 1024)
                logging.debug(f"Free space detected on disk for '{backup_dir}': {free_gb:.2f} GB")
                if free_bytes < min_bytes_required:
                    msg = ("Insufficient disk space for backup!\n\n" +
                           "Free space: {0:.2f} GB\n" +
                           "Minimum required space: {1} GB\n\n" +
                           "Free up space on the destination disk ('{2}') or disable the check in settings.").format(free_gb, min_gb_required, backup_dir)
                    QMessageBox.warning(self.main_window, "Insufficient Disk Space", msg)
                    return
            except FileNotFoundError:
                 msg = "Error checking space: the specified backup path does not seem to be valid or accessible:\n{0}".format(backup_dir)
                 QMessageBox.critical(self.main_window, "Backup Path Error", msg)
                 return
            except Exception as e_space:
                 msg = "An error occurred while checking free disk space:\n{0}".format(e_space)
                 QMessageBox.critical(self.main_window, "Error Checking Space", msg)
                 logging.error("Error while checking free disk space.", exc_info=True)
                 return
        else:
             logging.debug("Free space check disabled.")

        # Check for existing worker thread on main_window
        if hasattr(self.main_window, 'worker_thread') and self.main_window.worker_thread and self.main_window.worker_thread.isRunning():
             QMessageBox.information(self.main_window, "Operation in Progress", "A backup or restore is already in progress. Wait for completion.")
             return

        # Set status and controls on main_window
        self.main_window.status_label.setText("Starting backup for '{0}'...".format(profile_name))
        self.main_window.set_controls_enabled(False)

        # Create and assign WorkerThread to main_window
        self.main_window.worker_thread = WorkerThread(
            core_logic.perform_backup,
            # Pass the list of source_paths instead of single save_path
            profile_name, source_paths, backup_dir, max_bk, max_src_size, compression_mode
        )
        # Connect signals to slots in this handler class
        self.main_window.worker_thread.finished.connect(self.on_operation_finished)
        # Progress still updates the main window's status label directly
        self.main_window.worker_thread.progress.connect(self.main_window.status_label.setText)
        self.main_window.worker_thread.start()
        logging.debug(f"Started backup thread for profile '{profile_name}'.")

    # Opens the restore dialog and starts the restore process if confirmed.
    @Slot()
    def handle_restore(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: return

        profile_data = self.main_window.profiles.get(profile_name)
        if not profile_data or not isinstance(profile_data, dict):
            QMessageBox.critical(self.main_window, "Internal Error", "Corrupted or missing profile data for '{0}'.".format(profile_name))
            logging.error(f"Invalid profile data for '{profile_name}' during restore: {profile_data}")
            return

        # --- Determine Destination Paths START ---
        destination_paths = []
        paths_data = profile_data.get('paths')
        path_data = profile_data.get('path')

        if isinstance(paths_data, list) and paths_data and all(isinstance(p, str) for p in paths_data):
            destination_paths = paths_data
            logging.debug(f"Restore target using 'paths': {destination_paths}")
        elif isinstance(path_data, str) and path_data:
            destination_paths = [path_data]
            logging.debug(f"Restore target using 'path': {destination_paths}")
        else:
            QMessageBox.critical(self.main_window, "Profile Data Error",
                                 "No valid destination path ('paths' or 'path') found in profile '{0}'. Unable to restore.".format(profile_name))
            logging.error(f"Invalid destination path data for profile '{profile_name}': paths={paths_data}, path={path_data}")
            return
        # --- Determine Destination Paths END ---

        dialog = RestoreDialog(profile_name, self.main_window) # Pass main_window as parent
        if dialog.exec():
            archive_to_restore = dialog.get_selected_path()
            if archive_to_restore:
                # Format destination paths for display in the message box
                destination_paths_str = "\n".join([f"- {p}" for p in destination_paths])
                confirm = QMessageBox.warning(self.main_window,
                                              "Confirm Final Restore",
                                              # Updated message to show all destination paths
                                              "WARNING!\nRestoring '{0}' will overwrite files in the following destinations:\n{1}\n\nProceed?".format(os.path.basename(archive_to_restore), destination_paths_str),
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                              QMessageBox.StandardButton.No)

                if confirm == QMessageBox.StandardButton.Yes:
                    # Check for existing worker thread
                    if hasattr(self.main_window, 'worker_thread') and self.main_window.worker_thread and self.main_window.worker_thread.isRunning():
                        QMessageBox.information(self.main_window, "Operation in Progress", "Another operation is already in progress.")
                        return

                    self.main_window.status_label.setText("Starting restore for '{0}'...".format(profile_name))
                    self.main_window.set_controls_enabled(False)

                    self.main_window.worker_thread = WorkerThread(
                        core_logic.perform_restore,
                        # Pass the list of destination paths
                        profile_name, destination_paths, archive_to_restore
                    )
                    self.main_window.worker_thread.finished.connect(self.on_operation_finished)
                    self.main_window.worker_thread.progress.connect(self.main_window.status_label.setText)
                    self.main_window.worker_thread.start()
                    logging.info(f"Started restore worker thread for '{profile_name}'.")
                else:
                    self.main_window.status_label.setText("Restore cancelled.")
            else:
                self.main_window.status_label.setText("No backup selected for restore.")
        else:
            self.main_window.status_label.setText("Backup selection cancelled.")

    # Opens the manage backups dialog for the selected profile.
    @Slot()
    def handle_manage_backups(self):
        profile_name = self.main_window.profile_table_manager.get_selected_profile_name()
        if not profile_name: QMessageBox.warning(self.main_window, "Error", "No profile selected."); return
        dialog = ManageBackupsDialog(profile_name, self.main_window) # Pass main_window as parent
        dialog.exec()
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
                self.main_window.overlay_widget.resize(self.main_window.centralWidget().size())
                self.main_window._center_loading_label()
                self.main_window.overlay_widget.show()
                self.main_window.overlay_widget.raise_()
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
            profile_name_for_results=profile_name
        )
        # Connect thread finished signal to handler method
        thread.finished.connect(self.handle_steam_search_results)
        self.main_window.current_search_thread = thread
        self.main_window.set_controls_enabled(False)
        thread.start()

    # Handles the results from the Steam save path search worker thread.
    @Slot(list, str) # Receives guesses_with_scores, profile_name_from_thread
    def handle_steam_search_results(self, guesses_with_scores, profile_name_from_thread):
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
            path_choices = []
            display_text_to_original_path = {}
            current_selection_index = 0
            existing_path_found_in_list = False
            show_scores = self.main_window.developer_mode_enabled
            logging.debug(f"Preparing QInputDialog items. Show scores: {show_scores}")

            norm_existing = os.path.normpath(existing_path) if existing_path else None
            for i, (p, score) in enumerate(guesses_with_scores):
                norm_p = os.path.normpath(p)
                is_current_marker = "[CURRENT]" if norm_existing and norm_p == norm_existing else ""
                score_str = f"(Score: {score})" if show_scores else ""
                display_text = f"{p} {score_str} {is_current_marker}".strip().replace("  ", " ")
                path_choices.append(display_text)
                display_text_to_original_path[display_text] = p
                if norm_existing and norm_p == norm_existing:
                    current_selection_index = i
                    existing_path_found_in_list = True

            if existing_path and not existing_path_found_in_list:
                logging.warning(f"Existing path '{existing_path}' was not found in the suggested paths list.")

            manual_option_str = "--- Enter path manually ---"
            path_choices.append(manual_option_str)
            dialog_label_text = (
                "These potential paths were found for '{0}'.\n"
                "Select the correct one (ordered by probability) or choose manual entry:"
            ).format(profile_name)

            logging.debug(f"Showing QInputDialog.getItem with {len(path_choices)} choices, pre-selected index: {current_selection_index}")
            chosen_display_str, ok = QInputDialog.getItem(
                self.main_window, "Confirm Save Path", dialog_label_text,
                path_choices, current_selection_index, False
            )

            if ok and chosen_display_str:
                if chosen_display_str == manual_option_str:
                    confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
                else:
                    confirmed_path = display_text_to_original_path.get(chosen_display_str)
                    if confirmed_path is None:
                        logging.error(f"Error mapping selected choice '{chosen_display_str}' back to path.")
                        QMessageBox.critical(self.main_window, "Internal Error", "Error in path selection.")
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