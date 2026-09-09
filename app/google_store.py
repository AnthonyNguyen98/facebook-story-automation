from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from .models import MusicTrack, StoryJob
from .num import as_float, as_int
from .settings import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
QUEUE_COLUMNS = ["JOB_ID", "DATE", "TIME", "SCHEDULED_AT", "CONTENT_TYPE", "SOURCE_FILE_NAME", "SOURCE_DRIVE_URL", "TEXT_CONTENT", "MUSIC_MODE", "MUSIC_POOL", "MUSIC_TRACK_ID", "LINK_URL", "LINK_TEXT", "STATUS", "RETRY_COUNT", "NEXT_ATTEMPT_AT", "PUBLISHED_AT", "ERROR", "NOTE"]


def _oauth_creds(info: dict[str, Any]):
    required = ("client_id", "client_secret", "refresh_token")
    if not all(info.get(k) for k in required):
        raise RuntimeError("GOOGLE_OAUTH_CREDENTIALS_JSON is incomplete")
    return UserCredentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri=info.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        scopes=SCOPES,
    )


def _creds():
    mode = (settings.google_auth_mode or "AUTO").strip().upper()
    oauth_info = json.loads(settings.google_oauth_credentials_json or "{}")
    service_info = json.loads(settings.google_service_account_json or "{}")

    if mode in {"AUTO", "OAUTH"} and oauth_info.get("refresh_token"):
        return _oauth_creds(oauth_info)
    if mode == "OAUTH":
        raise RuntimeError("GOOGLE_OAUTH_CREDENTIALS_JSON is not configured")

    if mode in {"AUTO", "SERVICE_ACCOUNT"} and service_info.get("client_email"):
        return service_account.Credentials.from_service_account_info(service_info, scopes=SCOPES)
    if mode == "SERVICE_ACCOUNT":
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")

    raise RuntimeError("Google credentials are not configured")


def _parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    tz = ZoneInfo(settings.timezone)
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz)
        except ValueError:
            pass
    return None


def _scheduled(date_value: str, time_value: str) -> datetime | None:
    tz = ZoneInfo(settings.timezone)
    d = None
    for dfmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(date_value, dfmt).date()
            break
        except ValueError:
            pass
    if d is None:
        return None
    for tfmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(time_value, tfmt).time()
            return datetime.combine(d, t, tzinfo=tz)
        except ValueError:
            continue
    return None


class GoogleStore:
    def __init__(self):
        creds = _creds()
        self.sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.sid = settings.spreadsheet_id

    def read_config(self) -> dict[str, str]:
        values = self.sheets.spreadsheets().values().get(spreadsheetId=self.sid, range="CONFIG!A2:C200", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        cfg = {}
        for row in values:
            if row and str(row[0]).strip():
                cfg[str(row[0]).strip()] = str(row[1]).strip() if len(row) > 1 else ""
        return cfg

    def read_queue(self) -> list[StoryJob]:
        rows = self.sheets.spreadsheets().values().get(spreadsheetId=self.sid, range="QUEUE!A2:S2000", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        jobs = []
        for idx, raw in enumerate(rows, start=2):
            raw = raw + [""] * (19 - len(raw))
            if not any(str(x).strip() for x in raw):
                continue
            jobs.append(StoryJob(row=idx, job_id=str(raw[0]).strip(), date=str(raw[1]).strip(), time=str(raw[2]).strip(), scheduled_at=_scheduled(str(raw[1]).strip(), str(raw[2]).strip()), content_type=str(raw[4]).strip().upper() or "AUTO", source_file_name=str(raw[5]).strip(), source_drive_url=str(raw[6]).strip(), text_content=str(raw[7]).strip(), music_mode=str(raw[8]).strip().upper() or "AUTO", music_pool=str(raw[9]).strip().upper() or "AUTO", music_track_id=str(raw[10]).strip(), link_url=str(raw[11]).strip(), link_text=str(raw[12]).strip(), status=str(raw[13]).strip().upper() or "DRAFT", retry_count=as_int(raw[14], 0), next_attempt_at=_parse_dt(str(raw[15])), published_at=_parse_dt(str(raw[16])), error=str(raw[17]).strip(), note=str(raw[18]).strip()))
        return jobs

    def due_jobs(self) -> list[StoryJob]:
        now = datetime.now(ZoneInfo(settings.timezone))
        due = []
        for j in self.read_queue():
            if j.status not in {"QUEUED", "RETRY"}:
                continue
            gate = j.next_attempt_at if j.status == "RETRY" and j.next_attempt_at else j.scheduled_at
            if gate and gate <= now:
                due.append(j)
        return sorted(due, key=lambda j: j.scheduled_at or now)

    def update_job(self, row: int, **fields: Any) -> None:
        col = {name: i for i, name in enumerate(QUEUE_COLUMNS)}
        data = []
        for key, value in fields.items():
            key = key.upper()
            if key not in col:
                continue
            letter = self._col_letter(col[key] + 1)
            if isinstance(value, datetime):
                value = value.astimezone(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M")
            data.append({"range": f"QUEUE!{letter}{row}", "values": [[value]]})
        if data:
            self.sheets.spreadsheets().values().batchUpdate(spreadsheetId=self.sid, body={"valueInputOption": "USER_ENTERED", "data": data}).execute()

    def append_log(self, values: list[Any]) -> None:
        self.sheets.spreadsheets().values().append(spreadsheetId=self.sid, range="LOGS!A:L", valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS", body={"values": [values]}).execute()

    def recent_link_texts(self, limit: int) -> set[str]:
        jobs = [j for j in self.read_queue() if j.status == "PUBLISHED" and j.link_text]
        return {j.link_text for j in jobs[-max(0, limit):]}

    def recent_track_ids(self, limit: int) -> set[str]:
        jobs = [j for j in self.read_queue() if j.status == "PUBLISHED" and j.music_track_id]
        return {j.music_track_id for j in jobs[-max(0, limit):]}

    def music_catalog(self) -> list[MusicTrack]:
        rows = self.sheets.spreadsheets().values().get(spreadsheetId=self.sid, range="MUSIC_CATALOG!A2:P2000", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        tracks = []
        for idx, raw in enumerate(rows, start=2):
            raw = raw + [""] * (16 - len(raw))
            if not str(raw[0]).strip():
                continue
            tracks.append(MusicTrack(row=idx, track_id=str(raw[0]).strip(), title=str(raw[1]).strip(), source=str(raw[2]).strip(), pool_primary=str(raw[3]).strip().upper(), pool_secondary=str(raw[4]).strip().upper(), energy_score=as_float(raw[5], 0.0), vocal_type=str(raw[6]).strip(), duration_sec=as_float(raw[7], 0.0), license_status=str(raw[8]).strip().upper(), drive_file_name=str(raw[9]).strip(), drive_file_id=str(raw[10]).strip(), last_used_at=str(raw[11]).strip(), use_count=as_int(raw[12], 0), approved=str(raw[13]).strip().upper() in {"TRUE", "YES", "1"}, notes=str(raw[14]).strip(), added_at=str(raw[15]).strip()))
        return tracks

    def mark_track_used(self, track: MusicTrack) -> None:
        now = datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M")
        self.sheets.spreadsheets().values().batchUpdate(spreadsheetId=self.sid, body={"valueInputOption":"USER_ENTERED","data":[{"range":f"MUSIC_CATALOG!L{track.row}","values":[[now]]},{"range":f"MUSIC_CATALOG!M{track.row}","values":[[track.use_count + 1]]}]}).execute()

    def download_drive_file(self, file_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = self.drive.files().get_media(fileId=file_id)
        with io.FileIO(destination, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return destination

    def upload_file(self, path: Path, folder_id: str, name: str | None = None) -> dict[str, str]:
        media = MediaFileUpload(str(path), resumable=True)
        body = {"name": name or path.name, "parents": [folder_id]}
        f = self.drive.files().create(body=body, media_body=media, fields="id,name,webViewLink").execute()
        return {"id": f["id"], "name": f.get("name", ""), "url": f.get("webViewLink", "")}

    @staticmethod
    def extract_drive_id(value: str) -> str:
        value = (value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{15,}", value):
            return value
        for pattern in (r"/d/([A-Za-z0-9_-]+)", r"[?&]id=([A-Za-z0-9_-]+)"):
            m = re.search(pattern, value)
            if m:
                return m.group(1)
        raise ValueError("Could not extract Google Drive file ID")

    @staticmethod
    def _col_letter(n: int) -> str:
        result = ""
        while n:
            n, r = divmod(n - 1, 26)
            result = chr(65 + r) + result
        return result
