"""Sketch2Banner API (spec §08) + serves the web client from /.

Run:  cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import io
import json
import logging

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from . import history
from .config import get_settings
from .jobs import Busy, Conflict, JobStore
from .schemas import Brief

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()
store = JobStore(settings)

app = FastAPI(title="Sketch2Banner API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "MPO": ".jpg"}
PUBLIC_FIELDS = (
    "job_id", "status", "stage", "error_code", "error_message", "created_at", "started_at", "completed_at",
    "model_id", "provider", "is_fixture", "variants", "warnings", "metrics", "layout_source", "layout_reading",
    "needs_clarification", "headline_source", "headline_used", "history_event", "brief",
)


def _public(job: dict) -> dict:
    return {k: job.get(k) for k in PUBLIC_FIELDS}


async def _read_image(f: UploadFile, role: str) -> tuple[bytes, str]:
    data = await f.read()
    if not data:
        raise HTTPException(422, {"error_code": f"missing_{role}", "message": f"Thiếu ảnh {role}."})
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, {"error_code": f"{role}_too_large",
                                  "message": f"Ảnh {role} vượt {settings.max_upload_mb:g} MB."})
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, {"error_code": f"invalid_{role}", "message": f"Ảnh {role} không đọc được."})
    if fmt not in ALLOWED:
        raise HTTPException(415, {"error_code": f"unsupported_{role}", "message": "Chỉ nhận JPEG/PNG/WEBP."})
    return data, ALLOWED[fmt]


def _auth(job_id: str, token: str | None) -> dict:
    job = store.load(job_id)
    if not job:
        raise HTTPException(404, {"error_code": "job_not_found", "message": "Không tìm thấy job."})
    if not token or token != job["job_token"]:
        raise HTTPException(403, {"error_code": "bad_token", "message": "Sai job token."})
    return job


@app.get("/health")
def health():
    return {"status": "ok", "provider": settings.ai_provider, "model_id": settings.resolved_model(),
            "ai_key_configured": bool(settings.ai_api_key.get_secret_value()) or settings.ai_provider == "mock",
            "history_events": len(history.load_events(str(settings.history_events_path)))}


@app.post("/v1/generations", status_code=202)
async def create_generation(
    sketch: UploadFile = File(...),
    product: UploadFile = File(...),
    brief_json: str = Form(...),
    client_request_id: str = Form(..., min_length=8, max_length=80),
):
    try:
        brief = Brief(**json.loads(brief_json))
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise HTTPException(422, {"error_code": "invalid_brief", "message": "Brief không hợp lệ.",
                                  "detail": str(e)[:300]})
    if brief.history_event_id and not history.get(str(settings.history_events_path), brief.history_event_id):
        raise HTTPException(422, {"error_code": "unknown_history_event", "message": "Không tìm thấy sự kiện."})
    s_bytes, s_ext = await _read_image(sketch, "sketch")
    p_bytes, p_ext = await _read_image(product, "product")
    try:
        job, _new = store.create(client_request_id, s_bytes, s_ext, p_bytes, p_ext, brief)
    except Conflict:
        raise HTTPException(409, {"error_code": "request_id_conflict",
                                  "message": "client_request_id đã dùng với nội dung khác."})
    except Busy:
        raise HTTPException(503, {"error_code": "busy", "message": "Server đang bận, thử lại sau ít giây."})
    return {"job_id": job["job_id"], "job_token": job["job_token"], "status": job["status"]}


@app.get("/v1/generations/{job_id}")
def get_generation(job_id: str, x_job_token: str | None = Header(None), token: str | None = Query(None)):
    return _public(_auth(job_id, x_job_token or token))


@app.get("/v1/generations/{job_id}/variants/{variant}.png")
def get_variant(job_id: str, variant: str, x_job_token: str | None = Header(None), token: str | None = Query(None)):
    return _variant_file(job_id, variant, x_job_token or token, thumb=False)


@app.get("/v1/generations/{job_id}/variants/{variant}/thumbnail")
def get_thumb(job_id: str, variant: str, x_job_token: str | None = Header(None), token: str | None = Query(None)):
    return _variant_file(job_id, variant, x_job_token or token, thumb=True)


def _variant_file(job_id: str, variant: str, token: str | None, thumb: bool):
    job = _auth(job_id, token)
    if variant not in ("A", "B", "C") or job["status"] != "SUCCEEDED":
        raise HTTPException(404, {"error_code": "variant_not_ready", "message": "Ảnh chưa sẵn sàng."})
    d = settings.data_dir / job_id
    if thumb:
        return FileResponse(d / f"{variant}_thumb.jpg", media_type="image/jpeg")
    return FileResponse(d / f"{variant}.png", media_type="image/png",
                        filename=f"sketch2banner_{job_id}_{variant}.png")


@app.get("/v1/generations/{job_id}/inputs/{role}")
def get_input(job_id: str, role: str, x_job_token: str | None = Header(None), token: str | None = Query(None)):
    job = _auth(job_id, x_job_token or token)
    if role not in ("sketch", "product"):
        raise HTTPException(404)
    return FileResponse(settings.data_dir / job_id / job["inputs"][role])


@app.get("/v1/history/events")
def list_events(q: str = "", month_day: str = Query("", pattern=r"^(\d{2}-\d{2})?$"), limit: int = Query(20, le=100)):
    return {"items": history.search(str(settings.history_events_path), q, month_day, limit)}


# ---- web client ----
if settings.web_dir.exists():
    app.mount("/web", StaticFiles(directory=settings.web_dir, html=True), name="web")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/web/")
