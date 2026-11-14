"""Vietnam history events (curated seed + optional extract of minhxthanh/Vietnam-History-1M-Vi)."""
from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


@lru_cache
def load_events(path: str) -> tuple[dict, ...]:
    p = Path(path)
    if not p.exists():
        return ()
    events = json.loads(p.read_text(encoding="utf-8"))
    for e in events:
        e["_fold"] = _fold(f"{e['event']} {e['year']} {e.get('summary', '')}")
    # verified/curated first, then chronological
    events.sort(key=lambda e: (not e.get("verified", False), e["year"]))
    return tuple(events)


def public(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def search(path: str, q: str = "", month_day: str = "", limit: int = 20) -> list[dict]:
    events = load_events(path)
    out = []
    terms = _fold(q).split()
    for e in events:
        if not e.get("promo_safe", True):  # sad/sensitive events are not offered for promo banners
            continue
        if month_day and e.get("month_day") != month_day:
            continue
        if terms and not all(t in e["_fold"] for t in terms):
            continue
        out.append(public(e))
        if len(out) >= limit:
            break
    return out


def get(path: str, event_id: str) -> dict | None:
    for e in load_events(path):
        if e["id"] == event_id:
            return public(e)
    return None
