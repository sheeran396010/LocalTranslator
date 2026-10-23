# -*- coding: utf-8 -*-
"""Fluent 界面层：截图翻译 / 实时监听 / 文本翻译 + 设置持久化。

依赖 qfluentwidgets（PySide6-Fluent-Widgets，GPLv3）。
本模块只在 GUI 运行时导入，--selftest 不会加载它。
"""
from __future__ import annotations

import time
import traceback

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    Slider,
    StrongBodyLabel,
    SwitchButton,
    TextBrowser,
    Theme,
    setTheme,
    setThemeColor,
)

import capture
import langs
import layout
import live
import ocr
import paths
import server
import settings as settings_mod
import translate
from overlay import Overlay

PORT = paths.DEFAULT_PORT
BASE_URL = f"http://127.0.0.1:{PORT}"

PILL_STYLE = {
    "wait": "background:#332a10;color:#e3c06a;border-radius:9px;padding:3px 10px;font-size:12px;",
    "ok": "background:#12351f;color:#6ccb5f;border-radius:9px;padding:3px 10px;font-size:12px;",
    "err": "background:#3b1c1f;color:#ff99a4;border-radius:9px;padding:3px 10px;font-size:12px;",
}


# ---------------------------------------------------------------- 后台线程
class Pipeline(QThread):
    """单次截图翻译。"""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, image, target, base):
        super().__init__()
        self.image = image
        self.target = target
        self.base = base

    def run(self) -> None:  # noqa: D401
        try:
            t0 = time.perf_counter()
            lines, src_lang = ocr.recognize_auto(self.image)
            t1 = time.perf_counter()
            paragraphs = layout.merge_paragraphs(lines)
            pairs = translate.translate_paragraphs(paragraphs, self.target, self.base)
            t2 = time.perf_counter()
            self.done.emit(
                {
                    "lines": len(lines),
                    "paragraphs": paragraphs,
                    "pairs": pairs,
                    "src_lang": src_lang,
                    "ocr_ms": (t1 - t0) * 1000,
                    "tr_ms": (t2 - t1) * 1000,
                }
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}")


class TextTranslate(QThread):
    done = Signal(str, str, str)
    failed = Signal(str)

    def __init__(self, text, target, base):
        super().__init__()
        self.text = text
        self.target = target
        self.base = base

    def run(self) -> None:  # noqa: D401
        try:
            paragraphs = [p for p in self.text.splitlines() if p.strip()]
            pairs = translate.translate_paragraphs(paragraphs, self.target, self.base)
            dst = "\n".join(p["dst"] for p in pairs)
            pair = (
                f"{langs.label(pairs[0]['src_lang'])} → {langs.label(pairs[0]['tgt_lang'])}"
                if pairs else ""
            )
            self.done.emit(self.text, dst, pair)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class Startup(QThread):
    done = Signal(bool, str)

    def __init__(self, handle):
        super().__init__()
        self.handle = handle

    def run(self) -> None:  # noqa: D401
        try:
            ok, msg = server.ensure(BASE_URL, PORT, handle=self.handle)
        except Exception as e:  # noqa: BLE001
            ok, msg = False, str(e)
        self.done.emit(ok, msg)


# ---------------------------------------------------------------- 页面
class CapturePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("capturePage")
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 18, 26, 16)
        v.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(BodyLabel("目标语言"))
        self.combo = ComboBox()
        self.combo.setMinimumWidth(150)
        row.addWidget(self.combo)
        row.addStretch(1)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.btn_capture = PrimaryPushButton(FIF.CAMERA, "框选翻译    Alt+Q")
        self.btn_capture.setMinimumHeight(40)
        row2.addWidget(self.btn_capture, 2)
        self.btn_live = PushButton(FIF.SYNC, "实时翻译    Alt+R")
        self.btn_live.setMinimumHeight(40)
        row2.addWidget(self.btn_live, 2)
        self.pill = QLabel("● 启动中")
        self.pill.setStyleSheet(PILL_STYLE["wait"])
        row2.addWidget(self.pill, 0, Qt.AlignVCenter)
        v.addLayout(row2)

        self.hint = CaptionLabel(
            "框选翻译：结果直接显示在下方 · 实时翻译：框选后弹出独立浮窗，内容变化自动翻译"
            "（Alt+P 暂停/继续，Alt+W 退出；实时中按 Alt+Q 会先暂停、翻译完自动继续）"
        )
        v.addWidget(self.hint)

        self.split = QSplitter(Qt.Horizontal)
        self.listw = ListWidget()
        self.listw.setMinimumWidth(260)
        self.detail = TextBrowser()
        self.split.addWidget(self.listw)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([290, 660])
        v.addWidget(self.split, 1)

        row3 = QHBoxLayout()
        self.footer = CaptionLabel("等待框选…")
        row3.addWidget(self.footer, 1)
        self.btn_copy = PushButton(FIF.COPY, "复制译文")
        row3.addWidget(self.btn_copy)
        v.addLayout(row3)


class TextPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("textPage")
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 18, 26, 16)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("目标语言"))
        self.combo = ComboBox()
        self.combo.setMinimumWidth(150)
        row.addWidget(self.combo)
        row.addStretch(1)
        v.addLayout(row)

        v.addWidget(CaptionLabel("输入 / 粘贴文本（Ctrl+Enter 翻译）"))
        self.txt_in = PlainTextEdit()
        self.txt_in.setPlaceholderText("把要翻译的文字粘到这里…")
        self.txt_in.setMinimumHeight(130)
        v.addWidget(self.txt_in, 1)

        row2 = QHBoxLayout()
        self.btn_translate = PrimaryPushButton(FIF.LANGUAGE, "翻译    Ctrl+Enter")
        row2.addWidget(self.btn_translate)
        self.btn_clear = PushButton(FIF.BROOM, "清空")
        row2.addWidget(self.btn_clear)
        row2.addStretch(1)
        self.btn_copy = PushButton(FIF.COPY, "复制译文")
        row2.addWidget(self.btn_copy)
        v.addLayout(row2)

        v.addWidget(CaptionLabel("译文"))
        self.txt_out = PlainTextEdit()
        self.txt_out.setReadOnly(True)
        self.txt_out.setMinimumHeight(130)
        v.addWidget(self.txt_out, 1)

        self.footer = CaptionLabel("Ctrl+Enter 翻译")
        v.addWidget(self.footer)


# ---------------------------------------------------------------- 主窗口
class MainWindow(FluentWindow):
    hotkey_capture = Signal()
    hotkey_live = Signal()
    hotkey_stop_live = Signal()
    hotkey_pause = Signal()

    def __init__(self, cfg: settings_mod.Settings):
        setTheme(Theme.DARK)
        setThemeColor("#2f6fdb")
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle(f"{paths.APP_NAME} {paths.APP_VERSION}")
        self.resize(1000, 700)
        self.setMinimumSize(860, 600)

        self._shot = None
        self._overlay: Overlay | None = None
        self._pipe: Pipeline | None = None
        self._text_job: TextTranslate | None = None
        self._startup: Startup | None = None
        self._live: live.LiveSession | None = None
        self._server = server.ServerHandle()
        self._history: list[dict] = []
        self._dpr = 1.0
        self._ready = False
        self._syncing = False
        self._mode = "single"      # "single" | "live"
        self._paused_for_single = False   # 因单次框选而暂停了实时翻译

        self.capture_page = CapturePage(self)
        self.text_page = TextPage(self)
        self.addSubInterface(self.capture_page, FIF.CAMERA, "截图翻译")
        self.addSubInterface(self.text_page, FIF.EDIT, "文本翻译")
        nav = getattr(self, "navigationInterface", None)
        if nav is not None:
            for meth, arg in (("setExpandWidth", 180), ("setMinimumExpandWidth", 900)):
                try:
                    getattr(nav, meth)(arg)
                except Exception:  # noqa: BLE001
                    pass

        self._fill_combos()
        self._bind_controls()
        self._restore_state()

        self.hotkey_capture.connect(self.start_capture, Qt.QueuedConnection)
        self.hotkey_live.connect(self.start_live_capture, Qt.QueuedConnection)
        self.hotkey_stop_live.connect(self.stop_live, Qt.QueuedConnection)
        self.hotkey_pause.connect(self.toggle_live_pause, Qt.QueuedConnection)
        QTimer.singleShot(200, self._register_hotkeys)
        QTimer.singleShot(260, self._start_service)
        QTimer.singleShot(800, self._warmup_ocr)

        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self._save_geometry)

    # ---------- 初始化 ----------
    def _fill_combos(self) -> None:
        for combo in (self.capture_page.combo, self.text_page.combo):
            combo.addItem("自动判断", userData="auto")
            for code, name in langs.LANGS:
                combo.addItem(name, userData=code)

    def _bind_controls(self) -> None:
        cp, tp = self.capture_page, self.text_page
        cp.combo.currentIndexChanged.connect(lambda _i: self._on_combo(cp.combo))
        tp.combo.currentIndexChanged.connect(lambda _i: self._on_combo(tp.combo))
        cp.btn_capture.clicked.connect(self.start_capture)
        cp.btn_live.clicked.connect(self.start_live_capture)
        cp.btn_copy.clicked.connect(self._copy_current)
        cp.listw.currentRowChanged.connect(self._show_row)
        tp.btn_translate.clicked.connect(self._translate_text)
        tp.btn_clear.clicked.connect(self._clear_text)
        tp.btn_copy.clicked.connect(self._copy_text_result)
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+Return"), self, self._translate_text)

    def _restore_state(self) -> None:
        cfg = self.cfg
        self._syncing = True
        target = cfg.get("target")
        for combo in (self.capture_page.combo, self.text_page.combo):
            idx = self._index_of(combo, target)
            combo.setCurrentIndex(idx)
        self._syncing = False

        geo = cfg.get("window")
        if geo:
            try:
                x, y, w, h = geo
                screen = QGuiApplication.primaryScreen().availableGeometry()
                if (x + 200 > screen.left() and x < screen.right()
                        and y + 100 > screen.top() and y < screen.bottom()):
                    self.setGeometry(x, y, max(860, w), max(600, h))
            except Exception:  # noqa: BLE001
                pass
        if cfg.get("page") == 1:
            self.switchTo(self.text_page)

    @staticmethod
    def _index_of(combo: ComboBox, code: str) -> int:
        for i in range(combo.count()):
            if combo.itemData(i) == code:
                return i
        return 0

    # ---------- 设置联动 ----------
    def _on_combo(self, combo: ComboBox) -> None:
        if self._syncing:
            return
        code = combo.itemData(combo.currentIndex()) or "auto"
        self._syncing = True
        for c in (self.capture_page.combo, self.text_page.combo):
            if c is not combo:
                c.setCurrentIndex(self._index_of(c, code))
        self._syncing = False
        self.cfg.set("target", code)

    def _on_mask_opacity(self, value: int) -> None:
        """浮窗里调透明度 -> 记到设置里，下次实时翻译沿用。"""
        self.cfg.set("opacity", int(value))

    def _on_live_font(self, value: int) -> None:
        self.cfg.set("font_size", int(value))

    def _on_live_size(self, w: int, h: int) -> None:
        self.cfg.set("live_size", [int(w), int(h)])

    def _current_target(self) -> str | None:
        code = self.cfg.get("target")
        return None if code == "auto" else code

    # ---------- 启动任务 ----------
    def _register_hotkeys(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey("alt+q", lambda: self.hotkey_capture.emit())
            keyboard.add_hotkey("alt+r", lambda: self.hotkey_live.emit())
            keyboard.add_hotkey("alt+p", lambda: self.hotkey_pause.emit())
            keyboard.add_hotkey("alt+w", lambda: self.hotkey_stop_live.emit())
        except Exception:  # noqa: BLE001
            pass

    def _start_service(self) -> None:
        self._startup = Startup(self._server)
        self._startup.done.connect(self._on_service)
        self._startup.start()

    def _on_service(self, ok: bool, msg: str) -> None:
        self._ready = ok
        pill = self.capture_page.pill
        if ok:
            pill.setText("● 服务就绪")
            pill.setStyleSheet(PILL_STYLE["ok"])
            self.capture_page.footer.setText(f"本地推理已就绪 · {msg}")
        else:
            pill.setText("● 服务异常")
            pill.setStyleSheet(PILL_STYLE["err"])
            self.capture_page.footer.setText(f"推理服务不可用：{msg}")
            self._toast("推理服务不可用", msg, error=True)

    def _warmup_ocr(self) -> None:
        import threading

        def run():
            try:
                ocr.warmup()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=run, daemon=True).start()

    # ---------- 提示 ----------
    def _toast(self, title: str, content: str = "", error: bool = False) -> None:
        try:
            fn = InfoBar.error if error else InfoBar.success
            fn(title=title, content=content, parent=self,
               position=InfoBarPosition.TOP_RIGHT, duration=1800)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 截图 / 实时 ----------
    def start_capture(self) -> None:
        self._begin_selection("single")

    def start_live_capture(self) -> None:
        self._begin_selection("live")

    def _begin_selection(self, mode: str) -> None:
        if self._pipe is not None and self._pipe.isRunning():
            return

        if mode == "live":
            if self._live is not None:      # Alt+R 在实时中 = 关闭实时
                self.stop_live()
                return
        elif self._live is not None:
            # 单次框选：暂停实时，做完自动继续
            self._paused_for_single = True
            self._live.pause("正在框选翻译…")

        self._mode = mode
        self.capture_page.footer.setText(
            "框选要实时翻译的区域…" if mode == "live" else "框选要翻译的区域…"
        )
        self.hide()
        QTimer.singleShot(180, self._do_capture)

    def _do_capture(self) -> None:
        try:
            self._shot = capture.grab_primary()
        except Exception as e:  # noqa: BLE001
            self.show()
            self.capture_page.footer.setText(f"抓屏失败：{e}")
            return
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        self._dpr = dpr or 1.0
        self._overlay = Overlay(self._shot, self._dpr)
        self._overlay.selected.connect(self._on_selected)
        self._overlay.canceled.connect(self._on_canceled)
        self._overlay.show()

    def _on_canceled(self) -> None:
        self._overlay = None
        self.show()
        self.capture_page.footer.setText("已取消框选")
        self._maybe_resume_live()

    def _on_selected(self, box) -> None:
        self._overlay = None
        if self._mode == "live":
            self._start_live(box)
            return
        img = capture.crop(self._shot, box)
        self.show()
        self.raise_()
        self.capture_page.footer.setText(f"识别中… 区域 {box[2]}×{box[3]}")
        self.capture_page.btn_capture.setEnabled(False)
        self._pipe = Pipeline(img, self._current_target(), BASE_URL)
        self._pipe.done.connect(self._on_done)
        self._pipe.failed.connect(self._on_failed)
        self._pipe.start()

    def _start_live(self, box) -> None:
        self.hide()
        opacity = int(self.cfg.get("opacity") or 60)
        font_size = int(self.cfg.get("font_size") or 17)
        size = self.cfg.get("live_size")
        panel_size = tuple(size) if isinstance(size, list) and len(size) == 2 else None
        self._live = live.LiveSession(
            box, self._dpr, self._current_target(), BASE_URL, opacity, font_size, panel_size
        )
        self._live.status.connect(lambda m: self.capture_page.footer.setText(m))
        self._live.finished.connect(self._on_live_finished)
        # 浮窗里的透明度/字号改动写回设置
        self._live.opacity_changed.connect(self._on_mask_opacity)
        self._live.font_changed.connect(self._on_live_font)
        self._live.size_changed.connect(self._on_live_size)
        self._live.start()

    def toggle_live_pause(self) -> None:
        """Alt+P：暂停 / 继续实时翻译。"""
        if self._live is None:
            self.capture_page.footer.setText("当前没有进行中的实时翻译")
            return
        paused = self._live.toggle_pause()
        self.capture_page.footer.setText(
            "实时翻译已暂停（Alt+P 继续）" if paused else "实时翻译已继续"
        )

    def _maybe_resume_live(self) -> None:
        if self._paused_for_single and self._live is not None:
            self._paused_for_single = False
            self._live.resume()

    def stop_live(self) -> None:
        if self._live is None:
            self.capture_page.footer.setText("当前没有进行中的实时监听")
            return
        self._paused_for_single = False
        session, self._live = self._live, None
        session.stop()

    def _on_live_finished(self) -> None:
        self.show()
        self.raise_()
        self.capture_page.footer.setText("实时监听已结束")

    # ---------- 单次结果 ----------
    def _on_done(self, r: dict) -> None:
        cp = self.capture_page
        cp.btn_capture.setEnabled(True)
        total = r["ocr_ms"] + r["tr_ms"]
        src_name = langs.label(r["src_lang"])
        cp.footer.setText(
            f"识别为{src_name} · OCR {r['ocr_ms']:.0f} ms · 翻译 {r['tr_ms']:.0f} ms · 合计 {total:.0f} ms"
        )
        item = {
            "time": time.strftime("%H:%M:%S"),
            "pairs": r["pairs"],
            "ocr_ms": r["ocr_ms"],
            "tr_ms": r["tr_ms"],
            "lines": r["lines"],
            "src_lang": r["src_lang"],
        }
        self._history.insert(0, item)
        tgt_name = langs.label(r["pairs"][0]["tgt_lang"]) if r["pairs"] else "—"
        from PySide6.QtWidgets import QListWidgetItem

        cp.listw.insertItem(
            0, QListWidgetItem(f"{item['time']}   {src_name} → {tgt_name} · {total:.0f} ms")
        )
        cp.listw.setCurrentRow(0)
        self._maybe_resume_live()

    def _on_failed(self, msg: str) -> None:
        self.capture_page.btn_capture.setEnabled(True)
        first = msg.splitlines()[0] if msg else "未知错误"
        self.capture_page.footer.setText(f"失败：{first}")
        self.capture_page.detail.setHtml(
            "<p style='color:#ff99a4'><b>出错了</b></p>"
            f"<pre style='color:#b9bec7;white-space:pre-wrap'>{msg}</pre>"
        )
        self._toast("翻译失败", first, error=True)
        self._maybe_resume_live()

    def _show_row(self, row: int) -> None:
        if not (0 <= row < len(self._history)):
            return
        it = self._history[row]
        parts = []
        for i, p in enumerate(it["pairs"], 1):
            parts.append(
                f"<p style='color:#8a8f98;margin:0 0 2px 0'>"
                f"{i}. 原文 · {langs.label(p['src_lang'])}</p>"
                f"<p style='color:#d0d4da;margin:0 0 8px 0'>{_esc(p['src'])}</p>"
                f"<p style='color:#8a8f98;margin:0 0 2px 0'>译文 · {langs.label(p['tgt_lang'])}</p>"
                f"<p style='color:#f0f3f7;margin:0 0 14px 0'>{_esc(p['dst'])}</p>"
            )
        head = (
            f"<p style='color:#8a8f98;font-size:12px'>{it['time']} · "
            f"{it['lines']} 行 → {len(it['pairs'])} 段 · OCR {it['ocr_ms']:.0f} ms · "
            f"翻译 {it['tr_ms']:.0f} ms</p>"
        )
        self.capture_page.detail.setHtml(head + "".join(parts))

    def _copy_current(self) -> None:
        row = self.capture_page.listw.currentRow()
        if not (0 <= row < len(self._history)):
            self.capture_page.footer.setText("还没有可复制的译文")
            return
        QApplication.clipboard().setText(
            "\n\n".join(p["dst"] for p in self._history[row]["pairs"])
        )
        self.capture_page.footer.setText("已复制到剪贴板")
        self._toast("已复制", "译文已复制到剪贴板")

    # ---------- 文本翻译 ----------
    def _translate_text(self) -> None:
        tp = self.text_page
        text = tp.txt_in.toPlainText().strip()
        if not text:
            tp.footer.setText("请输入要翻译的文本")
            return
        if self._text_job is not None and self._text_job.isRunning():
            return
        tp.btn_translate.setEnabled(False)
        tp.txt_out.setPlainText("翻译中…")
        self._text_job = TextTranslate(text, self._current_target(), BASE_URL)
        self._text_job.done.connect(self._on_text_done)
        self._text_job.failed.connect(self._on_text_failed)
        self._text_job.start()

    def _on_text_done(self, src: str, dst: str, pair: str) -> None:
        tp = self.text_page
        tp.btn_translate.setEnabled(True)
        tp.txt_out.setPlainText(dst)
        tp.footer.setText(f"文本翻译完成 · {pair}")

    def _on_text_failed(self, msg: str) -> None:
        tp = self.text_page
        tp.btn_translate.setEnabled(True)
        tp.txt_out.setPlainText(f"翻译失败：{msg}")
        tp.footer.setText("文本翻译失败")
        self._toast("翻译失败", msg.splitlines()[0] if msg else "", error=True)

    def _clear_text(self) -> None:
        self.text_page.txt_in.clear()
        self.text_page.txt_out.clear()
        self.text_page.footer.setText("已清空")

    def _copy_text_result(self) -> None:
        text = self.text_page.txt_out.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.text_page.footer.setText("已复制到剪贴板")
        self._toast("已复制", "译文已复制到剪贴板")

    # ---------- 状态持久化 ----------
    def _save_geometry(self) -> None:
        g = self.geometry()
        self.cfg.set("window", [g.x(), g.y(), g.width(), g.height()], save=True)

    def moveEvent(self, ev) -> None:  # noqa: N802
        super().moveEvent(ev)
        timer = getattr(self, "_geo_timer", None)
        if timer is not None:
            timer.start()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        timer = getattr(self, "_geo_timer", None)
        if timer is not None:
            timer.start()

    def _save_page(self) -> None:
        try:
            current = self.stackedWidget.currentWidget()
            self.cfg.set("page", 1 if current is self.text_page else 0)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, ev) -> None:  # noqa: N802
        try:
            import keyboard

            keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._server.stop()
        self._save_geometry()
        self._save_page()
        self.cfg.save()
        super().closeEvent(ev)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def run_gui() -> int:
    import sys

    from PySide6.QtWidgets import QApplication as _QApp

    app = _QApp(sys.argv)
    app.setApplicationName("LocalTranslator")
    cfg = settings_mod.Settings()
    win = MainWindow(cfg)
    # 记住页面切换
    try:
        win.stackedWidget.currentChanged.connect(lambda _i: win._save_page())
    except Exception:  # noqa: BLE001
        pass
    win.show()
    return app.exec()
