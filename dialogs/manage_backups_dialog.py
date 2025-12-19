# -*- coding: utf-8 -*-
import os
from PySide6.QtWidgets import (
    QDialog, QListWidget, QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
    QMessageBox, QApplication, QStyle, QListWidgetItem, QWidget, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Slot, Qt, QLocale, QCoreApplication, QSize
from PySide6.QtGui import QIcon

# Import necessary logic
import core_logic
import config
import logging
from gui_components import lock_backup_manager
from utils import resource_path


class ManageBackupsDialog(QDialog):

     def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.setWindowTitle(f"Manage Backups for {self.profile_name}")
        self.setMinimumWidth(550)
        # Get the style for standard icons
        style = QApplication.instance().style()
        
        # --- Load lock icon path for stylesheet ---
        self.lock_icon_path = None
        try:
            icon_path = resource_path("icons/lock.png")
            if os.path.exists(icon_path):
                # Convert to forward slashes for CSS url()
                self.lock_icon_path = icon_path.replace("\\", "/")
                logging.debug(f"Lock icon found: {self.lock_icon_path}")
        except Exception as e:
            logging.debug(f"Lock icon not found: {e}")
        # --- End load lock icon ---
        
        # Widget - Use QTableWidget for better control over columns
        self.backup_table = QTableWidget()
        self.backup_table.setColumnCount(2)  # Backup name, Lock toggle
        self.backup_table.setHorizontalHeaderLabels(["Backup", "Lock"])
        self.backup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Configure header
        header = self.backup_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Backup name stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # Lock column fixed width
        self.backup_table.setColumnWidth(1, 50)  # Lock column width
        self.backup_table.verticalHeader().setDefaultSectionSize(36)
        
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setObjectName("DangerButton")
        
        # Set standard icon for Delete
        delete_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        self.delete_button.setIcon(delete_icon)
        
        self.delete_all_button = QPushButton("Delete All")
        self.delete_all_button.setObjectName("DangerButton")
        self.delete_all_button.setIcon(delete_icon)
        
        self.close_button = QPushButton("Close")
        
        # Set standard icon for Close
        close_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        self.close_button.setIcon(close_icon)
        
        self.delete_button.setEnabled(False)
        self.delete_all_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Existing backups for '{self.profile_name}':"))
        layout.addWidget(self.backup_table)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.delete_all_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        
        # Connect selection change to update delete button state
        self.backup_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.delete_button.clicked.connect(self.delete_selected_backup)
        self.delete_all_button.clicked.connect(self.delete_all_backups)
        self.close_button.clicked.connect(self.reject)
        self.populate_backup_list()
     
     def _on_selection_changed(self):
        """Handle selection change in the backup table."""
        selected_rows = self.backup_table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            name_item = self.backup_table.item(row, 0)  # Column 0 is now the backup name
            has_valid_path = name_item is not None and name_item.data(Qt.ItemDataRole.UserRole) is not None
            self.delete_button.setEnabled(has_valid_path)
        else:
            self.delete_button.setEnabled(False)
     
     def _create_lock_checkbox(self, backup_path: str, is_locked: bool) -> QWidget:
        """Create a styled lock checkbox widget for the backup."""
        checkbox_widget = QWidget()
        checkbox_widget.setStyleSheet("background-color: transparent;")
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        checkbox = QCheckBox()
        checkbox.setChecked(is_locked)
        checkbox.setProperty("backup_path", backup_path)
        
        # Build stylesheet with lock icon if available
        icon_style = ""
        if self.lock_icon_path:
            icon_style = f"""
            QCheckBox::indicator:checked {{
                image: url({self.lock_icon_path});
            }}
            """
        
        # Custom checkbox styling - blue theme for lock with icon inside
        checkbox.setStyleSheet(f"""
            QCheckBox {{
                spacing: 0px;
            }}
            QCheckBox::indicator {{
                width: 24px;
                height: 24px;
                border-radius: 4px;
                border: 2px solid #555555;
                background-color: #2b2b2b;
            }}
            QCheckBox::indicator:hover {{
                border: 2px solid #888888;
                background-color: #353535;
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid #2196F3;
                background-color: #2196F3;
            }}
            QCheckBox::indicator:checked:hover {{
                border: 2px solid #42A5F5;
                background-color: #42A5F5;
            }}
            {icon_style}
        """)
        
        # Set tooltip
        if is_locked:
            checkbox.setToolTip("Click to unlock this backup")
        else:
            checkbox.setToolTip("Click to lock this backup (protects from deletion)")
        
        # Connect to toggle handler
        checkbox.toggled.connect(lambda checked, path=backup_path: self._on_lock_toggled(path, checked))
        
        checkbox_layout.addWidget(checkbox)
        return checkbox_widget
     
     def _on_lock_toggled(self, backup_path: str, checked: bool):
        """Handle lock checkbox toggle."""
        if checked:
            # Lock the backup
            success, message = lock_backup_manager.lock_backup(self.profile_name, backup_path)
            if success:
                logging.info(f"Backup locked: {backup_path}")
            else:
                QMessageBox.warning(self, "Lock Failed", message)
                # Refresh the list to reset checkbox state
                self.populate_backup_list()
        else:
            # Unlock the backup
            success, message = lock_backup_manager.unlock_backup(self.profile_name, backup_path)
            if success:
                logging.info(f"Backup unlocked: {backup_path}")
            else:
                QMessageBox.warning(self, "Unlock Failed", message)
                # Refresh the list to reset checkbox state
                self.populate_backup_list()
        
        # Update tooltip on the checkbox
        self._update_lock_tooltip_for_path(backup_path, checked)
     
     def _update_lock_tooltip_for_path(self, backup_path: str, is_locked: bool):
        """Update the tooltip for a specific lock checkbox."""
        for row in range(self.backup_table.rowCount()):
            checkbox_widget = self.backup_table.cellWidget(row, 1)  # Column 1 is now the lock checkbox
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.property("backup_path") == backup_path:
                    if is_locked:
                        checkbox.setToolTip("Click to unlock this backup")
                    else:
                        checkbox.setToolTip("Click to lock this backup (protects from deletion)")
                    break
     
     # --- Method populate_backup_list ---
     @Slot()
     def populate_backup_list(self):
        self.backup_table.setRowCount(0)
        self.delete_button.setEnabled(False)
        self.delete_all_button.setEnabled(False)

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
        
        # Get locked backup for this profile
        locked_backup_path = lock_backup_manager.get_locked_backup_for_profile(self.profile_name)

        if not backups:
            # Handle no backups found - add a single row with message
            self.backup_table.setRowCount(1)
            no_backup_item = QTableWidgetItem("No backups found.")
            no_backup_item.setData(Qt.ItemDataRole.UserRole, None)
            self.backup_table.setItem(0, 0, no_backup_item)  # Column 0 is backup name
            self.backup_table.setEnabled(False)
            self.delete_all_button.setEnabled(False)
        else:
            # There are backups, populate the table
            self.backup_table.setEnabled(True)
            self.delete_all_button.setEnabled(True)

            # Loop to add each backup with formatted date
            for row_idx, (name, path, dt_obj) in enumerate(backups):
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
                
                # Check if this backup is locked
                is_locked = False
                if locked_backup_path:
                    is_locked = os.path.normcase(os.path.normpath(path)) == os.path.normcase(os.path.normpath(locked_backup_path))

                # Insert row
                self.backup_table.insertRow(row_idx)
                
                # Column 0: Backup name with path stored in UserRole
                name_item = QTableWidgetItem(item_text)
                name_item.setData(Qt.ItemDataRole.UserRole, path)
                self.backup_table.setItem(row_idx, 0, name_item)
                
                # Column 1: Lock checkbox
                lock_widget = self._create_lock_checkbox(path, is_locked)
                self.backup_table.setCellWidget(row_idx, 1, lock_widget)
            # End loop for backups
        # End if/else not backups
    # --- End populate_backup_list ---
     
     @Slot()
     def delete_selected_backup(self):
        selected_rows = self.backup_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.backup_table.item(row, 0)  # Column 0 is now the backup name
        if not name_item:
            return
        
        backup_path = name_item.data(Qt.ItemDataRole.UserRole)
        if not backup_path:
            return
        
        backup_name = os.path.basename(backup_path)
        
        # Check if backup is locked
        if lock_backup_manager.is_backup_locked(backup_path):
            QMessageBox.warning(
                self,
                "Backup Locked",
                f"Cannot delete '{backup_name}'.\n\nThis backup is locked. Unlock it first to delete."
            )
            return
        
        confirm_title = "Confirm Deletion"
        confirm_text = (
            "Are you sure you want to PERMANENTLY delete the backup file:\n\n"
            f"{backup_name}\n\n"
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
                self.populate_backup_list()
     
     @Slot()
     def delete_all_backups(self):
        """Delete all backups for this profile after confirmation."""
        # Count backups and check for locked ones
        backup_count = 0
        locked_count = 0
        for row in range(self.backup_table.rowCount()):
            item = self.backup_table.item(row, 0)  # Column 0 is now the backup name
            if item and item.data(Qt.ItemDataRole.UserRole):
                backup_path = item.data(Qt.ItemDataRole.UserRole)
                backup_count += 1
                if lock_backup_manager.is_backup_locked(backup_path):
                    locked_count += 1
        
        if backup_count == 0:
            return
        
        # Prepare confirmation message
        confirm_title = "Confirm Delete All"
        if locked_count > 0:
            confirm_text = (
                f"Are you sure you want to PERMANENTLY delete {backup_count - locked_count} backup(s) "
                f"for profile '{self.profile_name}'?\n\n"
                f"Note: {locked_count} locked backup(s) will be skipped.\n\n"
                "This action cannot be undone!"
            )
        else:
            confirm_text = (
                f"Are you sure you want to PERMANENTLY delete ALL {backup_count} backup(s) "
                f"for profile '{self.profile_name}'?\n\n"
                "This action cannot be undone!"
            )
        
        confirm = QMessageBox.warning(
            self, 
            confirm_title, 
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            QApplication.processEvents()
            
            # Collect all backup paths (excluding locked ones)
            backup_paths = []
            for row in range(self.backup_table.rowCount()):
                item = self.backup_table.item(row, 0)  # Column 0 is now the backup name
                if item:
                    backup_path = item.data(Qt.ItemDataRole.UserRole)
                    if backup_path and not lock_backup_manager.is_backup_locked(backup_path):
                        backup_paths.append(backup_path)
            
            # Delete all unlocked backups
            success_count = 0
            failed_count = 0
            
            for backup_path in backup_paths:
                success, message = core_logic.delete_single_backup_file(backup_path)
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    logging.error(f"Failed to delete backup: {message}")
            
            self.setEnabled(True)
            
            # Show result
            if failed_count == 0:
                result_msg = f"Successfully deleted {success_count} backup(s)."
                if locked_count > 0:
                    result_msg += f"\n{locked_count} locked backup(s) were skipped."
                QMessageBox.information(self, "Success", result_msg)
            else:
                QMessageBox.warning(
                    self,
                    "Partial Success",
                    f"Deleted {success_count} backup(s).\n"
                    f"Failed to delete {failed_count} backup(s)."
                    + (f"\n{locked_count} locked backup(s) were skipped." if locked_count > 0 else "")
                )
            
            # Refresh the list
            self.populate_backup_list()