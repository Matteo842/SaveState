# cloud_utils/cloud_settings_panel.py
# -*- coding: utf-8 -*-
"""
Cloud Save Settings Panel - Settings specific to Cloud Save functionality.
Shown when clicking settings button while in Cloud Save panel.
"""

import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QFormLayout
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
        
        # Default settings (placeholders for now)
        self.settings = {
            'auto_sync_on_startup': False,
            'auto_sync_enabled': False,
            'auto_sync_interval_hours': 12,
            'sync_all_profiles': True,
            'compression_level': 'standard',
            'bandwidth_limit_enabled': False,
            'bandwidth_limit_mbps': 10
        }
        
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        
        # --- Header ---
        header_layout = QHBoxLayout()
        
        title_label = QLabel("<h2>Cloud Save Settings</h2>")
        title_label.setObjectName("CloudSettingsTitle")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch(1)
        
        main_layout.addLayout(header_layout)
        
        # --- Description ---
        description = QLabel(
            "Configure how SaveState synchronizes your backups with Google Drive. "
            "These settings will be available in version 2.0."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #AAAAAA; font-size: 10pt;")
        main_layout.addWidget(description)
        
        # --- Automatic Sync Settings ---
        auto_sync_group = QGroupBox("Automatic Synchronization")
        auto_sync_layout = QVBoxLayout()
        auto_sync_layout.setContentsMargins(8, 8, 8, 8)
        auto_sync_layout.setSpacing(8)
        
        # Auto sync on startup
        self.auto_sync_startup_checkbox = QCheckBox("Sync all profiles on application startup")
        self.auto_sync_startup_checkbox.setToolTip(
            "When enabled, automatically syncs all enabled profiles with Google Drive when SaveState starts"
        )
        self.auto_sync_startup_checkbox.setChecked(self.settings['auto_sync_on_startup'])
        auto_sync_layout.addWidget(self.auto_sync_startup_checkbox)
        
        # Periodic auto sync
        self.auto_sync_enabled_checkbox = QCheckBox("Enable periodic automatic sync")
        self.auto_sync_enabled_checkbox.setToolTip(
            "When enabled, runs background sync at regular intervals"
        )
        self.auto_sync_enabled_checkbox.setChecked(self.settings['auto_sync_enabled'])
        self.auto_sync_enabled_checkbox.toggled.connect(self._on_auto_sync_toggled)
        auto_sync_layout.addWidget(self.auto_sync_enabled_checkbox)
        
        # Sync interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Sync interval:"))
        
        self.sync_interval_spin = QSpinBox()
        self.sync_interval_spin.setRange(1, 168)  # 1 hour to 1 week
        self.sync_interval_spin.setValue(self.settings['auto_sync_interval_hours'])
        self.sync_interval_spin.setSuffix(" hours")
        self.sync_interval_spin.setEnabled(self.settings['auto_sync_enabled'])
        interval_layout.addWidget(self.sync_interval_spin)
        
        interval_layout.addStretch(1)
        auto_sync_layout.addLayout(interval_layout)
        
        auto_sync_group.setLayout(auto_sync_layout)
        main_layout.addWidget(auto_sync_group)
        
        # --- Profile Selection ---
        profile_sync_group = QGroupBox("Profile Synchronization")
        profile_sync_layout = QVBoxLayout()
        profile_sync_layout.setContentsMargins(8, 8, 8, 8)
        profile_sync_layout.setSpacing(8)
        
        self.sync_all_profiles_checkbox = QCheckBox("Sync all profiles automatically")
        self.sync_all_profiles_checkbox.setToolTip(
            "When enabled, all profiles will be synced. When disabled, you can choose which profiles to sync manually."
        )
        self.sync_all_profiles_checkbox.setChecked(self.settings['sync_all_profiles'])
        profile_sync_layout.addWidget(self.sync_all_profiles_checkbox)
        
        # Note about manual selection
        manual_note = QLabel("Note: Manual profile selection will be available in the main Cloud Save panel")
        manual_note.setStyleSheet("color: #888888; font-size: 9pt; font-style: italic;")
        manual_note.setWordWrap(True)
        profile_sync_layout.addWidget(manual_note)
        
        profile_sync_group.setLayout(profile_sync_layout)
        main_layout.addWidget(profile_sync_group)
        
        # --- Advanced Settings ---
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QFormLayout()
        advanced_layout.setContentsMargins(8, 8, 8, 8)
        advanced_layout.setSpacing(8)
        
        # Compression level
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["Standard", "Maximum", "None (Faster)"])
        compression_map = {'standard': 0, 'maximum': 1, 'stored': 2}
        self.compression_combo.setCurrentIndex(compression_map.get(self.settings['compression_level'], 0))
        self.compression_combo.setToolTip("Compression level for cloud uploads (affects upload time and storage)")
        advanced_layout.addRow("Cloud upload compression:", self.compression_combo)
        
        # Bandwidth limit
        bandwidth_layout = QHBoxLayout()
        self.bandwidth_limit_checkbox = QCheckBox("Limit bandwidth")
        self.bandwidth_limit_checkbox.setChecked(self.settings['bandwidth_limit_enabled'])
        self.bandwidth_limit_checkbox.toggled.connect(self._on_bandwidth_limit_toggled)
        bandwidth_layout.addWidget(self.bandwidth_limit_checkbox)
        
        self.bandwidth_limit_spin = QSpinBox()
        self.bandwidth_limit_spin.setRange(1, 1000)
        self.bandwidth_limit_spin.setValue(self.settings['bandwidth_limit_mbps'])
        self.bandwidth_limit_spin.setSuffix(" Mbps")
        self.bandwidth_limit_spin.setEnabled(self.settings['bandwidth_limit_enabled'])
        bandwidth_layout.addWidget(self.bandwidth_limit_spin)
        
        bandwidth_layout.addStretch(1)
        advanced_layout.addRow("Upload/Download speed:", bandwidth_layout)
        
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)
        
        # --- Placeholder Info ---
        placeholder_info = QLabel(
            "⚠️ These settings are placeholders and will be fully functional in version 2.0 "
            "when Google Drive integration is implemented."
        )
        placeholder_info.setWordWrap(True)
        placeholder_info.setStyleSheet(
            "background-color: rgba(255, 165, 0, 0.1); "
            "border: 1px solid rgba(255, 165, 0, 0.3); "
            "border-radius: 4px; "
            "padding: 8px; "
            "color: #FFA500; "
            "font-size: 9pt;"
        )
        main_layout.addWidget(placeholder_info)
        
        main_layout.addStretch(1)
        
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
        
        logging.info(f"Cloud settings saved (placeholder): {self.settings}")
        
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
        self.auto_sync_startup_checkbox.setChecked(self.settings['auto_sync_on_startup'])
        self.auto_sync_enabled_checkbox.setChecked(self.settings['auto_sync_enabled'])
        self.sync_interval_spin.setValue(self.settings['auto_sync_interval_hours'])
        self.sync_all_profiles_checkbox.setChecked(self.settings['sync_all_profiles'])
        
        compression_map = {'standard': 0, 'maximum': 1, 'stored': 2}
        self.compression_combo.setCurrentIndex(compression_map.get(self.settings['compression_level'], 0))
        
        self.bandwidth_limit_checkbox.setChecked(self.settings['bandwidth_limit_enabled'])
        self.bandwidth_limit_spin.setValue(self.settings['bandwidth_limit_mbps'])

