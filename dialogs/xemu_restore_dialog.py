# -*- coding: utf-8 -*-
"""Restore UI personalizzata per profili xemu (HDD con giochi | ZIP)."""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QLocale,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from core import core_logic
import config
from gui.gui_utils import WorkerThread
from gui_components import lock_backup_manager
from common.utils import resource_path


# Verde Xbox ufficiale (#0E7A0D) + lime chiaro per bordi/LED su UI scura
XBOX_GREEN = "#0E7A0D"
XBOX_GREEN_HOVER = "#0B650B"
XBOX_GREEN_PRESSED = "#094F09"
XBOX_LIME = "#3DDC3D"  # variante chiara del green (leggibile su dark)
XBOX_LIME_BRIGHT = "#6AEF6A"
XBOX_METAL_TOP = "#778079"
XBOX_METAL_MID = "#4B524C"
XBOX_METAL_DARK = "#292E2A"

# Stili bottoni: stessa famiglia Xbox — niente #229954 di SaveButton
_XBOX_BTN_PRIMARY = f"""
QPushButton {{
    min-height: 22px;
    padding: 9px 20px;
    font-weight: 700;
    color: #FFFFFF;
    background-color: {XBOX_GREEN};
    border: 1px solid {XBOX_LIME};
    border-radius: 8px;
}}
QPushButton:hover {{
    background-color: {XBOX_GREEN_HOVER};
    border-color: {XBOX_LIME_BRIGHT};
}}
QPushButton:pressed {{
    background-color: {XBOX_GREEN_PRESSED};
}}
QPushButton:disabled {{
    color: #747A74;
    background-color: #262B26;
    border-color: #343A34;
}}
"""

_XBOX_BTN_OUTLINE = f"""
QPushButton {{
    min-height: 22px;
    padding: 8px 14px;
    font-weight: 600;
    color: #E7ECE7;
    background-color: #1B201B;
    border: 1px solid #394239;
    border-radius: 8px;
}}
QPushButton:hover {{
    color: #FFFFFF;
    background-color: #222A22;
    border-color: {XBOX_GREEN};
}}
QPushButton:pressed {{
    background-color: #151A15;
}}
QPushButton:disabled {{
    color: #656B65;
    background-color: #191D19;
    border-color: #2B302B;
}}
"""

_XEMU_DIALOG_QSS = f"""
QDialog#XemuRestoreDialog {{
    background-color: #111411;
    color: #F2F5F2;
}}
QFrame#RestoreHero {{
    background-color: #181D18;
    border: 1px solid #2C342C;
    border-radius: 12px;
}}
QLabel#HeroEyebrow {{
    color: {XBOX_LIME};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#HeroTitle {{
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 700;
}}
QLabel#HeroSubtitle {{
    color: #AEB6AE;
    font-size: 11px;
}}
QLabel#HeroModeBadge {{
    color: {XBOX_LIME};
    background-color: #122412;
    border: 1px solid #2A622A;
    border-radius: 9px;
    padding: 5px 9px;
    font-size: 9px;
    font-weight: 700;
}}
QLabel#TitleIdBadge {{
    color: #D7DDD7;
    background-color: #222722;
    border: 1px solid #343C34;
    border-radius: 9px;
    padding: 5px 9px;
    font-size: 9px;
}}
QFrame#PanelCard {{
    background-color: #171B17;
    border: 1px solid #2A312A;
    border-radius: 12px;
}}
QLabel#StepBadge {{
    color: #0B120B;
    background-color: {XBOX_LIME};
    border: none;
    border-radius: 12px;
    font-weight: 800;
}}
QLabel#SectionTitle {{
    color: #F5F7F5;
    font-size: 14px;
    font-weight: 700;
}}
QLabel#SectionSubtitle {{
    color: #858E85;
    font-size: 10px;
}}
QLabel#ReadyPill {{
    color: {XBOX_LIME};
    background-color: #102310;
    border: 1px solid #275927;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 8px;
    font-weight: 700;
}}
QLabel#ErrorPill {{
    color: #FF9A9A;
    background-color: #2B1616;
    border: 1px solid #653030;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 8px;
    font-weight: 700;
}}
QLabel#CountPill {{
    color: #C9D0C9;
    background-color: #222722;
    border: 1px solid #333A33;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 8px;
    font-weight: 600;
}}
QFrame#DriveInfoBar {{
    background-color: #121612;
    border: 1px solid #252C25;
    border-radius: 8px;
}}
QLabel#DriveCaption, QLabel#SourceCaption {{
    color: #727B72;
    font-size: 8px;
    font-weight: 700;
}}
QLabel#DrivePath {{
    color: #B9C1B9;
    font-size: 9px;
}}
QLabel#DriveHint {{
    color: #A8B0A8;
    font-size: 9px;
}}
QListWidget#BackupList {{
    background-color: #111511;
    border: 1px solid #282F28;
    border-radius: 9px;
    outline: none;
    padding: 5px;
}}
QListWidget#BackupList::item {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 3px 1px;
}}
QScrollBar::handle:vertical {{
    background: #3B443B;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {XBOX_GREEN};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QLabel#ZipHelper {{
    color: #727A72;
    font-size: 9px;
}}
QFrame#RestoreFooter {{
    background-color: #181D18;
    border: 1px solid #2B332B;
    border-radius: 11px;
}}
QLabel#StatusKicker {{
    color: {XBOX_LIME};
    font-size: 8px;
    font-weight: 800;
}}
QLabel#StatusText {{
    color: #B5BDB5;
    font-size: 10px;
}}
QPushButton#CancelButton {{
    min-height: 22px;
    padding: 9px 18px;
    color: #D7DDD7;
    background-color: transparent;
    border: 1px solid #3A413A;
    border-radius: 8px;
}}
QPushButton#CancelButton:hover {{
    color: #FFFFFF;
    background-color: #242924;
    border-color: #596159;
}}
QPushButton#CancelButton:pressed {{
    background-color: #151815;
}}
QPushButton#CancelButton:disabled {{
    color: #626862;
    border-color: #2B302B;
}}
"""


MIN_ANIM_MS = 1200
TITLE_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole
CURRENT_TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
UPDATED_BADGE_ROLE = Qt.ItemDataRole.UserRole + 2
BACKUP_DATE_ROLE = Qt.ItemDataRole.UserRole + 10
BACKUP_KIND_ROLE = Qt.ItemDataRole.UserRole + 11
BACKUP_EMPTY_ROLE = Qt.ItemDataRole.UserRole + 12


def _format_size_mb(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "— MB"
    mb = size / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    if mb >= 100:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def _title_display_name(title_id: str) -> str:
    tid = (title_id or "").strip().lower()
    try:
        from emulator_utils.xemu_manager import _display_name

        return _display_name(tid)
    except Exception:
        from emulator_utils.xemu_lab.titles import game_display_name

        return game_display_name(tid)


def _scan_hdd_games(hdd_path: str) -> list[dict]:
    from emulator_utils.xemu_lab.titles import list_games_on_image

    games = []
    for game in list_games_on_image(hdd_path, partition="E", areas=("UDATA",)):
        tid = game.title_id.strip().lower()
        games.append(
            {
                "title_id": tid,
                "name": _title_display_name(tid),
                "area": game.area,
            }
        )
    games.sort(key=lambda g: g["name"].casefold())
    return games


def _hdd_body_rect(widget_rect: QRect) -> QRect:
    """Chassis 3.5\" (101.6×146 mm) in portrait: rettangolo più alto che largo."""
    margin = 4
    avail = widget_rect.adjusted(margin, 2, -margin, -margin)
    if avail.width() < 40 or avail.height() < 40:
        return avail
    # Form factor reale ≈ 0.70 w/h (portrait)
    target_ratio = 101.6 / 146.0
    if avail.width() / max(1, avail.height()) > target_ratio:
        h = avail.height()
        w = max(1, int(h * target_ratio))
    else:
        w = avail.width()
        h = max(1, int(w / target_ratio))
    # Usa quasi tutto lo spazio disponibile: se avanza altezza, allunga un po'
    # (lista giochi > fedeltà millimetrica)
    if h < avail.height():
        h = avail.height()
        w = min(avail.width(), max(w, int(h * 0.78)))
    x = avail.x() + (avail.width() - w) // 2
    y = avail.y() + (avail.height() - h) // 2
    return QRect(x, y, w, h)


def _build_hdd_outline(body: QRectF) -> QPainterPath:
    """
    Silhouette top-plate 3.5\" HDD: angoli a vite, vita laterale (waist).
    Ispirata a Seagate Barracuda / sketch utente.
    """
    x, y, w, h = body.x(), body.y(), body.width(), body.height()
    c = min(w, h) * 0.055
    waist_in = min(w, h) * 0.045
    waist_top = y + h * 0.40
    waist_bot = y + h * 0.60

    path = QPainterPath()
    path.moveTo(x + c, y)
    path.lineTo(x + w - c, y)
    path.lineTo(x + w, y + c)
    path.lineTo(x + w, waist_top)
    path.cubicTo(
        QPointF(x + w - waist_in, waist_top + (waist_bot - waist_top) * 0.15),
        QPointF(x + w - waist_in, waist_bot - (waist_bot - waist_top) * 0.15),
        QPointF(x + w, waist_bot),
    )
    path.lineTo(x + w, y + h - c)
    path.lineTo(x + w - c, y + h)
    path.lineTo(x + c, y + h)
    path.lineTo(x, y + h - c)
    path.lineTo(x, waist_bot)
    path.cubicTo(
        QPointF(x + waist_in, waist_bot - (waist_bot - waist_top) * 0.15),
        QPointF(x + waist_in, waist_top + (waist_bot - waist_top) * 0.15),
        QPointF(x, waist_top),
    )
    path.lineTo(x, y + c)
    path.lineTo(x + c, y)
    path.closeSubpath()
    return path


def _label_rect_for_body(body: QRect) -> QRect:
    """Zona sticker: quasi tutto l'interno sotto la brand strip."""
    inset_x = max(10, int(body.width() * 0.07))
    inset_top = max(28, int(body.height() * 0.09))
    inset_bot = max(28, int(body.height() * 0.08))
    return QRect(
        body.x() + inset_x,
        body.y() + inset_top,
        body.width() - 2 * inset_x,
        body.height() - inset_top - inset_bot,
    )


class GamesListDelegate(QStyledItemDelegate):
    """Evidenzia il Title ID del profilo (accent Xbox green) e badge updated."""

    def paint(self, painter, option, index):
        painter.save()
        is_current = bool(index.data(CURRENT_TITLE_ROLE))
        updated = bool(index.data(UPDATED_BADGE_ROLE))

        if is_current:
            painter.fillRect(option.rect, QColor(14, 122, 13, 55))
            painter.fillRect(
                option.rect.x(),
                option.rect.y(),
                3,
                option.rect.height(),
                QColor(XBOX_GREEN),
            )

        if updated:
            painter.fillRect(option.rect, QColor(14, 122, 13, 90))

        opt = QStyleOptionViewItem(option)
        if is_current or updated:
            opt.state &= ~QStyle.State.State_Selected
        super().paint(painter, opt, index)

        if updated:
            badge = "updated"
            font = QFont(option.font)
            font.setPointSize(max(7, font.pointSize() - 2))
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            tw = metrics.horizontalAdvance(badge) + 10
            th = metrics.height() + 4
            br = QRect(
                option.rect.right() - tw - 8,
                option.rect.center().y() - th // 2,
                tw,
                th,
            )
            painter.setBrush(QColor(XBOX_GREEN))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(br, 6, 6)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)

        painter.restore()


class BackupCardDelegate(QStyledItemDelegate):
    """Card compatte e coerenti con il linguaggio visivo Xbox del dialog."""

    def sizeHint(self, option, index):
        if index.data(BACKUP_EMPTY_ROLE):
            return QSize(max(260, option.rect.width()), 92)
        return QSize(max(260, option.rect.width()), 66)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(option.rect.adjusted(3, 3, -3, -3))
        if index.data(BACKUP_EMPTY_ROLE):
            painter.setPen(QPen(QColor("#2A322A"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor("#151915"))
            painter.drawRoundedRect(rect, 8, 8)

            title_font = QFont(option.font)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#AAB2AA"))
            title_rect = rect.adjusted(16, 15, -16, -38)
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "No local backups yet",
            )

            detail_font = QFont(option.font)
            detail_font.setPointSize(max(8, detail_font.pointSize() - 1))
            painter.setFont(detail_font)
            painter.setPen(QColor("#6F786F"))
            detail_rect = rect.adjusted(16, 42, -16, -12)
            painter.drawText(
                detail_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "Import a validated SaveState ZIP below.",
            )
            painter.restore()
            return

        selected = bool(option.state & QStyle.State.State_Selected)
        hovered = bool(option.state & QStyle.State.State_MouseOver)
        if selected:
            background = QColor("#173117")
            border = QColor(XBOX_LIME)
        elif hovered:
            background = QColor("#202620")
            border = QColor("#3B463B")
        else:
            background = QColor("#1A1F1A")
            border = QColor("#2B332B")

        painter.setBrush(background)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 8, 8)
        if selected:
            accent = QRectF(rect.left(), rect.top() + 9, 3.5, rect.height() - 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(XBOX_LIME))
            painter.drawRoundedRect(accent, 1.75, 1.75)

        kind = str(index.data(BACKUP_KIND_ROLE) or "LOCAL").upper()
        glyph_rect = QRectF(rect.left() + 13, rect.center().y() - 15, 30, 30)
        painter.setBrush(QColor("#102310") if selected else QColor("#242B24"))
        painter.setPen(QPen(QColor("#367336") if selected else QColor("#3B443B"), 1))
        painter.drawEllipse(glyph_rect)

        glyph_font = QFont(option.font)
        glyph_font.setBold(True)
        glyph_font.setPointSize(max(7, glyph_font.pointSize() - 2))
        painter.setFont(glyph_font)
        painter.setPen(QColor(XBOX_LIME) if selected else QColor("#A8B1A8"))
        painter.drawText(
            glyph_rect,
            Qt.AlignmentFlag.AlignCenter,
            "ZIP" if kind == "ZIP" else "HDD",
        )

        right_inset = 38 if selected else 14
        text_left = glyph_rect.right() + 12
        title_rect = QRectF(
            text_left,
            rect.top() + 9,
            rect.right() - text_left - right_inset,
            22,
        )
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_font.setPointSize(max(9, title_font.pointSize()))
        painter.setFont(title_font)
        painter.setPen(QColor("#F2F5F2"))
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        title = painter.fontMetrics().elidedText(
            title,
            Qt.TextElideMode.ElideRight,
            max(20, int(title_rect.width())),
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )

        meta_font = QFont(option.font)
        meta_font.setPointSize(max(8, meta_font.pointSize() - 1))
        painter.setFont(meta_font)
        painter.setPen(QColor("#899289"))
        date_text = str(index.data(BACKUP_DATE_ROLE) or "Date unavailable")
        meta = f"{kind} BACKUP  •  {date_text}"
        meta_rect = QRectF(
            text_left,
            rect.top() + 32,
            rect.right() - text_left - right_inset,
            18,
        )
        meta = painter.fontMetrics().elidedText(
            meta,
            Qt.TextElideMode.ElideRight,
            max(20, int(meta_rect.width())),
        )
        painter.drawText(
            meta_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            meta,
        )

        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        if decoration and not decoration.isNull() and not selected:
            icon_rect = QRect(
                int(rect.right() - 29),
                int(rect.center().y() - 8),
                16,
                16,
            )
            decoration.paint(painter, icon_rect)

        if selected:
            check_center = QPointF(rect.right() - 19, rect.center().y())
            painter.setBrush(QColor(XBOX_LIME))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(check_center, 9, 9)
            painter.setPen(QPen(QColor("#0A130A"), 1.8))
            painter.drawLine(
                QPointF(check_center.x() - 4, check_center.y()),
                QPointF(check_center.x() - 1, check_center.y() + 3),
            )
            painter.drawLine(
                QPointF(check_center.x() - 1, check_center.y() + 3),
                QPointF(check_center.x() + 5, check_center.y() - 4),
            )

        painter.restore()


class XemuHddPanel(QWidget):
    """HDD 3.5\" stilizzato con lista giochi nella zona sticker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._size_label = "— MB"
        self._game_count = 0
        self._pulse = 0.0
        self._body = QRect()
        self._label_area = QRect()

        self.setMinimumSize(240, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.games_list = QListWidget(self)
        self.games_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.games_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.games_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.games_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.games_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.games_list.setUniformItemSizes(True)
        self._games_delegate = GamesListDelegate(self.games_list)
        self.games_list.setItemDelegate(self._games_delegate)
        self.games_list.setStyleSheet(
            f"""
            QListWidget {{
                background: rgba(12, 14, 12, 230);
                color: #F0F0F0;
                border: 1px solid {XBOX_GREEN};
                border-radius: 3px;
                outline: none;
                padding: 1px;
            }}
            QListWidget::item {{
                padding: 4px 6px;
                border-radius: 2px;
                min-height: 22px;
            }}
            QListWidget::item:hover {{
                background: rgba(14, 122, 13, 55);
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 1px;
            }}
            QScrollBar::handle:vertical {{
                background: {XBOX_GREEN};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            """
        )

        # Size vive nella brand strip (paint); chip nascosto ma aggiornato per accessibilità
        self.size_chip = QLabel(self._size_label, self)
        self.size_chip.hide()

        self.count_badge = QLabel("0", self)
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_badge.setStyleSheet(
            f"""
            QLabel {{
                color: #FFFFFF;
                background: {XBOX_GREEN};
                border: 1px solid {XBOX_LIME};
                border-radius: 10px;
                font-weight: bold;
                padding: 3px 8px;
            }}
            """
        )

        self.count_caption = QLabel("games", self)
        self.count_caption.setStyleSheet("color: #DDDDDD; font-size: 10px;")

    def set_hdd_info(self, size_text: str, game_count: int) -> None:
        self._size_label = size_text
        self._game_count = int(game_count)
        self.size_chip.setText(size_text)
        self.count_badge.setText(str(self._game_count))
        self.update()

    def bump_count_pulse(self) -> None:
        self._pulse = 1.0
        self.count_badge.setStyleSheet(
            f"""
            QLabel {{
                color: #111111;
                background: {XBOX_LIME_BRIGHT};
                border: 1px solid {XBOX_LIME};
                border-radius: 10px;
                font-weight: bold;
                padding: 4px 10px;
            }}
            """
        )
        self.update()

        def _decay():
            self._pulse = max(0.0, self._pulse - 0.15)
            self.update()
            if self._pulse > 0.01:
                QTimer.singleShot(40, _decay)
            else:
                self.count_badge.setStyleSheet(
                    f"""
                    QLabel {{
                        color: #FFFFFF;
                        background: {XBOX_GREEN};
                        border: 1px solid {XBOX_LIME};
                        border-radius: 10px;
                        font-weight: bold;
                        padding: 4px 10px;
                    }}
                    """
                )

        QTimer.singleShot(40, _decay)

    def sizeHint(self) -> QSize:
        return QSize(300, 400)

    def label_global_rect(self) -> QRect:
        """Rect della zona lista in coordinate del dialog (parent chain)."""
        return QRect(self.mapTo(self.window(), self._label_area.topLeft()), self._label_area.size())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_children()

    def _layout_children(self) -> None:
        self._body = _hdd_body_rect(self.rect())
        if self._body.width() < 80:
            return
        self._label_area = _label_rect_for_body(self._body)

        # Lista = quasi tutto lo sticker (size e brand sono fuori / in paint)
        self.games_list.setGeometry(
            self._label_area.x() + 4,
            self._label_area.y() + 4,
            self._label_area.width() - 8,
            max(60, self._label_area.height() - 8),
        )

        self.count_badge.adjustSize()
        bw = max(32, self.count_badge.sizeHint().width() + 4)
        bh = max(22, self.count_badge.sizeHint().height())
        badge_x = self._body.right() - bw - max(8, int(self._body.width() * 0.06))
        badge_y = self._body.bottom() - bh - max(6, int(self._body.height() * 0.035))
        self.count_badge.setGeometry(badge_x, badge_y, bw, bh)
        self.count_badge.raise_()

        self.count_caption.adjustSize()
        self.count_caption.move(
            badge_x - self.count_caption.width() - 6,
            badge_y + (bh - self.count_caption.height()) // 2,
        )
        self.count_caption.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        body = QRectF(_hdd_body_rect(self.rect()))
        if body.width() < 40:
            return

        outline = _build_hdd_outline(body)

        shadow = QPainterPath(outline)
        shadow.translate(3, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawPath(shadow)

        metal = QLinearGradient(body.topLeft(), body.bottomRight())
        metal.setColorAt(0.0, QColor(XBOX_METAL_TOP))
        metal.setColorAt(0.45, QColor(XBOX_METAL_MID))
        metal.setColorAt(1.0, QColor(XBOX_METAL_DARK))
        painter.setBrush(QBrush(metal))
        painter.setPen(QPen(QColor(XBOX_LIME), 2.5))
        painter.drawPath(outline)

        inset = body.adjusted(
            body.width() * 0.03,
            body.height() * 0.025,
            -body.width() * 0.03,
            -body.height() * 0.025,
        )
        inner = _build_hdd_outline(inset)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(80, 85, 90, 160), 1.2))
        painter.drawPath(inner)

        screw_r = max(2.2, min(body.width(), body.height()) * 0.011)
        screws = [
            QPointF(body.left() + body.width() * 0.08, body.top() + body.height() * 0.055),
            QPointF(body.right() - body.width() * 0.08, body.top() + body.height() * 0.055),
            QPointF(body.left() + body.width() * 0.08, body.bottom() - body.height() * 0.055),
            QPointF(body.right() - body.width() * 0.08, body.bottom() - body.height() * 0.055),
            QPointF(body.left() + body.width() * 0.08, body.center().y()),
            QPointF(body.right() - body.width() * 0.08, body.center().y()),
        ]
        for pt in screws:
            grad = QRadialGradient(pt, screw_r * 2.2)
            grad.setColorAt(0.0, QColor("#E8E8E8"))
            grad.setColorAt(0.55, QColor("#888888"))
            grad.setColorAt(1.0, QColor("#333333"))
            painter.setBrush(grad)
            painter.setPen(QPen(QColor("#222222"), 0.8))
            painter.drawEllipse(pt, screw_r, screw_r)

        # Brand strip: titolo a sinistra, size a destra (non ruba spazio alla lista)
        brand = QRectF(
            body.left() + body.width() * 0.12,
            body.top() + body.height() * 0.028,
            body.width() * 0.76,
            max(22.0, body.height() * 0.055),
        )
        painter.setBrush(QColor(20, 22, 20, 230))
        painter.setPen(QPen(QColor(XBOX_GREEN), 1))
        painter.drawRoundedRect(brand, 5, 5)

        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        painter.setPen(QColor(XBOX_LIME))
        title_rect = brand.adjusted(8, 0, -brand.width() * 0.38, 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "XBOX HDD")

        size_font = QFont(self.font())
        size_font.setBold(True)
        size_font.setPointSize(max(8, size_font.pointSize()))
        painter.setFont(size_font)
        painter.setPen(QColor("#111111"))
        size_box = QRectF(brand.right() - brand.width() * 0.34, brand.top() + 2, brand.width() * 0.30, brand.height() - 4)
        painter.setBrush(QColor(XBOX_LIME))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(size_box, 4, 4)
        painter.setPen(QColor("#111111"))
        painter.drawText(size_box, Qt.AlignmentFlag.AlignCenter, self._size_label)

        led = QPointF(size_box.left() - 10, brand.center().y())
        led_color = QColor(XBOX_LIME_BRIGHT) if self._pulse > 0.2 else QColor(XBOX_LIME)
        painter.setBrush(led_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(led, 3.8, 3.8)

        label = QRectF(_label_rect_for_body(body.toRect()))
        painter.setBrush(QColor(245, 245, 240, 22))
        painter.setPen(QPen(QColor(XBOX_GREEN), 1))
        painter.drawRoundedRect(label, 3, 3)


class XemuRestoreDialog(QDialog):
    """Dialog restore xemu: HDD (con giochi) | backup ZIP."""

    restore_completed = Signal(bool, str)

    def __init__(self, profile_name: str, profile_data: dict, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.profile_data = dict(profile_data or {})
        self.title_id = (
            str(self.profile_data.get("title_id") or self.profile_data.get("id") or "")
            .strip()
            .lower()
        )
        self.hdd_path = self._resolve_hdd_path()
        self.game_name = _title_display_name(self.title_id) if self.title_id else profile_name

        self._worker: Optional[WorkerThread] = None
        self._restore_running = False
        self._anim_done = False
        self._worker_done = False
        self._worker_success = False
        self._worker_message = ""
        self._min_timer_done = False
        self._ghost: Optional[QLabel] = None
        self._fly_group: Optional[QParallelAnimationGroup] = None
        self._title_was_present = False
        self._zip_list_item = None

        self.setWindowTitle(f"Restore xemu — {self.game_name}")
        self.setMinimumSize(840, 600)
        self.resize(920, 660)

        self._build_ui()
        self._reload_hdd_games()
        self._populate_backups()

    @property
    def games_list(self) -> QListWidget:
        return self.hdd_panel.games_list

    def _resolve_hdd_path(self) -> Optional[str]:
        hdd = self.profile_data.get("hdd_path")
        if isinstance(hdd, str) and hdd and os.path.isfile(hdd):
            return hdd
        paths = self.profile_data.get("paths")
        if isinstance(paths, list):
            for p in paths:
                if isinstance(p, str) and p and os.path.isfile(p):
                    return p
        path = self.profile_data.get("path")
        if isinstance(path, str) and path and os.path.isfile(path):
            return path
        return None

    def _build_ui(self) -> None:
        self.setObjectName("XemuRestoreDialog")
        self.setStyleSheet(_XEMU_DIALOG_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Hero: natura unica della funzione, spiegata in modo sobrio ---
        hero = QFrame()
        hero.setObjectName("RestoreHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(17, 13, 17, 13)
        hero_layout.setSpacing(18)

        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(2)
        eyebrow = QLabel("XEMU  /  SAVE RESTORE")
        eyebrow.setObjectName("HeroEyebrow")
        hero_copy.addWidget(eyebrow)
        hero_title = QLabel(f"Restore {self.game_name}")
        hero_title.setObjectName("HeroTitle")
        hero_title.setWordWrap(True)
        hero_copy.addWidget(hero_title)
        hero_subtitle = QLabel(
            "Choose a backup and write it directly into the live Xbox HDD. "
            "Other titles remain untouched."
        )
        hero_subtitle.setObjectName("HeroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_copy.addWidget(hero_subtitle)
        hero_layout.addLayout(hero_copy, stretch=1)

        hero_badges = QVBoxLayout()
        hero_badges.setSpacing(6)
        hero_badges.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mode_badge = QLabel("RAW HDD  •  DIRECT FATX")
        mode_badge.setObjectName("HeroModeBadge")
        mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_badges.addWidget(mode_badge)
        title_id_badge = QLabel(f"TITLE ID  {(self.title_id or 'UNKNOWN').upper()}")
        title_id_badge.setObjectName("TitleIdBadge")
        title_id_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_badges.addWidget(title_id_badge)
        hero_layout.addLayout(hero_badges)
        root.addWidget(hero)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        root.addLayout(columns, stretch=1)

        # --- Left card: destinazione HDD ---
        left_card = QFrame()
        left_card.setObjectName("PanelCard")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(14, 13, 14, 13)
        left.setSpacing(9)

        left_heading = QHBoxLayout()
        left_heading.setSpacing(9)
        left_step = QLabel("1")
        left_step.setObjectName("StepBadge")
        left_step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_step.setFixedSize(24, 24)
        left_heading.addWidget(left_step)
        left_titles = QVBoxLayout()
        left_titles.setSpacing(0)
        left_title = QLabel("Live Xbox HDD")
        left_title.setObjectName("SectionTitle")
        left_titles.addWidget(left_title)
        left_subtitle = QLabel("Destination")
        left_subtitle.setObjectName("SectionSubtitle")
        left_titles.addWidget(left_subtitle)
        left_heading.addLayout(left_titles)
        left_heading.addStretch()
        drive_pill = QLabel("READY" if self.hdd_path else "NOT FOUND")
        drive_pill.setObjectName("ReadyPill" if self.hdd_path else "ErrorPill")
        left_heading.addWidget(drive_pill)
        left.addLayout(left_heading)

        self.hdd_panel = XemuHddPanel()
        left.addWidget(self.hdd_panel, stretch=1)

        drive_info = QFrame()
        drive_info.setObjectName("DriveInfoBar")
        drive_info_layout = QVBoxLayout(drive_info)
        drive_info_layout.setContentsMargins(10, 8, 10, 8)
        drive_info_layout.setSpacing(2)
        drive_caption = QLabel("HDD IMAGE")
        drive_caption.setObjectName("DriveCaption")
        drive_info_layout.addWidget(drive_caption)
        self.hdd_path_label = QLabel("")
        self.hdd_path_label.setWordWrap(True)
        self.hdd_path_label.setObjectName("DrivePath")
        self.hdd_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        drive_info_layout.addWidget(self.hdd_path_label)
        self.games_hint = QLabel("")
        self.games_hint.setObjectName("DriveHint")
        self.games_hint.setWordWrap(True)
        drive_info_layout.addWidget(self.games_hint)
        left.addWidget(drive_info)
        columns.addWidget(left_card, stretch=5)

        # --- Right card: sorgente backup ---
        right_card = QFrame()
        right_card.setObjectName("PanelCard")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(14, 13, 14, 13)
        right.setSpacing(9)

        right_heading = QHBoxLayout()
        right_heading.setSpacing(9)
        right_step = QLabel("2")
        right_step.setObjectName("StepBadge")
        right_step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_step.setFixedSize(24, 24)
        right_heading.addWidget(right_step)
        right_titles = QVBoxLayout()
        right_titles.setSpacing(0)
        right_title = QLabel("Choose a backup")
        right_title.setObjectName("SectionTitle")
        right_titles.addWidget(right_title)
        right_subtitle = QLabel("Source")
        right_subtitle.setObjectName("SectionSubtitle")
        right_titles.addWidget(right_subtitle)
        right_heading.addLayout(right_titles)
        right_heading.addStretch()
        self.backup_count_label = QLabel("0 AVAILABLE")
        self.backup_count_label.setObjectName("CountPill")
        right_heading.addWidget(self.backup_count_label)
        right.addLayout(right_heading)

        self.backup_list = QListWidget()
        self.backup_list.setObjectName("BackupList")
        self.backup_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.backup_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.backup_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.backup_list.setMouseTracking(True)
        self.backup_list.setSpacing(1)
        self.backup_delegate = BackupCardDelegate(self.backup_list)
        self.backup_list.setItemDelegate(self.backup_delegate)
        right.addWidget(self.backup_list, stretch=1)

        zip_caption = QLabel("EXTERNAL ARCHIVE")
        zip_caption.setObjectName("SourceCaption")
        right.addWidget(zip_caption)
        zip_row = QHBoxLayout()
        zip_row.setSpacing(7)
        self.load_zip_button = QPushButton("  Import backup from ZIP…")
        folder_icon = QApplication.instance().style().standardIcon(
            QStyle.StandardPixmap.SP_DirOpenIcon
        )
        self.load_zip_button.setIcon(folder_icon)
        self.load_zip_button.setStyleSheet(_XBOX_BTN_OUTLINE)
        self.load_zip_button.clicked.connect(self._handle_load_from_zip)
        self.clear_zip_button = QPushButton("Remove ZIP")
        self.clear_zip_button.setStyleSheet(_XBOX_BTN_OUTLINE)
        self.clear_zip_button.clicked.connect(self._handle_clear_zip)
        self.clear_zip_button.hide()
        zip_row.addWidget(self.load_zip_button, stretch=1)
        zip_row.addWidget(self.clear_zip_button)
        right.addLayout(zip_row)
        zip_helper = QLabel(
            "Only validated SaveState archives are accepted. Keep xemu closed while restoring."
        )
        zip_helper.setObjectName("ZipHelper")
        zip_helper.setWordWrap(True)
        right.addWidget(zip_helper)
        columns.addWidget(right_card, stretch=6)

        # --- Footer: stato persistente e unica azione primaria ---
        footer = QFrame()
        footer.setObjectName("RestoreFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 10, 12, 10)
        footer_layout.setSpacing(12)
        status_copy = QVBoxLayout()
        status_copy.setSpacing(1)
        self.status_kicker = QLabel("SELECT A BACKUP")
        self.status_kicker.setObjectName("StatusKicker")
        status_copy.addWidget(self.status_kicker)
        self.status_label = QLabel("Choose a local snapshot or import a ZIP to continue.")
        self.status_label.setObjectName("StatusText")
        self.status_label.setWordWrap(True)
        status_copy.addWidget(self.status_label)
        footer_layout.addLayout(status_copy, stretch=1)

        buttons = QDialogButtonBox()
        self.restore_button = buttons.addButton(
            "Restore to Xbox HDD", QDialogButtonBox.ButtonRole.AcceptRole
        )
        # Non usare SaveButton (#229954): resta nella palette Xbox del dialog
        self.restore_button.setStyleSheet(_XBOX_BTN_PRIMARY)
        self.restore_button.setMinimumWidth(168)
        self.restore_button.setEnabled(False)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setObjectName("CancelButton")
        buttons.accepted.connect(self._on_restore_clicked)
        buttons.rejected.connect(self.reject)
        self._cancel_button = cancel_button
        footer_layout.addWidget(buttons)
        root.addWidget(footer)

        self.backup_list.currentItemChanged.connect(self._on_backup_selection)
        self.backup_list.itemDoubleClicked.connect(lambda _i: self._on_restore_clicked())

        if not self.hdd_path:
            self.games_hint.setText("HDD unavailable · Title scan and restore are disabled.")
            self.restore_button.setEnabled(False)
            self.hdd_path_label.setText("No HDD image is configured for this profile.")
        else:
            self.hdd_path_label.setText(self.hdd_path)

    def _reload_hdd_games(self) -> None:
        self.games_list.clear()
        if not self.hdd_path or not os.path.isfile(self.hdd_path):
            self.hdd_panel.set_hdd_info("— MB", 0)
            return

        try:
            games = _scan_hdd_games(self.hdd_path)
        except Exception as exc:
            logging.error("xemu restore UI: HDD scan failed: %s", exc, exc_info=True)
            self.games_hint.setText(f"Scan failed · {exc}")
            self.hdd_panel.set_hdd_info(_format_size_mb(self.hdd_path), 0)
            return

        present = False
        for game in games:
            item = QListWidgetItem(game["name"])
            item.setData(TITLE_ROLE, game["title_id"])
            item.setToolTip(f"{game['title_id']} · {game['area']}")
            is_current = game["title_id"] == self.title_id
            item.setData(CURRENT_TITLE_ROLE, is_current)
            if is_current:
                present = True
                item.setText(f"{game['name']}  ·  profile")
                item.setToolTip(f"{game['title_id']} · {game['area']} · current profile")
            else:
                item.setToolTip(f"{game['title_id']} · {game['area']}")
            self.games_list.addItem(item)

        self._title_was_present = present
        self.hdd_panel.set_hdd_info(_format_size_mb(self.hdd_path), len(games))
        if present:
            self.games_hint.setText(
                "Overwrite mode · This title already exists; only its save data will be replaced."
            )
        else:
            self.games_hint.setText(
                "New title · Save data will be added, with FATX remapping when needed."
            )

    def _populate_backups(self) -> None:
        self.backup_list.clear()
        self._zip_list_item = None

        parent = self.parent()
        if parent and hasattr(parent, "current_settings"):
            backup_base = parent.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            backup_base = config.BACKUP_BASE_DIR

        backups = core_logic.list_available_backups(
            self.profile_name, backup_base, profile_data=self.profile_data
        )
        self.backup_count_label.setText(
            f"{len(backups)} AVAILABLE" if len(backups) != 1 else "1 AVAILABLE"
        )
        if not backups:
            empty = QListWidgetItem("")
            empty.setData(BACKUP_EMPTY_ROLE, True)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.backup_list.addItem(empty)
            return

        lock_icon = None
        try:
            from PySide6.QtGui import QIcon

            icon_path = resource_path("icons/Lock.png")
            if os.path.exists(icon_path):
                lock_icon = QIcon(icon_path)
        except Exception:
            lock_icon = None

        locked = lock_backup_manager.get_locked_backup_for_profile(self.profile_name)
        locale = QLocale.system()
        for name, path, dt_obj in backups:
            date_str = "???"
            if dt_obj:
                try:
                    date_str = locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
                except Exception:
                    pass
            display = core_logic.get_display_name_from_backup_filename(name)
            item = QListWidgetItem(display)
            item.setData(PATH_ROLE, path)
            item.setData(BACKUP_DATE_ROLE, date_str)
            item.setData(BACKUP_KIND_ROLE, "LOCAL")
            item.setToolTip(f"{display}\n{date_str}\n{path}")
            if locked and os.path.normcase(os.path.normpath(path)) == os.path.normcase(
                os.path.normpath(locked)
            ):
                if lock_icon:
                    item.setIcon(lock_icon)
                item.setToolTip(
                    f"{display}\n{date_str}\n{path}\nLocked (protected from deletion)"
                )
            self.backup_list.addItem(item)

    def _on_backup_selection(self, current, _previous) -> None:
        ok = bool(current and current.data(PATH_ROLE))
        self.restore_button.setEnabled(ok and not self._restore_running and bool(self.hdd_path))
        if self._restore_running:
            return
        self.status_label.setStyleSheet("")
        if ok:
            kind = str(current.data(BACKUP_KIND_ROLE) or "LOCAL").upper()
            self.status_kicker.setText("READY TO RESTORE")
            self.status_label.setText(
                f"{kind.title()} backup selected · It will be written to the live Xbox HDD."
            )
        else:
            self.status_kicker.setText("SELECT A BACKUP")
            self.status_label.setText(
                "Choose a local snapshot or import a ZIP to continue."
            )

    def get_selected_path(self) -> Optional[str]:
        item = self.backup_list.currentItem()
        if not item:
            return None
        path = item.data(PATH_ROLE)
        return path if isinstance(path, str) else None

    def _handle_load_from_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Backup ZIP",
            "",
            "ZIP Archives (*.zip);;All Files (*)",
        )
        if not path:
            return
        ok, result = core_logic.validate_backup_zip(path)
        if not ok:
            QMessageBox.warning(self, "Invalid Backup", str(result))
            return

        if self._zip_list_item is not None:
            row = self.backup_list.row(self._zip_list_item)
            if row >= 0:
                self.backup_list.takeItem(row)
            self._zip_list_item = None

        for row in range(self.backup_list.count() - 1, -1, -1):
            candidate = self.backup_list.item(row)
            if candidate and candidate.data(BACKUP_EMPTY_ROLE):
                self.backup_list.takeItem(row)

        name = os.path.basename(path)
        item = QListWidgetItem(os.path.splitext(name)[0])
        item.setData(PATH_ROLE, path)
        item.setData(BACKUP_DATE_ROLE, "Imported archive")
        item.setData(BACKUP_KIND_ROLE, "ZIP")
        item.setToolTip(path)
        self.backup_list.insertItem(0, item)
        self._zip_list_item = item
        self.backup_list.setCurrentItem(item)
        available = sum(
            1
            for row in range(self.backup_list.count())
            if self.backup_list.item(row).data(PATH_ROLE)
        )
        self.backup_count_label.setText(
            f"{available} AVAILABLE" if available != 1 else "1 AVAILABLE"
        )
        self.clear_zip_button.show()

    def _handle_clear_zip(self) -> None:
        if self._zip_list_item is not None:
            row = self.backup_list.row(self._zip_list_item)
            if row >= 0:
                self.backup_list.takeItem(row)
            self._zip_list_item = None
        self.clear_zip_button.hide()
        self._populate_backups()
        self._on_backup_selection(self.backup_list.currentItem(), None)

    def _set_busy(self, busy: bool) -> None:
        self._restore_running = busy
        self.restore_button.setEnabled(
            not busy and bool(self.get_selected_path()) and bool(self.hdd_path)
        )
        self.load_zip_button.setEnabled(not busy)
        self.clear_zip_button.setEnabled(not busy)
        self.backup_list.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        if busy:
            self.status_kicker.setText("RESTORE IN PROGRESS")
            self.status_label.setText(
                f"Writing {self.game_name} directly into the live Xbox HDD…"
            )
            self.status_label.setStyleSheet("")
        mw = self.parent()
        if mw and hasattr(mw, "set_controls_enabled"):
            mw.set_controls_enabled(not busy)

    def _on_restore_clicked(self) -> None:
        if self._restore_running:
            return
        archive = self.get_selected_path()
        if not archive or not self.hdd_path:
            return

        if self._title_was_present:
            msg = (
                f"Restore '{os.path.basename(archive)}' into the live HDD?\n\n"
                f"Title '{self.game_name}' ({self.title_id}) is already on the disk — "
                f"its save data will be overwritten.\n\n"
                f"Other games on the HDD will not be touched."
            )
        else:
            msg = (
                f"Restore '{os.path.basename(archive)}' into the live HDD?\n\n"
                f"Title '{self.game_name}' ({self.title_id}) is not on the disk yet — "
                f"it will be added (FATX remap if needed).\n\n"
                f"Other games on the HDD will not be touched.\n"
                f"Make sure xemu is closed."
            )

        confirm = QMessageBox.warning(
            self,
            "Confirm xemu Restore",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        mw = self.parent()
        if (
            mw
            and hasattr(mw, "worker_thread")
            and mw.worker_thread
            and mw.worker_thread.isRunning()
        ):
            QMessageBox.information(
                self, "Operation in Progress", "Another operation is already in progress."
            )
            return

        self._title_was_present = self._find_game_row(self.title_id) is not None
        self._set_busy(True)
        self._anim_done = False
        self._worker_done = False
        self._min_timer_done = False
        self._worker_success = False
        self._worker_message = ""

        self._start_fly_animation()
        QTimer.singleShot(MIN_ANIM_MS, self._on_min_timer)

        dest = self.profile_data.get("paths") or [self.hdd_path]
        self._worker = WorkerThread(
            core_logic.perform_restore,
            self.profile_name,
            dest,
            archive,
            self.profile_data,
        )
        self._worker.finished.connect(self._on_worker_finished)
        if mw and hasattr(mw, "worker_thread"):
            mw.worker_thread = self._worker
        self._worker.start()

    def _find_game_row(self, title_id: str) -> Optional[int]:
        tid = (title_id or "").strip().lower()
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if item and str(item.data(TITLE_ROLE) or "").lower() == tid:
                return i
        return None

    def _target_games_rect(self) -> QRect:
        row = self._find_game_row(self.title_id)
        if row is not None:
            item = self.games_list.item(row)
            vr = self.games_list.visualItemRect(item)
            top_left = self.games_list.viewport().mapTo(self, vr.topLeft())
            return QRect(top_left, vr.size())

        if self.games_list.count() > 0:
            last = self.games_list.item(self.games_list.count() - 1)
            vr = self.games_list.visualItemRect(last)
            top_left = self.games_list.viewport().mapTo(
                self, QPoint(vr.left(), vr.bottom() + 2)
            )
            return QRect(top_left, QSize(max(120, vr.width()), max(24, vr.height())))

        # Empty list: aim at sticker well center
        well = self.hdd_panel._label_area
        gp = self.hdd_panel.mapTo(self, well.center())
        return QRect(gp.x() - 80, gp.y() - 14, 160, 28)

    def _start_fly_animation(self) -> None:
        self._cleanup_ghost()
        src_item = self.backup_list.currentItem()
        if not src_item:
            self._anim_done = True
            self._try_finish()
            return

        src_rect = self.backup_list.visualItemRect(src_item)
        src_top = self.backup_list.viewport().mapTo(self, src_rect.topLeft())
        start = QRect(src_top, src_rect.size())
        end = self._target_games_rect()

        ghost = QLabel(self.game_name, self)
        ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ghost.setStyleSheet(
            f"""
            QLabel {{
                background-color: #1A1F1A;
                color: white;
                border: 2px solid {XBOX_LIME};
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: bold;
            }}
            """
        )
        ghost.setGeometry(start)
        ghost.show()
        ghost.raise_()
        self._ghost = ghost

        effect = QGraphicsOpacityEffect(ghost)
        ghost.setGraphicsEffect(effect)
        effect.setOpacity(1.0)

        pos_anim = QPropertyAnimation(ghost, b"geometry")
        pos_anim.setDuration(MIN_ANIM_MS)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        opacity_anim = QPropertyAnimation(effect, b"opacity")
        opacity_anim.setDuration(MIN_ANIM_MS)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setKeyValueAt(0.75, 1.0)
        opacity_anim.setEndValue(0.35)
        opacity_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(opacity_anim)
        group.finished.connect(self._on_anim_finished)
        self._fly_group = group
        group.start()

    def _on_anim_finished(self) -> None:
        self._anim_done = True
        self._try_finish()

    def _on_min_timer(self) -> None:
        self._min_timer_done = True
        self._try_finish()

    def _on_worker_finished(self, success: bool, message: str) -> None:
        self._worker_done = True
        self._worker_success = bool(success)
        self._worker_message = message or ""
        self._try_finish()

    def _try_finish(self) -> None:
        if not (self._worker_done and self._min_timer_done and self._anim_done):
            return
        if not self._restore_running:
            return

        self._cleanup_ghost()

        if self._worker_success:
            was_present = self._title_was_present
            self._reload_hdd_games()
            if not was_present:
                self.hdd_panel.bump_count_pulse()
            self._pulse_existing_title()
            self.status_kicker.setText("RESTORE COMPLETE")
            self.status_label.setText(self._worker_message or "Restore completed.")
            self.status_label.setStyleSheet("")
        else:
            self.status_kicker.setText("RESTORE FAILED")
            self.status_label.setText(self._worker_message or "Restore failed.")
            self.status_label.setStyleSheet("color: #FF8E8E;")
            QMessageBox.critical(
                self,
                "xemu Restore Failed",
                self._worker_message or "Restore failed.",
            )

        self._set_busy(False)
        mw = self.parent()
        if mw and getattr(mw, "worker_thread", None) is self._worker:
            mw.worker_thread = None
        self.restore_completed.emit(self._worker_success, self._worker_message)

    def _pulse_existing_title(self) -> None:
        row = self._find_game_row(self.title_id)
        if row is None:
            return
        item = self.games_list.item(row)
        item.setData(UPDATED_BADGE_ROLE, True)
        self.games_list.scrollToItem(item)
        self.games_list.viewport().update()

        def _clear():
            if item:
                item.setData(UPDATED_BADGE_ROLE, False)
                self.games_list.viewport().update()

        QTimer.singleShot(1800, _clear)

    def _cleanup_ghost(self) -> None:
        if self._fly_group:
            self._fly_group.stop()
            self._fly_group = None
        if self._ghost:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None

    def reject(self) -> None:
        if self._restore_running:
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._restore_running:
            event.ignore()
            return
        self._cleanup_ghost()
        super().closeEvent(event)
