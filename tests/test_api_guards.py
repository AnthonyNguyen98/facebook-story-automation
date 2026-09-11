from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main_module
from app.android_state import ClaimMeta, note_with_claim
from app.main import (
    _claim_token,
    _device_id,
    _job_payload,
    _require_android,
    _verify_current_claim,
)
from app.settings import settings


READY = "ANDROID_READY:https://drive.google.com/file/d/abc123456789012/view"
DEVICE = "android-device-01"
CLAIM_TOKEN = "C" * 32


class DummyJob:
    job_id = "JOB-001"
    scheduled_at = None
    content_type = "TEXT"
    link_url = "https://tuyendung.megas.vn/?ref=RE3ZHC"
    link_text = "Apply qua đây"
    music_mode = "NONE"


def test_android_api_rejects_non_android_transport(monkeypatch):
    monkeypatch.setattr(settings, "publish_transport", "BROWSER")
    monkeypatch.setattr(settings, "android_api_token", "A" * 40)
    with pytest.raises(HTTPException) as exc:
        _require_android("Bearer " + "A" * 40)
    assert exc.value.status_code == 503
    assert exc.value.detail == "ANDROID_TRANSPORT_DISABLED"


def test_android_api_rejects_missing_or_short_server_secret(monkeypatch):
    monkeypatch.setattr(settings, "publish_transport", "ANDROID")
    monkeypatch.setattr(settings, "android_api_token", "short")
    with pytest.raises(HTTPException) as exc:
        _require_android("Bearer short")
    assert exc.value.status_code == 503
    assert exc.value.detail == "ANDROID_API_TOKEN_NOT_CONFIGURED"


def test_android_api_rejects_wrong_bearer(monkeypatch):
    secret = "S" * 40
    monkeypatch.setattr(settings, "publish_transport", "ANDROID")
    monkeypatch.setattr(settings, "android_api_token", secret)
    with pytest.raises(HTTPException) as exc:
        _require_android("Bearer " + "X" * 40)
    assert exc.value.status_code == 401
    assert exc.value.detail == "ANDROID_UNAUTHORIZED"


def test_android_api_accepts_exact_bearer(monkeypatch):
    secret = "S" * 40
    monkeypatch.setattr(settings, "publish_transport", "ANDROID")
    monkeypatch.setattr(settings, "android_api_token", secret)
    assert _require_android("Bearer " + secret) is None


@pytest.mark.parametrize("bad", [None, "", "short", "spaces are bad", "../escape"])
def test_device_id_rejects_invalid_values(bad):
    with pytest.raises(HTTPException) as exc:
        _device_id(bad)
    assert exc.value.status_code == 400


def test_claim_token_rejects_invalid_values():
    with pytest.raises(HTTPException) as exc:
        _claim_token("tiny")
    assert exc.value.status_code == 400


def test_job_payload_never_allows_publish_in_pilot(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "android_pilot_safe_mode", True)
    payload = _job_payload(DummyJob())
    assert payload["publish_allowed"] is False
    assert payload["pilot_safe_mode"] is True


def test_job_payload_requires_both_safety_switches_off_before_publish_flag(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "android_pilot_safe_mode", False)
    payload = _job_payload(DummyJob())
    assert payload["publish_allowed"] is True


def expired_claim_job():
    claim = ClaimMeta(DEVICE, CLAIM_TOKEN, 1_000)
    return SimpleNamespace(status="PROCESSING", note=note_with_claim(READY, claim))


def test_expired_claim_cannot_download_or_report_success(monkeypatch):
    monkeypatch.setattr(main_module, "now_epoch", lambda: 1_001)
    with pytest.raises(HTTPException) as exc:
        _verify_current_claim(expired_claim_job(), DEVICE, CLAIM_TOKEN)
    assert exc.value.status_code == 409
    assert exc.value.detail == "CLAIM_LEASE_EXPIRED"


def test_expired_claim_owner_can_release_for_recovery(monkeypatch):
    monkeypatch.setattr(main_module, "now_epoch", lambda: 1_001)
    claim = _verify_current_claim(
        expired_claim_job(),
        DEVICE,
        CLAIM_TOKEN,
        allow_expired=True,
    )
    assert claim.device_id == DEVICE
    assert claim.claim_token == CLAIM_TOKEN


def test_expired_claim_wrong_device_still_cannot_release(monkeypatch):
    monkeypatch.setattr(main_module, "now_epoch", lambda: 1_001)
    with pytest.raises(HTTPException) as exc:
        _verify_current_claim(
            expired_claim_job(),
            "android-other-02",
            CLAIM_TOKEN,
            allow_expired=True,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "CLAIM_OWNERSHIP_MISMATCH"


def test_expired_claim_wrong_token_still_cannot_release(monkeypatch):
    monkeypatch.setattr(main_module, "now_epoch", lambda: 1_001)
    with pytest.raises(HTTPException) as exc:
        _verify_current_claim(
            expired_claim_job(),
            DEVICE,
            "X" * 32,
            allow_expired=True,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "CLAIM_OWNERSHIP_MISMATCH"
