# gui_components/profile_list_manager.py
# -*- coding: utf-8 -*-
import logging
import os
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, 
                               QWidget, QHBoxLayout, QPushButton, QStyledItemDelegate, QStyleOptionViewItem, QStyle)
from PySide6.QtCore import Qt, QLocale, Slot, QSize
from PySide6.QtGui import QIcon, QColor, QPalette
import core_logic
import config

# Import the new manager and utils
from gui_components import favorites_manager # Assuming it's in gui_components
from gui_components.empty_state_widget import EmptyStateWidget
from gui_components import icon_extractor  # For game icon extraction
from utils import resource_path # <--- Import from utils
from gui_utils import open_folder_in_file_manager  # For opening folders cross-platform

class ProfileSelectionDelegate(QStyledItemDelegate):
    """
    Custom Delegate to draw the selection with theme support:
    - Single selection: horizontal accent line at bottom of row
    - Multi selection: vertical accent bar on the left side (before favorites column)
    
    Theme colors:
    - Dark Theme: Dark grey background (#2A2A2A) with red accent (#A10808), white text
    - Light Theme: Light teal background (#C8E6E3) with teal accent (#007c8e), dark text
    """
    
    def __init__(self, parent=None, is_dark_mode=True, table_widget=None):
        super().__init__(parent)
        self._is_dark_mode = is_dark_mode
        self._table_widget = table_widget  # Reference to check selection count
    
    def set_dark_mode(self, is_dark: bool):
        """Update the delegate's theme mode. Call parent().viewport().update() after."""
        self._is_dark_mode = is_dark
    
    def set_table_widget(self, table_widget):
        """Set the table widget reference for multi-selection detection."""
        self._table_widget = table_widget
    
    def _get_selection_count(self) -> int:
        """Returns the number of selected rows."""
        if self._table_widget and self._table_widget.selectionModel():
            return len(self._table_widget.selectionModel().selectedRows())
        return 1
    
    def paint(self, painter, option, index):
        painter.save()
        
        # Check if the item is selected
        if option.state & QStyle.State_Selected:
            # Theme-specific colors
            if self._is_dark_mode:
                bg_color = QColor("#2A2A2A")       # Dark grey background
                accent_color = QColor("#A10808")   # Red accent line
                text_color = QColor(Qt.GlobalColor.white)
            else:
                bg_color = QColor("#C8E6E3")       # Light teal-tinted background for selection
                accent_color = QColor("#007c8e")   # Teal accent line
                text_color = QColor("#1E1E1E")     # Dark text for readability
            
            # 1. Custom Background
            painter.fillRect(option.rect, bg_color)
            
            # 2. Selection indicator based on selection count
            selection_count = self._get_selection_count()
            
            if selection_count > 1:
                # MULTI-SELECTION: Vertical bar on the LEFT (only for first column)
                if index.column() == 0:
                    bar_width = 4
                    painter.fillRect(
                        option.rect.x(),  # Left edge
                        option.rect.y(), 
                        bar_width, 
                        option.rect.height(), 
                        accent_color
                    )
            else:
                # SINGLE SELECTION: Horizontal line at the BOTTOM
                line_height = 4
                painter.fillRect(
                    option.rect.x(), 
                    option.rect.y() + option.rect.height() - line_height, 
                    option.rect.width(), 
                    line_height, 
                    accent_color
                )
            
            # 3. Prepare option for base painting (Text/Icon)
            # Remove Selected state so the default delegate doesn't overwrite our bg with standard selection color
            opt = QStyleOptionViewItem(option)
            opt.state &= ~QStyle.State.State_Selected 
            
            # Force Text Color based on theme
            palette = opt.palette
            palette.setColor(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text, text_color)
            palette.setColor(QPalette.ColorGroup.Normal, QPalette.ColorRole.WindowText, text_color)
            # Ensure it applies to all states involved
            palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Text, text_color)
            palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText, text_color)
            opt.palette = palette
            
            # Draw content (icon, text) using the modified option
            super().paint(painter, opt, index)
        else:
            # Standard unselected painting
            super().paint(painter, option, index)
            
        painter.restore()


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
        
        # --- Loading Trash Icon ---
        trash_icon_path = resource_path("icons/trash.png")
        self.trash_icon_path = trash_icon_path if os.path.exists(trash_icon_path) else None
        # --- End Loading Icons ---

        # --- Create Empty State Widget ---
        self.empty_state_widget = EmptyStateWidget()
        # Insert it into the same layout as the table widget
        parent_layout = self.table_widget.parent().layout() if self.table_widget.parent() else None
        if parent_layout:
            # Find the table's position in the layout and insert empty state at same position
            table_index = parent_layout.indexOf(self.table_widget)
            if table_index >= 0:
                parent_layout.insertWidget(table_index, self.empty_state_widget)
            else:
                parent_layout.addWidget(self.empty_state_widget)
        self.empty_state_widget.hide()  # Start hidden, will be shown if no profiles
        # --- End Empty State Widget ---

        # Configure the table
        self.table_widget.setObjectName("ProfileTable")
        self.table_widget.setColumnCount(4)  # Added column for delete button
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ExtendedSelection allows: Click=single, Ctrl+Click=toggle, Shift+Click=range
        self.table_widget.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Header settings
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Column 0: Favorite Icon
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)        # Column 1: Profile Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Column 2: Backup Info
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Column 3: Delete button
        self.table_widget.setColumnWidth(3, 45)  # Delete column width (same as favorites column)
        self.table_widget.verticalHeader().setDefaultSectionSize(36)  # Increased to match manage backups
        self.table_widget.setColumnWidth(0, 32)

        # Signal connections
        # Row selection change (handled by MainWindow)
        self.table_widget.itemSelectionChanged.connect(self.main_window.update_action_button_states)
        # Cell click (to handle favorite toggle)
        self.table_widget.cellClicked.connect(self.handle_favorite_toggle)
        # Double-click to open save folder
        self.table_widget.cellDoubleClicked.connect(self.handle_double_click)
        self.table_widget.itemSelectionChanged.connect(self._update_delete_buttons_state)
        # Repaint when selection changes (to switch between horizontal/vertical selection indicator)
        self.table_widget.itemSelectionChanged.connect(self._on_selection_changed)
        
        # Set Custom Delegate with current theme and table reference for multi-selection
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        is_dark = (current_theme == 'dark')
        self.delegate = ProfileSelectionDelegate(self.table_widget, is_dark_mode=is_dark, table_widget=self.table_widget)
        self.table_widget.setItemDelegate(self.delegate)

        self.retranslate_headers() # Set initial headers
        # self.update_profile_table() # Will be called by MainWindow after __init__

    def update_theme(self):
        """Update the delegate's theme mode based on current settings."""
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        is_dark = (current_theme == 'dark')
        self.delegate.set_dark_mode(is_dark)
        # Force a repaint of the table to apply the new colors
        self.table_widget.viewport().update()

    def _on_selection_changed(self):
        """Force repaint when selection changes to update the selection indicator style."""
        # This ensures the delegate repaints with correct style (horizontal vs vertical bar)
        self.table_widget.viewport().update()

    def retranslate_headers(self):
        """Update the table header labels."""
        self.table_widget.setHorizontalHeaderLabels([
            "", # Empty header for favorite column
            "Profile",
            "Backup Info",
            ""  # Empty header for delete column
        ])

    def get_selected_profile_name(self):
        """Returns the name of the first selected profile in the table (reads from the NAME column, now index 1)."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.table_widget.item(first_row_index, 1) # <-- Index 1 for the name
            if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def get_selected_profile_names(self) -> list:
        """Returns a list of all selected profile names (for multi-selection backup)."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        profile_names = []
        for row_index in selected_rows:
            name_item = self.table_widget.item(row_index.row(), 1)  # Column 1 = name
            if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                profile_names.append(name_item.data(Qt.ItemDataRole.UserRole))
        return profile_names
    
    def get_selection_count(self) -> int:
        """Returns the number of selected profiles."""
        return len(self.table_widget.selectionModel().selectedRows())

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
            # Show empty state widget instead of the table
            self.table_widget.setRowCount(0)
            self.table_widget.hide()
            self.empty_state_widget.show()
            self.table_widget.setEnabled(False)
        else:
            # Hide empty state and show table
            self.empty_state_widget.hide()
            self.table_widget.show()
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
                
                # --- Add Game Icon if available ---
                show_icons = self.main_window.current_settings.get("show_profile_icons", True)
                if show_icons:
                    game_icon = icon_extractor.get_profile_icon(profile_data, profile_name)
                    if game_icon and not game_icon.isNull():
                        name_item.setIcon(game_icon)
                        # logging.debug(f"Game icon set for profile '{profile_name}'")
                # --- End Game Icon ---

                # --- Create Info Item (Column 2) ---
                info_item = QTableWidgetItem(info_str)
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                # Insert row and items in the correct columns
                self.table_widget.insertRow(row_index)
                self.table_widget.setItem(row_index, 0, fav_item)
                self.table_widget.setItem(row_index, 1, name_item)
                self.table_widget.setItem(row_index, 2, info_item)

                # --- Create Delete Button (Column 3) ---
                delete_widget = self._create_delete_button(profile_name)
                self.table_widget.setCellWidget(row_index, 3, delete_widget)

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
        
        success, message = open_folder_in_file_manager(folder_to_open)
        
        if success:
            self.main_window.status_label.setText(f"Opened save folder for '{profile_name}'")
        else:
            logging.error(f"Error opening save folder for profile '{profile_name}': {message}")
            self.main_window.status_label.setText(f"Error opening save folder: {message}")
            
            # In case of error, try to open the parent directory if the path is a file
            if os.path.isfile(save_path):
                parent_dir = os.path.dirname(save_path)
                logging.info(f"Retrying with parent directory: {parent_dir}")
                
                success_parent, message_parent = open_folder_in_file_manager(parent_dir)
                
                if success_parent:
                    self.main_window.status_label.setText(f"Opened parent folder for '{profile_name}'")
                else:
                    logging.error(f"Error opening parent folder: {message_parent}")
                    self.main_window.status_label.setText(f"Error opening parent folder: {message_parent}")

    def _create_delete_button(self, profile_name: str) -> QWidget:
        """Create a styled delete button widget for the profile row.
        
        Styled to match the Lock checkbox in Manage Backups dialog exactly.
        """
        # Container widget with transparent background (like lock checkbox)
        button_widget = QWidget()
        button_widget.setStyleSheet("background-color: transparent;")
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        button = QPushButton()
        button.setProperty("profile_name", profile_name)
        button.setEnabled(False)  # Start disabled, will be enabled for selected row
        button.setVisible(False)  # Start hidden, will be shown only for selected row
        button.setFlat(True)  # Flat button for cleaner look
        button.setToolTip(f"Delete profile '{profile_name}'")
        
        # Set trash icon - try custom icon first, then fallback to system icon
        icon_set = False
        if self.trash_icon_path and os.path.exists(self.trash_icon_path):
            trash_icon = QIcon(self.trash_icon_path)
            if not trash_icon.isNull():
                button.setIcon(trash_icon)
                icon_set = True
                logging.debug(f"Loaded trash icon from: {self.trash_icon_path}")
        
        if not icon_set:
            # Fallback to system trash icon
            from PySide6.QtWidgets import QApplication, QStyle
            style = QApplication.instance().style()
            if style:
                system_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                button.setIcon(system_icon)
                logging.debug("Using system trash icon as fallback")
        
        # Custom button styling - Theme-aware colors
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        if current_theme == 'dark':
            hover_bg = "#353535"
            pressed_bg = "#b00020"
        else:
            hover_bg = "#D0D0D0"
            pressed_bg = "#D32F2F"
        
        button.setStyleSheet(f"""
            QPushButton {{
                width: 24px;
                height: 24px;
                min-width: 24px;
                min-height: 24px;
                max-width: 24px;
                max-height: 24px;
                border-radius: 4px;
                border: none;
                background-color: transparent;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover {{
                border: 2px solid #888888;
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                border: 2px solid {pressed_bg};
                background-color: {pressed_bg};
            }}
        """)
        
        # Set icon size to fit nicely inside the 24x24 button (leaving room for border)
        button.setIconSize(QSize(16, 16))
        
        # Connect to delete handler
        button.clicked.connect(lambda: self._on_delete_button_clicked(profile_name))
        
        button_layout.addWidget(button)
        return button_widget
    
    def _update_delete_buttons_state(self):
        """Show delete button only for the currently selected row, hide for others."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        selected_row = selected_rows[0].row() if selected_rows else -1
        
        for row in range(self.table_widget.rowCount()):
            button_widget = self.table_widget.cellWidget(row, 3)  # Column 3 is the delete button
            if button_widget:
                button = button_widget.findChild(QPushButton)
                if button:
                    # Show button only on selected row, hide on others
                    is_selected = (row == selected_row)
                    button.setVisible(is_selected)
                    button.setEnabled(is_selected)
    
    def _on_delete_button_clicked(self, profile_name: str):
        """Handle delete button click by delegating to the main window's delete handler."""
        if not profile_name or profile_name not in self.profiles:
            logging.warning(f"Delete button clicked for invalid profile: '{profile_name}'")
            return
        
        logging.debug(f"Delete button clicked for profile: '{profile_name}'")
        
        # Ensure the profile is selected in the table before calling the handler
        self.select_profile_in_table(profile_name)
        
        if hasattr(self.main_window, 'handlers') and self.main_window.handlers:
            self.main_window.handlers.handle_delete_profile()



