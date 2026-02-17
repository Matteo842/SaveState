# cloud_utils/git_config_dialog.py
# -*- coding: utf-8 -*-
"""
Git Configuration Dialog - UI for configuring Git repository settings.
"""

import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QFileDialog, QGroupBox, QFormLayout,
    QMessageBox, QFrame
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


class GitConnectionTestWorker(QObject):
    """Worker thread for testing Git connection."""
    finished = Signal(dict)
    
    def __init__(self, repo_path, remote_url, branch, auto_push, auto_pull):
        super().__init__()
        self.repo_path = repo_path
        self.remote_url = remote_url
        self.branch = branch
        self.auto_push = auto_push
        self.auto_pull = auto_pull
    
    def run(self):
        """Test the connection in background."""
        try:
            from cloud_utils.git_provider import GitProvider
            
            provider = GitProvider()
            success = provider.connect(
                repo_path=self.repo_path,
                remote_url=self.remote_url or None,
                branch=self.branch,
                auto_push=self.auto_push,
                auto_pull=self.auto_pull
            )
            
            if success:
                result = provider.test_connection()
                provider.disconnect()
                self.finished.emit(result)
            else:
                self.finished.emit({
                    'success': False,
                    'message': 'Failed to connect to repository',
                    'details': None
                })
                
        except Exception as e:
            logging.error(f"Git connection test error: {e}")
            self.finished.emit({
                'success': False,
                'message': str(e),
                'details': None
            })


class GitConfigDialog(QDialog):
    """
    Dialog for configuring Git repository settings.
    
    Allows user to:
    - Select or create repository path
    - Specify remote URL for push/pull
    - Configure branch and auto-sync options
    """
    
    config_saved = Signal(dict)
    
    def __init__(self, parent=None, current_config: dict = None):
        super().__init__(parent)
        
        self.current_config = current_config or {}
        self.test_thread = None
        self.test_worker = None
        
        self.setWindowTitle("Git Repository Configuration")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self._init_ui()
        self._apply_styles()
        self._load_current_config()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Repository settings
        repo_group = QGroupBox("Repository")
        repo_layout = QFormLayout()
        
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("C:\\path\\to\\savestate-backups.git")
        path_row.addWidget(self.path_edit)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        repo_layout.addRow("Repository Path:", path_row)
        
        path_help = QLabel("Local folder for the Git repo. Created if it doesn't exist.")
        path_help.setWordWrap(True)
        path_help.setStyleSheet("color: #888888; font-size: 11px;")
        repo_layout.addRow("", path_help)
        
        self.branch_edit = QLineEdit()
        self.branch_edit.setPlaceholderText("main")
        self.branch_edit.setMaxLength(256)
        repo_layout.addRow("Branch:", self.branch_edit)
        
        repo_group.setLayout(repo_layout)
        layout.addWidget(repo_group)
        
        # Remote settings
        remote_group = QGroupBox("Remote (Optional)")
        remote_layout = QFormLayout()
        
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("https://github.com/user/repo.git or git@github.com:user/repo.git")
        remote_layout.addRow("Remote URL:", self.remote_edit)
        
        remote_help = QLabel("GitHub, GitLab, Bitbucket, or any Git server. Leave empty for local-only.")
        remote_help.setWordWrap(True)
        remote_help.setStyleSheet("color: #888888; font-size: 11px;")
        remote_layout.addRow("", remote_help)
        
        remote_group.setLayout(remote_layout)
        layout.addWidget(remote_group)
        
        # Options
        options_group = QGroupBox("Sync Options")
        options_layout = QVBoxLayout()
        
        self.auto_push_checkbox = QCheckBox("Auto-push after upload")
        self.auto_push_checkbox.setChecked(True)
        self.auto_push_checkbox.setToolTip("Push to remote after each upload")
        options_layout.addWidget(self.auto_push_checkbox)
        
        self.auto_pull_checkbox = QCheckBox("Auto-pull before operations")
        self.auto_pull_checkbox.setChecked(True)
        self.auto_pull_checkbox.setToolTip("Pull from remote before upload/download")
        options_layout.addWidget(self.auto_pull_checkbox)
        
        self.auto_connect_checkbox = QCheckBox("Auto-connect on startup")
        self.auto_connect_checkbox.setToolTip("Connect to this repo when SaveState starts")
        options_layout.addWidget(self.auto_connect_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # Test connection
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
        
        # Buttons
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
            QLineEdit {
                background-color: #3E3E42;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
                color: #E0E0E0;
            }
            QLineEdit:focus {
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
    
    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select or Create Repository Folder",
            self.path_edit.text() or os.path.expanduser("~")
        )
        if path:
            self.path_edit.setText(path)
    
    def _load_current_config(self):
        if not self.current_config:
            return
        self.path_edit.setText(self.current_config.get('git_repo_path', ''))
        self.branch_edit.setText(self.current_config.get('git_branch', 'main'))
        self.remote_edit.setText(self.current_config.get('git_remote_url', ''))
        self.auto_push_checkbox.setChecked(self.current_config.get('git_auto_push', True))
        self.auto_pull_checkbox.setChecked(self.current_config.get('git_auto_pull', True))
        self.auto_connect_checkbox.setChecked(self.current_config.get('git_auto_connect', False))
    
    def _on_test_clicked(self):
        repo_path = self.path_edit.text().strip()
        if not repo_path:
            QMessageBox.warning(
                self, "Missing Information",
                "Please enter a repository path."
            )
            return
        
        self.test_status_label.setText("Testing connection...")
        self.test_status_label.setStyleSheet("color: #AAAAAA;")
        self.test_button.setEnabled(False)
        
        self.test_thread = QThread()
        self.test_worker = GitConnectionTestWorker(
            repo_path=repo_path,
            remote_url=self.remote_edit.text().strip() or None,
            branch=self.branch_edit.text().strip() or "main",
            auto_push=self.auto_push_checkbox.isChecked(),
            auto_pull=self.auto_pull_checkbox.isChecked()
        )
        self.test_worker.moveToThread(self.test_thread)
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self._on_test_finished)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_thread.start()
    
    def _on_test_finished(self, result: dict):
        self.test_button.setEnabled(True)
        if result.get('success'):
            self.test_status_label.setText("✓ Connection successful!")
            self.test_status_label.setStyleSheet("color: #55FF55;")
        else:
            msg = result.get('message', 'Connection failed')
            self.test_status_label.setText(f"✗ {msg}")
            self.test_status_label.setStyleSheet("color: #FF5555;")
    
    def _on_save_clicked(self):
        repo_path = self.path_edit.text().strip()
        if not repo_path:
            QMessageBox.warning(
                self, "Missing Information",
                "Please enter a repository path."
            )
            return
        
        config = self.get_config()
        self.config_saved.emit(config)
        self.accept()
    
    def closeEvent(self, event):
        """Clean up test thread if still running when dialog is closed."""
        if self.test_thread and self.test_thread.isRunning():
            self.test_thread.quit()
            self.test_thread.wait(2000)  # Wait up to 2 seconds
        super().closeEvent(event)
    
    def get_config(self) -> dict:
        return {
            'git_repo_path': self.path_edit.text().strip(),
            'git_branch': self.branch_edit.text().strip() or 'main',
            'git_remote_url': self.remote_edit.text().strip(),
            'git_auto_push': self.auto_push_checkbox.isChecked(),
            'git_auto_pull': self.auto_pull_checkbox.isChecked(),
            'git_auto_connect': self.auto_connect_checkbox.isChecked()
        }
