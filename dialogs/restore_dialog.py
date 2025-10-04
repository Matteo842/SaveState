# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem, QPushButton, QFileDialog, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt, QLocale, QCoreApplication

import core_logic
import config
import logging
import os


class RestoreDialog(QDialog):
    def __init__(self, profile_name=None, parent=None):
        super().__init__(parent)
        
        # Store profile name (can be None for standalone ZIP restore)
        self.profile_name = profile_name
        self.selected_backup_path = None
        self.loaded_manifest = None  # Store manifest from loaded ZIP
        
        # Set title based on whether we have a profile
        if profile_name:
            self.setWindowTitle(f"Restore Backup for {profile_name}")
        else:
            self.setWindowTitle("Restore Backup from ZIP")
        
        self.setMinimumWidth(450)
        self.backup_list_widget = QListWidget()
        no_backup_label = None

        # --- Retrieve the CURRENT base path from the parent's settings ---
        current_backup_base_dir = "" # Default empty
        if parent and hasattr(parent, 'current_settings'): # Check if parent and settings exist
            current_backup_base_dir = parent.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            # Fallback if we can't get the settings (unlikely)
            logging.warning("RestoreDialog: Unable to access current_settings from parent. Using default from config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR

        # --- Call core_logic only if we have a profile name ---
        backups = []
        if profile_name:
            # The function list_available_backups must already have been modified
            # to return (name, path, datetime_obj)
            backups = core_logic.list_available_backups(profile_name, current_backup_base_dir)

        if not backups and profile_name:
            # Handle no backups found (only show if we have a profile)
            no_backup_label = QLabel("No backups found for this profile.")
            self.backup_list_widget.setEnabled(False)
        elif profile_name:
            # --- Use system locale for date formatting ---
            system_locale = QLocale.system()
            logging.debug(f"Using system locale for date formatting in RestoreDialog: {system_locale.name()}")
            # --- End localization logic ---

            # --- Loop to populate the list WITH DATE FORMATTING ---
            # Now we iterate over (name, path, dt_obj)
            for name, path, dt_obj in backups:
                # Format the date using QLocale
                date_str_formatted = "???" # Fallback
                if dt_obj:
                    try:
                        date_str_formatted = system_locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
                    except Exception as e_fmt:
                        logging.error(f"Error formatting date ({dt_obj}) for backup {name}: {e_fmt}")

                # Clean the file name (use the function from core_logic)
                display_name = core_logic.get_display_name_from_backup_filename(name)
                item_text = f"{display_name} ({date_str_formatted})" # Use clean name and formatted date

                # Create and add the item to the list
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path) # Save the full path
                self.backup_list_widget.addItem(item)
            # --- End list population loop ---
        
        # If no profile name, disable the list and show info label
        if not profile_name:
            self.backup_list_widget.setEnabled(False)
            no_backup_label = QLabel("Use 'Load from ZIP' button to select a backup file.")

        # --- Info label for loaded ZIP ---
        self.zip_info_label = QLabel("")
        self.zip_info_label.setWordWrap(True)
        self.zip_info_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; font-size: 11pt; padding: 8px; }")
        self.zip_info_label.hide()

        # --- Load from ZIP Button ---
        self.load_zip_button = QPushButton("Load from ZIP...")
        self.load_zip_button.clicked.connect(self.handle_load_from_zip)
        
        # --- Clear ZIP Button (initially hidden) ---
        self.clear_zip_button = QPushButton("Clear Selection")
        self.clear_zip_button.clicked.connect(self.handle_clear_zip)
        self.clear_zip_button.hide()
        
        # --- Dialog Buttons ---
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton("Restore Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button.setEnabled(False) # Disable OK at the start

        # --- Layout ---
        layout = QVBoxLayout(self)
        
        # Top section with instruction label
        if profile_name:
            layout.addWidget(QLabel("Select the backup to restore from:"))
        else:
            layout.addWidget(QLabel("Load a backup ZIP file to restore:"))
        
        if no_backup_label: 
            layout.addWidget(no_backup_label)
        
        # Backup list
        layout.addWidget(self.backup_list_widget)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.load_zip_button)
        button_layout.addWidget(self.clear_zip_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Info label for loaded ZIP (with more context)
        layout.addWidget(self.zip_info_label)
        
        # Dialog buttons
        layout.addWidget(buttons)

        # Connect selection change signal
        self.backup_list_widget.currentItemChanged.connect(self.on_selection_change)
        
        # Store reference to buttons
        self.button_box = buttons
        self.ok_button = ok_button
    # --- End of __init__ method ---
    
    def handle_load_from_zip(self):
        """Handle the 'Load from ZIP' button click."""
        # Get the backup directory to start from
        start_dir = ""
        if self.parent() and hasattr(self.parent(), 'current_settings'):
            start_dir = self.parent().current_settings.get("backup_base_dir", "")
        
        if not start_dir:
            start_dir = config.BACKUP_BASE_DIR if hasattr(config, 'BACKUP_BASE_DIR') else ""
        
        # Open file dialog to select a ZIP file, starting from backup directory
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backup ZIP File",
            start_dir,  # Start from backup directory
            "ZIP Files (*.zip);;All Files (*)"
        )
        
        if not zip_path:
            return  # User cancelled
        
        # Validate the ZIP file
        is_valid, manifest, error_msg = core_logic.validate_backup_zip(zip_path)
        
        if not is_valid:
            QMessageBox.warning(
                self,
                "Invalid Backup ZIP",
                f"The selected ZIP file is not a valid SaveState backup:\n\n{error_msg}"
            )
            return
        
        # Store the selected ZIP path and manifest
        self.selected_backup_path = zip_path
        self.loaded_manifest = manifest
        
        # Extract info from manifest
        profile_name = manifest.get("profile_name", "Unknown")
        created_at = manifest.get("created_at", "Unknown date")
        
        # Format the date if possible
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(created_at)
            system_locale = QLocale.system()
            date_str = system_locale.toString(dt, QLocale.FormatType.ShortFormat)
        except:
            date_str = created_at
        
        # Update info label with clearer message
        self.zip_info_label.setText(
            f"📦 Ready to restore from ZIP:\n"
            f"Profile: {profile_name}\n"
            f"Backup Date: {date_str}"
        )
        self.zip_info_label.show()
        
        # Disable and grey out the backup list to make it clear it's not being used
        self.backup_list_widget.setEnabled(False)
        self.backup_list_widget.clearSelection()
        self.backup_list_widget.setStyleSheet("QListWidget:disabled { background-color: #2a2a2a; }")
        
        # Show the clear button
        self.clear_zip_button.show()
        
        # Enable the restore button
        if self.ok_button:
            self.ok_button.setEnabled(True)
        
        logging.info(f"Loaded ZIP backup: {os.path.basename(zip_path)} for profile '{profile_name}'")

    # The rest of the RestoreDialog class (on_selection_change, get_selected_path) remains unchanged...
    # ... (make sure the rest of the class is present in your file)

    def handle_clear_zip(self):
        """Clear the loaded ZIP and restore normal list selection."""
        # Clear ZIP data
        self.selected_backup_path = None
        self.loaded_manifest = None
        
        # Hide ZIP info and clear button
        self.zip_info_label.hide()
        self.clear_zip_button.hide()
        
        # Re-enable the backup list
        self.backup_list_widget.setEnabled(True)
        self.backup_list_widget.setStyleSheet("")  # Reset style
        
        # Disable restore button until something is selected
        if self.ok_button:
            self.ok_button.setEnabled(False)
        
        logging.info("Cleared loaded ZIP selection")
    
    def on_selection_change(self, current_item, previous_item):
        """Handle selection change in the backup list."""
        # Don't process selection changes if a ZIP is loaded
        if self.loaded_manifest is not None:
            return
        
        # Retrieve the data associated with the selected item
        item_data = None
        if current_item:
            try:
                # Attempt to retrieve the path saved as UserRole
                item_data = current_item.data(Qt.ItemDataRole.UserRole)
            except Exception as e_data:
                # Log only if there is an error retrieving the data
                logging.error(f"Error retrieving data from selected item: {e_data}")

        # Enable the button ONLY if an item is selected AND has valid data (not None)
        if current_item and item_data is not None:
            self.selected_backup_path = item_data # Save the valid path
            if self.ok_button:
                self.ok_button.setEnabled(True)
        else:
            self.selected_backup_path = None
            if self.ok_button:
                self.ok_button.setEnabled(False)
        
    def get_selected_path(self):
        """Return the selected backup path (either from list or loaded ZIP)."""
        return self.selected_backup_path
    
    def get_manifest(self):
        """Return the loaded manifest (if loaded from ZIP), or None."""
        return self.loaded_manifest
