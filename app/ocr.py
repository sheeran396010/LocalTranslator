# -*- coding: utf-8 -*-
"""OCR 层：RapidOCR 封装，返回带 bbox 的行。支持中/英/日/俄/西/法六语。

性能要点（实测，别随手改）：
  1. limit_type 必须是 "max"。默认的 "min" 会把短边不足 736 的窄裁剪放大到 736，
     一条 1124x40 的单行会被放大 18 倍，耗时从 244ms 涨到 1226ms。
  2. limit_side_len=960 是精度/速度平衡点：整屏大图缩到 960 仍能认全 10px 小字，
     降到 480 时 12px 正文直接全部丢失（实测 0/5）。
  3. use_cls=False：截图里的文字不会倒着，方向分类纯属浪费（约 450ms）。
  4. 送检前裁掉四周纯色边距，减少 det 输入面积（用户框得松时收益明显）。
  5. 语种：默认 v6/ch 已覆盖 中英日西法；俄语需 v5 cyrillic 模型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

import langs

DET_LIMIT_SIDE_LEN = 960
TRIM_TOL = 6
TRIM_MAX_FRAC = 0.35
TRIM_MIN_KEEP = 0.2
TRIM_MIN_PIXELS = 120_000  # 小于这个面积不值得裁边（裁边本身约 20ms）

_engines: dict[str, RapidOCR] = {}


def _build_engine(profile: tuple[str, str] | None) -> RapidOCR:
    params: dict = {
        "Global.use_cls": False,
        "Det.limit_type": "max",
        "Det.limit_side_len": DET_LIMIT_SIDE_LEN,
    }
    if profile is not None:
        version, lang = profile
        params["Rec.ocr_version"] = OCRVersion.PPOCRV5 if version == "v5" else OCRVersion.PPOCRV4
        params["Rec.lang_type"] = LangRec(lang)
        params["Rec.model_type"] = ModelType.MOBILE
    return RapidOCR(params=params)


def engine(lang: str = "zh") -> RapidOCR:
    """按语种取引擎（单例缓存）。中文/英文/日语/西语/法语共用默认引擎。"""
    key = lang if langs.OCR_PROFILE.get(lang) is not None else "default"
    eng = _engines.get(key)
    if eng is None:
        eng = _build_engine(langs.OCR_PROFILE.get(lang))
        _engines[key] = eng
    return eng


@dataclass
class Line:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _warm_image(w: int, h: int) -> Image.Image:
    """带文字的合成图（空白图 det 结果为空时 rec 模型不会被加载）。"""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    try:
        fnt = ImageFont.load_default(size=16)
    except TypeError:  # 老版本 Pillow
        fnt = ImageFont.load_default()
    y = 8
    while y < h - 20:
        draw.text((8, y), "Warmup sample text 0123456789 ABCDEF", font=fnt, fill=(0, 0, 0))
        y += 24
    return img


def warmup() -> None:
    """预热默认引擎 + 俄语引擎（各语种首次调用都要加载模型，约 0.5-1s）。"""
    for lang in ("zh", "ru"):
        for size in ((600, 200), (1120, 200)):
            try:
                recognize(_warm_image(*size), lang)
            except Exception:  # noqa: BLE001
                pass


def trim_uniform_border(img: Image.Image) -> Image.Image:
    """裁掉四周与角落同色的空白边。失败就原样返回。"""
    try:
        rgb = img.convert("RGB")
        arr = np.asarray(rgb).astype(np.int16)
        h, w, _ = arr.shape
        if h < 12 or w < 12 or h * w < TRIM_MIN_PIXELS:
            return img

        corner = np.median(
            np.stack([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]), axis=0
        )
        content = np.abs(arr - corner).max(axis=2) > TRIM_TOL

        rows = np.where(content.any(axis=1))[0]
        cols = np.where(content.any(axis=0))[0]
        if rows.size == 0 or cols.size == 0:
            return img

        top, bottom = int(rows[0]), int(rows[-1])
        left, right = int(cols[0]), int(cols[-1])

        if top > h * TRIM_MAX_FRAC or left > w * TRIM_MAX_FRAC:
            return img
        if (h - bottom) > h * TRIM_MAX_FRAC or (w - right) > w * TRIM_MAX_FRAC:
            return img

        pad = 4
        box = (
            max(0, left - pad),
            max(0, top - pad),
            min(w, right + 1 + pad),
            min(h, bottom + 1 + pad),
        )
        if (box[2] - box[0]) * (box[3] - box[1]) < h * w * TRIM_MIN_KEEP:
            return img
        return rgb.crop(box)
    except Exception:  # noqa: BLE001
        return img


def recognize(img: Image.Image, lang: str = "zh") -> list[Line]:
    img = trim_uniform_border(img)
    arr = np.asarray(img.convert("RGB"))[:, :, ::-1].copy()  # cv2 约定：BGR
    res = engine(lang)(arr)

    txts = getattr(res, "txts", None) or []
    scores = getattr(res, "scores", None) or []
    boxes = getattr(res, "boxes", None)

    lines: list[Line] = []
    for i, text in enumerate(txts):
        if boxes is None or i >= len(boxes):
            continue
        pts = np.asarray(boxes[i], dtype=float).reshape(-1, 2)
        x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
        x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
        score = float(scores[i]) if i < len(scores) else 0.0
        if text and text.strip():
            lines.append(Line(text.strip(), score, x0, y0, x1, y1))
    return lines


_last_auto_lang = "zh"


def _meaningful(lines: list[Line]) -> bool:
    text = "".join(l.text for l in lines)
    return len(re.sub(r"[\W_]+", "", text)) >= 4


def recognize_auto(img: Image.Image) -> tuple[list[Line], str]:
    """自动语种识别。

    先用"上次成功"的语种引擎（连续截同一语种时省一半时间），失败再试另一个；
    俄文用默认 v6/ch 引擎通常只吐出几个标点，据此触发 v5/cyrillic 回退。
    """
    global _last_auto_lang

    order = [_last_auto_lang, "ru" if _last_auto_lang != "ru" else "zh"]
    best: tuple[list[Line], str] | None = None
    for lang in order:
        lines = recognize(img, lang)
        if _meaningful(lines):
            _last_auto_lang = lang
            return lines, langs.detect("".join(l.text for l in lines))
        if best is None:
            best = (lines, lang)
    lines = best[0] if best else []
    return lines, langs.detect("".join(l.text for l in lines))
