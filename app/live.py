# -*- coding: utf-8 -*-
"""实时翻译：监听框选区域，内容变化后自动翻译，结果显示在独立浮窗里。

浮窗特性：
  · 半透明遮罩背景（透明度可调，默认 60%）
  · 译文用独立文本框显示，字号可调（12–32px，默认 17）
  · 标题栏可拖动；点 × 或按 Alt+W / Esc 关闭
  · 通过 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) 从截屏中排除，
    即使遮住监听区域也不会拍到自己（否则会自我循环）

轮询三层去抖（实测数据见 HANDOFF）：
  1. 像素级：dHash(16x16) 汉明 <= 3 视为未变（约 1ms）
  2. 稳定级：变化后需再稳定一拍才识别（避开滚动中的半截文本）
  3. 兜底：连续 4 拍（~1.2s）无变化也强制识别一次
     —— 9x8 的粗哈希对"同位置、字数相近的文字变化"会算出相同哈希（实测汉明=0），
        光靠哈希会漏掉字幕换句；加大到 16x16 后仍可能接近，故必须保留强制识别
  4. 文本级：OCR 结果归一化后与上次比较，相同不重复翻译（挡光标闪烁）
"""
from __future__ import annotations

import ctypes
import re
import sys
import time

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QPoint, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import capture
import layout
import ocr
import translate

POLL_MS = 300
HASH_SIZE = 16          # 9x8 太粗：同一位置、字数相近的文字变化会算出相同哈希
HASH_TOLERANCE = 3      # 16x16=256 bit；静止画面实测差 0，容差 3 足够安全
MIN_INTERVAL = 0.5      # 两次识别的最小间隔（变化频繁时限速，避免堆积）
IDLE_INTERVAL = 1.2     # 画面稳定时的兜底识别间隔（防哈希盲区漏句）
BUSY_WATCHDOG = 15.0    # 单次识别超过这么久视为卡死，强制解锁
WDA_EXCLUDEFROMCAPTURE = 0x00000011

PANEL_MIN_W, PANEL_MIN_H = 340, 200      # 最小尺寸（用户可自由放大）
PANEL_DEFAULT_W, PANEL_DEFAULT_H = 560, 300
PANEL_MAX_W = 1200
FONT_MIN, FONT_MAX, FONT_DEFAULT = 12, 32, 17
OPACITY_MIN, OPACITY_MAX, OPACITY_DEFAULT = 25, 95, 60

PANEL_QSS = """
QLabel#head { color:#dfe3e8; font-size:12px; }
QLabel#status { color:#9aa0a6; font-size:11px; }
QLabel#tag { color:#8a9099; font-size:11px; }
QPushButton#close {
    background:rgba(255,255,255,0.08); color:#cfd3da; border:none;
    border-radius:6px; font-size:14px; padding:0px;
}
QPushButton#close:hover { background:rgba(220,80,80,0.55); color:#fff; }
QPushButton#gear {
    background:rgba(255,255,255,0.08); color:#cfd3da; border:none;
    border-radius:6px; font-size:13px; padding:0px;
}
QPushButton#gear:hover { background:rgba(255,255,255,0.20); color:#fff; }
QPushButton#step {
    background:rgba(255,255,255,0.09); color:#e6e9ee; border:none;
    border-radius:5px; font-size:13px; padding:1px 0px;
}
QPushButton#step:hover { background:rgba(255,255,255,0.18); }
QFrame#box {
    background: rgba(22, 24, 29, 240);
    border: 1px solid rgba(255,255,255,32);
    border-radius: 10px;
}
QLabel#prev { color:#9aa3ad; font-size:12px; }
QFrame#line { background: rgba(255,255,255,26); max-height:1px; }
QSizeGrip { background: transparent; width:14px; height:14px; }
QPlainTextEdit#body {
    background:transparent; border:none; color:#f2f5f8;
    selection-background-color:#2f6fdb;
}
QSlider::groove:horizontal { height:3px; background:rgba(255,255,255,0.18); border-radius:2px; }
QSlider::handle:horizontal {
    width:12px; height:12px; margin:-5px 0; border-radius:6px; background:#4a9eff;
}
QSlider::sub-page:horizontal { background:rgba(74,158,255,0.75); border-radius:2px; }
"""


def dhash(img: Image.Image, size: int = HASH_SIZE) -> int:
    g = img.convert("L").resize((size, size - 1), Image.BILINEAR)
    a = np.asarray(g, dtype=np.int16)
    bits = 0
    for b in (a[:, 1:] > a[:, :-1]).flatten():
        bits = (bits << 1) | int(b)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _exclude_from_capture(widget: QWidget) -> bool:
    """让窗口从屏幕捕获中消失（Win10 2004+）。失败返回 False。"""
    if sys.platform != "win32":
        return False
    try:
        return bool(
            ctypes.windll.user32.SetWindowDisplayAffinity(
                int(widget.winId()), WDA_EXCLUDEFROMCAPTURE
            )
        )
    except Exception:  # noqa: BLE001
        return False


class _Draggable(QWidget):
    """标题条：按住可拖动整个浮窗。"""

    def __init__(self, panel: "LivePanel", text: str):
        super().__init__(panel)
        self.panel = panel
        self._drag: QPoint | None = None
        self.label = QLabel(text, self)
        self.label.setObjectName("head")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)
        lay.addStretch(1)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.panel.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag is not None:
            self.panel._close_settings()
            self.panel.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag = None



class SettingsPopup(QWidget):
    """齿轮弹层：字号 + 透明度。"""

    font_changed = Signal(int)
    opacity_changed = Signal(int)

    def __init__(self, parent, font_size: int, opacity: int):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(PANEL_QSS)
        self._font_size = int(font_size)
        self._opacity = int(opacity)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("box")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # 字号
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        t1 = QLabel("字号", card)
        t1.setObjectName("tag")
        row1.addWidget(t1)
        self.btn_minus = QPushButton("−", card)
        self.btn_minus.setObjectName("step")
        self.btn_minus.setFixedSize(24, 22)
        self.btn_minus.clicked.connect(lambda: self._bump_font(-1))
        row1.addWidget(self.btn_minus)
        self.lbl_font = QLabel(str(self._font_size), card)
        self.lbl_font.setObjectName("status")
        self.lbl_font.setFixedWidth(26)
        self.lbl_font.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.lbl_font)
        self.btn_plus = QPushButton("+", card)
        self.btn_plus.setObjectName("step")
        self.btn_plus.setFixedSize(24, 22)
        self.btn_plus.clicked.connect(lambda: self._bump_font(1))
        row1.addWidget(self.btn_plus)
        row1.addStretch(1)
        lay.addLayout(row1)

        # 透明度
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        t2 = QLabel("透明度", card)
        t2.setObjectName("tag")
        row2.addWidget(t2)
        self.slider = QSlider(Qt.Horizontal, card)
        self.slider.setRange(OPACITY_MIN, OPACITY_MAX)
        self.slider.setValue(self._opacity)
        self.slider.setFixedWidth(130)
        self.slider.valueChanged.connect(self._on_slider)
        row2.addWidget(self.slider)
        self.lbl_opacity = QLabel(f"{self._opacity}%", card)
        self.lbl_opacity.setObjectName("status")
        self.lbl_opacity.setFixedWidth(36)
        row2.addWidget(self.lbl_opacity)
        row2.addStretch(1)
        lay.addLayout(row2)

        hint = QLabel("调整即时生效，并会记住", card)
        hint.setObjectName("tag")
        lay.addWidget(hint)

    def _bump_font(self, delta: int) -> None:
        value = max(FONT_MIN, min(FONT_MAX, self._font_size + delta))
        if value == self._font_size:
            return
        self._font_size = value
        self.lbl_font.setText(str(value))
        self.font_changed.emit(value)

    def _on_slider(self, value: int) -> None:
        self._opacity = value
        self.lbl_opacity.setText(f"{value}%")
        self.opacity_changed.emit(value)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        _exclude_from_capture(self)


class LivePanel(QWidget):
    """独立浮窗：半透明遮罩 + 最新/上一段译文 + 字号透明度设置 + 可自由缩放。"""

    closed = Signal()
    opacity_changed = Signal(int)
    font_changed = Signal(int)
    resized = Signal(int, int)

    def __init__(
        self,
        region_logical: tuple[int, int, int, int],
        opacity: int = OPACITY_DEFAULT,
        font_size: int = FONT_DEFAULT,
        pair_text: str = "实时翻译",
        size: tuple[int, int] | None = None,
    ):
        super().__init__()
        self._opacity = max(OPACITY_MIN, min(OPACITY_MAX, int(opacity)))
        self._font_size = max(FONT_MIN, min(FONT_MAX, int(font_size)))
        self._pair = pair_text  # 例如 "德语 → 中文"
        self._prev_text = ""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(PANEL_QSS)
        # 最小尺寸：再小就摆不下标题与两段文字
        self.setMinimumSize(PANEL_MIN_W, PANEL_MIN_H)

        self._place(region_logical, size)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 标题行：可拖动标题 + 设置齿轮 + 关闭
        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        self.head = _Draggable(self, self._title())
        head_row.addWidget(self.head, 1)

        self.btn_gear = QPushButton("\u2699", self)
        self.btn_gear.setObjectName("gear")
        self.btn_gear.setFixedSize(22, 22)
        self.btn_gear.setCursor(Qt.PointingHandCursor)
        self.btn_gear.setToolTip("字号 / 透明度")
        self.btn_gear.clicked.connect(self.toggle_settings)
        head_row.addWidget(self.btn_gear)

        self.btn_close = QPushButton("×", self)
        self.btn_close.setObjectName("close")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        head_row.addWidget(self.btn_close)
        root.addLayout(head_row)

        # 上一段译文（保留一小段时间，新的译文到来时被顶掉）
        self.prev = QLabel(self)
        self.prev.setObjectName("prev")
        self.prev.setWordWrap(True)
        self.prev.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.prev.hide()
        root.addWidget(self.prev)

        self.line = QFrame(self)
        self.line.setObjectName("line")
        self.line.setFrameShape(QFrame.HLine)
        self.line.hide()
        root.addWidget(self.line)

        # 最新译文
        self.body = QPlainTextEdit(self)
        self.body.setObjectName("body")
        self.body.setReadOnly(True)
        self.body.setPlaceholderText("等待内容变化…")
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root.addWidget(self.body, 1)

        self.status = QLabel("监听中 · Alt+P 暂停 · Alt+W 退出", self)
        self.status.setObjectName("status")
        root.addWidget(self.status)

        # 右下角缩放手柄（无边框窗口靠它调整大小）
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.setToolTip("拖动调整窗口大小")
        self._popup: SettingsPopup | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(400)
        self._resize_timer.timeout.connect(
            lambda: self.resized.emit(self.width(), self.height())
        )
        self._apply_font()

    # ---------- 设置弹层 ----------
    def toggle_settings(self) -> None:
        """齿轮：展开/收起 字号 + 透明度 设置弹层。"""
        if self._popup is not None and self._popup.isVisible():
            self._close_settings()
            return
        popup = SettingsPopup(self, self._font_size, self._opacity)
        popup.font_changed.connect(self.set_font_size)
        popup.opacity_changed.connect(self.set_mask_opacity)
        popup.adjustSize()

        gx = self.mapToGlobal(self.btn_gear.pos()).x() + self.btn_gear.width() - popup.width()
        gy = self.mapToGlobal(self.btn_gear.pos()).y() + self.btn_gear.height() + 6
        screen = QGuiApplication.primaryScreen().availableGeometry()
        gx = max(screen.left() + 8, min(gx, screen.right() - popup.width() - 8))
        popup.move(int(gx), int(gy))
        popup.show()
        self._popup = popup

    def _close_settings(self) -> None:
        if self._popup is not None:
            popup, self._popup = self._popup, None
            popup.close()

    def settings_visible(self) -> bool:
        return self._popup is not None and self._popup.isVisible()

    # ---------- 外观 ----------
    def _title(self) -> str:
        return f"{self._pair}   ·   实时翻译"

    def _place(self, region_logical: tuple[int, int, int, int],
               size: tuple[int, int] | None = None) -> None:
        x, y, w, h = region_logical
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if size:
            pw = max(PANEL_MIN_W, min(PANEL_MAX_W, int(size[0])))
            ph = max(PANEL_MIN_H, min(1000, int(size[1])))
        else:
            pw = max(PANEL_DEFAULT_W, min(PANEL_MAX_W, int(w)))
            ph = max(PANEL_DEFAULT_H, min(520, int(h) + 150))
        pw = min(pw, max(PANEL_MIN_W, screen.width() - 16))
        ph = min(ph, max(PANEL_MIN_H, screen.height() - 16))

        left = x + w + 16
        if left + pw > screen.right() - 8:
            left = max(screen.left() + 8, x - pw - 16)
        top = max(screen.top() + 8, min(y, screen.bottom() - ph - 8))
        self.setGeometry(int(left), int(top), int(pw), int(ph))

    def _apply_font(self) -> None:
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(self._font_size)
        self.body.setFont(f)
        pf = QFont("Microsoft YaHei UI")
        pf.setPixelSize(max(11, self._font_size - 3))
        self.prev.setFont(pf)

    def set_font_size(self, px: int) -> None:
        value = max(FONT_MIN, min(FONT_MAX, int(px)))
        if value == self._font_size:
            return
        self._font_size = value
        self._apply_font()
        self.font_changed.emit(value)

    def set_mask_opacity(self, value: int) -> None:
        value = max(OPACITY_MIN, min(OPACITY_MAX, int(value)))
        if value == self._opacity:
            return
        self._opacity = value
        self.opacity_changed.emit(value)
        self.update()

    # 兼容旧调用
    def _step_font(self, delta: int) -> None:
        self.set_font_size(self._font_size + delta)

    def set_pair(self, pair_text: str) -> None:
        if pair_text and pair_text != self._pair:
            self._pair = pair_text
            self.head.set_text(self._title())

    def set_text(self, text: str) -> None:
        current = self.body.toPlainText().strip()
        if current and current != text:
            self._prev_text = current
            shown = current if len(current) <= 260 else current[:260] + " …"
            self.prev.setText(shown)
            self.prev.show()
            self.line.show()
        self.body.setPlainText(text)
        self.status.setText(f"已更新 {time.strftime('%H:%M:%S')} · Alt+P 暂停 · Alt+W 退出")

    def previous_text(self) -> str:
        return self._prev_text

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        ok = _exclude_from_capture(self)
        self.status.setText(
            ("监听中 · Alt+P 暂停 · Alt+W 退出" if ok
             else "监听中（本窗口未被排除，可能拍到自身）· Alt+P 暂停 · Alt+W 退出")
        )
        self.raise_()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        grip = getattr(self, "grip", None)
        if grip is not None:
            grip.move(self.width() - grip.width() - 6, self.height() - grip.height() - 6)
            grip.raise_()
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.start()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._close_settings()
        self.closed.emit()
        super().closeEvent(ev)

    # ---------- 自绘遮罩 ----------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            alpha = int(self._opacity / 100 * 255)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 13, 16, alpha))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
            p.setPen(QColor(255, 255, 255, 26))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        finally:
            p.end()


class RecogniseWorker(QThread):
    """后台 OCR + 翻译。"""

    done = Signal(str, str, str)     # 原文, 译文, 语种对
    failed = Signal(str)

    def __init__(self, image: Image.Image, target: str | None, base: str, known: str):
        super().__init__()
        self.image = image
        self.target = target
        self.base = base
        self.known = known

    def run(self) -> None:  # noqa: D401
        try:
            lines, _src_lang = ocr.recognize_auto(self.image)
            paragraphs = layout.merge_paragraphs(lines)
            if not paragraphs:
                self.done.emit("", "", "")
                return
            src = "\n".join(paragraphs)
            if self.known and _norm(src) and _norm(self.known) in _norm(src):
                self.done.emit("", "", "")      # 拍到了自己（兜底）
                return
            pairs = translate.translate_paragraphs(
                paragraphs, self.target, self.base, timeout=20.0
            )
            pair = ""
            if pairs:
                import langs as _langs

                pair = f"{_langs.label(pairs[0]['src_lang'])} → {_langs.label(pairs[0]['tgt_lang'])}"
            self.done.emit(src, "\n".join(p["dst"] for p in pairs), pair)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class LiveSession(QObject):
    """管理一次实时翻译会话：轮询选区域 + 驱动浮窗。"""

    status = Signal(str)
    finished = Signal()
    opacity_changed = Signal(int)   # 浮窗里调透明度
    font_changed = Signal(int)      # 浮窗里调字号
    size_changed = Signal(int, int) # 浮窗被拖大/拖小

    def __init__(self, rect_physical, dpr, target, base, opacity, font_size,
                 panel_size: tuple[int, int] | None = None):
        super().__init__()
        self.rect = rect_physical
        self.target = target
        self.base = base
        self._dpr = dpr or 1.0
        self._opacity = opacity
        self._font_size = font_size
        self._panel_size = panel_size

        self._panel: LivePanel | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._prev_hash: int | None = None
        self._pending_hash: int | None = None
        self._idle_ticks = 0
        self._last_recognise = 0.0
        self._last_change = 0.0
        self._busy_since = 0.0
        self._paused = False
        self._last_src = ""
        self._last_dst = ""
        self._busy = False
        self._worker: RecogniseWorker | None = None

    # ---------- 生命周期 ----------
    def start(self) -> None:
        x, y, w, h = self.rect
        logical = (
            int(x / self._dpr), int(y / self._dpr),
            max(80, int(w / self._dpr)), max(50, int(h / self._dpr)),
        )
        self._panel = LivePanel(logical, self._opacity, self._font_size, size=self._panel_size)
        self._panel.closed.connect(self._on_panel_closed)
        self._panel.opacity_changed.connect(self._on_opacity)
        self._panel.font_changed.connect(self._on_font)
        self._panel.resized.connect(self.size_changed)
        self._panel.show()
        self._paused = False
        self._timer.start()
        self.status.emit("实时翻译已开启（300ms 轮询）· Alt+P 暂停 · Alt+W 退出")

    # ---------- 暂停 / 继续 ----------
    def is_paused(self) -> bool:
        return self._paused

    def pause(self, reason: str = "") -> None:
        """暂停轮询（画面与译文保持不动）。"""
        if self._paused:
            return
        self._paused = True
        self._timer.stop()
        hint = "已暂停"
        if reason:
            hint = f"已暂停（{reason}）"
        if self._panel is not None:
            self._panel.set_status(f"{hint} · Alt+P 继续 · Alt+W 退出")
        self.status.emit(f"实时翻译{hint}")

    def resume(self) -> None:
        """继续轮询。重置哈希，避免暂停期间的变化被当成"未变"。"""
        if not self._paused:
            return
        self._paused = False
        self._prev_hash = None
        self._pending_hash = None
        self._last_recognise = 0.0
        self._timer.start()
        if self._panel is not None:
            self._panel.set_status("监听中 · Alt+P 暂停 · Alt+W 退出")
        self.status.emit("实时翻译已继续")

    def toggle_pause(self) -> bool:
        if self._paused:
            self.resume()
        else:
            self.pause()
        return self._paused

    def stop(self) -> None:
        self._paused = False
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        if self._panel is not None:
            panel, self._panel = self._panel, None
            panel.blockSignals(True)
            panel.close()
        self.status.emit("实时翻译已停止")
        self.finished.emit()

    def _on_panel_closed(self) -> None:
        self.stop()

    def _on_opacity(self, value: int) -> None:
        self._opacity = value
        self.opacity_changed.emit(value)
        self.status.emit(f"遮罩透明度 {value}%")

    def _on_font(self, value: int) -> None:
        self._font_size = value
        self.font_changed.emit(value)
        self.status.emit(f"译文字号 {value}px")

    # ---------- 轮询 ----------
    def _tick(self) -> None:
        try:
            img = capture.grab_region(self.rect)
        except Exception as e:  # noqa: BLE001
            if self._panel is not None:
                self._panel.set_status(f"抓屏失败：{e}")
            return

        now = time.monotonic()

        # 卡死保护：识别线程异常长时间不返回（例如推理服务挂住）时强制解锁
        if self._busy and (now - self._busy_since) > BUSY_WATCHDOG:
            self._busy = False
            if self._panel is not None:
                self._panel.set_status("识别超时，已重试")

        h = dhash(img)
        changed = self._prev_hash is None or hamming(h, self._prev_hash) > HASH_TOLERANCE
        self._prev_hash = h

        if self._busy:
            return                      # 上一次识别还没结束，等它

        if changed:
            self._last_change = now
            # 画面在变（视频/字幕/滚动）：节流到最快 0.5s 一次，绝不"等画面稳定"
            if now - self._last_recognise >= MIN_INTERVAL:
                self._recognise(img)
            return

        # 画面稳定：每 1.2s 兜底识别一次（防哈希盲区漏句）
        if now - self._last_recognise >= IDLE_INTERVAL:
            self._recognise(img)

    def _recognise(self, img: Image.Image) -> None:
        if self._busy:
            return
        self._busy = True
        self._busy_since = time.monotonic()
        self._last_recognise = self._busy_since
        self._worker = RecogniseWorker(img, self.target, self.base, self._last_dst)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        self._busy = False

    def _on_done(self, src: str, dst: str, pair: str) -> None:
        if self._panel is None:
            return
        if not src or not dst:
            self._panel.set_status(
                f"未识别到文字 · {time.strftime('%H:%M:%S')}（Alt+W 退出）"
            )
            return
        if _norm(src) == _norm(self._last_src):
            return
        self._last_src = src
        self._last_dst = dst
        self._panel.set_pair(pair)
        self._panel.set_text(dst)
        self.status.emit(f"已更新译文 · {time.strftime('%H:%M:%S')}")

    def _on_failed(self, msg: str) -> None:
        if self._panel is not None:
            self._panel.set_status(f"失败：{msg.splitlines()[0] if msg else ''}")
