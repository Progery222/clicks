"""Тесты кэша счётчиков."""

import uuid

from app.services.stats_cache import (
    bump_dashboard_counts_on_click,
    get_cached_dashboard_counts,
    invalidate_dashboard_counts_cache,
    set_cached_dashboard_counts,
)


def test_bump_dashboard_counts_increments_without_full_invalidate():
    invalidate_dashboard_counts_cache()
    lid = uuid.uuid4()
    set_cached_dashboard_counts({lid: (10, 3)})
    bump_dashboard_counts_on_click(lid)
    cached = get_cached_dashboard_counts()
    assert cached is not None
    assert cached[lid] == (11, 4)


def test_bump_skips_when_cache_cold():
    invalidate_dashboard_counts_cache()
    bump_dashboard_counts_on_click(uuid.uuid4())
