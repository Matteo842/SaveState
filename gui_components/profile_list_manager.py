# gui_components/profile_list_manager.py
# -*- coding: utf-8 -*-
import logging
import os
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, 
                               QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QStyledItemDelegate,
                               QStyleOptionViewItem, QStyle, QTextEdit, QLabel, QApplication)
from PySide6.QtCore import Qt, QLocale, Slot, QSize, Signal, QTimer, QPoint, QEvent
from PySide6.QtGui import QIcon, QColor, QPalette, QPainter
import core_logic
import config

# Import the new manager and utils
from gui_components import favorites_manager # Assuming it's in gui_components
from gui_components import notes_manager  # For profile notes
from gui_components.empty_state_widget import EmptyStateWidget
from gui_components import icon_extractor  # For game icon extraction
from utils import resource_path # <--- Import from utils
from gui_utils import open_folder_in_file_manager  # For opening folders cross-platform


class NoteOverlayButton(QPushButton):
    """Small floating button showing note icon, positioned over column 1 of a table row.
    Emits signals on hover enter/leave for popup management."""
    hover_entered = Signal(str)  # profile_name
    hover_left = Signal()

    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self.hover_entered.emit(self.profile_name)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)


class NotePopupWidget(QWidget):
    """Speech-bubble style popup for displaying and editing profile notes.
    Two modes:
    - Preview: semi-transparent with visible background, completely non-interactive
              (mouse events pass through via WA_TransparentForMouseEvents)
    - Edit: solid/opaque, editable text with Save/Cancel buttons
    """
    note_saved = Signal(str, str)  # profile_name, note_text

    def __init__(self, parent=None, is_dark_mode=True):
        super().__init__(parent)
        self._profile_name = ""
        self._original_text = ""  # For cancel/discard
        self._edit_mode = False
        self._is_dark_mode = is_dark_mode
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(350)  # ms delay before hiding in preview mode
        self._hide_timer.timeout.connect(self._do_hide)
        self._event_filter_installed = False

        # Setup UI
        self.setFixedWidth(380)
        self.setMinimumHeight(80)
        self.setMaximumHeight(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header label
        self.header_label = QLabel()
        layout.addWidget(self.header_label)

        # Text area for note content
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Write your note here...")
        self.text_edit.setMinimumHeight(50)
        self.text_edit.setMaximumHeight(220)
        self.text_edit.setAcceptRichText(False)  # Plain text only
        layout.addWidget(self.text_edit)

        # Save & Cancel button row (visible only in edit mode) - INSIDE the popup box
        self.button_row = QWidget()
        btn_layout = QHBoxLayout(self.button_row)
        btn_layout.setContentsMargins(0, 6, 0, 2)
        btn_layout.setSpacing(8)
        btn_layout.addStretch(1)

        self.cancel_button = QPushButton("Cancel \u2717")
        self.cancel_button.setFixedHeight(28)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_and_close)
        btn_layout.addWidget(self.cancel_button)

        self.save_close_button = QPushButton("Save \u2713")
        self.save_close_button.setFixedHeight(28)
        self.save_close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_close_button.clicked.connect(self.save_and_close)
        btn_layout.addWidget(self.save_close_button)

        layout.addWidget(self.button_row)
        self.button_row.hide()  # Hidden in preview mode

        self.hide()  # Start hidden
        self._apply_style()

    def set_dark_mode(self, is_dark: bool):
        """Update the popup's theme mode."""
        self._is_dark_mode = is_dark
        self._apply_style()

    def _apply_style(self):
        """Apply styling based on current mode (preview/edit) and theme."""
        if self._edit_mode:
            self._apply_edit_style()
        else:
            self._apply_preview_style()

    def _apply_preview_style(self):
        """Semi-transparent preview: visible background (~35% alpha), completely non-interactive."""
        self._edit_mode = False
        self.text_edit.setReadOnly(True)
        self.button_row.hide()
        # Make the entire popup non-interactive - mouse events pass through
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        if self._is_dark_mode:
            self.setStyleSheet("""
                NotePopupWidget {
                    background-color: rgba(25, 25, 25, 170);
                    border: 1px solid rgba(120, 120, 120, 120);
                    border-radius: 8px;
                }
            """)
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    color: rgba(255, 255, 255, 255);
                    border: none;
                    font-size: 10pt;
                }
                QTextEdit QScrollBar { width: 0px; height: 0px; }
            """)
            self.header_label.setStyleSheet(
                "color: rgba(255, 255, 255, 255); font-weight: bold; font-size: 9pt;")
        else:
            self.setStyleSheet("""
                NotePopupWidget {
                    background-color: rgba(240, 240, 240, 153);
                    border: 1px solid rgba(140, 140, 140, 120);
                    border-radius: 8px;
                }
            """)
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    color: rgba(0, 0, 0, 255);
                    border: none;
                    font-size: 10pt;
                }
                QTextEdit QScrollBar { width: 0px; height: 0px; }
            """)
            self.header_label.setStyleSheet(
                "color: rgba(0, 0, 0, 255); font-weight: bold; font-size: 9pt;")

    def _apply_edit_style(self):
        """Solid, editable mode with Save/Cancel buttons."""
        self._edit_mode = True
        # Re-enable mouse interaction
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.text_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction)
        self.text_edit.setReadOnly(False)
        self.text_edit.setFocus()
        self.button_row.show()
        if self._is_dark_mode:
            self.setStyleSheet("""
                NotePopupWidget {
                    background-color: rgba(30, 30, 30, 255);
                    border: 2px solid #C4A000;
                    border-radius: 8px;
                }
            """)
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background-color: rgba(20, 20, 20, 255);
                    color: #ffffff;
                    border: 1px solid #555;
                    border-radius: 4px;
                    font-size: 10pt;
                    padding: 4px;
                }
            """)
            self.header_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 9pt;")
            self.save_close_button.setStyleSheet("""
                QPushButton {
                    background-color: #C4A000;
                    color: #1a1a1a;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 16px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #D4B400;
                }
            """)
            self.cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #444;
                    color: #ddd;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 16px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #555;
                }
            """)
        else:
            self.setStyleSheet("""
                NotePopupWidget {
                    background-color: rgba(255, 255, 255, 255);
                    border: 2px solid #007c8e;
                    border-radius: 8px;
                }
            """)
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background-color: rgba(250, 250, 250, 255);
                    color: #1E1E1E;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    font-size: 10pt;
                    padding: 4px;
                }
            """)
            self.header_label.setStyleSheet("color: #333; font-weight: bold; font-size: 9pt;")
            self.save_close_button.setStyleSheet("""
                QPushButton {
                    background-color: #007c8e;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 16px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #009aad;
                }
            """)
            self.cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #ccc;
                    color: #333;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 16px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #bbb;
                }
            """)

    def show_for_profile(self, profile_name, note_text, pos, edit=False):
        """Show the popup for a given profile at the specified position."""
        self._hide_timer.stop()
        self._profile_name = profile_name
        self._original_text = note_text  # Store original for cancel
        self.header_label.setText(f"\U0001f4dd {profile_name}")
        self.text_edit.setPlainText(note_text)
        if edit:
            self._apply_edit_style()
        else:
            self._apply_preview_style()
        self.adjustSize()
        # Ensure popup stays within the parent widget bounds
        if self.parent():
            parent_rect = self.parent().rect()
            x = min(pos.x(), parent_rect.width() - self.width() - 5)
            y = min(pos.y(), parent_rect.height() - self.height() - 5)
            x = max(5, x)
            y = max(5, y)
            self.move(x, y)
        else:
            self.move(pos)
        self.show()
        self.raise_()
        # Install event filter to catch clicks outside the popup
        if edit:
            self._install_click_outside_filter()

    def _install_click_outside_filter(self):
        """Install event filter on the application to detect clicks outside."""
        if not self._event_filter_installed:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._event_filter_installed = True

    def _remove_click_outside_filter(self):
        """Remove the click-outside event filter."""
        if self._event_filter_installed:
            app = QApplication.instance()
            if app:
                app.removeEventFilter(self)
            self._event_filter_installed = False

    def eventFilter(self, watched, event):
        """Catch mouse clicks outside the popup to save and close."""
        if event.type() == QEvent.Type.MouseButtonPress:
            if self._edit_mode and self.isVisible():
                # Use mapToGlobal for reliable position comparison
                click_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                popup_tl = self.mapToGlobal(QPoint(0, 0))
                popup_br = self.mapToGlobal(QPoint(self.width(), self.height()))
                from PySide6.QtCore import QRect
                popup_global_rect = QRect(popup_tl, popup_br)
                if not popup_global_rect.contains(click_pos):
                    self.save_and_close()
                    return False  # Don't consume the click event
        return super().eventFilter(watched, event)

    def switch_to_edit_mode(self):
        """Switch from preview to edit mode."""
        self._hide_timer.stop()
        if not self._edit_mode:
            self._original_text = self.text_edit.toPlainText()
            self._apply_edit_style()
            self._install_click_outside_filter()

    def schedule_hide(self):
        """Schedule a delayed hide (for hover leave transitions)."""
        if not self._edit_mode:
            self._hide_timer.start()

    def cancel_hide(self):
        """Cancel any pending hide."""
        self._hide_timer.stop()

    def _do_hide(self):
        """Actually hide the popup (called by timer)."""
        if not self._edit_mode:
            self.hide()

    def save_and_close(self):
        """Save the current note text and close the popup."""
        self._remove_click_outside_filter()
        if self._profile_name:
            new_text = self.text_edit.toPlainText()
            self.note_saved.emit(self._profile_name, new_text)
        self._edit_mode = False
        self._hide_timer.stop()
        self.button_row.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

    def cancel_and_close(self):
        """Discard changes and close the popup without saving."""
        self._remove_click_outside_filter()
        self._edit_mode = False
        self._hide_timer.stop()
        self.button_row.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

    @property
    def is_edit_mode(self):
        return self._edit_mode

    @property
    def current_profile(self):
        return self._profile_name

    def keyPressEvent(self, event):
        """Handle Escape to cancel the popup."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_and_close()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        """Required override for QWidget subclasses to render stylesheet backgrounds.
        Without this, background-color in stylesheets is completely ignored."""
        from PySide6.QtWidgets import QStyleOption
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)
        p.end()

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

        # --- Loading Note Icon ---
        note_icon_path = resource_path("icons/note.png")
        self.note_icon_path = note_icon_path if os.path.exists(note_icon_path) else None
        if not self.note_icon_path:
            logging.info("Note icon 'note.png' not found. Will use fallback text.")
        # --- End Loading Note Icon ---

        # --- Note Overlay System ---
        self._note_overlay_buttons = []  # List of active NoteOverlayButton instances
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        is_dark = (current_theme == 'dark')
        # Create the shared note popup widget (child of main window for proper positioning)
        self.note_popup = NotePopupWidget(parent=self.main_window, is_dark_mode=is_dark)
        self.note_popup.note_saved.connect(self._on_note_saved)
        # --- End Note Overlay System ---

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
        
        # Scroll: reposition note overlays and hide popup
        self.table_widget.verticalScrollBar().valueChanged.connect(self._reposition_note_overlays)
        self.table_widget.verticalScrollBar().valueChanged.connect(lambda: self._dismiss_note_popup_if_preview())
        # Resize: reposition buttons when columns are resized
        self.table_widget.horizontalHeader().sectionResized.connect(self._reposition_note_overlays)

        # Set Custom Delegate with current theme and table reference for multi-selection
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
        # Update note popup theme
        if hasattr(self, 'note_popup'):
            self.note_popup.set_dark_mode(is_dark)
        # Rebuild note overlays with updated theme
        if hasattr(self, '_note_overlay_buttons'):
            self._create_note_overlays()
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
    
    def is_selected_profile_group(self) -> bool:
        """Check if the first selected profile is a group profile."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            return False
        
        first_row_index = selected_rows[0].row()
        name_item = self.table_widget.item(first_row_index, 1)
        if name_item:
            # Check the stored group flag
            return name_item.data(Qt.ItemDataRole.UserRole + 1) == "group"
        return False
    
    def get_selected_group_members(self) -> list:
        """Get the list of member profile names if a group is selected."""
        profile_name = self.get_selected_profile_name()
        if not profile_name:
            return []
        
        profile_data = self.profiles.get(profile_name, {})
        if core_logic.is_group_profile(profile_data):
            return core_logic.get_group_member_profiles(profile_name, self.profiles)
        return []

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
        """Update QTableWidget with profiles (sorted by favorites) and backup info.
        
        Uses get_visible_profiles() to filter out profiles that are members of groups,
        showing only standalone profiles and groups themselves.
        """
        self.profiles = self.main_window.profiles # Reload profiles from main_window
        selected_profile_name = self.get_selected_profile_name() # Save current selection
        logging.debug(f"Updating profile table. Previously selected: {selected_profile_name}")

        # --- Load favorites status ---
        favorites_status = favorites_manager.load_favorites()
        # --- End Loading ---

        self.table_widget.setRowCount(0) # Clear the table

        # --- Get visible profiles (filters out grouped profiles) ---
        visible_profiles = core_logic.get_visible_profiles(self.profiles)
        
        # --- Sorting (Favorites first, then alphabetical) ---
        profile_names = list(visible_profiles.keys())
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
                is_group = core_logic.is_group_profile(profile_data)
                save_path = profile_data.get('path', '') # Get path (empty for groups)

                # Retrieve backup info - different for groups vs regular profiles
                current_backup_base_dir = self.main_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
                
                if is_group:
                    # For groups, show aggregated info from all member profiles
                    member_profiles = core_logic.get_group_member_profiles(profile_name, self.profiles)
                    total_count = 0
                    latest_backup_dt = None
                    for member_name in member_profiles:
                        member_data = self.profiles.get(member_name, {})
                        m_count, m_last_dt = core_logic.get_profile_backup_summary(member_name, current_backup_base_dir, profile_data=member_data)
                        total_count += m_count
                        if m_last_dt and (latest_backup_dt is None or m_last_dt > latest_backup_dt):
                            latest_backup_dt = m_last_dt
                    count = total_count
                    last_backup_dt = latest_backup_dt
                else:
                    count, last_backup_dt = core_logic.get_profile_backup_summary(profile_name, current_backup_base_dir, profile_data=profile_data)

                info_str = ""
                if is_group:
                    # Show profile count in group + backup info
                    member_count = len(core_logic.get_group_member_profiles(profile_name, self.profiles))
                    if count > 0:
                        date_str = "N/D"
                        if last_backup_dt:
                            try:
                                system_locale = QLocale.system()
                                date_str = system_locale.toString(last_backup_dt, QLocale.FormatType.ShortFormat)
                            except Exception:
                                date_str = "???"
                        info_str = f"Group ({member_count}) | Last: {date_str}"
                    else:
                        info_str = f"Group ({member_count} profiles)"
                elif count > 0:
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
                
                # --- Add Icon (Game icon for profiles, folder icon for groups) ---
                show_icons = self.main_window.current_settings.get("show_profile_icons", True)
                if is_group:
                    # Use folder icon for groups
                    from PySide6.QtWidgets import QApplication, QStyle
                    style = QApplication.instance().style()
                    if style:
                        folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                        name_item.setIcon(folder_icon)
                    # Store group flag for context menu handling
                    name_item.setData(Qt.ItemDataRole.UserRole + 1, "group")
                elif show_icons:
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
        
        # --- Create note overlay buttons for profiles with notes ---
        self._create_note_overlays()
        # --- End note overlays ---

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
        """Handles double-click on a profile row to open the save folder.
        
        For group profiles, opens the Edit Group dialog instead.
        """
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
        
        # Check if this is a group profile - open Edit Group dialog instead
        import core_logic
        if core_logic.is_group_profile(profile_data):
            logging.info(f"Double-click on group '{profile_name}': opening Edit Group dialog")
            # Trigger the edit group handler if available
            if hasattr(self.main_window, 'handlers') and hasattr(self.main_window.handlers, 'handle_edit_group'):
                self.main_window.handlers.handle_edit_group()
            else:
                logging.warning(f"Cannot open Edit Group dialog: handler not available")
                self.main_window.status_label.setText(f"Right-click on '{profile_name}' to edit group settings")
            return
        
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
        """Show delete button for all selected rows, hide for others."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        selected_row_indices = {row.row() for row in selected_rows}  # Use set for O(1) lookup
        
        for row in range(self.table_widget.rowCount()):
            button_widget = self.table_widget.cellWidget(row, 3)  # Column 3 is the delete button
            if button_widget:
                button = button_widget.findChild(QPushButton)
                if button:
                    # Show button on ALL selected rows, hide on others
                    is_selected = (row in selected_row_indices)
                    button.setVisible(is_selected)
                    button.setEnabled(is_selected)
    
    def _on_delete_button_clicked(self, profile_name: str):
        """Handle delete button click by delegating to the main window's delete handler.
        
        Preserves multi-selection: if multiple profiles are selected, all will be processed.
        Only selects the clicked profile if no row is currently selected.
        """
        if not profile_name or profile_name not in self.profiles:
            logging.warning(f"Delete button clicked for invalid profile: '{profile_name}'")
            return
        
        logging.debug(f"Delete button clicked for profile: '{profile_name}'")
        
        # Only select the profile if there's no current selection
        # This preserves multi-selection when user clicks delete on one of the selected profiles
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            self.select_profile_in_table(profile_name)
        
        if hasattr(self.main_window, 'handlers') and self.main_window.handlers:
            self.main_window.handlers.handle_delete_profile()


    # ========================================================================
    # NOTE OVERLAY SYSTEM
    # ========================================================================

    def _clear_note_overlays(self):
        """Remove all existing note overlay buttons from the viewport."""
        for btn in self._note_overlay_buttons:
            try:
                btn.hover_entered.disconnect()
                btn.hover_left.disconnect()
                btn.clicked.disconnect()
                btn.deleteLater()
            except Exception:
                pass
        self._note_overlay_buttons.clear()

    def _create_note_overlays(self):
        """Create floating note buttons for all rows that have notes.
        Buttons are children of the table viewport, positioned over column 1."""
        self._clear_note_overlays()

        all_notes = notes_manager.load_notes()
        if not all_notes:
            return

        current_theme = self.main_window.current_settings.get('theme', 'dark')
        is_dark = (current_theme == 'dark')
        hover_bg = "#353535" if is_dark else "#D0D0D0"

        viewport = self.table_widget.viewport()

        for row in range(self.table_widget.rowCount()):
            name_item = self.table_widget.item(row, 1)
            if not name_item:
                continue
            profile_name = name_item.data(Qt.ItemDataRole.UserRole)
            if not profile_name or profile_name not in all_notes:
                continue

            # Create the note button as a child of the viewport
            btn = NoteOverlayButton(profile_name, parent=viewport)
            btn.setFlat(True)

            # Set icon or fallback text
            if self.note_icon_path and os.path.exists(self.note_icon_path):
                btn.setIcon(QIcon(self.note_icon_path))
                btn.setIconSize(QSize(18, 18))
            else:
                btn.setText("\U0001f4dd")

            btn.setFixedSize(26, 26)
            #btn.setToolTip(f"Note for '{profile_name}'")

            # Transparent square button styling (matching delete button pattern)
            btn.setStyleSheet(f"""
                QPushButton {{
                    width: 26px;
                    height: 26px;
                    min-width: 26px;
                    min-height: 26px;
                    max-width: 26px;
                    max-height: 26px;
                    border-radius: 4px;
                    border: none;
                    background-color: transparent;
                    padding: 0px;
                    margin: 0px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
            """)

            # Connect signals
            btn.hover_entered.connect(self._on_note_hover_enter)
            btn.hover_left.connect(self._on_note_hover_leave)
            btn.clicked.connect(lambda checked=False, pn=profile_name: self._on_note_button_clicked(pn))

            # Store row index as a property for repositioning
            btn.setProperty("row_index", row)
            self._note_overlay_buttons.append(btn)
            btn.show()

        # Position all buttons correctly
        self._reposition_note_overlays()

    def _reposition_note_overlays(self):
        """Reposition all note overlay buttons at the far right of the name column."""
        viewport = self.table_widget.viewport()
        if not viewport:
            return
        viewport_rect = viewport.rect()

        for btn in self._note_overlay_buttons:
            row = btn.property("row_index")
            if row is None:
                btn.hide()
                continue

            # Get the visual rect for the name cell (column 1)
            name_item = self.table_widget.item(row, 1)
            if not name_item:
                btn.hide()
                continue

            item_rect = self.table_widget.visualItemRect(name_item)

            # Check if the row is visible in the viewport
            if not viewport_rect.intersects(item_rect):
                btn.hide()
                continue

            # Position: always at the far right edge of the column 1
            btn_x = item_rect.right() - btn.width() - 4
            btn_y = item_rect.top() + (item_rect.height() - btn.height()) // 2
            
            btn.move(btn_x, btn_y)
            btn.show()
            btn.raise_()

    def _get_popup_position(self, profile_name):
        """Calculate the popup position in main window coordinates, below the note button."""
        for btn in self._note_overlay_buttons:
            if btn.profile_name == profile_name:
                # Map button's bottom-left to main window coordinates
                btn_bottom_left = btn.mapTo(self.main_window, QPoint(0, btn.height()))
                return QPoint(btn_bottom_left.x() - 50, btn_bottom_left.y() + 4)
        # Fallback: center of table mapped to main window
        table_center = self.table_widget.mapTo(self.main_window,
                                                QPoint(self.table_widget.width() // 3,
                                                       self.table_widget.height() // 3))
        return table_center

    def _on_note_hover_enter(self, profile_name):
        """Show note popup in preview mode when hovering the note button."""
        # Don't interrupt edit mode on a different profile
        if self.note_popup.isVisible() and self.note_popup.is_edit_mode:
            return
        self.note_popup.cancel_hide()
        note_text = notes_manager.get_note(profile_name)
        if note_text:
            pos = self._get_popup_position(profile_name)
            self.note_popup.show_for_profile(profile_name, note_text, pos, edit=False)

    def _on_note_hover_leave(self):
        """Schedule popup hide when mouse leaves the note button."""
        if not self.note_popup.is_edit_mode:
            self.note_popup.schedule_hide()

    def _on_note_button_clicked(self, profile_name):
        """Handle click on note button: toggle between edit mode and close."""
        if self.note_popup.isVisible() and self.note_popup.current_profile == profile_name:
            if self.note_popup.is_edit_mode:
                # Already editing this profile - save and close
                self.note_popup.save_and_close()
            else:
                # Preview mode - switch to edit
                self.note_popup.switch_to_edit_mode()
        else:
            # Show popup in edit mode for this profile
            if self.note_popup.isVisible():
                self.note_popup.save_and_close()
            note_text = notes_manager.get_note(profile_name)
            pos = self._get_popup_position(profile_name)
            self.note_popup.show_for_profile(profile_name, note_text, pos, edit=True)

    def show_note_editor(self, profile_name):
        """Public method: open the note popup in edit mode for a profile.
        Called from context menu 'Add/Edit Note' action."""
        if self.note_popup.isVisible():
            self.note_popup.save_and_close()
        note_text = notes_manager.get_note(profile_name)
        pos = self._get_popup_position(profile_name)
        self.note_popup.show_for_profile(profile_name, note_text, pos, edit=True)

    def _on_note_saved(self, profile_name, note_text):
        """Handle note_saved signal from the popup: persist and refresh overlays."""
        notes_manager.set_note(profile_name, note_text)
        logging.info(f"Note {'saved' if note_text.strip() else 'removed'} for profile '{profile_name}'.")
        # Rebuild overlays to show/hide note icons
        self._create_note_overlays()

    def _dismiss_note_popup_if_preview(self):
        """Dismiss the note popup if it's showing in preview mode (e.g. on scroll)."""
        if self.note_popup.isVisible() and not self.note_popup.is_edit_mode:
            self.note_popup.hide()
