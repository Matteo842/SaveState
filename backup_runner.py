# backup_runner.py
# -*- coding: utf-8 -*-

import argparse
import sys
import os
import logging
import re
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

# Try to import notify_py for native Linux notifications
try:
    import notify_py  # type: ignore[import-untyped]
    NATIVE_NOTIFY_AVAILABLE = True
    logging.info("notify_py imported successfully. Native Linux notifications are available.")
except ImportError:
    NATIVE_NOTIFY_AVAILABLE = False
    logging.info("notify_py not found. Native Linux notifications will not be used. Will fallback to Qt notifications on Linux if Qt is available.")

# Import our modules
try:
    import core_logic
    import settings_manager
    import config # Needed to load the correct QSS
    from gui_utils import NotificationPopup 
    from utils import resource_path
except ImportError as e_mod:
    logging.error(f"Error importing modules ({e_mod}).")
    sys.exit(1)



# --- Notification Function ---
def show_notification(success, message):
    """
    Shows a custom popup notification. Uses native Linux notifications if available,
    otherwise falls back to Qt.
    """
    logging.debug(">>> Entered show_notification <<<")
    title = "Backup Complete" if success else "Backup Error"
    clean_message = re.sub(r'\n+', '\n', message).strip()

    # Attempt Linux native notification first
    if sys.platform.startswith('linux') and NATIVE_NOTIFY_AVAILABLE:
        try:
            notification = notify_py.Notify()
            notification.title = title
            notification.message = clean_message
            if success:
                icon_path_native = resource_path(os.path.join("icons", "SaveStateIconBK.ico"))
                if os.path.exists(icon_path_native):
                    notification.icon = icon_path_native
                else:
                    logging.warning(f"Success icon not found for native notification: {icon_path_native}")
            # For errors, notify-py will use a default system error icon if not specified
            notification.send(block=False) # Send non-blocking
            log_level = logging.INFO if success else logging.ERROR
            logging.log(log_level, f"BACKUP RESULT (Native Linux Notification): {title} - {clean_message}")
            logging.debug("<<< Exiting show_notification after native Linux notification >>>")
            return # Notification sent, exit
        except Exception as e_native:
            logging.warning(f"Failed to send native Linux notification: {e_native}. Falling back to Qt notification if available.")
            # Fall through to Qt notification

    # Fallback to Qt notification (existing logic)
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

        icon_path_qt = None
        if success:
            icon_path_qt_success = resource_path(os.path.join("icons", "SaveStateIconBK.ico"))
            if os.path.exists(icon_path_qt_success):
                icon_path_qt = icon_path_qt_success
            else:
                logging.warning(f"Success icon not found for Qt notification: {icon_path_qt_success}")
        # For errors with Qt, NotificationPopup currently doesn't have specific error icon logic
        # We'll pass None, it might default to no icon or its own default. Future enhancement: add error icon to NotificationPopup.

        try:
            popup = NotificationPopup(title, clean_message, success, icon_path=icon_path_qt)
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


# --- Group Backup Helper Function ---
def _run_group_backup(group_name, profiles, settings):
    """
    Backup all profiles in a group sequentially.
    
    Uses group settings override if enabled, otherwise falls back to global settings.
    Priority: Group override > Profile override > Global settings
    
    Args:
        group_name: Name of the group profile
        profiles: Dictionary of all profiles
        settings: Loaded settings dictionary
        
    Returns:
        True if all backups succeeded, False if any failed
    """
    member_profiles = core_logic.get_group_member_profiles(group_name, profiles)
    
    if not member_profiles:
        logging.error(f"Group '{group_name}' has no member profiles.")
        show_notification(False, f"Error: Group '{group_name}' is empty.")
        return False
    
    # Get group settings for logging purposes
    group_settings = core_logic.get_group_settings(group_name, profiles)
    if group_settings.get('enabled'):
        logging.info(f"Group '{group_name}' has settings override enabled: {group_settings}")
    
    logging.info(f"Starting group backup for '{group_name}' with {len(member_profiles)} profiles")
    
    all_success = True
    success_count = 0
    failed_profiles = []
    backup_base_dir = settings.get("backup_base_dir")
    
    for idx, member_name in enumerate(member_profiles, 1):
        logging.info(f"[Group Backup {idx}/{len(member_profiles)}] Backing up: '{member_name}'")
        
        member_data = profiles.get(member_name)
        if not member_data or not isinstance(member_data, dict):
            logging.error(f"Invalid profile data for group member '{member_name}'")
            failed_profiles.append(member_name)
            all_success = False
            continue
        
        # Get paths for this member
        paths_to_backup = None
        if 'paths' in member_data and isinstance(member_data['paths'], list):
            paths_to_backup = member_data['paths']
        elif 'path' in member_data and isinstance(member_data['path'], str):
            paths_to_backup = [member_data['path']]
        
        if not paths_to_backup:
            logging.error(f"No valid path for group member '{member_name}'")
            failed_profiles.append(member_name)
            all_success = False
            continue
        
        # Get effective settings using helper (respects group > profile > global priority)
        try:
            effective = core_logic.get_effective_profile_settings(
                member_name, member_data, profiles, settings
            )
            max_bk = effective.get('max_backups')
            max_src_size = effective.get('max_source_size_mb')
            compression_mode = effective.get('compression_mode', 'standard')
        except Exception as e:
            logging.warning(f"Error getting effective settings for '{member_name}': {e}")
            max_bk = settings.get("max_backups")
            max_src_size = settings.get("max_source_size_mb")
            compression_mode = settings.get("compression_mode", "standard")
        
        # Perform backup for this member
        try:
            success, message = core_logic.perform_backup(
                member_name,
                paths_to_backup,
                backup_base_dir,
                max_bk,
                max_src_size,
                compression_mode,
                member_data
            )
            
            if success:
                success_count += 1
                logging.info(f"[Group Backup] '{member_name}' backup succeeded")
            else:
                failed_profiles.append(member_name)
                all_success = False
                logging.error(f"[Group Backup] '{member_name}' backup failed: {message}")
                
        except Exception as e:
            failed_profiles.append(member_name)
            all_success = False
            logging.error(f"[Group Backup] Error backing up '{member_name}': {e}", exc_info=True)
    
    # Show final notification
    if all_success:
        message = f"Group backup completed successfully!\n\n{group_name}: {success_count}/{len(member_profiles)} profiles backed up."
        show_notification(True, message)
    else:
        message = f"Group backup completed with errors.\n\n{group_name}: {success_count}/{len(member_profiles)} succeeded.\nFailed: {', '.join(failed_profiles)}"
        show_notification(False, message)
    
    return all_success


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

    # 3. Check Profile Existence (with fallback to sanitized name)
    actual_profile_name = profile_name
    if profile_name not in profiles:
        # Try sanitized version (removes special chars like colons)
        try:
            import shortcut_utils
            sanitized_name = shortcut_utils.sanitize_profile_name(profile_name)
            if sanitized_name and sanitized_name in profiles:
                logging.info(f"Profile '{profile_name}' not found, but found sanitized version: '{sanitized_name}'")
                actual_profile_name = sanitized_name
            else:
                logging.error(f"Profile '{profile_name}' not found in '{core_logic.PROFILES_FILE_PATH}'. Backup cancelled.")
                show_notification(False, f"Profile not found: {profile_name}")
                return False
        except Exception as e_sanitize:
            logging.error(f"Profile '{profile_name}' not found in '{core_logic.PROFILES_FILE_PATH}'. Backup cancelled.")
            show_notification(False, f"Profile not found: {profile_name}")
            return False
    
    profile_name = actual_profile_name  # Use the found name for the rest

    # 4. Retrieve Necessary Data
    profile_data = profiles.get(profile_name) # Get the profile dictionary
    if not profile_data or not isinstance(profile_data, dict):
        # If we don't find a valid dictionary
        logging.error(f"Invalid profile data for '{profile_name}' in backup_runner. Backup cancelled.")
        show_notification(False, f"Error: Invalid profile data for {profile_name}.")
        return False
    
    # 4b. Check if this is a group profile - backup all members sequentially
    if core_logic.is_group_profile(profile_data):
        return _run_group_backup(profile_name, profiles, settings)

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

    # TODO: SPECIAL HANDLING FOR XEMU PROFILES - TEMPORARILY DISABLED
    # Xemu specialized backup is commented out until HDD extraction/injection is implemented
    # When ready, uncomment this block
    
    # if 'emulator' in profile_data and profile_data.get('emulator') == 'xemu':
    #     logging.info(f"Detected xemu profile: {profile_name} (type: {profile_data.get('type', 'unknown')})")
    #     try:
    #         from emulator_utils.xemu_manager import backup_xbox_save
    #         
    #         # Create backup directory for this profile
    #         sanitized_folder_name = core_logic.sanitize_foldername(profile_name)
    #         profile_backup_dir = os.path.join(settings.get("backup_base_dir", ""), sanitized_folder_name)
    #         
    #         # Use xemu's specialized backup function (no size limits for Xbox saves)
    #         success = backup_xbox_save(profile_data['id'], profile_backup_dir)
    #         
    #         if success:
    #             show_notification(True, f"Xbox save backup completed successfully:\n{profile_name}")
    #             return True
    #         else:
    #             show_notification(False, f"Xbox save backup failed for:\n{profile_name}")
    #             return False
    #             
    #     except Exception as e:
    #         logging.error(f"Error during xemu backup for '{profile_name}': {e}", exc_info=True)
    #         show_notification(False, f"Xbox save backup error: {e}")
    #         return False

    backup_base_dir = settings.get("backup_base_dir")
    check_space = settings.get("check_free_space_enabled", True)
    min_gb_required = config.MIN_FREE_SPACE_GB
    
    # Get effective settings using helper (respects group > profile > global priority)
    # This is important for profiles that are members of a group
    try:
        effective = core_logic.get_effective_profile_settings(
            profile_name, profile_data, profiles, settings
        )
        max_bk = effective.get('max_backups')
        max_src_size = effective.get('max_source_size_mb')
        compression_mode = effective.get('compression_mode', 'standard')
        
        # Log if using group settings
        if profile_data.get('member_of_group'):
            group_name = profile_data.get('member_of_group')
            group_settings = core_logic.get_group_settings(group_name, profiles)
            if group_settings.get('enabled'):
                logging.info(f"Profile '{profile_name}' is using group '{group_name}' settings override")
    except Exception as e:
        logging.warning(f"Error getting effective settings for '{profile_name}': {e}")
        max_bk = settings.get("max_backups")
        max_src_size = settings.get("max_source_size_mb")
        compression_mode = settings.get("compression_mode", "standard")

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
            compression_mode,
            profile_data  # Pass profile data for emulator-specific handling (e.g., Ymir)
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