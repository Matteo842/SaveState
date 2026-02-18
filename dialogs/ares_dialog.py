# dialogs/ares_dialog.py
# -*- coding: utf-8 -*-

"""
Two-step dialog for ares emulator:
  Step 1: Select a system/console (e.g. "Game Boy", "PlayStation")
  Step 2: Select a game from that system

Pattern mirrors RetroArchSetupDialog.
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox,
    QAbstractItemView, QListWidgetItem, QWidget, QStackedLayout
)
from PySide6.QtCore import Qt, Slot

log = logging.getLogger(__name__)


class AresSetupDialog(QDialog):
    """Unified two-step dialog to select ares system and then a game/profile."""

    def __init__(self, ares_hint: str, systems_list: List[Dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("ares - Select System & Game")
        self.setMinimumWidth(460)

        self.ares_hint = ares_hint
        self.systems_list = systems_list or []
        self.selected_system_id: Optional[str] = None
        self.selected_profile_data: Optional[Dict] = None

        layout = QVBoxLayout(self)

        # Stacked pages
        self.stack_container = QWidget(self)
        self.stack = QStackedLayout(self.stack_container)
        layout.addWidget(self.stack_container)

        # ── Page 0: System / Console selection ──
        self.system_page = QWidget(self)
        system_layout = QVBoxLayout(self.system_page)
        self.system_label = QLabel("Select a console with detected saves:")
        self.system_label.setWordWrap(True)
        system_layout.addWidget(self.system_label)

        self.system_list = QListWidget()
        self.system_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for system in self.systems_list:
            name = system.get("name", system.get("id", "Unknown"))
            count = system.get("count", 0)
            item = QListWidgetItem(f"{name} ({count} saves)")
            item.setData(Qt.ItemDataRole.UserRole, system)
            self.system_list.addItem(item)
        self.system_list.itemDoubleClicked.connect(lambda _: self._on_next_or_select())
        self.system_list.itemSelectionChanged.connect(self._update_button_state)
        system_layout.addWidget(self.system_list)
        self.stack.addWidget(self.system_page)

        # ── Page 1: Game / Profile selection ──
        self.profile_page = QWidget(self)
        profile_layout = QVBoxLayout(self.profile_page)
        self.profile_label = QLabel("Select a game/profile for the chosen system:")
        self.profile_label.setWordWrap(True)
        profile_layout.addWidget(self.profile_label)

        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.profile_list.itemDoubleClicked.connect(self.accept)
        self.profile_list.itemSelectionChanged.connect(self._update_button_state)
        profile_layout.addWidget(self.profile_list)
        self.stack.addWidget(self.profile_page)

        # ── Buttons ──
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_next_or_select)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Back button
        self.back_button = self.button_box.addButton(
            "Back", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.back_button.clicked.connect(self._on_back)

        # Initial state
        self.stack.setCurrentIndex(0)
        if self.system_list.count() > 0:
            self.system_list.setCurrentRow(0)
        self._configure_button_texts()
        self._update_button_state()

    # ── helpers ──

    def _configure_button_texts(self):
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self.stack.currentIndex() == 0:
            if ok_btn:
                ok_btn.setText("Next")
            self.back_button.setEnabled(False)
        else:
            if ok_btn:
                ok_btn.setText("Select")
            self.back_button.setEnabled(True)

    @Slot()
    def _update_button_state(self):
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self.stack.currentIndex() == 0:
            selected = bool(self.system_list.selectedItems())
            if ok_btn:
                ok_btn.setEnabled(selected)
        else:
            selected = bool(self.profile_list.selectedItems())
            if ok_btn:
                ok_btn.setEnabled(selected)

    # ── navigation ──

    @Slot()
    def _on_next_or_select(self):
        if self.stack.currentIndex() == 0:
            # Step 0 → Step 1
            items = self.system_list.selectedItems()
            if not items:
                return
            system = items[0].data(Qt.ItemDataRole.UserRole) or {}
            self.selected_system_id = system.get("id")
            self._populate_profiles_for_system(self.selected_system_id)
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

    def _populate_profiles_for_system(self, system_id: Optional[str]):
        from emulator_utils.ares_manager import find_ares_profiles_for_system
        self.profile_list.clear()
        if not system_id:
            return
        try:
            profiles = find_ares_profiles_for_system(system_id, self.ares_hint) or []
        except Exception as e:
            log.error(f"Failed to load profiles for ares system {system_id}: {e}")
            profiles = []
        if not profiles:
            item = QListWidgetItem("(No saves found for this system)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.profile_list.addItem(item)
            return
        for profile in profiles:
            display_name = profile.get('name', profile.get('id', 'Unknown'))
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self.profile_list.addItem(item)

    # ── public getters ──

    def get_selected_system(self) -> Optional[str]:
        return self.selected_system_id

    def get_selected_profile_data(self) -> Optional[Dict]:
        return self.selected_profile_data
