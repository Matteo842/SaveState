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
from dialogs.restore_dialog import RestoreSelectionDelegate
from gui.gui_utils import WorkerThread
from gui_components import lock_backup_manager
from common.utils import resource_path


# Verde iconico prima Xbox (lime storico 2001) + verde brand più scuro
XBOX_LIME = "#9BC848"
XBOX_GREEN = "#107C10"
XBOX_LIME_BRIGHT = "#C5E872"
XBOX_METAL_TOP = "#C8CCD0"
XBOX_METAL_MID = "#9EA3A8"
XBOX_METAL_DARK = "#5C6166"

# Stili bottoni: stessa famiglia (lime bordo / green fill) — niente #229954 di SaveButton
_XBOX_BTN_PRIMARY = f"""
QPushButton {{
    padding: 8px 18px;
    font-weight: bold;
    color: #FFFFFF;
    background-color: {XBOX_GREEN};
    border: 2px solid {XBOX_LIME};
    border-radius: 4px;
}}
QPushButton:hover {{
    background-color: #0D6A0D;
    border-color: {XBOX_LIME_BRIGHT};
}}
QPushButton:pressed {{
    background-color: #0A550A;
}}
QPushButton:disabled {{
    color: #AAAAAA;
    background-color: #3A3A3A;
    border-color: #555555;
}}
"""

_XBOX_BTN_OUTLINE = f"""
QPushButton {{
    padding: 8px 16px;
    font-weight: bold;
    color: {XBOX_LIME};
    background-color: transparent;
    border: 2px solid {XBOX_LIME};
    border-radius: 4px;
}}
QPushButton:hover {{
    color: #FFFFFF;
    background-color: {XBOX_GREEN};
    border-color: {XBOX_LIME_BRIGHT};
}}
QPushButton:pressed {{
    background-color: #0A550A;
}}
QPushButton:disabled {{
    color: #666666;
    border-color: #555555;
}}
"""


MIN_ANIM_MS = 1200
TITLE_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole
CURRENT_TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
UPDATED_BADGE_ROLE = Qt.ItemDataRole.UserRole + 2


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
            painter.fillRect(option.rect, QColor(155, 200, 72, 45))
            painter.fillRect(
                option.rect.x(),
                option.rect.y(),
                3,
                option.rect.height(),
                QColor(XBOX_LIME),
            )

        if updated:
            painter.fillRect(option.rect, QColor(16, 124, 16, 70))

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


class XemuHddPanel(QWidget):
    """HDD 3.5\" stilizzato con lista giochi nella zona sticker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._size_label = "— MB"
        self._game_count = 0
        self._pulse = 0.0
        self._body = QRect()
        self._label_area = QRect()

        self.setMinimumSize(260, 380)
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
                background: rgba(155, 200, 72, 40);
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
        return QSize(300, 480)

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
        self.setMinimumSize(780, 560)
        self.resize(860, 620)

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
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QLabel(
            f"Inject save for <b>{self.game_name}</b> "
            f"<span style='color:#888'>({self.title_id or '????'})</span> into the live xemu HDD."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        root.addLayout(columns, stretch=1)

        # --- Left: HDD with games inside ---
        left = QVBoxLayout()
        left.setSpacing(4)
        left_title = QLabel("Xbox HDD")
        left_title.setStyleSheet(f"font-weight: bold; color: {XBOX_LIME};")
        left.addWidget(left_title)

        self.hdd_panel = XemuHddPanel()
        left.addWidget(self.hdd_panel, stretch=1)

        self.hdd_path_label = QLabel("")
        self.hdd_path_label.setWordWrap(True)
        self.hdd_path_label.setStyleSheet("color: #888; font-size: 11px;")
        left.addWidget(self.hdd_path_label)

        self.games_hint = QLabel("")
        self.games_hint.setStyleSheet("color: #888; font-size: 11px;")
        self.games_hint.setWordWrap(True)
        left.addWidget(self.games_hint)
        columns.addLayout(left, stretch=5)

        # --- Right: backups ---
        right = QVBoxLayout()
        right_title = QLabel("Backups")
        right_title.setStyleSheet(f"font-weight: bold; color: {XBOX_LIME};")
        right.addWidget(right_title)
        self.backup_list = QListWidget()
        self.backup_delegate = RestoreSelectionDelegate(self.backup_list)
        self.backup_list.setItemDelegate(self.backup_delegate)
        right.addWidget(self.backup_list, stretch=1)

        zip_row = QHBoxLayout()
        self.load_zip_button = QPushButton("  Load from ZIP...")
        folder_icon = QApplication.instance().style().standardIcon(
            QStyle.StandardPixmap.SP_DirOpenIcon
        )
        self.load_zip_button.setIcon(folder_icon)
        self.load_zip_button.setStyleSheet(_XBOX_BTN_OUTLINE)
        self.load_zip_button.clicked.connect(self._handle_load_from_zip)
        self.clear_zip_button = QPushButton("Clear Selection")
        self.clear_zip_button.clicked.connect(self._handle_clear_zip)
        self.clear_zip_button.hide()
        zip_row.addWidget(self.load_zip_button)
        zip_row.addWidget(self.clear_zip_button)
        zip_row.addStretch()
        right.addLayout(zip_row)
        columns.addLayout(right, stretch=4)

        buttons = QDialogButtonBox()
        self.restore_button = buttons.addButton(
            "Restore Selected", QDialogButtonBox.ButtonRole.AcceptRole
        )
        # Non usare SaveButton (#229954): resta nella palette Xbox del dialog
        self.restore_button.setStyleSheet(_XBOX_BTN_PRIMARY)
        self.restore_button.setEnabled(False)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_restore_clicked)
        buttons.rejected.connect(self.reject)
        self._cancel_button = cancel_button
        root.addWidget(buttons)

        self.backup_list.currentItemChanged.connect(self._on_backup_selection)
        self.backup_list.itemDoubleClicked.connect(lambda _i: self._on_restore_clicked())

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #AAAAAA;")
        root.addWidget(self.status_label)

        if not self.hdd_path:
            self.games_hint.setText("HDD path missing — cannot scan titles.")
            self.restore_button.setEnabled(False)
            self.hdd_path_label.setText("No HDD configured on this profile.")
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
            self.games_hint.setText(f"Failed to scan HDD: {exc}")
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
                "This Title ID is already on the HDD — restore will overwrite its save data."
            )
        else:
            self.games_hint.setText(
                "This Title ID is not on the HDD yet — restore will add it (remap if needed)."
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
        if not backups:
            empty = QListWidgetItem("No backups found for this profile.")
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
            item = QListWidgetItem(f"{display} ({date_str})")
            item.setData(PATH_ROLE, path)
            if locked and os.path.normcase(os.path.normpath(path)) == os.path.normcase(
                os.path.normpath(locked)
            ):
                if lock_icon:
                    item.setIcon(lock_icon)
                item.setToolTip("Locked backup (protected from deletion)")
            self.backup_list.addItem(item)

    def _on_backup_selection(self, current, _previous) -> None:
        ok = bool(current and current.data(PATH_ROLE))
        self.restore_button.setEnabled(ok and not self._restore_running and bool(self.hdd_path))

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

        name = os.path.basename(path)
        item = QListWidgetItem(f"[ZIP] {name}")
        item.setData(PATH_ROLE, path)
        self.backup_list.insertItem(0, item)
        self._zip_list_item = item
        self.backup_list.setCurrentItem(item)
        self.clear_zip_button.show()

    def _handle_clear_zip(self) -> None:
        if self._zip_list_item is not None:
            row = self.backup_list.row(self._zip_list_item)
            if row >= 0:
                self.backup_list.takeItem(row)
            self._zip_list_item = None
        self.clear_zip_button.hide()

    def _set_busy(self, busy: bool) -> None:
        self._restore_running = busy
        self.restore_button.setEnabled(not busy and bool(self.get_selected_path()))
        self.load_zip_button.setEnabled(not busy)
        self.clear_zip_button.setEnabled(not busy)
        self.backup_list.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        if busy:
            self.status_label.setText("Restoring into HDD…")
            self.status_label.setStyleSheet(f"color: {XBOX_LIME};")
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
            self.status_label.setText(self._worker_message or "Restore completed.")
            self.status_label.setStyleSheet(f"color: {XBOX_LIME};")
        else:
            self.status_label.setText(self._worker_message or "Restore failed.")
            self.status_label.setStyleSheet("color: #FF5555;")
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
