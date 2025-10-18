# dialogs/retroarch_dialog.py
# -*- coding: utf-8 -*-

import logging
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox, QAbstractItemView,
    QListWidgetItem, QWidget, QStackedLayout
)
from PySide6.QtCore import Qt, Slot

log = logging.getLogger(__name__)


class RetroArchCoreSelectionDialog(QDialog):
    """Step 1 dialog: select which RetroArch core to browse saves for."""
    def __init__(self, cores_list: List[Dict[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select RetroArch Core")
        self.setMinimumWidth(420)

        self.selected_core_id: Optional[str] = None
        self.cores_list = cores_list or []

        layout = QVBoxLayout(self)

        label = QLabel("Select a RetroArch core with detected saves:")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for core in self.cores_list:
            name = core.get("name", core.get("id", "Unknown"))
            count = core.get("count", 0)
            item = QListWidgetItem(f"{name} ({count} saves)")
            item.setData(Qt.ItemDataRole.UserRole, core)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        self.list_widget.itemSelectionChanged.connect(self._update_button_state)
        layout.addWidget(self.list_widget)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Make it clear there is a next step after selecting a core
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Next")

        self._update_button_state()
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    @Slot()
    def _update_button_state(self):
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            selected = self.list_widget.selectedItems()
            is_valid = bool(selected)
            ok_btn.setEnabled(is_valid)

    def accept(self):
        selected = self.list_widget.selectedItems()
        if selected:
            core = selected[0].data(Qt.ItemDataRole.UserRole)
            self.selected_core_id = core.get("id")
            super().accept()
        else:
            super().reject()

    def get_selected_core(self) -> Optional[str]:
        return self.selected_core_id


class RetroArchSetupDialog(QDialog):
    """Unified two-step dialog to select RetroArch core and then a game/profile."""
    def __init__(self, ra_hint: str, cores_list: List[Dict[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("RetroArch Setup")
        self.setMinimumWidth(460)

        self.ra_hint = ra_hint
        self.cores_list = cores_list or []
        self.selected_core_id: Optional[str] = None
        self.selected_profile_data: Optional[Dict] = None

        layout = QVBoxLayout(self)

        # Stacked pages
        self.stack_container = QWidget(self)
        self.stack = QStackedLayout(self.stack_container)
        layout.addWidget(self.stack_container)

        # Page 0: Core selection
        self.core_page = QWidget(self)
        core_layout = QVBoxLayout(self.core_page)
        self.core_label = QLabel("Select a RetroArch core with detected saves:")
        self.core_label.setWordWrap(True)
        core_layout.addWidget(self.core_label)
        self.core_list = QListWidget()
        self.core_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for core in self.cores_list:
            name = core.get("name", core.get("id", "Unknown"))
            count = core.get("count", 0)
            item = QListWidgetItem(f"{name} ({count} saves)")
            item.setData(Qt.ItemDataRole.UserRole, core)
            self.core_list.addItem(item)
        self.core_list.itemDoubleClicked.connect(lambda _: self._on_next_or_select())
        self.core_list.itemSelectionChanged.connect(self._update_button_state)
        core_layout.addWidget(self.core_list)
        self.stack.addWidget(self.core_page)

        # Page 1: Profile selection
        self.profile_page = QWidget(self)
        profile_layout = QVBoxLayout(self.profile_page)
        self.profile_label = QLabel("Select a game/profile for the chosen core:")
        self.profile_label.setWordWrap(True)
        profile_layout.addWidget(self.profile_label)
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.profile_list.itemDoubleClicked.connect(self.accept)
        self.profile_list.itemSelectionChanged.connect(self._update_button_state)
        profile_layout.addWidget(self.profile_list)
        self.stack.addWidget(self.profile_page)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_next_or_select)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Add back button (ActionRole)
        self.back_button = self.button_box.addButton("Back", QDialogButtonBox.ButtonRole.ActionRole)
        self.back_button.clicked.connect(self._on_back)

        # Initial state
        self.stack.setCurrentIndex(0)
        if self.core_list.count() > 0:
            self.core_list.setCurrentRow(0)
        self._configure_button_texts()
        self._update_button_state()

    def _configure_button_texts(self):
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self.stack.currentIndex() == 0:
            if ok_btn: ok_btn.setText("Next")
            self.back_button.setEnabled(False)
        else:
            if ok_btn: ok_btn.setText("Select")
            self.back_button.setEnabled(True)

    @Slot()
    def _update_button_state(self):
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self.stack.currentIndex() == 0:
            selected = bool(self.core_list.selectedItems())
            if ok_btn: ok_btn.setEnabled(selected)
        else:
            selected = bool(self.profile_list.selectedItems())
            if ok_btn: ok_btn.setEnabled(selected)

    @Slot()
    def _on_next_or_select(self):
        # Step 0 -> Step 1
        if self.stack.currentIndex() == 0:
            items = self.core_list.selectedItems()
            if not items:
                return
            core = items[0].data(Qt.ItemDataRole.UserRole) or {}
            self.selected_core_id = core.get("id")
            # Load profiles for this core
            self._populate_profiles_for_core(self.selected_core_id)
            # Move to page 1
            self.stack.setCurrentIndex(1)
            self._configure_button_texts()
            self._update_button_state()
            if self.profile_list.count() > 0:
                self.profile_list.setCurrentRow(0)
        else:
            # Final accept on page 1
            selected = self.profile_list.selectedItems()
            if selected:
                self.selected_profile_data = selected[0].data(Qt.ItemDataRole.UserRole)
                super().accept()

    @Slot()
    def _on_back(self):
        if self.stack.currentIndex() == 1:
            self.stack.setCurrentIndex(0)
            self._configure_button_texts()
            self._update_button_state()

    def _populate_profiles_for_core(self, core_id: Optional[str]):
        from emulator_utils.retroarch_manager import find_retroarch_profiles
        self.profile_list.clear()
        if not core_id:
            return
        try:
            profiles = find_retroarch_profiles(core_id, self.ra_hint) or []
        except Exception as e:
            log.error(f"Failed to load profiles for core {core_id}: {e}")
            profiles = []
        if not profiles:
            # Show a disabled item to indicate empty state
            item = QListWidgetItem("(No saves found for this core)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.profile_list.addItem(item)
            return
        for profile in profiles:
            display_name = profile.get('name', profile.get('id', 'Unknown'))
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self.profile_list.addItem(item)

    def get_selected_core(self) -> Optional[str]:
        return self.selected_core_id

    def get_selected_profile_data(self) -> Optional[Dict]:
        return self.selected_profile_data
