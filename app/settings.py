from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spreadsheet_id: str = ""
    timezone: str = "Asia/Ho_Chi_Minh"
    poll_seconds: int = 20
    dry_run: bool = True

    google_service_account_json: str = "{}"

    meta_business_url: str = "https://business.facebook.com/latest/home"
    meta_storage_state_path: str = "/data/meta_storage_state.json"
    meta_storage_state_b64: str = ""
    strict_link_text: bool = True
    headless: bool = True

    work_dir: str = "/tmp/facebook-story-worker"
    session_dir: str = "/data"


settings = Settings()
