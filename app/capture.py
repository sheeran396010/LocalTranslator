# -*- coding: utf-8 -*-
"""屏幕抓取：全屏定格 + 按物理像素裁切。"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

try:  # mss 10.x 推荐 MSS，老版本只有 mss()
    from mss import MSS as _MSS
except ImportError:  # pragma: no cover
    from mss import mss as _MSS


@dataclass
class Shot:
    image: Image.Image          # 物理像素整屏
    left: int
    top: int
    width: int
    height: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


def grab_primary() -> Shot:
    """抓主显示器整屏（物理像素）。"""
    with _MSS() as sct:
        mon = sct.monitors[1]
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    return Shot(img, mon["left"], mon["top"], mon["width"], mon["height"])


def crop(shot: Shot, box: tuple[int, int, int, int]) -> Image.Image:
    """box 为相对整屏的物理像素 (x, y, w, h)。"""
    x, y, w, h = box
    x = max(0, min(int(x), shot.width - 1))
    y = max(0, min(int(y), shot.height - 1))
    w = max(1, min(int(w), shot.width - x))
    h = max(1, min(int(h), shot.height - y))
    return shot.image.crop((x, y, x + w, y + h))


def grab_region(rect: tuple[int, int, int, int]) -> Image.Image:
    """直接抓取屏幕上一块物理像素区域（实时监听用，约 5ms）。"""
    x, y, w, h = (int(v) for v in rect)
    w = max(1, w)
    h = max(1, h)
    with _MSS() as sct:
        raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
