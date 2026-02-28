# gui_components/controller_panel.py
# -*- coding: utf-8 -*-
"""
Controller Settings Panel — inline panel embedded in the main window.
Owns all UI for enabling/disabling controller support and remapping buttons.

Uses a two-tab layout (like browser tabs):
  Tab 1 — Button Mapping   (the original remap grid)
  Tab 2 — Shortcuts         (combo-button shortcut profiles)
"""

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QComboBox, QFrame, QGridLayout,
    QStackedWidget, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from gui_components.controller_shortcuts_panel import ControllerShortcutsPanel

# Re-exported so other modules only need to import from here
CTRL_BUTTONS = ["A", "B", "X", "Y", "Start", "View/Select", "LB", "RB", "LT+RT"]

CTRL_ACTIONS = [
    ("",               "(None — disabled)"),
    ("backup",         "Backup"),
    ("restore",        "Restore"),
    ("manage_backups", "Manage Backups"),
    ("backup_all",     "Backup all profiles"),
    ("context_menu",   "Open context menu"),
    ("back",           "Back / Close panel"),
    ("delete",         "Delete profile"),
    ("page_up",        "Page up"),
    ("page_down",      "Page down"),
]

CTRL_DEFAULT_MAPPINGS: dict[str, str] = {
    "A":           "backup",
    "B":           "back",
    "X":           "restore",
    "Y":           "manage_backups",
    "Start":       "context_menu",
    "View/Select": "delete",
    "LB":          "page_up",
    "RB":          "page_down",
    "LT+RT":       "backup_all",
}

CTRL_BADGE_COLOR: dict[str, str] = {
    "A":           "#1E8449",
    "B":           "#922B21",
    "X":           "#1A5276",
    "Y":           "#7D6608",
    "Start":       "#1E8449",
    "View/Select": "#616A6B",
    "LB":          "#4A235A",
    "RB":          "#4A235A",
    "LT+RT":       "#784212",
}

# ── Tab button styles ─────────────────────────────────────────────────
_TAB_ACTIVE_SS = """
    QPushButton {
        background-color: #2a2a2a;
        color: #e0e0e0;
        border: 1px solid #555;
        border-bottom: 2px solid #4fc3f7;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 6px 18px;
        font-weight: bold;
        font-size: 9pt;
    }
"""

_TAB_INACTIVE_SS = """
    QPushButton {
        background-color: #1a1a1a;
        color: #777;
        border: 1px solid #333;
        border-bottom: 1px solid #555;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 6px 18px;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #222;
        color: #aaa;
    }
"""


class ControllerPanel(QGroupBox):
    """
    Inline Controller Settings panel.  Drop it into any layout like the
    other inline panels (settings_panel_group, cloud_panel, …).

    Uses a two-tab layout:
      Tab 0 — Button Mapping
      Tab 1 — Shortcuts

    Signals
    -------
    save_requested  — user clicked Save
    exit_requested  — user clicked Exit
    """

    save_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Controller Settings", parent)
        self._build_ui()
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_enabled(self) -> bool:
        return self.controller_enabled_switch.isChecked()

    def get_mappings(self) -> dict[str, str]:
        return {btn: (combo.currentData() or "") for btn, combo in self.ctrl_mapping_combos.items()}

    def get_shortcut_profiles(self) -> list[dict]:
        """Return the current list of shortcut profile dicts."""
        return self.shortcuts_panel.get_all_profiles()

    def update_connection_status(self, connected: bool):
        """Update the controller connection indicator (like Cloud panel)."""
        if connected:
            self._conn_status_label.setText("● Controller connected")
            self._conn_status_label.setStyleSheet(
                "color: #55FF55; font-size: 9pt; font-weight: bold;"
            )
        else:
            self._conn_status_label.setText("● No controller detected")
            self._conn_status_label.setStyleSheet(
                "color: #FF5555; font-size: 9pt; font-weight: bold;"
            )

    def populate(self, settings: dict):
        """Fill the panel's widgets from a settings dict."""
        self.controller_enabled_switch.setChecked(
            settings.get("controller_support_enabled", True)
        )
        saved_mappings: dict = settings.get("controller_button_mappings", CTRL_DEFAULT_MAPPINGS)
        for btn_name, combo in self.ctrl_mapping_combos.items():
            action_id = saved_mappings.get(btn_name, CTRL_DEFAULT_MAPPINGS.get(btn_name, ""))
            idx = combo.findData(action_id)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Populate controller shortcut profiles
        shortcut_data = settings.get("controller_shortcut_profiles", [])
        tray_on = settings.get("minimize_to_tray_on_close", False)
        self.shortcuts_panel.populate(shortcut_data, tray_on)

        # Always start on Tab 0 (Button Mapping)
        self._switch_tab(0)

    def set_profile_count(self, count: int):
        """Show or hide the L1+L2 row based on profile count (requires ≥3 profiles)."""
        visible = count >= 3
        for w in self._l1l2_row_widgets:
            w.setVisible(visible)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 10, 16, 10)
        main_layout.setSpacing(0)

        # ── Enable / Disable switch + connection status ───────────────
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(12)
        self.controller_enabled_switch = QCheckBox(
            "Enable controller compatibility"
        )
        self.controller_enabled_switch.setObjectName("ControllerSwitch")
        self.controller_enabled_switch.setStyleSheet("""
            QCheckBox#ControllerSwitch { spacing: 8px; font-size: 10pt; }
            QCheckBox#ControllerSwitch::indicator {
                width: 40px; height: 22px; border-radius: 11px; border: none;
            }
            QCheckBox#ControllerSwitch::indicator:unchecked       { background-color: #555555; }
            QCheckBox#ControllerSwitch::indicator:checked         { background-color: #2d7d46; }
            QCheckBox#ControllerSwitch::indicator:unchecked:hover { background-color: #666666; }
            QCheckBox#ControllerSwitch::indicator:checked:hover   { background-color: #38a158; }
        """)
        toggle_row.addWidget(self.controller_enabled_switch)
        toggle_row.addStretch(1)

        # Connection status indicator (like Cloud panel)
        self._conn_status_label = QLabel("● No controller detected")
        self._conn_status_label.setStyleSheet(
            "color: #FF5555; font-size: 9pt; font-weight: bold;"
        )
        toggle_row.addWidget(self._conn_status_label)

        main_layout.addLayout(toggle_row)

        main_layout.addSpacing(8)

        # ── Tab bar ────────────────────────────────────────────────────
        tab_bar_row = QHBoxLayout()
        tab_bar_row.setContentsMargins(0, 0, 0, 0)
        tab_bar_row.setSpacing(4)

        self._tab_btn_mapping = QPushButton("Button Mapping")
        self._tab_btn_mapping.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_btn_mapping.clicked.connect(lambda: self._switch_tab(0))

        self._tab_btn_shortcuts = QPushButton("Shortcuts")
        self._tab_btn_shortcuts.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_btn_shortcuts.clicked.connect(lambda: self._switch_tab(1))

        tab_bar_row.addWidget(self._tab_btn_mapping)
        tab_bar_row.addWidget(self._tab_btn_shortcuts)
        tab_bar_row.addStretch(1)
        main_layout.addLayout(tab_bar_row)

        # ── Thin separator line under tabs ─────────────────────────────
        tab_sep = QFrame()
        tab_sep.setFrameShape(QFrame.Shape.HLine)
        tab_sep.setFixedHeight(1)
        tab_sep.setStyleSheet("background-color: #555; border: none;")
        main_layout.addWidget(tab_sep)

        main_layout.addSpacing(6)

        # ── Stacked pages ──────────────────────────────────────────────
        self._stacked = QStackedWidget()

        # --- Page 0: Button Mapping ---
        page_mapping = QWidget()
        page_mapping_layout = QVBoxLayout(page_mapping)
        page_mapping_layout.setContentsMargins(0, 0, 0, 0)
        page_mapping_layout.setSpacing(4)

        mapping_group = QGroupBox("Button Mapping")
        mapping_outer = QVBoxLayout()
        mapping_outer.setContentsMargins(8, 6, 8, 6)
        mapping_outer.setSpacing(4)

        nav_label = QLabel("  D-pad / Left stick  →  Navigate profile list  (always)")
        nav_label.setStyleSheet("color: #888; font-style: italic; font-size: 9pt;")
        mapping_outer.addWidget(nav_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        _badge_ss = (
            "border-radius: 9px; background-color: {bg}; color: white; "
            "font-size: 8pt; font-weight: bold; padding: 1px 7px; "
            "min-width: 22px; max-width: 80px;"
        )

        self.ctrl_mapping_combos: dict[str, QComboBox] = {}
        self._l1l2_row_widgets: list = []   # widgets to show/hide based on profile count

        for row_i, btn_name in enumerate(CTRL_BUTTONS):
            btn_lbl = QLabel(btn_name)
            btn_lbl.setStyleSheet(_badge_ss.format(bg=CTRL_BADGE_COLOR.get(btn_name, "#555")))
            btn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn_lbl.setFixedWidth(80)
            grid.addWidget(btn_lbl, row_i, 0)

            combo = QComboBox()
            for action_id, action_label in CTRL_ACTIONS:
                combo.addItem(action_label, action_id)
            self.ctrl_mapping_combos[btn_name] = combo
            grid.addWidget(combo, row_i, 1)

            if btn_name == "LT+RT":
                # Hidden by default until profile count ≥ 3
                btn_lbl.setVisible(False)
                combo.setVisible(False)
                self._l1l2_row_widgets = [btn_lbl, combo]

        mapping_outer.addLayout(grid)

        # ── Long Press LB info label ──────────────────────────────────
        lp_row = QHBoxLayout()
        lp_row.setSpacing(12)
        lp_badge = QLabel("Hold LT")
        lp_badge.setStyleSheet(_badge_ss.format(bg=CTRL_BADGE_COLOR.get("LT+RT", "#784212")))
        lp_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_badge.setFixedWidth(80)
        lp_label = QLabel("Toggle General / Actions  (always)")
        lp_label.setStyleSheet("color: #888; font-style: italic; font-size: 9pt;")
        lp_row.addWidget(lp_badge)
        lp_row.addWidget(lp_label, 1)
        mapping_outer.addLayout(lp_row)

        mapping_group.setLayout(mapping_outer)
        page_mapping_layout.addWidget(mapping_group, stretch=1)

        self._stacked.addWidget(page_mapping)  # index 0

        # --- Page 1: Shortcuts ---
        page_shortcuts = QWidget()
        page_shortcuts_layout = QVBoxLayout(page_shortcuts)
        page_shortcuts_layout.setContentsMargins(0, 0, 0, 0)
        page_shortcuts_layout.setSpacing(0)

        self.shortcuts_panel = ControllerShortcutsPanel(parent=page_shortcuts)
        self.shortcuts_panel.capture_requested.connect(self._on_shortcut_capture)
        page_shortcuts_layout.addWidget(self.shortcuts_panel, stretch=1)

        self._stacked.addWidget(page_shortcuts)  # index 1

        main_layout.addWidget(self._stacked, stretch=1)

        main_layout.addSpacing(6)

        # ── Exit / Save buttons ────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.exit_button = QPushButton("Exit")
        self.save_button = QPushButton("Save")
        btn_row.addStretch(1)
        btn_row.addWidget(self.exit_button)
        btn_row.addWidget(self.save_button)
        main_layout.addLayout(btn_row)

        self.setLayout(main_layout)

        # Internal signal connections
        self.exit_button.clicked.connect(self.exit_requested)
        self.save_button.clicked.connect(self.save_requested)

        # Default to tab 0 active
        self._switch_tab(0)

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def _switch_tab(self, index: int):
        """Switch between tab 0 (Button Mapping) and tab 1 (Shortcuts)."""
        self._stacked.setCurrentIndex(index)
        if index == 0:
            self._tab_btn_mapping.setStyleSheet(_TAB_ACTIVE_SS)
            self._tab_btn_shortcuts.setStyleSheet(_TAB_INACTIVE_SS)
        else:
            self._tab_btn_mapping.setStyleSheet(_TAB_INACTIVE_SS)
            self._tab_btn_shortcuts.setStyleSheet(_TAB_ACTIVE_SS)

    # ------------------------------------------------------------------
    # Shortcut capture handling
    # ------------------------------------------------------------------

    def _on_shortcut_capture(self, row, slot_index):
        """A shortcut row requested button capture. The parent MainWindow
        should connect to ControllerPoller to relay the next button press
        to this method via `deliver_captured_button`."""
        # The actual capture relay is wired up in gui_handlers / SaveState_gui
        pass

    def deliver_captured_button(self, button_label: str):
        """Deliver a captured controller button to whichever shortcut row
        is currently waiting."""
        row = self.shortcuts_panel.get_capturing_row()
        if row is not None:
            row.finish_capture(button_label)

    def cancel_shortcut_capture(self):
        """Cancel any ongoing capture."""
        self.shortcuts_panel.cancel_all_captures()
