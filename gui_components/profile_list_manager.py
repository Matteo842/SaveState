# gui_components/profile_list_manager.py
# -*- coding: utf-8 -*-
import logging
import os
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
from PySide6.QtCore import Qt, QLocale, QCoreApplication, Slot, QSize
from PySide6.QtGui import QIcon
import core_logic
import config

# Import the new manager and utils
from gui_components import favorites_manager # Assuming it's in gui_components
from gui_utils import resource_path

class ProfileListManager:
    """Handles the QTableWidget of profiles and related action buttons."""

    def __init__(self, table_widget: QTableWidget, main_window):
        self.table_widget = table_widget
        self.main_window = main_window # Reference to the main window
        self.profiles = main_window.profiles # Access the profiles through main_window

        # --- Loading Favorite Icons ---
        star_icon_path = resource_path("icons/star.png")
        empty_star_icon_path = resource_path("icons/emptystar.png")
        self.star_icon = QIcon(star_icon_path) if os.path.exists(star_icon_path) else None
        self.empty_star_icon = QIcon(empty_star_icon_path) if os.path.exists(empty_star_icon_path) else None
        if not self.star_icon:
            logging.warning(f"Favorite icon 'star.png' not found in {star_icon_path}")
        if not self.empty_star_icon:
            logging.warning(f"Non-favorite icon 'emptystar.png' not found in {empty_star_icon_path}")
        # --- End Loading Icons ---

        # Configure the table
        self.table_widget.setObjectName("ProfileTable")
        self.table_widget.setColumnCount(3)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Header settings
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Column 0: Favorite Icon
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)        # Column 1: Profile Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Column 2: Backup Info
        self.table_widget.verticalHeader().setDefaultSectionSize(32)
        self.table_widget.setColumnWidth(0, 32)

        # Signal connections
        # Row selection change (handled by MainWindow)
        self.table_widget.itemSelectionChanged.connect(self.main_window.update_action_button_states)
        # Cell click (to handle favorite toggle)
        self.table_widget.cellClicked.connect(self.handle_favorite_toggle)
        # Double-click to open save folder
        self.table_widget.cellDoubleClicked.connect(self.handle_double_click)

        self.retranslate_headers() # Set initial headers
        # self.update_profile_table() # Will be called by MainWindow after __init__


    def retranslate_headers(self):
        """Update the table header labels."""
        self.table_widget.setHorizontalHeaderLabels([
            "", # Empty header for favorite column
            "Profile",
            "Backup Info"
        ])

    def get_selected_profile_name(self):
        """Returns the name of the selected profile in the table (reads from the NAME column, now index 1)."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.table_widget.item(first_row_index, 1) # <-- Index 1 for the name
            if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def has_selection(self) -> bool:
        """Checks if any row is currently selected in the table."""
        return bool(self.table_widget.selectionModel().selectedRows())

    def select_profile_in_table(self, profile_name_to_select):
        """Select the row corresponding to the profile name (searches in column 1)."""
        if not profile_name_to_select:
            return
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 1) # <-- Search for name in column 1
            if item and item.data(Qt.ItemDataRole.UserRole) == profile_name_to_select:
                self.table_widget.selectRow(row)
                logging.debug(f"Profile '{profile_name_to_select}' selected in table at row {row}.")
                return
        logging.warning(f"Tried to select profile '{profile_name_to_select}', but not found in table.")


    def update_profile_table(self):
        """Update QTableWidget with profiles (sorted by favorites) and backup info."""
        self.profiles = self.main_window.profiles # Reload profiles from main_window
        selected_profile_name = self.get_selected_profile_name() # Save current selection
        logging.debug(f"Updating profile table. Previously selected: {selected_profile_name}")

        # --- Load favorites status ---
        favorites_status = favorites_manager.load_favorites()
        # --- End Loading ---

        self.table_widget.setRowCount(0) # Clear the table

        # --- Sorting (Favorites first, then alphabetical) ---
        profile_names = list(self.profiles.keys())
        sorted_profiles = sorted(
            profile_names,
            key=lambda name: (not favorites_status.get(name, False), name.lower())
        )
        logging.debug(f"Profile list sorted for display (favorites first): {sorted_profiles}")
        # --- End Sorting ---

        if not sorted_profiles:
            # Show "No profile" row
            self.table_widget.setRowCount(1)
            item_fav_placeholder = QTableWidgetItem("")
            item_nome = QTableWidgetItem(
                "No profiles created."
            )
            item_info = QTableWidgetItem("")
            # Don't set UserRole for placeholder fav or set it to None
            item_nome.setData(Qt.ItemDataRole.UserRole, None)
            # Make the row non-selectable
            flags = item_nome.flags() & ~Qt.ItemFlag.ItemIsSelectable
            item_fav_placeholder.setFlags(flags)
            item_nome.setFlags(flags)
            item_info.setFlags(flags)

            self.table_widget.setItem(0, 0, item_fav_placeholder)
            self.table_widget.setItem(0, 1, item_nome)
            self.table_widget.setItem(0, 2, item_info)
            self.table_widget.setEnabled(False)
        else:
            # Populate table with sorted profiles
            self.table_widget.setEnabled(True)
            row_to_reselect = -1
            for row_index, profile_name in enumerate(sorted_profiles):
                profile_data = self.profiles.get(profile_name, {})
                is_favorite = favorites_status.get(profile_name, False)
                save_path = profile_data.get('path', '') # Get path

                # Retrieve backup info
                current_backup_base_dir = self.main_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
                # Pass save_path to get_profile_backup_summary (ensure the function accepts it)
                # If get_profile_backup_summary doesn't accept save_path, you'll need to use a different logic here
                count, last_backup_dt = core_logic.get_profile_backup_summary(profile_name, current_backup_base_dir) # Remove save_path if not needed

                info_str = ""
                if count > 0:
                    date_str = "N/D"
                    if last_backup_dt:
                        try:
                            # Use system locale for date formatting instead of app language setting
                            system_locale = QLocale.system()
                            date_str = system_locale.toString(last_backup_dt, QLocale.FormatType.ShortFormat)
                            logging.debug(f"Using system locale for date formatting: {system_locale.name()}")
                        except Exception as e:
                            logging.error(f"Error formatting last backup date for {profile_name}: {e}", exc_info=True)
                            date_str = "???"

                    backup_label_singular = "Backup"
                    backup_label_plural = "Backups"
                    last_label = "Last"
                    backup_label = backup_label_singular if count == 1 else backup_label_plural
                    info_str = f"{backup_label}: {count} | {last_label}: {date_str}"
                else:
                     info_str = "No backups"

                # --- Create Favorite Item (Column 0) ---
                fav_item = QTableWidgetItem()
                fav_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_favorite and self.star_icon:
                    fav_item.setIcon(self.star_icon)
                    fav_item.setToolTip("Remove from favorites")
                elif self.empty_star_icon: # Use empty star if available
                    fav_item.setIcon(self.empty_star_icon)
                    fav_item.setToolTip("Add to favorites")
                else: # Fallback without empty star icon
                    fav_item.setToolTip("Add/Remove favorite") # Fallback

                fav_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                fav_item.setData(Qt.ItemDataRole.UserRole, profile_name) # Save name for toggle
                fav_item.setSizeHint(QSize(32, 32))
                # --- End Creating Favorite Item ---

                # --- Create Name Item (Column 1) ---
                name_item = QTableWidgetItem(profile_name)
                name_item.setData(Qt.ItemDataRole.UserRole, profile_name) # Save name for row selection

                # --- Create Info Item (Column 2) ---
                info_item = QTableWidgetItem(info_str)
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                # Insert row and items in the correct columns
                self.table_widget.insertRow(row_index)
                self.table_widget.setItem(row_index, 0, fav_item)
                self.table_widget.setItem(row_index, 1, name_item)
                self.table_widget.setItem(row_index, 2, info_item)

                # Check if we need to reselect the row
                if profile_name == selected_profile_name:
                    row_to_reselect = row_index

            # Reselect the row
            if row_to_reselect != -1:
                logging.debug(f"Reselecting row {row_to_reselect} for profile '{selected_profile_name}'")
                self.table_widget.selectRow(row_to_reselect)
            elif selected_profile_name:
                 logging.debug(f"Previously selected profile '{selected_profile_name}' not found after update.")

        # Update button states AFTER populating the table
        self.main_window.update_action_button_states()
        logging.debug("Profile table update finished.")

    @Slot(int, int)
    def handle_favorite_toggle(self, row, column):
        """Handles the click on the cell to change the favorite status."""
        if column == 0: # Only if clicking on the first column (Favorites)
            item = self.table_widget.item(row, 0)
            if not item: return # Security check

            profile_name = item.data(Qt.ItemDataRole.UserRole)
            # Additional check that the name is valid in the current profiles
            if not profile_name or profile_name not in self.profiles:
                 logging.warning(f"Favorite toggle requested for invalid or non-existent profile: row {row}, name '{profile_name}'")
                 return

            logging.debug(f"Click on Favorites column for: '{profile_name}'")

            # Invert the status using the manager and check the success
            success = favorites_manager.toggle_favorite(profile_name)

            if success:
                # Read the status *just saved* for security
                new_status = favorites_manager.is_favorite(profile_name)

                # Update the icon and tooltip in the clicked cell
                if new_status and self.star_icon:
                    item.setIcon(self.star_icon)
                    item.setToolTip("Remove from favorites")
                elif self.empty_star_icon: # Use empty star if available
                    item.setIcon(self.empty_star_icon)
                    item.setToolTip("Add to favorites")
                else: # Fallback without empty star icon
                    item.setIcon(QIcon()) # Remove icon
                    item.setToolTip("Add/Remove favorite")

                # --- Update the table to apply favorites sorting ---
                logging.debug("Update table to apply favorites sorting...")
                self.update_profile_table()
                # Note: update_profile_table() will attempt to reselect the last selected row

            else:
                # The saving failed (manager has already logged the error)
                QMessageBox.warning(self.main_window,
                                    "Error",
                                    f"Unable to save favorite status for '{profile_name}'.")
                # We don't update the icon in the GUI if the saving fails
                
    @Slot(int, int)
    def handle_double_click(self, row, column):
        """Handles double-click on a profile row to open the save folder."""
        # Skip if clicking on the favorite column (column 0)
        if column == 0:
            return
            
        # Get the profile name from the clicked row
        profile_name = None
        item = self.table_widget.item(row, 1)  # Get item from name column (index 1)
        if item:
            profile_name = item.data(Qt.ItemDataRole.UserRole)
        
        if not profile_name or profile_name not in self.profiles:
            logging.warning(f"Double-click on invalid or non-existent profile: row {row}, name '{profile_name}'")
            return
            
        # Get the profile data
        profile_data = self.profiles.get(profile_name, {})
        
        # Check if profile has a path or paths
        save_path = None
        if 'paths' in profile_data and isinstance(profile_data['paths'], list) and profile_data['paths']:
            # Use the first valid path from the paths list
            for path in profile_data['paths']:
                if isinstance(path, str) and os.path.exists(path):
                    save_path = path
                    break
        elif 'path' in profile_data and isinstance(profile_data['path'], str):
            save_path = profile_data['path']
        
        if not save_path or not os.path.exists(save_path):
            logging.warning(f"Cannot open save folder for profile '{profile_name}': path does not exist")
            self.main_window.status_label.setText(f"Save folder for '{profile_name}' does not exist")
            return
        
        # Check if the path is a file or directory
        folder_to_open = save_path
        if os.path.isfile(save_path):
            # If it's a file, get its parent directory
            folder_to_open = os.path.dirname(save_path)
            logging.info(f"Save path is a file, opening its parent directory: {folder_to_open}")
            
        # Open the save folder using the system's file explorer
        logging.info(f"Opening save folder for profile '{profile_name}': {folder_to_open}")
        try:
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                # On Windows, use explorer.exe
                subprocess.Popen(f'explorer "{folder_to_open}"')
            elif platform.system() == "Darwin":
                # On macOS, use open
                subprocess.Popen(["open", folder_to_open])
            else:
                # On Linux, use xdg-open
                subprocess.Popen(["xdg-open", folder_to_open])
                
            self.main_window.status_label.setText(f"Opened save folder for '{profile_name}'")
        except Exception as e:
            logging.error(f"Error opening save folder for profile '{profile_name}': {e}")
            self.main_window.status_label.setText(f"Error opening save folder: {str(e)}")
            
            # In case of error, try to open the parent directory if the path is a file
            if os.path.isfile(save_path):
                try:
                    parent_dir = os.path.dirname(save_path)
                    logging.info(f"Retrying with parent directory: {parent_dir}")
                    
                    if platform.system() == "Windows":
                        subprocess.Popen(f'explorer "{parent_dir}"')
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", parent_dir])
                    else:
                        subprocess.Popen(["xdg-open", parent_dir])
                        
                    self.main_window.status_label.setText(f"Opened parent folder for '{profile_name}'")
                except Exception as e2:
                    logging.error(f"Error opening parent folder: {e2}")
                    self.main_window.status_label.setText(f"Error opening parent folder: {str(e2)}")