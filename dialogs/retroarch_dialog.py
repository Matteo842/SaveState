# dialogs/retroarch_dialog.py
# -*- coding: utf-8 -*-

import logging
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox, QAbstractItemView,
    QListWidgetItem
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


