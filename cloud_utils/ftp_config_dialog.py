# cloud_utils/ftp_config_dialog.py
# -*- coding: utf-8 -*-
"""
FTP Configuration Dialog - UI for configuring FTP server settings.
"""

import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QGroupBox, QFormLayout,
    QMessageBox, QFrame, QSpinBox
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


class FTPConnectionTestWorker(QObject):
    """Worker thread for testing FTP connection."""
    finished = Signal(dict)
    
    def __init__(self, host, port, username, password, use_tls, passive_mode, base_path):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.passive_mode = passive_mode
        self.base_path = base_path
    
    def run(self):
        """Test the connection in background."""
        try:
            from cloud_utils.ftp_provider import FTPProvider
            
            provider = FTPProvider()
            success = provider.connect(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                use_tls=self.use_tls,
                passive_mode=self.passive_mode,
                base_path=self.base_path
            )
            
            if success:
                result = provider.test_connection()
                provider.disconnect()
                self.finished.emit(result)
            else:
                self.finished.emit({
                    'success': False,
                    'message': 'Failed to connect to FTP server',
                    'details': None
                })
                
        except Exception as e:
            logging.error(f"FTP connection test error: {e}")
            self.finished.emit({
                'success': False,
                'message': str(e),
                'details': None
            })


class FTPConfigDialog(QDialog):
    """
    Dialog for configuring FTP server settings.
    
    Allows user to:
    - Enter FTP server address and port
    - Specify username and password
    - Enable FTPS (TLS/SSL)
    - Test the connection
    """
    
    # Emitted when configuration is saved
    config_saved = Signal(dict)
    
    def __init__(self, parent=None, current_config: dict = None):
        """
        Initialize the FTP configuration dialog.
        
        Args:
            parent: Parent widget
            current_config: Current FTP configuration to pre-populate
        """
        super().__init__(parent)
        
        self.current_config = current_config or {}
        self.test_thread = None
        self.test_worker = None
        
        self.setWindowTitle("FTP Server Configuration")
        self.setModal(True)
        self.setMinimumWidth(450)
        
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
        
        # Host
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("ftp.example.com or 192.168.1.100")
        server_layout.addRow("Server Address:", self.host_edit)
        
        # Port
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(21)
        server_layout.addRow("Port:", self.port_spin)
        
        # Base path
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/ (root directory)")
        self.path_edit.setText("/")
        server_layout.addRow("Remote Path:", self.path_edit)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # --- Authentication Group ---
        auth_group = QGroupBox("Authentication")
        auth_layout = QFormLayout()
        auth_layout.setSpacing(8)
        
        # Username
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("anonymous")
        auth_layout.addRow("Username:", self.username_edit)
        
        # Password
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Leave empty for anonymous")
        auth_layout.addRow("Password:", self.password_edit)
        
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)
        
        # --- Connection Options Group ---
        options_group = QGroupBox("Connection Options")
        options_layout = QVBoxLayout()
        options_layout.setSpacing(8)
        
        # Use TLS/SSL
        self.tls_checkbox = QCheckBox("Use FTPS (TLS/SSL encryption)")
        self.tls_checkbox.setToolTip(
            "Enable secure FTP connection.\n"
            "Recommended for connections over the internet."
        )
        options_layout.addWidget(self.tls_checkbox)
        
        # Passive mode
        self.passive_checkbox = QCheckBox("Passive mode (recommended)")
        self.passive_checkbox.setChecked(True)
        self.passive_checkbox.setToolTip(
            "Use passive mode for FTP connections.\n"
            "This is recommended for most setups, especially behind firewalls."
        )
        options_layout.addWidget(self.passive_checkbox)
        
        # Auto-connect
        self.auto_connect_checkbox = QCheckBox("Auto-connect on startup")
        self.auto_connect_checkbox.setToolTip(
            "Automatically connect to this FTP server when SaveState starts"
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
            QLineEdit, QSpinBox {
                background-color: #3E3E42;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
                color: #E0E0E0;
            }
            QLineEdit:focus, QSpinBox:focus {
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
    
    def _load_current_config(self):
        """Load current configuration into UI fields."""
        if not self.current_config:
            return
        
        self.host_edit.setText(self.current_config.get('ftp_host', ''))
        self.port_spin.setValue(self.current_config.get('ftp_port', 21))
        self.path_edit.setText(self.current_config.get('ftp_base_path', '/'))
        self.username_edit.setText(self.current_config.get('ftp_username', ''))
        # Note: password is not loaded for security reasons
        self.tls_checkbox.setChecked(self.current_config.get('ftp_use_tls', False))
        self.passive_checkbox.setChecked(self.current_config.get('ftp_passive_mode', True))
        self.auto_connect_checkbox.setChecked(self.current_config.get('ftp_auto_connect', False))
    
    def _on_test_clicked(self):
        """Test the connection with current settings."""
        host = self.host_edit.text().strip()
        
        if not host:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter a server address."
            )
            return
        
        # Update status
        self.test_status_label.setText("Testing connection...")
        self.test_status_label.setStyleSheet("color: #AAAAAA;")
        self.test_button.setEnabled(False)
        
        # Start test in background thread
        self.test_thread = QThread()
        self.test_worker = FTPConnectionTestWorker(
            host=host,
            port=self.port_spin.value(),
            username=self.username_edit.text().strip() or 'anonymous',
            password=self.password_edit.text(),
            use_tls=self.tls_checkbox.isChecked(),
            passive_mode=self.passive_checkbox.isChecked(),
            base_path=self.path_edit.text().strip() or '/'
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
        host = self.host_edit.text().strip()
        
        if not host:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter a server address."
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
            'ftp_host': self.host_edit.text().strip(),
            'ftp_port': self.port_spin.value(),
            'ftp_base_path': self.path_edit.text().strip() or '/',
            'ftp_username': self.username_edit.text().strip() or 'anonymous',
            'ftp_password': self.password_edit.text(),  # Will be handled securely
            'ftp_use_tls': self.tls_checkbox.isChecked(),
            'ftp_passive_mode': self.passive_checkbox.isChecked(),
            'ftp_auto_connect': self.auto_connect_checkbox.isChecked()
        }
