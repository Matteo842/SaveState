# dialogs/emulator_selection_dialog.py
# -*- coding: utf-8 -*-

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox, QAbstractItemView,
    QListWidgetItem, QMessageBox
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
        self.setMinimumWidth(400)

        self.profile_data_list = profile_data_list
        self.selected_profile_data = None # Store the selected profile dict here

        # --- Layout ---
        layout = QVBoxLayout(self)

        # --- Label ---
        label = QLabel(f"The following profiles/games have been found for {emulator_name}.\nSelect the one to add:")
        label.setWordWrap(True)
        layout.addWidget(label)

        # --- List Widget ---
        self.profile_list_widget = QListWidget()
        self.profile_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

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
        layout.addWidget(self.profile_list_widget)

        # --- Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        # Initial state: OK button disabled if no items or nothing selected
        self._update_button_state()

        # Select the first item by default if list is not empty
        if self.profile_list_widget.count() > 0 and self.profile_list_widget.item(0).flags() & Qt.ItemFlag.ItemIsSelectable:
            self.profile_list_widget.setCurrentRow(0)

    @Slot()
    def _update_button_state(self):
        """Enables the OK button only if a valid item is selected."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            selected_items = self.profile_list_widget.selectedItems()
            is_selection_valid = False # Assume not valid initially
            if selected_items:
                # Check if the first selected item has the selectable flag set
                flags = selected_items[0].flags()
                if flags & Qt.ItemFlag.ItemIsSelectable:
                    is_selection_valid = True # It's valid if selectable

        # Now setEnabled is called with a proper boolean
        ok_button.setEnabled(is_selection_valid)

    def accept(self):
        """Overrides accept to save the selected item's data before closing."""
        selected_items = self.profile_list_widget.selectedItems()
        if selected_items:
            self.selected_profile_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
            if self.selected_profile_data:
                log.debug(f"Emulator game selected: {self.selected_profile_data}")
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