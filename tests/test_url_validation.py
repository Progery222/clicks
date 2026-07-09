"""Тесты валидации целевых URL."""

from app.url_validation import is_valid_destination_url, safe_redirect_location


def test_rejects_crlf_and_private_hosts():
    assert not is_valid_destination_url("https://evil.com/\r\nX-Injected: 1")
    assert not is_valid_destination_url("http://127.0.0.1/path")
    assert not is_valid_destination_url("http://localhost/test")


def test_accepts_public_https():
    assert is_valid_destination_url("https://example.com/path?q=1")
    assert safe_redirect_location("https://example.com/x") == "https://example.com/x"


def test_private_allowed_when_flag_set():
    assert is_valid_destination_url("http://127.0.0.1/x", allow_private_hosts=True)
