"""Тесты кэша байтов аватаров."""

from app.services.avatar_image_cache import (
    get_cached_avatar,
    invalidate_link_avatar_cache,
    put_cached_avatar,
)


def test_put_and_get_avatar_bytes():
    put_cached_avatar("lid1", "https://cdn.example/a.jpg", b"abc", "image/jpeg")
    row = get_cached_avatar("lid1", "https://cdn.example/a.jpg")
    assert row is not None
    assert row.content == b"abc"
    assert row.media_type == "image/jpeg"
    assert row.etag


def test_invalidate_by_link_id():
    put_cached_avatar("lid2", "https://cdn.example/b.jpg", b"xyz", "image/png")
    invalidate_link_avatar_cache("lid2")
    assert get_cached_avatar("lid2", "https://cdn.example/b.jpg") is None
