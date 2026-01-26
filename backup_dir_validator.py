# backup_dir_validator.py
# -*- coding: utf-8 -*-
"""
Validates the backup directory configuration and handles missing folder scenarios.
Provides a dialog to allow users to locate or create a new backup folder.
"""

import os
import logging
import platform
import re


def is_at_drive_root(path: str) -> bool:
    """
    Check if the path is at the root of a filesystem drive.
    
    Examples:
        - Windows: "D:\\GameSaveBackups" -> True
        - Windows: "C:\\Users\\Name\\Backups" -> False
        - Linux: "/home/user/GameSaveBackups" -> False (typically)
        - Linux: "/GameSaveBackups" or "/mnt/disk/GameSaveBackups" -> True-ish
    
    Args:
        path: The path to check
        
    Returns:
        True if the path is at the first level of a drive/mount point
    """
    if not path or not isinstance(path, str):
        return False
    
    path = os.path.normpath(os.path.abspath(path))
    
    if platform.system() == "Windows":
        # On Windows, check if parent is a drive root like "D:\"
        parent = os.path.dirname(path)
        # Drive root has format like "D:\" or "D:"
        if re.match(r'^[A-Za-z]:\\?$', parent):
            return True
        return False
    else:
        # On Linux/macOS, check common mount patterns
        parts = path.strip('/').split('/')
        # Consider first-level paths on mount points
        # e.g., /home/user/GameSaveBackups -> 3 parts, not root
        # e.g., /mnt/disk/GameSaveBackups -> 3 parts, could be root of mounted disk
        # e.g., /GameSaveBackups -> 1 part, definitely root
        if len(parts) <= 1:
            return True
        # Check if it's under a common mount point
        if len(parts) == 3 and parts[0] in ('mnt', 'media', 'run'):
            return True
        return False


def get_folder_name(path: str) -> str:
    """
    Get the folder name from a path.
    
    Args:
        path: The full path
        
    Returns:
        The folder name (last component of the path)
    """
    if not path:
        return ""
    return os.path.basename(os.path.normpath(path))


def get_available_drives() -> list:
    """
    Get a list of available drives/mount points in the system.
    
    Returns:
        List of drive/mount point paths
    """
    drives = []
    
    if platform.system() == "Windows":
        # Check all possible drive letters
        import string
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                drives.append(drive_path)
    else:
        # On Linux/macOS, check common mount points
        # Start with root
        drives.append("/")
        
        # Check /mnt and /media for mounted drives
        for mount_base in ["/mnt", "/media"]:
            if os.path.isdir(mount_base):
                try:
                    for entry in os.listdir(mount_base):
                        mount_path = os.path.join(mount_base, entry)
                        if os.path.isdir(mount_path):
                            drives.append(mount_path)
                except PermissionError:
                    pass
        
        # Check /media/$USER for user-mounted drives
        try:
            user = os.environ.get("USER", "")
            if user:
                user_media = f"/media/{user}"
                if os.path.isdir(user_media):
                    for entry in os.listdir(user_media):
                        mount_path = os.path.join(user_media, entry)
                        if os.path.isdir(mount_path):
                            drives.append(mount_path)
        except Exception:
            pass
        
        # Check /run/media/$USER (Fedora/some distros)
        try:
            user = os.environ.get("USER", "")
            if user:
                run_media = f"/run/media/{user}"
                if os.path.isdir(run_media):
                    for entry in os.listdir(run_media):
                        mount_path = os.path.join(run_media, entry)
                        if os.path.isdir(mount_path):
                            drives.append(mount_path)
        except Exception:
            pass
    
    return drives


def search_folder_on_other_drives(folder_name: str, original_path: str) -> list:
    """
    Search for a folder with the given name on all available drives.
    
    Args:
        folder_name: The name of the folder to search for (e.g., "GameSaveBackups")
        original_path: The original path (to exclude its drive from results showing it's "different")
        
    Returns:
        List of paths where the folder was found
    """
    found_paths = []
    
    if not folder_name:
        return found_paths
    
    original_drive = None
    if platform.system() == "Windows" and original_path:
        # Get drive letter from original path
        match = re.match(r'^([A-Za-z]):', original_path)
        if match:
            original_drive = match.group(1).upper()
    
    drives = get_available_drives()
    
    for drive in drives:
        # Skip the original drive if this was a drive-root path
        if platform.system() == "Windows" and original_drive:
            drive_letter = drive[0].upper() if len(drive) > 0 else ""
            if drive_letter == original_drive:
                continue
        
        # Check if the folder exists on this drive
        potential_path = os.path.join(drive, folder_name)
        
        if os.path.isdir(potential_path):
            # Verify it's not the same path (in case of symlinks or mount overlaps)
            try:
                if os.path.normcase(os.path.realpath(potential_path)) != os.path.normcase(os.path.realpath(original_path)):
                    found_paths.append(potential_path)
                    logging.info(f"Found folder '{folder_name}' at alternate location: {potential_path}")
            except Exception:
                found_paths.append(potential_path)
    
    return found_paths


def validate_backup_directory(backup_dir: str, attempt_create: bool = True) -> dict:
    """
    Validate that the backup directory exists and is accessible.
    
    Args:
        backup_dir: The backup directory path from settings
        attempt_create: Whether to attempt creating the directory if it doesn't exist
        
    Returns:
        Dictionary with validation result:
        {
            'valid': bool,           # True if the directory exists and is accessible
            'path': str,             # The original path
            'error': str | None,     # Error message if not valid
            'is_at_root': bool,      # True if the path is at a drive/mount root
            'folder_name': str,      # The folder name from the path
            'alternate_locations': list,  # Paths where the folder was found on other drives
            'created': bool,         # True if the directory was created
        }
    """
    result = {
        'valid': False,
        'path': backup_dir,
        'error': None,
        'is_at_root': False,
        'folder_name': '',
        'alternate_locations': [],
        'created': False,
    }
    
    if not backup_dir or not isinstance(backup_dir, str):
        result['error'] = "Backup directory path is not configured"
        return result
    
    backup_dir = os.path.normpath(backup_dir)
    result['path'] = backup_dir
    result['folder_name'] = get_folder_name(backup_dir)
    result['is_at_root'] = is_at_drive_root(backup_dir)
    
    # Check if directory exists
    if os.path.isdir(backup_dir):
        result['valid'] = True
        return result
    
    # Directory doesn't exist - check if we can create it
    if attempt_create:
        try:
            os.makedirs(backup_dir, exist_ok=True)
            result['valid'] = True
            result['created'] = True
            logging.info(f"Created backup directory: {backup_dir}")
            return result
        except OSError as e:
            logging.warning(f"Could not create backup directory {backup_dir}: {e}")
            result['error'] = f"Cannot create directory: {e}"
    else:
        result['error'] = "Directory does not exist"
    
    # If path was at drive root and creation failed, search on other drives
    if result['is_at_root'] and result['folder_name']:
        logging.info(f"Backup folder '{result['folder_name']}' not found at root location, searching other drives...")
        alternate_locations = search_folder_on_other_drives(result['folder_name'], backup_dir)
        result['alternate_locations'] = alternate_locations
        if alternate_locations:
            logging.info(f"Found {len(alternate_locations)} alternate location(s) for backup folder")
    
    return result


def show_backup_directory_dialog(parent, validation_result: dict) -> str | None:
    """
    Show a dialog to the user when the backup directory is not found.
    
    Args:
        parent: Parent widget for the dialog
        validation_result: The result from validate_backup_directory()
        
    Returns:
        The new backup directory path chosen by the user, or None if cancelled
    """
    from PySide6.QtWidgets import QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel, QPushButton, QListWidget, QDialogButtonBox, QHBoxLayout
    from PySide6.QtCore import Qt
    
    original_path = validation_result.get('path', '')
    folder_name = validation_result.get('folder_name', 'GameSaveBackups')
    alternates = validation_result.get('alternate_locations', [])
    error = validation_result.get('error', 'Directory not found')
    
    # Build the message
    msg = f"The backup folder could not be found at:\n{original_path}\n\n"
    
    if alternates:
        msg += f"However, a folder named '{folder_name}' was found on other drives.\n"
        msg += "Would you like to use one of these locations instead?\n\n"
        
        # Create a custom dialog with options
        dialog = QDialog(parent)
        dialog.setWindowTitle("Backup Folder Not Found")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(300)
        
        layout = QVBoxLayout()
        
        label = QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # List of alternate locations
        list_widget = QListWidget()
        for alt_path in alternates:
            list_widget.addItem(alt_path)
        if alternates:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        use_selected_button = QPushButton("Use Selected Location")
        use_selected_button.setDefault(True)
        
        browse_button = QPushButton("Browse for Another Folder...")
        create_original_button = QPushButton("Create at Original Location")
        cancel_button = QPushButton("Cancel (Exit App)")
        
        buttons_layout.addWidget(use_selected_button)
        buttons_layout.addWidget(browse_button)
        buttons_layout.addWidget(create_original_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        dialog.setLayout(layout)
        
        selected_path = [None]  # Use list to allow modification in nested function
        
        def on_use_selected():
            current = list_widget.currentItem()
            if current:
                selected_path[0] = current.text()
                dialog.accept()
        
        def on_browse():
            new_path = QFileDialog.getExistingDirectory(
                dialog,
                "Select Backup Folder",
                os.path.dirname(original_path) if os.path.exists(os.path.dirname(original_path)) else ""
            )
            if new_path:
                selected_path[0] = new_path
                dialog.accept()
        
        def on_create_original():
            try:
                os.makedirs(original_path, exist_ok=True)
                selected_path[0] = original_path
                dialog.accept()
            except OSError as e:
                QMessageBox.critical(dialog, "Error", f"Cannot create folder:\n{e}")
        
        def on_cancel():
            dialog.reject()
        
        use_selected_button.clicked.connect(on_use_selected)
        browse_button.clicked.connect(on_browse)
        create_original_button.clicked.connect(on_create_original)
        cancel_button.clicked.connect(on_cancel)
        
        if dialog.exec() == QDialog.Accepted:
            return selected_path[0]
        return None
        
    else:
        # No alternates found, show a custom dialog with clear button labels
        msg += "You can:\n• Create a new folder at the original location\n• Browse for an existing folder\n• Cancel and exit the application"
        
        dialog = QDialog(parent)
        dialog.setWindowTitle("Backup Folder Not Found")
        dialog.setMinimumWidth(450)
        
        layout = QVBoxLayout()
        
        label = QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Buttons with clear labels
        buttons_layout = QHBoxLayout()
        
        create_button = QPushButton("Create Folder")
        create_button.setDefault(True)
        
        browse_button = QPushButton("Browse...")
        cancel_button = QPushButton("Cancel")
        
        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(browse_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        dialog.setLayout(layout)
        
        selected_path = [None]
        
        def on_create():
            try:
                os.makedirs(original_path, exist_ok=True)
                selected_path[0] = original_path
                dialog.accept()
            except OSError as e:
                QMessageBox.critical(dialog, "Error", f"Cannot create folder:\n{e}")
        
        def on_browse():
            # Start from a sensible directory
            start_dir = os.path.dirname(original_path)
            if not os.path.exists(start_dir):
                start_dir = os.path.expanduser("~")
            
            new_path = QFileDialog.getExistingDirectory(
                dialog,
                "Select Backup Folder",
                start_dir
            )
            if new_path:
                selected_path[0] = new_path
                dialog.accept()
        
        def on_cancel():
            dialog.reject()
        
        create_button.clicked.connect(on_create)
        browse_button.clicked.connect(on_browse)
        cancel_button.clicked.connect(on_cancel)
        
        if dialog.exec() == QDialog.Accepted:
            return selected_path[0]
        return None


def check_and_fix_backup_directory(settings: dict, parent=None) -> tuple:
    """
    Main entry point: validate backup directory and show dialog if needed.
    
    Should be called after loading settings but before initializing the main UI.
    
    Args:
        settings: The loaded settings dictionary
        parent: Parent widget for any dialogs
        
    Returns:
        Tuple of (success: bool, updated_settings: dict)
        - success: True if backup directory is valid (or was fixed)
        - updated_settings: The settings dict, potentially with updated backup_base_dir
    """
    backup_dir = settings.get('backup_base_dir', '')
    
    if not backup_dir:
        # No backup directory configured - this is handled by first-launch dialog
        return True, settings
    
    # Validate the backup directory
    validation = validate_backup_directory(backup_dir, attempt_create=True)
    
    if validation['valid']:
        return True, settings
    
    # Directory is not valid - need user intervention
    logging.warning(f"Backup directory not found: {backup_dir}")
    
    if parent is None:
        # No parent for dialog - can't show UI
        logging.error("Cannot show backup directory dialog without a parent widget")
        return False, settings
    
    # Show dialog to user
    new_path = show_backup_directory_dialog(parent, validation)
    
    if new_path:
        settings['backup_base_dir'] = new_path
        logging.info(f"Backup directory updated to: {new_path}")
        return True, settings
    
    return False, settings
