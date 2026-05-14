import hashlib
import uuid
from datetime import UTC, date


def fingerprint_fallback(ip: str | None, user_agent: str | None, day: date) -> str:
    raw = f"{ip or ''}|{user_agent or ''}|{day.isoformat()}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"f:{h}"


def dedupe_key_for_visitor(visitor: uuid.UUID) -> str:
    return f"v:{visitor}"


def parse_vid_cookie(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None
