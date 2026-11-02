"""Pure helpers for tags and time values (no framework or audio-library imports)."""

import math

MAX_TAGS = 20
MAX_TAG_LENGTH = 32


def normalize_tags(raw: str) -> str:
    """'Rock, 80s ,rock' -> '80s,rock' order-preserving, lower-cased, de-duplicated."""
    seen: list[str] = []
    for part in raw.split(","):
        tag = " ".join(part.split()).lower()[:MAX_TAG_LENGTH]
        if tag and tag not in seen:
            seen.append(tag)
    return ",".join(seen[:MAX_TAGS])


def parse_time_ms(text: str) -> int | None:
    """Parse '75', '75.5', '1:15' or '1:15.5' into milliseconds. Blank -> None."""
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("use seconds, m:ss or h:mm:ss")
    total = 0.0
    try:
        for part in parts:
            value = float(part)
            if value < 0:
                raise ValueError
            total = total * 60 + value
    except ValueError:
        raise ValueError("use seconds, m:ss or h:mm:ss") from None
    if not math.isfinite(total):
        raise ValueError("use seconds, m:ss or h:mm:ss")
    return round(total * 1000)


def format_time_ms(ms: int | None) -> str:
    """90000 -> '1:30.0'. None -> ''."""
    if ms is None:
        return ""
    minutes, tenths = divmod(round(ms / 100), 600)
    return f"{minutes}:{tenths / 10:04.1f}"
