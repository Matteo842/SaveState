# cloud_utils/webdav_config_dialog.py
# -*- coding: utf-8 -*-
"""
WebDAV Configuration Dialog - UI for configuring WebDAV server settings.
"""

import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QGroupBox, QFormLayout,
    QMessageBox, QFrame, QComboBox
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


class WebDAVConnectionTestWorker(QObject):
    """Worker thread for testing WebDAV connection."""
    finished = Signal(dict)
    
    def __init__(self, url, username, password, use_digest_auth, verify_ssl):
        super().__init__()
        self.url = url
        self.username = username
        self.password = password
        self.use_digest_auth = use_digest_auth
        self.verify_ssl = verify_ssl
    
    def run(self):
        """Test the connection in background."""
        try:
            from cloud_utils.webdav_provider import WebDAVProvider
            
            provider = WebDAVProvider()
            success = provider.connect(
                url=self.url,
                username=self.username,
                password=self.password,
                use_digest_auth=self.use_digest_auth,
                verify_ssl=self.verify_ssl
            )
            
            if success:
                result = provider.test_connection()
                provider.disconnect()
                self.finished.emit(result)
            else:
                self.finished.emit({
                    'success': False,
                    'message': 'Failed to connect to WebDAV server',
                    'details': None
                })
                
        except Exception as e:
            logging.error(f"WebDAV connection test error: {e}")
            self.finished.emit({
                'success': False,
                'message': str(e),
                'details': None
            })


class WebDAVConfigDialog(QDialog):
    """
    Dialog for configuring WebDAV server settings.
    
    Allows user to:
    - Enter WebDAV server URL
    - Specify username and password
    - Configure SSL options
    - Test the connection
    """
    
    # Emitted when configuration is saved
    config_saved = Signal(dict)
    
    def __init__(self, parent=None, current_config: dict = None):
        """
        Initialize the WebDAV configuration dialog.
        
        Args:
            parent: Parent widget
            current_config: Current WebDAV configuration to pre-populate
        """
        super().__init__(parent)
        
        self.current_config = current_config or {}
        self.test_thread = None
        self.test_worker = None
        
        self.setWindowTitle("WebDAV Configuration")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self._init_ui()
        self._apply_styles()
        self._load_current_config()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # --- Server Settings Group ---
        server_group = QGroupBox("Server Settings")
        server_layout = QFormLayout()
        server_layout.setSpacing(8)
        
        # Preset selector
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Custom", "")
        self.preset_combo.addItem("Nextcloud", "nextcloud")
        self.preset_combo.addItem("ownCloud", "owncloud")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        server_layout.addRow("Server Type:", self.preset_combo)
        
        # URL
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://cloud.example.com/remote.php/dav/files/username/")
        server_layout.addRow("WebDAV URL:", self.url_edit)
        
        # Help text
        self.url_help = QLabel()
        self.url_help.setWordWrap(True)
        self.url_help.setStyleSheet("color: #888888; font-size: 11px;")
        self._update_url_help()
        server_layout.addRow("", self.url_help)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # --- Authentication Group ---
        auth_group = QGroupBox("Authentication")
        auth_layout = QFormLayout()
        auth_layout.setSpacing(8)
        
        # Username
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Your username")
        auth_layout.addRow("Username:", self.username_edit)
        
        # Password
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Password or App Password")
        auth_layout.addRow("Password:", self.password_edit)
        
        # App password hint
        password_hint = QLabel("For Nextcloud/ownCloud, use an App Password from Security settings")
        password_hint.setWordWrap(True)
        password_hint.setStyleSheet("color: #888888; font-size: 11px;")
        auth_layout.addRow("", password_hint)
        
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)
        
        # --- Advanced Options Group ---
        options_group = QGroupBox("Advanced Options")
        options_layout = QVBoxLayout()
        options_layout.setSpacing(8)
        
        # Verify SSL
        self.verify_ssl_checkbox = QCheckBox("Verify SSL Certificate")
        self.verify_ssl_checkbox.setChecked(True)
        self.verify_ssl_checkbox.setToolTip(
            "Verify SSL certificates.\n"
            "Disable only for self-signed certificates (not recommended)."
        )
        options_layout.addWidget(self.verify_ssl_checkbox)
        
        # Digest auth
        self.digest_auth_checkbox = QCheckBox("Use Digest Authentication")
        self.digest_auth_checkbox.setToolTip(
            "Use Digest authentication instead of Basic.\n"
            "Rarely needed - most servers use Basic auth with HTTPS."
        )
        options_layout.addWidget(self.digest_auth_checkbox)
        
        # Auto-connect
        self.auto_connect_checkbox = QCheckBox("Auto-connect on startup")
        self.auto_connect_checkbox.setToolTip(
            "Automatically connect to this WebDAV server when SaveState starts"
        )
        options_layout.addWidget(self.auto_connect_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # --- Test Connection ---
        test_frame = QFrame()
        test_layout = QHBoxLayout(test_frame)
        test_layout.setContentsMargins(0, 0, 0, 0)
        
        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self._on_test_clicked)
        test_layout.addWidget(self.test_button)
        
        self.test_status_label = QLabel("")
        self.test_status_label.setWordWrap(True)
        test_layout.addWidget(self.test_status_label, stretch=1)
        
        layout.addWidget(test_frame)
        
        # --- Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._on_save_clicked)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
    
    def _apply_styles(self):
        """Apply consistent styling to the dialog (matching SaveState dark theme)."""
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
                color: #E0E0E0;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 4px;
                margin-top: 8px;
                padding: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QLineEdit, QComboBox {
                background-color: #3E3E42;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
                color: #E0E0E0;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #007ACC;
            }
            QPushButton {
                background-color: #4A4A4A;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 6px 16px;
                color: #E0E0E0;
            }
            QPushButton:hover {
                background-color: #5A5A5A;
            }
            QPushButton:pressed {
                background-color: #3A3A3A;
            }
            QPushButton#PrimaryButton {
                background-color: #0E639C;
                border-color: #0E639C;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #1177BB;
            }
            QCheckBox {
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
            }
        """)
    
    def _update_url_help(self):
        """Update the URL help text based on selected preset."""
        preset = self.preset_combo.currentData()
        if preset == "nextcloud":
            self.url_help.setText(
                "Nextcloud URL format: https://your-server.com/remote.php/dav/files/USERNAME/\n"
                "Replace USERNAME with your Nextcloud username"
            )
        elif preset == "owncloud":
            self.url_help.setText(
                "ownCloud URL format: https://your-server.com/remote.php/webdav/\n"
                "The username is specified in the Authentication section"
            )
        else:
            self.url_help.setText(
                "Enter the full WebDAV URL including the path"
            )
    
    def _on_preset_changed(self, index):
        """Handle preset selection change."""
        self._update_url_help()
    
    def _load_current_config(self):
        """Load current configuration into UI fields."""
        if not self.current_config:
            return
        
        self.url_edit.setText(self.current_config.get('webdav_url', ''))
        self.username_edit.setText(self.current_config.get('webdav_username', ''))
        # Note: password is not loaded for security reasons
        self.verify_ssl_checkbox.setChecked(self.current_config.get('webdav_verify_ssl', True))
        self.digest_auth_checkbox.setChecked(self.current_config.get('webdav_use_digest', False))
        self.auto_connect_checkbox.setChecked(self.current_config.get('webdav_auto_connect', False))
    
    def _on_test_clicked(self):
        """Test the connection with current settings."""
        url = self.url_edit.text().strip()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        
        if not url:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter a WebDAV URL."
            )
            return
        
        if not username or not password:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter username and password."
            )
            return
        
        # Update status
        self.test_status_label.setText("Testing connection...")
        self.test_status_label.setStyleSheet("color: #AAAAAA;")
        self.test_button.setEnabled(False)
        
        # Start test in background thread
        self.test_thread = QThread()
        self.test_worker = WebDAVConnectionTestWorker(
            url=url,
            username=username,
            password=password,
            use_digest_auth=self.digest_auth_checkbox.isChecked(),
            verify_ssl=self.verify_ssl_checkbox.isChecked()
        )
        
        self.test_worker.moveToThread(self.test_thread)
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self._on_test_finished)
        self.test_worker.finished.connect(self.test_thread.quit)
        
        self.test_thread.start()
    
    def _on_test_finished(self, result: dict):
        """Handle connection test result."""
        self.test_button.setEnabled(True)
        
        if result.get('success'):
            self.test_status_label.setText("✓ Connection successful!")
            self.test_status_label.setStyleSheet("color: #55FF55;")
        else:
            message = result.get('message', 'Connection failed')
            self.test_status_label.setText(f"✗ {message}")
            self.test_status_label.setStyleSheet("color: #FF5555;")
    
    def _on_save_clicked(self):
        """Save configuration and close dialog."""
        url = self.url_edit.text().strip()
        username = self.username_edit.text().strip()
        
        if not url:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter a WebDAV URL."
            )
            return
        
        if not username:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter a username."
            )
            return
        
        # Build configuration
        config = self.get_config()
        
        # Emit signal and close
        self.config_saved.emit(config)
        self.accept()
    
    def get_config(self) -> dict:
        """Get the current configuration from the dialog."""
        return {
            'webdav_url': self.url_edit.text().strip(),
            'webdav_username': self.username_edit.text().strip(),
            'webdav_password': self.password_edit.text(),  # Will be handled securely
            'webdav_verify_ssl': self.verify_ssl_checkbox.isChecked(),
            'webdav_use_digest': self.digest_auth_checkbox.isChecked(),
            'webdav_auto_connect': self.auto_connect_checkbox.isChecked()
        }
