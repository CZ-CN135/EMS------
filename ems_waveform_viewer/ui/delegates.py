# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QListWidget
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtCore import QRect, QEvent, Qt
from ems_waveform_viewer.utils import _is_checked_state

class CheckBoxDelegate(QStyledItemDelegate):
    CHECK_SIZE = 16
    CHECK_RADIUS = 3
    LEFT_PADDING = 6
    TEXT_GAP = 8

    CHECK_FILLED = QColor("#1f77b4")
    CHECK_BORDER = QColor("#7a7a7a")
    CHECK_BG = QColor("#ffffff")
    CHECK_MARK = QColor("#ffffff")

    def _check_rect(self, option):
        r = option.rect
        top = r.top() + (r.height() - self.CHECK_SIZE) // 2
        return QRect(r.left() + self.LEFT_PADDING, top, self.CHECK_SIZE, self.CHECK_SIZE)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), self.CHECK_SIZE + 6))
        return size

    def _read_checked(self, index, option) -> bool:
        try:
            lw = option.widget
            if isinstance(lw, QListWidget):
                it = lw.item(index.row())
                if it is not None: return _is_checked_state(it.checkState())
        except Exception: pass
        try:
            v = index.data(Qt.CheckStateRole)
            return _is_checked_state(v)
        except Exception: return False

    def paint(self, painter, option, index):
        try: self._paint_impl(painter, option, index)
        except Exception:
            try: super().paint(painter, option, index)
            except Exception: pass

    def _paint_impl(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        try:
            if option.state & QStyle.State_Selected: painter.fillRect(rect, option.palette.highlight())
            elif option.state & QStyle.State_MouseOver:
                c = option.palette.highlight().color()
                c.setAlpha(40)
                painter.fillRect(rect, c)
        except Exception: pass

        check_rect = self._check_rect(option)
        checked = self._read_checked(index, option)

        if checked:
            painter.setBrush(QBrush(self.CHECK_FILLED))
            painter.setPen(QPen(self.CHECK_FILLED, 1))
        else:
            painter.setBrush(QBrush(self.CHECK_BG))
            painter.setPen(QPen(self.CHECK_BORDER, 1))
        painter.drawRoundedRect(check_rect, self.CHECK_RADIUS, self.CHECK_RADIUS)

        if checked:
            pen = QPen(self.CHECK_MARK, 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            x1, y1 = check_rect.left() + 3, check_rect.top() + 8
            x2, y2 = check_rect.left() + 6, check_rect.top() + 11
            x3, y3 = check_rect.left() + 12, check_rect.top() + 4
            painter.drawLine(x1, y1, x2, y2)
            painter.drawLine(x2, y2, x3, y3)

        text = str(index.data(Qt.DisplayRole) or "")
        text_rect = QRect(check_rect.right() + self.TEXT_GAP, rect.top(), max(0, rect.right() - (check_rect.right() + self.TEXT_GAP) - 4), rect.height())

        fg_color = None
        try:
            fg_brush = index.data(Qt.ForegroundRole)
            if isinstance(fg_brush, QBrush): fg_color = fg_brush.color()
            elif isinstance(fg_brush, QColor): fg_color = fg_brush
        except Exception: pass

        if option.state & QStyle.State_Selected: fg_color = option.palette.highlightedText().color()
        if fg_color is None: fg_color = option.palette.text().color()
        painter.setPen(fg_color)

        fm = painter.fontMetrics()
        elided = fm.elidedText(text, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            try: pos = event.position().toPoint()
            except AttributeError: pos = event.pos()
            if self._check_rect(option).contains(pos):
                lw = option.widget
                if isinstance(lw, QListWidget):
                    item = lw.item(index.row())
                    if item is not None:
                        new = Qt.Unchecked if _is_checked_state(item.checkState()) else Qt.Checked
                        item.setCheckState(new)
                        try: lw.viewport().update()
                        except Exception: pass
                        return True
                cur = _is_checked_state(index.data(Qt.CheckStateRole))
                new = Qt.Unchecked if cur else Qt.Checked
                model.setData(index, new, Qt.CheckStateRole)
                return True
        return super().editorEvent(event, model, option, index)