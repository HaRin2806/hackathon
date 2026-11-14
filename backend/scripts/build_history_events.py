"""Extract a deduplicated event table from minhxthanh/Vietnam-History-1M-Vi (MIT, 871 MB JSONL).

The dataset is templated synthetic Q&A: the same few hundred events repeat with different wordings.
We stream it (never load 871 MB into RAM), regex-parse the assistant 'final' answers into
{event, year, summary, significance}, dedupe by (event, year), and merge with the curated seed.
Curated entries always win and are the only ones marked verified=true.

Usage (from backend/):
  python scripts/build_history_events.py --max-rows 50000          # quick sample over HTTP
  python scripts/build_history_events.py                            # full stream (~871 MB download)
  python scripts/build_history_events.py --local "D:/data/Vietnam History Complete.jsonl"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import httpx

URL = ("https://huggingface.co/datasets/minhxthanh/Vietnam-History-1M-Vi/resolve/main/"
       "Vietnam%20History%20Complete.jsonl")
OUT = Path(__file__).resolve().parent.parent / "data" / "history_events.json"
SOURCE = "dataset:minhxthanh/Vietnam-History-1M-Vi (MIT)"

SENSITIVE = re.compile(r"dịch|sự cố|ô nhiễm|thảm họa|thảm sát|lũ|bão|động đất|nạn đói|thất thủ|mất|tử|hy sinh|khủng hoảng|bị bắt|xâm lược|đô hộ|bảo hộ|hòa ước|thực dân|chia cắt", re.I)  # not for promo banners

PATTERNS = [
    re.compile(r"^\*\*(?P<event>.+?)\*\* xảy ra năm (?P<year>\d{3,4})\. (?P<summary>.+?)\.?\s*"
               r"Đây là cột mốc quan trọng vì (?P<sig>.+?)\.?$"),
    re.compile(r"^(?P<event>[^()\n]+?) \((?P<year>\d{3,4})\)[:.] (?P<summary>.+?)\.?\s*"
               r"Sự kiện này có ý nghĩa là (?P<sig>.+?)\.?$"),
    re.compile(r"^(?P<event>.+?) \((?P<year>\d{3,4})\)\. (?P<summary>[^.]+)\. (?P<sig>.+?)\.?$"),
    re.compile(r"^(?P<year>\d{3,4}): (?P<event>[^.]+)\. (?P<summary>[^.]+)\. (?P<sig>.+?)\.?$"),
]


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower()).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip("-")


def clean(s: str) -> str:
    s = re.sub(r"\.{2,}", ".", s.strip().replace("**", ""))
    return s[:1].upper() + s[1:] if s else s


def lines_from(args):
    if args.local:
        with open(args.local, encoding="utf-8") as f:
            yield from f
        return
    with httpx.stream("GET", URL, follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as r:
        r.raise_for_status()
        yield from r.iter_lines()


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--local", default="")
    ap.add_argument("--min-count", type=int, default=2, help="keep events seen at least N times")
    args = ap.parse_args()

    found: dict[tuple[str, int], dict] = {}
    counts: Counter = Counter()
    rows = parsed = 0
    stream = lines_from(args)
    while True:
        try:
            line = next(stream)
        except StopIteration:
            break
        except httpx.HTTPError as e:  # flaky network: keep what we already parsed
            print(f"  stream interrupted after {rows:,} rows ({type(e).__name__}); saving partial result",
                  file=sys.stderr)
            break
        if not line.strip():
            continue
        rows += 1
        try:
            msgs = json.loads(line)["messages"]
        except (json.JSONDecodeError, KeyError):
            continue
        final = next((m["content"] for m in reversed(msgs)
                      if m.get("role") == "assistant" and m.get("channel") in ("final", None)), "")
        for pat in PATTERNS:
            m = pat.match(final.strip())
            if m:
                year = int(m["year"])
                if not 100 <= year <= 2030:
                    break
                event = clean(m["event"])
                key = (fold(event), year)
                counts[key] += 1
                if key not in found:
                    found[key] = {"event": event, "year": year,
                                  "summary": clean(m["summary"]) + ".", "significance": clean(m["sig"]) + "."}
                parsed += 1
                break
        if rows % 5000 == 0:
            print(f"  {rows:,} rows, {parsed:,} parsed, {len(found):,} unique", file=sys.stderr)
        if args.max_rows and rows >= args.max_rows:
            break

    curated = [e for e in json.loads(OUT.read_text(encoding="utf-8")) if e.get("source") == "curated"] \
        if OUT.exists() else []
    curated_keys = {(fold(e["event"]), e["year"]) for e in curated}
    extracted = []
    for key, e in found.items():
        if counts[key] < args.min_count or key in curated_keys:
            continue
        extracted.append({"id": f"{e['year']}-{key[0][:40]}", "event": e["event"], "year": e["year"],
                          "month_day": None, "summary": e["summary"], "significance": e["significance"],
                          "source": SOURCE, "verified": False, "occurrences": counts[key],
                          "promo_safe": not SENSITIVE.search(e["event"] + " " + e["summary"])})
    extracted.sort(key=lambda e: e["year"])
    OUT.write_text(json.dumps(curated + extracted, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rows={rows:,} parsed={parsed:,} unique={len(found):,} kept={len(extracted):,} "
          f"curated={len(curated)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
