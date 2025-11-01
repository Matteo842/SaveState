# cloud_utils/cloud_panel.py
# -*- coding: utf-8 -*-
"""
Cloud Save Panel UI - Inline panel for managing cloud backups via Google Drive.
Similar to the settings panel, this is embedded in the main window.
"""

import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QLineEdit, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QEvent
from PySide6.QtGui import QIcon, QColor


class CloudSavePanel(QWidget):
    """
    Inline panel for Cloud Save management.
    Shows list of backups from the backup folder and allows sync with Google Drive.
    """
    
    # Signals
    sync_requested = Signal(list)  # Emitted when user wants to sync selected backups
    download_requested = Signal(str)  # Emitted when user wants to download a backup
    
    def __init__(self, backup_base_dir, profiles, parent=None):
        """
        Initialize the Cloud Save panel.
        
        Args:
            backup_base_dir: Base directory where backups are stored
            profiles: Dictionary of current profiles
            parent: Parent widget (MainWindow)
        """
        super().__init__(parent)
        
        self.backup_base_dir = backup_base_dir
        self.profiles = profiles
        self.main_window = parent
        
        # Track which backups are available locally
        self.local_backups = []
        
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        
        # --- Header Section ---
        header_layout = QHBoxLayout()
        
        title_label = QLabel("<h2>Cloud Save Manager</h2>")
        title_label.setObjectName("CloudPanelTitle")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch(1)
        
        # Google Drive connection status
        self.connection_status_label = QLabel("● Not Connected")
        self.connection_status_label.setObjectName("ConnectionStatus")
        self.connection_status_label.setStyleSheet("color: #FF5555;")
        header_layout.addWidget(self.connection_status_label)
        
        main_layout.addLayout(header_layout)
        
        # --- Description ---
        description = QLabel(
            "Sync your save backups with Google Drive. "
            "Select backups to upload or download from the cloud."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #AAAAAA; font-size: 10pt;")
        main_layout.addWidget(description)
        
        # --- Connection and Filters Row (side by side) ---
        connection_filters_row = QHBoxLayout()
        connection_filters_row.setSpacing(12)
        
        # Google Drive Connection Section (left side)
        connection_group = QGroupBox("Google Drive Connection")
        connection_layout = QVBoxLayout()
        connection_layout.setContentsMargins(8, 8, 8, 8)
        connection_layout.setSpacing(6)
        
        # Connection buttons row
        connection_buttons_layout = QHBoxLayout()
        
        self.connect_button = QPushButton("Connect to Google Drive")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.clicked.connect(self._on_connect_clicked)
        connection_buttons_layout.addWidget(self.connect_button)
        
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)
        connection_buttons_layout.addWidget(self.disconnect_button)
        
        connection_buttons_layout.addStretch(1)
        
        connection_layout.addLayout(connection_buttons_layout)
        connection_group.setLayout(connection_layout)
        connection_filters_row.addWidget(connection_group, stretch=1)
        
        # Filter Options (right side)
        filter_group = QGroupBox("Display Filters")
        filter_layout = QVBoxLayout()
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_layout.setSpacing(6)
        
        self.show_all_backups_checkbox = QCheckBox("Show all backups (including non-profile backups)")
        self.show_all_backups_checkbox.setToolTip(
            "When enabled, shows all backup folders even if they don't match any profile"
        )
        self.show_all_backups_checkbox.toggled.connect(self._on_filter_changed)
        filter_layout.addWidget(self.show_all_backups_checkbox)
        
        filter_group.setLayout(filter_layout)
        connection_filters_row.addWidget(filter_group, stretch=1)
        
        main_layout.addLayout(connection_filters_row)
        
        # --- Backup List Table ---
        list_group = QGroupBox("Available Backups")
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(6, 6, 6, 6)
        list_layout.setSpacing(6)
        
        self.backup_table = QTableWidget()
        self.backup_table.setColumnCount(5)
        self.backup_table.setHorizontalHeaderLabels([
            "Select", "Backup Name", "Profile", "Local Status", "Cloud Status"
        ])
        
        # Configure table
        self.backup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.backup_table.setAlternatingRowColors(False)  # Disabled to fix white row bug
        self.backup_table.verticalHeader().setVisible(False)
        
        # Set column widths
        header = self.backup_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Select checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Backup Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Profile
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Local Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Cloud Status
        self.backup_table.setColumnWidth(0, 60)
        
        list_layout.addWidget(self.backup_table)
        list_group.setLayout(list_layout)
        main_layout.addWidget(list_group, stretch=1)
        
        # --- Progress Bar (initially hidden) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("%v/%m files (%p%)")
        main_layout.addWidget(self.progress_bar)
        
        # --- Action Buttons and Search Bar Row ---
        actions_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("Refresh List")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        actions_layout.addWidget(self.refresh_button)
        
        # Search bar (hidden by default, appears when typing)
        self.filter_search = QLineEdit()
        self.filter_search.setPlaceholderText("Type to filter backups...")
        self.filter_search.setMaximumWidth(250)
        self.filter_search.textChanged.connect(self._on_search_changed)
        self.filter_search.hide()  # Initially hidden
        actions_layout.addWidget(self.filter_search)
        
        actions_layout.addStretch(1)
        
        self.upload_button = QPushButton("Upload Selected to Cloud")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self._on_upload_clicked)
        actions_layout.addWidget(self.upload_button)
        
        self.download_button = QPushButton("Download Selected from Cloud")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._on_download_clicked)
        actions_layout.addWidget(self.download_button)
        
        main_layout.addLayout(actions_layout)
        
        # --- Exit Button ---
        exit_layout = QHBoxLayout()
        exit_layout.addStretch(1)
        
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self._on_exit_clicked)
        exit_layout.addWidget(self.exit_button)
        
        main_layout.addLayout(exit_layout)
        
        # Initial population
        self._populate_backup_list()
    
    def _populate_backup_list(self):
        """Populate the table with available backups from the backup directory."""
        self.backup_table.setRowCount(0)
        self.local_backups.clear()
        
        if not os.path.isdir(self.backup_base_dir):
            logging.warning(f"Backup directory does not exist: {self.backup_base_dir}")
            return
        
        # Get all subdirectories in backup folder (each is a profile backup folder)
        try:
            entries = os.listdir(self.backup_base_dir)
        except Exception as e:
            logging.error(f"Error reading backup directory: {e}")
            return
        
        show_all = self.show_all_backups_checkbox.isChecked()
        search_text = self.filter_search.text().lower()
        
        for entry in sorted(entries):
            entry_path = os.path.join(self.backup_base_dir, entry)
            
            # Only process directories
            if not os.path.isdir(entry_path):
                continue
            
            # Skip special folders
            if entry.startswith('.') or entry == '__pycache__':
                continue
            
            # Check if this backup folder matches a profile
            profile_match = entry if entry in self.profiles else "Unknown"
            
            # Filter: if not showing all, skip non-profile backups
            if not show_all and profile_match == "Unknown":
                continue
            
            # Search filter
            if search_text and search_text not in entry.lower():
                continue
            
            # Count backup files in this folder
            try:
                backup_files = [f for f in os.listdir(entry_path) if f.endswith('.zip')]
                file_count = len(backup_files)
            except Exception:
                file_count = 0
            
            self.local_backups.append({
                'name': entry,
                'path': entry_path,
                'profile': profile_match,
                'file_count': file_count
            })
        
        # Populate table
        for backup in self.local_backups:
            self._add_backup_row(backup)
    
    def _add_backup_row(self, backup_info):
        """Add a row to the backup table."""
        row = self.backup_table.rowCount()
        self.backup_table.insertRow(row)
        
        # Column 0: Checkbox
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox = QCheckBox()
        checkbox_layout.addWidget(checkbox)
        self.backup_table.setCellWidget(row, 0, checkbox_widget)
        
        # Column 1: Backup Name
        name_item = QTableWidgetItem(backup_info['name'])
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.backup_table.setItem(row, 1, name_item)
        
        # Column 2: Profile
        profile_item = QTableWidgetItem(backup_info['profile'])
        profile_item.setFlags(profile_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if backup_info['profile'] == "Unknown":
            profile_item.setForeground(QColor("#FF5555"))
        else:
            profile_item.setForeground(QColor("#4CAF50"))
        self.backup_table.setItem(row, 2, profile_item)
        
        # Column 3: Local Status
        local_status = f"{backup_info['file_count']} files"
        local_item = QTableWidgetItem(local_status)
        local_item.setFlags(local_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        local_item.setForeground(QColor("#4CAF50"))
        self.backup_table.setItem(row, 3, local_item)
        
        # Column 4: Cloud Status (placeholder - will be updated when connected)
        cloud_item = QTableWidgetItem("Not synced")
        cloud_item.setFlags(cloud_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        cloud_item.setForeground(QColor("#AAAAAA"))
        self.backup_table.setItem(row, 4, cloud_item)
    
    def _on_filter_changed(self, checked):
        """Handle filter checkbox change."""
        self._populate_backup_list()
    
    def _on_search_changed(self, text):
        """Handle search text change and hide search bar if empty."""
        self._populate_backup_list()
        
        # Hide search bar if text is empty
        if not text:
            self.filter_search.hide()
    
    def event(self, event_obj):
        """Handles events for the cloud panel, specifically KeyPress to activate search bar."""
        if event_obj.type() == QEvent.Type.KeyPress:
            # Only act if the search bar is currently hidden
            if not self.filter_search.isVisible():
                key_text = event_obj.text()
                # Check if the key produces a printable character and is not just whitespace
                # Also exclude special keys
                if key_text and key_text.isprintable() and key_text.strip() != '' and \
                   event_obj.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, 
                                          Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
                    # Show the search bar, set focus to it, and input the typed character
                    self.filter_search.show()
                    self.filter_search.setFocus()
                    self.filter_search.setText(key_text)  # This also triggers _on_search_changed
                    return True  # Event handled, stop further processing
            # Handle Escape key when search bar is visible and has focus
            elif self.filter_search.isVisible() and self.filter_search.hasFocus() and \
                 event_obj.key() == Qt.Key.Key_Escape:
                self.filter_search.clear()  # This will trigger _on_search_changed, which will hide it
                self.backup_table.setFocus()  # Return focus to table
                return True  # Event handled
        
        # For all other events or if the key press wasn't handled above,
        # call the base class's event handler
        return super().event(event_obj)
    
    def _on_refresh_clicked(self):
        """Refresh the backup list."""
        logging.info("Refreshing backup list...")
        self._populate_backup_list()
        # TODO: Also refresh cloud status when connected
    
    def _on_connect_clicked(self):
        """Handle Google Drive connection."""
        logging.info("Connecting to Google Drive...")
        # TODO: Implement Google Drive OAuth flow
        QMessageBox.information(
            self,
            "Google Drive Connection",
            "Google Drive integration will be implemented in version 2.0.\n\n"
            "This will allow you to:\n"
            "• Sync backups to Google Drive\n"
            "• Download backups from any device\n"
            "• Automatic backup synchronization"
        )
        
        # Placeholder: simulate connection
        # self._set_connected(True)
    
    def _on_disconnect_clicked(self):
        """Handle Google Drive disconnection."""
        logging.info("Disconnecting from Google Drive...")
        self._set_connected(False)
    
    def _set_connected(self, connected):
        """Update UI based on connection status."""
        if connected:
            self.connection_status_label.setText("● Connected")
            self.connection_status_label.setStyleSheet("color: #4CAF50;")
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.upload_button.setEnabled(True)
            self.download_button.setEnabled(True)
        else:
            self.connection_status_label.setText("● Not Connected")
            self.connection_status_label.setStyleSheet("color: #FF5555;")
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
            self.upload_button.setEnabled(False)
            self.download_button.setEnabled(False)
    
    def _on_upload_clicked(self):
        """Handle upload selected backups to cloud."""
        selected = self._get_selected_backups()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select backups to upload.")
            return
        
        logging.info(f"Uploading {len(selected)} backups to cloud...")
        # TODO: Implement upload logic
        self.sync_requested.emit(selected)
    
    def _on_download_clicked(self):
        """Handle download selected backups from cloud."""
        selected = self._get_selected_backups()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select backups to download.")
            return
        
        logging.info(f"Downloading {len(selected)} backups from cloud...")
        # TODO: Implement download logic
    
    def _get_selected_backups(self):
        """Get list of selected backup names."""
        selected = []
        for row in range(self.backup_table.rowCount()):
            checkbox_widget = self.backup_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    name_item = self.backup_table.item(row, 1)
                    if name_item:
                        selected.append(name_item.text())
        return selected
    
    def _on_exit_clicked(self):
        """Handle exit button - return to main view."""
        if self.main_window:
            self.main_window.exit_cloud_panel()
    
    def update_backup_dir(self, new_dir):
        """Update the backup directory and refresh the list."""
        self.backup_base_dir = new_dir
        self._populate_backup_list()
    
    def update_profiles(self, profiles):
        """Update the profiles dictionary and refresh the list."""
        self.profiles = profiles
        self._populate_backup_list()

