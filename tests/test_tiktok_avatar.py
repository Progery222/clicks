"""Парсинг аватара TikTok из HTML профиля."""

from app.services.account_avatar import (
    _normalize_tiktok_profile_url,
    extract_tiktok_avatar_from_html,
)


def test_normalize_tiktok_profile_url():
    assert _normalize_tiktok_profile_url("https://www.tiktok.com/@alice") == (
        "https://www.tiktok.com/@alice"
    )
    assert _normalize_tiktok_profile_url("https://m.tiktok.com/@bob?lang=en") == (
        "https://www.tiktok.com/@bob"
    )
    assert _normalize_tiktok_profile_url("https://www.tiktok.com/alice") == (
        "https://www.tiktok.com/@alice"
    )
    assert _normalize_tiktok_profile_url("https://example.com/@alice") is None


def test_extract_from_universal_data_script():
    cdn = "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-avt-0068/abc~tplv-tiktokx-cropcenter:1080:1080.jpeg"
    html = f"""
    <html><body>
    <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
    {{"__DEFAULT_SCOPE__":{{"webapp.user-detail":{{"userInfo":{{"user":{{"avatarLarger":"{cdn}"}}}}}}}}}}
    </script>
    </body></html>
    """
    assert extract_tiktok_avatar_from_html(html) == cdn


def test_extract_prefers_avatar_larger_over_medium():
    larger = "https://p16-sign-va.tiktokcdn.com/obj/larger.jpeg"
    medium = "https://p16-sign-va.tiktokcdn.com/obj/medium.jpeg"
    html = f'{{"avatarMedium":"{medium}","avatarLarger":"{larger}"}}'
    assert extract_tiktok_avatar_from_html(html) == larger


def test_extract_decodes_escaped_slashes():
    raw = "https:\\/\\/p16-sign-va.tiktokcdn.com\\/obj\\/pic.jpeg"
    html = f'{{"avatarLarger":"{raw}"}}'
    assert extract_tiktok_avatar_from_html(html) == (
        "https://p16-sign-va.tiktokcdn.com/obj/pic.jpeg"
    )


def test_extract_returns_none_for_shell_page():
    assert extract_tiktok_avatar_from_html("<html><body>blocked</body></html>") is None
