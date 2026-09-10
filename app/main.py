from __future__ import annotations

import asyncio
import hmac
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from .google_store import GoogleStore
from .runner import scheduler_loop
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        store = GoogleStore()
        cfg = store.read_config()
        print(
            f"GOOGLE_SELF_TEST_OK auth_mode={settings.google_auth_mode} "
            f"config_keys={len(cfg)} publish_transport={settings.publish_transport}",
            flush=True,
        )
    except Exception as exc:
        print(f"GOOGLE_SELF_TEST_ERROR {type(exc).__name__}: {exc}", flush=True)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop))
    app.state.stop = stop
    app.state.task = task
    yield
    stop.set()
    await task


app = FastAPI(title="Facebook Story Automation Control Plane", lifespan=lifespan)


def _require_android(authorization: str | None = Header(default=None)) -> None:
    token = (settings.android_api_token or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="ANDROID_API_TOKEN_NOT_CONFIGURED")
    supplied = authorization or ""
    expected = f"Bearer {token}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="ANDROID_UNAUTHORIZED")


def _find_job(store: GoogleStore, job_id: str):
    for job in store.read_queue():
        if job.job_id == job_id:
            return job
    raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")


def _ready_url(note: str) -> str:
    note = (note or "").strip()
    for prefix in ("ANDROID_READY:", "READY:"):
        if note.startswith(prefix):
            return note[len(prefix):].split(" | ", 1)[0].strip()
    return ""


def _job_payload(job) -> dict:
    return {
        "job_id": job.job_id,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "content_type": job.content_type,
        "link_url": job.link_url,
        "link_text": job.link_text,
        "music_mode": job.music_mode,
        "media_path": f"/api/android/jobs/{job.job_id}/media",
        "publish_allowed": not settings.dry_run,
        "dry_run": settings.dry_run,
    }


class AndroidResult(BaseModel):
    state: str
    error: str = ""
    note: str = ""


@app.get("/health")
def health():
    return {
        "ok": True,
        "timezone": settings.timezone,
        "dry_run": settings.dry_run,
        "publish_transport": settings.publish_transport,
        "google_auth_mode": settings.google_auth_mode,
        "now": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
    }


@app.get("/api/android/ping", dependencies=[Depends(_require_android)])
def android_ping():
    return {
        "ok": True,
        "transport": settings.publish_transport,
        "dry_run": settings.dry_run,
        "timezone": settings.timezone,
    }


@app.get("/api/android/jobs/next", dependencies=[Depends(_require_android)])
def android_next_job():
    if (settings.publish_transport or "").upper() != "ANDROID":
        raise HTTPException(status_code=503, detail="ANDROID_TRANSPORT_DISABLED")
    store = GoogleStore()
    candidates = [
        j for j in store.read_queue()
        if j.status == "VALIDATED"
        and _ready_url(j.note)
        and "ANDROID_DRY_RUN_OK" not in (j.note or "")
        and "ANDROID_PUBLISHED" not in (j.note or "")
    ]
    if not candidates:
        return {"job": None}
    now = datetime.now(ZoneInfo(settings.timezone))
    candidates.sort(key=lambda j: j.scheduled_at or now)
    return {"job": _job_payload(candidates[0])}


@app.post("/api/android/jobs/{job_id}/claim", dependencies=[Depends(_require_android)])
def android_claim_job(job_id: str):
    store = GoogleStore()
    job = _find_job(store, job_id)
    if job.status != "VALIDATED" or not _ready_url(job.note):
        raise HTTPException(status_code=409, detail=f"JOB_NOT_READY:{job.status}")
    now = datetime.now(ZoneInfo(settings.timezone))
    store.update_job(job.row, STATUS="PROCESSING", ERROR="")
    store.append_log([
        now.strftime("%d/%m/%Y %H:%M:%S"), job.job_id, "ANDROID_CLAIM",
        "VALIDATED", "PROCESSING", "ANDROID_DEVICE", "OK", job.retry_count,
        "android-companion", "", "", "Phone claimed prepared Story"
    ])
    return {"ok": True, "job": _job_payload(job)}


@app.get("/api/android/jobs/{job_id}/media", dependencies=[Depends(_require_android)])
def android_job_media(job_id: str):
    store = GoogleStore()
    job = _find_job(store, job_id)
    if job.status not in {"VALIDATED", "PROCESSING"}:
        raise HTTPException(status_code=409, detail=f"JOB_MEDIA_NOT_AVAILABLE:{job.status}")
    url = _ready_url(job.note)
    if not url:
        raise HTTPException(status_code=404, detail="READY_MEDIA_MISSING")
    file_id = store.extract_drive_id(url)
    meta = store.drive.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    safe_job = re.sub(r"[^A-Za-z0-9_.-]", "_", job.job_id)[:100]
    original_name = str(meta.get("name") or "story_media")
    suffix = Path(original_name).suffix
    api_dir = Path(settings.work_dir) / "android_api"
    api_dir.mkdir(parents=True, exist_ok=True)
    destination = api_dir / f"{safe_job}{suffix}"
    store.download_drive_file(file_id, destination)
    media_type = str(meta.get("mimeType") or "") or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    return FileResponse(
        destination,
        media_type=media_type,
        filename=original_name,
        background=BackgroundTask(lambda: destination.unlink(missing_ok=True)),
    )


@app.post("/api/android/jobs/{job_id}/result", dependencies=[Depends(_require_android)])
def android_job_result(job_id: str, result: AndroidResult):
    store = GoogleStore()
    job = _find_job(store, job_id)
    state = (result.state or "").strip().upper()
    now = datetime.now(ZoneInfo(settings.timezone))
    base_note = job.note.split(" | ", 1)[0] if job.note else ""

    if state == "PUBLISHED":
        if settings.dry_run:
            raise HTTPException(status_code=409, detail="PUBLISH_DISABLED_BY_DRY_RUN")
        store.update_job(
            job.row,
            STATUS="PUBLISHED",
            PUBLISHED_AT=now,
            ERROR="",
            NEXT_ATTEMPT_AT="",
            NOTE=f"{base_note} | ANDROID_PUBLISHED",
        )
        if job.music_track_id:
            track = next((t for t in store.music_catalog() if t.track_id == job.music_track_id), None)
            if track:
                store.mark_track_used(track)
        target_status = "PUBLISHED"
        event = "ANDROID_PUBLISH"
    elif state in {"DRY_RUN_READY", "READY_TO_PUBLISH"}:
        store.update_job(
            job.row,
            STATUS="VALIDATED",
            ERROR="",
            NEXT_ATTEMPT_AT="",
            NOTE=f"{base_note} | ANDROID_DRY_RUN_OK",
        )
        target_status = "VALIDATED"
        event = "ANDROID_DRY_RUN"
    elif state in {"FAILED", "RELEASE"}:
        store.update_job(
            job.row,
            STATUS="VALIDATED",
            ERROR=(result.error or "ANDROID_DEVICE_FAILED")[:1500],
            NEXT_ATTEMPT_AT="",
            NOTE=f"{base_note} | ANDROID_RETRY_READY",
        )
        target_status = "VALIDATED"
        event = "ANDROID_RELEASE"
    else:
        raise HTTPException(status_code=400, detail="INVALID_ANDROID_RESULT_STATE")

    store.append_log([
        now.strftime("%d/%m/%Y %H:%M:%S"), job.job_id, event,
        job.status, target_status, "ANDROID_DEVICE", "OK" if state != "FAILED" else "ERROR",
        job.retry_count, "android-companion", "", (result.error or "")[:1000],
        (result.note or "")[:1000]
    ])
    return {"ok": True, "status": target_status}
