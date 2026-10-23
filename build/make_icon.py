# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（蓝底圆角 + 白色「译」字）。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"E:\Sheeran\build\app.ico")
OUT.parent.mkdir(parents=True, exist_ok=True)

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角矩形（模拟圆角）
radius = 56
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=radius, fill=(47, 111, 219, 255))

# 中间的字
glyph = "译"
font = None
for path in (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
):
    try:
        font = ImageFont.truetype(path, 150)
        break
    except Exception:  # noqa: BLE001
        continue

if font is not None:
    bbox = d.textbbox((0, 0), glyph, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    d.text(
        ((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1]),
        glyph,
        font=font,
        fill=(255, 255, 255, 255),
    )

img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon ->", OUT, OUT.stat().st_size, "bytes")
