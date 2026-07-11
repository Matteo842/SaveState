# dialogs/emulator_selection_dialog.py
# -*- coding: utf-8 -*-

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox, QAbstractItemView,
    QListWidgetItem, QMessageBox, QCheckBox, QHBoxLayout
)
from PySide6.QtCore import Qt, Slot

log = logging.getLogger(__name__)

class EmulatorGameSelectionDialog(QDialog):
    """
    A dialog to select a specific game/profile detected for an emulator.
    """
    def __init__(self, emulator_name, profile_data_list, parent=None):
        """
        Initializes the dialog.

        Args:
            emulator_name (str): The name of the detected emulator.
            profile_data_list (list[dict]): A list of dictionaries, where each dict
                                           contains profile info (e.g., {'id': '...', 'path': '...'}).
                                           The 'id' will be displayed.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Select {emulator_name} Game")
        self.setMinimumWidth(460)

        self.profile_data_list = profile_data_list
        self.selected_profile_data = None # Backward-compatible first selected profile
        self.selected_profiles_data = []

        # --- Layout ---
        layout = QVBoxLayout(self)

        # --- Label ---
        label = QLabel(
            f"The following profiles/games have been found for {emulator_name}.\n"
            "Select one or more games to add:"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        # --- List Widget ---
        self.profile_list_widget = QListWidget()
        self.profile_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Populate the list widget
        if not self.profile_data_list:
             # Should not happen if called correctly, but handle gracefully
             item = QListWidgetItem("(No profiles found)")
             item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable) # Make it unselectable
             self.profile_list_widget.addItem(item)
        else:
            current_label = None
            for profile_data in self.profile_data_list:
                item_label = profile_data.get('label')
                
                # Check for label change to insert separator/header
                if item_label and item_label != current_label:
                    separator_text = f"--- {item_label} ---"
                    sep_item = QListWidgetItem(separator_text)
                    sep_item.setFlags(sep_item.flags() & ~Qt.ItemFlag.ItemIsSelectable) # Make it unselectable
                    sep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    
                    # Make it bold
                    font = sep_item.font()
                    font.setBold(True)
                    sep_item.setFont(font)
                    
                    self.profile_list_widget.addItem(sep_item)
                    current_label = item_label

                profile_id = profile_data.get('id', 'Unknown ID') # Get the ID to display
                display_name = profile_data.get('name', profile_id) # Use name, fallback to ID
                item = QListWidgetItem(display_name) # Display the name (or ID)
                # Store the whole dictionary in the item's data
                item.setData(Qt.ItemDataRole.UserRole, profile_data)
                self.profile_list_widget.addItem(item)

        self.profile_list_widget.itemSelectionChanged.connect(self._update_button_state)
        self.profile_list_widget.itemDoubleClicked.connect(self.accept) # Double-click accepts

        selection_row = QHBoxLayout()
        selection_row.addStretch()
        self.select_all_checkbox = QCheckBox("Select all games")
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.clicked.connect(self._toggle_all_profiles)
        selection_row.addWidget(self.select_all_checkbox)
        layout.addLayout(selection_row)
        layout.addWidget(self.profile_list_widget)

        # --- Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "SaveButton"
        )
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        # Initial state: OK button disabled if no items or nothing selected
        self._update_button_state()

        # Select the first item by default if list is not empty
        for row in range(self.profile_list_widget.count()):
            item = self.profile_list_widget.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable and item.data(Qt.ItemDataRole.UserRole):
                self.profile_list_widget.setCurrentItem(item)
                break

    @Slot()
    def _update_button_state(self):
        """Enable profile actions only when valid game rows exist/are selected."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            selected_items = [
                item for item in self.profile_list_widget.selectedItems()
                if item.flags() & Qt.ItemFlag.ItemIsSelectable
                and item.data(Qt.ItemDataRole.UserRole)
            ]
            selection_count = len(selected_items)
            ok_button.setEnabled(selection_count > 0)
            ok_button.setText(
                "Add Game" if selection_count == 1 else f"Add {selection_count} Games"
            )
            ok_button.setDefault(True)

        profile_count = sum(
            1
            for row in range(self.profile_list_widget.count())
            if self.profile_list_widget.item(row).data(Qt.ItemDataRole.UserRole)
        )
        self.select_all_checkbox.setEnabled(profile_count > 0)
        self.select_all_checkbox.blockSignals(True)
        if profile_count == 0 or selection_count == 0:
            state = Qt.CheckState.Unchecked
        elif selection_count == profile_count:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.select_all_checkbox.setCheckState(state)
        self.select_all_checkbox.blockSignals(False)

    @Slot(bool)
    def _toggle_all_profiles(self, checked):
        """Select or clear every actual profile row, leaving section headers untouched."""
        self.profile_list_widget.clearSelection()
        if checked:
            for row in range(self.profile_list_widget.count()):
                item = self.profile_list_widget.item(row)
                if item.flags() & Qt.ItemFlag.ItemIsSelectable and item.data(Qt.ItemDataRole.UserRole):
                    item.setSelected(True)
        self._update_button_state()

    def accept(self):
        """Overrides accept to save the selected item's data before closing."""
        selected_items = [
            item for item in self.profile_list_widget.selectedItems()
            if item.flags() & Qt.ItemFlag.ItemIsSelectable
            and item.data(Qt.ItemDataRole.UserRole)
        ]
        if selected_items:
            self.selected_profiles_data = [
                item.data(Qt.ItemDataRole.UserRole) for item in selected_items
            ]
            self.selected_profile_data = self.selected_profiles_data[0]
            if self.selected_profiles_data:
                log.debug(f"Emulator games selected: {self.selected_profiles_data}")
                super().accept() # Call the original QDialog accept
            else:
                # Should not happen if UserRole is set correctly
                log.error("Selected item in EmulatorGameSelectionDialog has no UserRole data!")
                # Optionally show a message?
                QMessageBox.warning(self, "Selection Error", "Unable to retrieve data for the selected profile.")
                super().reject() # Reject if data is missing
        # else: No item selected (should not happen if OK button logic is correct)

    def get_selected_profile_data(self):
        """
        Returns the dictionary containing the selected profile's data
        (e.g., {'id': '...', 'path': '...'}) after the dialog has been accepted.
        Returns None if the dialog was cancelled or no selection was made.
        """
        return self.selected_profile_data

    def get_selected_profiles_data(self):
        """Return all selected profile dictionaries after the dialog is accepted."""
        return list(self.selected_profiles_data)