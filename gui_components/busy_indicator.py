# gui_components/busy_indicator.py
# -*- coding: utf-8 -*-
"""Snake-style busy indicator for the main window status bar.

Full-width chunky pixel snake that crawls toward a green apple; each bite
respawns the snake one pixel longer. At max length the snake stays put and
pulses to show the bar is full.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QSizePolicy, QWidget


_PAD = 1
_GAP = 2
_INITIAL_LEN = 3
_SPEED_MS = 70
_PULSE_MS = 50
_PULSE_STEPS = 24  # round-trip dim ↔ bright
_APPLE_HIDDEN_TICKS = 8  # pause before the next apple appears


class BusyIndicator(QWidget):
    """Full-width Snake animation used while backup/search/restore is running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BusyProgressBar")
        self.setMinimumHeight(10)
        self.setMaximumHeight(16)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._length = _INITIAL_LEN
        self._head = _INITIAL_LEN - 1
        self._cols = 0
        self._full = False
        self._pulse = 0
        self._apple_hidden = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_SPEED_MS)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):
        super().showEvent(event)
        self._length = _INITIAL_LEN
        self._head = _INITIAL_LEN - 1
        self._cols = 0
        self._full = False
        self._pulse = 0
        self._apple_hidden = 0
        self._timer.setInterval(_SPEED_MS)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cols, _, _, _ = self._layout()
        if cols != self._cols and cols > 0:
            self._cols = cols
            if not self._full:
                max_len = max(1, cols - 1)
                self._length = min(self._length, max_len)
                self._head = min(self._head, max(0, cols - 2))

    def _layout(self):
        """Centered pixel grid: (cols, px, x0, inner_h).

        Leftover width is split left/right so both sides look the same.
        """
        inner_h = max(2, self.height() - 2 * _PAD)
        inner_w = max(0, self.width() - 2 * _PAD)
        px = inner_h  # square chunks
        cols = max(4, (inner_w + _GAP) // (px + _GAP))
        used = cols * px + (cols - 1) * _GAP
        x0 = _PAD + max(0, (inner_w - used) // 2)
        return cols, px, x0, inner_h

    def _enter_full(self, cols: int):
        self._full = True
        self._length = cols
        self._pulse = 0
        self._apple_hidden = 0
        self._timer.setInterval(_PULSE_MS)

    def _tick(self):
        cols, _, _, _ = self._layout()
        if cols < 4:
            return
        self._cols = cols

        if self._full:
            self._pulse = (self._pulse + 1) % _PULSE_STEPS
            self.update()
            return

        if self._apple_hidden > 0:
            self._apple_hidden -= 1

        apple = cols - 1
        max_len = apple

        self._head += 1
        if self._head >= apple:
            # Ate it — apple vanishes, snake respawns longer; apple returns soon
            self._length += 1
            self._apple_hidden = _APPLE_HIDDEN_TICKS
            if self._length > max_len:
                self._enter_full(cols)
            else:
                self._head = self._length - 1

        self.update()

    def _is_dark(self) -> bool:
        return self.palette().color(QPalette.ColorRole.Window).lightness() < 140

    def _pixel_x(self, col: int, x0: int, px: int) -> int:
        return x0 + col * (px + _GAP)

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )

    def _pulse_factor(self) -> float:
        """Triangle 0→1→0 for a smooth dim↔bright pulse."""
        half = _PULSE_STEPS // 2
        if self._pulse <= half:
            return self._pulse / half
        return (_PULSE_STEPS - self._pulse) / half

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w, h = self.width(), self.height()
        dark = self._is_dark()

        track = QColor("#1A1A1A" if dark else "#E8EAF2")
        empty = QColor("#3A3A3A" if dark else "#C5CAD8")
        lit = QColor("#E53935" if dark else "#4F46E5")
        dim = QColor("#7A1A1A" if dark else "#A5B4FC")
        head_c = QColor("#FF7043" if dark else "#818CF8")
        apple_c = QColor("#4CAF50")

        painter.fillRect(0, 0, w, h, track)

        cols, px, x0, inner_h = self._layout()
        if cols < 4:
            return

        if self._full:
            self._paint_full_pulse(painter, cols, px, x0, inner_h, dim, lit)
        else:
            self._paint_snake(
                painter, cols, px, x0, inner_h, empty, lit, head_c, apple_c
            )

    def _paint_snake(self, painter, cols, px, x0, inner_h, empty, lit, head_c, apple_c):
        apple_col = cols - 1
        snake_cols = set()
        for i in range(self._length):
            col = self._head - i
            if 0 <= col < apple_col:
                snake_cols.add(col)

        show_apple = self._apple_hidden == 0
        for col in range(cols):
            x = self._pixel_x(col, x0, px)
            if col == apple_col and show_apple:
                color = apple_c
            elif col in snake_cols:
                color = head_c if col == self._head else lit
            else:
                color = empty
            painter.fillRect(x, _PAD, px, inner_h, color)

    def _paint_full_pulse(self, painter, cols, px, x0, inner_h, dim, lit):
        # Stationary full snake: every pixel lit, whole bar pulses dim↔bright
        color = self._lerp_color(dim, lit, self._pulse_factor())
        for col in range(cols):
            x = self._pixel_x(col, x0, px)
            painter.fillRect(x, _PAD, px, inner_h, color)
