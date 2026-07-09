"""Безопасные исходящие HTTP GET с проверкой каждого редиректа."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from app.url_validation import _MAX_FETCH_REDIRECTS, is_safe_fetch_url


def create_safe_http_client(**kwargs: object) -> httpx.AsyncClient:
    """Клиент без автоматических редиректов — только через safe_get."""
    opts = dict(kwargs)
    opts.setdefault("follow_redirects", False)
    return httpx.AsyncClient(**opts)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = _MAX_FETCH_REDIRECTS,
    **kwargs: object,
) -> httpx.Response:
    current = (url or "").strip()
    if not is_safe_fetch_url(current):
        raise ValueError(f"unsafe fetch URL: {current[:120]}")

    for _ in range(max_redirects + 1):
        response = await client.get(current, **kwargs)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(current, location.strip())
        if not is_safe_fetch_url(current):
            raise ValueError(f"unsafe redirect target: {current[:120]}")
    raise ValueError("too many redirects")
