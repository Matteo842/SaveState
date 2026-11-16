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
from common.i18n import tr


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
                    'message': tr('Failed to connect to WebDAV server'),
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
        
        self.setWindowTitle(tr("WebDAV Configuration"))
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self._init_ui()
        self._load_current_config()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # --- Server Settings Group ---
        server_group = QGroupBox(tr("Server Settings"))
        server_layout = QFormLayout()
        server_layout.setSpacing(8)
        
        # Preset selector
        self.preset_combo = QComboBox()
        self.preset_combo.addItem(tr("Custom"), "")
        self.preset_combo.addItem("Nextcloud", "nextcloud")
        self.preset_combo.addItem("ownCloud", "owncloud")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        server_layout.addRow(tr("Server Type:"), self.preset_combo)
        
        # URL
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://cloud.example.com/remote.php/dav/files/username/")
        server_layout.addRow(tr("WebDAV URL:"), self.url_edit)
        
        # Help text
        self.url_help = QLabel()
        self.url_help.setWordWrap(True)
        self.url_help.setStyleSheet("color: #888888; font-size: 11px;")
        self._update_url_help()
        server_layout.addRow("", self.url_help)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # --- Authentication Group ---
        auth_group = QGroupBox(tr("Authentication"))
        auth_layout = QFormLayout()
        auth_layout.setSpacing(8)
        
        # Username
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(tr("Your username"))
        auth_layout.addRow(tr("Username:"), self.username_edit)
        
        # Password
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(tr("Password or App Password"))
        auth_layout.addRow(tr("Password:"), self.password_edit)
        
        # App password hint
        password_hint = QLabel(tr("For Nextcloud/ownCloud, use an App Password from Security settings"))
        password_hint.setWordWrap(True)
        password_hint.setStyleSheet("color: #888888; font-size: 11px;")
        auth_layout.addRow("", password_hint)
        
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)
        
        # --- Advanced Options Group ---
        options_group = QGroupBox(tr("Advanced Options"))
        options_layout = QVBoxLayout()
        options_layout.setSpacing(8)
        
        # Verify SSL
        self.verify_ssl_checkbox = QCheckBox(tr("Verify SSL Certificate"))
        self.verify_ssl_checkbox.setChecked(True)
        self.verify_ssl_checkbox.setToolTip(
            tr("Verify SSL certificates.\n"
            "Disable only for self-signed certificates (not recommended).")
        )
        options_layout.addWidget(self.verify_ssl_checkbox)
        
        # Digest auth
        self.digest_auth_checkbox = QCheckBox(tr("Use Digest Authentication"))
        self.digest_auth_checkbox.setToolTip(
            tr("Use Digest authentication instead of Basic.\n"
            "Rarely needed - most servers use Basic auth with HTTPS.")
        )
        options_layout.addWidget(self.digest_auth_checkbox)
        
        # Auto-connect
        self.auto_connect_checkbox = QCheckBox(tr("Auto-connect on startup"))
        self.auto_connect_checkbox.setToolTip(
            tr("Automatically connect to this WebDAV server when SaveState starts")
        )
        options_layout.addWidget(self.auto_connect_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # --- Test Connection ---
        test_frame = QFrame()
        test_layout = QHBoxLayout(test_frame)
        test_layout.setContentsMargins(0, 0, 0, 0)
        
        self.test_button = QPushButton(tr("Test Connection"))
        self.test_button.clicked.connect(self._on_test_clicked)
        test_layout.addWidget(self.test_button)
        
        self.test_status_label = QLabel("")
        self.test_status_label.setWordWrap(True)
        test_layout.addWidget(self.test_status_label, stretch=1)
        
        layout.addWidget(test_frame)
        
        # --- Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.save_button = QPushButton(tr("Save"))
        self.save_button.setObjectName("SaveButton")
        self.save_button.clicked.connect(self._on_save_clicked)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
    
    def _update_url_help(self):
        """Update the URL help text based on selected preset."""
        preset = self.preset_combo.currentData()
        if preset == "nextcloud":
            self.url_help.setText(
                tr("Nextcloud URL format: https://your-server.com/remote.php/dav/files/USERNAME/\n"
                "Replace USERNAME with your Nextcloud username")
            )
        elif preset == "owncloud":
            self.url_help.setText(
                tr("ownCloud URL format: https://your-server.com/remote.php/webdav/\n"
                "The username is specified in the Authentication section")
            )
        else:
            self.url_help.setText(
                tr("Enter the full WebDAV URL including the path")
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
        if self.current_config.get('webdav_has_password', False):
            self.password_edit.setPlaceholderText(tr("Saved password will be used if left blank"))
        self.verify_ssl_checkbox.setChecked(self.current_config.get('webdav_verify_ssl', True))
        self.digest_auth_checkbox.setChecked(self.current_config.get('webdav_use_digest', False))
        self.auto_connect_checkbox.setChecked(self.current_config.get('webdav_auto_connect', False))
    
    def _on_test_clicked(self):
        """Test the connection with current settings."""
        url = self.url_edit.text().strip()
        username = self.username_edit.text().strip()
        password = self.password_edit.text() or self.current_config.get('webdav_saved_password', '')
        
        if not url:
            QMessageBox.warning(
                self,
                tr("Missing Information"),
                tr("Please enter a WebDAV URL.")
            )
            return
        
        if not username or not password:
            QMessageBox.warning(
                self,
                tr("Missing Information"),
                tr("Please enter username and password.")
            )
            return
        
        # Update status
        self.test_status_label.setText(tr("Testing connection..."))
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
            self.test_status_label.setText(tr("✓ Connection successful!"))
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
                tr("Missing Information"),
                tr("Please enter a WebDAV URL.")
            )
            return
        
        if not username:
            QMessageBox.warning(
                self,
                tr("Missing Information"),
                tr("Please enter a username.")
            )
            return

        if not self.password_edit.text() and not self.current_config.get('webdav_has_password', False):
            QMessageBox.warning(
                self,
                tr("Missing Information"),
                tr("Please enter a password.")
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
