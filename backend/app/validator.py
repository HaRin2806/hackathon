"""Business + geometry rules that turn a (possibly sloppy) AIDesign into a renderable DesignSpec.

Never crashes on bad geometry: clamps, resolves overlaps, fills missing variants, fixes contrast.
Every repair is recorded in spec.repairs so the team can see what the model got wrong.
"""
from __future__ import annotations

from .schemas import AIDesign, Anchors, BBox, Brief, DesignSpec, Variant

SAFE = 0.04
MIN_W, MIN_H = 0.10, 0.06

DEFAULT_ANCHORS = {
    "headline": BBox(x=0.06, y=0.05, w=0.88, h=0.16),
    "product": BBox(x=0.06, y=0.26, w=0.50, h=0.58),
    "price": BBox(x=0.60, y=0.32, w=0.34, h=0.22),
    "cta": BBox(x=0.60, y=0.66, w=0.34, h=0.12),
}

PRESETS = {
    "A": Variant(id="A", style="faithful", bg="#FFF5E8", fg="#15324F", accent="#087F8C",
                 headline_scale=1.0, product_scale=1.0, treatment="card"),
    "B": Variant(id="B", style="minimal", bg="#FFFFFF", fg="#1F2937", accent="#287B70",
                 headline_scale=0.9, product_scale=0.9, treatment="plain"),
    "C": Variant(id="C", style="promotion", bg="#15324F", fg="#FFFFFF", accent="#EAAE48",
                 headline_scale=1.15, product_scale=0.95, treatment="badge"),
}
STYLE_OF = {"A": ("faithful", "card"), "B": ("minimal", "plain"), "C": ("promotion", "badge")}


# ---------- geometry ----------
def _clamp(b: BBox) -> BBox:
    x = min(max(b.x, SAFE), 1 - SAFE - MIN_W)
    y = min(max(b.y, SAFE), 1 - SAFE - MIN_H)
    w = min(max(b.w, MIN_W), 1 - SAFE - x)
    h = min(max(b.h, MIN_H), 1 - SAFE - y)
    return BBox(x=round(x, 4), y=round(y, 4), w=round(w, 4), h=round(h, 4))


def _inter(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy


def _carve(box: BBox, obstacle: BBox, gap: float = 0.015) -> BBox | None:
    """Largest piece of `box` that does not touch `obstacle` (left/right/top/bottom remainder)."""
    pieces = [
        BBox(x=box.x, y=box.y, w=obstacle.x - gap - box.x, h=box.h),  # left
        BBox(x=obstacle.x + obstacle.w + gap, y=box.y, w=box.x + box.w - (obstacle.x + obstacle.w + gap), h=box.h),
        BBox(x=box.x, y=box.y, w=box.w, h=obstacle.y - gap - box.y),  # top
        BBox(x=box.x, y=obstacle.y + obstacle.h + gap, w=box.w, h=box.y + box.h - (obstacle.y + obstacle.h + gap)),
    ]
    ok = [p for p in pieces if p.w >= MIN_W and p.h >= MIN_H]
    return max(ok, key=lambda p: p.w * p.h) if ok else None


def _free_slot(obstacles: list[BBox], want: BBox) -> BBox:
    """Find a free region of roughly `want` size by scanning the canvas."""
    w, h = max(want.w, 0.22), max(want.h, 0.08)
    best, best_d = None, 9.0
    steps = 24
    for i in range(steps + 1):
        for j in range(steps + 1):
            x = SAFE + (1 - 2 * SAFE - w) * i / steps
            y = SAFE + (1 - 2 * SAFE - h) * j / steps
            cand = BBox(x=x, y=y, w=w, h=h)
            if all(_inter(cand, o) == 0 for o in obstacles):
                d = (x - want.x) ** 2 + (y - want.y) ** 2
                if d < best_d:
                    best, best_d = cand, d
    return best or want


def _normalize_frame(anchors: Anchors, repairs: list[str]) -> Anchors:
    """If the model measured against the whole photo/paper, the 4 boxes only cover part of the canvas.
    Stretch their union to the safe area (keeps relative positions, i.e. the user's intent)."""
    boxes = {k: getattr(anchors, k) for k in ("headline", "product", "price", "cta")}
    x0 = min(b.x for b in boxes.values()); y0 = min(b.y for b in boxes.values())
    x1 = max(b.x + b.w for b in boxes.values()); y1 = max(b.y + b.h for b in boxes.values())
    uw, uh = x1 - x0, y1 - y0
    if uw <= 0 or uh <= 0 or (uw >= 0.82 and uh >= 0.82):
        return anchors
    lo, span = 0.05, 0.90
    sx = span / uw if uw < 0.82 else 1.0
    sy = span / uh if uh < 0.82 else 1.0
    ox = lo - x0 * sx if uw < 0.82 else 0.0
    oy = lo - y0 * sy if uh < 0.82 else 0.0
    repairs.append("bố cục: giãn theo khung banner (AI đo theo cả tờ giấy)")
    return Anchors(**{k: BBox(x=b.x * sx + ox, y=b.y * sy + oy, w=b.w * sx, h=b.h * sy) for k, b in boxes.items()})


def _resolve(anchors: Anchors, repairs: list[str]) -> Anchors:
    anchors = _normalize_frame(anchors, repairs)
    a = {k: _clamp(getattr(anchors, k)) for k in ("headline", "product", "price", "cta")}
    # Headline vs product: the photo is contain-scaled, so shrink the PRODUCT box rather than squeezing text.
    if _inter(a["headline"], a["product"]) > 0:
        shrunk = _carve(a["product"], a["headline"])
        if shrunk and shrunk.w >= 0.25 and shrunk.h >= 0.25:
            a["product"] = shrunk
            repairs.append("product: thu nhỏ để không đè lên tiêu đề")
    placed: list[tuple[str, BBox]] = [("product", a["product"])]
    for name in ("headline", "price", "cta"):  # priority order
        box = a[name]
        for other_name, other in placed:
            if _inter(box, other) > 0:
                carved = _carve(box, other)
                if carved and all(_inter(carved, o) == 0 for _, o in placed):
                    box = carved
                else:
                    box = _free_slot([o for _, o in placed], box)
                repairs.append(f"{name}: dời khỏi vùng {other_name} để không chồng lấn")
                break
        a[name] = box
        placed.append((name, box))
    return Anchors(**a)


# ---------- color ----------
def _lum(hex_: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _fix_variant(v: Variant, repairs: list[str]) -> Variant:
    style, treatment = STYLE_OF[v.id]
    data = v.model_dump()
    data.update(style=style, treatment=treatment)
    if contrast(v.fg, v.bg) < 4.5:
        data["fg"] = "#111827" if contrast("#111827", v.bg) >= contrast("#FFFFFF", v.bg) else "#FFFFFF"
        repairs.append(f"{v.id}: đổi màu chữ để đủ tương phản")
    return Variant(**data)


# ---------- main ----------
def build_spec(ai: AIDesign, brief: Brief) -> DesignSpec:
    repairs: list[str] = []
    anchors = _resolve(ai.anchors, repairs)

    by_id = {v.id: v for v in ai.variants}
    variants = []
    for vid in ("A", "B", "C"):
        if vid not in by_id:
            repairs.append(f"{vid}: AI không trả phương án này, dùng preset")
            variants.append(PRESETS[vid])
        else:
            variants.append(_fix_variant(by_id[vid], repairs))

    # "Đa phương án": every pair must differ in palette, not just file name.
    for i in range(3):
        for j in range(i + 1, 3):
            if variants[i].bg == variants[j].bg and variants[i].accent == variants[j].accent:
                variants[j] = PRESETS[variants[j].id]
                repairs.append(f"{variants[j].id}: trùng bảng màu với {variants[i].id}, dùng preset")

    if brief.headline:
        headline_source = "user"
    elif ai.headline_suggestion.strip():
        headline_source = "ai_suggestion"
    else:
        headline_source = "product_name"

    return DesignSpec(
        needs_clarification=ai.needs_clarification,
        layout_source="suggested" if ai.needs_clarification else "sketch",
        layout_reading=ai.layout_reading,
        headline_source=headline_source,
        anchors=anchors,
        variants=variants,
        repairs=repairs,
    )


def headline_text(spec: DesignSpec, brief: Brief, suggestion: str) -> str:
    if spec.headline_source == "user":
        return brief.headline
    if spec.headline_source == "ai_suggestion":
        return suggestion.strip()
    return brief.product_name
