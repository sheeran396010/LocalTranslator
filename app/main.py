# -*- coding: utf-8 -*-
"""本地截图翻译 · 入口

    LocalTranslator.exe              -> 启动 Fluent 界面
    LocalTranslator.exe --selftest   -> 无界面全链路自检

界面实现在 ui_main.py（只在 GUI 模式导入，自检不加载 Qt/Fluent 依赖）。
"""
from __future__ import annotations

import sys
import time

import langs
import layout
import ocr
import paths
import server
import translate

PORT = paths.DEFAULT_PORT
BASE_URL = f"http://127.0.0.1:{PORT}"


def run_selftest() -> int:
    """验证 打包/模型/服务/OCR/翻译 全链路（含多语种）。"""
    import os
    import tempfile

    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                sys.stderr = sys.stdout
        except Exception:  # noqa: BLE001
            pass

    report: list[str] = []

    def say(msg: str = "") -> None:
        report.append(msg)
        try:
            print(msg)
        except Exception:  # noqa: BLE001
            pass

    say("=== 环境 ===")
    for line in paths.describe().splitlines():
        say("  " + line)

    ok, msg = server.ensure(BASE_URL, PORT, handle=server.ServerHandle())
    say(f"=== 服务 === {ok} {msg}")
    if not ok:
        say("FAIL: 推理服务不可用")
        _write_report(report)
        return 1

    say("=== OCR 预热 ===")
    t = time.perf_counter()
    ocr.warmup()
    say(f"  {((time.perf_counter() - t) * 1000):.0f} ms")

    from PIL import Image, ImageDraw, ImageFont

    def font(size: int):
        for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
        return ImageFont.load_default()

    samples = [
        ("中文", "人工智能正在改变世界，本地推理让隐私更安全。"),
        ("英文", "All inference runs on this machine."),
        ("西班牙语", "La inferencia local protege tu privacidad."),
        ("俄语", "Локальный вывод защищает вашу конфиденциальность."),
    ]

    failures = 0
    for i, (tag, text) in enumerate(samples):
        img = Image.new("RGB", (860, 70), "white")
        d = ImageDraw.Draw(img)
        d.text((20, 18), text, font=font(20), fill="black")
        img.save(os.path.join(tempfile.gettempdir(), f"lt_selftest_{i}.png"))

        t0 = time.perf_counter()
        lines, src_lang = ocr.recognize_auto(img)
        t1 = time.perf_counter()
        paras = layout.merge_paragraphs(lines)
        pairs = translate.translate_paragraphs(paras, None, BASE_URL)
        t2 = time.perf_counter()

        say("")
        say(f"--- 样本: {tag} ---")
        say(f"  OCR : {len(lines)} 行 / 判为 {langs.label(src_lang)} / {(t1 - t0) * 1000:.0f} ms")
        for l in lines:
            say(f"        conf={l.score:.3f} {l.text}")
        say(f"  翻译: {(t2 - t1) * 1000:.0f} ms")
        for p in pairs:
            say(f"        {langs.label(p['src_lang'])} -> {langs.label(p['tgt_lang'])}: {p['dst']}")
        if not pairs or not all(p["dst"].strip() for p in pairs):
            failures += 1

    say("")
    say(f"结果: {'PASS' if failures == 0 else 'FAIL'}（{len(samples) - failures}/{len(samples)} 个样本正常）")
    _write_report(report)
    return 0 if failures == 0 else 2


def _write_report(report: list[str]) -> None:
    try:
        out = paths.app_dir() / "selftest_report.txt"
        out.write_text("\n".join(report), encoding="utf-8")
        try:
            print(f"report -> {out}")
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    if "--selftest" in sys.argv:
        return run_selftest()
    import ui_main

    return ui_main.run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
