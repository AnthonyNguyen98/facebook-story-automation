from __future__ import annotations

import random

from .models import MusicTrack
from .num import as_float

POOLS = ["ENERGETIC", "YOUTH", "FUN", "EVENT", "INSPIRATIONAL", "CORPORATE", "CHILL"]


def weighted_pool(config: dict[str, str]) -> str:
    weights = []
    for pool in POOLS:
        try:
            w = as_float(config.get(f"POOL_WEIGHT_{pool}", "0"), 0.0)
        except ValueError:
            w = 0
        weights.append(max(0.0, w))
    if not any(weights):
        return "ENERGETIC"
    return random.choices(POOLS, weights=weights, k=1)[0]


def choose_track(catalog: list[MusicTrack], requested_pool: str, recent_ids: set[str], config: dict[str, str]) -> MusicTrack:
    pool = requested_pool if requested_pool in POOLS else weighted_pool(config)
    approved = [
        t for t in catalog
        if t.approved and t.license_status == "APPROVED" and t.source.upper() == "META_SOUND_COLLECTION"
        and pool in {t.pool_primary, t.pool_secondary}
    ]
    if not approved:
        raise RuntimeError(f"NO_APPROVED_MUSIC_TRACK:{pool}")
    fresh = [t for t in approved if t.track_id not in recent_ids]
    choices = fresh or approved
    min_uses = min(t.use_count for t in choices)
    shortlist = [t for t in choices if t.use_count <= min_uses + 1]
    return random.choice(shortlist)
