# cloud_utils/cloud_settings_panel.py
# -*- coding: utf-8 -*-
"""
Cloud Save Settings Panel - Settings specific to Cloud Save functionality.
Shown when clicking settings button while in Cloud Save panel.
"""

import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QFormLayout, QGridLayout
)
from PySide6.QtCore import Qt, Signal


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
            'auto_sync_on_startup': False,
            'auto_sync_enabled': False,
            'auto_sync_interval_hours': 12,
            'sync_all_profiles': True,
            'compression_level': 'standard',
            'bandwidth_limit_enabled': False,
            'bandwidth_limit_mbps': 10,
            'show_sync_notifications': True,
            'max_cloud_backups_enabled': False,
            'max_cloud_backups_count': 5,
            'max_cloud_storage_enabled': False,
            'max_cloud_storage_gb': 5
        }
        
        self._init_ui()
        
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
        
        # Automatic Sync
        auto_sync_group = QGroupBox("Automatic Sync")
        auto_sync_layout = QVBoxLayout()
        auto_sync_layout.setContentsMargins(8, 8, 8, 8)
        auto_sync_layout.setSpacing(6)
        
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
        self.sync_interval_spin.setMaximumWidth(110)
        interval_layout.addWidget(self.sync_interval_spin)
        interval_layout.addStretch(1)
        auto_sync_layout.addLayout(interval_layout)
        
        auto_sync_group.setLayout(auto_sync_layout)
        left_column.addWidget(auto_sync_group)
        
        # Profile Sync
        profile_group = QGroupBox("Profile Sync")
        profile_layout = QVBoxLayout()
        profile_layout.setContentsMargins(8, 8, 8, 8)
        profile_layout.setSpacing(6)
        
        self.sync_all_profiles_checkbox = QCheckBox("Sync all profiles")
        self.sync_all_profiles_checkbox.setToolTip("Sync all profiles automatically")
        self.sync_all_profiles_checkbox.setChecked(self.settings['sync_all_profiles'])
        profile_layout.addWidget(self.sync_all_profiles_checkbox)
        
        profile_group.setLayout(profile_layout)
        left_column.addWidget(profile_group)
        
        # Backup Management
        backup_group = QGroupBox("Backup Management")
        backup_layout = QVBoxLayout()
        backup_layout.setContentsMargins(8, 8, 8, 8)
        backup_layout.setSpacing(6)
        
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
        self.max_backups_spin.setMaximumWidth(130)
        self.max_backups_spin.setEnabled(self.settings['max_cloud_backups_enabled'])
        count_layout.addWidget(self.max_backups_spin)
        count_layout.addStretch(1)
        backup_layout.addLayout(count_layout)
        
        backup_group.setLayout(backup_layout)
        left_column.addWidget(backup_group)
        
        left_column.addStretch(1)
        columns_layout.addLayout(left_column, 1)
        
        # RIGHT COLUMN
        right_column = QVBoxLayout()
        right_column.setSpacing(8)
        
        # Advanced Settings
        advanced_group = QGroupBox("Advanced")
        advanced_layout = QVBoxLayout()
        advanced_layout.setContentsMargins(8, 8, 8, 8)
        advanced_layout.setSpacing(6)
        
        # Compression
        comp_layout = QHBoxLayout()
        comp_layout.addWidget(QLabel("Compression:"))
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["Standard", "Maximum", "None"])
        compression_map = {'standard': 0, 'maximum': 1, 'stored': 2}
        self.compression_combo.setCurrentIndex(compression_map.get(self.settings['compression_level'], 0))
        self.compression_combo.setToolTip("Upload compression level")
        self.compression_combo.setMaximumWidth(130)
        comp_layout.addWidget(self.compression_combo)
        comp_layout.addStretch(1)
        advanced_layout.addLayout(comp_layout)
        
        # Bandwidth
        self.bandwidth_limit_checkbox = QCheckBox("Limit bandwidth")
        self.bandwidth_limit_checkbox.setChecked(self.settings['bandwidth_limit_enabled'])
        self.bandwidth_limit_checkbox.toggled.connect(self._on_bandwidth_limit_toggled)
        self.bandwidth_limit_checkbox.setToolTip("Limit upload/download speed")
        advanced_layout.addWidget(self.bandwidth_limit_checkbox)
        
        bw_layout = QHBoxLayout()
        bw_layout.addSpacing(20)
        bw_layout.addWidget(QLabel("Speed:"))
        self.bandwidth_limit_spin = QSpinBox()
        self.bandwidth_limit_spin.setRange(1, 1000)
        self.bandwidth_limit_spin.setValue(self.settings['bandwidth_limit_mbps'])
        self.bandwidth_limit_spin.setSuffix(" Mbps")
        self.bandwidth_limit_spin.setMaximumWidth(120)
        self.bandwidth_limit_spin.setEnabled(self.settings['bandwidth_limit_enabled'])
        bw_layout.addWidget(self.bandwidth_limit_spin)
        bw_layout.addStretch(1)
        advanced_layout.addLayout(bw_layout)
        
        advanced_group.setLayout(advanced_layout)
        right_column.addWidget(advanced_group)
        
        # Storage Limit
        storage_group = QGroupBox("Storage Limit")
        storage_layout = QVBoxLayout()
        storage_layout.setContentsMargins(8, 8, 8, 8)
        storage_layout.setSpacing(6)
        
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
        self.max_storage_spin.setMaximumWidth(120)
        self.max_storage_spin.setEnabled(self.settings['max_cloud_storage_enabled'])
        storage_limit_layout.addWidget(self.max_storage_spin)
        storage_limit_layout.addStretch(1)
        storage_layout.addLayout(storage_limit_layout)
        
        storage_group.setLayout(storage_layout)
        right_column.addWidget(storage_group)
        
        # Notifications
        notif_group = QGroupBox("Notifications")
        notif_layout = QVBoxLayout()
        notif_layout.setContentsMargins(8, 8, 8, 8)
        notif_layout.setSpacing(6)
        
        self.show_notifications_checkbox = QCheckBox("Show sync notifications")
        self.show_notifications_checkbox.setChecked(self.settings['show_sync_notifications'])
        self.show_notifications_checkbox.setToolTip("Show notifications when sync completes")
        notif_layout.addWidget(self.show_notifications_checkbox)
        
        notif_group.setLayout(notif_layout)
        right_column.addWidget(notif_group)
        
        right_column.addStretch(1)
        columns_layout.addLayout(right_column, 1)
        
        main_layout.addLayout(columns_layout)
        
        # --- Info Note ---
        info_note = QLabel("💡 Settings are saved automatically and take effect immediately.")
        info_note.setWordWrap(True)
        info_note.setStyleSheet(
            "background-color: rgba(76, 175, 80, 0.1); "
            "border: 1px solid rgba(76, 175, 80, 0.3); "
            "border-radius: 4px; "
            "padding: 8px; "
            "color: #4CAF50; "
            "font-size: 9pt;"
        )
        main_layout.addWidget(info_note)
        
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
    
    def _on_save_clicked(self):
        """Save settings and return to cloud panel."""
        # Collect settings
        self.settings['auto_sync_on_startup'] = self.auto_sync_startup_checkbox.isChecked()
        self.settings['auto_sync_enabled'] = self.auto_sync_enabled_checkbox.isChecked()
        self.settings['auto_sync_interval_hours'] = self.sync_interval_spin.value()
        self.settings['sync_all_profiles'] = self.sync_all_profiles_checkbox.isChecked()
        
        compression_map = {0: 'standard', 1: 'maximum', 2: 'stored'}
        self.settings['compression_level'] = compression_map.get(self.compression_combo.currentIndex(), 'standard')
        
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
        self.auto_sync_startup_checkbox.setChecked(self.settings.get('auto_sync_on_startup', False))
        self.auto_sync_enabled_checkbox.setChecked(self.settings.get('auto_sync_enabled', False))
        self.sync_interval_spin.setValue(self.settings.get('auto_sync_interval_hours', 12))
        self.sync_all_profiles_checkbox.setChecked(self.settings.get('sync_all_profiles', True))
        
        compression_map = {'standard': 0, 'maximum': 1, 'stored': 2}
        self.compression_combo.setCurrentIndex(compression_map.get(self.settings.get('compression_level', 'standard'), 0))
        
        self.bandwidth_limit_checkbox.setChecked(self.settings.get('bandwidth_limit_enabled', False))
        self.bandwidth_limit_spin.setValue(self.settings.get('bandwidth_limit_mbps', 10))
        
        self.show_notifications_checkbox.setChecked(self.settings.get('show_sync_notifications', True))
        self.max_backups_checkbox.setChecked(self.settings.get('max_cloud_backups_enabled', False))
        self.max_backups_spin.setValue(self.settings.get('max_cloud_backups_count', 5))
        self.max_storage_checkbox.setChecked(self.settings.get('max_cloud_storage_enabled', False))
        self.max_storage_spin.setValue(self.settings.get('max_cloud_storage_gb', 5))
