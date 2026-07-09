"""In-memory rate limit для GET /r/{slug} по IP клиента."""

from __future__ import annotations

from app.services.rate_limit import allow_request


def allow_redirect(ip: str | None, *, limit_per_minute: int) -> bool:
    return allow_request(ip, limit_per_minute=limit_per_minute, bucket="redirect")
