# dialogs/group_dialog.py
# -*- coding: utf-8 -*-
"""
Dialog for creating and editing Profile Groups (Matrioska profiles).

A Profile Group is a virtual profile that contains references to multiple
real profiles. When backup/restore is triggered on a group, it processes
all contained profiles sequentially.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QDialogButtonBox, QAbstractItemView, QListWidgetItem, QMessageBox,
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Slot

import core_logic

log = logging.getLogger(__name__)


class GroupDialog(QDialog):
    """
    Dialog for creating or editing a Profile Group.
    
    In create mode: allows selecting multiple profiles to group together.
    In edit mode: shows existing group members with ability to add/remove.
    """
    
    def __init__(self, profiles_dict: dict, parent=None, 
                 edit_group_name: str = None, preselected_profiles: list = None):
        """
        Initialize the group dialog.
        
        Args:
            profiles_dict: Dictionary of all profiles
            parent: Parent widget
            edit_group_name: If provided, dialog is in edit mode for this group
            preselected_profiles: List of profile names to pre-select (for create mode)
        """
        super().__init__(parent)
        
        self.profiles_dict = profiles_dict
        self.edit_mode = edit_group_name is not None
        self.original_group_name = edit_group_name
        self.result_group_name = None
        self.result_profile_names = None
        
        # Setup window
        if self.edit_mode:
            self.setWindowTitle("Edit Profile Group")
        else:
            self.setWindowTitle("Create Profile Group")
        
        self.setMinimumWidth(450)
        self.setMinimumHeight(400)
        
        # Build UI
        self._setup_ui(preselected_profiles)
        
        # If editing, populate with existing data
        if self.edit_mode:
            self._populate_edit_mode()
    
    def _setup_ui(self, preselected_profiles: list = None):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
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
        
        # Populate with available profiles (excluding groups and already-grouped profiles)
        available_profiles = self._get_available_profiles()
        
        if not available_profiles:
            item = QListWidgetItem("(No available profiles)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.profile_list.addItem(item)
        else:
            for profile_name in sorted(available_profiles):
                item = QListWidgetItem(profile_name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                
                # Pre-select if in preselected list or if editing
                if preselected_profiles and profile_name in preselected_profiles:
                    item.setCheckState(Qt.CheckState.Checked)
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                
                item.setData(Qt.ItemDataRole.UserRole, profile_name)
                self.profile_list.addItem(item)
        
        self.profile_list.itemChanged.connect(self._update_button_state)
        layout.addWidget(self.profile_list)
        
        # --- Selection Info ---
        self.selection_info_label = QLabel()
        self.selection_info_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.selection_info_label)
        
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
        
        log.info(f"Group dialog accepted: name='{name}', profiles={checked_profiles}")
        super().accept()
    
    def get_result(self) -> tuple:
        """
        Get the dialog result after acceptance.
        
        Returns:
            Tuple (group_name: str, profile_names: list) or (None, None) if cancelled
        """
        return self.result_group_name, self.result_profile_names


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
