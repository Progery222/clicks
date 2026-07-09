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
from app.safe_http import create_safe_http_client, safe_get
from app.services.avatar_image_cache import invalidate_link_avatar_cache
from app.services.avatar_upload import delete_link_avatar_upload, is_upload_avatar_url
from app.url_validation import is_safe_fetch_url

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

_OG_IMAGE_SCAN_BYTES = 1_500_000

_YOUTUBE_AVATAR_RE = re.compile(
    r'"avatar"\s*:\s*\{\s*"thumbnails"\s*:\s*\[\s*\{\s*"url"\s*:\s*"([^"]+)"',
    re.I,
)

_YOUTUBE_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
    re.I,
)

_YOUTUBE_CHANNEL_URL_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/(?:@|channel/|c/|user/)",
    re.I,
)



_TIKTOK_UNIVERSAL_DATA_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>',
    re.I,
)

_TIKTOK_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_TIKTOK_MIN_HTML_BYTES = 8_000


def _decode_embedded_cdn_url(raw: str) -> str:
    url = unescape(raw.replace("\\u002F", "/").replace("\\/", "/"))
    if url.startswith("https:"):
        return url
    if url.startswith("http:"):
        return url
    return url


def _normalize_tiktok_profile_url(url: str) -> str | None:
    if "tiktok.com" not in url.lower():
        return None
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host not in ("tiktok.com", "m.tiktok.com"):
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return None
    user = parts[0].lstrip("@").split("?")[0].strip()
    if not user:
        return None
    return f"https://www.tiktok.com/@{user}"


def _find_tiktok_avatar_in_json_blob(raw: str) -> str | None:
    for key in ("avatarLarger", "avatarMedium", "avatarThumb"):
        pat = re.compile(rf'"{re.escape(key)}"\s*:\s*"((?:https:)?[^"]+)"')
        m = pat.search(raw)
        if not m:
            continue
        url = _decode_embedded_cdn_url(m.group(1))
        if not url.startswith("http"):
            url = f"https:{url}" if url.startswith("//") else f"https://{url.lstrip(':')}"
        if is_safe_fetch_url(url):
            return url
    return None


def extract_tiktok_avatar_from_html(html: str) -> str | None:
    """Парсинг avatarLarger из HTML профиля TikTok (нужен mobile User-Agent при fetch)."""
    chunk = html[:1_500_000]
    uni = _TIKTOK_UNIVERSAL_DATA_RE.search(chunk)
    if uni:
        pic = _find_tiktok_avatar_in_json_blob(uni.group(1))
        if pic:
            return pic
    return _find_tiktok_avatar_in_json_blob(chunk)


def _normalize_youtube_profile_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host not in ("youtube.com", "m.youtube.com", "youtu.be"):
        return None
    path = (parsed.path or "").strip("/")
    if not path:
        return None
    if path.startswith("@"):
        handle = path.split("/")[0]
        return f"https://www.youtube.com/{handle}"
    parts = path.split("/")
    if parts[0] in ("channel", "c", "user") and len(parts) > 1:
        return f"https://www.youtube.com/{parts[0]}/{parts[1].split('?')[0]}"
    return f"https://www.youtube.com/@{parts[0].lstrip('@').split('?')[0]}"


def extract_youtube_avatar_from_html(html: str) -> str | None:
    """Аватар канала YouTube из og:image или JSON avatar.thumbnails."""
    chunk = html[:_OG_IMAGE_SCAN_BYTES]
    m = _YOUTUBE_OG_IMAGE_RE.search(chunk)
    if m:
        url = unescape(m.group(1).strip())
        if is_safe_fetch_url(url):
            return url
    m = _YOUTUBE_AVATAR_RE.search(chunk)
    if m:
        url = _decode_embedded_cdn_url(m.group(1))
        if is_safe_fetch_url(url):
            return url
    return None


def _is_youtube_profile_url(url: str) -> bool:
    return bool(_YOUTUBE_CHANNEL_URL_RE.match((url or "").strip()))


_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)


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
        return f"https://www.reddit.com/user/{user}/"
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
                url = unescape(urljoin(base_url, raw))
                if is_safe_fetch_url(url):
                    return url
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
        async with create_safe_http_client(headers=_FETCH_HEADERS) as client:
            pic = await _fetch_photo_url(link.label, link.platform, client)
    else:
        from app.services.accountstats_avatar import is_placeholder_avatar, lookup_profile_pic

        pic = await lookup_profile_pic(link.label, link.platform)
        if pic and is_placeholder_avatar(pic):
            pic = None

    link.account_avatar_url = pic or platform_logo_url_for_link(link)
    invalidate_link_avatar_cache(link.id)


async def scrape_link_avatar(db: AsyncSession, link: Link) -> str | None:
    """Принудительно спарсить фото профиля (как в accountstats)."""
    if not link.label or not str(link.label).strip():
        return None
    async with create_safe_http_client(headers=_FETCH_HEADERS) as client:
        pic = await _fetch_photo_url(link.label, link.platform, client)
    if pic:
        delete_link_avatar_upload(link.id)
        link.account_avatar_url = pic
        link.account_avatar_mode = AVATAR_MODE_PHOTO
        invalidate_link_avatar_cache(link.id)
    return pic


async def set_custom_avatar_url(db: AsyncSession, link: Link, url: str) -> None:
    """Задать аватар по прямой ссылке на изображение."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Укажите URL")
    if not is_safe_fetch_url(raw):
        raise ValueError("Недопустимый URL (нужен публичный http(s) на картинку)")
    delete_link_avatar_upload(link.id)
    link.account_avatar_url = raw
    link.account_avatar_mode = AVATAR_MODE_PHOTO
    invalidate_link_avatar_cache(link.id)


async def set_uploaded_avatar(
    db: AsyncSession,
    link: Link,
    content: bytes,
    *,
    declared_type: str | None = None,
) -> None:
    """Сохранить загруженный файл как аватар."""
    from app.services.avatar_upload import save_link_avatar_upload, upload_marker, validate_avatar_upload

    media_type = validate_avatar_upload(content, declared_type)
    save_link_avatar_upload(link.id, content, media_type)
    link.account_avatar_url = upload_marker(link.id)
    link.account_avatar_mode = AVATAR_MODE_PHOTO
    invalidate_link_avatar_cache(link.id)


async def set_link_avatar_mode(db: AsyncSession, link: Link, mode: str) -> None:
    if mode not in AVATAR_MODES:
        raise ValueError(f"invalid avatar mode: {mode}")
    link.account_avatar_mode = mode
    invalidate_link_avatar_cache(link.id)
    if mode == AVATAR_MODE_LETTER:
        link.account_avatar_url = None
        delete_link_avatar_upload(link.id)
    elif mode == AVATAR_MODE_PLATFORM:
        link.account_avatar_url = platform_logo_url_for_link(link)
    elif mode == AVATAR_MODE_AUTO:
        await bootstrap_link_avatar(db, link)


async def _url_is_image(client: httpx.AsyncClient, url: str) -> bool:
    if not is_safe_fetch_url(url):
        return False
    try:
        r = await client.head(url, timeout=8.0)
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
    if not is_safe_fetch_url(page_url):
        return None
    try:
        r = await safe_get(client, page_url, timeout=12.0)
        if r.status_code != 200:
            return None
        ct = (r.headers.get("content-type") or "").lower()
        if "html" not in ct and "text" not in ct:
            return None
        return _extract_og_image(r.text[:_OG_IMAGE_SCAN_BYTES], str(r.url))
    except Exception as exc:
        log.debug("og:image fetch failed for %s: %s", page_url, exc)
        return None


async def _try_youtube_avatar_html(client: httpx.AsyncClient, profile_url: str) -> str | None:
    norm = _normalize_youtube_profile_url(profile_url)
    if not norm or not is_safe_fetch_url(norm):
        return None
    try:
        r = await safe_get(client, norm, timeout=15.0)
        if r.status_code != 200:
            return None
        ct = (r.headers.get("content-type") or "").lower()
        if "html" not in ct and "text" not in ct:
            return None
        return extract_youtube_avatar_from_html(r.text)
    except Exception as exc:
        log.debug("youtube avatar html failed for %s: %s", profile_url, exc)
        return None


async def _try_tiktok_oembed(client: httpx.AsyncClient, profile_url: str) -> str | None:
    """oEmbed для профилей TikTok thumbnail_url больше не отдаёт — оставлено для совместимости."""
    _ = client
    if "tiktok.com" not in profile_url.lower():
        return None
    norm = _normalize_tiktok_profile_url(profile_url)
    if not norm:
        return None
    try:
        r = await safe_get(
            client,
            "https://www.tiktok.com/oembed",
            params={"url": norm},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        thumb = r.json().get("thumbnail_url")
        if thumb and is_safe_fetch_url(str(thumb)):
            return str(thumb)
    except Exception as exc:
        log.debug("tiktok oembed failed for %s: %s", profile_url, exc)
    return None


async def _try_tiktok_avatar_html(client: httpx.AsyncClient, profile_url: str) -> str | None:
    _ = client
    norm = _normalize_tiktok_profile_url(profile_url)
    if not norm or not is_safe_fetch_url(norm):
        return None
    try:
        async with create_safe_http_client(headers=_TIKTOK_MOBILE_HEADERS, timeout=18.0) as tik_client:
            r = await safe_get(tik_client, norm, timeout=18.0)
        if r.status_code != 200:
            return None
        if len(r.text) < _TIKTOK_MIN_HTML_BYTES:
            log.debug("tiktok profile shell page (len=%s) for %s", len(r.text), norm)
            return None
        return extract_tiktok_avatar_from_html(r.text)
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
        plat = (platform or "").lower()
        if plat == "youtube" or _is_youtube_profile_url(profile_url):
            yt_pic = await _try_youtube_avatar_html(client, profile_url)
            if yt_pic:
                return yt_pic
        tiktok_pic = await _try_tiktok_avatar_html(client, profile_url)
        if tiktok_pic:
            return tiktok_pic
        oembed = await _try_tiktok_oembed(client, profile_url)
        if oembed:
            return oembed

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

    async with create_safe_http_client(headers=_FETCH_HEADERS) as client:
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