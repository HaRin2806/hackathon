"""Durable file-based job store + single background worker (spec §05/§08).

Each job lives in data/jobs/{job_id}/ (inputs, job.json, spec.json, PNGs), so closing the app or
restarting the phone never loses a generation. Backend restart marks running jobs INTERRUPTED.
Idempotency: same client_request_id + same payload -> same job; different payload -> 409.
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import history
from .ai_adapter import AIError, generate_design
from .config import Settings
from .renderer import Texts, render
from .schemas import Brief
from .validator import build_spec, headline_text

log = logging.getLogger("sketch2banner.jobs")

TERMINAL = {"SUCCEEDED", "FAILED", "INTERRUPTED"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Conflict(Exception):
    pass


class Busy(Exception):
    pass


class JobStore:
    def __init__(self, settings: Settings):
        self.s = settings
        self.root: Path = settings.data_dir
        self.lock = threading.RLock()
        self.q: queue.Queue[str] = queue.Queue(maxsize=5)
        self.req_index = self.root / "_requests.json"
        self._mark_interrupted()
        threading.Thread(target=self._worker, name="job-worker", daemon=True).start()

    # ---------- persistence ----------
    def _dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _write(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, job_id: str) -> dict | None:
        p = self._dir(job_id) / "job.json"
        if not p.exists() or "/" in job_id or "\\" in job_id or ".." in job_id:
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def update(self, job_id: str, **fields) -> dict:
        with self.lock:
            job = self.load(job_id) or {}
            job.update(fields)
            self._write(self._dir(job_id) / "job.json", job)
            return job

    def _mark_interrupted(self) -> None:
        for p in self.root.glob("*/job.json"):
            job = json.loads(p.read_text(encoding="utf-8"))
            if job.get("status") not in TERMINAL:
                job.update(status="INTERRUPTED", stage="INTERRUPTED", error_code="backend_restarted",
                           error_message="Server khởi động lại khi job đang chạy. Hãy tạo lượt mới.",
                           completed_at=now_iso())
                self._write(p, job)

    # ---------- create ----------
    def create(self, client_request_id: str, sketch: bytes, sketch_ext: str, product: bytes, product_ext: str,
               brief: Brief) -> tuple[dict, bool]:
        """Returns (job, created_new)."""
        payload_hash = hashlib.sha256(
            sketch + b"|" + product + b"|" + brief.model_dump_json().encode()
        ).hexdigest()
        with self.lock:
            index = json.loads(self.req_index.read_text(encoding="utf-8")) if self.req_index.exists() else {}
            if client_request_id in index:
                entry = index[client_request_id]
                if entry["payload_hash"] != payload_hash:
                    raise Conflict()
                job = self.load(entry["job_id"])
                if job:
                    return job, False
            if self.q.full():
                raise Busy()

            job_id = datetime.now().strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            d = self._dir(job_id)
            d.mkdir(parents=True)
            sp, pp = d / f"sketch{sketch_ext}", d / f"product{product_ext}"
            sp.write_bytes(sketch)
            pp.write_bytes(product)
            job = {
                "job_id": job_id,
                "job_token": secrets.token_urlsafe(24),
                "client_request_id": client_request_id,
                "status": "QUEUED",
                "stage": "QUEUED",
                "error_code": None,
                "error_message": None,
                "created_at": now_iso(),
                "started_at": None,
                "completed_at": None,
                "model_id": self.s.resolved_model(),
                "provider": self.s.ai_provider,
                "is_fixture": self.s.ai_provider == "mock",
                "brief": brief.model_dump(),
                "inputs": {"sketch": sp.name, "product": pp.name,
                           "sketch_bytes": len(sketch), "product_bytes": len(product)},
                "variants": [],
                "warnings": [],
                "metrics": {},
            }
            self._write(d / "job.json", job)
            index[client_request_id] = {"job_id": job_id, "payload_hash": payload_hash}
            self._write(self.req_index, index)
            self.q.put_nowait(job_id)
            return job, True

    # ---------- worker ----------
    def _worker(self) -> None:
        while True:
            job_id = self.q.get()
            try:
                self._run(job_id)
            except Exception:  # never kill the worker
                log.exception("job %s crashed", job_id)
                self.update(job_id, status="FAILED", stage="FAILED", error_code="internal_error",
                            error_message="Lỗi nội bộ khi xử lý job.", completed_at=now_iso())

    def _run(self, job_id: str) -> None:
        job = self.load(job_id)
        if not job:
            return
        d = self._dir(job_id)
        t0 = time.perf_counter()
        deadline = time.monotonic() + self.s.job_deadline_s
        brief = Brief(**job["brief"])
        event = history.get(str(self.s.history_events_path), brief.history_event_id) if brief.history_event_id else None

        self.update(job_id, status="ANALYZING", stage="ANALYZING", started_at=now_iso())
        try:
            ai = generate_design(self.s, str(d / job["inputs"]["sketch"]), str(d / job["inputs"]["product"]),
                                 brief, event, deadline)
        except AIError as e:
            log.warning("job %s AI error %s", job_id, e.code)
            self.update(job_id, status="FAILED", stage="FAILED", error_code=e.code, error_message=e.message,
                        completed_at=now_iso(), metrics={"total_ms": int((time.perf_counter() - t0) * 1000)})
            return

        self.update(job_id, status="VALIDATING", stage="VALIDATING")
        spec = build_spec(ai.design, brief)
        self._write(d / "spec.json", {**spec.model_dump(), "headline_suggestion": ai.design.headline_suggestion})

        self.update(job_id, status="RENDERING", stage="RENDERING")
        kicker = f"Ngày này năm {event['year']} · {event['event']}" if event else ""
        texts = Texts(
            headline=headline_text(spec, brief, ai.design.headline_suggestion),
            product_name=brief.product_name,
            price=brief.price,
            cta=brief.cta,
            kicker=kicker[:60],
        )
        r0 = time.perf_counter()
        result = render(spec, texts, str(d / job["inputs"]["product"]), d, self.s.font_bold, self.s.font_regular)
        render_ms = int((time.perf_counter() - r0) * 1000)

        variants = [{"id": v.id, "style": v.style, "treatment": v.treatment,
                     "sha256": hashlib.sha256(Path(result.paths[v.id]).read_bytes()).hexdigest()[:16]}
                    for v in spec.variants]
        self.update(
            job_id,
            status="SUCCEEDED",
            stage="SUCCEEDED",
            completed_at=now_iso(),
            model_id=ai.model_id,
            is_fixture=ai.is_fixture,
            variants=variants,
            warnings=result.warnings + spec.repairs,
            layout_source=spec.layout_source,
            layout_reading=spec.layout_reading,
            needs_clarification=spec.needs_clarification,
            headline_source=spec.headline_source,
            headline_used=texts.headline,
            history_event=event,
            metrics={"ai_ms": ai.ai_ms, "render_ms": render_ms, "attempts": ai.attempts, "usage": ai.usage,
                     "total_ms": int((time.perf_counter() - t0) * 1000)},
        )
        log.info("job %s SUCCEEDED model=%s total_ms=%s", job_id, ai.model_id,
                 int((time.perf_counter() - t0) * 1000))

    # ---------- listing ----------
    def recent(self, limit: int = 10) -> list[dict]:
        jobs = []
        for p in sorted(self.root.glob("*/job.json"), reverse=True)[:limit]:
            jobs.append(json.loads(p.read_text(encoding="utf-8")))
        return jobs
