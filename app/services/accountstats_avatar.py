"""Аватары из БД accountstats (social-dashboard): accounts.profile_pic."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.services.label_match import account_label_display

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


def is_placeholder_avatar(url: str | None) -> bool:
    if not url or not str(url).strip():
        return True
    return bool(_PLACEHOLDER_PIC_RE.search(str(url)))


def _normalize_profile_url(url: str) -> str:
    u = urlparse(url.strip())
    host = (u.netloc or "").lower().removeprefix("www.")
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


async def lookup_profile_pic(label: str | None, platform: str | None) -> str | None:
    """Найти profile_pic в accountstats по URL или platform+username."""
    from app.services.account_avatar import account_profile_url

    engine = _engine()
    if engine is None or not label or not str(label).strip():
        return None

    profile_url = account_profile_url(label, platform)
    username = account_label_display(label)
    plat = _accountstats_platform(platform)

    norm_url = _normalize_profile_url(profile_url) if profile_url else None

    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT profile_pic
                        FROM accounts
                        WHERE profile_pic IS NOT NULL
                          AND btrim(profile_pic) <> ''
                          AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc.php%'
                          AND (
                            (:norm_url IS NOT NULL AND """
                        + _SQL_NORM_URL
                        + """ = :norm_url)
                            OR (
                              :plat IS NOT NULL
                              AND :username IS NOT NULL
                              AND upper(platform) = :plat
                              AND lower(username) = lower(:username)
                            )
                          )
                        ORDER BY
                          CASE WHEN :norm_url IS NOT NULL AND """
                        + _SQL_NORM_URL
                        + """ = :norm_url THEN 0 ELSE 1 END
                        LIMIT 1
                        """
                    ),
                    {
                        "norm_url": norm_url,
                        "plat": plat,
                        "username": username,
                    },
                )
            ).first()
    except Exception as exc:
        log.warning("accountstats avatar lookup failed: %s", exc)
        return None

    if not row:
        return None
    pic = row[0]
    return str(pic) if _is_usable_pic(pic) else None


async def lookup_profile_pics_batch(
    items: list[tuple[str, str | None]],
) -> dict[str, str]:
    """Пакетный поиск: ключ — label, значение — profile_pic."""
    from app.services.account_avatar import account_profile_url

    engine = _engine()
    if engine is None or not items:
        return {}

    norm_urls: list[str] = []
    pairs: list[tuple[str, str]] = []
    label_keys: dict[str, str] = {}

    for label, platform in items:
        if not label or not str(label).strip():
            continue
        key = str(label).strip()
        profile_url = account_profile_url(key, platform)
        username = account_label_display(key)
        plat = _accountstats_platform(platform)
        if profile_url:
            norm = _normalize_profile_url(profile_url)
            norm_urls.append(norm)
            label_keys[norm] = key
        if plat and username:
            pair = (plat, username.casefold())
            pairs.append(pair)
            label_keys[f"{pair[0]}:{pair[1]}"] = key

    if not norm_urls and not pairs:
        return {}

    out: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            if norm_urls:
                rows = (
                    await conn.execute(
                        text(
                            f"""
                            SELECT {_SQL_NORM_URL} AS norm_url, profile_pic
                            FROM accounts
                            WHERE profile_pic IS NOT NULL
                              AND btrim(profile_pic) <> ''
                              AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc.php%'
                              AND {_SQL_NORM_URL} = ANY(:urls)
                            """
                        ),
                        {"urls": list(set(norm_urls))},
                    )
                ).all()
                for norm_url, pic in rows:
                    if not _is_usable_pic(pic):
                        continue
                    label = label_keys.get(norm_url)
                    if label:
                        out[label] = str(pic)

            missing = [it for it in items if it[0] and str(it[0]).strip() not in out]
            if missing and pairs:
                plats = list({p[0] for p in pairs})
                users = list({p[1] for p in pairs})
                rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT upper(platform) AS plat, lower(username) AS uname, profile_pic
                            FROM accounts
                            WHERE profile_pic IS NOT NULL
                              AND btrim(profile_pic) <> ''
                              AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc.php%'
                              AND upper(platform) = ANY(:plats)
                              AND lower(username) = ANY(:users)
                            """
                        ),
                        {"plats": plats, "users": users},
                    )
                ).all()
                pair_to_pic = {
                    (str(plat), str(uname)): str(pic)
                    for plat, uname, pic in rows
                    if _is_usable_pic(pic)
                }
                for label, platform in missing:
                    key = str(label).strip()
                    username = account_label_display(key)
                    plat = _accountstats_platform(platform)
                    if not plat or not username:
                        continue
                    pic = pair_to_pic.get((plat, username.casefold()))
                    if pic:
                        out[key] = pic
    except Exception as exc:
        log.warning("accountstats batch avatar lookup failed: %s", exc)

    return out
