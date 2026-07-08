"""Прокси аватаров в админке: accountstats → кэш в links → HTTP (og:image / oEmbed)."""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link
from app.services.account_avatar import _FETCH_HEADERS, resolve_account_avatar_url
from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pic

log = logging.getLogger(__name__)

_IMG_HEADERS = {
    **_FETCH_HEADERS,
    "Accept": "image/*,*/*;q=0.8",
}

_resolve_locks: dict[uuid.UUID, asyncio.Lock] = {}
_resolve_guard = asyncio.Lock()
_http_resolve_sem = asyncio.Semaphore(6)


def admin_avatar_href(link_id: uuid.UUID) -> str:
    return f"/admin/avatar/{link_id}"


async def _lock_for(link_id: uuid.UUID) -> asyncio.Lock:
    async with _resolve_guard:
        if link_id not in _resolve_locks:
            _resolve_locks[link_id] = asyncio.Lock()
        return _resolve_locks[link_id]


async def resolve_and_cache_link_avatar(db: AsyncSession, link: Link) -> str | None:
    """Вернуть URL картинки; при необходимости подтянуть из accountstats или HTTP."""
    if link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
        return link.account_avatar_url

    pic = await lookup_profile_pic(link.label, link.platform)
    if pic:
        link.account_avatar_url = pic
        await db.commit()
        return pic

    lock = await _lock_for(link.id)
    async with lock:
        await db.refresh(link)
        if link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
            return link.account_avatar_url

        async with _http_resolve_sem:
            async with httpx.AsyncClient(
                headers=_FETCH_HEADERS, follow_redirects=True, timeout=15.0
            ) as client:
                pic = await resolve_account_avatar_url(link.label, link.platform, client)

        if pic and pic != link.account_avatar_url:
            link.account_avatar_url = pic
            await db.commit()
        return pic


async def stream_link_avatar(db: AsyncSession, link: Link) -> Response:
    pic_url = await resolve_and_cache_link_avatar(db, link)
    if not pic_url:
        raise HTTPException(status_code=404, detail="avatar not found")

    async with httpx.AsyncClient(
        headers=_IMG_HEADERS, follow_redirects=True, timeout=20.0
    ) as client:
        try:
            r = await client.get(pic_url)
        except Exception as exc:
            log.warning("avatar proxy fetch failed %s: %s", pic_url[:80], exc)
            raise HTTPException(status_code=502, detail="fetch failed") from exc

    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="upstream not found")

    ct = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=404, detail="not an image")

    return Response(
        content=r.content,
        media_type=ct,
        headers={"Cache-Control": "private, max-age=604800"},
    )
