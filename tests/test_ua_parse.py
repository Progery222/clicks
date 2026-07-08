"""Тесты разбора User-Agent."""

from app.services.ua_parse import parse_device_type, parse_os


def test_os_bot_linux_chromeos_are_other():
    assert parse_os("Mozilla/5.0 (compatible; Googlebot/2.1)") == "Другое"
    assert parse_os("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36") == "Другое"
    assert parse_os(
        "Mozilla/5.0 (X11; CrOS x86_64) AppleWebKit/537.36 Chrome/120.0.0.0"
    ) == "Другое"


def test_os_keeps_main_platforms():
    assert parse_os("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "iOS"
    assert parse_os("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "Windows"


def test_device_type_only_mobile_or_desktop():
    assert parse_device_type("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "Мобильный"
    assert parse_device_type("Mozilla/5.0 (compatible; Googlebot/2.1)") == "Десктоп"
    assert parse_device_type("Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0") == "Десктоп"
    assert parse_device_type(None) == "Десктоп"
