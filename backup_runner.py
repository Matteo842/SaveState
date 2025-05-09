# backup_runner.py
# -*- coding: utf-8 -*-

import argparse
import sys
import os
import logging
import re
import platform
import winshell

# Import necessary modules for loading data and performing backups
# Assume these files are findable (in the same folder or in the python path)
# Specific imports for Qt notification
try:
    from PySide6.QtWidgets import QApplication # Needed even just for the notification
    from PySide6.QtGui import QScreen     # For positioning the notification
    from PySide6.QtCore import QTimer       # QTimer is used inside NotificationPopup
    QT_AVAILABLE = True
except ImportError as e_qt:
     QT_AVAILABLE = False
     logging.error(f"PySide6 not found, unable to show GUI notifications: {e_qt}")

# Import our modules
try:
    import core_logic
    import settings_manager
    import config # Needed to load the correct QSS
    from gui_utils import NotificationPopup 
except ImportError as e_mod:
    logging.error(f"Error importing modules ({e_mod}).")
    sys.exit(1)



# --- Notification Function ---
def show_notification(success, message):
    """
    Shows a custom popup notification using Qt.
    """
    logging.debug(">>> Entered show_notification <<<")
    # If PySide6 is not available, just log
    if not QT_AVAILABLE:
         log_level = logging.INFO if success else logging.ERROR
         logging.log(log_level, f"BACKUP RESULT (GUI Notification Unavailable): {message}")
         logging.debug("QT not available, exit from show_notification.")
         return

    app = None # Initialize app to None
    try:
        logging.debug("Checking/Creating QApplication...")
        app = QApplication.instance()
        needs_exec = False 
        created_app = False # Flag to know if we created the app
        if app is None:
            logging.debug("No existing QApplication found, creating a new one.")
            app_args = sys.argv if hasattr(sys, 'argv') and sys.argv else ['backup_runner']
            app = QApplication(app_args)
            created_app = True # We created the app
        else:
             logging.debug("Existing QApplication found.")

        # ... (code for loading theme and creating popup, remains the same) ...
        logging.debug("Loading theme settings...")
        try:
            settings, _ = settings_manager.load_settings()
            theme = settings.get('theme', 'dark')
            qss = config.DARK_THEME_QSS if theme == 'dark' else config.LIGHT_THEME_QSS
            logging.debug(f"Theme loaded: {theme}")
        except Exception as e_set:
             logging.error(f"Unable to load settings/theme for notification: {e_set}", exc_info=True)
             qss = "" # Fallback to empty style

        logging.debug("Creating NotificationPopup...")
        title = "Backup Complete" if success else "Backup Error" 
        clean_message = re.sub(r'\n+', '\n', message).strip()

        try:
            popup = NotificationPopup(title, clean_message, success)
            # Apply QSS *before* adjustSize and show for consistency
            logging.debug("Applying QSS...")
            try:
                 popup.setStyleSheet(qss)
            except Exception as e_qss:
                 logging.error(f"QSS application error at notification: {e_qss}", exc_info=True)

            popup.adjustSize() # Calculate size after QSS
            logging.debug(f"Popup size calculated: {popup.size()}")

            # Calculate position (remains the same)
            logging.debug("Calculating position...")
            # ... (code for calculating popup_x, popup_y) ...
            primary_screen = QApplication.primaryScreen()
            if primary_screen:
                 screen_geometry = primary_screen.availableGeometry()
                 margin = 15
                 popup_x = screen_geometry.width() - popup.width() - margin
                 popup_y = screen_geometry.height() - popup.height() - margin
                 popup.move(popup_x, popup_y)
                 logging.debug(f"Positioning notification at: ({popup_x}, {popup_y})")
            else:
                 logging.warning("Primary screen not found, unable to position notification.")

        except Exception as e_popup_create:
             logging.error(f"Error while creating NotificationPopup: {e_popup_create}", exc_info=True)
             # If we cannot create the popup, maybe it's better to exit?
             # Besides logging, we could try to close the app if we created it.
             if created_app and app:
                 app.quit()
             return # Exit if we cannot create the popup

        # Show the popup
        logging.debug("Showing popup...")
        popup.show()

        # If we created the QApplication just for this notification, set a timer to close it
        # shortly after the popup should have closed itself.
        if created_app and app:
            popup_duration_ms = 6000 # Duration of the popup (must match the one in NotificationPopup)
            quit_delay_ms = popup_duration_ms + 500 # Add half a second of margin
            logging.debug(f"Setting QTimer to call app.quit() after {quit_delay_ms} ms.")
            QTimer.singleShot(quit_delay_ms, app.quit)
            # Start the event loop, but it will exit automatically thanks to the timer
            logging.debug("Starting app.exec() for notification (with exit timer)...")
            app.exec()
            logging.debug("Exited from app.exec() after timer or manual popup closure.")
        else:
            logging.debug("Pre-existing QApplication, not starting exec/timer here. Just showing popup.")

    except Exception as e_main_show:
        logging.critical(f"Critical error in show_notification: {e_main_show}", exc_info=True)
        # Try to close the app if we created it and there was a serious error
        if created_app and app:
            app.quit()

    logging.debug("<<< Exiting show_notification >>>")


# --- Main Silent Execution Function ---
def run_silent_backup(profile_name):
    """
    Runs the backup logic for a given profile without GUI.
    Returns True on success, False otherwise.
    """
    logging.info(f"Starting silent backup for profile: '{profile_name}'")

    # 1. Load Settings
    try:
        settings, _ = settings_manager.load_settings()
        if not settings: # Handle rare case where load_settings returns None
              logging.error("Unable to load settings.")
              show_notification(False, "Error loading settings.")
              return False
    except Exception as e:
        logging.error(f"Critical error loading settings: {e}", exc_info=True)
        show_notification(False, f"Critical settings error: {e}")
        return False

    # 2. Load Profiles
    try:
        profiles = core_logic.load_profiles()
    except Exception as e:
        logging.error(f"Critical error loading profiles: {e}", exc_info=True)
        show_notification(False, f"Critical profile error: {e}")
        return False

    # 3. Check Profile Existence
    if profile_name not in profiles:
        logging.error(f"Profile '{profile_name}' not found in '{config.PROFILE_FILE}'. Backup cancelled.")
        show_notification(False, f"Profile not found: {profile_name}")
        return False

    # 4. Retrieve Necessary Data
    profile_data = profiles.get(profile_name) # Get the profile dictionary
    if not profile_data or not isinstance(profile_data, dict):
        # If we don't find a valid dictionary
        logging.error(f"Invalid profile data for '{profile_name}' in backup_runner. Backup cancelled.")
        show_notification(False, f"Error: Invalid profile data for {profile_name}.")
        return False

    # Handling 'paths' (list) and 'path' (string)
    paths_to_backup = None
    if 'paths' in profile_data and isinstance(profile_data['paths'], list):
        paths_to_backup = profile_data['paths']
        logging.debug(f"Found key 'paths' (list) for '{profile_name}': {paths_to_backup}")
    elif 'path' in profile_data and isinstance(profile_data['path'], str):
        paths_to_backup = [profile_data['path']] # Put the string in a list
        logging.debug(f"Found key 'path' (string) for '{profile_name}': {paths_to_backup}")

    # If neither 'paths' nor 'path' key is valid or found
    if paths_to_backup is None or not paths_to_backup: # Also check if the list is empty
        logging.error(f"No valid backup path ('paths' or 'path') found for '{profile_name}'. Backup cancelled.")
        # Show a more specific message to the user
        show_notification(False, f"Error: No valid backup path defined for {profile_name}.")
        return False
    # At this point, paths_to_backup contains a list (potentially with a single element) of paths
    # The actual validation of the paths' existence will happen inside perform_backup

    backup_base_dir = settings.get("backup_base_dir")
    max_bk = settings.get("max_backups")
    max_src_size = settings.get("max_source_size_mb")
    compression_mode = settings.get("compression_mode", "zip")
    check_space = settings.get("check_free_space_enabled", True)
    min_gb_required = config.MIN_FREE_SPACE_GB

    # Validate other settings (backup_base_dir is checked above)
    if not backup_base_dir or max_bk is None or max_src_size is None:
         logging.error("Necessary settings (backup base directory, max backups, max source size) are invalid in backup_runner.")
         show_notification(False, "Error: Invalid backup settings.")
         return False

    # 5. Calculate Total Source Size (using core_logic helper)
    logging.debug(f"Requesting actual total source size calculation from core_logic for profile '{profile_name}'...")
    total_source_size = core_logic._get_actual_total_source_size(paths_to_backup)

    if total_source_size == -1: # Check if core_logic signaled a critical error
        msg = f"Backup cancelled for '{profile_name}': Critical error calculating source size (see core_logic logs)."
        logging.error(msg)
        show_notification(False, "Error calculating source size. Backup cancelled.") # Generic to user
        return False
    # Logging of the size itself is handled by _get_actual_total_source_size in core_logic

    # Check Free Space
    if check_space:
        logging.info(f"Checking free disk space (Min: {min_gb_required} GB)...")
        min_bytes_required = min_gb_required * 1024 * 1024 * 1024
        try:
            os.makedirs(backup_base_dir, exist_ok=True)
            # Import shutil only if necessary
            import shutil
            disk_usage = shutil.disk_usage(backup_base_dir)
            free_bytes = disk_usage.free
            # Compare free space with needed space (basic check)
            # Add the minimum required GB as a safety margin
            required_bytes_with_margin = total_source_size + min_bytes_required
            if free_bytes < required_bytes_with_margin:
                 free_gb = free_bytes / (1024*1024*1024)
                 required_gb = required_bytes_with_margin / (1024*1024*1024)
                 msg = f"Insufficient disk space for backup '{profile_name}'. Available: {free_gb:.2f} GB, Estimated Required: {required_gb:.2f} GB (incl. {min_gb_required} GB margin)."
                 logging.error(msg)
                 show_notification(False, msg)
                 return False
            logging.info("Space control passed.")
        except Exception as e_space:
            msg = f"Disk space check error: {e_space}"
            logging.error(msg, exc_info=True)
            show_notification(False, msg)
            return False

    # 6. Perform Actual Backup
    logging.info(f"Starting core_logic.perform_backup for '{profile_name}'...")
    try:
        logging.debug(f"--->>> PRE-CALLING core_logic.perform_backup for '{profile_name}'")
        logging.debug(f"      Arguments: paths={paths_to_backup}, max_backups={max_bk}, backup_dir={backup_base_dir}, compression={compression_mode}")
        success, message = core_logic.perform_backup(
            profile_name,
            paths_to_backup, # Use the validated/corrected list of paths
            backup_base_dir,
            max_bk,
            max_src_size,
            compression_mode
        )
        logging.debug(f"<<<--- POST-CALL core_logic.perform_backup for '{profile_name}'")
        logging.debug(f"      Result: success={success}, error_message='{message}'")

        # 7. Show Notification
        show_notification(success, message)
        return success
    except Exception as e_backup:
         # Unexpected error INSIDE perform_backup not handled? Log it here.
         logging.error(f"Unexpected error during execution core_logic.perform_backup: {e_backup}", exc_info=True)
         show_notification(False, f"Unexpected backup error: {e_backup}")
         return False


# --- Main Runner Script Execution Block ---
if __name__ == "__main__":
    
    # --- Logging Configuration (Runner with File) ---
    # Set log file path in the same folder as the script
    try:
        log_file_dir = os.path.dirname(os.path.abspath(__file__)) # Current script folder
    except NameError:
        log_file_dir = os.getcwd() # Fallback if __file__ is not defined
    log_file = os.path.join(log_file_dir, "backup_runner.log")

    log_level = logging.INFO # Use DEBUG to capture everything now!
    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    log_datefmt = '%Y-%m-%d %H:%M:%S'
    log_formatter = logging.Formatter(log_format, log_datefmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove old handlers if present
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # Console Handler (Keep it, useful if running backup_runner.py manually from cmd)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    logging.info("--- Starting Backup Runner (Console Log Only) ---")
    logging.info("Logging configured for Console.") 
    logging.info(f"Received arguments: {' '.join(sys.argv)}")
    # --- END Logging ---

    parser = argparse.ArgumentParser(description="Runs the backup for a specific Game Saver profile.") 
    parser.add_argument("--backup", required=True, help="Name of the profile to back up.") 

    try:
        args = parser.parse_args()
        profile_to_backup = args.backup
        logging.info(f"Received argument --backup '{profile_to_backup}'")

        # Execute the main function
        backup_success = run_silent_backup(profile_to_backup)

        # Exit with appropriate code (0 = success, 1 = failure)
        sys.exit(0 if backup_success else 1)

    except SystemExit as e:
         # argparse exits with SystemExit (code 2) if arguments are wrong
         # Let it exit normally in that case, or log if you prefer
         if e.code != 0:
              logging.error(f"Error in arguments or required output. Code: {e.code}")
         sys.exit(e.code) # Propagate the exit code
    except Exception as e_main:
         # Generic error not caught before
         logging.critical(f"Fatal error in backup_runner: {e_main}", exc_info=True)
         # Try showing a notification even for fatal errors?
         show_notification(False, f"Fatal error: {e_main}") 
         sys.exit(1)