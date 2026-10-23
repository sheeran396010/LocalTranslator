# -*- coding: utf-8 -*-
"""小字精度对照：不同 limit_side_len 对 10/12 号灰字的影响。

逻辑：limit_type=max 只会"缩小"大图。整屏截图（2560 宽）在 960/480 下分别缩到 0.375x / 0.19x，
小字会糊掉。这里用真实的 10~12px 灰字来量化损失。
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr import RapidOCR

OUT = Path(r"E:\Ai\_downloads\ocr_small_text.txt")
PAGE = Path(r"E:\Ai\_downloads\ocr_small_page.png")
lines: list[str] = []

CJK = "C:/Windows/Fonts/msyh.ttc"


def font(size: int):
    try:
        return ImageFont.truetype(CJK, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


TEXTS_12 = [
    "这是十二号字体的正文，常见于网页与小字号界面说明。",
    "另一行十二号灰字，用于检验下采样后的可读性。",
    "第三行包含数字 2026 与英文 word 混排的情况。",
]
TEXTS_10 = [
    "十号脚注文字通常更淡更小，是 OCR 最容易丢失的部分。",
    "第二行脚注：版权信息与免责声明一般出现在这里。",
]


def build() -> Image.Image:
    img = Image.new("RGB", (1500, 520), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 20), "小字号精度测试", font=font(22), fill=(10, 10, 10))
    y = 70
    for t in TEXTS_12:
        d.text((30, y), t, font=font(12), fill=(90, 90, 90))
        y += 22
    y += 20
    for t in TEXTS_10:
        d.text((30, y), t, font=font(10), fill=(130, 130, 130))
        y += 20
    img.save(PAGE)
    return img


page = build()
arr = np.asarray(page.convert("RGB"))[:, :, ::-1].copy()
lines.append(f"测试图: {PAGE}  {page.width}x{page.height}（含 12px / 10px 灰字）")

CONFIGS = [
    ("不缩放 (max 99999)", {"Global.use_cls": False, "Det.limit_type": "max", "Det.limit_side_len": 99999}),
    ("max 960", {"Global.use_cls": False, "Det.limit_type": "max", "Det.limit_side_len": 960}),
    ("max 480", {"Global.use_cls": False, "Det.limit_type": "max", "Det.limit_side_len": 480}),
]

EXPECT = TEXTS_12 + TEXTS_10
for name, params in CONFIGS:
    eng = RapidOCR(params=params)
    eng(arr)
    ts = []
    res = None
    for _ in range(3):
        t = time.perf_counter()
        res = eng(arr)
        ts.append((time.perf_counter() - t) * 1000)
    txts = list(res.txts or [])
    join = "".join(txts).replace(" ", "")
    hit = sum(1 for e in EXPECT if e.replace(" ", "") in join)
    lines.append("")
    lines.append(f"### {name}   {min(ts):.0f} ms   识别 {len(txts)} 行 / 期望 5 行   命中 {hit}/5")
    for t in txts:
        lines.append(f"    {t}")
    missing = [e for e in EXPECT if e.replace(" ", "") not in join]
    if missing:
        lines.append(f"    缺失: {missing}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written:", OUT)
