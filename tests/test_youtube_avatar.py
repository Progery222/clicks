"""Парсинг аватара YouTube из HTML канала."""

from app.services.account_avatar import (
    _normalize_youtube_profile_url,
    extract_youtube_avatar_from_html,
)


def test_normalize_youtube_profile_url():
    assert _normalize_youtube_profile_url("https://www.youtube.com/@phil.report") == (
        "https://www.youtube.com/@phil.report"
    )
    assert _normalize_youtube_profile_url("https://www.youtube.com/channel/UCxyz1234567890") == (
        "https://www.youtube.com/channel/UCxyz1234567890"
    )
    assert _normalize_youtube_profile_url("https://example.com/@x") is None


def test_extract_from_og_image_late_in_html():
    cdn = "https://yt3.googleusercontent.com/abc=s900-c-k-c0x00ffffff-no-rj"
    padding = "x" * 650_000
    html = (
        f"{padding}<meta property=\"og:image\" content=\"{cdn}\">"
        f'"avatar":{{"thumbnails":[{{"url":"{cdn}/fallback"}}]}}'
    )
    assert extract_youtube_avatar_from_html(html) == cdn


def test_extract_from_avatar_json():
    cdn = "https://yt3.googleusercontent.com/avatar-thumb=s88-c-k-no-rj"
    html = f'{{"avatar":{{"thumbnails":[{{"url":"{cdn}"}}]}}}}'
    assert extract_youtube_avatar_from_html(html) == cdn


def test_extract_returns_none_without_avatar():
    assert extract_youtube_avatar_from_html("<html><body>empty</body></html>") is None
