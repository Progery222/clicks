"""Прокси аватаров в админке: accountstats → кэш в links → HTTP (og:image / oEmbed)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link
from app.services.account_avatar import (
    AVATAR_MODE_AUTO,
    AVATAR_MODE_LETTER,
    AVATAR_MODE_PHOTO,
    AVATAR_MODE_PLATFORM,
    _FETCH_HEADERS,
    _fetch_photo_url,
    link_shows_avatar_image,
    platform_logo_url_for_link,
    resolve_account_avatar_url,
)
from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pic
from app.safe_http import create_safe_http_client, safe_get
from app.services.avatar_image_cache import (
    get_cached_avatar,
    invalidate_link_avatar_cache,
    put_cached_avatar,
)
from app.url_validation import is_safe_fetch_url

log = logging.getLogger(__name__)

_IMG_HEADERS = {
    **_FETCH_HEADERS,
    "Accept": "image/*,*/*;q=0.8",
}

_BROWSER_CACHE = "private, max-age=2592000, immutable"

_resolve_locks: dict[uuid.UUID, asyncio.Lock] = {}
_resolve_guard = asyncio.Lock()
_http_resolve_sem = asyncio.Semaphore(6)


def avatar_version(link: Link) -> int:
    if link.updated_at:
        return int(link.updated_at.timestamp())
    return 0


def admin_avatar_href(link: Link | uuid.UUID) -> str | None:
    if isinstance(link, Link):
        if not link_shows_avatar_image(link):
            return None
        return f"/admin/avatar/{link.id}?v={avatar_version(link)}"
    return f"/admin/avatar/{link}"


async def _lock_for(link_id: uuid.UUID) -> asyncio.Lock:
    async with _resolve_guard:
        if link_id not in _resolve_locks:
            _resolve_locks[link_id] = asyncio.Lock()
        return _resolve_locks[link_id]


async def resolve_and_cache_link_avatar(db: AsyncSession, link: Link) -> str | None:
    """Вернуть URL картинки с учётом режима отображения."""
    mode = link.account_avatar_mode or AVATAR_MODE_AUTO

    if mode == AVATAR_MODE_LETTER:
        return None

    if mode == AVATAR_MODE_PLATFORM:
        return platform_logo_url_for_link(link)

    if link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
        if mode == AVATAR_MODE_PHOTO or mode == AVATAR_MODE_AUTO:
            return link.account_avatar_url

    pic = await lookup_profile_pic(link.label, link.platform)
    if pic and not is_placeholder_avatar(pic):
        link.account_avatar_url = pic
        invalidate_link_avatar_cache(link.id)
        await db.commit()
        return pic

    if mode == AVATAR_MODE_PHOTO or mode == AVATAR_MODE_AUTO:
        lock = await _lock_for(link.id)
        async with lock:
            await db.refresh(link)
            if link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
                return link.account_avatar_url

            async with _http_resolve_sem:
                async with create_safe_http_client(
                    headers=_FETCH_HEADERS, timeout=15.0
                ) as client:
                    if mode == AVATAR_MODE_PHOTO:
                        pic = await _fetch_photo_url(link.label, link.platform, client)
                    else:
                        pic = await resolve_account_avatar_url(
                            link.label, link.platform, client
                        )

            if pic and pic != link.account_avatar_url:
                link.account_avatar_url = pic
                invalidate_link_avatar_cache(link.id)
                await db.commit()
            elif mode == AVATAR_MODE_AUTO:
                fallback = platform_logo_url_for_link(link)
                if fallback:
                    link.account_avatar_url = fallback
                    invalidate_link_avatar_cache(link.id)
                    await db.commit()
                    return fallback
            return pic

    return platform_logo_url_for_link(link)


def _avatar_response(cached, request: Request | None) -> Response:
    if request is not None:
        inm = (request.headers.get("if-none-match") or "").strip()
        if inm and inm.strip('"') == cached.etag:
            return Response(status_code=304, headers={"ETag": f'"{cached.etag}"', "Cache-Control": _BROWSER_CACHE})
    return Response(
        content=cached.content,
        media_type=cached.media_type,
        headers={
            "Cache-Control": _BROWSER_CACHE,
            "ETag": f'"{cached.etag}"',
        },
    )


async def stream_link_avatar(
    db: AsyncSession,
    link: Link,
    request: Request | None = None,
) -> Response:
    pic_url = await resolve_and_cache_link_avatar(db, link)
    if not pic_url:
        raise HTTPException(status_code=404, detail="avatar not found")
    if not is_safe_fetch_url(pic_url):
        raise HTTPException(status_code=404, detail="unsafe avatar URL")

    lid = str(link.id)
    cached = get_cached_avatar(lid, pic_url)
    if cached is not None:
        return _avatar_response(cached, request)

    async with create_safe_http_client(headers=_IMG_HEADERS, timeout=20.0) as client:
        try:
            r = await safe_get(client, pic_url)
        except ValueError:
            raise HTTPException(status_code=404, detail="unsafe avatar URL")
        except Exception as exc:
            log.warning("avatar proxy fetch failed %s: %s", pic_url[:80], exc)
            raise HTTPException(status_code=502, detail="fetch failed") from exc

    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="upstream not found")

    ct = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=404, detail="not an image")

    cached = put_cached_avatar(lid, pic_url, r.content, ct)
    return _avatar_response(cached, request)
