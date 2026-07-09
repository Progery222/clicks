"""Тесты безопасных URL и dedupe."""

from datetime import date

from app.services.dedupe import fingerprint_fallback
from app.url_validation import is_safe_fetch_url


def test_safe_fetch_rejects_private_hosts():
    assert not is_safe_fetch_url("http://127.0.0.1/a.jpg")
    assert not is_safe_fetch_url("http://169.254.169.254/latest/meta-data/")


def test_safe_fetch_accepts_public_cdn():
    assert is_safe_fetch_url("https://cdn.example.com/avatar.jpg")


def test_fingerprint_fallback_stable_per_day():
    a = fingerprint_fallback("1.2.3.4", "Mozilla/5.0", date(2026, 1, 1))
    b = fingerprint_fallback("1.2.3.4", "Mozilla/5.0", date(2026, 1, 1))
    c = fingerprint_fallback("1.2.3.4", "Mozilla/5.0", date(2026, 1, 2))
    assert a == b
    assert a != c
    assert a.startswith("f:")
