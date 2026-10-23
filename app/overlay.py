# -*- coding: utf-8 -*-
"""全屏定格覆盖层：冻结画面 + 拖拽框选。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from capture import Shot


class Overlay(QWidget):
    """selected 发出的是相对整屏的物理像素 (x, y, w, h)。"""

    selected = Signal(tuple)
    canceled = Signal()

    def __init__(self, shot: Shot, dpr: float):
        super().__init__()
        self.shot = shot
        self.dpr = dpr

        img = shot.image.convert("RGB")
        qimg = QImage(
            img.tobytes("raw", "RGB"),
            img.width,
            img.height,
            img.width * 3,
            QImage.Format_RGB888,
        ).copy()
        self.pix = QPixmap.fromImage(qimg)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        # 物理 -> 逻辑
        self.setGeometry(
            int(shot.left / dpr),
            int(shot.top / dpr),
            int(shot.width / dpr),
            int(shot.height / dpr),
        )

        self._start: QPoint | None = None
        self._cur: QPoint | None = None

    # ---------- 绘制 ----------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        sel = self._sel_rect()
        if sel is not None and sel.width() > 2 and sel.height() > 2:
            src = QRect(
                int(sel.x() * self.dpr),
                int(sel.y() * self.dpr),
                int(sel.width() * self.dpr),
                int(sel.height() * self.dpr),
            )
            p.drawPixmap(sel, self.pix, src)
            p.setPen(QPen(QColor(64, 180, 255), 2))
            p.drawRect(sel)

            size = f"{int(sel.width() * self.dpr)} x {int(sel.height() * self.dpr)}"
            p.setPen(QColor(64, 180, 255))
            p.drawText(sel.adjusted(4, -20, 4, 0), Qt.AlignLeft | Qt.AlignBottom, size)

        if self._start is None:
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                self.rect().adjusted(0, 40, 0, 0),
                Qt.AlignHCenter | Qt.AlignTop,
                "拖动框选要翻译的区域    ·    Esc 取消",
            )
        p.end()

    def _sel_rect(self) -> QRect | None:
        if self._start is None or self._cur is None:
            return None
        return QRect(self._start, self._cur).normalized()

    # ---------- 交互 ----------
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._start = ev.position().toPoint()
            self._cur = self._start
            self.update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._start is not None:
            self._cur = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.LeftButton or self._start is None:
            return
        self._cur = ev.position().toPoint()
        sel = self._sel_rect().intersected(self.rect())
        self._start = None
        self.close()
        if sel is not None and sel.width() > 6 and sel.height() > 6:
            self.selected.emit(
                (
                    int(sel.x() * self.dpr),
                    int(sel.y() * self.dpr),
                    int(sel.width() * self.dpr),
                    int(sel.height() * self.dpr),
                )
            )
        else:
            self.canceled.emit()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.close()
            self.canceled.emit()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self.activateWindow()
        self.raise_()
        self.setFocus()
        QGuiApplication.processEvents()
