from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spreadsheet_id: str = ""
    timezone: str = "Asia/Ho_Chi_Minh"
    poll_seconds: int = 20
    dry_run: bool = True

    # Android is the only supported publishing transport. Railway must never open Facebook.
    publish_transport: str = "ANDROID"

    # Android companion API. Token lives only in Railway + the phone.
    android_api_token: str = ""
    android_claim_lease_sec: int = 900
    android_max_media_bytes: int = 262_144_000

    # Google auth. AUTO prefers OAuth, then falls back to service account.
    google_auth_mode: str = "AUTO"
    google_oauth_credentials_json: str = "{}"
    google_service_account_json: str = "{}"

    work_dir: str = "/tmp/facebook-story-worker"


settings = Settings()
