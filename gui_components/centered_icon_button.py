# gui_components/centered_icon_button.py
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter
from PySide6.QtGui import QIcon
from PySide6.QtCore import QRect


class CenteredIconButton(QPushButton):
    """A QPushButton that centers icon + text together as one block,
    like a normal button, but with a bigger space between them.

    A normal QPushButton keeps the icon and the text almost touching (about 4 px)
    and there is no setting to change that space.
    """

    QT_GAP = 4  # Space a normal QPushButton puts between icon and text

    def __init__(self, text="", parent=None, icon_gap=8):
        super().__init__(text, parent)
        self._icon_gap = icon_gap  # Space between the icon and the text, in pixels

    def sizeHint(self):
        hint = super().sizeHint()
        if not self.icon().isNull() and self.text():
            # The normal hint already counts the icon and 4 px of space
            hint.setWidth(hint.width() + max(0, self._icon_gap - self.QT_GAP))
        return hint

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        icon = QIcon(option.icon)  # A real copy: the next line clears option.icon
        option.icon = QIcon()

        # 1. The button background and border
        painter.drawControl(QStyle.ControlElement.CE_PushButtonBevel, option)

        size = self.iconSize()
        if icon.isNull():
            painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)
            return

        if option.text:
            # Icon + space + text, centered together as one block
            text_width = self.fontMetrics().horizontalAdvance(option.text)
            block_width = size.width() + self._icon_gap + text_width
            x = max((self.width() - block_width) // 2, 4)
            # 2. The text, moved right so it sits just after the icon
            shift = (size.width() + self._icon_gap) // 2
            option.rect = option.rect.translated(shift, 0)
            painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)
        else:
            x = (self.width() - size.width()) // 2  # Icon only: center it
        y = (self.height() - size.height()) // 2

        # 3. The icon
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        pixmap = icon.pixmap(size, self.devicePixelRatioF(), mode)
        painter.drawPixmap(QRect(x, y, size.width(), size.height()), pixmap)
