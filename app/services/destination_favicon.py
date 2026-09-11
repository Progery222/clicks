"""Favicon домена цели: с сайта, иначе внешние CDN (без Google-заглушки-глобуса)."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from html import unescape
from threading import Lock
from urllib.parse import urljoin, urlparse

import httpx

from app.safe_http import create_safe_http_client, safe_get
from app.url_validation import is_safe_fetch_url

log = logging.getLogger(__name__)

_ICON_RE = re.compile(
    r"""<link[^>]+rel=["'][^"']*(?:icon|shortcut icon|apple-touch-icon)[^"']*["'][^>]*>""",
    re.I,
)
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)

_MAX_BYTES = 512_000
_TTL_SEC = 7 * 24 * 3600
_MAX_ENTRIES = 500


@dataclass(frozen=True)
class CachedFavicon:
    content: bytes
    media_type: str
    etag: str
    stored_at: float


_lock = Lock()
_store: dict[str, CachedFavicon] = {}


def _etag(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:32]


def _get_cached(host: str) -> CachedFavicon | None:
    now = time.time()
    with _lock:
        row = _store.get(host)
        if row is None:
            return None
        if now - row.stored_at > _TTL_SEC:
            _store.pop(host, None)
            return None
        return row


def _put_cached(host: str, content: bytes, media_type: str) -> CachedFavicon:
    row = CachedFavicon(
        content=content,
        media_type=media_type,
        etag=_etag(content),
        stored_at=time.time(),
    )
    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            oldest = min(_store, key=lambda k: _store[k].stored_at)
            _store.pop(oldest, None)
        _store[host] = row
    return row


def _is_image_response(resp: httpx.Response) -> bool:
    if resp.status_code != 200 or not resp.content:
        return False
    if len(resp.content) < 64 or len(resp.content) > _MAX_BYTES:
        return False
    ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        return True
    # favicon.ico иногда отдаётся как octet-stream
    head = resp.content[:16]
    if head.startswith(b"\x00\x00\x01\x00") or head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"):
        return True
    if head[:6] in (b"GIF87a", b"GIF89a") or head.startswith(b"RIFF"):
        return True
    return False


def _media_type(resp: httpx.Response) -> str:
    ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        return ct
    head = resp.content[:16]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head.startswith(b"RIFF"):
        return "image/webp"
    return "image/x-icon"


def _icon_hrefs_from_html(html: str, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in _ICON_RE.findall(html or ""):
        m = _HREF_RE.search(tag)
        if not m:
            continue
        href = unescape(m.group(1).strip())
        if not href or href.startswith("data:"):
            continue
        abs_url = urljoin(base_url, href)
        if is_safe_fetch_url(abs_url):
            out.append(abs_url)
    return out


async def _try_get(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    if not is_safe_fetch_url(url):
        return None
    try:
        resp = await safe_get(
            client,
            url,
            timeout=8.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BioLinksFavicon/1.0)"},
        )
    except Exception:
        return None
    if not _is_image_response(resp):
        return None
    return resp.content, _media_type(resp)


async def resolve_destination_favicon(host: str) -> CachedFavicon | None:
    """Скачать favicon домена; кэш в памяти."""
    host = (host or "").strip().lower().removeprefix("www.")
    if not host or "/" in host or " " in host:
        return None
    hit = _get_cached(host)
    if hit is not None:
        return hit

    origins = [f"https://{host}/", f"https://www.{host}/"]
    # PNG/SVG раньше .ico — браузеры стабильнее показывают растр
    static_paths = (
        "apple-touch-icon.png",
        "apple-touch-icon-precomposed.png",
        "favicon.png",
        "favicon.svg",
        "favicon.ico",
    )
    external = [
        f"https://icons.duckduckgo.com/ip3/{host}.ico",
        f"https://icon.horse/icon/{host}",
    ]
    preferred = ("image/png", "image/svg+xml", "image/jpeg", "image/webp")

    async with create_safe_http_client(timeout=10.0) as client:
        best_ico: tuple[bytes, str] | None = None

        def _keep(got: tuple[bytes, str]) -> CachedFavicon | None:
            nonlocal best_ico
            if got[1] in preferred:
                return _put_cached(host, got[0], got[1])
            if best_ico is None:
                best_ico = got
            return None

        for origin in origins:
            try:
                page = await safe_get(
                    client,
                    origin,
                    timeout=8.0,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; BioLinksFavicon/1.0)"},
                )
                if page.status_code == 200 and page.text:
                    for href in _icon_hrefs_from_html(page.text[:200_000], str(page.url)):
                        got = await _try_get(client, href)
                        if got:
                            done = _keep(got)
                            if done:
                                return done
            except Exception as exc:
                log.debug("favicon html fetch failed for %s: %s", host, exc)

            for path in static_paths:
                got = await _try_get(client, urljoin(origin, path))
                if got:
                    done = _keep(got)
                    if done:
                        return done

        if best_ico:
            return _put_cached(host, best_ico[0], best_ico[1])

        for url in external:
            got = await _try_get(client, url)
            if got:
                return _put_cached(host, got[0], got[1])

    return None


def destination_favicon_href(host: str) -> str:
    from urllib.parse import quote

    return f"/admin/api/destination-favicon?host={quote(host)}"


def destination_client_fallbacks(host: str) -> list[str]:
    """Запасные URL для <img onError>, если прокси не отдал картинку."""
    h = (host or "").strip().lower().removeprefix("www.")
    if not h:
        return []
    return [
        f"https://icons.duckduckgo.com/ip3/{h}.ico",
        f"https://icon.horse/icon/{h}",
    ]
