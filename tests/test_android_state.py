from types import SimpleNamespace

import pytest

from app.android_state import (
    ClaimMeta,
    has_marker,
    make_claim,
    note_with_claim,
    note_with_marker,
    parse_claim,
    ready_base,
    ready_url,
    transition_decision,
    valid_claim_token,
    valid_device_id,
)
from app.num import as_float, as_int
from app.runner import _stable_job_id


READY = "ANDROID_READY:https://drive.google.com/file/d/abc123456789012/view"


def test_ready_url_only_reads_first_ready_segment():
    note = READY + " | ANDROID_RETRY_READY | CLAIM_DEVICE=android-device-01"
    assert ready_base(note) == READY
    assert ready_url(note) == "https://drive.google.com/file/d/abc123456789012/view"


def test_non_ready_note_has_no_media_url():
    assert ready_base("hello") == ""
    assert ready_url("hello | ANDROID_READY:https://evil.example") == ""


def test_marker_matching_is_exact_not_substring():
    note = READY + " | ANDROID_DRY_RUN_OK"
    assert has_marker(note, "ANDROID_DRY_RUN_OK")
    assert not has_marker(note, "DRY_RUN")
    assert not has_marker(note, "ANDROID_DRY_RUN")


def test_device_and_claim_token_validation():
    assert valid_device_id("android-12345678")
    assert not valid_device_id("short")
    assert not valid_device_id("android bad spaces")
    assert valid_claim_token("A" * 20)
    assert not valid_claim_token("tiny")
    assert not valid_claim_token("A" * 19 + "!")


def test_claim_round_trip_and_lease_boundary():
    claim = make_claim(READY, "android-device-01", 120, now=1_000)
    note = note_with_claim(READY, claim)
    parsed = parse_claim(note)
    assert parsed == claim
    assert parsed.active(1_119)
    assert not parsed.active(1_120)


def test_make_claim_requires_ready_media():
    with pytest.raises(ValueError, match="READY_MEDIA_MISSING"):
        make_claim("", "android-device-01", 120, now=1_000)


def test_make_claim_rejects_unsafe_lease_lengths():
    with pytest.raises(ValueError, match="INVALID_LEASE_SECONDS"):
        make_claim(READY, "android-device-01", 59, now=1_000)
    with pytest.raises(ValueError, match="INVALID_LEASE_SECONDS"):
        make_claim(READY, "android-device-01", 3_601, now=1_000)


def test_parse_claim_rejects_malformed_claim():
    assert parse_claim(READY + " | CLAIM_DEVICE=x | CLAIM_TOKEN=bad | LEASE_UNTIL=nope") is None


def test_marker_builder_rejects_structural_injection():
    with pytest.raises(ValueError, match="INVALID_MARKER"):
        note_with_marker(READY, "OK | CLAIM_TOKEN=oops")
    with pytest.raises(ValueError, match="INVALID_MARKER"):
        note_with_marker(READY, "CLAIM_TOKEN=oops")


def test_publish_is_blocked_in_dry_run():
    with pytest.raises(ValueError, match="PUBLISH_DISABLED_BY_DRY_RUN"):
        transition_decision("PROCESSING", "PUBLISHED", True)


def test_publish_only_allowed_from_processing_when_safety_off():
    assert transition_decision("PROCESSING", "PUBLISHED", False) == "PUBLISHED"
    with pytest.raises(ValueError, match="RESULT_REQUIRES_PROCESSING"):
        transition_decision("VALIDATED", "PUBLISHED", False)


def test_dry_run_and_release_transitions():
    assert transition_decision("PROCESSING", "DRY_RUN_READY", True) == "DRY_RUN_OK"
    assert transition_decision("PROCESSING", "READY_TO_PUBLISH", True) == "DRY_RUN_OK"
    assert transition_decision("PROCESSING", "RELEASE", True) == "RELEASE"
    assert transition_decision("PROCESSING", "FAILED", True) == "RELEASE"


def test_unknown_result_state_is_rejected():
    with pytest.raises(ValueError, match="INVALID_ANDROID_RESULT_STATE"):
        transition_decision("PROCESSING", "CLICK_SOMETHING", True)


def test_published_is_terminal_except_idempotent_publish():
    assert transition_decision("PUBLISHED", "PUBLISHED", False) == "IDEMPOTENT_PUBLISHED"
    with pytest.raises(ValueError, match="PUBLISHED_IS_TERMINAL"):
        transition_decision("PUBLISHED", "RELEASE", False)


def test_vi_number_parsing_regression():
    assert as_float("0,5") == 0.5
    assert as_float("1.234,5") == 1234.5
    assert as_int("1.200") == 1  # a dot-only value is decimal syntax, not vi thousands formatting


def test_stable_auto_job_id_is_deterministic():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    job = SimpleNamespace(
        job_id="",
        row=42,
        scheduled_at=datetime(2026, 9, 11, 10, 47, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
    )
    assert _stable_job_id(job) == "AUTO-20260911-1047-R42"
    assert _stable_job_id(job) == "AUTO-20260911-1047-R42"


def test_existing_job_id_is_never_rewritten():
    job = SimpleNamespace(job_id="CUSTOM-001", row=42, scheduled_at=None)
    assert _stable_job_id(job) == "CUSTOM-001"
