from __future__ import annotations

import asyncio
import hmac
import mimetypes
import re
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from .android_state import (
    has_marker,
    make_claim,
    note_with_claim,
    note_with_marker,
    now_epoch,
    parse_claim,
    ready_base,
    ready_url,
    transition_decision,
    valid_claim_token,
    valid_device_id,
)
from .google_store import GoogleStore
from .num import as_int
from .runner import scheduler_loop
from .settings import settings

# Railway currently runs one replica. This lock also makes claim/recovery/result
# atomic inside the process so two phones cannot both observe VALIDATED and win.
_ANDROID_STATE_LOCK = threading.RLock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (settings.publish_transport or "").strip().upper() != "ANDROID":
        raise RuntimeError("ONLY_ANDROID_TRANSPORT_IS_SUPPORTED")
    if len((settings.android_api_token or "").strip()) < 32:
        raise RuntimeError("ANDROID_API_TOKEN_MUST_BE_AT_LEAST_32_CHARS")

    store = GoogleStore()
    cfg = store.read_config()
    print(
        f"GOOGLE_SELF_TEST_OK auth_mode={settings.google_auth_mode} "
        f"config_keys={len(cfg)} publish_transport=ANDROID "
        f"pilot_safe_mode={settings.android_pilot_safe_mode}",
        flush=True,
    )

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop))
    app.state.stop = stop
    app.state.task = task
    yield
    stop.set()
    await task


app = FastAPI(
    title="Facebook Story Automation Control Plane",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _require_android(authorization: str | None = Header(default=None)) -> None:
    if (settings.publish_transport or "").strip().upper() != "ANDROID":
        raise HTTPException(status_code=503, detail="ANDROID_TRANSPORT_DISABLED")
    token = (settings.android_api_token or "").strip()
    if len(token) < 32:
        raise HTTPException(status_code=503, detail="ANDROID_API_TOKEN_NOT_CONFIGURED")
    if not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="ANDROID_UNAUTHORIZED")


def _device_id(value: str | None) -> str:
    device = (value or "").strip()
    if not valid_device_id(device):
        raise HTTPException(status_code=400, detail="INVALID_DEVICE_ID")
    return device


def _claim_token(value: str | None) -> str:
    token = (value or "").strip()
    if not valid_claim_token(token):
        raise HTTPException(status_code=400, detail="INVALID_CLAIM_TOKEN")
    return token


def _find_job(store: GoogleStore, job_id: str):
    matches = [j for j in store.read_queue() if j.job_id == job_id]
    if not matches:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if len(matches) != 1:
        raise HTTPException(status_code=409, detail="DUPLICATE_JOB_ID")
    return matches[0]


def _assert_unique_ids(jobs) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for job in jobs:
        if not job.job_id:
            continue
        if job.job_id in seen:
            duplicates.add(job.job_id)
        seen.add(job.job_id)
    if duplicates:
        raise HTTPException(status_code=409, detail="DUPLICATE_JOB_ID_IN_QUEUE")


def _validate_job_payload(store: GoogleStore, job) -> None:
    if not job.job_id:
        raise HTTPException(status_code=409, detail="MISSING_JOB_ID")
    if job.content_type not in {"VIDEO", "IMAGE", "TEXT"}:
        raise HTTPException(status_code=409, detail="INVALID_CONTENT_TYPE")
    if not job.scheduled_at:
        raise HTTPException(status_code=409, detail="MISSING_SCHEDULE")
    if not job.link_url:
        raise HTTPException(status_code=409, detail="MISSING_LINK_URL")
    if not job.link_text:
        raise HTTPException(status_code=409, detail="MISSING_LINK_TEXT")
    cfg = store.read_config()
    default_link = cfg.get("DEFAULT_LINK", "").strip()
    locked = cfg.get("LINK_LOCKED", "TRUE").strip().upper() in {"TRUE", "1", "YES", "Y"}
    if locked and job.link_url != default_link:
        raise HTTPException(status_code=409, detail="LINK_LOCKED_MISMATCH")


def _retry_policy(store: GoogleStore) -> tuple[int, int]:
    cfg = store.read_config()
    retry_max = max(0, as_int(cfg.get("RETRY_MAX", "3"), 3))
    retry_delay = max(30, as_int(cfg.get("RETRY_DELAY_SEC", "120"), 120))
    return retry_max, retry_delay


def _job_payload(job, claim_token: str = "", lease_until: int = 0) -> dict:
    publish_allowed = not settings.dry_run and not settings.android_pilot_safe_mode
    payload = {
        "job_id": job.job_id,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "content_type": job.content_type,
        "link_url": job.link_url,
        "link_text": job.link_text,
        "music_mode": job.music_mode,
        "media_path": f"/api/android/jobs/{job.job_id}/media",
        "publish_allowed": publish_allowed,
        "dry_run": settings.dry_run,
        "pilot_safe_mode": settings.android_pilot_safe_mode,
    }
    if claim_token:
        payload["claim_token"] = claim_token
        payload["lease_until_epoch"] = lease_until
    return payload


def _verify_current_claim(job, device_id: str, claim_token: str):
    if job.status != "PROCESSING":
        raise HTTPException(status_code=409, detail=f"CLAIM_REQUIRES_PROCESSING:{job.status}")
    claim = parse_claim(job.note)
    if not claim:
        raise HTTPException(status_code=409, detail="JOB_HAS_NO_ACTIVE_CLAIM")
    if not claim.active(now_epoch()):
        raise HTTPException(status_code=409, detail="CLAIM_LEASE_EXPIRED")
    if claim.device_id != device_id or not hmac.compare_digest(claim.claim_token, claim_token):
        raise HTTPException(status_code=409, detail="CLAIM_OWNERSHIP_MISMATCH")
    return claim


def _recover_expired_claims(store: GoogleStore, jobs) -> int:
    """Recover crashed Android claims and legacy v0.1 PROCESSING rows.

    A PROCESSING row with ANDROID_READY media but no parseable claim is impossible in
    the hardened protocol, so it is safe to treat it as a legacy/stale claim.
    """
    current_epoch = now_epoch()
    now = datetime.now(ZoneInfo(settings.timezone))
    retry_max, retry_delay = _retry_policy(store)
    recovered = 0

    for job in jobs:
        if job.status != "PROCESSING" or not ready_url(job.note):
            continue
        claim = parse_claim(job.note)
        if claim and claim.active(current_epoch):
            continue

        retry_count = job.retry_count + 1
        if retry_count > retry_max:
            target = "FAILED"
            next_try = ""
            marker = "ANDROID_RETRY_EXHAUSTED"
        else:
            target = "VALIDATED"
            next_try = now + timedelta(seconds=retry_delay)
            marker = "ANDROID_RETRY_READY"

        reason = "ANDROID_CLAIM_LEASE_EXPIRED" if claim else "ANDROID_LEGACY_CLAIM_RECOVERED"
        base = ready_base(job.note)
        store.update_job(
            job.row,
            STATUS=target,
            RETRY_COUNT=retry_count,
            NEXT_ATTEMPT_AT=next_try,
            ERROR=reason,
            NOTE=note_with_marker(base, marker),
        )
        store.append_log([
            now.strftime("%d/%m/%Y %H:%M:%S"), job.job_id, "ANDROID_RECOVERY",
            "PROCESSING", target, "LEASE_RECOVERY", "ERROR", retry_count,
            "android-control-plane", "", reason, marker,
        ])
        recovered += 1
    return recovered


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
        "pilot_safe_mode": settings.android_pilot_safe_mode,
        "publish_transport": "ANDROID",
        "google_auth_mode": settings.google_auth_mode,
        "now": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
    }


@app.get("/api/android/ping", dependencies=[Depends(_require_android)])
def android_ping():
    return {
        "ok": True,
        "transport": "ANDROID",
        "dry_run": settings.dry_run,
        "pilot_safe_mode": settings.android_pilot_safe_mode,
        "timezone": settings.timezone,
    }


@app.get("/api/android/jobs/next", dependencies=[Depends(_require_android)])
def android_next_job(x_device_id: str | None = Header(default=None)):
    _device_id(x_device_id)
    with _ANDROID_STATE_LOCK:
        store = GoogleStore()
        jobs = store.read_queue()
        _assert_unique_ids(jobs)
        _recover_expired_claims(store, jobs)
        jobs = store.read_queue()

        now = datetime.now(ZoneInfo(settings.timezone))
        candidates = [
            j for j in jobs
            if j.status == "VALIDATED"
            and ready_url(j.note)
            and not has_marker(j.note, "ANDROID_DRY_RUN_OK")
            and not has_marker(j.note, "ANDROID_PUBLISHED")
            and not has_marker(j.note, "ANDROID_RETRY_EXHAUSTED")
            and (not j.next_attempt_at or j.next_attempt_at <= now)
            and j.scheduled_at is not None
            and j.scheduled_at <= now
        ]
        if not candidates:
            return {"job": None}
        candidates.sort(key=lambda j: j.scheduled_at or now)
        job = candidates[0]
        _validate_job_payload(store, job)
        return {"job": _job_payload(job)}


@app.post("/api/android/jobs/{job_id}/claim", dependencies=[Depends(_require_android)])
def android_claim_job(job_id: str, x_device_id: str | None = Header(default=None)):
    device = _device_id(x_device_id)
    with _ANDROID_STATE_LOCK:
        store = GoogleStore()
        job = _find_job(store, job_id)
        _validate_job_payload(store, job)
        if not ready_url(job.note):
            raise HTTPException(status_code=409, detail="READY_MEDIA_MISSING")

        current = now_epoch()
        existing = parse_claim(job.note)
        if job.status == "PROCESSING" and existing and existing.active(current):
            if existing.device_id != device:
                raise HTTPException(status_code=409, detail="JOB_CLAIMED_BY_OTHER_DEVICE")
            return {
                "ok": True,
                "idempotent": True,
                "job": _job_payload(job, existing.claim_token, existing.lease_until_epoch),
            }

        # Direct claim of an expired/legacy PROCESSING row must go through the same
        # retry accounting as /next recovery; it cannot silently bypass retry delay.
        if job.status == "PROCESSING":
            _recover_expired_claims(store, [job])
            job = _find_job(store, job_id)

        if job.status != "VALIDATED":
            raise HTTPException(status_code=409, detail=f"JOB_NOT_READY:{job.status}")
        now_dt = datetime.now(ZoneInfo(settings.timezone))
        if job.next_attempt_at and job.next_attempt_at > now_dt:
            raise HTTPException(status_code=409, detail="JOB_RETRY_NOT_DUE")

        claim = make_claim(job.note, device, settings.android_claim_lease_sec, current)
        claimed_note = note_with_claim(job.note, claim)
        store.update_job(
            job.row,
            STATUS="PROCESSING",
            ERROR="",
            NEXT_ATTEMPT_AT="",
            NOTE=claimed_note,
        )
        store.append_log([
            now_dt.strftime("%d/%m/%Y %H:%M:%S"), job.job_id, "ANDROID_CLAIM",
            job.status, "PROCESSING", "ANDROID_DEVICE", "OK", job.retry_count,
            f"android:{device}", "", "", "Leased claim; idempotent for same device",
        ])
        return {
            "ok": True,
            "idempotent": False,
            "job": _job_payload(job, claim.claim_token, claim.lease_until_epoch),
        }


@app.get("/api/android/jobs/{job_id}/media", dependencies=[Depends(_require_android)])
def android_job_media(
    job_id: str,
    x_device_id: str | None = Header(default=None),
    x_claim_token: str | None = Header(default=None),
):
    device = _device_id(x_device_id)
    claim_token = _claim_token(x_claim_token)
    store = GoogleStore()
    job = _find_job(store, job_id)
    _verify_current_claim(job, device, claim_token)

    url = ready_url(job.note)
    if not url:
        raise HTTPException(status_code=404, detail="READY_MEDIA_MISSING")
    file_id = store.extract_drive_id(url)
    meta = store.drive.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,parents",
    ).execute()
    media_type = str(meta.get("mimeType") or "")
    if not (media_type.startswith("image/") or media_type.startswith("video/")):
        raise HTTPException(status_code=415, detail="UNSUPPORTED_READY_MEDIA_TYPE")
    try:
        size = int(meta.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        raise HTTPException(status_code=409, detail="READY_MEDIA_EMPTY")
    if size > settings.android_max_media_bytes:
        raise HTTPException(status_code=413, detail="READY_MEDIA_TOO_LARGE")

    cfg = store.read_config()
    ready_folder = cfg.get("MEDIA_READY_FOLDER_ID", "").strip()
    parents = set(meta.get("parents") or [])
    if ready_folder and ready_folder not in parents:
        raise HTTPException(status_code=409, detail="READY_MEDIA_OUTSIDE_APPROVED_FOLDER")

    original_name = str(meta.get("name") or "story_media")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_name)[:180] or "story_media"
    suffix = Path(safe_name).suffix or (".mp4" if media_type.startswith("video/") else ".jpg")
    api_dir = Path(settings.work_dir) / "android_api"
    api_dir.mkdir(parents=True, exist_ok=True)
    destination = api_dir / f"{uuid.uuid4().hex}{suffix}"
    store.download_drive_file(file_id, destination)
    if not destination.exists() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="READY_MEDIA_DOWNLOAD_EMPTY")
    if destination.stat().st_size > settings.android_max_media_bytes:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="READY_MEDIA_TOO_LARGE")

    return FileResponse(
        destination,
        media_type=media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        filename=safe_name,
        background=BackgroundTask(lambda: destination.unlink(missing_ok=True)),
    )


@app.post("/api/android/jobs/{job_id}/result", dependencies=[Depends(_require_android)])
def android_job_result(
    job_id: str,
    result: AndroidResult,
    x_device_id: str | None = Header(default=None),
    x_claim_token: str | None = Header(default=None),
):
    device = _device_id(x_device_id)
    state = (result.state or "").strip().upper()

    with _ANDROID_STATE_LOCK:
        store = GoogleStore()
        job = _find_job(store, job_id)

        # Lost HTTP response after a successful state write must be harmless.
        if job.status == "PUBLISHED" and state == "PUBLISHED" and has_marker(job.note, "ANDROID_PUBLISHED"):
            return {"ok": True, "status": "PUBLISHED", "idempotent": True}
        if state in {"DRY_RUN_READY", "READY_TO_PUBLISH"} and job.status == "VALIDATED" and has_marker(job.note, "ANDROID_DRY_RUN_OK"):
            return {"ok": True, "status": "VALIDATED", "idempotent": True}
        if state in {"FAILED", "RELEASE"} and has_marker(job.note, "ANDROID_RETRY_READY") and job.status == "VALIDATED":
            return {"ok": True, "status": "VALIDATED", "idempotent": True}
        if state in {"FAILED", "RELEASE"} and has_marker(job.note, "ANDROID_RETRY_EXHAUSTED") and job.status == "FAILED":
            return {"ok": True, "status": "FAILED", "idempotent": True}

        claim_token = _claim_token(x_claim_token)
        _verify_current_claim(job, device, claim_token)
        try:
            decision = transition_decision(
                job.status,
                state,
                settings.dry_run or settings.android_pilot_safe_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        now = datetime.now(ZoneInfo(settings.timezone))
        base = ready_base(job.note)
        log_retry_count = job.retry_count

        if decision == "PUBLISHED":
            store.update_job(
                job.row,
                STATUS="PUBLISHED",
                PUBLISHED_AT=now,
                ERROR="",
                NEXT_ATTEMPT_AT="",
                NOTE=note_with_marker(base, "ANDROID_PUBLISHED"),
            )
            if job.music_track_id:
                track = next((t for t in store.music_catalog() if t.track_id == job.music_track_id), None)
                if track:
                    store.mark_track_used(track)
            target_status = "PUBLISHED"
            event = "ANDROID_PUBLISH"
        elif decision == "DRY_RUN_OK":
            store.update_job(
                job.row,
                STATUS="VALIDATED",
                ERROR="",
                NEXT_ATTEMPT_AT="",
                NOTE=note_with_marker(base, "ANDROID_DRY_RUN_OK"),
            )
            target_status = "VALIDATED"
            event = "ANDROID_DRY_RUN"
        else:  # RELEASE
            retry_max, delay = _retry_policy(store)
            retry_count = job.retry_count + 1
            log_retry_count = retry_count
            if retry_count > retry_max:
                target_status = "FAILED"
                next_try = ""
                marker = "ANDROID_RETRY_EXHAUSTED"
            else:
                target_status = "VALIDATED"
                next_try = now + timedelta(seconds=delay)
                marker = "ANDROID_RETRY_READY"
            store.update_job(
                job.row,
                STATUS=target_status,
                RETRY_COUNT=retry_count,
                ERROR=(result.error or "ANDROID_DEVICE_FAILED")[:1500],
                NEXT_ATTEMPT_AT=next_try,
                NOTE=note_with_marker(base, marker),
            )
            event = "ANDROID_RELEASE"

        store.append_log([
            now.strftime("%d/%m/%Y %H:%M:%S"), job.job_id, event,
            job.status, target_status, "ANDROID_DEVICE", "OK" if decision != "RELEASE" else "ERROR",
            log_retry_count, f"android:{device}", "", (result.error or "")[:1000],
            (result.note or "")[:1000],
        ])
        return {"ok": True, "status": target_status, "idempotent": False}
