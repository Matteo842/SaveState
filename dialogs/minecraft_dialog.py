# dialogs/minecraft_dialog.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QLabel, QVBoxLayout,
    QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt, Slot

class MinecraftWorldsDialog(QDialog):
    """
    Dialog to show and select a Minecraft world from a list.
    """
    def __init__(self, worlds_data, parent=None):
        """
        Initializes the dialog.

        Args:
            worlds_data (list): List of world dictionaries, produced by
                                 minecraft_utils.list_minecraft_worlds.
                                 E.g.: [{'folder_name': ..., 'world_name': ..., 'full_path': ...}, ...]
            parent (QWidget, optional): Parent widget. Default None.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Select Minecraft World"))
        self.setMinimumWidth(400)
        self.selected_world = None # Stores the selected world's info

        layout = QVBoxLayout(self)

        label = QLabel(self.tr("Select the world to create a profile for:"))
        layout.addWidget(label)

        self.worlds_list_widget = QListWidget()

        if not worlds_data:
            # Case when no worlds are found
            info_label = QLabel(self.tr("No worlds found in the Minecraft 'saves' folder.\nCheck that Minecraft Java Edition is installed correctly."))
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
            self.worlds_list_widget.setVisible(False) # Hide the empty list
        else:
            # Populate the list
            for world_info in worlds_data:
                # Show the name read from NBT (or folder name if NBT fails)
                display_text = world_info.get('world_name', world_info.get('folder_name', 'Unknown Name'))
                item = QListWidgetItem(display_text)
                # Store the ENTIRE world_info dictionary in the item
                item.setData(Qt.ItemDataRole.UserRole, world_info)
                self.worlds_list_widget.addItem(item)
            layout.addWidget(self.worlds_list_widget)

        # OK / Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Disable OK at the start (if there are worlds)
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
             ok_button.setEnabled(False if worlds_data else False) # Disable if list is empty or at the start

        layout.addWidget(self.button_box)

        # Connect selection change to enable/disable OK
        self.worlds_list_widget.currentItemChanged.connect(self._update_button_state)
        # Connect double click to accept immediately
        self.worlds_list_widget.itemDoubleClicked.connect(self.accept)

    @Slot()
    def _update_button_state(self):
        """Enables the OK button only if an item is selected."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setEnabled(self.worlds_list_widget.currentItem() is not None)

    def accept(self):
        """Overrides accept to save the selected item before closing."""
        current_item = self.worlds_list_widget.currentItem()
        if current_item:
            self.selected_world = current_item.data(Qt.ItemDataRole.UserRole)
            # Check that we actually retrieved the data
            if self.selected_world:
                 super().accept() # Call the original QDialog accept
            else:
                 # Should not happen if UserRole is set correctly
                 QMessageBox.warning(self, self.tr("Selection Error"), self.tr("Unable to retrieve the selected world's data."))
        # else: No item selected (should not happen if the OK button was enabled)

    def get_selected_world_info(self):
        """
        Returns the dictionary with the selected world's information
        after the dialog has been accepted.
        """
        return self.selected_world