from __future__ import annotations

import random


def select_link_text(config: dict[str, str], recent: set[str], explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    candidates = [v.strip() for k, v in sorted(config.items()) if k.startswith("LINK_TEXT_") and k != "LINK_TEXT_MODE" and v.strip()]
    if not candidates:
        raise RuntimeError("No LINK_TEXT_* values are configured")
    fresh = [x for x in candidates if x not in recent]
    return random.choice(fresh or candidates)
