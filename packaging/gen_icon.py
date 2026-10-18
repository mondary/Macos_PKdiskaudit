#!/usr/bin/env python3
"""Génère l'icône de PKDiskAudit (PNG 1024 + .icns)."""

import os
import subprocess

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICONS = os.path.join(HERE, "icons")
SIZE = 1024


def build():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fond arrondi
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=228, fill=(16, 16, 18, 255))
    draw.rounded_rectangle([26, 26, SIZE - 27, SIZE - 27], radius=204,
                           outline=(35, 35, 39, 255), width=3)

    # Jauge (anneau)
    box = [262, 220, 762, 720]
    draw.arc(box, start=0, end=360, fill=(35, 35, 39, 255), width=76)
    value_end = -90 + 360 * 0.955
    draw.arc(box, start=-90, end=value_end, fill=(217, 139, 139, 255), width=76)

    # Mini-treemap à l'intérieur
    left = (372, 330, 520, 610)
    right_top = (536, 330, 652, 462)
    right_bottom = (536, 478, 652, 610)
    draw.rounded_rectangle(left, radius=18, fill=(51, 59, 70, 255))
    draw.rounded_rectangle(right_top, radius=18, fill=(61, 56, 47, 255))
    draw.rounded_rectangle(right_bottom, radius=18, fill=(58, 47, 54, 255))

    # Barres type classement
    bars = [
        ((262, 790, 762, 826), (74, 79, 88, 255)),
        ((262, 850, 640, 886), (61, 56, 47, 255)),
        ((262, 910, 544, 946), (63, 74, 69, 255)),
    ]
    for rect, color in bars:
        draw.rounded_rectangle(rect, radius=18, fill=color)

    os.makedirs(ICONS, exist_ok=True)
    png = os.path.join(ICONS, "icon.png")
    img.save(png)
    img.save(os.path.join(ROOT, "icon.png"))

    # iconset pour iconutil
    iconset = os.path.join(ICONS, "icon.iconset")
    os.makedirs(iconset, exist_ok=True)
    sizes = [
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ]
    for size, name in sizes:
        img.resize((size, size), Image.LANCZOS).save(os.path.join(iconset, name))

    icns = os.path.join(ICONS, "icon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    print("OK", png, icns)


if __name__ == "__main__":
    build()
