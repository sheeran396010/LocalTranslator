# -*- coding: utf-8 -*-
"""实时翻译逻辑测试（覆盖"画面连续变化"的真实场景）。

场景 A：静态画面 → 变化一次   （基本功能）
场景 B：画面每帧都在变（视频/字幕）—— 之前正是在这里卡死：
       旧逻辑要求"画面稳定一拍"才识别，连续变化时永远不会识别。

    E:\\Ai\\venv312\\Scripts\\python.exe E:\\Sheeran\\app\\livetest.py
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import live
import translate

OUT = r"E:\Ai\_downloads\livetest_log.txt"
log: list[str] = []


def rec(msg: str) -> None:
    log.append(msg)
    try:
        open(OUT, "w", encoding="utf-8").write("\n".join(log))
    except Exception:  # noqa: BLE001
        pass


def _font(size: int = 20):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def frame(text: str) -> Image.Image:
    img = Image.new("RGB", (700, 120), "white")
    ImageDraw.Draw(img).text((20, 40), text, font=_font(), fill="black")
    return img


FRAMES = [
    frame("第 1 句：本地推理保护隐私。"),
    frame("第 2 句：画面一直在变化。"),
    frame("第 3 句：字幕每帧都不同。"),
    frame("第 4 句：现在应当继续更新。"),
    frame("第 5 句：仍然要在变化中识别。"),
]

state = {"n": 0, "mode": "A"}


def fake_grab(_rect):
    state["n"] += 1
    if state["mode"] == "A":
        return (FRAMES[0] if state["n"] <= 4 else FRAMES[1]).copy()
    return FRAMES[state["n"] % len(FRAMES)].copy()


def fake_translate(paragraphs, target=None, base="", timeout=180.0):
    return [{"src": p, "dst": f"[译文] {p}", "src_lang": "zh", "tgt_lang": "en"} for p in paragraphs]


def main() -> int:
    live.capture.grab_region = fake_grab
    translate.translate_paragraphs = fake_translate

    app = QApplication(sys.argv)
    session = live.LiveSession((0, 0, 700, 120), 1.0, None, "http://127.0.0.1:8080", 60, 17)
    session.start()

    seen: list[str] = []
    result = {"ok_a": False}

    def snapshot() -> str:
        p = session._panel
        return p.body.toPlainText().strip() if p else ""

    def poll():
        t = snapshot()
        if t and (not seen or seen[-1] != t):
            seen.append(t)

    def phase_a():
        text = snapshot()
        rec(f"[A] 抓屏={state['n']} 译文={text!r}")
        result["ok_a"] = text.startswith("[译文]")
        rec(f"[A] 判定: {'OK' if result['ok_a'] else 'FAIL'}")
        # 进入场景 B：画面每帧都在变
        state["mode"] = "B"
        state["n"] = 0
        seen.clear()
        QTimer.singleShot(5000, phase_b)

    def phase_b():
        text = snapshot()
        distinct = len(set(seen))
        rec(f"[B] 抓屏={state['n']} 最新译文={text!r} 采样到不同译文={distinct}")
        rec(f"[B] 最近采样={seen[-3:]}")
        ok_b = distinct >= 2
        rec(f"[B] 判定: {'OK（连续变化下仍在更新）' if ok_b else 'FAIL（连续变化下停止更新）'}")

        # [C] 上一段是否保留显示
        panel = session._panel
        prev = panel.previous_text()
        rec(f"[C] 上一段保留: {prev!r}  可见={panel.prev.isVisible()}")
        ok_c = bool(prev) and panel.prev.isVisible()
        rec(f"[C] 判定: {'OK' if ok_c else 'FAIL'}")

        # [D] 自由缩放 + 最小尺寸
        panel.resize(780, 430)
        app.processEvents()
        big = (panel.width(), panel.height())
        panel.resize(200, 100)
        app.processEvents()
        small = (panel.width(), panel.height())
        rec(f"[D] 放大后={big} 缩到最小后={small} 最小要求=({live.PANEL_MIN_W},{live.PANEL_MIN_H})")
        ok_d = big[0] >= 760 and small == (live.PANEL_MIN_W, live.PANEL_MIN_H)
        rec(f"[D] 判定: {'OK' if ok_d else 'FAIL'}")

        session.stop()
        rec(f"总判定: {'OK' if (result['ok_a'] and ok_b and ok_c and ok_d) else 'FAIL'}")
        app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(200)
    QTimer.singleShot(3500, phase_a)
    QTimer.singleShot(20000, app.quit)
    app.exec()

    text = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
    return 0 if "总判定: OK" in text else 1


if __name__ == "__main__":
    raise SystemExit(main())
