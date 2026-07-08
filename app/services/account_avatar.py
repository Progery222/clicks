"""Превью/аватар аккаунта по label (URL профиля или username)."""

from __future__ import annotations

import asyncio
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link
from app.platforms import platform_favicon_url

log = logging.getLogger(__name__)

AVATAR_MODE_AUTO = "auto"
AVATAR_MODE_PHOTO = "photo"
AVATAR_MODE_PLATFORM = "platform"
AVATAR_MODE_LETTER = "letter"
AVATAR_MODES = frozenset({AVATAR_MODE_AUTO, AVATAR_MODE_PHOTO, AVATAR_MODE_PLATFORM, AVATAR_MODE_LETTER})

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BioLinksBot/1.0; +https://bytl.org)"
    ),
    "Accept": "text/html,application/xhtml+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_OG_IMAGE_PATTERNS = (
    re.compile(
        r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::url)?["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
        re.I,
    ),
)

_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)


_TIKTOK_AVATAR_RE = re.compile(
    r'"(?:avatarLarger|avatarMedium|avatarThumb)"\s*:\s*"(https:[^"]+)"',
    re.I,
)


def _decode_embedded_cdn_url(raw: str) -> str:
    return unescape(raw.replace("\\u002F", "/").replace("\\/", "/"))


def _first_path_segment(path: str) -> str | None:
    segs = [p for p in (path or "").split("/") if p]
    return segs[0] if segs else None


def account_profile_url(label: str | None, platform: str | None) -> str | None:
    """Публичный URL профиля для og:image / превью."""
    if not label or not str(label).strip():
        return None
    s = str(label).strip()
    if re.match(r"^https?://", s, re.I):
        return s

    user = s.lstrip("@").split("/")[0].split("?")[0].strip()
    if not user:
        return None

    plat = (platform or "").lower()
    low = s.lower()

    if plat == "telegram" or low.startswith("t.me/") or "telegram" in low:
        return f"https://t.me/{user}"
    if plat == "tiktok" or low.startswith("@"):
        return f"https://www.tiktok.com/@{user}"
    if plat == "instagram":
        return f"https://www.instagram.com/{user}/"
    if plat == "youtube":
        if user.startswith("@"):
            return f"https://www.youtube.com/{user}"
        if user.startswith("UC") and len(user) >= 20:
            return f"https://www.youtube.com/channel/{user}"
        return f"https://www.youtube.com/@{user.lstrip('@')}"
    if plat == "x":
        return f"https://x.com/{user}"
    if plat == "threads":
        return f"https://www.threads.net/@{user}"
    if plat == "facebook":
        if user.isdigit():
            return f"https://www.facebook.com/profile.php?id={user}"
        return f"https://www.facebook.com/{user}"
    if plat == "reddit":
        return f"https://www.reddit.com/r/{user}/"
    if plat == "rumble":
        return f"https://rumble.com/c/{user}"

    if _DOMAIN_RE.match(s):
        return f"https://{s.lower()}"

    if plat == "telegram":
        return f"https://t.me/{user}"
    return None


def _telegram_username(label: str | None, platform: str | None) -> str | None:
    url = account_profile_url(label, platform)
    if not url:
        return None
    try:
        u = urlparse(url)
    except Exception:
        return None
    if (u.netloc or "").lower().replace("www.", "") not in ("t.me", "telegram.me"):
        return None
    return _first_path_segment(u.path)


def _extract_og_image(html: str, base_url: str) -> str | None:
    for pat in _OG_IMAGE_PATTERNS:
        m = pat.search(html)
        if m:
            raw = m.group(1).strip()
            if raw:
                return unescape(urljoin(base_url, raw))
    return None


def _favicon_url(domain: str) -> str:
    host = domain.lower().removeprefix("www.")
    return f"https://www.google.com/s2/favicons?domain={host}&sz=128"


def _domain_from_label(label: str) -> str | None:
    s = str(label).strip()
    if re.match(r"^https?://", s, re.I):
        try:
            host = urlparse(s).netloc.lower()
        except Exception:
            return None
    elif _DOMAIN_RE.match(s):
        host = s.lower()
    else:
        return None
    return host.removeprefix("www.") or None


def platform_logo_url_for_link(link: Link) -> str | None:
    """Логотип платформы или favicon домена из аккаунта/цели."""
    if link.platform:
        plat_url = platform_favicon_url(link.platform)
        if plat_url:
            return plat_url
    for raw in (link.label, link.destination_url):
        if not raw:
            continue
        domain = _domain_from_label(str(raw))
        if domain:
            return _favicon_url(domain)
    return None


def link_shows_avatar_image(link: Link) -> bool:
    return (link.account_avatar_mode or AVATAR_MODE_AUTO) != AVATAR_MODE_LETTER


async def _fetch_photo_url(
    label: str | None,
    platform: str | None,
    client: httpx.AsyncClient,
) -> str | None:
    from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pic

    stats_pic = await lookup_profile_pic(label, platform)
    if stats_pic and not is_placeholder_avatar(stats_pic):
        return stats_pic
    pic = await resolve_account_avatar_url(label, platform, client)
    if pic and not is_placeholder_avatar(pic):
        return pic
    return None


async def bootstrap_link_avatar(
    db: AsyncSession,
    link: Link,
    *,
    allow_http: bool = True,
) -> None:
    """При создании/изменении: фото аккаунта или логотип платформы (режим auto)."""
    link.account_avatar_mode = link.account_avatar_mode or AVATAR_MODE_AUTO
    if link.account_avatar_mode == AVATAR_MODE_LETTER:
        link.account_avatar_url = None
        return
    if link.account_avatar_mode == AVATAR_MODE_PLATFORM:
        link.account_avatar_url = platform_logo_url_for_link(link)
        return

    if not link.label or not str(link.label).strip():
        link.account_avatar_url = platform_logo_url_for_link(link)
        return

    pic: str | None = None
    if allow_http:
        async with httpx.AsyncClient(headers=_FETCH_HEADERS, follow_redirects=True) as client:
            pic = await _fetch_photo_url(link.label, link.platform, client)
    else:
        from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pic

        pic = await lookup_profile_pic(link.label, link.platform)
        if pic and is_placeholder_avatar(pic):
            pic = None

    link.account_avatar_url = pic or platform_logo_url_for_link(link)


async def scrape_link_avatar(db: AsyncSession, link: Link) -> str | None:
    """Принудительно спарсить фото профиля (как в accountstats)."""
    if not link.label or not str(link.label).strip():
        return None
    async with httpx.AsyncClient(headers=_FETCH_HEADERS, follow_redirects=True) as client:
        pic = await _fetch_photo_url(link.label, link.platform, client)
    if pic:
        link.account_avatar_url = pic
        link.account_avatar_mode = AVATAR_MODE_PHOTO
    return pic


async def set_link_avatar_mode(db: AsyncSession, link: Link, mode: str) -> None:
    if mode not in AVATAR_MODES:
        raise ValueError(f"invalid avatar mode: {mode}")
    link.account_avatar_mode = mode
    if mode == AVATAR_MODE_LETTER:
        link.account_avatar_url = None
    elif mode == AVATAR_MODE_PLATFORM:
        link.account_avatar_url = platform_logo_url_for_link(link)
    elif mode == AVATAR_MODE_AUTO:
        await bootstrap_link_avatar(db, link)


async def _url_is_image(client: httpx.AsyncClient, url: str) -> bool:    try:
        r = await client.head(url, follow_redirects=True, timeout=8.0)
        if r.status_code != 200:
            return False
        ct = (r.headers.get("content-type") or "").lower()
        return ct.startswith("image/")
    except Exception:
        return False


async def _try_telegram_userpic(client: httpx.AsyncClient, username: str) -> str | None:
    for size in (320, 160):
        url = f"https://t.me/i/userpic/{size}/{username}.jpg"
        if await _url_is_image(client, url):
            return url
    return None


async def _fetch_og_image(client: httpx.AsyncClient, page_url: str) -> str | None:
    try:
        r = await client.get(page_url, follow_redirects=True, timeout=12.0)
        if r.status_code != 200:
            return None
        ct = (r.headers.get("content-type") or "").lower()
        if "html" not in ct and "text" not in ct:
            return None
        return _extract_og_image(r.text[:500_000], str(r.url))
    except Exception as exc:
        log.debug("og:image fetch failed for %s: %s", page_url, exc)
        return None


async def _try_tiktok_oembed(client: httpx.AsyncClient, profile_url: str) -> str | None:
    if "tiktok.com" not in profile_url.lower():
        return None
    try:
        r = await client.get(
            "https://www.tiktok.com/oembed",
            params={"url": profile_url},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        thumb = r.json().get("thumbnail_url")
        if thumb:
            return str(thumb)
    except Exception as exc:
        log.debug("tiktok oembed failed for %s: %s", profile_url, exc)
    return None


async def _try_tiktok_avatar_html(client: httpx.AsyncClient, profile_url: str) -> str | None:
    if "tiktok.com" not in profile_url.lower():
        return None
    try:
        r = await client.get(profile_url, timeout=15.0)
        if r.status_code != 200:
            return None
        m = _TIKTOK_AVATAR_RE.search(r.text[:900_000])
        if not m:
            return None
        return _decode_embedded_cdn_url(m.group(1))
    except Exception as exc:
        log.debug("tiktok avatar html failed for %s: %s", profile_url, exc)
    return None


async def resolve_account_avatar_url(
    label: str | None,
    platform: str | None,
    client: httpx.AsyncClient,
) -> str | None:
    if not label or not str(label).strip():
        return None

    from app.services.accountstats_avatar import lookup_profile_pic

    stats_pic = await lookup_profile_pic(label, platform)
    if stats_pic:
        return stats_pic

    profile_url = account_profile_url(label, platform)
    if profile_url:
        oembed = await _try_tiktok_oembed(client, profile_url)
        if oembed:
            return oembed
        tiktok_pic = await _try_tiktok_avatar_html(client, profile_url)
        if tiktok_pic:
            return tiktok_pic

    tg_user = _telegram_username(label, platform)
    if tg_user:
        pic = await _try_telegram_userpic(client, tg_user)
        if pic:
            return pic

    profile_url = account_profile_url(label, platform)
    if profile_url:
        og = await _fetch_og_image(client, profile_url)
        if og:
            return og

    domain = _domain_from_label(label)
    if domain and not platform:
        return _favicon_url(domain)

    return None


async def ensure_link_avatar(
    db: AsyncSession,
    link: Link,
    client: httpx.AsyncClient,
    *,
    force: bool = False,
) -> bool:
    """Заполнить link.account_avatar_url. Возвращает True, если значение изменилось."""
    if not link.label or not str(link.label).strip():
        if link.account_avatar_url is not None:
            link.account_avatar_url = None
            return True
        return False
    from app.services.accountstats_avatar import is_placeholder_avatar

    if not force and link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
        return False

    url = await resolve_account_avatar_url(link.label, link.platform, client)
    if url == link.account_avatar_url:
        return False
    link.account_avatar_url = url
    return True


async def sync_avatars_from_accountstats(
    db: AsyncSession,
    links: list[Link],
    *,
    limit: int = 100,
) -> int:
    """Быстрое обновление аватаров только из accountstats (без HTTP)."""
    from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pics_batch

    todo = [
        ln
        for ln in links
        if ln.label
        and (ln.account_avatar_mode or AVATAR_MODE_AUTO) in (AVATAR_MODE_AUTO, AVATAR_MODE_PHOTO)
        and (not ln.account_avatar_url or is_placeholder_avatar(ln.account_avatar_url))
    ][:limit]
    if not todo:
        return 0

    batch_pics = await lookup_profile_pics_batch(
        [(ln.label, ln.platform) for ln in todo]
    )
    updated = 0
    for link in todo:
        pic = batch_pics.get(str(link.label).strip())
        if pic and pic != link.account_avatar_url:
            link.account_avatar_url = pic
            updated += 1
    if updated:
        await db.commit()
    return updated


async def backfill_link_avatars(
    db: AsyncSession,
    links: list[Link],
    *,
    limit: int = 20,
    allow_http: bool = True,
) -> int:
    """Подтянуть аватары: accountstats + опционально HTTP (og:image)."""
    from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pics_batch

    todo = [
        ln
        for ln in links
        if ln.label
        and (ln.account_avatar_mode or AVATAR_MODE_AUTO) in (AVATAR_MODE_AUTO, AVATAR_MODE_PHOTO)
        and (not ln.account_avatar_url or is_placeholder_avatar(ln.account_avatar_url))
    ][:limit]
    if not todo:
        return 0

    batch_pics = await lookup_profile_pics_batch(
        [(ln.label, ln.platform) for ln in todo]
    )

    updated = 0
    for link in todo:
        pic = batch_pics.get(str(link.label).strip())
        if pic and pic != link.account_avatar_url:
            link.account_avatar_url = pic
            updated += 1

    if not allow_http:
        if updated:
            await db.commit()
        return updated

    async with httpx.AsyncClient(headers=_FETCH_HEADERS, follow_redirects=True) as client:
        for link in todo:
            if link.account_avatar_url and not is_placeholder_avatar(link.account_avatar_url):
                continue
            if await ensure_link_avatar(db, link, client, force=True):
                updated += 1
    if updated:
        await db.commit()
    return updated


async def refresh_link_avatar(db: AsyncSession, link: Link, *, force: bool = True) -> None:
    await bootstrap_link_avatar(db, link, allow_http=force)