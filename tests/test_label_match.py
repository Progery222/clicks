"""Тесты нормализации URL аккаунта для resolve-clicks."""

from app.services.label_match import account_label_display, normalize_account_label


def test_tiktok_trailing_slash_and_www():
    a = normalize_account_label("https://www.tiktok.com/@User/")
    b = normalize_account_label("https://tiktok.com/@user")
    assert a == b == "tiktok:@user"


def test_instagram_case():
    a = normalize_account_label("https://www.instagram.com/Phil.Redpill/")
    b = normalize_account_label("HTTPS://INSTAGRAM.COM/phil.redpill")
    assert a == b == "instagram:phil.redpill"


def test_facebook_profile_php():
    a = normalize_account_label("https://www.facebook.com/profile.php?id=123456789012")
    b = normalize_account_label("https://facebook.com/123456789012")
    assert a == b == "facebook:id:123456789012"


def test_account_label_display_urls():
    assert account_label_display("https://www.instagram.com/Phil.Redpill/") == "phil.redpill"
    assert account_label_display("https://www.tiktok.com/@User/") == "@user"
    assert account_label_display("https://www.facebook.com/profile.php?id=123456789012") == "123456789012"
    assert account_label_display("@plain_handle") == "plain_handle"
