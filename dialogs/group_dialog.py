# dialogs/group_dialog.py
# -*- coding: utf-8 -*-
"""
Dialog for creating and editing Profile Groups (Matrioska profiles).

A Profile Group is a virtual profile that contains references to multiple
real profiles. When backup/restore is triggered on a group, it processes
all contained profiles sequentially.

Groups can also have their own settings that override individual profile
settings (and global settings) for all member profiles.
"""

import logging
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QDialogButtonBox, QAbstractItemView, QListWidgetItem, QMessageBox,
    QFrame, QSizePolicy, QGroupBox, QCheckBox, QSpinBox, QComboBox,
    QPushButton, QFormLayout, QFileDialog, QStyle, QWidget
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap

import core_logic

log = logging.getLogger(__name__)

# Default values for group settings (matching global defaults from settings_manager)
DEFAULT_MAX_BACKUPS = 5
DEFAULT_COMPRESSION_MODE = "standard"
DEFAULT_MAX_SOURCE_SIZE_MB = 500

# Size options for max source size combobox (matching settings_dialog.py)
SIZE_OPTIONS = [
    ("50 MB", 50),
    ("100 MB", 100),
    ("250 MB", 250),
    ("500 MB", 500),
    ("1 GB (1024 MB)", 1024),
    ("2 GB (2048 MB)", 2048),
    ("5 GB (5120 MB)", 5120),
    ("No Limit", -1)
]

# Compression options
COMPRESSION_OPTIONS = {
    "standard": "Standard (Recommended)",
    "maximum": "Maximum (Slower)",
    "stored": "None (Faster)"
}


class GroupDialog(QDialog):
    """
    Dialog for creating or editing a Profile Group.
    
    In create mode: allows selecting multiple profiles to group together.
    In edit mode: shows existing group members with ability to add/remove.
    
    Groups can have their own settings that override individual profile
    settings for all member profiles when backup is performed.
    """
    
    def __init__(self, profiles_dict: dict, parent=None, 
                 edit_group_name: str = None, preselected_profiles: list = None,
                 global_settings: dict = None):
        """
        Initialize the group dialog.
        
        Args:
            profiles_dict: Dictionary of all profiles
            parent: Parent widget
            edit_group_name: If provided, dialog is in edit mode for this group
            preselected_profiles: List of profile names to pre-select (for create mode)
            global_settings: Global application settings (for default values)
        """
        super().__init__(parent)
        
        self.profiles_dict = profiles_dict
        self.edit_mode = edit_group_name is not None
        self.original_group_name = edit_group_name
        self.result_group_name = None
        self.result_profile_names = None
        self.result_settings = None  # Group settings result
        # Custom icon edit state, mirroring the inline profile editor.
        # Values: None (no change), 'clear' (remove icon), str path (set new).
        self._pending_icon_action = None
        # Files saved into the custom-icons folder during this dialog session,
        # tracked for cleanup on cancel / replacement.
        self._session_temp_icons = []
        self.result_custom_icon_path = None  # set on accept(): None/'' (clear)/path
        
        # Store global settings for defaults
        self.global_settings = global_settings or {}
        
        # Setup window
        if self.edit_mode:
            self.setWindowTitle("Edit Profile Group")
        else:
            self.setWindowTitle("Create Profile Group")
        
        self.setMinimumWidth(500)
        self.setMinimumHeight(550)
        
        # Build UI
        self._setup_ui(preselected_profiles)
        
        # If editing, populate with existing data
        if self.edit_mode:
            self._populate_edit_mode()
    
    def _setup_ui(self, preselected_profiles: list = None):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Custom Icon Picker (hidden when icons are disabled globally) ---
        self.icon_row = QWidget()
        icon_row_layout = QHBoxLayout(self.icon_row)
        icon_row_layout.setContentsMargins(0, 0, 0, 0)
        icon_row_layout.setSpacing(8)
        icon_row_layout.addWidget(QLabel("Icon:"))
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(48, 48)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet(
            "QLabel { border: 1px solid #555; border-radius: 4px; "
            "background-color: rgba(0, 0, 0, 30); }"
        )
        icon_row_layout.addWidget(self.icon_preview)
        self.icon_change_button = QPushButton("Change Icon...")
        self.icon_change_button.setToolTip(
            "Pick a custom image (PNG, JPG, ICO, BMP, WEBP, SVG) or steal "
            "the icon from a program / shortcut (.exe, .dll, .lnk, "
            ".desktop, .AppImage)"
        )
        self.icon_change_button.clicked.connect(self._on_change_icon)
        self.icon_reset_button = QPushButton("Reset")
        self.icon_reset_button.setToolTip(
            "Remove the custom icon and use the default folder icon"
        )
        self.icon_reset_button.clicked.connect(self._on_reset_icon)
        icon_row_layout.addWidget(self.icon_change_button)
        icon_row_layout.addWidget(self.icon_reset_button)
        icon_row_layout.addStretch(1)
        layout.addWidget(self.icon_row)
        if not self.global_settings.get("show_profile_icons", True):
            self.icon_row.setVisible(False)
        self._refresh_icon_preview()

        # --- Group Name Section ---
        name_label = QLabel("Group Name:")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter a name for the group...")
        self.name_edit.textChanged.connect(self._update_button_state)
        layout.addWidget(name_label)
        layout.addWidget(self.name_edit)
        
        # --- Separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        
        # --- Profile Selection Section ---
        profiles_label = QLabel("Select profiles to include in this group:")
        layout.addWidget(profiles_label)
        
        # Profile list with checkboxes
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.profile_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Store preselected for sorting
        self._preselected_profiles = preselected_profiles or []
        
        # Populate with available profiles (excluding groups and already-grouped profiles)
        available_profiles = self._get_available_profiles()
        
        if not available_profiles:
            item = QListWidgetItem("(No available profiles)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.profile_list.addItem(item)
        else:
            # Sort profiles: selected first, then alphabetically
            selected_profiles = [p for p in sorted(available_profiles) if p in self._preselected_profiles]
            unselected_profiles = [p for p in sorted(available_profiles) if p not in self._preselected_profiles]
            sorted_profiles = selected_profiles + unselected_profiles
            
            for profile_name in sorted_profiles:
                item = QListWidgetItem(profile_name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                
                # Pre-select if in preselected list or if editing
                if preselected_profiles and profile_name in preselected_profiles:
                    item.setCheckState(Qt.CheckState.Checked)
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                
                item.setData(Qt.ItemDataRole.UserRole, profile_name)
                self.profile_list.addItem(item)
        
        self.profile_list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.profile_list)
        
        # --- Selection Info ---
        self.selection_info_label = QLabel()
        self.selection_info_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.selection_info_label)
        
        # --- Group Settings Section (only in edit mode) ---
        if self.edit_mode:
            self._setup_settings_section(layout)
        
        # --- Buttons ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
        
        # Initial button state
        self._update_button_state()
    
    def _setup_settings_section(self, parent_layout: QVBoxLayout):
        """Setup the group settings override section."""
        # --- Settings Group Box ---
        self.settings_group = QGroupBox("Group Settings (Override)")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(8)
        
        # Enable settings checkbox
        self.enable_settings_checkbox = QCheckBox("Enable group-level settings override")
        self.enable_settings_checkbox.setToolTip(
            "When enabled, these settings will override individual profile settings\n"
            "and global settings for all profiles in this group."
        )
        self.enable_settings_checkbox.toggled.connect(self._on_settings_enabled_toggled)
        settings_layout.addWidget(self.enable_settings_checkbox)
        
        # Settings form (initially disabled)
        self.settings_form_widget = QFrame()
        form_layout = QFormLayout(self.settings_form_widget)
        form_layout.setContentsMargins(20, 8, 8, 8)
        form_layout.setSpacing(8)
        
        # Max backups spinbox
        self.max_backups_spin = QSpinBox()
        self.max_backups_spin.setRange(1, 99)
        self.max_backups_spin.setValue(
            self.global_settings.get('max_backups', DEFAULT_MAX_BACKUPS)
        )
        self.max_backups_spin.setToolTip("Maximum number of backups to keep per profile")
        form_layout.addRow("Max backups:", self.max_backups_spin)
        
        # Compression mode combobox
        self.compression_combo = QComboBox()
        for key, display_text in COMPRESSION_OPTIONS.items():
            self.compression_combo.addItem(display_text, key)
        # Set default from global settings
        default_compression = self.global_settings.get('compression_mode', DEFAULT_COMPRESSION_MODE)
        idx = self.compression_combo.findData(default_compression)
        if idx >= 0:
            self.compression_combo.setCurrentIndex(idx)
        self.compression_combo.setToolTip("Compression mode for backup archives")
        form_layout.addRow("Compression:", self.compression_combo)
        
        # Max source size combobox
        self.max_source_size_combo = QComboBox()
        for display_text, value in SIZE_OPTIONS:
            self.max_source_size_combo.addItem(display_text, value)
        # Set default from global settings
        default_size = self.global_settings.get('max_source_size_mb', DEFAULT_MAX_SOURCE_SIZE_MB)
        size_idx = next(
            (i for i, (_, v) in enumerate(SIZE_OPTIONS) if v == default_size),
            3  # Default to 500 MB (index 3)
        )
        self.max_source_size_combo.setCurrentIndex(size_idx)
        self.max_source_size_combo.setToolTip("Maximum source size allowed for backup")
        form_layout.addRow("Max source size:", self.max_source_size_combo)
        
        settings_layout.addWidget(self.settings_form_widget)
        
        # Reset button
        reset_layout = QHBoxLayout()
        reset_layout.addStretch()
        self.reset_settings_btn = QPushButton("Reset to Defaults")
        self.reset_settings_btn.setToolTip("Reset settings to global defaults")
        self.reset_settings_btn.clicked.connect(self._reset_settings_to_defaults)
        reset_layout.addWidget(self.reset_settings_btn)
        settings_layout.addLayout(reset_layout)
        
        self.settings_group.setLayout(settings_layout)
        parent_layout.addWidget(self.settings_group)
        
        # Initially disable settings form
        self._on_settings_enabled_toggled(False)
    
    @Slot(bool)
    def _on_settings_enabled_toggled(self, enabled: bool):
        """Handle settings enable checkbox toggle."""
        self.settings_form_widget.setEnabled(enabled)
        self.reset_settings_btn.setEnabled(enabled)
        
        # Visual feedback for disabled state
        if enabled:
            self.settings_form_widget.setStyleSheet("")
        else:
            self.settings_form_widget.setStyleSheet("QFrame { color: gray; }")
    
    @Slot()
    def _reset_settings_to_defaults(self):
        """Reset settings to global defaults."""
        self.max_backups_spin.setValue(
            self.global_settings.get('max_backups', DEFAULT_MAX_BACKUPS)
        )
        
        default_compression = self.global_settings.get('compression_mode', DEFAULT_COMPRESSION_MODE)
        idx = self.compression_combo.findData(default_compression)
        if idx >= 0:
            self.compression_combo.setCurrentIndex(idx)
        
        default_size = self.global_settings.get('max_source_size_mb', DEFAULT_MAX_SOURCE_SIZE_MB)
        size_idx = next(
            (i for i, (_, v) in enumerate(SIZE_OPTIONS) if v == default_size),
            3
        )
        self.max_source_size_combo.setCurrentIndex(size_idx)
        
        log.debug("Group settings reset to defaults")
    
    def _get_current_settings(self) -> dict:
        """Get the current settings from the UI controls."""
        # Settings section only exists in edit mode
        if not self.edit_mode:
            return {}
        
        if not self.enable_settings_checkbox.isChecked():
            return {}
        
        return {
            'enabled': True,
            'max_backups': self.max_backups_spin.value(),
            'compression_mode': self.compression_combo.currentData(),
            'max_source_size_mb': self.max_source_size_combo.currentData(),
        }
    
    def _get_available_profiles(self) -> list:
        """
        Get list of profiles that can be added to a group.
        
        Excludes:
        - Group profiles (no nested groups)
        - Profiles already in another group (unless editing that group)
        """
        available = []
        
        for name, data in self.profiles_dict.items():
            if not isinstance(data, dict):
                continue
            
            # Skip groups
            if core_logic.is_group_profile(data):
                continue
            
            # Check if already in a group
            member_of = data.get('member_of_group')
            if member_of:
                # Allow if editing the same group
                if self.edit_mode and member_of == self.original_group_name:
                    available.append(name)
                # Skip if in another group
                continue
            
            available.append(name)
        
        return available
    
    def _populate_edit_mode(self):
        """Populate dialog with existing group data for editing."""
        if not self.original_group_name or self.original_group_name not in self.profiles_dict:
            return
        
        # Set group name
        self.name_edit.setText(self.original_group_name)
        
        # Get current members
        group_data = self.profiles_dict[self.original_group_name]
        current_members = group_data.get('profiles', [])
        
        # Check the member profiles
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            profile_name = item.data(Qt.ItemDataRole.UserRole)
            if profile_name in current_members:
                item.setCheckState(Qt.CheckState.Checked)
        
        # Load existing group settings
        self._populate_settings_from_group(group_data)
    
    def _populate_settings_from_group(self, group_data: dict):
        """Populate settings controls from existing group data."""
        settings = group_data.get('settings', {})
        
        if not settings:
            # No settings, keep defaults and disabled
            self.enable_settings_checkbox.setChecked(False)
            return
        
        # Enable settings if they were enabled
        settings_enabled = settings.get('enabled', False)
        self.enable_settings_checkbox.setChecked(settings_enabled)
        
        # Populate max_backups
        if 'max_backups' in settings and settings['max_backups'] is not None:
            self.max_backups_spin.setValue(int(settings['max_backups']))
        
        # Populate compression_mode
        if 'compression_mode' in settings and settings['compression_mode'] is not None:
            idx = self.compression_combo.findData(settings['compression_mode'])
            if idx >= 0:
                self.compression_combo.setCurrentIndex(idx)
        
        # Populate max_source_size_mb
        if 'max_source_size_mb' in settings and settings['max_source_size_mb'] is not None:
            size_value = settings['max_source_size_mb']
            size_idx = next(
                (i for i, (_, v) in enumerate(SIZE_OPTIONS) if v == size_value),
                -1
            )
            if size_idx >= 0:
                self.max_source_size_combo.setCurrentIndex(size_idx)
        
        log.debug(f"Loaded group settings: {settings}")
    
    def _get_checked_profiles(self) -> list:
        """Get list of checked profile names."""
        checked = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                profile_name = item.data(Qt.ItemDataRole.UserRole)
                if profile_name:
                    checked.append(profile_name)
        return checked
    
    @Slot(QListWidgetItem)
    def _on_item_changed(self, item: QListWidgetItem):
        """Handle item check state change - re-sort list and update button state."""
        # Update button state
        self._update_button_state()
        
        # Re-sort list to keep checked items at top
        self._sort_profile_list()
    
    def _sort_profile_list(self):
        """Sort the profile list: checked items at top, then alphabetically."""
        # Temporarily disconnect to avoid recursion
        try:
            self.profile_list.itemChanged.disconnect(self._on_item_changed)
        except Exception:
            pass
        
        # Collect all items with their data
        items_data = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item:
                profile_name = item.data(Qt.ItemDataRole.UserRole)
                if profile_name:  # Skip placeholder items
                    is_checked = item.checkState() == Qt.CheckState.Checked
                    items_data.append((profile_name, is_checked))
        
        # Sort: checked first, then alphabetically
        items_data.sort(key=lambda x: (not x[1], x[0].lower()))
        
        # Clear and repopulate
        self.profile_list.clear()
        for profile_name, is_checked in items_data:
            item = QListWidgetItem(profile_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, profile_name)
            self.profile_list.addItem(item)
        
        # Reconnect signal
        self.profile_list.itemChanged.connect(self._on_item_changed)
    
    @Slot()
    def _update_button_state(self):
        """Update OK button state and selection info based on current input."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        
        # Check if name is valid
        name = self.name_edit.text().strip()
        name_valid = bool(name)
        
        # Check for name conflicts (if creating or renaming)
        name_conflict = False
        if name_valid:
            if name in self.profiles_dict:
                # Conflict unless we're editing this same group
                if not (self.edit_mode and name == self.original_group_name):
                    name_conflict = True
        
        # Check selection count
        checked_profiles = self._get_checked_profiles()
        selection_count = len(checked_profiles)
        selection_valid = selection_count >= 1
        
        # Update selection info
        if selection_count == 0:
            self.selection_info_label.setText("Select at least 1 profile")
            self.selection_info_label.setStyleSheet("color: #d32f2f; font-style: italic;")
        elif selection_count == 1:
            self.selection_info_label.setText("1 profile selected (consider adding more)")
            self.selection_info_label.setStyleSheet("color: #f57c00; font-style: italic;")
        else:
            self.selection_info_label.setText(f"{selection_count} profiles selected")
            self.selection_info_label.setStyleSheet("color: #388e3c; font-style: italic;")
        
        # Show name error if conflict
        if name_conflict:
            self.selection_info_label.setText(f"A profile named '{name}' already exists")
            self.selection_info_label.setStyleSheet("color: #d32f2f; font-style: italic;")
        
        # Enable OK button only if everything is valid
        can_accept = name_valid and not name_conflict and selection_valid
        if ok_button:
            ok_button.setEnabled(can_accept)
    
    def _get_existing_custom_icon(self):
        """Return the persisted custom icon path of the group (if editing)."""
        if not self.edit_mode or not self.original_group_name:
            return None
        data = self.profiles_dict.get(self.original_group_name, {})
        if not isinstance(data, dict):
            return None
        path = data.get('custom_icon_path') or data.get('icon')
        if isinstance(path, str) and os.path.isfile(path):
            return path
        return None

    def _refresh_icon_preview(self):
        """Update the icon preview based on pending action / persisted state."""
        if not hasattr(self, 'icon_preview'):
            return
        pending = self._pending_icon_action
        icon_path = None
        if isinstance(pending, str) and pending and pending != 'clear':
            icon_path = pending
        elif pending != 'clear':
            icon_path = self._get_existing_custom_icon()

        pixmap = None
        if icon_path and os.path.isfile(icon_path):
            try:
                pm = QPixmap(icon_path)
                if not pm.isNull():
                    pixmap = pm
            except Exception:
                pixmap = None

        if pixmap is None:
            try:
                style = self.style()
                pixmap = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon).pixmap(48, 48)
            except Exception:
                pixmap = QPixmap(48, 48)
                pixmap.fill(Qt.GlobalColor.transparent)

        scaled = pixmap.scaled(
            48, 48,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.icon_preview.setPixmap(scaled)

        # Reset button enabled only when there's something to clear
        has_custom = bool(
            (isinstance(pending, str) and pending and pending != 'clear') or
            (pending is None and self._get_existing_custom_icon())
        )
        self.icon_reset_button.setEnabled(has_custom)

    @Slot()
    def _on_change_icon(self):
        """Open a file picker and stage a new custom icon for this group."""
        try:
            from gui_components import icon_extractor
        except Exception as e:
            log.error(f"Failed to import icon_extractor: {e}")
            return

        # Allow regular image files OR executables/shortcuts to "steal"
        # the icon from another program (Windows-style behavior).
        import platform as _plat
        if _plat.system() == "Windows":
            exe_pattern = "*.exe *.dll *.lnk *.ico"
        else:
            exe_pattern = "*.AppImage *.desktop *.exe *.ico"
        file_filter = (
            "Icon sources (*.png *.jpg *.jpeg *.bmp *.webp *.ico *.svg "
            f"{exe_pattern});;"
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.ico *.svg);;"
            f"Programs / shortcuts ({exe_pattern});;"
            "All files (*)"
        )
        source_path, _ = QFileDialog.getOpenFileName(
            self, "Select Group Icon", "", file_filter
        )
        if not source_path:
            return

        # Use a stable name for new groups before they have one
        name_for_file = (self.name_edit.text().strip()
                         or self.original_group_name
                         or "group")
        saved_path = icon_extractor.save_custom_icon(source_path, name_for_file)
        if not saved_path:
            QMessageBox.warning(
                self,
                "Icon Error",
                "Could not load the selected image.\n"
                "Make sure the file is a valid image (PNG, JPG, BMP, ICO, WEBP, SVG)."
            )
            return

        # Drop the previous in-session pending file so we don't leak it
        prev = self._pending_icon_action
        if isinstance(prev, str) and prev and prev != 'clear' \
                and prev in self._session_temp_icons and prev != saved_path:
            icon_extractor.delete_custom_icon_file(prev)
            try:
                self._session_temp_icons.remove(prev)
            except ValueError:
                pass

        if saved_path not in self._session_temp_icons:
            self._session_temp_icons.append(saved_path)
        self._pending_icon_action = saved_path
        self._refresh_icon_preview()

    @Slot()
    def _on_reset_icon(self):
        """Mark the dialog session to clear the persisted custom icon."""
        try:
            from gui_components import icon_extractor
            prev = self._pending_icon_action
            if isinstance(prev, str) and prev and prev != 'clear' \
                    and prev in self._session_temp_icons:
                icon_extractor.delete_custom_icon_file(prev)
                try:
                    self._session_temp_icons.remove(prev)
                except ValueError:
                    pass
        except Exception:
            pass
        self._pending_icon_action = 'clear'
        self._refresh_icon_preview()

    def reject(self):
        """Discard any uncommitted custom icon files before closing."""
        try:
            from gui_components import icon_extractor
            for f in list(self._session_temp_icons):
                icon_extractor.delete_custom_icon_file(f)
            self._session_temp_icons.clear()
        except Exception:
            pass
        self._pending_icon_action = None
        super().reject()

    def accept(self):
        """Validate and accept the dialog."""
        name = self.name_edit.text().strip()
        checked_profiles = self._get_checked_profiles()
        
        # Final validation
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a group name.")
            return
        
        if not checked_profiles:
            QMessageBox.warning(self, "No Selection", "Please select at least one profile.")
            return
        
        # Check for name conflict (shouldn't happen if button state is correct)
        if name in self.profiles_dict:
            if not (self.edit_mode and name == self.original_group_name):
                QMessageBox.warning(self, "Name Conflict", 
                                   f"A profile named '{name}' already exists.")
                return
        
        # Store results
        self.result_group_name = name
        self.result_profile_names = checked_profiles
        self.result_settings = self._get_current_settings()
        # Translate the pending icon action into the result the caller will
        # apply to the group profile data.
        pending = self._pending_icon_action
        if pending == 'clear':
            self.result_custom_icon_path = ''  # explicit removal
        elif isinstance(pending, str) and pending:
            self.result_custom_icon_path = pending
        else:
            self.result_custom_icon_path = None  # no change
        
        log.info(f"Group dialog accepted: name='{name}', profiles={checked_profiles}, settings={self.result_settings}, icon={self.result_custom_icon_path!r}")
        super().accept()
    
    def get_result(self) -> tuple:
        """
        Get the dialog result after acceptance.
        
        Returns:
            Tuple (group_name: str, profile_names: list, settings: dict)
            or (None, None, None) if cancelled
        """
        return self.result_group_name, self.result_profile_names, self.result_settings

    def get_custom_icon_result(self):
        """Return the icon decision from this dialog session.

        - ``None``: no change requested (preserve the existing icon, if any).
        - ``''`` (empty string): clear the persisted custom icon.
        - non-empty ``str``: absolute path to the new custom icon (already
          stored inside the managed custom-icons folder).
        """
        return self.result_custom_icon_path


class GroupMemberSelectionDialog(QDialog):
    """
    Dialog for selecting which profile to restore from a group.
    
    When restoring a group, user can choose to restore all profiles
    or select specific ones.
    """
    
    def __init__(self, group_name: str, member_profiles: list, parent=None):
        """
        Initialize the member selection dialog.
        
        Args:
            group_name: Name of the group
            member_profiles: List of profile names in the group
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.group_name = group_name
        self.member_profiles = member_profiles
        self.selected_profiles = None
        
        self.setWindowTitle(f"Restore from Group: {group_name}")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Info label
        info_label = QLabel(
            f"The group '{self.group_name}' contains {len(self.member_profiles)} profiles.\n"
            "Select which profiles to restore:"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Profile list with checkboxes
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        
        for profile_name in self.member_profiles:
            item = QListWidgetItem(profile_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)  # Default to all selected
            item.setData(Qt.ItemDataRole.UserRole, profile_name)
            self.profile_list.addItem(item)
        
        self.profile_list.itemChanged.connect(self._update_button_state)
        layout.addWidget(self.profile_list)
        
        # Quick selection buttons
        quick_layout = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        quick_layout.addWidget(select_all_btn)
        
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self._select_none)
        quick_layout.addWidget(select_none_btn)
        
        quick_layout.addStretch()
        layout.addLayout(quick_layout)
        
        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.setLayout(layout)
        self._update_button_state()
    
    def _select_all(self):
        """Select all profiles."""
        for i in range(self.profile_list.count()):
            self.profile_list.item(i).setCheckState(Qt.CheckState.Checked)
    
    def _select_none(self):
        """Deselect all profiles."""
        for i in range(self.profile_list.count()):
            self.profile_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    
    def _get_checked_profiles(self) -> list:
        """Get list of checked profile names."""
        checked = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                profile_name = item.data(Qt.ItemDataRole.UserRole)
                if profile_name:
                    checked.append(profile_name)
        return checked
    
    @Slot()
    def _update_button_state(self):
        """Update OK button state based on selection."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        checked = self._get_checked_profiles()
        if ok_button:
            ok_button.setEnabled(len(checked) > 0)
    
    def accept(self):
        """Accept the dialog with selected profiles."""
        self.selected_profiles = self._get_checked_profiles()
        if not self.selected_profiles:
            QMessageBox.warning(self, "No Selection", "Please select at least one profile.")
            return
        super().accept()
    
    def get_selected_profiles(self) -> list:
        """Get the list of selected profile names."""
        return self.selected_profiles if self.selected_profiles else []
