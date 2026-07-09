"""Короткий in-memory кэш для тяжёлых агрегатов статистики."""

from __future__ import annotations

import time
import uuid
from typing import Any

_DASHBOARD_COUNTS_TTL_SEC = 15.0
_dashboard_counts_cache: tuple[float, dict[uuid.UUID, tuple[int, int]]] | None = None


def get_cached_dashboard_counts() -> dict[uuid.UUID, tuple[int, int]] | None:
    global _dashboard_counts_cache
    if _dashboard_counts_cache is None:
        return None
    ts, data = _dashboard_counts_cache
    if time.monotonic() - ts > _DASHBOARD_COUNTS_TTL_SEC:
        return None
    return data


def set_cached_dashboard_counts(data: dict[uuid.UUID, tuple[int, int]]) -> None:
    global _dashboard_counts_cache
    _dashboard_counts_cache = (time.monotonic(), data)


def invalidate_dashboard_counts_cache() -> None:
    global _dashboard_counts_cache
    _dashboard_counts_cache = None
