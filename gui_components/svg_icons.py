# gui_components/svg_icons.py
# -*- coding: utf-8 -*-
"""Load SaveState's own SVG icons and paint them in a chosen color.

The SVG files in icons/ use the word "currentColor" as their color.
This module replaces it with a real color (for example the text color
of the active theme), so one SVG file works for both dark and light themes.
"""
import logging

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from common.utils import resource_path

# Pixel sizes rendered into the icon. Qt picks the best one for the
# button size and the screen scaling (100%, 150%, 200%...).
_RENDER_SIZES = (16, 24, 32, 48, 64)


def themed_svg_icon(relative_path, color):
    """Return a QIcon from an SVG in icons/, painted in the given color.

    relative_path: path like "icons/manage_backups.svg".
    color: any CSS color, for example "#e0e0e0".
    Returns an empty QIcon if the file is missing or invalid.
    """
    try:
        with open(resource_path(relative_path), encoding="utf-8") as svg_file:
            svg_text = svg_file.read()
    except OSError as e:
        logging.warning(f"SVG icon not found: {relative_path} ({e})")
        return QIcon()

    svg_text = svg_text.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    if not renderer.isValid():
        logging.warning(f"SVG icon is not valid: {relative_path}")
        return QIcon()

    icon = QIcon()
    view_box = renderer.viewBoxF()
    for size in _RENDER_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        # Keep the drawing's proportions and center it in the square.
        scale = size / max(view_box.width(), view_box.height())
        width = view_box.width() * scale
        height = view_box.height() * scale
        target = QRectF((size - width) / 2, (size - height) / 2, width, height)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, target)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
