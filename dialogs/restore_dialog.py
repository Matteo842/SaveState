# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem
)
from PySide6.QtCore import Qt, QLocale, QCoreApplication

import core_logic
import config
import logging


class RestoreDialog(QDialog):
    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        # Translated and formatted title
        self.setWindowTitle(f"Restore Backup for {profile_name}")
        self.setMinimumWidth(450)
        self.backup_list_widget = QListWidget()
        self.selected_backup_path = None
        no_backup_label = None

        # --- Retrieve the CURRENT base path from the parent's settings ---
        current_backup_base_dir = "" # Default empty
        if parent and hasattr(parent, 'current_settings'): # Check if parent and settings exist
            current_backup_base_dir = parent.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            # Fallback if we can't get the settings (unlikely)
            logging.warning("RestoreDialog: Unable to access current_settings from parent. Using default from config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR

        # --- Call core_logic (now returns list with datetime object) ---
        # The function list_available_backups must already have been modified
        # to return (name, path, datetime_obj)
        backups = core_logic.list_available_backups(profile_name, current_backup_base_dir)

        if not backups:
            # Handle no backups found
            no_backup_label = QLabel("No backups found for this profile.")
            self.backup_list_widget.setEnabled(False)
        else:
            # --- Logic for localized date formatting ---
            current_lang_code = "en" # Default fallback
            if parent and hasattr(parent, 'current_settings'):
                current_lang_code = parent.current_settings.get("language", "en")
            locale = QLocale(QLocale.Language.English if current_lang_code == "en" else QLocale.Language.Italian)
            # --- End localization logic ---

            # --- Loop to populate the list WITH DATE FORMATTING ---
            # Now we iterate over (name, path, dt_obj)
            for name, path, dt_obj in backups:
                # Format the date using QLocale
                date_str_formatted = "???" # Fallback
                if dt_obj:
                    try:
                        date_str_formatted = locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
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

        # --- Dialog Buttons (as before) ---
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton("Restore Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button.setEnabled(False) # Disable OK at the start

        # --- Layout (as before) ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the backup to restore from:"))
        if no_backup_label: layout.addWidget(no_backup_label)
        layout.addWidget(self.backup_list_widget)
        layout.addWidget(buttons)

        # Connect selection change signal (as before)
        self.backup_list_widget.currentItemChanged.connect(self.on_selection_change)
    # --- End of __init__ method ---

    # The rest of the RestoreDialog class (on_selection_change, get_selected_path) remains unchanged...
    # ... (make sure the rest of the class is present in your file)

    def on_selection_change(self, current_item, previous_item):
        # Find the OK button (AcceptRole)
        button_box = self.findChild(QDialogButtonBox)
        if not button_box:
            # Log only if we can't find the button box
            logging.error("RestoreDialog: QDialogButtonBox not found in on_selection_change!")
            return
        all_buttons = button_box.buttons()
        ok_button = None # Initialize to None
        # Search among the buttons for the one with AcceptRole
        for button in all_buttons:
            if button_box.buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole:
                ok_button = button # Found!
                break # Exit the loop as soon as you find it

        if ok_button:
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
                ok_button.setEnabled(True)
            else:
                # Otherwise, disable the button and reset the selected path
                self.selected_backup_path = None
                ok_button.setEnabled(False)
        else:
            # Log only if we can't find the specific OK/Accept button
            logging.error("OK button (AcceptRole) not found in RestoreDialog!")
        
    def get_selected_path(self):
        return self.selected_backup_path
