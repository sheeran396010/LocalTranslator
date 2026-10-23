# -*- coding: utf-8 -*-
"""支持的六个语种：名称映射、脚本检测、OCR 模型配置。

实测结论（详见 HANDOVER）：
  - PP-OCRv6/ch 模型本身能覆盖 中/英/日/西/法（含 á、¿、L'、très 这类字符）
  - 俄语必须切到 PP-OCRv5 + cyrillic
"""
from __future__ import annotations

import re

LANGS: list[tuple[str, str]] = [
    ("zh", "中文"),
    ("en", "英文"),
    ("ja", "日语"),
    ("ru", "俄语"),
    ("es", "西班牙语"),
    ("fr", "法语"),
]

NAME = dict(LANGS)                 # code -> 中文名
CODE = {name: code for code, name in LANGS}

# OCR 模型配置：None = 默认 PP-OCRv6/ch；("v5", "cyrillic") = 切 v5 西里尔模型
OCR_PROFILE: dict[str, tuple[str, str] | None] = {
    "zh": None,
    "en": None,
    "ja": None,
    "es": None,
    "fr": None,
    "ru": ("v5", "cyrillic"),
}

_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_CYR = re.compile(r"[\u0400-\u04ff]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_ES_MARK = re.compile(r"[ñ¿¡áíóú]")
_FR_MARK = re.compile(r"[àâçèêëîïôûùœ]", re.IGNORECASE)

_STOP = {
    # 刻意剔除歧义词（如 "no" 西语/英语通用、"de" 法西通用），只留判别力强的
    "es": set("el la los las un una del que y es para con por muy su sus al como más pero está son este esta".split()),
    "fr": set("le la les un une des du et est sont pour avec très dans que qui ce cette votre notre nous vous sur cet".split()),
    "en": set("the a an is are and of to in that it for with on at by from this these those you your was were".split()),
}
# 平票时的优先级：拉丁语系里英文更常见，避免把英文误判成西/法
_PRIORITY = ("en", "es", "fr")


def detect(text: str) -> str:
    """按脚本特征猜语种，返回 code。拉丁字母之间靠符号+停用词区分。"""
    if not text or not text.strip():
        return "zh"

    kana = len(_KANA.findall(text))
    cyr = len(_CYR.findall(text))
    han = len(_HAN.findall(text))
    lat = len(_LATIN.findall(text))
    total = kana + cyr + han + lat or 1

    if kana >= 2 and kana / total >= 0.05:
        return "ja"
    if cyr >= 3 and cyr / total >= 0.3:
        return "ru"
    if han >= 3 and han / total >= 0.3:
        return "zh"

    # 拉丁字母：先看特有符号，再看停用词
    if _ES_MARK.search(text):
        return "es"
    if _FR_MARK.search(text):
        return "fr"
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    scores = {k: sum(1 for w in words if w in _STOP[k]) for k in _STOP}
    best = max(scores.values())
    if best <= 0:
        return "en"
    for code in _PRIORITY:          # 平票按优先级取
        if scores[code] == best:
            return code
    return "en"


def choose_target(src_lang: str) -> str:
    """自动模式下的目标语：中文→英文，其它→中文。"""
    return "en" if src_lang == "zh" else "zh"


def normalize_target(value: str | None) -> str | None:
    """接受 code 或中文名，统一成 code。"""
    if not value:
        return None
    if value in NAME:
        return value
    return CODE.get(value)


def label(code: str) -> str:
    return NAME.get(code, code)
