from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

READY_PREFIXES = ("ANDROID_READY:", "READY:")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,80}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,160}$")


@dataclass(frozen=True)
class ClaimMeta:
    device_id: str
    claim_token: str
    lease_until_epoch: int

    def active(self, now_epoch: int) -> bool:
        return self.lease_until_epoch > now_epoch


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def valid_device_id(value: str) -> bool:
    return bool(DEVICE_ID_RE.fullmatch((value or "").strip()))


def valid_claim_token(value: str) -> bool:
    return bool(TOKEN_RE.fullmatch((value or "").strip()))


def ready_base(note: str) -> str:
    first = (note or "").split(" | ", 1)[0].strip()
    return first if any(first.startswith(p) for p in READY_PREFIXES) else ""


def ready_url(note: str) -> str:
    base = ready_base(note)
    for prefix in READY_PREFIXES:
        if base.startswith(prefix):
            return base[len(prefix):].strip()
    return ""


def has_marker(note: str, marker: str) -> bool:
    return any(part.strip() == marker for part in (note or "").split(" | "))


def parse_claim(note: str) -> ClaimMeta | None:
    values: dict[str, str] = {}
    for part in (note or "").split(" | ")[1:]:
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()
    device = values.get("CLAIM_DEVICE", "")
    token = values.get("CLAIM_TOKEN", "")
    lease = values.get("LEASE_UNTIL", "")
    if not valid_device_id(device) or not valid_claim_token(token):
        return None
    try:
        lease_epoch = int(lease)
    except (TypeError, ValueError):
        return None
    return ClaimMeta(device, token, lease_epoch)


def make_claim(note: str, device_id: str, lease_seconds: int, now: int | None = None) -> ClaimMeta:
    if not valid_device_id(device_id):
        raise ValueError("INVALID_DEVICE_ID")
    if lease_seconds < 60 or lease_seconds > 3600:
        raise ValueError("INVALID_LEASE_SECONDS")
    current = now_epoch() if now is None else int(now)
    return ClaimMeta(device_id, secrets.token_urlsafe(32), current + lease_seconds)


def note_with_claim(note: str, claim: ClaimMeta) -> str:
    base = ready_base(note)
    if not base:
        raise ValueError("READY_MEDIA_MISSING")
    return (
        f"{base} | CLAIM_DEVICE={claim.device_id} | CLAIM_TOKEN={claim.claim_token} "
        f"| LEASE_UNTIL={claim.lease_until_epoch}"
    )


def note_with_marker(note: str, marker: str) -> str:
    base = ready_base(note)
    if not base:
        raise ValueError("READY_MEDIA_MISSING")
    return f"{base} | {marker}"


def transition_decision(current_status: str, requested_state: str, dry_run: bool) -> str:
    current = (current_status or "").strip().upper()
    state = (requested_state or "").strip().upper()

    if current == "PUBLISHED":
        if state == "PUBLISHED":
            return "IDEMPOTENT_PUBLISHED"
        raise ValueError("PUBLISHED_IS_TERMINAL")

    if current != "PROCESSING":
        raise ValueError(f"RESULT_REQUIRES_PROCESSING:{current}")

    if state == "PUBLISHED":
        if dry_run:
            raise ValueError("PUBLISH_DISABLED_BY_DRY_RUN")
        return "PUBLISHED"
    if state in {"DRY_RUN_READY", "READY_TO_PUBLISH"}:
        return "DRY_RUN_OK"
    if state in {"FAILED", "RELEASE"}:
        return "RELEASE"
    raise ValueError("INVALID_ANDROID_RESULT_STATE")
