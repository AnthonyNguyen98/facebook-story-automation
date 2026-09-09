from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class StoryJob:
    row: int
    job_id: str
    date: str
    time: str
    scheduled_at: Optional[datetime]
    content_type: str
    source_file_name: str
    source_drive_url: str
    text_content: str
    music_mode: str
    music_pool: str
    music_track_id: str
    link_url: str
    link_text: str
    status: str
    retry_count: int
    next_attempt_at: Optional[datetime]
    published_at: Optional[datetime]
    error: str
    note: str


@dataclass
class MusicTrack:
    row: int
    track_id: str
    title: str
    source: str
    pool_primary: str
    pool_secondary: str
    energy_score: float
    vocal_type: str
    duration_sec: float
    license_status: str
    drive_file_name: str
    drive_file_id: str
    last_used_at: str
    use_count: int
    approved: bool
    notes: str
    added_at: str
