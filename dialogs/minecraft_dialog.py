# dialogs/minecraft_dialog.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QLabel, QVBoxLayout,
    QDialogButtonBox, QMessageBox, QComboBox, QHBoxLayout
)
from PySide6.QtCore import Qt, Slot
import minecraft_utils
import logging


class MinecraftWorldsDialog(QDialog):
    """
    Dialog to show and select a Minecraft world from a list.
    Supports multiple sources: vanilla Minecraft and Prism Launcher instances.
    """
    def __init__(self, worlds_data=None, parent=None, sources=None):
        """
        Initializes the dialog.

        Args:
            worlds_data (list): DEPRECATED - List of world dictionaries for backwards compatibility.
                                If provided, will be used as a single source.
            parent (QWidget, optional): Parent widget. Default None.
            sources (list, optional): List of source dictionaries from get_all_minecraft_saves_sources().
                                      If provided, worlds_data is ignored.
        """
        super().__init__(parent)
        self.setWindowTitle("Select Minecraft World")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)
        self.selected_world = None  # Stores the selected world's info
        self._sources = []  # Store sources for later use
        self._current_worlds = []  # Currently displayed worlds

        layout = QVBoxLayout(self)

        # --- Source selection (if multiple sources available) ---
        self._source_combo = None
        
        if sources:
            # New multi-source mode
            self._sources = sources
            if len(sources) > 1:
                source_layout = QHBoxLayout()
                source_label = QLabel("Source:")
                source_layout.addWidget(source_label)
                
                self._source_combo = QComboBox()
                for src in sources:
                    self._source_combo.addItem(src['source_name'], src)
                self._source_combo.currentIndexChanged.connect(self._on_source_changed)
                source_layout.addWidget(self._source_combo, 1)
                layout.addLayout(source_layout)
            
            # Load worlds from first source
            if sources:
                self._load_worlds_from_source(sources[0])
        elif worlds_data is not None:
            # Legacy single-source mode (backwards compatibility)
            self._current_worlds = worlds_data
        else:
            self._current_worlds = []

        # --- World list label ---
        self._list_label = QLabel("Select the world to create a profile for:")
        layout.addWidget(self._list_label)

        # --- World list ---
        self.worlds_list_widget = QListWidget()
        layout.addWidget(self.worlds_list_widget)

        # --- OK / Cancel buttons (must be created BEFORE _populate_world_list) ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Disable OK at the start
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setEnabled(False)

        layout.addWidget(self.button_box)

        # Populate the world list (after button_box is created)
        self._populate_world_list()

        # Connect selection change to enable/disable OK
        self.worlds_list_widget.currentItemChanged.connect(self._update_button_state)
        # Connect double click to accept immediately
        self.worlds_list_widget.itemDoubleClicked.connect(self.accept)

    def _load_worlds_from_source(self, source):
        """Load worlds from a specific source."""
        saves_path = source.get('saves_path')
        if saves_path:
            self._current_worlds = minecraft_utils.list_minecraft_worlds(saves_path)
            # Add source info to each world for reference
            for world in self._current_worlds:
                world['source_name'] = source.get('source_name', 'Unknown')
                world['launcher'] = source.get('launcher', 'vanilla')
        else:
            self._current_worlds = []

    def _populate_world_list(self):
        """Populate the world list widget with current worlds."""
        self.worlds_list_widget.clear()
        
        if not self._current_worlds:
            # Show info item when no worlds found
            info_item = QListWidgetItem("No worlds found in this source")
            info_item.setFlags(Qt.ItemFlag.NoItemFlags)  # Make it non-selectable
            info_item.setForeground(Qt.GlobalColor.gray)
            self.worlds_list_widget.addItem(info_item)
        else:
            for world_info in self._current_worlds:
                # Show the name read from NBT (or folder name if NBT fails)
                display_text = world_info.get('world_name', world_info.get('folder_name', 'Unknown Name'))
                item = QListWidgetItem(display_text)
                # Store the ENTIRE world_info dictionary in the item
                item.setData(Qt.ItemDataRole.UserRole, world_info)
                self.worlds_list_widget.addItem(item)
        
        # Update OK button state
        self._update_button_state()

    @Slot(int)
    def _on_source_changed(self, index):
        """Handle source selection change."""
        if self._source_combo and index >= 0:
            source = self._source_combo.itemData(index)
            if source:
                logging.debug(f"Minecraft source changed to: {source.get('source_name')}")
                self._load_worlds_from_source(source)
                self._populate_world_list()

    @Slot()
    def _update_button_state(self):
        """Enables the OK button only if an item is selected."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            current_item = self.worlds_list_widget.currentItem()
            # Check if item is valid (has user data)
            has_valid_selection = (current_item is not None and 
                                   current_item.data(Qt.ItemDataRole.UserRole) is not None)
            ok_button.setEnabled(has_valid_selection)

    def accept(self):
        """Overrides accept to save the selected item before closing."""
        current_item = self.worlds_list_widget.currentItem()
        if current_item:
            self.selected_world = current_item.data(Qt.ItemDataRole.UserRole)
            # Check that we actually retrieved the data
            if self.selected_world:
                super().accept()  # Call the original QDialog accept
            else:
                # Should not happen if UserRole is set correctly
                QMessageBox.warning(self, "Selection Error", "Unable to retrieve the selected world's data.")
        # else: No item selected (should not happen if the OK button was enabled)

    def get_selected_world_info(self):
        """
        Returns the dictionary with the selected world's information
        after the dialog has been accepted.
        """
        return self.selected_world
