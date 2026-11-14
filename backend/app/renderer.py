"""Pillow renderer: DesignSpec + confirmed texts + ORIGINAL product photo -> 3 PNG 1080x1080 + thumbnails.

Rules (spec §09): product photo is never stretched or redrawn (ImageOps.contain), text is drawn after
compositing, wrapped and shrunk to fit; price/CTA are never silently cut — overflow is reported.
Everything is drawn at 2x then downsampled for smooth edges.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .schemas import BBox, DesignSpec, Variant

OUT = 1080
S = 2  # supersampling
W = OUT * S

_FONT_CANDIDATES = {
    True: ["NotoSans-Bold.ttf", "Roboto-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    False: ["NotoSans-Regular.ttf", "Roboto-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
}
_FONT_DIRS = [
    Path(__file__).resolve().parent.parent / "fonts",
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/truetype/dejavu"),
]


def find_font(bold: bool, override: str = "") -> str:
    if override and os.path.exists(override):
        return override
    for d in _FONT_DIRS:
        for name in _FONT_CANDIDATES[bold]:
            p = d / name
            if p.exists():
                return str(p)
    raise RuntimeError("Không tìm thấy font có dấu tiếng Việt; đặt FONT_BOLD/FONT_REGULAR trong .env")


@dataclass
class Texts:
    headline: str
    product_name: str
    price: str
    cta: str
    kicker: str = ""  # e.g. "Ngày này năm 1010 · Chiếu dời đô"


@dataclass
class RenderResult:
    paths: dict[str, str]
    thumbs: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    ra, rb = _rgb(a), _rgb(b)
    return tuple(int(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))  # type: ignore[return-value]


def _px(b: BBox) -> tuple[int, int, int, int]:
    return int(b.x * W), int(b.y * W), int(b.w * W), int(b.h * W)


def _on(color: str) -> str:
    """Readable text color on top of `color`."""
    r, g, b = _rgb(color)
    return "#111827" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


# ---------- text fitting ----------
def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        # a single word wider than the box: hard-split by characters
        while draw.textlength(word, font=font) > max_w and len(word) > 1:
            k = len(word)
            while k > 1 and draw.textlength(word[:k], font=font) > max_w:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_text(draw, text, box, font_path, max_size, min_size, max_lines=3, spacing=1.15):
    """Return (font, lines, line_h, fits). Shrinks until the text fits in box=(w,h)."""
    bw, bh = box
    size = max_size
    while True:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, bw)
        asc, desc = font.getmetrics()
        line_h = int((asc + desc) * spacing)
        widest_word = max((draw.textlength(w_, font=font) for w_ in text.split()), default=0)
        fits = len(lines) <= max_lines and line_h * len(lines) <= bh and widest_word <= bw
        if fits or size <= min_size:
            return font, lines, line_h, fits
        size = max(min_size, int(size * 0.92))


def _draw_block(draw, text, rect, font_path, color, max_size, min_size, align="left", valign="center",
                max_lines=3, warnings=None, label=""):
    x, y, w, h = rect
    if not text:
        return
    font, lines, line_h, fits = fit_text(draw, text, (w, h), font_path, max_size, min_size, max_lines)
    if not fits and warnings is not None:
        warnings.append(f"text_overflow:{label}")
    total = line_h * len(lines)
    ty = y if valign == "top" else y + max(0, (h - total) // 2)
    for line in lines:
        lw = draw.textlength(line, font=font)
        tx = x if align == "left" else (x + (w - lw) // 2 if align == "center" else x + w - lw)
        draw.text((tx, ty), line, font=font, fill=color)
        ty += line_h


# ---------- shapes ----------
def _shadow(canvas: Image.Image, rect, radius, blur=28, offset=14, alpha=60):
    x, y, w, h = rect
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x, y + offset, x + w, y + h + offset), radius, fill=(0, 0, 0, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _paste_product(canvas: Image.Image, product: Image.Image, rect, scale: float):
    x, y, w, h = rect
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    img = ImageOps.contain(product, (tw, th), Image.LANCZOS)  # keeps aspect ratio, never crops
    px, py = x + (w - img.width) // 2, y + (h - img.height) // 2
    canvas.alpha_composite(img, (px, py))
    return px, py, img.width, img.height


# ---------- variant renderers ----------
def _render_variant(spec: DesignSpec, v: Variant, texts: Texts, product: Image.Image, fonts, warnings) -> Image.Image:
    bold, regular = fonts
    canvas = Image.new("RGBA", (W, W), _rgb(v.bg) + (255,))
    draw = ImageDraw.Draw(canvas)
    a = spec.anchors

    # --- background decoration per treatment ---
    if v.treatment == "card":
        deco = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        dd = ImageDraw.Draw(deco)
        dd.ellipse((int(W * 0.62), int(-W * 0.18), int(W * 1.25), int(W * 0.45)), fill=_rgb(v.accent) + (38,))
        dd.ellipse((int(-W * 0.2), int(W * 0.78), int(W * 0.3), int(W * 1.25)), fill=_rgb(v.accent) + (28,))
        canvas.alpha_composite(deco)
    elif v.treatment == "badge":
        deco = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        dd = ImageDraw.Draw(deco)
        dd.polygon([(0, int(W * 0.86)), (W, int(W * 0.62)), (W, W), (0, W)], fill=_mix(v.bg, "#FFFFFF", 0.08) + (255,))
        dd.line([(0, int(W * 0.86)), (W, int(W * 0.62))], fill=_rgb(v.accent) + (255,), width=6 * S)
        canvas.alpha_composite(deco)
    draw = ImageDraw.Draw(canvas)

    # --- product (original photo) ---
    px, py, pw, ph = _px(a.product)
    name_h = int(ph * 0.14) if texts.product_name else 0
    if v.treatment in ("card", "badge"):
        radius = int(min(pw, ph) * 0.07)
        _shadow(canvas, (px, py, pw, ph), radius)
        card_fill = (255, 255, 255, 255) if v.treatment == "card" else _mix(v.bg, "#FFFFFF", 0.88) + (255,)
        ImageDraw.Draw(canvas).rounded_rectangle((px, py, px + pw, py + ph), radius, fill=card_fill)
        pad = int(min(pw, ph) * 0.06)
        _paste_product(canvas, product, (px + pad, py + pad, pw - 2 * pad, ph - 2 * pad - name_h), v.product_scale)
        name_color = "#1F2937"
    else:
        _paste_product(canvas, product, (px, py, pw, ph - name_h), v.product_scale)
        name_color = v.fg
    draw = ImageDraw.Draw(canvas)
    if texts.product_name:
        _draw_block(draw, texts.product_name, (px + int(pw * 0.06), py + ph - name_h - int(ph * 0.03),
                    int(pw * 0.88), name_h), regular, name_color, int(name_h * 0.62), 20 * S,
                    align="center", max_lines=1, warnings=warnings, label="product_name")

    # --- headline (+ optional history kicker) ---
    hx, hy, hw, hh = _px(a.headline)
    if texts.kicker:
        kh = int(hh * 0.28)
        kfont, klines, _, _ = fit_text(draw, texts.kicker, (hw, kh), bold, int(kh * 0.7), 16 * S, max_lines=1)
        kw = int(draw.textlength(klines[0], font=kfont)) + int(kh * 0.9)
        chip_fill = v.accent
        draw.rounded_rectangle((hx, hy, hx + min(kw, hw), hy + kh), kh // 2, fill=chip_fill)
        draw.text((hx + int(kh * 0.45), hy + int(kh * 0.12)), klines[0], font=kfont, fill=_on(chip_fill))
        hy, hh = hy + kh + int(hh * 0.06), hh - kh - int(hh * 0.06)
    base = int(min(hh * 0.62, 92 * S) * v.headline_scale)
    _draw_block(draw, texts.headline, (hx, hy, hw, hh), bold, v.fg, base, 22 * S, max_lines=2,
                warnings=warnings, label="headline")
    if v.treatment == "plain":
        draw.rectangle((hx, hy + hh + int(6 * S), hx + int(hw * 0.18), hy + hh + int(10 * S)), fill=v.accent)

    # --- price ---
    if texts.price:
        rx, ry, rw, rh = _px(a.price)
        if v.treatment == "badge":
            d = min(rw, rh) if rw > rh * 1.6 else min(rw, int(rh * 1.15))
            cx, cy = rx + rw // 2, ry + rh // 2
            badge = Image.new("RGBA", (d, d), (0, 0, 0, 0))
            bd = ImageDraw.Draw(badge)
            bd.ellipse((0, 0, d - 1, d - 1), fill=_rgb(v.accent) + (255,))
            bd.ellipse((int(d * 0.06), int(d * 0.06), int(d * 0.94), int(d * 0.94)), outline=_on(v.accent), width=max(2, d // 90))
            inner = int(d * 0.68)
            _draw_block(bd, texts.price, ((d - inner) // 2, (d - inner) // 2, inner, inner), bold, _on(v.accent),
                        int(d * 0.24), 18 * S, align="center", max_lines=3, warnings=warnings, label="price")
            badge = badge.rotate(-8, resample=Image.BICUBIC, expand=True)
            canvas.alpha_composite(badge, (cx - badge.width // 2, cy - badge.height // 2))
            draw = ImageDraw.Draw(canvas)
        else:
            color = v.accent if v.treatment == "plain" else v.fg
            _draw_block(draw, texts.price, (rx, ry, rw, rh), bold, color, int(min(rh * 0.5, 110 * S)), 22 * S,
                        align="left", max_lines=2, warnings=warnings, label="price")
            if v.treatment == "card":
                draw.rounded_rectangle((rx, ry + rh - int(8 * S), rx + int(rw * 0.35), ry + rh - int(2 * S)),
                                       3 * S, fill=v.accent)

    # --- CTA ---
    cx, cy, cw, ch = _px(a.cta)
    btn_h = min(ch, int(96 * S))
    by = cy + (ch - btn_h) // 2
    r = btn_h // 2
    if v.treatment == "plain":
        draw.rounded_rectangle((cx, by, cx + cw, by + btn_h), r, outline=v.accent, width=4 * S, fill=None)
        txt_color = v.accent
    else:
        draw.rounded_rectangle((cx, by, cx + cw, by + btn_h), r, fill=v.accent)
        txt_color = _on(v.accent)
    cta = texts.cta.upper() if v.treatment == "badge" else texts.cta
    _draw_block(draw, cta, (cx + r // 2, by, cw - r, btn_h), bold, txt_color, int(btn_h * 0.42), 16 * S,
                align="center", max_lines=1, warnings=warnings, label="cta")

    return canvas.convert("RGB").resize((OUT, OUT), Image.LANCZOS)


def render(spec: DesignSpec, texts: Texts, product_path: str, out_dir: str | Path,
           font_bold: str = "", font_regular: str = "") -> RenderResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fonts = (find_font(True, font_bold), find_font(False, font_regular))
    with Image.open(product_path) as src:
        product = ImageOps.exif_transpose(src).convert("RGBA")
        product.thumbnail((W, W))
    result = RenderResult(paths={}, thumbs={})
    for v in spec.variants:
        img = _render_variant(spec, v, texts, product, fonts, result.warnings)
        p = out / f"{v.id}.png"
        img.save(p, "PNG", optimize=True)
        t = out / f"{v.id}_thumb.jpg"
        img.resize((360, 360), Image.LANCZOS).save(t, "JPEG", quality=85)
        result.paths[v.id], result.thumbs[v.id] = str(p), str(t)
    return result
