from __future__ import annotations


def as_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return default
    if "," in s and "." in s:
        # vi-VN formatted number, e.g. 1.234,5
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def as_int(value, default: int = 0) -> int:
    return int(as_float(value, float(default)))
