# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import List, Optional, Tuple, Union

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QDialogButtonBox,
    QStyledItemDelegate,
    QStyle,
    QStylePainter,
)
from PySide6.QtGui import QFontMetrics, QFont
from PySide6.QtWidgets import QStyleOptionComboBox

import config
from utils import shorten_save_path


class BoldPrefixDelegate(QStyledItemDelegate):
    """Custom delegate to render text with bold prefix."""
    
    def paint(self, painter, option, index):
        # Read display text and optional prefix length from custom role
        full_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        prefix_len = index.data(Qt.ItemDataRole.UserRole + 1) or 0

        # Ensure consistent left padding for all rows
        left_pad = 8

        # If no prefix, draw normally but with the same padding
        if not prefix_len or prefix_len <= 0 or prefix_len >= len(full_text):
            painter.save()
            # Selection background
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
                text_color = option.palette.highlightedText().color()
            else:
                text_color = option.palette.text().color()
            painter.setPen(text_color)
            painter.setFont(option.font)
            painter.drawText(option.rect.adjusted(left_pad, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, full_text)
            painter.restore()
            return

        prefix = full_text[:prefix_len]
        rest = full_text[prefix_len:]

        painter.save()

        # Draw selection background if needed
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
        else:
            text_color = option.palette.text().color()

        # Prepare fonts
        bold_font = QFont(option.font)
        bold_font.setBold(True)
        normal_font = option.font

        # Left padding
        # Slightly increased horizontal padding
        left_pad = 8

        # Draw bold prefix
        painter.setPen(text_color)
        painter.setFont(bold_font)
        bold_metrics = painter.fontMetrics()
        painter.drawText(option.rect.adjusted(left_pad, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, prefix)
        prefix_width = bold_metrics.horizontalAdvance(prefix)

        # Draw rest
        painter.setFont(normal_font)
        painter.drawText(option.rect.adjusted(left_pad + prefix_width, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, rest)

        painter.restore()

    def sizeHint(self, option, index):
        # Slightly increase the row height for readability
        base = super().sizeHint(option, index)
        return QSize(base.width(), base.height() + 4)


class BoldPrefixCombo(QComboBox):
    """QComboBox that paints the current item with a bold prefix as well."""

    def paintEvent(self, event):
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)

        painter = QStylePainter(self)
        try:
            painter.drawComplexControl(QStyle.CC_ComboBox, opt)

            # Determine edit field rect
            edit_rect = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)

            text = self.currentText() or ""
            prefix_len = self.itemData(self.currentIndex(), Qt.ItemDataRole.UserRole + 1) or 0

            # Ensure consistent padding
            left_pad = 8

            painter.save()
            try:
                # Choose text color according to enabled state
                # Use palette.text() to ensure visibility in dark themes
                text_color = opt.palette.text().color()
                painter.setPen(text_color)

                base_font = self.font()

                if prefix_len and 0 < prefix_len < len(text):
                    prefix = text[:prefix_len]
                    rest = text[prefix_len:]
                    # Draw bold prefix
                    bold_font = QFont(base_font)
                    bold_font.setBold(True)
                    painter.setFont(bold_font)
                    bold_metrics = painter.fontMetrics()
                    painter.drawText(edit_rect.adjusted(left_pad, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, prefix)
                    prefix_width = bold_metrics.horizontalAdvance(prefix)
                    # Draw rest
                    painter.setFont(base_font)
                    painter.drawText(edit_rect.adjusted(left_pad + prefix_width, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, rest)
                else:
                    # No prefix: draw normally
                    painter.setFont(base_font)
                    painter.drawText(edit_rect.adjusted(left_pad, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)
            finally:
                painter.restore()
        finally:
            painter.end()


class SavePathSelectionDialog(QDialog):
    """Dialog to select a detected save path with a compact status badge.

    It mimics QInputDialog.getItem but adds a pill-style indicator that shows
    whether the selected folder appears to contain save files.
    """

    def __init__(
        self,
        items: List[Union[Tuple[str, int], Tuple[str, int, bool], dict]],
        title: str,
        prompt_text: str,
        show_scores: bool = False,
        shorten_paths: bool = True,
        game_install_dir: Optional[str] = None,
        preselect_index: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        # Base minimum; will expand to fit the longest item below
        self._base_min_width = 500
        self.setMinimumWidth(self._base_min_width)

        # Build normalized model: list of dicts {path, score, has_saves}
        normalized_items = []
        for item in items:
            if isinstance(item, dict):
                path = item.get("path")
                score = int(item.get("score", 0))
                has_saves = bool(item.get("has_saves", False)) if "has_saves" in item else None
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                path = item[0]
                score = int(item[1])
                has_saves = bool(item[2]) if len(item) > 2 else None
            else:
                continue
            if isinstance(path, str) and path:
                normalized_items.append({"path": os.path.normpath(path), "score": score, "has_saves": has_saves})

        self._items = normalized_items
        self._shorten_paths = shorten_paths
        self._game_install_dir = game_install_dir

        # UI
        layout = QVBoxLayout(self)
        self._label = QLabel(prompt_text)
        layout.addWidget(self._label)

        row = QHBoxLayout()
        self._combo = BoldPrefixCombo()
        # Install custom delegate for bold prefix rendering (popup view + current)
        delegate = BoldPrefixDelegate()
        self._combo.setItemDelegate(delegate)
        try:
            view = self._combo.view()
            view.setItemDelegate(delegate)
            try:
                # Add a tiny spacing between rows
                view.setSpacing(2)
            except Exception:
                pass
        except Exception:
            pass
        
        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setMinimumWidth(120)
        self._badge.setStyleSheet(self._style_unknown())

        # Populate combo
        longest_display_text = ""
        for entry in self._items:
            full_path = entry["path"]
            display = full_path
            plain_display = full_path  # For width calculation
            
            # Shorten path for display if enabled
            if self._shorten_paths:
                shortened, prefix_len = shorten_save_path(full_path, self._game_install_dir)
                display = shortened
                plain_display = shortened
            
            if show_scores:
                score_text = f" (Score: {entry['score']})"
                display = f"{display}{score_text}"
                plain_display = f"{plain_display}{score_text}"
                
            if len(plain_display) > len(longest_display_text):
                longest_display_text = plain_display
            
            # Store full path in data, show shortened in UI
            self._combo.addItem(display, entry)
            row_index = self._combo.count() - 1
            # Add tooltip with full path
            self._combo.setItemData(row_index, full_path, Qt.ItemDataRole.ToolTipRole)
            # Provide prefix length for delegate rendering
            if self._shorten_paths:
                self._combo.setItemData(row_index, prefix_len, Qt.ItemDataRole.UserRole + 1)

        # Manual option
        self._manual_text = "[Enter Manually...]"
        self._combo.addItem(self._manual_text, {"manual": True})

        # Allow the combobox to grow to contents
        try:
            self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        except Exception:
            pass

        row.addWidget(self._combo, stretch=1)
        row.addWidget(self._badge)
        layout.addLayout(row)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Wiring
        self._combo.currentIndexChanged.connect(self._update_badge)

        # Adjust dialog and dropdown widths to content
        self._adjust_widths_to_content(longest_display_text)

        # Preselect
        if 0 <= preselect_index < self._combo.count() - 1:  # before manual item
            self._combo.setCurrentIndex(preselect_index)
        self._update_badge(self._combo.currentIndex())

    # --- Badge helpers ---
    def _style_green(self) -> str:
        return (
            "QLabel { background-color: #2ecc71; color: #0b1f0c;"
            " padding: 4px 10px; border-radius: 9px; font-weight: 600; }"
        )

    def _style_grey(self) -> str:
        return (
            "QLabel { background-color: #6c757d; color: white;"
            " padding: 4px 10px; border-radius: 9px; font-weight: 600; }"
        )

    def _style_unknown(self) -> str:
        return (
            "QLabel { background-color: #3a3f44; color: #d0d0d0;"
            " padding: 4px 10px; border-radius: 9px; font-weight: 600; }"
        )

    def _update_badge(self, index: int) -> None:
        data = self._combo.itemData(index)
        if not isinstance(data, dict):
            self._badge.setText("")
            self._badge.setStyleSheet(self._style_unknown())
            return
        if data.get("manual"):
            self._badge.setText("manual")
            self._badge.setStyleSheet(self._style_unknown())
            return

        has = data.get("has_saves", None)
        if has is True:
            self._badge.setText("saves inside")
            self._badge.setToolTip("Save files detected in this folder (by quick scan).")
            self._badge.setStyleSheet(self._style_green())
        elif has is False:
            # Fallback quick scan if not provided and allowed
            self._badge.setText("no saves detected")
            self._badge.setToolTip("No common save files found at top-level.")
            self._badge.setStyleSheet(self._style_grey())
        else:
            # Unknown -> do a lightweight check now
            has_any = self._quick_check_contains_saves(data.get("path"))
            if has_any:
                self._badge.setText("saves inside")
                self._badge.setToolTip("Save files detected in this folder (by quick scan).")
                self._badge.setStyleSheet(self._style_green())
            else:
                self._badge.setText("unknown")
                self._badge.setToolTip("Could not detect save files quickly. It may still be correct.")
                self._badge.setStyleSheet(self._style_unknown())

    def _quick_check_contains_saves(self, path: Optional[str]) -> bool:
        if not path or not os.path.isdir(path):
            return False
        try:
            common_exts = {e.lower() for e in getattr(config, "COMMON_SAVE_EXTENSIONS", set())}
            common_names = {f.lower() for f in getattr(config, "COMMON_SAVE_FILENAMES", set())}
            for entry in os.listdir(path):
                full = os.path.join(path, entry)
                if not os.path.isfile(full):
                    continue
                lower = entry.lower()
                _, ext = os.path.splitext(lower)
                if ext in common_exts:
                    return True
                if any(key in lower for key in common_names):
                    return True
        except Exception:
            return False
        return False

    # --- Results API ---
    def get_selected_path(self) -> Optional[str]:
        data = self._combo.currentData()
        if isinstance(data, dict) and data.get("manual"):
            return None
        if isinstance(data, dict):
            return data.get("path")
        return None

    # --- Sizing helpers ---
    def _adjust_widths_to_content(self, longest_display_text: str) -> None:
        """Compute and apply a preferred dialog width based on the longest entry.

        Guarantees a reasonable minimum and caps to the available screen area.
        Also widens the dropdown list view so that long entries are readable.
        """
        try:
            fm = QFontMetrics(self._combo.font())
            text_px = fm.horizontalAdvance(longest_display_text or "W" * 10)
        except Exception:
            text_px = 600

        # Heuristics for control paddings and arrow width
        combo_extra = 50  # margins + arrow + internal padding (balanced)
        badge_width = max(self._badge.minimumWidth(), 120)
        gutters = 50  # layout margins/spacings (balanced)
        desired_dialog_width = text_px + combo_extra + badge_width + gutters

        # Respect screen bounds (keep some margin)
        try:
            screen = (self.windowHandle().screen() if self.windowHandle() else None) or getattr(self, 'screen', lambda: None)()
            if not screen:
                from PySide6.QtWidgets import QApplication
                screen = QApplication.primaryScreen()
            avail_w = screen.availableGeometry().width() if screen else 1600
        except Exception:
            avail_w = 1600

        max_width = int(avail_w * 0.95)
        final_width = max(self._base_min_width, min(desired_dialog_width, max_width))
        try:
            self.resize(final_width, self.sizeHint().height())
        except Exception:
            self.setMinimumWidth(final_width)

        # Also widen the popup view to at least the longest text width
        try:
            # For the popup, we need less extra space (no badge, just scrollbar)
            popup_width = min(max_width, text_px + 40)
            view = self._combo.view()
            view.setMinimumWidth(popup_width)
        except Exception:
            pass

    def is_manual_selected(self) -> bool:
        data = self._combo.currentData()
        return isinstance(data, dict) and bool(data.get("manual"))


