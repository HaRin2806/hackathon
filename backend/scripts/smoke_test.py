"""End-to-end smoke test against a running backend (local or tunnel URL).

  python scripts/smoke_test.py                         # http://127.0.0.1:8000, product-left sketch
  python scripts/smoke_test.py --base https://xxx.trycloudflare.com --sketch samples/sketch_product_right.jpg
Logs one line per run in the spec §12 measurement format (evidence/runs.csv).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--sketch", default=str(ROOT / "samples" / "sketch_product_left.jpg"))
    ap.add_argument("--product", default=str(ROOT / "samples" / "product_tra_sua.jpg"))
    ap.add_argument("--event", default="")
    args = ap.parse_args()

    brief = {"product_name": "Trà sữa trân châu đường đen", "headline": "", "price": "39.000đ",
             "cta": "Đặt ngay hôm nay", "history_event_id": args.event or None}
    t0 = time.perf_counter()
    with httpx.Client(base_url=args.base, timeout=60) as c:
        print("health:", c.get("/health").json())
        r = c.post("/v1/generations",
                   files={"sketch": open(args.sketch, "rb"), "product": open(args.product, "rb")},
                   data={"brief_json": json.dumps(brief, ensure_ascii=False),
                         "client_request_id": uuid.uuid4().hex})
        r.raise_for_status()
        created = r.json()
        upload_ms = int((time.perf_counter() - t0) * 1000)
        jid, tok = created["job_id"], created["job_token"]
        print("created:", jid)
        last = None
        while True:
            job = c.get(f"/v1/generations/{jid}", headers={"X-Job-Token": tok}).json()
            if job["stage"] != last:
                print(f"  {time.perf_counter() - t0:5.1f}s  {job['stage']}")
                last = job["stage"]
            if job["status"] in ("SUCCEEDED", "FAILED", "INTERRUPTED"):
                break
            time.sleep(1)
        total_ms = int((time.perf_counter() - t0) * 1000)
        out = ROOT / "evidence" / jid
        out.mkdir(parents=True, exist_ok=True)
        if job["status"] == "SUCCEEDED":
            for v in job["variants"]:
                png = c.get(f"/v1/generations/{jid}/variants/{v['id']}.png", headers={"X-Job-Token": tok})
                (out / f"{v['id']}.png").write_bytes(png.content)
        (out / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: job.get(k) for k in ("status", "error_code", "model_id", "is_fixture", "layout_source",
                                                "layout_reading", "headline_used", "warnings", "metrics")},
                     ensure_ascii=False, indent=2))
    log = ROOT / "evidence" / "runs.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["job_id", "model_id", "is_fixture", "sketch", "upload_ms", "ai_ms", "render_ms",
                        "total_ms", "status", "error_code", "warnings"])
        m = job.get("metrics") or {}
        w.writerow([jid, job.get("model_id"), job.get("is_fixture"), Path(args.sketch).name, upload_ms,
                    m.get("ai_ms"), m.get("render_ms"), total_ms, job["status"], job.get("error_code"),
                    "; ".join(job.get("warnings") or [])])
    print("evidence ->", out)
    return 0 if job["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
