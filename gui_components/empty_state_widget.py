# gui_components/empty_state_widget.py
# -*- coding: utf-8 -*-
"""
Empty state widget shown when no profiles exist.
Provides onboarding guidance for new users.
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPen, QColor, QPalette


class DropZoneIcon(QFrame):
    """A custom widget that draws a drag-and-drop zone icon with dashed border."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 100)
        self.setMaximumSize(160, 130)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        
    def paintEvent(self, event):
        """Draw a dashed rectangle with a down arrow icon."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Get widget dimensions
        w = self.width()
        h = self.height()
        margin = 8
        
        # Determine colors based on current theme (use palette text color as reference)
        palette = self.palette()
        text_color = palette.color(QPalette.ColorRole.Text)
        # Use a muted version of the text color for the border
        is_dark_theme = text_color.lightness() > 128
        
        if is_dark_theme:
            border_color = QColor(120, 120, 120)  # Muted gray for dark theme
            arrow_color = QColor(150, 150, 150)
        else:
            border_color = QColor(170, 170, 170)  # Slightly darker for light theme
            arrow_color = QColor(140, 140, 140)
        
        # Draw dashed border rectangle
        pen = QPen(border_color)
        pen.setWidth(3)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([8, 6])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        rect_x = margin
        rect_y = margin
        rect_w = w - 2 * margin
        rect_h = h - 2 * margin
        corner_radius = 12
        painter.drawRoundedRect(rect_x, rect_y, rect_w, rect_h, corner_radius, corner_radius)
        
        # Draw down arrow inside
        painter.setPen(QPen(arrow_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        
        center_x = w // 2
        arrow_top = h // 3
        arrow_bottom = h * 2 // 3
        arrow_width = 20
        
        # Vertical line of arrow
        painter.drawLine(center_x, arrow_top - 5, center_x, arrow_bottom)
        
        # Arrow head (V shape)
        painter.drawLine(center_x - arrow_width, arrow_bottom - arrow_width, center_x, arrow_bottom)
        painter.drawLine(center_x + arrow_width, arrow_bottom - arrow_width, center_x, arrow_bottom)
        
        painter.end()


class EmptyStateWidget(QWidget):
    """
    Widget displayed when no profiles exist.
    Shows onboarding instructions for how to add profiles.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateWidget")
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the empty state UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 15, 30, 15)
        layout.setSpacing(8)
        
        # Add vertical stretch to center content
        layout.addStretch(1)
        
        # Drag-drop zone icon (centered)
        self.drop_icon = DropZoneIcon()
        layout.addWidget(self.drop_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # Main instruction text
        self.title_label = QLabel("No profiles yet")
        self.title_label.setObjectName("EmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        
        # Instructions text - shorter lines
        instructions_text = (
            "Drag and drop a Steam link, shortcut, or folder onto this window\n"
            "— or —\n"
            "Click \"Manage Steam\" to add games from your Steam library"
        )
        self.instructions_label = QLabel(instructions_text)
        self.instructions_label.setObjectName("EmptyStateInstructions")
        self.instructions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.instructions_label)
        
        # Additional hint about emulators
        hint_text = "💡 Tip: You can also drag emulator/game shortcuts!"
        self.hint_label = QLabel(hint_text)
        self.hint_label.setObjectName("EmptyStateHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)
        
        # Add vertical stretch to center content
        layout.addStretch(1)

