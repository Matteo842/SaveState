# dialogs/emulator_selection_dialog.py
# -*- coding: utf-8 -*-

import html
import logging
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox, QAbstractItemView,
    QListWidgetItem, QMessageBox, QCheckBox, QHBoxLayout, QWidget, QStackedLayout,
    QPushButton
)
from PySide6.QtCore import Qt, Slot
from dialogs.selection_utils import apply_profile_selection_style

log = logging.getLogger(__name__)


def _group_profiles(profile_data_list):
    """
    Groups profiles that are the same game found in different folders.

    Switch emulators (Yuzu family) give each save a 'title_id' and a folder 'label'.
    Saves with the same title_id become one game with several folder options.
    Other profiles stay one game each, in their original order.

    Returns a list of {'name': game name, 'options': [profile dicts]}.
    """
    groups = []
    groups_by_title_id = {}
    for profile_data in profile_data_list:
        title_id = profile_data.get('title_id')
        folder_label = profile_data.get('label')
        if title_id and folder_label:
            if title_id in groups_by_title_id:
                groups_by_title_id[title_id]['options'].append(profile_data)
                continue
            # Show the game name without the "(... Folder)" suffix
            game_name = profile_data.get('name', title_id)
            suffix = f" ({folder_label})"
            if game_name.endswith(suffix):
                game_name = game_name[:-len(suffix)]
            group = {'name': game_name, 'options': [profile_data]}
            groups_by_title_id[title_id] = group
            groups.append(group)
        else:
            profile_id = profile_data.get('id', 'Unknown ID')
            groups.append({'name': profile_data.get('name', profile_id), 'options': [profile_data]})

    # Folder-grouped games are shown together, sorted by name
    if groups_by_title_id:
        groups.sort(key=lambda group: group['name'].casefold())
    return groups


def _latest_save_time(paths):
    """Returns the newest modification time of the files in the save folders (0 if none)."""
    latest = 0.0
    for save_path in paths or []:
        for root, _dirs, files in os.walk(save_path):
            for file_name in files:
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(root, file_name)))
                except OSError:
                    pass
    return latest

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

        self._folder_groups = []      # All games selected on the game list
        self._multi_folder_groups = []  # The selected games with more than one folder
        self._folder_step = 0         # Which multi-folder game the folder page shows
        self._chosen_profiles = {}    # {id(game group): chosen profile dict}

        # --- Layout ---
        layout = QVBoxLayout(self)

        # Two pages in the same dialog (like RetroArch):
        # page 0 = game list, page 1 = save folder choice
        self.stack_container = QWidget(self)
        self.stack = QStackedLayout(self.stack_container)
        layout.addWidget(self.stack_container)

        game_page = QWidget(self)
        game_layout = QVBoxLayout(game_page)
        game_layout.setContentsMargins(0, 0, 0, 0)

        # --- Label ---
        label = QLabel(
            f"The following profiles/games have been found for {emulator_name}.\n"
            "Select one or more games to add:"
        )
        label.setWordWrap(True)
        game_layout.addWidget(label)

        # --- List Widget ---
        self.profile_list_widget = QListWidget()
        self.profile_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.profile_selection_delegate = apply_profile_selection_style(
            self.profile_list_widget, parent
        )

        # Populate the list widget
        if not self.profile_data_list:
             # Should not happen if called correctly, but handle gracefully
             item = QListWidgetItem("(No profiles found)")
             item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable) # Make it unselectable
             self.profile_list_widget.addItem(item)
        else:
            # One row per game. A game saved in more than one folder
            # (e.g. Lichii saving in the Eden folder) is shown once;
            # the folder is chosen on the next page.
            for group in _group_profiles(self.profile_data_list):
                display_name = group['name']
                folder_count = len(group['options'])
                if folder_count > 1:
                    display_name = f"{display_name}   ({folder_count} folders)"
                item = QListWidgetItem(display_name)
                # Store the game group (name + folder options) in the item's data
                item.setData(Qt.ItemDataRole.UserRole, group)
                self.profile_list_widget.addItem(item)

        self.profile_list_widget.itemSelectionChanged.connect(self._update_button_state)
        self.profile_list_widget.itemDoubleClicked.connect(self.accept) # Double-click accepts

        selection_row = QHBoxLayout()
        selection_row.addStretch()
        self.select_all_checkbox = QCheckBox("Select all games")
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.clicked.connect(self._toggle_all_profiles)
        selection_row.addWidget(self.select_all_checkbox)
        game_layout.addLayout(selection_row)
        game_layout.addWidget(self.profile_list_widget)
        self.stack.addWidget(game_page)

        # --- Page 1: save folder choice ---
        folder_page = QWidget(self)
        folder_layout = QVBoxLayout(folder_page)
        folder_layout.setContentsMargins(0, 0, 0, 0)

        folder_header = QHBoxLayout()
        self.back_button = QPushButton("←  Back")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 4px 8px; "
            "min-width: 0px; text-align: left; } "
            "QPushButton:hover { text-decoration: underline; }"
        )
        self.back_button.clicked.connect(self._on_back)
        folder_header.addWidget(self.back_button)
        folder_header.addStretch()
        folder_layout.addLayout(folder_header)

        # Text set for each game in _show_folder_step
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label)

        # Same selection list as the game list (like RetroArch), one folder per row
        self.folder_list_widget = QListWidget()
        self.folder_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.folder_selection_delegate = apply_profile_selection_style(
            self.folder_list_widget, parent
        )
        self.folder_list_widget.itemSelectionChanged.connect(self._update_button_state)
        self.folder_list_widget.itemDoubleClicked.connect(self.accept)  # Double-click accepts
        folder_layout.addWidget(self.folder_list_widget)
        self.stack.addWidget(folder_page)

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
        if ok_button and self.stack.currentIndex() == 1:
            # Folder page: "Next" until the last multi-folder game,
            # then add everything selected on the game list
            ok_button.setEnabled(bool(self.folder_list_widget.selectedItems()))
            if self._folder_step < len(self._multi_folder_groups) - 1:
                ok_button.setText("Next")
            else:
                count = len(self._folder_groups)
                ok_button.setText("Add Game" if count == 1 else f"Add {count} Games")
            ok_button.setDefault(True)
            return
        if ok_button:
            selected_groups = self._selected_groups()
            selection_count = len(selected_groups)
            ok_button.setEnabled(selection_count > 0)
            if any(len(group['options']) > 1 for group in selected_groups):
                ok_button.setText("Next")  # The folder choice comes next
            else:
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

    def _selected_groups(self):
        """Returns the game groups selected in the game list."""
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.profile_list_widget.selectedItems()
            if item.flags() & Qt.ItemFlag.ItemIsSelectable
            and item.data(Qt.ItemDataRole.UserRole)
        ]

    def _remember_folder_choice(self):
        """Saves the folder selected on the folder page for the game it shows."""
        selected = self.folder_list_widget.selectedItems()
        if selected:
            group = self._multi_folder_groups[self._folder_step]
            self._chosen_profiles[id(group)] = selected[0].data(Qt.ItemDataRole.UserRole)

    @Slot()
    def _on_back(self):
        """Folder page -> previous multi-folder game, or the game list (the selection is kept)."""
        self._remember_folder_choice()
        if self._folder_step > 0:
            self._show_folder_step(self._folder_step - 1)
        else:
            self.stack.setCurrentIndex(0)
            self._update_button_state()

    def _show_folder_step(self, step):
        """Shows the folder list of one multi-folder game (one game per step)."""
        self._folder_step = step
        group = self._multi_folder_groups[step]
        total = len(self._multi_folder_groups)
        counter = f" ({step + 1} of {total})" if total > 1 else ""
        self.folder_label.setText(
            f"<b>{html.escape(group['name'])}</b>{counter} has saves in more than one folder.<br>"
            "Select the folder to use (the most recently saved one is selected):"
        )

        self.folder_list_widget.clear()
        chosen = self._chosen_profiles.get(id(group))
        selected_row = 0
        for row, (text, save_path, profile_data) in enumerate(_folder_choices(group['options'])):
            item = QListWidgetItem(text)
            item.setToolTip(save_path)
            item.setData(Qt.ItemDataRole.UserRole, profile_data)
            self.folder_list_widget.addItem(item)
            if chosen is not None and chosen == profile_data:
                selected_row = row  # Coming back: keep the earlier choice
        self.folder_list_widget.setCurrentRow(selected_row)

        self.stack.setCurrentIndex(1)
        self._update_button_state()

    def accept(self):
        """
        OK / double-click. On the game list: go to the folder page if a selected
        game has saves in more than one folder, otherwise add the games.
        On the folder page: go to the next multi-folder game, or add the games
        with the chosen folders after the last one.
        """
        if self.stack.currentIndex() == 1:
            if not self.folder_list_widget.selectedItems():
                return
            self._remember_folder_choice()
            if self._folder_step < len(self._multi_folder_groups) - 1:
                self._show_folder_step(self._folder_step + 1)
                return
            selected_groups = self._folder_groups
        else:
            selected_groups = self._selected_groups()
            multi_folder_groups = [g for g in selected_groups if len(g['options']) > 1]
            self._chosen_profiles = {}
            if multi_folder_groups:
                self._folder_groups = selected_groups
                self._multi_folder_groups = multi_folder_groups
                self._show_folder_step(0)
                return

        if selected_groups:
            self.selected_profiles_data = [
                self._chosen_profiles.get(id(group)) or group['options'][0]
                for group in selected_groups
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




def _folder_choices(options):
    """
    Returns the folder rows for one game saved in more than one folder,
    as (text, save path, profile dict). The most recently saved folder
    comes first and is marked "Latest".
    """
    # Newest saves first; folders with the same time keep the scan order
    timed_options = [(_latest_save_time(p.get('paths', [])), p) for p in options]
    timed_options.sort(key=lambda option: option[0], reverse=True)

    # Same folder twice (different Switch users): add the user folder to tell them apart
    labels = [p.get('label') or "Folder" for _time, p in timed_options]

    choices = []
    for index, (save_time, profile_data) in enumerate(timed_options):
        text = labels[index]
        save_path = (profile_data.get('paths') or [""])[0]
        if labels.count(text) > 1 and save_path:
            user_id = os.path.basename(os.path.dirname(save_path))
            text += f" · user {user_id[:8]}"
        if save_time > 0:
            date_text = datetime.fromtimestamp(save_time).strftime("%Y-%m-%d %H:%M")
            text += f" — {'Latest — ' if index == 0 else ''}last saved {date_text}"
        else:
            text += " — no save files"
        choices.append((text, save_path, profile_data))
    return choices
