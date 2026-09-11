from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .google_store import GoogleStore
from .link_text import select_link_text
from .media import detect_type, has_audio, prepare_media
from .music import choose_track
from .num import as_int
from .settings import settings


def _bool(v: str, default=False) -> bool:
    if v == "":
        return default
    return v.strip().upper() in {"TRUE", "1", "YES", "Y"}


def _stable_job_id(job) -> str:
    if job.job_id:
        return job.job_id
    if job.scheduled_at:
        stamp = job.scheduled_at.strftime("%Y%m%d-%H%M")
    else:
        stamp = "UNSCHEDULED"
    return f"AUTO-{stamp}-R{job.row}"


class JobRunner:
    def __init__(self):
        if (settings.publish_transport or "").strip().upper() != "ANDROID":
            raise RuntimeError("ONLY_ANDROID_TRANSPORT_IS_SUPPORTED")
        self.store = GoogleStore()
        self.work_root = Path(settings.work_dir)
        self.work_root.mkdir(parents=True, exist_ok=True)

    async def run_due_once(self) -> int:
        jobs = self.store.due_jobs()
        if not jobs:
            return 0
        await self.process(jobs[0])
        return 1

    async def process(self, job):
        cfg = self.store.read_config()
        now = datetime.now(ZoneInfo(settings.timezone))
        jid = _stable_job_id(job)
        actor = "android-control-plane"

        # A blank JOB_ID is legal input from ChatGPT/Sheet, but Android requires a
        # stable unique id. Persist it before any processing so retries use the same id.
        if not job.job_id:
            self.store.update_job(job.row, JOB_ID=jid)
            job.job_id = jid

        duplicates = [j for j in self.store.read_queue() if j.job_id == jid]
        if len(duplicates) != 1:
            self.store.update_job(
                job.row,
                STATUS="FAILED",
                ERROR="DUPLICATE_JOB_ID",
                NEXT_ATTEMPT_AT="",
            )
            self.store.append_log([
                now.strftime("%d/%m/%Y %H:%M:%S"), jid, "ERROR", job.status,
                "FAILED", "VALIDATE_JOB_ID", "ERROR", job.retry_count, actor,
                "", "DUPLICATE_JOB_ID", "Manual correction required",
            ])
            return

        self.store.update_job(job.row, STATUS="PROCESSING", ERROR="", NEXT_ATTEMPT_AT="")
        self.store.append_log([
            now.strftime("%d/%m/%Y %H:%M:%S"), jid, "START", job.status,
            "PROCESSING", "PREPARE_MEDIA", "OK", job.retry_count, actor, "", "", ""
        ])
        try:
            default_link = cfg.get("DEFAULT_LINK", "").strip()
            if not default_link:
                raise RuntimeError("DEFAULT_LINK_NOT_CONFIGURED")
            link_locked = _bool(cfg.get("LINK_LOCKED", "TRUE"), True)
            link = (job.link_url or default_link).strip()
            if link_locked and link != default_link:
                raise RuntimeError("LINK_LOCKED_MISMATCH")

            repeat_window = max(1, as_int(cfg.get("LINK_TEXT_REPEAT_WINDOW", "1"), 1))
            link_text = select_link_text(cfg, self.store.recent_link_texts(repeat_window), job.link_text)

            job_dir = self.work_root / jid
            job_dir.mkdir(parents=True, exist_ok=True)
            source = None
            if job.source_drive_url:
                source_id = self.store.extract_drive_id(job.source_drive_url)
                ext = Path(job.source_file_name).suffix or ".bin"
                source = self.store.download_drive_file(source_id, job_dir / f"source{ext}")

            detected = detect_type(source, job.text_content)
            content_type = detected if job.content_type in {"", "AUTO"} else job.content_type
            if content_type not in {"VIDEO", "IMAGE", "TEXT"}:
                raise RuntimeError("CONTENT_TYPE_NEEDS_REVIEW")

            music_path = None
            selected_track = None
            source_has_audio = bool(source and content_type == "VIDEO" and has_audio(source))
            music_mode = job.music_mode if job.music_mode not in {"", "AUTO"} else cfg.get("MUSIC_MODE", "SMART_RANDOM").upper()
            if source_has_audio and cfg.get("SOURCE_AUDIO_POLICY", "KEEP_IF_PRESENT").upper() == "KEEP_IF_PRESENT":
                music_mode = "KEEP_SOURCE"

            if music_mode in {"SMART_RANDOM", "OVERRIDE"} and not source_has_audio:
                if job.music_track_id:
                    selected_track = next((t for t in self.store.music_catalog() if t.track_id == job.music_track_id), None)
                    if not selected_track:
                        raise RuntimeError("MUSIC_TRACK_OVERRIDE_NOT_FOUND")
                else:
                    recent_n = max(0, as_int(cfg.get("MUSIC_REPEAT_WINDOW", "10"), 10))
                    selected_track = choose_track(
                        self.store.music_catalog(), job.music_pool,
                        self.store.recent_track_ids(recent_n), cfg
                    )
                if not selected_track.drive_file_id:
                    raise RuntimeError("MUSIC_TRACK_FILE_MISSING")
                music_ext = Path(selected_track.drive_file_name).suffix or ".mp3"
                music_path = self.store.download_drive_file(
                    selected_track.drive_file_id, job_dir / f"music{music_ext}"
                )

            ready = prepare_media(source, content_type, job.text_content, music_path, job_dir / "ready", cfg)
            if not ready.exists() or ready.stat().st_size <= 0:
                raise RuntimeError("READY_MEDIA_EMPTY")
            if ready.stat().st_size > settings.android_max_media_bytes:
                raise RuntimeError("READY_MEDIA_TOO_LARGE")

            ready_folder = cfg.get("MEDIA_READY_FOLDER_ID", "").strip()
            if not ready_folder:
                raise RuntimeError("MEDIA_READY_FOLDER_ID_NOT_CONFIGURED")
            ready_ref = self.store.upload_file(ready, ready_folder, f"{jid}_{ready.name}")
            ready_url = ready_ref.get("url", "").strip()
            if not ready_url:
                raise RuntimeError("READY_MEDIA_UPLOAD_MISSING_URL")

            self.store.update_job(
                job.row,
                CONTENT_TYPE=content_type,
                MUSIC_MODE=music_mode,
                MUSIC_TRACK_ID=selected_track.track_id if selected_track else job.music_track_id,
                LINK_URL=link,
                LINK_TEXT=link_text,
                STATUS="VALIDATED",
                ERROR="",
                NEXT_ATTEMPT_AT="",
                NOTE=f"ANDROID_READY:{ready_url}",
            )
            self.store.append_log([
                datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M:%S"),
                jid, "ANDROID_READY", "PROCESSING", "VALIDATED", "HANDOFF_TO_ANDROID",
                "OK", job.retry_count, actor, "", "",
                "Cloud preparation complete; Railway cannot open Facebook"
            ])
        except Exception as exc:
            retry_max = max(0, as_int(cfg.get("RETRY_MAX", "3"), 3))
            delay = max(30, as_int(cfg.get("RETRY_DELAY_SEC", "120"), 120))
            retry_count = job.retry_count + 1
            if retry_count <= retry_max:
                next_try = datetime.now(ZoneInfo(settings.timezone)) + timedelta(seconds=delay)
                status = "RETRY"
            else:
                next_try = ""
                status = "FAILED"
            self.store.update_job(
                job.row,
                STATUS=status,
                RETRY_COUNT=retry_count,
                NEXT_ATTEMPT_AT=next_try,
                ERROR=str(exc)[:1500],
            )
            self.store.append_log([
                datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M:%S"),
                jid, "ERROR", "PROCESSING", status, "PREPARE_MEDIA", "ERROR",
                retry_count, actor, "", str(exc)[:1000], ""
            ])


async def scheduler_loop(stop: asyncio.Event):
    runner = JobRunner()
    while not stop.is_set():
        try:
            await runner.run_due_once()
        except Exception as exc:
            print(f"scheduler error: {exc}", flush=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(5, settings.poll_seconds))
        except asyncio.TimeoutError:
            pass
