from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .google_store import GoogleStore
from .link_text import select_link_text
from .media import detect_type, has_audio, prepare_media
from .meta_worker import MetaWorker
from .music import choose_track
from .settings import settings


def _bool(v: str, default=False) -> bool:
    if v == "":
        return default
    return v.strip().upper() in {"TRUE", "1", "YES", "Y"}


class JobRunner:
    def __init__(self):
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
        jid = job.job_id or f"ROW-{job.row}"
        self.store.update_job(job.row, STATUS="PROCESSING", ERROR="", NEXT_ATTEMPT_AT="")
        self.store.append_log([now.strftime("%d/%m/%Y %H:%M:%S"), jid, "START", job.status, "PROCESSING", "CLAIM_JOB", "OK", job.retry_count, "browser-worker", "", "", ""])
        try:
            default_link = cfg.get("DEFAULT_LINK", "").strip()
            link_locked = _bool(cfg.get("LINK_LOCKED", "TRUE"), True)
            link = (job.link_url or default_link).strip()
            if link_locked and link != default_link:
                raise RuntimeError("LINK_LOCKED_MISMATCH")
            repeat_window = int(float(cfg.get("LINK_TEXT_REPEAT_WINDOW", "1")))
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
            if content_type == "NEEDS_REVIEW":
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
                    recent_n = int(float(cfg.get("MUSIC_REPEAT_WINDOW", "10")))
                    selected_track = choose_track(self.store.music_catalog(), job.music_pool, self.store.recent_track_ids(recent_n), cfg)
                if not selected_track.drive_file_id:
                    raise RuntimeError("MUSIC_TRACK_FILE_MISSING")
                music_ext = Path(selected_track.drive_file_name).suffix or ".mp3"
                music_path = self.store.download_drive_file(selected_track.drive_file_id, job_dir / f"music{music_ext}")
            ready = prepare_media(source, content_type, job.text_content, music_path, job_dir / "ready", cfg)
            ready_folder = cfg.get("MEDIA_READY_FOLDER_ID", "")
            ready_ref = self.store.upload_file(ready, ready_folder, f"{jid}_{ready.name}") if ready_folder else {"url":""}
            self.store.update_job(job.row, CONTENT_TYPE=content_type, MUSIC_MODE=music_mode, MUSIC_TRACK_ID=selected_track.track_id if selected_track else job.music_track_id, LINK_URL=link, LINK_TEXT=link_text, NOTE=f"READY:{ready_ref.get('url','')}")
            worker = MetaWorker(job_dir / "screenshots")
            screenshot = await worker.publish(ready, link, link_text, jid)
            if settings.dry_run:
                self.store.update_job(job.row, STATUS="VALIDATED", ERROR="", NOTE=f"DRY_RUN_OK:{screenshot}")
                self.store.append_log([now.strftime("%d/%m/%Y %H:%M:%S"), jid, "DRY_RUN", "PROCESSING", "VALIDATED", "META_UI", "OK", job.retry_count, "browser-worker", str(screenshot), "", "Publish button not clicked"])
            else:
                published = datetime.now(ZoneInfo(settings.timezone))
                self.store.update_job(job.row, STATUS="PUBLISHED", PUBLISHED_AT=published, ERROR="", NEXT_ATTEMPT_AT="")
                if selected_track:
                    self.store.mark_track_used(selected_track)
                self.store.append_log([published.strftime("%d/%m/%Y %H:%M:%S"), jid, "PUBLISH", "PROCESSING", "PUBLISHED", "META_UI", "OK", job.retry_count, "browser-worker", str(screenshot), "", ""])
        except Exception as exc:
            retry_max = int(float(cfg.get("RETRY_MAX", "3")))
            delay = int(float(cfg.get("RETRY_DELAY_SEC", "120")))
            retry_count = job.retry_count + 1
            if retry_count <= retry_max:
                next_try = datetime.now(ZoneInfo(settings.timezone)) + timedelta(seconds=delay)
                status = "RETRY"
            else:
                next_try = ""
                status = "FAILED"
            self.store.update_job(job.row, STATUS=status, RETRY_COUNT=retry_count, NEXT_ATTEMPT_AT=next_try, ERROR=str(exc))
            self.store.append_log([datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M:%S"), jid, "ERROR", "PROCESSING", status, "PROCESS_JOB", "ERROR", retry_count, "browser-worker", "", str(exc), ""])


async def scheduler_loop(stop: asyncio.Event):
    runner = JobRunner()
    while not stop.is_set():
        try:
            await runner.run_due_once()
        except Exception as exc:
            print(f"scheduler error: {exc}", flush=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.poll_seconds)
        except asyncio.TimeoutError:
            pass
