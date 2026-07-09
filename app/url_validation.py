"""Валидация целевых URL и безопасный заголовок Location."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_MAX_URL_LEN = 2048
_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "metadata",
    "metadata.google.internal",
    "169.254.169.254",
})
_MAX_FETCH_REDIRECTS = 5


def is_valid_destination_url(url: str, *, allow_private_hosts: bool = False) -> bool:
    """http(s) URL без CRLF; по умолчанию без приватных/loopback адресов."""
    raw = (url or "").strip()
    if not raw or len(raw) > _MAX_URL_LEN:
        return False
    if any(ch in raw for ch in "\r\n\x00"):
        return False
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if not allow_private_hosts and host in _BLOCKED_HOSTS:
        return False
    if not allow_private_hosts:
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return False
        except ValueError:
            pass
    return True


def is_safe_fetch_url(url: str) -> bool:
    """Публичный http(s) URL для исходящих запросов сервера (аватары, og:image)."""
    return is_valid_destination_url(url, allow_private_hosts=False)


def safe_redirect_location(url: str, *, allow_private_hosts: bool = False) -> str:
    """Строка для заголовка Location (без CRLF)."""
    if not is_valid_destination_url(url, allow_private_hosts=allow_private_hosts):
        raise ValueError("invalid redirect URL")
    return url.strip().split("\r")[0].split("\n")[0]
