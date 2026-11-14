"""Generate test inputs: two hand-drawn-looking sketches (product LEFT / RIGHT) and a product photo.

Used for spec test T02 (Sketch A/B) and the smoke test. Replace with real photos for the demo.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "samples"
FONT = next((p for p in ["C:/Windows/Fonts/NotoSans-Regular.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if Path(p).exists()), None)


def wobbly_rect(d: ImageDraw.ImageDraw, box, rnd: random.Random, width=5):
    x0, y0, x1, y1 = box
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        j = lambda: rnd.uniform(-6, 6)  # noqa: E731
        d.line([(ax + j(), ay + j()), ((ax + bx) / 2 + j(), (ay + by) / 2 + j()), (bx + j(), by + j())],
               fill=(40, 40, 60), width=width, joint="curve")


def sketch(product_left: bool, name: str):
    rnd = random.Random(7 if product_left else 11)
    img = Image.new("RGB", (900, 1200), (246, 241, 228))  # paper, portrait photo of a square drawing
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 46) if FONT else None
    ox, oy, s = 60, 180, 780  # the square drawing area on the paper
    wobbly_rect(d, (ox, oy, ox + s, oy + s), rnd, 4)

    def box(x, y, w, h, label):
        b = (ox + x * s, oy + y * s, ox + (x + w) * s, oy + (y + h) * s)
        wobbly_rect(d, b, rnd)
        d.text((b[0] + 18, b[1] + 14), label, fill=(30, 30, 90), font=font)

    box(0.06, 0.05, 0.88, 0.15, "TIÊU ĐỀ")
    if product_left:
        box(0.06, 0.27, 0.48, 0.58, "SP (ly trà)")
        box(0.60, 0.30, 0.34, 0.22, "GIÁ")
        box(0.60, 0.66, 0.34, 0.12, "CTA")
    else:
        box(0.46, 0.27, 0.48, 0.58, "SP (ly trà)")
        box(0.06, 0.30, 0.34, 0.22, "GIÁ")
        box(0.06, 0.66, 0.34, 0.12, "CTA")
    img = img.rotate(rnd.uniform(-2, 2), fillcolor=(230, 225, 210)).filter(ImageFilter.GaussianBlur(0.6))
    img.save(OUT / name, quality=90)


def product():
    img = Image.new("RGB", (900, 1100), (232, 226, 218))
    d = ImageDraw.Draw(img)
    d.ellipse((150, 930, 750, 1030), fill=(205, 198, 188))  # shadow
    d.polygon([(250, 260), (650, 260), (600, 980), (300, 980)], fill=(196, 140, 92))  # cup body (milk tea)
    d.polygon([(258, 300), (642, 300), (628, 420), (272, 420)], fill=(236, 214, 190))  # foam
    for i in range(18):  # tapioca pearls
        x, y = 320 + (i % 6) * 45, 860 + (i // 6) * 35
        d.ellipse((x, y, x + 34, y + 34), fill=(50, 32, 25))
    d.rectangle((230, 230, 670, 270), fill=(250, 250, 250))  # lid rim
    d.rectangle((430, 60, 470, 260), fill=(220, 60, 70))  # straw
    d.rounded_rectangle((340, 560, 560, 680), 20, fill=(255, 250, 240))
    if FONT:
        d.text((365, 590), "TRÀ SỮA", fill=(120, 70, 40), font=ImageFont.truetype(FONT, 40))
    img.save(OUT / "product_tra_sua.jpg", quality=92)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    sketch(True, "sketch_product_left.jpg")
    sketch(False, "sketch_product_right.jpg")
    product()
    print("samples ->", OUT)
