# cloud_utils/smb_config_dialog.py
# -*- coding: utf-8 -*-
"""
SMB Configuration Dialog - UI for configuring network folder settings.
"""

import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QFileDialog, QGroupBox, QFormLayout,
    QMessageBox, QFrame
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


class ConnectionTestWorker(QObject):
    """Worker thread for testing SMB connection."""
    finished = Signal(dict)  # Result dict from test_connection
    
    def __init__(self, provider, path, use_credentials, username):
        super().__init__()
        self.provider = provider
        self.path = path
        self.use_credentials = use_credentials
        self.username = username
    
    def run(self):
        """Test the connection in background."""
        try:
            # Try to connect
            success = self.provider.connect(
                path=self.path,
                use_credentials=self.use_credentials,
                username=self.username
            )
            
            if success:
                result = self.provider.test_connection()
            else:
                result = {
                    'success': False,
                    'message': 'Could not connect to the specified path',
                    'details': None
                }
            
            self.finished.emit(result)
            
        except Exception as e:
            logging.error(f"Connection test failed: {e}")
            self.finished.emit({
                'success': False,
                'message': str(e),
                'details': None
            })


class SMBConfigDialog(QDialog):
    """
    Dialog for configuring SMB/Network Folder provider settings.
    
    Allows user to:
    - Select network path (UNC or mapped drive)
    - Optionally specify credentials
    - Test the connection
    """
    
    # Emitted when configuration is saved
    config_saved = Signal(dict)
    
    def __init__(self, parent=None, current_config: dict = None):
        """
        Initialize the SMB configuration dialog.
        
        Args:
            parent: Parent widget
            current_config: Current SMB configuration to pre-populate
        """
        super().__init__(parent)
        
        self.setWindowTitle("Network Folder Configuration")
        self.setMinimumWidth(500)
        self.setModal(True)
        
        # Store current config
        self.current_config = current_config or {}
        
        # Worker thread for connection test
        self._test_thread = None
        self._test_worker = None
        
        self._init_ui()
        self._load_current_config()
        self._apply_styles()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Header
        header_label = QLabel("Configure Network Folder")
        header_label.setProperty("class", "section-header")
        layout.addWidget(header_label)
        
        description = QLabel(
            "Sync your save backups to a network share or local folder.\n"
            "Supports Windows shares (\\\\server\\share), mapped drives, "
            "and local folders."
        )
        description.setWordWrap(True)
        description.setProperty("class", "description")
        layout.addWidget(description)
        
        # Path configuration group
        path_group = QGroupBox("Network Path")
        path_layout = QFormLayout(path_group)
        
        # Path input with browse button
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("\\\\server\\share\\folder or Z:\\Backups")
        path_row.addWidget(self.path_edit, 1)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        path_row.addWidget(self.browse_btn)
        
        path_layout.addRow("Path:", path_row)
        
        layout.addWidget(path_group)
        
        # Credentials group
        cred_group = QGroupBox("Authentication (Optional)")
        cred_layout = QVBoxLayout(cred_group)
        
        self.use_credentials_cb = QCheckBox("Use different credentials")
        self.use_credentials_cb.toggled.connect(self._on_credentials_toggled)
        cred_layout.addWidget(self.use_credentials_cb)
        
        # Credentials form
        self.cred_form = QFrame()
        cred_form_layout = QFormLayout(self.cred_form)
        cred_form_layout.setContentsMargins(20, 10, 0, 0)
        
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("domain\\username or username@domain")
        cred_form_layout.addRow("Username:", self.username_edit)
        
        cred_note = QLabel(
            "Note: Password will be requested when connecting.\n"
            "For permanent access, use Windows Credential Manager."
        )
        cred_note.setProperty("class", "help-text")
        cred_note.setWordWrap(True)
        cred_form_layout.addRow("", cred_note)
        
        self.cred_form.setVisible(False)
        cred_layout.addWidget(self.cred_form)
        
        layout.addWidget(cred_group)
        
        # Auto-connect option
        self.auto_connect_cb = QCheckBox("Auto-connect on startup")
        self.auto_connect_cb.setToolTip(
            "Automatically connect to this network folder when SaveState starts"
        )
        layout.addWidget(self.auto_connect_cb)
        
        # Test connection section
        test_layout = QHBoxLayout()
        
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test_clicked)
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setProperty("class", "status-label")
        test_layout.addWidget(self.test_status, 1)
        
        layout.addLayout(test_layout)
        
        # Spacer
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.save_btn.setProperty("class", "primary")
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
    
    def _apply_styles(self):
        """Apply consistent styling to the dialog (matching SaveState dark theme)."""
        # NOTE: This dialog inherits styles from the global app stylesheet.
        # We only need to override a few specific things for this dialog.
        # The colors below match config.py DARK_THEME_QSS:
        # - Background: #2D2D2D (main), #1E1E1E (darker)
        # - Input fields: #3C3C3C
        # - Borders: #555555
        # - GroupBox titles: #A10808 (red accent)
        # - Text: #F0F0F0, #E0E0E0
        # - Buttons: #4A4A4A, hover #5A5A5A
        # - Primary/Danger button: #AA0000, hover #CC0000
        self.setStyleSheet("""
            QLabel[class="section-header"] {
                font-size: 14px;
                font-weight: bold;
                color: #A10808;
            }
            QLabel[class="description"] {
                color: #A0A0A0;
                font-size: 10pt;
            }
            QLabel[class="help-text"] {
                color: #707070;
                font-size: 9pt;
            }
            QLabel[class="status-label"] {
                font-size: 10pt;
            }
            QPushButton[class="primary"] {
                background-color: #AA0000;
                font-weight: bold;
            }
            QPushButton[class="primary"]:hover {
                background-color: #CC0000;
            }
            QPushButton[class="primary"]:pressed {
                background-color: #880000;
            }
        """)
    
    def _load_current_config(self):
        """Load current configuration into UI fields."""
        if not self.current_config:
            return
        
        self.path_edit.setText(self.current_config.get('smb_path', ''))
        self.use_credentials_cb.setChecked(
            self.current_config.get('smb_use_credentials', False)
        )
        self.username_edit.setText(self.current_config.get('smb_username', ''))
        self.auto_connect_cb.setChecked(
            self.current_config.get('smb_auto_connect', False)
        )
    
    def _on_credentials_toggled(self, checked: bool):
        """Show/hide credentials form based on checkbox state."""
        self.cred_form.setVisible(checked)
        self.adjustSize()
    
    def _on_browse_clicked(self):
        """Open folder browser dialog."""
        # Start from current path if set
        start_path = self.path_edit.text() or ""
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Network Folder",
            start_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if folder:
            self.path_edit.setText(folder)
    
    def _on_test_clicked(self):
        """Test the connection with current settings."""
        path = self.path_edit.text().strip()
        
        if not path:
            self.test_status.setText("❌ Please enter a path")
            self.test_status.setStyleSheet("color: #ff6666;")
            return
        
        # Disable button during test
        self.test_btn.setEnabled(False)
        self.test_status.setText("⏳ Testing connection...")
        self.test_status.setStyleSheet("color: #a0a0a0;")
        
        # Create provider and test
        from cloud_utils.smb_provider import SMBProvider
        provider = SMBProvider()
        
        # Run test in background thread
        self._test_thread = QThread()
        self._test_worker = ConnectionTestWorker(
            provider,
            path,
            self.use_credentials_cb.isChecked(),
            self.username_edit.text().strip()
        )
        self._test_worker.moveToThread(self._test_thread)
        
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.finished.connect(self._test_thread.quit)
        
        self._test_thread.start()
    
    def _on_test_finished(self, result: dict):
        """Handle connection test result."""
        self.test_btn.setEnabled(True)
        
        if result.get('success'):
            self.test_status.setText("✓ Connection successful")
            self.test_status.setStyleSheet("color: #66ff66;")
        else:
            message = result.get('message', 'Unknown error')
            self.test_status.setText(f"❌ {message}")
            self.test_status.setStyleSheet("color: #ff6666;")
    
    def _on_save_clicked(self):
        """Save configuration and close dialog."""
        path = self.path_edit.text().strip()
        
        if not path:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Please enter a network path."
            )
            return
        
        # Build configuration dictionary
        config = {
            'smb_enabled': True,
            'smb_path': path,
            'smb_use_credentials': self.use_credentials_cb.isChecked(),
            'smb_username': self.username_edit.text().strip(),
            'smb_auto_connect': self.auto_connect_cb.isChecked()
        }
        
        self.config_saved.emit(config)
        self.accept()
    
    def get_config(self) -> dict:
        """Get the current configuration from the dialog."""
        return {
            'smb_enabled': True,
            'smb_path': self.path_edit.text().strip(),
            'smb_use_credentials': self.use_credentials_cb.isChecked(),
            'smb_username': self.username_edit.text().strip(),
            'smb_auto_connect': self.auto_connect_cb.isChecked()
        }
