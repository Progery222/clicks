"""Аватары из БД accountstats (social-dashboard): accounts.profile_pic."""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.services.label_match import account_label_display, normalize_account_label

log = logging.getLogger(__name__)

_SQL_NORM_URL = (
    "lower(regexp_replace(regexp_replace(rtrim(url, '/'), '^https?://', '', 'i'), '^www\\.', '', 'i'))"
)

_PLACEHOLDER_PIC_RE = re.compile(
    r"cdninstagram\.com/rsrc\.php|google\.com/s2/favicons",
    re.I,
)

_PLATFORM_TO_ACCOUNTSTATS: dict[str, str] = {
    "tiktok": "TIKTOK",
    "instagram": "INSTAGRAM",
    "x": "TWITTER",
    "facebook": "FACEBOOK",
    "youtube": "YOUTUBE",
    "telegram": "TELEGRAM",
    "reddit": "REDDIT",
    "threads": "THREADS",
}

_WHERE_USABLE = """
    profile_pic IS NOT NULL
    AND btrim(profile_pic) <> ''
    AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc.php%'
    AND profile_pic NOT ILIKE '%google.com/s2/favicons%'
"""


def is_placeholder_avatar(url: str | None) -> bool:
    if not url or not str(url).strip():
        return True
    return bool(_PLACEHOLDER_PIC_RE.search(str(url)))


def _normalize_profile_url(url: str) -> str:
    u = urlparse(url.strip().split("?")[0].split("#")[0])
    host = (u.netloc or "").lower().removeprefix("www.")
    if host == "threads.com":
        host = "threads.net"
    path = (u.path or "").rstrip("/")
    return f"{host}{path}".casefold()


def _accountstats_platform(platform: str | None) -> str | None:
    if not platform:
        return None
    return _PLATFORM_TO_ACCOUNTSTATS.get(platform.strip().lower())


@lru_cache
def _engine() -> AsyncEngine | None:
    raw = get_settings().accountstats_database_url
    if not raw or not str(raw).strip():
        return None
    url = str(raw).strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


def _is_usable_pic(url: str | None) -> bool:
    return bool(url and str(url).strip() and not is_placeholder_avatar(url))


def _label_norm_keys(label: str, platform: str | None) -> list[str]:
    from app.services.account_avatar import account_profile_url

    keys: list[str] = []
    s = str(label).strip()
    profile_url = account_profile_url(s, platform)
    if profile_url:
        keys.append(_normalize_profile_url(profile_url))
    if re.match(r"^https?://", s, re.I):
        keys.append(_normalize_profile_url(s))
    norm = normalize_account_label(s)
    if norm:
        keys.append(norm.casefold())
    return list(dict.fromkeys(keys))


_ACCOUNTSTATS_INDEX_TTL_SEC = 300.0
_accountstats_index_cache: tuple[float, tuple[dict[str, str], dict[tuple[str, str], str], list[tuple[str, str, str]]]] | None = None


async def _get_accountstats_index(
    conn,
) -> tuple[dict[str, str], dict[tuple[str, str], str], list[tuple[str, str, str]]]:
    global _accountstats_index_cache
    now = time.monotonic()
    if _accountstats_index_cache is not None:
        ts, data = _accountstats_index_cache
        if now - ts < _ACCOUNTSTATS_INDEX_TTL_SEC:
            return data
    data = await _load_accountstats_index(conn)
    _accountstats_index_cache = (now, data)
    return data


async def _load_accountstats_index(
    conn,
) -> tuple[dict[str, str], dict[tuple[str, str], str], list[tuple[str, str, str]]]:
    """norm_url → pic; (plat, user) → pic; список для fuzzy (plat, user, pic)."""
    rows = (
        await conn.execute(
            text(
                f"""
                SELECT upper(platform) AS plat,
                       lower(username) AS uname,
                       {_SQL_NORM_URL} AS norm_url,
                       profile_pic
                FROM accounts
                WHERE {_WHERE_USABLE}
                """
            )
        )
    ).all()

    by_url: dict[str, str] = {}
    by_user: dict[tuple[str, str], str] = {}
    fuzzy: list[tuple[str, str, str]] = []
    for plat, uname, norm_url, pic in rows:
        if not _is_usable_pic(pic):
            continue
        pic_s = str(pic)
        if norm_url:
            by_url[str(norm_url)] = pic_s
        if plat and uname:
            by_user[(str(plat), str(uname))] = pic_s
            fuzzy.append((str(plat), str(uname), pic_s))
    return by_url, by_user, fuzzy


def _fuzzy_match(
    plat: str,
    username: str,
    fuzzy_rows: list[tuple[str, str, str]],
) -> str | None:
    user_cf = username.casefold()
    for row_plat, row_user, pic in fuzzy_rows:
        if row_plat != plat:
            continue
        if row_user == user_cf:
            return pic
    return None


async def lookup_profile_pic(label: str | None, platform: str | None) -> str | None:
    """Найти profile_pic в accountstats по URL или platform+username."""
    engine = _engine()
    if engine is None or not label or not str(label).strip():
        return None

    username = account_label_display(label)
    plat = _accountstats_platform(platform)
    norm_keys = _label_norm_keys(str(label).strip(), platform)

    try:
        async with engine.connect() as conn:
            by_url, by_user, fuzzy = await _get_accountstats_index(conn)
            for nk in norm_keys:
                if nk in by_url:
                    return by_url[nk]
            if plat and username:
                pic = by_user.get((plat, username.casefold()))
                if pic:
                    return pic
                pic = _fuzzy_match(plat, username, fuzzy)
                if pic:
                    return pic
    except Exception as exc:
        log.warning("accountstats avatar lookup failed: %s", exc)
        return None

    return None


async def lookup_profile_pics_batch(
    items: list[tuple[str, str | None]],
) -> dict[str, str]:
    """Пакетный поиск: ключ — label, значение — profile_pic."""
    engine = _engine()
    if engine is None or not items:
        return {}

    out: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            by_url, by_user, fuzzy = await _get_accountstats_index(conn)
            for label, platform in items:
                if not label or not str(label).strip():
                    continue
                key = str(label).strip()
                if key in out:
                    continue
                username = account_label_display(key)
                plat = _accountstats_platform(platform)
                for nk in _label_norm_keys(key, platform):
                    pic = by_url.get(nk)
                    if pic:
                        out[key] = pic
                        break
                if key in out:
                    continue
                if plat and username:
                    pic = by_user.get((plat, username.casefold()))
                    if not pic:
                        pic = _fuzzy_match(plat, username, fuzzy)
                    if pic:
                        out[key] = pic
    except Exception as exc:
        log.warning("accountstats batch avatar lookup failed: %s", exc)

    return out
