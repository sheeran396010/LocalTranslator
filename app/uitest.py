# -*- coding: utf-8 -*-
"""UI 自动化验证（Fluent + 独立实时浮窗）。

覆盖：单次框选翻译 → 文本翻译 → 实时翻译浮窗（字号/透明度/设置落盘）

    E:\\Ai\\venv312\\Scripts\\python.exe E:\\Sheeran\\app\\uitest.py
"""
from __future__ import annotations

import os

# 测试用 offscreen 平台：窗口不显示在桌面上，逻辑照常运行（避免打扰用户）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import capture
import live as live_mod
import settings as settings_mod

OUT = r"E:\Ai\_downloads\uitest_log.txt"
WINDOW_PNG = r"E:\Ai\_downloads\uitest_window.png"
PANEL_PNG = r"E:\Ai\_downloads\uitest_panel.png"
SETTINGS_PNG = r"E:\Ai\_downloads\uitest_settings_popup.png"
SHOT_PNG = r"E:\Ai\_downloads\uitest_shot.png"
CFG_PATH = Path(r"E:\Ai\_downloads\uitest_settings.json")
log: list[str] = []


def rec(msg: str) -> None:
    log.append(msg)
    try:
        Path(OUT).write_text("\n".join(log), encoding="utf-8")
    except Exception:
        pass


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def build_fake_shot() -> capture.Shot:
    img = Image.new("RGB", (1000, 420), (250, 249, 246))
    d = ImageDraw.Draw(img)
    d.text((30, 22), "本地截图翻译 · 界面验证", font=_font("C:/Windows/Fonts/msyh.ttc", 25), fill=(20, 20, 20))
    d.text((30, 82), "这台机器上的翻译模型完全在本地运行，", font=_font("C:/Windows/Fonts/msyh.ttc", 17), fill=(30, 30, 30))
    d.text((30, 110), "截图内容不会被上传到任何服务器。", font=_font("C:/Windows/Fonts/msyh.ttc", 17), fill=(30, 30, 30))
    d.text((30, 172), "All inference happens on the local GPU.", font=_font("C:/Windows/Fonts/segoeui.ttf", 16), fill=(40, 40, 40))
    img.save(SHOT_PNG)
    return capture.Shot(img, 0, 0, img.width, img.height)


FRAME_1 = Image.new("RGB", (700, 120), "white")
_d = ImageDraw.Draw(FRAME_1)
_d.text((20, 40), "第一帧：本地推理保护隐私。", font=_font("C:/Windows/Fonts/msyh.ttc", 20), fill="black")
FRAME_2 = Image.new("RGB", (700, 120), "white")
_d2 = ImageDraw.Draw(FRAME_2)
_d2.text((20, 40), "第二帧：页面内容已经变化。", font=_font("C:/Windows/Fonts/msyh.ttc", 20), fill="black")
grab_n = {"n": 0}


def fake_grab_region(_rect):
    grab_n["n"] += 1
    return (FRAME_1 if grab_n["n"] <= 4 else FRAME_2).copy()


def main() -> int:
    fake = build_fake_shot()
    capture.grab_primary = lambda: fake
    capture.grab_region = fake_grab_region

    import ui_main

    CFG_PATH.unlink(missing_ok=True)
    app = QApplication(sys.argv)
    cfg = settings_mod.Settings(CFG_PATH)
    win = ui_main.MainWindow(cfg)
    win.show()
    cp, tp = win.capture_page, win.text_page
    rec("主窗口已显示（FluentWindow，两个按钮 + 状态徽标）")
    rec(f"按钮: capture='{cp.btn_capture.text()}'  live='{cp.btn_live.text()}'")
    rec(f"状态徽标: '{cp.pill.text()}'")

    waited = {"n": 0}
    state: dict = {}
    box = {"left": 18, "top": 60, "right": 640, "bottom": 200}

    # ---------- 1) 等服务 ----------
    def step_service():
        waited["n"] += 1
        if win._ready:
            rec(f"服务就绪（{waited['n'] * 0.4:.1f}s）")
            QTimer.singleShot(200, step_capture)
            return
        if waited["n"] > 150:
            rec("FAIL: 服务未就绪")
            done(2)
            return
        QTimer.singleShot(400, step_service)

    # ---------- 2) 单次框选 ----------
    def step_capture():
        cp.btn_capture.click()
        QTimer.singleShot(700, step_drag_single)

    def step_drag_single():
        ov = win._overlay
        if ov is None:
            QTimer.singleShot(120, step_drag_single)
            return
        drag(ov, box)
        rec("单次模式：已拖拽框选")
        QTimer.singleShot(400, step_wait_result)

    def step_wait_result():
        txt = cp.detail.toPlainText()
        if "出错了" in txt:
            rec("FAIL: 单次翻译报错\n" + txt[:300])
            done()
            return
        if cp.listw.count() == 0:
            QTimer.singleShot(300, step_wait_result)
            return
        rec(f"历史条目: {cp.listw.count()}  首条: {cp.listw.item(0).text()}")
        rec(f"状态: {cp.footer.text()}")
        for line in txt.splitlines():
            if line.strip():
                rec("   详情| " + line)
        win.grab().save(WINDOW_PNG)
        QTimer.singleShot(200, step_text_tab)

    # ---------- 3) 文本翻译 ----------
    def step_text_tab():
        tp.txt_in.setPlainText("本地推理让隐私更安全。")
        win._translate_text()
        QTimer.singleShot(2500, step_check_text)

    def step_check_text():
        out = tp.txt_out.toPlainText().strip()
        rec(f"文本翻译: {out}")
        rec(f"文本翻译判定: {'OK' if out and '翻译中' not in out and '失败' not in out else 'FAIL'}")
        QTimer.singleShot(200, step_live_start)

    # ---------- 4) 实时翻译 ----------
    def step_live_start():
        grab_n["n"] = 0
        state["prev_overlay"] = win._overlay
        cp.btn_live.click()
        QTimer.singleShot(700, step_drag_live)

    def step_drag_live():
        ov = win._overlay
        if ov is None or ov is state.get("prev_overlay"):
            QTimer.singleShot(120, step_drag_live)
            return
        drag(ov, box)
        rec("实时模式：已拖拽框选")
        QTimer.singleShot(1200, step_wait_panel)

    def step_wait_panel():
        tries = state.get("panel_tries", 0) + 1
        state["panel_tries"] = tries
        session = win._live
        panel = getattr(session, "_panel", None) if session else None
        if panel is None:
            rec("FAIL: 实时浮窗未创建")
            done(2)
            return
        text = panel.body.toPlainText().strip()
        if not text:
            if tries >= 18:            # 最多等 ~14 秒，绝不无限重试
                rec("FAIL: 等不到译文")
                rec(f"  诊断: grab次数={grab_n['n']} busy={getattr(session, '_busy', '?')} "
                    f"面板状态='{panel.status.text()}'")
                rec(f"  会话状态: last_src={getattr(session, '_last_src', '')!r}")
                rec(f"  服务在线: {ui_main.translate.health('http://127.0.0.1:8080', timeout=2)}")
                done(2)
                return
            QTimer.singleShot(800, step_wait_panel)
            return
        rec(f"实时浮窗: {panel.width()}x{panel.height()} @({panel.x()},{panel.y()})")
        rec(f"浮窗译文: {text}")
        rec(f"浮窗初始: 字号={panel._font_size} 透明度={panel._opacity}")
        panel.grab().save(PANEL_PNG)
        rec(f"浮窗截图: {PANEL_PNG}")
        # 打开齿轮设置弹层，调字号 + 透明度
        panel.toggle_settings()
        rec(f"设置弹层可见: {panel.settings_visible()}")
        popup = panel._popup
        if popup is not None:
            popup.grab().save(SETTINGS_PNG)
            rec(f"弹层截图: {SETTINGS_PNG} ({popup.width()}x{popup.height()})")
            popup._bump_font(4)          # 17 -> 21
            popup.slider.setValue(85)
            rec(f"弹层调整后: 字号={popup.lbl_font.text()} 透明度={popup.lbl_opacity.text()}")
        rec(f"上一段保留: {panel.previous_text()!r} 可见={panel.prev.isVisible()}")
        panel.resize(760, 420)          # 拖大
        QTimer.singleShot(900, step_check_live_settings)

    def step_check_live_settings():
        panel = win._live._panel
        rec(f"调整后(面板): 字号={panel._font_size} 透明度={panel._opacity}")
        rec(f"调整后(尺寸): {panel.width()}x{panel.height()}")
        try:
            data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            rec("设置文件: " + json.dumps(data, ensure_ascii=False))
            rec(
                f"判定 font={data.get('font_size')} opacity={data.get('opacity')} "
                f"target={data.get('target')} window={isinstance(data.get('window'), list)} "
                f"live_size={data.get('live_size')}"
            )
        except Exception as e:  # noqa: BLE001
            rec(f"设置读取失败: {e}")
        QTimer.singleShot(200, step_pause_hotkey)

    # ---------- Alt+P 暂停 / 继续 ----------
    def step_pause_hotkey():
        session = win._live
        win.toggle_live_pause()                      # 等价 Alt+P
        paused = session.is_paused()
        status_paused = session._panel.status.text()
        grabs = grab_n["n"]
        rec(f"Alt+P 暂停: paused={paused} 状态='{status_paused}'")
        QTimer.singleShot(1200, lambda: step_check_paused(session, grabs))

    def step_check_paused(session, grabs_before):
        frozen = grab_n["n"] == grabs_before
        rec(f"暂停 1.2s 内抓屏增量={grab_n['n'] - grabs_before}（0=确实停住了）")
        win.toggle_live_pause()                      # 继续
        rec(f"Alt+P 继续: paused={session.is_paused()} 状态='{session._panel.status.text()}'")
        QTimer.singleShot(1500, lambda: step_check_resumed(session, grabs_before, frozen))

    def step_check_resumed(session, grabs_before, frozen):
        moved = grab_n["n"] > grabs_before
        rec(f"继续后抓屏是否恢复={moved}")
        rec(f"Alt+P 判定: {'OK' if (frozen and not session.is_paused()) else 'FAIL'}")
        QTimer.singleShot(200, step_single_during_live)

    # ---------- 实时中按 Alt+Q 做单次框选 ----------
    def step_single_during_live():
        state["hist_before"] = cp.listw.count()
        state["live_session"] = win._live
        state["prev_overlay3"] = win._overlay
        rec(f"实时中触发 Alt+Q（历史当前 {state['hist_before']} 条）")
        win.start_capture()
        QTimer.singleShot(700, step_drag_during_live)

    def step_drag_during_live():
        ov = win._overlay
        if ov is None or ov is state.get("prev_overlay3"):
            QTimer.singleShot(120, step_drag_during_live)
            return
        session = state.get("live_session")
        rec(f"框选覆盖层已出现 · 实时是否暂停={session.is_paused() if session else None}")
        drag(ov, box)
        QTimer.singleShot(400, lambda: step_wait_single_done(session, 0))

    def step_wait_single_done(session, tries):
        if cp.listw.count() <= state.get("hist_before", 0):
            if tries >= 40:
                rec("FAIL: 实时中的单次翻译没有完成")
                done(2)
                return
            QTimer.singleShot(300, lambda: step_wait_single_done(session, tries + 1))
            return
        rec(f"单次完成 · 历史={cp.listw.count()} 条")
        rec(f"单次完成后实时是否已自动继续={not session.is_paused() if session else None}")
        rec(f"浮窗状态='{session._panel.status.text()}'" if session and session._panel else "浮窗已关闭")
        rec(f"实时中 Alt+Q 判定: {'OK' if (session and not session.is_paused()) else 'FAIL'}")
        if session and session._panel:
            session._panel.close()
        QTimer.singleShot(600, step_after_close)

    def step_after_close():
        rec(f"关闭浮窗后主窗口可见: {win.isVisible()}")
        done()

    def drag(ov, b):
        p1 = QPoint(b["left"], b["top"])
        p2 = QPoint(min(b["right"], ov.width() - 2), min(b["bottom"], ov.height() - 2))
        QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, p1)
        QTest.mouseMove(ov, p2)
        QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, p2)

    def done(code: int = 0) -> None:
        try:
            if win._live is not None:
                win._live.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            win.close()
        except Exception:  # noqa: BLE001
            pass
        open(OUT, "w", encoding="utf-8").write("\n".join(log))
        print("DONE code=%s -> %s" % (code, OUT), flush=True)
        QTimer.singleShot(0, lambda: app.exit(code))

    def watchdog():
        rec("FAIL: 测试超时（看门狗触发）")
        done(3)

    QTimer.singleShot(300, step_service)
    QTimer.singleShot(90000, watchdog)     # 硬超时，绝不无限等待
    rc = app.exec()

    text = "\n".join(log)
    ok = (
        "文本翻译判定: OK" in text
        and "浮窗译文:" in text
        and "font=" in text
        and "关闭浮窗后主窗口可见: True" in text
    )
    return 0 if ok and rc in (0, None) else 2


if __name__ == "__main__":
    raise SystemExit(main())
