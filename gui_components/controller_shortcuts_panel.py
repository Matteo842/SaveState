# gui_components/controller_shortcuts_panel.py
# -*- coding: utf-8 -*-
"""
Controller Shortcuts Panel — allows users to create shortcut profiles
that map 1-3 simultaneous controller button presses to an action.

Each shortcut profile has:
  • Up to 3 button slots (assigned via controller input capture)
  • An action dropdown (Backup, Restore, Manage Backups, etc.)
  • A "Run when app is closed" checkbox (only enabled when
    minimize-to-tray is active in settings)
"""

import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QScrollArea, QGroupBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer


# ── Button name mapping (XInput bitmask → friendly label) ─────────
# Same constant names used in controller_manager.py
_BUTTON_NAMES = {
    0x0001: "D-Up",
    0x0002: "D-Down",
    0x0004: "D-Left",
    0x0008: "D-Right",
    0x0010: "Start",
    0x0020: "View/Select",
    0x0100: "LB",
    0x0200: "RB",
    0x1000: "A",
    0x2000: "B",
    0x4000: "X",
    0x8000: "Y",
}

# Extended names that include analog triggers (not bitmask-based)
BUTTON_LABEL_TO_ID = {
    "A": "A", "B": "B", "X": "X", "Y": "Y",
    "LB": "LB", "RB": "RB",
    "LT": "LT", "RT": "RT",
    "Start": "Start", "View/Select": "View/Select",
    "D-Up": "D-Up", "D-Down": "D-Down",
    "D-Left": "D-Left", "D-Right": "D-Right",
}

ALL_BUTTON_LABELS = list(BUTTON_LABEL_TO_ID.keys())

# Badge colours per button (reused from controller_panel.py where applicable)
_BADGE_COLORS = {
    "A": "#1E8449", "B": "#922B21", "X": "#1A5276", "Y": "#7D6608",
    "LB": "#4A235A", "RB": "#4A235A", "LT": "#784212", "RT": "#784212",
    "Start": "#1E8449", "View/Select": "#616A6B",
    "D-Up": "#555", "D-Down": "#555", "D-Left": "#555", "D-Right": "#555",
}

# Actions available for shortcuts (subset from controller_panel)
SHORTCUT_ACTIONS = [
    ("",               "(None — choose action)"),
    ("backup",         "Backup"),
    ("restore",        "Restore"),
    ("manage_backups", "Manage Backups"),
    ("backup_all",     "Backup all profiles"),
    ("context_menu",   "Open context menu"),
    ("delete",         "Delete profile"),
]

MAX_BUTTONS_PER_SHORTCUT = 3


# =====================================================================
# Individual shortcut profile row
# =====================================================================

class ShortcutProfileRow(QFrame):
    """One shortcut profile: up to 3 button-capture slots + action + options."""

    remove_requested = Signal(object)  # emits self
    capture_requested = Signal(object, int)  # emits (self, slot_index)

    def __init__(self, profile_data: dict | None = None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ShortcutProfileRow {
                background-color: #1e1e1e;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 6px;
            }
        """)

        self._button_ids: list[str | None] = [None, None, None]
        self._capturing_slot: int | None = None  # which slot is being captured

        self._build_ui()

        if profile_data:
            self._load_from_data(profile_data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_data(self) -> dict:
        """Return a serialisable dict for this shortcut profile."""
        buttons = [b for b in self._button_ids if b is not None]
        return {
            "buttons": buttons,
            "action": self.action_combo.currentData() or "",
            "target_profile": self.profile_combo.currentText(),
            "background_enabled": self.background_check.isChecked(),
        }

    def set_profiles(self, profiles_list: list[str]):
        """Populate the profile combo box with available profiles."""
        current_profile = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(profiles_list)
        if current_profile in profiles_list:
            self.profile_combo.setCurrentText(current_profile)
        elif profiles_list:
            pass # Keep default

    def set_tray_available(self, available: bool):
        """Enable / disable the background checkbox depending on tray setting."""
        if not available:
            self.background_check.setChecked(False)
            self.background_check.setEnabled(False)
            self.background_check.setToolTip(
                "Enable 'Minimize to tray on close' in Settings first"
            )
        else:
            self.background_check.setEnabled(True)
            self.background_check.setToolTip("")

    def start_capture(self, slot_index: int):
        """Enter 'listening' mode for the given slot."""
        if 0 <= slot_index < MAX_BUTTONS_PER_SHORTCUT:
            self._capturing_slot = slot_index
            btn = self._slot_buttons[slot_index]
            btn.setText("Press …")
            btn.setStyleSheet(self._capture_active_ss())

    def finish_capture(self, button_label: str):
        """Called externally when the controller manager detects a button press."""
        if self._capturing_slot is None:
            return
        slot = self._capturing_slot
        self._capturing_slot = None
        self._button_ids[slot] = button_label
        self._update_slot_display(slot)

    def cancel_capture(self):
        """Cancel an ongoing capture."""
        if self._capturing_slot is not None:
            slot = self._capturing_slot
            self._capturing_slot = None
            self._update_slot_display(slot)

    @property
    def is_capturing(self) -> bool:
        return self._capturing_slot is not None

    @property
    def capturing_slot(self) -> int | None:
        return self._capturing_slot

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # Row 1: button slots + delete button
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._slot_buttons: list[QPushButton] = []
        for i in range(MAX_BUTTONS_PER_SHORTCUT):
            if i > 0:
                plus_lbl = QLabel("+")
                plus_lbl.setStyleSheet(
                    "color: #aaa; font-size: 14pt; font-weight: bold; padding: 0 2px;"
                )
                plus_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                top_row.addWidget(plus_lbl)

            slot_btn = QPushButton("Assign")
            slot_btn.setFixedHeight(32)
            slot_btn.setMinimumWidth(80)
            slot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_btn.setStyleSheet(self._slot_default_ss())
            slot_btn.clicked.connect(lambda _=False, idx=i: self._on_slot_clicked(idx))
            self._slot_buttons.append(slot_btn)
            top_row.addWidget(slot_btn)

        top_row.addStretch(1)

        # — action label: →
        arrow = QLabel("→")
        arrow.setStyleSheet("color: #888; font-size: 14pt; font-weight: bold;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(arrow)

        # — action combo
        self.action_combo = QComboBox()
        self.action_combo.setMinimumWidth(160)
        for action_id, action_label in SHORTCUT_ACTIONS:
            self.action_combo.addItem(action_label, action_id)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        top_row.addWidget(self.action_combo)

        top_row.addStretch(1)

        # — remove button
        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("Remove this shortcut")
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b00020;
                border: 1px solid #b00020;
                border-radius: 14px;
                font-size: 12pt; font-weight: bold;
                min-width: 28px; max-width: 28px;
                min-height: 28px; max-height: 28px;
            }
            QPushButton:hover {
                background-color: #b00020;
                color: white;
            }
        """)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        top_row.addWidget(remove_btn)

        root.addLayout(top_row)

        # Row 2: profile combo + background checkbox
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        
        # — profile combo
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.setVisible(False)
        bottom_row.addWidget(self.profile_combo)

        self.background_check = QCheckBox("Active when app is closed (system tray)")
        self.background_check.setStyleSheet("font-size: 9pt; color: #aaa;")
        self.background_check.setEnabled(False)  # disabled until tray confirmed
        bottom_row.addWidget(self.background_check)
        
        bottom_row.addStretch(1)
        root.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_slot_clicked(self, slot_index: int):
        """User clicked an assign button — start capture."""
        # If we were capturing another slot, cancel it first
        if self._capturing_slot is not None and self._capturing_slot != slot_index:
            self.cancel_capture()
        self.capture_requested.emit(self, slot_index)

    def _on_action_changed(self):
        """Show/hide profile combo based on selected action."""
        action = self.action_combo.currentData()
        requires_profile = action in ("backup", "restore", "delete", "context_menu")
        self.profile_combo.setVisible(requires_profile)

    def _update_slot_display(self, slot_index: int):
        btn = self._slot_buttons[slot_index]
        label = self._button_ids[slot_index]
        if label:
            colour = _BADGE_COLORS.get(label, "#555")
            btn.setText(label)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {colour}; color: white; "
                f"border-radius: 6px; font-weight: bold; font-size: 9pt; "
                f"padding: 2px 10px; border: none; }}"
                f"QPushButton:hover {{ background-color: {colour}; opacity: 0.85; }}"
            )
        else:
            btn.setText("Assign")
            btn.setStyleSheet(self._slot_default_ss())

    def _load_from_data(self, data: dict):
        buttons = data.get("buttons", [])
        for i, b in enumerate(buttons[:MAX_BUTTONS_PER_SHORTCUT]):
            self._button_ids[i] = b
            self._update_slot_display(i)
        action = data.get("action", "")
        idx = self.action_combo.findData(action)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)
        
        target_profile = data.get("target_profile", "")
        # The list might not be populated yet during initial creation, so we add it silently
        if target_profile:
            self.profile_combo.clear()
            self.profile_combo.addItem(target_profile)
            self.profile_combo.setCurrentText(target_profile)
            
        bg = data.get("background_enabled", False)
        self.background_check.setChecked(bg)
        
        # Ensure correct initial visibility
        self._on_action_changed()

    @staticmethod
    def _slot_default_ss() -> str:
        return (
            "QPushButton { background-color: #2a2a2a; color: #999; "
            "border: 1px dashed #555; border-radius: 6px; font-size: 9pt; "
            "padding: 2px 10px; }"
            "QPushButton:hover { background-color: #333; border-color: #888; color: #ccc; }"
        )

    @staticmethod
    def _capture_active_ss() -> str:
        return (
            "QPushButton { background-color: #1a3a5c; color: #4fc3f7; "
            "border: 2px solid #4fc3f7; border-radius: 6px; font-size: 9pt; "
            "font-weight: bold; padding: 2px 10px; }"
        )


# =====================================================================
# Container panel (embedded inside ControllerPanel)
# =====================================================================

class ControllerShortcutsPanel(QWidget):
    """
    Manages a list of ShortcutProfileRows.
    
    Signals
    -------
    capture_requested(row, slot_index) — a row wants to capture a button
    """

    capture_requested = Signal(object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[ShortcutProfileRow] = []
        self._tray_available = False
        self._profiles_list: list[str] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_profiles(self) -> list[dict]:
        """Return serialisable list of shortcut profile dicts."""
        return [r.get_data() for r in self._rows]

    def populate(self, profiles_data: list[dict], tray_available: bool):
        """Rebuild rows from saved data."""
        self._tray_available = tray_available
        # Clear existing rows
        for r in list(self._rows):
            self._remove_row(r, emit=False)
        for pdata in profiles_data:
            self._add_row(pdata)
        self._update_empty_label()

    def set_tray_available(self, available: bool):
        """Update tray availability for all rows."""
        self._tray_available = available
        for r in self._rows:
            r.set_tray_available(available)

    def set_profiles(self, profiles_list: list[str]):
        """Update the list of profiles for all shortcut rows."""
        self._profiles_list = profiles_list
        for r in self._rows:
            r.set_profiles(profiles_list)

    def cancel_all_captures(self):
        """Cancel any active capture."""
        for r in self._rows:
            r.cancel_capture()

    def get_capturing_row(self) -> ShortcutProfileRow | None:
        """Return the row currently in capture mode, if any."""
        for r in self._rows:
            if r.is_capturing:
                return r
        return None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Controller Shortcuts")
        title.setStyleSheet(
            "font-size: 10pt; font-weight: bold; color: #e0e0e0;"
        )
        header.addWidget(title)
        header.addStretch(1)

        self._add_btn = QPushButton("+")
        self._add_btn.setFixedSize(30, 30)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setToolTip("Add new shortcut profile")
        self._add_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E8449;
                color: white;
                border-radius: 15px;
                font-size: 16pt; font-weight: bold;
                border: none;
                min-width: 30px; max-width: 30px;
                min-height: 30px; max-height: 30px;
            }
            QPushButton:hover { background-color: #27ae60; }
            QPushButton:pressed { background-color: #196f3d; }
        """)
        self._add_btn.clicked.connect(lambda: self._add_row())
        header.addWidget(self._add_btn)
        root.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # Scrollable area for rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(scroll_content)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        # Empty-state label
        self._empty_label = QLabel("No shortcut profiles yet. Press + to create one.")
        self._empty_label.setStyleSheet(
            "color: #666; font-style: italic; font-size: 9pt; padding: 16px;"
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows_layout.insertWidget(0, self._empty_label)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add_row(self, data: dict | None = None):
        row = ShortcutProfileRow(profile_data=data, parent=self)
        row.set_tray_available(self._tray_available)
        if self._profiles_list:
            row.set_profiles(self._profiles_list)
        row.remove_requested.connect(self._on_remove_requested)
        row.capture_requested.connect(self._on_capture_requested)
        self._rows.append(row)
        # Insert before the stretch
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._update_empty_label()

    def _remove_row(self, row: ShortcutProfileRow, emit: bool = True):
        if row in self._rows:
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        if emit:
            self._update_empty_label()

    def _on_remove_requested(self, row):
        self._remove_row(row)

    def _on_capture_requested(self, row, slot_index):
        # Cancel any other active capture first
        for r in self._rows:
            if r is not row:
                r.cancel_capture()
        row.start_capture(slot_index)
        self.capture_requested.emit(row, slot_index)

    def _update_empty_label(self):
        self._empty_label.setVisible(len(self._rows) == 0)
