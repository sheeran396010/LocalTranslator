# -*- coding: utf-8 -*-
"""OCR 提速方案 A/B 测试台。

测四档裁剪（1/3/6/12 行）× 多种配置，输出耗时矩阵 + 识别质量指纹（行数 + 文本 md5），
用于确认"提速没有牺牲精度"。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr import RapidOCR

OUT = Path(r"E:\Ai\_downloads\ocr_matrix.txt")
PAGE = Path(r"E:\Ai\_downloads\ocr_page.png")
lines: list[str] = []


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


CJK = "C:/Windows/Fonts/msyh.ttc"
EN = "C:/Windows/Fonts/segoeui.ttf"

BODY = [
    "人工智能的发展速度超出了大多数人的预期。",
    "十年前，机器翻译还只能给出勉强可读的结果，",
    "而今天，本地运行的小模型已经能在几百毫秒",
    "内完成长段落的精准翻译。这意味着隐私敏感的",
    "场景再也不需要把数据上传到云端处理。",
    "对于需要处理大量文档的用户来说，这种本地",
    "化的方案既节省成本，又避免了数据泄露风险。",
    "翻译质量的高低，最终取决于模型本身的训练",
    "数据规模与指令微调的质量，而不是参数量。",
    "一个调好的小模型，往往胜过没有针对任务优化",
    "的大模型，这也是端侧部署越来越受关注的原因。",
    "未来这类工具会像输入法一样成为系统的一部分。",
]
EN_BODY = [
    "All inference happens locally on the GPU.",
    "No screenshots ever leave this machine.",
    "Latency stays under one second for short clips.",
    "The model runs at roughly 90 tokens per second.",
]


def build_page() -> Image.Image:
    img = Image.new("RGB", (1180, 980), "white")
    d = ImageDraw.Draw(img)
    d.text((36, 24), "本地化翻译方案说明", font=font(CJK, 26), fill=(15, 15, 15))
    y = 80
    for t in BODY:
        d.text((36, y), t, font=font(CJK, 17), fill=(25, 25, 25))
        y += 30
    y += 20
    for t in EN_BODY:
        d.text((36, y), t, font=font(EN, 15), fill=(35, 35, 35))
        y += 26
    img.save(PAGE)
    return img


def crop_lines(img: Image.Image, n: int) -> Image.Image:
    # 正文从 y=80 开始，行高 30
    top = 80 - 6
    return img.crop((26, top, 1150, top + n * 30 + 10))


def md5(texts) -> str:
    return hashlib.md5("|".join(texts).encode("utf-8")).hexdigest()[:10]


CONFIGS = {
    "A baseline (min 736, cls off)": {"Global.use_cls": False},
    "B max 960 + cls off": {"Global.use_cls": False, "Det.limit_type": "max", "Det.limit_side_len": 960},
    "C max 480 + cls off": {"Global.use_cls": False, "Det.limit_type": "max", "Det.limit_side_len": 480},
}

page = build_page()
crops = {f"{n}行": np.asarray(crop_lines(page, n).convert("RGB"))[:, :, ::-1].copy() for n in (1, 3, 6, 12)}

lines.append(f"测试页: {PAGE}  裁剪尺寸: " + ", ".join(f"{k}={v.shape[1]}x{v.shape[0]}" for k, v in crops.items()))
lines.append("")

for name, params in CONFIGS.items():
    t0 = time.perf_counter()
    eng = RapidOCR(params=params)
    init_ms = (time.perf_counter() - t0) * 1000
    lines.append(f"### {name}   (init {init_ms:.0f} ms)")
    lines.append(f"    lock: limit_type={eng.cfg['Det']['limit_type']} limit_side_len={eng.cfg['Det']['limit_side_len']}")
    for tag, arr in crops.items():
        eng(arr)  # 预热
        ts = []
        res = None
        for _ in range(3):
            t = time.perf_counter()
            res = eng(arr)
            ts.append((time.perf_counter() - t) * 1000)
        n_lines = len(res.txts or [])
        lines.append(f"   {tag:5s} {min(ts):7.0f} ms  行数={n_lines:2d}  md5={md5(res.txts or [])}")
    lines.append("")

# ---------- 分项耗时（det / rec）----------
eng = RapidOCR(params={"Global.use_cls": False})
arr6 = crops["6行"]
arr1 = crops["1行"]

bgr6 = eng.load_img(arr6)
proc, op = eng.preprocess_img(bgr6)
t = time.perf_counter(); cropped, det_res = eng.detect_and_crop(proc, op); det_ms = (time.perf_counter() - t) * 1000
t = time.perf_counter(); eng.recognize_txt(cropped); rec_ms = (time.perf_counter() - t) * 1000
lines.append("### 分项耗时（6 行）")
lines.append(f"   det: {det_ms:6.0f} ms   ({len(cropped)} 个框)")
lines.append(f"   rec: {rec_ms:6.0f} ms")
lines.append(f"   det+rec = {det_ms + rec_ms:.0f} ms")

# 单行短路：跳过 det，直接 rec 整块
bgr1 = eng.load_img(arr1)
t = time.perf_counter(); out = eng.recognize_txt([bgr1]); rec_only_ms = (time.perf_counter() - t) * 1000
lines.append("")
lines.append("### 单行短路（跳过 det，直接 rec）")
lines.append(f"   耗时 {rec_only_ms:6.0f} ms   识别={out.txts}   conf={[round(float(s),3) for s in (out.scores or [])]}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written:", OUT)
