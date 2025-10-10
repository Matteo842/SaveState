# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem, QPushButton, QFileDialog, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt, QLocale, QCoreApplication
from PySide6.QtGui import QBrush, QColor

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
        self.selected_is_zip = False
        self._zip_list_item = None  # Reference to the synthetic list item representing the loaded ZIP
        self._profile_items = []     # References to normal profile backup items
        self._original_window_title = None
        self._original_instruction_text = None
        
        # Set title based on whether we have a profile
        if profile_name:
            self.setWindowTitle(f"Restore Backup for {profile_name}")
        else:
            self.setWindowTitle("Restore Backup from ZIP")
        self._original_window_title = self.windowTitle()
        
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
                self._profile_items.append(item)
            # --- End list population loop ---
        
        # If no profile name, keep the list enabled but empty and show an instruction label
        if not profile_name:
            self.backup_list_widget.setEnabled(True)
            no_backup_label = QLabel("Use 'Load from ZIP' button to select a backup file.")

        # --- Info label for loaded ZIP (kept hidden - superseded by list item presentation) ---
        self.zip_info_label = QLabel("")
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
            self.instruction_label = QLabel("Select the backup to restore from:")
        else:
            self.instruction_label = QLabel("Load a backup ZIP file to restore:")
        layout.addWidget(self.instruction_label)
        self._original_instruction_text = self.instruction_label.text()
        
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
        
        # Info label placeholder (intentionally hidden by default)
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
        self.selected_is_zip = True

        # Build a synthetic list item representing the loaded ZIP, inserted at the top
        profile_name = manifest.get("profile_name", "Unknown")
        created_at = manifest.get("created_at", "Unknown date")
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(created_at)
            system_locale = QLocale.system()
            date_str = system_locale.toString(dt, QLocale.FormatType.ShortFormat)
        except Exception:
            date_str = created_at

        zip_filename = os.path.basename(zip_path)
        zip_item_text = f"From ZIP — {profile_name} ({date_str})"

        if self._zip_list_item is None:
            item = QListWidgetItem(zip_item_text)
            # Mark as a ZIP item and store path
            item.setData(Qt.ItemDataRole.UserRole, zip_path)
            item.setData(Qt.ItemDataRole.UserRole + 1, True)  # flag: is_zip
            item.setToolTip(f"ZIP File: {zip_filename}\nProfile: {profile_name}\nDate: {date_str}\nPath: {zip_path}")
            # Slight visual cue (optional, subtle)
            item.setForeground(QBrush(QColor(220, 220, 220)))
            self.backup_list_widget.insertItem(0, item)
            self._zip_list_item = item
        else:
            self._zip_list_item.setText(zip_item_text)
            self._zip_list_item.setData(Qt.ItemDataRole.UserRole, zip_path)
            self._zip_list_item.setData(Qt.ItemDataRole.UserRole + 1, True)
            self._zip_list_item.setToolTip(f"ZIP File: {zip_filename}\nProfile: {profile_name}\nDate: {date_str}\nPath: {zip_path}")

        # Select the ZIP item and ensure OK is enabled
        self.backup_list_widget.setCurrentItem(self._zip_list_item)
        if self.ok_button:
            self.ok_button.setEnabled(True)

        # Hide profile items to avoid confusion; show only the loaded ZIP
        try:
            for it in self._profile_items:
                it.setHidden(True)
        except Exception:
            pass

        # Show the clear button (to remove the loaded ZIP entry)
        self.clear_zip_button.show()

        # Keep the info label hidden; list presentation is now the source of truth
        self.zip_info_label.hide()

        # Update window title and instruction label to reflect ZIP mode
        self.setWindowTitle(f"Restore Backup from ZIP — {profile_name}")
        if hasattr(self, 'instruction_label') and self.instruction_label:
            self.instruction_label.setText("Ready to restore from ZIP:")

        logging.info(f"Loaded ZIP backup: {os.path.basename(zip_path)} for profile '{profile_name}'")

    # The rest of the RestoreDialog class (on_selection_change, get_selected_path) remains unchanged...
    # ... (make sure the rest of the class is present in your file)

    def handle_clear_zip(self):
        """Clear the loaded ZIP and restore normal list selection."""
        # Clear ZIP data
        self.selected_backup_path = None
        self.loaded_manifest = None
        self.selected_is_zip = False
        
        # Remove the synthetic ZIP item if present
        if self._zip_list_item is not None:
            try:
                row = self.backup_list_widget.row(self._zip_list_item)
                it = self.backup_list_widget.takeItem(row)
                del it
            except Exception:
                pass
            self._zip_list_item = None
        
        # Hide clear button and info label
        self.zip_info_label.hide()
        self.clear_zip_button.hide()
        
        # Unhide profile items and restore title/instruction
        try:
            for it in self._profile_items:
                it.setHidden(False)
        except Exception:
            pass
        if self._original_window_title:
            self.setWindowTitle(self._original_window_title)
        if hasattr(self, 'instruction_label') and self.instruction_label and self._original_instruction_text:
            self.instruction_label.setText(self._original_instruction_text)

        # If there are items in the list (profile mode), select the first; else disable OK
        if self.backup_list_widget.count() > 0:
            self.backup_list_widget.setCurrentRow(0)
        else:
            if self.ok_button:
                self.ok_button.setEnabled(False)
        
        logging.info("Cleared loaded ZIP selection")
    
    def on_selection_change(self, current_item, previous_item):
        """Handle selection change in the backup list."""
        # Retrieve the data associated with the selected item
        item_data = None
        is_zip_item = False
        if current_item:
            try:
                item_data = current_item.data(Qt.ItemDataRole.UserRole)
                is_zip_item = bool(current_item.data(Qt.ItemDataRole.UserRole + 1))
            except Exception as e_data:
                logging.error(f"Error retrieving data from selected item: {e_data}")

        # Update selection state
        if current_item and item_data is not None:
            self.selected_backup_path = item_data
            self.selected_is_zip = is_zip_item
            # Only keep manifest if the selected item is the ZIP item
            if not is_zip_item:
                self.loaded_manifest = None
            if self.ok_button:
                self.ok_button.setEnabled(True)
        else:
            self.selected_backup_path = None
            self.selected_is_zip = False
            if self.ok_button:
                self.ok_button.setEnabled(False)
        
    def get_selected_path(self):
        """Return the selected backup path (either from list or loaded ZIP)."""
        return self.selected_backup_path
    
    def get_manifest(self):
        """Return the loaded manifest (if loaded from ZIP), or None."""
        return self.loaded_manifest if self.selected_is_zip else None
