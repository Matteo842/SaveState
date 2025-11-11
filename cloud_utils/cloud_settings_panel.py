# cloud_utils/cloud_settings_panel.py
# -*- coding: utf-8 -*-
"""
Cloud Save Settings Panel - Settings specific to Cloud Save functionality.
Shown when clicking settings button while in Cloud Save panel.
"""

import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QCheckBox, QSpinBox, QFormLayout, QGridLayout, QProgressBar
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


class StorageStatusWorker(QObject):
    """
    Background worker to fetch Google Drive storage info and
    SaveState folder size without blocking the UI thread.
    """
    finished = Signal(int, object)  # request_id, data dict

    def __init__(self, drive_manager, request_id):
        super().__init__()
        self.drive_manager = drive_manager
        self.request_id = request_id

    def run(self):
        try:
            if not self.drive_manager or not getattr(self.drive_manager, 'is_connected', False):
                self.finished.emit(self.request_id, {'connected': False})
                return

            info = self.drive_manager.get_storage_info()
            folder_bytes = int(self.drive_manager.get_app_folder_size())

            total = int(info.get('total', 0)) if isinstance(info, dict) else 0
            used = int(info.get('used', 0)) if isinstance(info, dict) else 0

            self.finished.emit(self.request_id, {
                'connected': True,
                'drive_total': total,
                'drive_used': used,
                'folder_bytes': folder_bytes,
            })
        except Exception:
            # On any error, report as not connected/available to keep UI consistent
            self.finished.emit(self.request_id, {'connected': False})


class CloudSettingsPanel(QWidget):
    """
    Settings panel specific to Cloud Save functionality.
    Contains options for sync behavior, automatic backups, etc.
    """
    
    # Signals
    settings_saved = Signal(dict)  # Emitted when settings are saved
    
    def __init__(self, parent=None):
        """
        Initialize the Cloud Settings panel.
        
        Args:
            parent: Parent widget (CloudSavePanel)
        """
        super().__init__(parent)
        self.cloud_panel = parent
        
        # Default settings
        self.settings = {
            'auto_connect_on_startup': False,  # NEW: Auto-connect to Google Drive on startup
            'auto_sync_on_startup': False,
            'auto_sync_enabled': False,
            'auto_sync_interval_hours': 12,
            'sync_all_profiles': True,
            'bandwidth_limit_enabled': False,
            'bandwidth_limit_mbps': 10,
            'show_sync_notifications': True,
            'max_cloud_backups_enabled': False,
            'max_cloud_backups_count': 5,
            'max_cloud_storage_enabled': False,
            'max_cloud_storage_gb': 5
        }
        
        self._init_ui()

        # Async storage refresh management
        self._usage_thread = None
        self._usage_worker = None
        self._usage_request_id = 0
        
    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)
        
        # --- Header ---
        header_layout = QHBoxLayout()
        title_label = QLabel("<h2>Cloud Save Settings</h2>")
        title_label.setObjectName("CloudSettingsTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        main_layout.addLayout(header_layout)
        
        # --- Description ---
        description = QLabel("Configure sync behavior, backup management, and notifications.")
        description.setWordWrap(True)
        description.setStyleSheet("color: #AAAAAA; font-size: 9pt; padding-bottom: 4px;")
        main_layout.addWidget(description)
        
        # --- Two Column Layout ---
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(10)
        
        # LEFT COLUMN
        left_column = QVBoxLayout()
        left_column.setSpacing(8)
        
        # Connection Settings (NEW)
        connection_group = QGroupBox("Connection")
        connection_layout = QVBoxLayout()
        connection_layout.setContentsMargins(8, 12, 8, 12)
        connection_layout.setSpacing(8)
        
        self.auto_connect_checkbox = QCheckBox("Auto-connect on startup")
        self.auto_connect_checkbox.setToolTip("Automatically connect to Google Drive when SaveState starts")
        self.auto_connect_checkbox.setChecked(self.settings.get('auto_connect_on_startup', False))
        connection_layout.addWidget(self.auto_connect_checkbox)
        
        connection_group.setLayout(connection_layout)
        connection_group.setMinimumHeight(70)  # Fixed height for alignment
        left_column.addWidget(connection_group)
        
        # Automatic Sync
        auto_sync_group = QGroupBox("Automatic Sync")
        auto_sync_layout = QVBoxLayout()
        auto_sync_layout.setContentsMargins(8, 12, 8, 12)
        auto_sync_layout.setSpacing(8)
        
        self.auto_sync_startup_checkbox = QCheckBox("Sync on startup")
        self.auto_sync_startup_checkbox.setToolTip("Sync all profiles when SaveState starts")
        self.auto_sync_startup_checkbox.setChecked(self.settings['auto_sync_on_startup'])
        auto_sync_layout.addWidget(self.auto_sync_startup_checkbox)
        
        self.auto_sync_enabled_checkbox = QCheckBox("Enable periodic sync")
        self.auto_sync_enabled_checkbox.setToolTip("Run background sync at regular intervals")
        self.auto_sync_enabled_checkbox.setChecked(self.settings['auto_sync_enabled'])
        self.auto_sync_enabled_checkbox.toggled.connect(self._on_auto_sync_toggled)
        auto_sync_layout.addWidget(self.auto_sync_enabled_checkbox)
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Interval:"))
        self.sync_interval_spin = QSpinBox()
        self.sync_interval_spin.setRange(1, 168)
        self.sync_interval_spin.setValue(self.settings['auto_sync_interval_hours'])
        self.sync_interval_spin.setSuffix(" hrs")
        self.sync_interval_spin.setEnabled(self.settings['auto_sync_enabled'])
        self.sync_interval_spin.setFixedWidth(110)
        interval_layout.addWidget(self.sync_interval_spin)
        interval_layout.addStretch(1)
        auto_sync_layout.addLayout(interval_layout)

        # (testing override removed)
        
        auto_sync_group.setLayout(auto_sync_layout)
        auto_sync_group.setMinimumHeight(130)  # Fixed height for alignment
        left_column.addWidget(auto_sync_group)
        
        # Profile Sync
        profile_group = QGroupBox("Profile Sync")
        profile_layout = QVBoxLayout()
        profile_layout.setContentsMargins(8, 12, 8, 12)
        profile_layout.setSpacing(8)
        
        self.sync_all_profiles_checkbox = QCheckBox("Sync all profiles")
        self.sync_all_profiles_checkbox.setToolTip("Sync all profiles automatically")
        self.sync_all_profiles_checkbox.setChecked(self.settings['sync_all_profiles'])
        profile_layout.addWidget(self.sync_all_profiles_checkbox)
        
        profile_group.setLayout(profile_layout)
        profile_group.setMinimumHeight(70)  # Fixed height for alignment
        left_column.addWidget(profile_group)
        
        # Backup Management
        backup_group = QGroupBox("Backup Management")
        backup_layout = QVBoxLayout()
        backup_layout.setContentsMargins(8, 12, 8, 12)
        backup_layout.setSpacing(8)
        
        self.max_backups_checkbox = QCheckBox("Limit backups per profile")
        self.max_backups_checkbox.setChecked(self.settings['max_cloud_backups_enabled'])
        self.max_backups_checkbox.toggled.connect(self._on_max_backups_toggled)
        self.max_backups_checkbox.setToolTip("Delete oldest backups when limit reached")
        backup_layout.addWidget(self.max_backups_checkbox)
        
        count_layout = QHBoxLayout()
        count_layout.addSpacing(20)
        self.max_backups_label = QLabel("Keep:")
        self.max_backups_label.setEnabled(self.settings['max_cloud_backups_enabled'])
        count_layout.addWidget(self.max_backups_label)
        self.max_backups_spin = QSpinBox()
        self.max_backups_spin.setRange(1, 100)
        self.max_backups_spin.setValue(self.settings['max_cloud_backups_count'])
        self.max_backups_spin.setSuffix(" backups")
        self.max_backups_spin.setFixedWidth(130)
        self.max_backups_spin.setEnabled(self.settings['max_cloud_backups_enabled'])
        count_layout.addWidget(self.max_backups_spin)
        count_layout.addStretch(1)
        backup_layout.addLayout(count_layout)
        
        backup_group.setLayout(backup_layout)
        backup_group.setMinimumHeight(100)  # Fixed height for alignment
        left_column.addWidget(backup_group)
        
        left_column.addStretch(1)
        columns_layout.addLayout(left_column, 1)
        
        # RIGHT COLUMN
        right_column = QVBoxLayout()
        right_column.setSpacing(8)
        
        # Storage Status (separate panel)
        status_group = QGroupBox("Storage Status")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(8, 12, 8, 12)
        status_layout.setSpacing(8)

        # Google Drive overall usage
        drive_row = QHBoxLayout()
        drive_row.addWidget(QLabel("Google Drive:"))
        self.drive_usage_bar = QProgressBar()
        self.drive_usage_bar.setRange(0, 100)
        self.drive_usage_bar.setValue(0)
        self.drive_usage_bar.setFormat("Not connected")
        self.drive_usage_bar.setTextVisible(True)
        self.drive_usage_bar.setFixedWidth(220)
        drive_row.addWidget(self.drive_usage_bar)
        drive_row.addStretch(1)
        status_layout.addLayout(drive_row)
        
        # SaveState app folder usage in cloud
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("SaveState (cloud):"))
        self.savestate_usage_bar = QProgressBar()
        self.savestate_usage_bar.setRange(0, 100)
        self.savestate_usage_bar.setValue(0)
        self.savestate_usage_bar.setFormat("Not connected")
        self.savestate_usage_bar.setTextVisible(True)
        self.savestate_usage_bar.setFixedWidth(220)
        folder_row.addWidget(self.savestate_usage_bar)
        folder_row.addStretch(1)
        status_layout.addLayout(folder_row)
        
        # Label used when there is no limit (bar hidden) - placed on same row
        self.savestate_unlimited_label = QLabel("")
        self.savestate_unlimited_label.setStyleSheet("color: #AAAAAA;")
        self.savestate_unlimited_label.setVisible(False)
        folder_row.addWidget(self.savestate_unlimited_label)

        status_group.setLayout(status_layout)
        status_group.setMinimumHeight(100)
        right_column.addWidget(status_group)

        # Advanced Settings
        advanced_group = QGroupBox("Advanced")
        advanced_layout = QVBoxLayout()
        advanced_layout.setContentsMargins(8, 12, 8, 12)
        advanced_layout.setSpacing(8)
        
        # Bandwidth (compact single row: checkbox + spinner)
        bandwidth_row = QHBoxLayout()
        bandwidth_row.setContentsMargins(0, 0, 0, 0)
        bandwidth_row.setSpacing(12)
        self.bandwidth_limit_checkbox = QCheckBox("Limit bandwidth")
        self.bandwidth_limit_checkbox.setChecked(self.settings['bandwidth_limit_enabled'])
        self.bandwidth_limit_checkbox.toggled.connect(self._on_bandwidth_limit_toggled)
        self.bandwidth_limit_checkbox.setToolTip("Limit upload/download speed")
        bandwidth_row.addWidget(self.bandwidth_limit_checkbox)
        self.bandwidth_limit_spin = QSpinBox()
        self.bandwidth_limit_spin.setRange(1, 1000)
        self.bandwidth_limit_spin.setValue(self.settings['bandwidth_limit_mbps'])
        self.bandwidth_limit_spin.setSuffix(" Mbps")
        self.bandwidth_limit_spin.setFixedWidth(120)
        self.bandwidth_limit_spin.setEnabled(self.settings['bandwidth_limit_enabled'])
        bandwidth_row.addWidget(self.bandwidth_limit_spin)
        bandwidth_row.addStretch(1)
        advanced_layout.addLayout(bandwidth_row)
        
        advanced_group.setLayout(advanced_layout)
        advanced_group.setMinimumHeight(90)  # Reduced height for compact layout
        right_column.addWidget(advanced_group)
        
        # Storage Limit
        storage_group = QGroupBox("Storage Limit")
        storage_layout = QVBoxLayout()
        storage_layout.setContentsMargins(8, 12, 8, 12)
        storage_layout.setSpacing(8)
        
        self.max_storage_checkbox = QCheckBox("Limit total cloud storage")
        self.max_storage_checkbox.setChecked(self.settings['max_cloud_storage_enabled'])
        self.max_storage_checkbox.toggled.connect(self._on_max_storage_toggled)
        self.max_storage_checkbox.setToolTip("Stop uploading when limit is reached")
        storage_layout.addWidget(self.max_storage_checkbox)
        
        storage_limit_layout = QHBoxLayout()
        storage_limit_layout.addSpacing(20)
        self.max_storage_label = QLabel("Max:")
        self.max_storage_label.setEnabled(self.settings['max_cloud_storage_enabled'])
        storage_limit_layout.addWidget(self.max_storage_label)
        self.max_storage_spin = QSpinBox()
        self.max_storage_spin.setRange(1, 1000)
        self.max_storage_spin.setValue(self.settings['max_cloud_storage_gb'])
        self.max_storage_spin.setSuffix(" GB")
        self.max_storage_spin.setFixedWidth(120)
        self.max_storage_spin.setEnabled(self.settings['max_cloud_storage_enabled'])
        storage_limit_layout.addWidget(self.max_storage_spin)
        storage_limit_layout.addStretch(1)
        storage_layout.addLayout(storage_limit_layout)
        
        storage_group.setLayout(storage_layout)
        storage_group.setMinimumHeight(100)  # Fixed height for alignment
        right_column.addWidget(storage_group)
        
        # Notifications
        notif_group = QGroupBox("Notifications")
        notif_layout = QVBoxLayout()
        notif_layout.setContentsMargins(8, 12, 8, 12)
        notif_layout.setSpacing(8)
        
        self.show_notifications_checkbox = QCheckBox("Show sync notifications")
        self.show_notifications_checkbox.setChecked(self.settings['show_sync_notifications'])
        self.show_notifications_checkbox.setToolTip("Show notifications when sync completes")
        notif_layout.addWidget(self.show_notifications_checkbox)
        
        notif_group.setLayout(notif_layout)
        notif_group.setMinimumHeight(70)  # Fixed height for alignment
        right_column.addWidget(notif_group)
        
        right_column.addStretch(1)
        columns_layout.addLayout(right_column, 1)
        
        main_layout.addLayout(columns_layout)
        
        # --- Action Buttons ---
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        buttons_layout.addWidget(self.cancel_button)
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(self.save_button)
        
        main_layout.addLayout(buttons_layout)
    
    def _on_auto_sync_toggled(self, checked):
        """Enable/disable sync interval spin box based on auto sync checkbox."""
        self.sync_interval_spin.setEnabled(checked)
    
    def _on_bandwidth_limit_toggled(self, checked):
        """Enable/disable bandwidth limit spin box based on checkbox."""
        self.bandwidth_limit_spin.setEnabled(checked)
    
    def _on_max_backups_toggled(self, checked):
        """Enable/disable max backups spin box based on checkbox."""
        self.max_backups_spin.setEnabled(checked)
        self.max_backups_label.setEnabled(checked)
    
    def _on_max_storage_toggled(self, checked):
        """Enable/disable max storage spin box based on checkbox."""
        self.max_storage_spin.setEnabled(checked)
        self.max_storage_label.setEnabled(checked)
        # Also refresh usage UI to reflect limit visibility/state
        try:
            self.refresh_storage_status()
        except Exception:
            pass
    
    def _on_save_clicked(self):
        """Save settings and return to cloud panel."""
        # Collect settings
        self.settings['auto_connect_on_startup'] = self.auto_connect_checkbox.isChecked()
        self.settings['auto_sync_on_startup'] = self.auto_sync_startup_checkbox.isChecked()
        self.settings['auto_sync_enabled'] = self.auto_sync_enabled_checkbox.isChecked()
        self.settings['auto_sync_interval_hours'] = self.sync_interval_spin.value()
        self.settings['sync_all_profiles'] = self.sync_all_profiles_checkbox.isChecked()
        
        self.settings['bandwidth_limit_enabled'] = self.bandwidth_limit_checkbox.isChecked()
        self.settings['bandwidth_limit_mbps'] = self.bandwidth_limit_spin.value()
        
        self.settings['show_sync_notifications'] = self.show_notifications_checkbox.isChecked()
        self.settings['max_cloud_backups_enabled'] = self.max_backups_checkbox.isChecked()
        self.settings['max_cloud_backups_count'] = self.max_backups_spin.value()
        self.settings['max_cloud_storage_enabled'] = self.max_storage_checkbox.isChecked()
        self.settings['max_cloud_storage_gb'] = self.max_storage_spin.value()
        
        # Emit signal
        self.settings_saved.emit(self.settings)
        
        # Return to cloud panel
        if self.cloud_panel and hasattr(self.cloud_panel, 'exit_cloud_settings'):
            self.cloud_panel.exit_cloud_settings()
    
    def _on_cancel_clicked(self):
        """Cancel and return to cloud panel without saving."""
        logging.debug("Cloud settings cancelled")
        
        # Return to cloud panel
        if self.cloud_panel and hasattr(self.cloud_panel, 'exit_cloud_settings'):
            self.cloud_panel.exit_cloud_settings()
    
    def get_settings(self):
        """Get current settings dictionary."""
        return self.settings.copy()
    
    def load_settings(self, settings_dict):
        """Load settings from dictionary and update UI."""
        if not settings_dict:
            return
        
        self.settings.update(settings_dict)
        
        # Update UI elements
        self.auto_connect_checkbox.setChecked(self.settings.get('auto_connect_on_startup', False))
        self.auto_sync_startup_checkbox.setChecked(self.settings.get('auto_sync_on_startup', False))
        self.auto_sync_enabled_checkbox.setChecked(self.settings.get('auto_sync_enabled', False))
        self.sync_interval_spin.setValue(self.settings.get('auto_sync_interval_hours', 12))
        self.sync_all_profiles_checkbox.setChecked(self.settings.get('sync_all_profiles', True))
        
        self.bandwidth_limit_checkbox.setChecked(self.settings.get('bandwidth_limit_enabled', False))
        self.bandwidth_limit_spin.setValue(self.settings.get('bandwidth_limit_mbps', 10))
        
        self.show_notifications_checkbox.setChecked(self.settings.get('show_sync_notifications', True))
        self.max_backups_checkbox.setChecked(self.settings.get('max_cloud_backups_enabled', False))
        self.max_backups_spin.setValue(self.settings.get('max_cloud_backups_count', 5))
        self.max_storage_checkbox.setChecked(self.settings.get('max_cloud_storage_enabled', False))
        self.max_storage_spin.setValue(self.settings.get('max_cloud_storage_gb', 5))
        
        # Update usage bars when loading settings
        try:
            self.refresh_storage_status()
        except Exception:
            pass

    # -------- Storage usage helpers --------
    def _format_bytes(self, num_bytes: int) -> str:
        """Return human-readable size (GB/TB with one decimal when useful)."""
        try:
            if not isinstance(num_bytes, (int, float)):
                return "0 B"
            tb = 1024 ** 4
            gb = 1024 ** 3
            if num_bytes >= tb:
                val = num_bytes / tb
                return f"{val:.1f} TB" if val < 10 else f"{int(val)} TB"
            else:
                val = num_bytes / gb
                return f"{val:.1f} GB" if val < 10 else f"{int(val)} GB"
        except Exception:
            return "0 B"

    def refresh_storage_status(self):
        """Refresh storage usage in background to avoid UI stalls."""
        # Set immediate placeholder state
        self.drive_usage_bar.setFormat("Loading...")
        self.savestate_usage_bar.setFormat("Loading...")
        self.savestate_unlimited_label.setVisible(False)
        self.savestate_usage_bar.setVisible(True)

        # Obtain drive manager via parent
        drive_manager = None
        try:
            if self.cloud_panel and hasattr(self.cloud_panel, 'drive_manager'):
                drive_manager = self.cloud_panel.drive_manager
        except Exception:
            drive_manager = None

        if not drive_manager or not getattr(drive_manager, 'is_connected', False):
            # Not connected: set steady state and exit
            self.drive_usage_bar.setFormat("Not connected")
            self.drive_usage_bar.setValue(0)
            self.savestate_usage_bar.setFormat("Not connected")
            self.savestate_usage_bar.setValue(0)
            return

        # Start/queue a background worker; ignore older results via request_id
        self._usage_request_id += 1
        req_id = self._usage_request_id

        # Fire worker
        try:
            self._usage_thread = QThread(self)
            self._usage_worker = StorageStatusWorker(drive_manager, req_id)
            self._usage_worker.moveToThread(self._usage_thread)
            self._usage_thread.started.connect(self._usage_worker.run)
            self._usage_worker.finished.connect(self._on_storage_status_ready)
            self._usage_worker.finished.connect(self._usage_thread.quit)
            self._usage_worker.finished.connect(self._usage_worker.deleteLater)
            self._usage_thread.finished.connect(self._usage_thread.deleteLater)
            self._usage_thread.start()
        except Exception:
            # Fallback: show error-like state
            self.drive_usage_bar.setFormat("Error")
            self.savestate_usage_bar.setFormat("Error")

    def _on_storage_status_ready(self, request_id: int, data: object):
        """Apply storage status once background worker finishes."""
        if request_id != self._usage_request_id:
            # Outdated result; ignore
            return

        try:
            info = data if isinstance(data, dict) else {}
            if not info.get('connected'):
                self.drive_usage_bar.setFormat("Not connected")
                self.drive_usage_bar.setValue(0)
                self.savestate_usage_bar.setFormat("Not connected")
                self.savestate_usage_bar.setValue(0)
                return

            # Drive overall
            total = int(info.get('drive_total', 0))
            used = int(info.get('drive_used', 0))
            if total > 0:
                pct = max(0, min(100, int((used / total) * 100)))
                self.drive_usage_bar.setValue(pct)
                self.drive_usage_bar.setFormat(f"{self._format_bytes(used)} / {self._format_bytes(total)}")
            else:
                self.drive_usage_bar.setValue(0)
                self.drive_usage_bar.setFormat("Unavailable")

            # SaveState folder
            folder_bytes = int(info.get('folder_bytes', 0))
            limit_enabled = bool(self.max_storage_checkbox.isChecked())
            if limit_enabled:
                try:
                    max_gb = int(self.max_storage_spin.value())
                    denom = max_gb * (1024 ** 3)
                    if denom > 0:
                        pct = max(0, min(100, int((folder_bytes / denom) * 100)))
                        self.savestate_usage_bar.setVisible(True)
                        self.savestate_unlimited_label.setVisible(False)
                        self.savestate_usage_bar.setValue(pct)
                        self.savestate_usage_bar.setFormat(f"{self._format_bytes(folder_bytes)} / {max_gb} GB")
                    else:
                        self.savestate_usage_bar.setVisible(True)
                        self.savestate_unlimited_label.setVisible(False)
                        self.savestate_usage_bar.setValue(0)
                        self.savestate_usage_bar.setFormat(self._format_bytes(folder_bytes))
                except Exception:
                    self.savestate_usage_bar.setVisible(True)
                    self.savestate_unlimited_label.setVisible(False)
                    self.savestate_usage_bar.setFormat(self._format_bytes(folder_bytes))
            else:
                self.savestate_usage_bar.setVisible(False)
                self.savestate_unlimited_label.setVisible(True)
                self.savestate_unlimited_label.setText(f"{self._format_bytes(folder_bytes)} (no limit)")
        except Exception:
            self.drive_usage_bar.setFormat("Error")
            self.savestate_usage_bar.setFormat("Error")
