# gui_components/controller_panel.py
# -*- coding: utf-8 -*-
"""
Controller Settings Panel — inline panel embedded in the main window.
Owns all UI for enabling/disabling controller support and remapping buttons.
"""

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QComboBox, QFrame, QGridLayout,
)
from PySide6.QtCore import Qt, Signal

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


class ControllerPanel(QGroupBox):
    """
    Inline Controller Settings panel.  Drop it into any layout like the
    other inline panels (settings_panel_group, cloud_panel, …).

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
        main_layout.setSpacing(10)

        # ── Enable / Disable switch ────────────────────────────────────
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(12)
        self.controller_enabled_switch = QCheckBox(
            "Enable controller compatibility  "
            "(XInput — Xbox, Steam Deck, and compatible devices)"
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
        main_layout.addLayout(toggle_row)

        # ── Separator ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        main_layout.addWidget(sep)

        # ── Button mapping group ───────────────────────────────────────
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
        mapping_group.setLayout(mapping_outer)
        main_layout.addWidget(mapping_group, stretch=1)

        # ── Exit / Save buttons ────────────────────────────────────────
        btn_row = QHBoxLayout()
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
