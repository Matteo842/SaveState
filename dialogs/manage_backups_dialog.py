# -*- coding: utf-8 -*-
import os
from PySide6.QtWidgets import (
    QDialog, QListWidget, QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
    QMessageBox, QApplication, QStyle, QListWidgetItem
)
from PySide6.QtCore import Slot, Qt, QLocale, QCoreApplication

# Import necessary logic
import core_logic
import config
import logging 


class ManageBackupsDialog(QDialog):

     def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.setWindowTitle(f"Manage Backups for {self.profile_name}")
        self.setMinimumWidth(500)
        # Get the style for standard icons
        style = QApplication.instance().style()
        
        # Widget
        self.backup_list_widget = QListWidget()
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setObjectName("DangerButton")
        
        # Set standard icon for Delete
        delete_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        self.delete_button.setIcon(delete_icon)
        
        self.close_button = QPushButton("Close")
        
        # Set standard icon for Close
        close_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        self.close_button.setIcon(close_icon)
        
        self.delete_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Existing backups for '{self.profile_name}':"))
        layout.addWidget(self.backup_list_widget)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        self.backup_list_widget.currentItemChanged.connect(
            lambda item: self.delete_button.setEnabled(item is not None and item.data(Qt.ItemDataRole.UserRole) is not None)
        )
        self.delete_button.clicked.connect(self.delete_selected_backup)
        self.close_button.clicked.connect(self.reject)
        self.populate_backup_list()
     
     # --- Method populate_backup_list ---
     @Slot()
     def populate_backup_list(self):
        self.backup_list_widget.clear()
        self.delete_button.setEnabled(False)

        # --- RECOVER SETTINGS HERE (BEFORE USING VARIABLES) ---
        current_backup_base_dir = "" # Default empty
        # Use system locale for date formatting
        system_locale = QLocale.system()
        logging.debug(f"ManageBackupsDialog: Using system locale for date formatting: {system_locale.name()}")

        parent_window = self.parent() # Get the parent once
        if parent_window and hasattr(parent_window, 'current_settings'):
            # Read the backup base path from settings
            current_backup_base_dir = parent_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            # Fallback if we don't find settings in the parent
            logging.warning("ManageBackupsDialog: Unable to access current_settings from parent. Using defaults from config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR
        # --- END RECOVER SETTINGS ---

        backups = core_logic.list_available_backups(self.profile_name, current_backup_base_dir)

        if not backups:
            # Handle no backups found
            item = QListWidgetItem("No backups found.") # Translate text
            item.setData(Qt.ItemDataRole.UserRole, None) # No associated path
            self.backup_list_widget.addItem(item)
            self.backup_list_widget.setEnabled(False) # Disable list
        else:
            # There are backups, populate the list
            self.backup_list_widget.setEnabled(True) # Enable list

            # Loop to add each backup with formatted date
            for name, path, dt_obj in backups: # Iterate on the tuple (name, path, datetime_object)
                # Format the date using the 'locale' defined above
                date_str_formatted = "???" # Fallback
                if dt_obj:
                    try:
                        date_str_formatted = system_locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
                    except Exception as e_fmt:
                        logging.error(f"Error formatting date ({dt_obj}) for backup {name}: {e_fmt}")

                # Clean the backup file name (remove timestamp)
                display_name = core_logic.get_display_name_from_backup_filename(name)
                # Create the item text with clean name and formatted date
                item_text = f"{display_name} ({date_str_formatted})"

                # Create and add the item
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path) # Save the full path in the item
                self.backup_list_widget.addItem(item)
            # End loop for backups
        # End if/else not backups
    # --- End populate_backup_list ---
     
     @Slot()
     def delete_selected_backup(self):
        current_item = self.backup_list_widget.currentItem()
        if not current_item: return
        backup_path = current_item.data(Qt.ItemDataRole.UserRole)
        if not backup_path: return
        backup_name = os.path.basename(backup_path)
        
        confirm_title = "Confirm Deletion"
        confirm_text = (
            "Are you sure you want to PERMANENTLY delete the backup file:\n\n"
            f"{backup_name}\n\n" # Placeholder for the file name
            "This action cannot be undone!"
        )

        confirm = QMessageBox.warning(self, confirm_title, confirm_text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            QApplication.processEvents()
            success, message = core_logic.delete_single_backup_file(backup_path)
            self.setEnabled(True)
            if success:
                QMessageBox.information(self, "Success", message)
                self.populate_backup_list()
            else:
                QMessageBox.critical(self, "Deletion Error", message)
                self.populate_backup_list() # Update anyway