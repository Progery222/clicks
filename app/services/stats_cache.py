"""In-memory кэш тяжёлых агрегатов статистики."""

from __future__ import annotations

import time
import uuid
from datetime import datetime

_DASHBOARD_COUNTS_TTL_SEC = 30.0
_PERIOD_COUNTS_TTL_SEC = 25.0
_SIDEBAR_COUNTS_TTL_SEC = 60.0
_EARLIEST_LINK_TTL_SEC = 300.0

_dashboard_counts_cache: tuple[float, dict[uuid.UUID, tuple[int, int]]] | None = None
_period_counts_cache: dict[tuple, tuple[float, dict[uuid.UUID, tuple[int, int]]]] = {}
_sidebar_counts_cache: tuple[float, tuple[dict[str, int], dict[str, int]]] | None = None
_earliest_link_cache: tuple[float, datetime | None] | None = None


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
    _dashboard_counts_cache = (time.monotonic(), dict(data))


def bump_dashboard_counts_on_click(link_id: uuid.UUID) -> None:
    """Инкремент в кэше вместо полного пересчёта по таблице clicks."""
    global _dashboard_counts_cache
    if _dashboard_counts_cache is None:
        return
    ts, data = _dashboard_counts_cache
    if time.monotonic() - ts > _DASHBOARD_COUNTS_TTL_SEC:
        return
    total, today = data.get(link_id, (0, 0))
    data[link_id] = (total + 1, today + 1)
    _dashboard_counts_cache = (ts, data)


def invalidate_dashboard_counts_cache() -> None:
    global _dashboard_counts_cache
    _dashboard_counts_cache = None
    _period_counts_cache.clear()


def _period_key(
    link_ids: list[uuid.UUID], start: datetime, end: datetime
) -> tuple[frozenset[uuid.UUID], str, str]:
    return (frozenset(link_ids), start.isoformat(), end.isoformat())


def get_cached_period_counts(
    link_ids: list[uuid.UUID], start: datetime, end: datetime
) -> dict[uuid.UUID, tuple[int, int]] | None:
    key = _period_key(link_ids, start, end)
    row = _period_counts_cache.get(key)
    if row is None:
        return None
    ts, data = row
    if time.monotonic() - ts > _PERIOD_COUNTS_TTL_SEC:
        _period_counts_cache.pop(key, None)
        return None
    return data


def set_cached_period_counts(
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    data: dict[uuid.UUID, tuple[int, int]],
) -> None:
    key = _period_key(link_ids, start, end)
    _period_counts_cache[key] = (time.monotonic(), dict(data))
    if len(_period_counts_cache) > 32:
        oldest = min(_period_counts_cache.items(), key=lambda item: item[1][0])
        _period_counts_cache.pop(oldest[0], None)


def get_cached_sidebar_counts() -> tuple[dict[str, int], dict[str, int]] | None:
    global _sidebar_counts_cache
    if _sidebar_counts_cache is None:
        return None
    ts, data = _sidebar_counts_cache
    if time.monotonic() - ts > _SIDEBAR_COUNTS_TTL_SEC:
        return None
    return data


def set_cached_sidebar_counts(
    profile_counts: dict[str, int], platform_counts: dict[str, int]
) -> None:
    global _sidebar_counts_cache
    _sidebar_counts_cache = (
        time.monotonic(),
        (dict(profile_counts), dict(platform_counts)),
    )


def invalidate_sidebar_counts_cache() -> None:
    global _sidebar_counts_cache
    _sidebar_counts_cache = None


def try_get_cached_earliest_link() -> tuple[bool, datetime | None]:
    global _earliest_link_cache
    if _earliest_link_cache is None:
        return False, None
    ts, val = _earliest_link_cache
    if time.monotonic() - ts > _EARLIEST_LINK_TTL_SEC:
        return False, None
    return True, val


def set_cached_earliest_link(value: datetime | None) -> None:
    global _earliest_link_cache
    _earliest_link_cache = (time.monotonic(), value)
