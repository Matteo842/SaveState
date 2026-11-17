# -*- coding: utf-8 -*-
"""
Language selector.

  LanguageButton    small button with the flag of the language in use.
  LanguageSelector  full-window panel opened by the button: a search box and
                    one tile with a flag for every available language.

The flags are drawn with code (no image files), so nothing has to be added to
the installer when a language is added.
"""
import logging
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from common import i18n
from common.i18n import tr, tr_for

TILE_SIZE = QSize(190, 160)
TILES_PER_ROW = 3
FLAG_RATIO = 1.5  # width / height


# --------------------------------------------------------------------------
# Flags
# --------------------------------------------------------------------------

def _star(center_x, center_y, radius, rotation):
    """A five-pointed star. `rotation` is the direction of one point, in radians."""
    points = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.382
        angle = rotation + i * math.pi / 5
        points.append(QPointF(center_x + r * math.cos(angle), center_y + r * math.sin(angle)))
    return QPolygonF(points)


def _draw_italy(painter, rect):
    band = rect.width() / 3
    for index, color in enumerate(("#009246", "#FFFFFF", "#CE2B37")):
        painter.fillRect(QRectF(rect.left() + index * band, rect.top(), band + 1, rect.height()), QColor(color))


def _draw_spain(painter, rect):
    """Red, yellow, red. The yellow band is twice as tall. The coat of arms is left out."""
    quarter = rect.height() / 4
    painter.fillRect(rect, QColor("#AA151B"))
    painter.fillRect(QRectF(rect.left(), rect.top() + quarter, rect.width(), quarter * 2), QColor("#F1BF00"))


def _draw_brazil(painter, rect):
    """Green field, yellow diamond, blue circle. The stars and the motto are left out."""
    painter.fillRect(rect, QColor("#009C3B"))
    painter.setPen(Qt.PenStyle.NoPen)
    margin_x = rect.width() * 0.085
    margin_y = rect.height() * 0.12
    painter.setBrush(QColor("#FFDF00"))
    painter.drawPolygon(QPolygonF([
        QPointF(rect.center().x(), rect.top() + margin_y),
        QPointF(rect.right() - margin_x, rect.center().y()),
        QPointF(rect.center().x(), rect.bottom() - margin_y),
        QPointF(rect.left() + margin_x, rect.center().y()),
    ]))
    radius = rect.height() * 0.25
    painter.setBrush(QColor("#002776"))
    painter.drawEllipse(rect.center(), radius, radius)


def _draw_russia(painter, rect):
    """White, blue, red horizontal bands of equal height."""
    band = rect.height() / 3
    for index, color in enumerate(("#FFFFFF", "#0039A6", "#D52B1E")):
        painter.fillRect(QRectF(rect.left(), rect.top() + index * band, rect.width(), band + 1), QColor(color))


def _draw_germany(painter, rect):
    """Black, red, gold horizontal bands of equal height."""
    band = rect.height() / 3
    for index, color in enumerate(("#000000", "#DD0000", "#FFCE00")):
        painter.fillRect(QRectF(rect.left(), rect.top() + index * band, rect.width(), band + 1), QColor(color))


def _draw_france(painter, rect):
    """Blue, white, red vertical bands of equal width."""
    band = rect.width() / 3
    for index, color in enumerate(("#002654", "#FFFFFF", "#CE1126")):
        painter.fillRect(QRectF(rect.left() + index * band, rect.top(), band + 1, rect.height()), QColor(color))


def _draw_japan(painter, rect):
    """White field with a red disc in the centre."""
    painter.fillRect(rect, QColor("#FFFFFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#BC002D"))
    radius = rect.height() * 0.3  # The disc is 3/5 of the flag height
    painter.drawEllipse(rect.center(), radius, radius)


def _draw_china(painter, rect):
    painter.fillRect(rect, QColor("#DE2910"))
    unit = rect.height() / 20  # The flag is designed on a 30 x 20 grid
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFDE00"))
    big_x, big_y = rect.left() + 5 * unit, rect.top() + 5 * unit
    painter.drawPolygon(_star(big_x, big_y, 3 * unit, -math.pi / 2))
    for grid_x, grid_y in ((10, 2), (12, 4), (12, 7), (10, 9)):
        x, y = rect.left() + grid_x * unit, rect.top() + grid_y * unit
        # Every small star points towards the big one
        painter.drawPolygon(_star(x, y, unit, math.atan2(big_y - y, big_x - x)))


def _draw_united_kingdom(painter, rect):
    white, red = QColor("#FFFFFF"), QColor("#C8102E")
    height = rect.height()
    painter.fillRect(rect, QColor("#012169"))
    for color, width in ((white, height * 0.20), (red, height * 0.07)):
        painter.setPen(QPen(color, width))
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())
    center = rect.center()
    for color, thickness in ((white, height / 3), (red, height / 5)):
        painter.fillRect(QRectF(rect.left(), center.y() - thickness / 2, rect.width(), thickness), color)
        painter.fillRect(QRectF(center.x() - thickness / 2, rect.top(), thickness, height), color)


def _draw_globe(painter, rect):
    """Used for "Automatic": follow the language of the operating system."""
    painter.fillRect(rect, QColor("#1E2A38"))
    radius = rect.height() * 0.38
    center = rect.center()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#9ECBFF"), max(1.0, rect.height() * 0.04)))
    painter.drawEllipse(center, radius, radius)
    painter.drawEllipse(center, radius * 0.45, radius)
    painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
    for offset in (-0.5, 0.5):
        half = radius * math.sqrt(1 - offset * offset)
        y = center.y() + radius * offset
        painter.drawLine(QPointF(center.x() - half, y), QPointF(center.x() + half, y))


# Language code -> function that draws its flag
_FLAG_PAINTERS = {
    "en": _draw_united_kingdom,
    "it": _draw_italy,
    "de": _draw_germany,
    "fr": _draw_france,
    "es": _draw_spain,
    "pt": _draw_brazil,
    "ru": _draw_russia,
    "ja": _draw_japan,
    "zh_CN": _draw_china,
    i18n.AUTO: _draw_globe,
}


def draw_flag(painter, rect, code):
    """Draw the flag of `code` inside `rect`, with rounded corners."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    clip = QPainterPath()
    corner = rect.height() * 0.12
    clip.addRoundedRect(rect, corner, corner)
    painter.setClipPath(clip)
    _FLAG_PAINTERS.get(code, _draw_globe)(painter, rect)
    painter.restore()
    # Thin outline, so white areas stay visible on a light background
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(128, 128, 128, 140), 1))
    painter.drawRoundedRect(rect, corner, corner)
    painter.restore()


def short_label(code):
    """Two letters for the button: "it" -> "IT", "zh_CN" -> "ZH"."""
    return code.split("_")[0].upper()


# --------------------------------------------------------------------------
# One tile of the selector
# --------------------------------------------------------------------------

class LanguageTile(QAbstractButton):
    def __init__(self, code, title, subtitle, is_current, parent=None):
        super().__init__(parent)
        self.code = code
        self.title = title
        self.subtitle = subtitle
        self.is_current = is_current
        self.setFixedSize(TILE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def search_text(self):
        english_name = i18n.LANGUAGE_ENGLISH_NAMES.get(self.code, "")
        return f"{self.title} {self.subtitle} {english_name} {self.code}".lower()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        area = QRectF(self.rect()).adjusted(2, 2, -2, -2)

        highlighted = self.underMouse() or self.hasFocus()
        painter.setBrush(QColor("#333333") if highlighted else QColor("#232323"))
        if self.is_current:
            painter.setPen(QPen(QColor("#E53935"), 2))
        else:
            painter.setPen(QPen(QColor("#777777") if highlighted else QColor("#3A3A3A"), 1))
        painter.drawRoundedRect(area, 10, 10)

        flag_height = 64
        flag_width = flag_height * FLAG_RATIO
        flag_rect = QRectF(area.center().x() - flag_width / 2, area.top() + 18, flag_width, flag_height)
        draw_flag(painter, flag_rect, self.code)

        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#F0F0F0"))
        title_rect = QRectF(area.left() + 6, flag_rect.bottom() + 10, area.width() - 12, 24)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self.title)

        if self.subtitle:
            font.setPointSize(8)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#9A9A9A"))
            subtitle_rect = QRectF(area.left() + 6, title_rect.bottom(), area.width() - 12, 20)
            painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignCenter, self.subtitle)


# --------------------------------------------------------------------------
# The full-window selector
# --------------------------------------------------------------------------

class LanguageSelector(QWidget):
    """Covers the whole window. Emits language_chosen with a language code or "auto"."""

    language_chosen = Signal(str)

    def __init__(self, window, saved_choice):
        super().__init__(window)
        self.setObjectName("LanguageSelector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#LanguageSelector { background-color: #141414; }"
            "QLabel { color: #F0F0F0; background: transparent; }"
            "QLineEdit { background-color: #232323; color: #F0F0F0; border: 1px solid #555555;"
            " border-radius: 8px; padding: 8px 12px; font-size: 11pt; }"
            "QLineEdit:focus { border: 1px solid #9A9A9A; }"
            "QScrollArea, QWidget#LanguageTiles { background: transparent; border: none; }"
            "QPushButton#LanguageSelectorClose { background: transparent; color: #CCCCCC;"
            " border: none; font-size: 14pt; padding: 4px 10px; }"
            "QPushButton#LanguageSelectorClose:hover { color: #FFFFFF; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 16, 40, 24)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        close_button = QPushButton("✕")
        close_button.setObjectName("LanguageSelectorClose")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setToolTip(tr("Close"))
        close_button.clicked.connect(self.close_selector)
        top_row.addWidget(close_button)
        layout.addLayout(top_row)

        title = QLabel(tr("Choose your language"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Search language..."))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(TILE_SIZE.width() * TILES_PER_ROW + 24)
        self.search_edit.textChanged.connect(self._arrange_tiles)
        self.search_edit.returnPressed.connect(self._choose_first_visible)
        layout.addWidget(self.search_edit, alignment=Qt.AlignmentFlag.AlignHCenter)

        tiles_widget = QWidget()
        tiles_widget.setObjectName("LanguageTiles")
        self.tiles_layout = QGridLayout(tiles_widget)
        self.tiles_layout.setSpacing(12)
        self.tiles_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(tiles_widget)
        layout.addWidget(scroll_area, stretch=1)

        self.no_result_label = QLabel(tr("No language found."))
        self.no_result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_result_label.setStyleSheet("color: #9A9A9A;")
        self.no_result_label.hide()
        layout.addWidget(self.no_result_label)

        hint = QLabel(tr("The new language is used the next time SaveState starts."))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #9A9A9A;")
        layout.addWidget(hint)

        # "Automatic" first, then every language with its own name
        system_code = i18n.detect_system_language()
        self.tiles = [LanguageTile(i18n.AUTO, tr("Automatic"),
                                   tr("System language: {0}", i18n.LANGUAGES[system_code]),
                                   saved_choice == i18n.AUTO)]
        for code, native_name in i18n.LANGUAGES.items():
            english_name = i18n.LANGUAGE_ENGLISH_NAMES.get(code, "")
            subtitle = english_name if english_name != native_name else ""
            self.tiles.append(LanguageTile(code, native_name, subtitle, saved_choice == code))
        for tile in self.tiles:
            tile.clicked.connect(lambda _checked=False, code=tile.code: self._choose(code))
        self._arrange_tiles()

        window.installEventFilter(self)  # Follow the window when it is resized
        self.setGeometry(window.rect())
        self.raise_()
        self.show()
        self.search_edit.setFocus()

    def _arrange_tiles(self):
        """Show only the tiles that match the search box, in rows of three."""
        wanted = self.search_edit.text().strip().lower()
        for tile in self.tiles:
            self.tiles_layout.removeWidget(tile)
            tile.hide()
        visible = [tile for tile in self.tiles if wanted in tile.search_text()]
        for position, tile in enumerate(visible):
            self.tiles_layout.addWidget(tile, position // TILES_PER_ROW, position % TILES_PER_ROW)
            tile.show()
        self.no_result_label.setVisible(not visible)

    def _choose_first_visible(self):
        for tile in self.tiles:
            if tile.isVisible():
                self._choose(tile.code)
                return

    def _choose(self, code):
        self.language_chosen.emit(code)
        self.close_selector()

    def close_selector(self):
        if self.parent() is not None:
            self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_selector()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        event.accept()  # Clicks on the background must not reach the window below

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(watched, event)


# --------------------------------------------------------------------------
# The small button that opens the selector
# --------------------------------------------------------------------------

class LanguageButton(QPushButton):
    """Shows the flag of the language in use. A click opens the selector."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setFixedSize(64, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Language"))
        self.clicked.connect(self.open_selector)

    def paintEvent(self, event):
        super().paintEvent(event)  # Normal button background and border
        painter = QPainter(self)
        code = i18n.get_language()
        flag_height = 14
        flag_rect = QRectF(9, (self.height() - flag_height) / 2, flag_height * FLAG_RATIO, flag_height)
        draw_flag(painter, flag_rect, code)
        painter.setPen(self.palette().buttonText().color())
        text_rect = QRectF(flag_rect.right() + 5, 0, self.width() - flag_rect.right() - 9, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, short_label(code))

    def open_selector(self):
        saved_choice = self.main_window.current_settings.get(i18n.SETTINGS_KEY, i18n.AUTO)
        if saved_choice not in i18n.LANGUAGES:
            saved_choice = i18n.AUTO
        selector = LanguageSelector(self.main_window, saved_choice)
        selector.language_chosen.connect(self._save_choice)

    def _save_choice(self, choice):
        """Save the chosen language. It is applied at the next start."""
        from core import settings_manager

        new_settings = dict(self.main_window.current_settings)
        if new_settings.get(i18n.SETTINGS_KEY, i18n.AUTO) == choice:
            return
        new_settings[i18n.SETTINGS_KEY] = choice
        if not settings_manager.save_settings(new_settings):
            logging.error("Could not save the language setting.")
            QMessageBox.warning(self.main_window, tr("Language"), tr("Unable to save the language setting."))
            return
        self.main_window.current_settings[i18n.SETTINGS_KEY] = choice
        logging.info(f"Language setting saved: {choice}")

        new_language = i18n.resolve_language(choice)
        if new_language != i18n.get_language():
            # Written in the language just chosen, so it can be read by who chose it
            QMessageBox.information(
                self.main_window,
                tr_for(new_language, "Language"),
                tr_for(new_language, "The new language will be used the next time SaveState starts."),
            )
