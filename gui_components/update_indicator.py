# gui_components/update_indicator.py
# -*- coding: utf-8 -*-
"""
Small circular indicator that lives in the title bar and reflects the
state of the UpdateManager.

Visible states:
    * hidden       - no update-related activity (default)
    * green dot    - update available
    * green ring   - download in progress (shows sweep animation)
    * amber dot    - download finished, restart pending

Clicking it tells the MainWindow to open the update dialog.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from update_manager import (
    STATE_DOWNLOADED,
    STATE_DOWNLOADING,
    STATE_ERROR,
    STATE_UPDATE_AVAILABLE,
)


_GREEN = QColor(76, 175, 80)
_AMBER = QColor(255, 167, 38)
_RED = QColor(229, 115, 115)
_TRACK = QColor(255, 255, 255, 40)


class UpdateIndicator(QPushButton):
    """Title-bar update indicator. Clickable when visible."""

    clicked_indicator = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateIndicator")
        # Narrow widget hugging the title text, so the dot sits visually
        # close to the version number rather than floating in the middle
        # of the title bar.
        self.setFixedSize(QSize(14, 28))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            "QPushButton#UpdateIndicator { border: none; background: transparent; padding: 0px; margin: 0px; }"
        )

        self._state: str | None = None
        self._progress: float = 0.0  # 0..1 (fraction downloaded)
        self._sweep_angle: int = 0   # for indeterminate animation

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(80)
        self._anim_timer.timeout.connect(self._tick_animation)

        # --- Attention blink on first "update available" ---
        # The dot toggles visible/hidden a handful of times to catch the
        # user's eye, then settles into the solid-dot state. We only blink
        # on the first transition *into* STATE_UPDATE_AVAILABLE per session,
        # so cycling states (download -> error -> update_available) doesn't
        # flash the UI repeatedly.
        self._blink_visible: bool = True
        self._has_blinked: bool = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(400)
        self._blink_timer.timeout.connect(self._tick_blink)
        self._blink_remaining: int = 0

        self.clicked.connect(self.clicked_indicator.emit)
        self.setVisible(False)

    # --- Public API ---------------------------------------------------

    def set_state(self, state: str):
        prev = self._state
        self._state = state
        visible = state in (
            STATE_UPDATE_AVAILABLE,
            STATE_DOWNLOADING,
            STATE_DOWNLOADED,
            STATE_ERROR,
        )
        self.setVisible(visible)
        if state == STATE_UPDATE_AVAILABLE:
            self.setToolTip("Update available - click for details")
        elif state == STATE_DOWNLOADING:
            self.setToolTip("Downloading update - click to view progress")
        elif state == STATE_DOWNLOADED:
            self.setToolTip("Update ready - click to install")
        elif state == STATE_ERROR:
            self.setToolTip("Update error - click for details")
        else:
            self.setToolTip("")

        if state == STATE_DOWNLOADING:
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            if self._anim_timer.isActive():
                self._anim_timer.stop()

        # Blink only on the first transition into UPDATE_AVAILABLE this session.
        if (
            state == STATE_UPDATE_AVAILABLE
            and prev != STATE_UPDATE_AVAILABLE
            and not self._has_blinked
        ):
            self._start_blink()
        elif state != STATE_UPDATE_AVAILABLE and self._blink_timer.isActive():
            # Moving away from the available state cancels any ongoing blink.
            self._stop_blink()
        self.update()

    def _start_blink(self, total_ms: int = 6000):
        self._has_blinked = True
        self._blink_visible = True
        # Number of 400 ms ticks we'll perform.
        self._blink_remaining = max(1, total_ms // self._blink_timer.interval())
        self._blink_timer.start()

    def _stop_blink(self):
        self._blink_timer.stop()
        self._blink_visible = True
        self.update()

    def _tick_blink(self):
        self._blink_visible = not self._blink_visible
        self._blink_remaining -= 1
        if self._blink_remaining <= 0:
            self._stop_blink()
        else:
            self.update()

    def set_progress(self, done: int, total: int):
        if total > 0:
            self._progress = max(0.0, min(1.0, done / total))
        else:
            self._progress = 0.0
        self.update()

    # --- Internals ----------------------------------------------------

    def _tick_animation(self):
        self._sweep_angle = (self._sweep_angle + 24) % 360
        self.update()

    def paintEvent(self, event):
        if self._state not in (
            STATE_UPDATE_AVAILABLE,
            STATE_DOWNLOADING,
            STATE_DOWNLOADED,
            STATE_ERROR,
        ):
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        d = 10  # diameter
        # Hug the left edge so the dot sits right next to the title text
        # (the QHBoxLayout still adds its 6 px spacing between widgets).
        x = 1
        y = (rect.height() - d) // 2

        if self._state == STATE_UPDATE_AVAILABLE:
            if self._blink_visible:
                p.setBrush(_GREEN)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(x, y, d, d)
        elif self._state == STATE_DOWNLOADED:
            p.setBrush(_AMBER)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x, y, d, d)
        elif self._state == STATE_ERROR:
            p.setBrush(_RED)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x, y, d, d)
        elif self._state == STATE_DOWNLOADING:
            # Draw track circle + progress arc. If progress is 0 we fall back
            # to a rotating sweep (indeterminate style).
            pen_track = QPen(_TRACK, 2)
            pen_prog = QPen(_GREEN, 2)
            pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen_prog.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen_track)
            p.drawEllipse(x, y, d, d)
            p.setPen(pen_prog)
            if self._progress > 0:
                span = int(360 * 16 * self._progress)
                p.drawArc(x, y, d, d, 90 * 16, -span)
            else:
                # Qt arc angles are 1/16th degrees, start at 90° (12 o'clock)
                p.drawArc(x, y, d, d, (90 - self._sweep_angle) * 16, -120 * 16)

        p.end()
