"""In-memory rate limit по IP (общий для /r/ и /api/v1)."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def allow_request(ip: str | None, *, limit_per_minute: int, bucket: str = "default") -> bool:
    """True — разрешить запрос; False — лимит превышен."""
    if limit_per_minute <= 0:
        return True
    key = f"{bucket}:{(ip or '').strip() or 'unknown'}"
    now = time.time()
    window = 60.0
    with _lock:
        hits = [t for t in _buckets[key] if t > now - window]
        if len(hits) >= limit_per_minute:
            _buckets[key] = hits
            return False
        hits.append(now)
        _buckets[key] = hits
        return True
