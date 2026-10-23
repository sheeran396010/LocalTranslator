# -*- coding: utf-8 -*-
"""版面层：把 OCR 的碎行合并成语义完整的段落。

为什么要做：专用翻译模型吃"整句/整段"质量最好，逐行喂会得到断裂的译文。
"""
from __future__ import annotations

import statistics

from ocr import Line

SENT_END = "。！？!?；;：:….、>）)】」』\"'"


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return 0x3000 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF


def _join(a: str, b: str) -> str:
    """中英混排时的空格规则。"""
    if not a:
        return b
    if not b:
        return a
    if _is_cjk(a[-1]) or _is_cjk(b[0]):
        return a + b
    return a + " " + b


def merge_paragraphs(lines: list[Line], gap_ratio: float = 0.75) -> list[str]:
    if not lines:
        return []

    lines = sorted(lines, key=lambda l: (round(l.y0), l.x0))
    heights = [l.height for l in lines if l.height > 1]
    med_h = statistics.median(heights) if heights else 16.0

    groups: list[list[Line]] = []
    cur: list[Line] = [lines[0]]
    for prev, nxt in zip(lines, lines[1:]):
        gap = nxt.y0 - prev.y1
        same_col = abs(nxt.x0 - prev.x0) < med_h * 1.8
        prev_ends = prev.text.rstrip()[-1:] in SENT_END if prev.text.strip() else True
        new_para = gap > med_h * gap_ratio or not same_col or prev_ends
        if new_para:
            groups.append(cur)
            cur = [nxt]
        else:
            cur.append(nxt)
    groups.append(cur)

    paragraphs: list[str] = []
    for g in groups:
        text = ""
        for line in g:
            text = _join(text, line.text)
        text = text.strip()
        if text:
            paragraphs.append(text)
    return paragraphs
