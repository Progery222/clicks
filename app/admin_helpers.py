"""Общие хелперы админки: профили, фильтры ссылок."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode, urlparse

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Click, Link
from app.platforms import detect_platform_from_text, platform_favicon_url
from app.stats_range import dashboard_stats_range, parse_range


def parse_profile_id(raw: str | None) -> uuid.UUID | None:
    if not raw or raw.strip() in ("", "none"):
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


def normalize_table_sort(sort: str | None) -> str | None:
    s = (sort or "").strip().lower()
    return s if s in ("total", "today") else None


def normalize_table_order(order: str | None, *, sort: str | None) -> str | None:
    if not sort:
        return None
    o = (order or "desc").strip().lower()
    return o if o in ("asc", "desc") else "desc"


def normalize_account_search(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    return s[:255]


def normalize_destination_filter(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s or s == "all":
        return None
    return s[:2048]


def destination_display_label(url: str) -> str:
    """Короткая подпись цели для сайдбара (хост или укороченный URL)."""
    s = (url or "").strip()
    if not s:
        return "—"
    try:
        parsed = urlparse(s if "://" in s else f"https://{s}")
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (parsed.path or "").rstrip("/")
        if host and (not path or path == ""):
            return host
        if host:
            label = f"{host}{path}"
            if parsed.query:
                label = f"{label}?{parsed.query}"
            return label[:80]
    except Exception:
        pass
    return s if len(s) <= 80 else s[:77] + "…"


def destination_host(url: str) -> str | None:
    s = (url or "").strip()
    if not s:
        return None
    try:
        parsed = urlparse(s if "://" in s else f"https://{s}")
        host = (parsed.netloc or "").lower().removeprefix("www.")
        return host or None
    except Exception:
        return None


def destination_site_icon_url(url: str) -> str | None:
    """URL иконки цели: наш прокси (реальный favicon сайта, без Google-глобуса)."""
    host = destination_host(url)
    if not host:
        return None
    from app.services.destination_favicon import destination_favicon_href

    return destination_favicon_href(host)


def destination_icons(url: str, *, platform_id: str | None = None) -> tuple[str | None, str | None, list[str]]:
    """(icon_url, platform_icon_url, client_fallbacks) для сайдбара и таблицы."""
    from app.services.destination_favicon import destination_client_fallbacks

    host = destination_host(url)
    icon = destination_site_icon_url(url)
    plat = detect_platform_from_text(url) or platform_id
    plat_icon = platform_favicon_url(plat)
    fallbacks = destination_client_fallbacks(host or "")
    if plat_icon and plat_icon not in fallbacks:
        fallbacks.append(plat_icon)
    return icon, plat_icon, fallbacks


def account_label_ilike(term: str):
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        Link.label.ilike(pattern, escape="\\"),
        Link.title.ilike(pattern, escape="\\"),
    )


def build_filter_query(
    profile: str,
    platform: str,
    *,
    account: str | None = None,
    destination: str | None = None,
    preset: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str | None = None,
    order: str | None = None,
) -> str:
    params: dict[str, str] = {}
    if profile and profile != "all":
        params["profile"] = profile
    if platform and platform != "all":
        params["platform"] = platform
    account_term = normalize_account_search(account)
    if account_term:
        params["account"] = account_term
    dest = normalize_destination_filter(destination)
    if dest:
        params["destination"] = dest
    p = (preset or "").strip().lower()
    if p and p not in ("", "all"):
        params["preset"] = p
    if date_from and date_from.strip():
        params["from"] = date_from.strip()
    if date_to and date_to.strip():
        params["to"] = date_to.strip()
    sort_key = normalize_table_sort(sort)
    order_key = normalize_table_order(order, sort=sort_key)
    if sort_key:
        params["sort"] = sort_key
    if order_key:
        params["order"] = order_key
    if not params:
        return ""
    return "?" + urlencode(params)


def link_filter_predicates(
    profile: str | None,
    platform: str | None,
    account: str | None = None,
    destination: str | None = None,
) -> list:
    """Условия WHERE для фильтра профиля/платформы/аккаунта/цели (select и delete)."""
    preds: list = []
    if profile == "none":
        preds.append(Link.profile_id.is_(None))
    elif profile and profile != "all":
        pid = parse_profile_id(profile)
        if pid is not None:
            preds.append(Link.profile_id == pid)
    if platform == "none":
        preds.append(Link.platform.is_(None))
    elif platform and platform != "all":
        preds.append(Link.platform == platform)
    account_term = normalize_account_search(account)
    if account_term:
        preds.append(account_label_ilike(account_term))
    dest = normalize_destination_filter(destination)
    if dest:
        preds.append(Link.destination_url == dest)
    return preds


def apply_link_filters(
    stmt: Select[tuple[Link]],
    *,
    profile: str | None,
    platform: str | None,
    account: str | None = None,
    destination: str | None = None,
) -> Select[tuple[Link]]:
    for pred in link_filter_predicates(profile, platform, account, destination):
        stmt = stmt.where(pred)
    return stmt


async def earliest_link_created_at(db: AsyncSession):
    from app.services.stats_cache import set_cached_earliest_link, try_get_cached_earliest_link

    hit, val = try_get_cached_earliest_link()
    if hit:
        return val
    row = await db.execute(select(func.min(Link.created_at)))
    val = row.scalar_one_or_none()
    set_cached_earliest_link(val)
    return val


async def cached_sidebar_link_counts(
    db: AsyncSession,
) -> tuple[dict[str, int], dict[str, int]]:
    """Кэш счётчиков сайдбара. Первый элемент — заглушка (профили убраны из UI)."""
    from app.services.stats_cache import get_cached_sidebar_counts, set_cached_sidebar_counts

    cached = get_cached_sidebar_counts()
    if cached is not None:
        return cached
    plat = await platform_link_counts(db)
    set_cached_sidebar_counts({}, plat)
    return {}, plat


def resolve_stats_period(
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
    *,
    earliest,
) -> tuple:
    custom = (date_from and date_from.strip()) or (date_to and date_to.strip())
    if (preset and preset.strip()) or not custom:
        return dashboard_stats_range(date_from, date_to, preset, earliest=earliest)
    return parse_range(date_from, date_to)


def apply_click_link_filters(
    stmt,
    profile: str,
    platform: str,
    account: str | None = None,
    destination: str | None = None,
):
    link_ids = apply_link_filters(
        select(Link.id),
        profile=profile,
        platform=platform,
        account=account,
        destination=destination,
    )
    return stmt.where(Click.link_id.in_(link_ids))


async def platform_link_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(select(Link.platform, func.count()).group_by(Link.platform))
    ).all()
    counts: dict[str, int] = {}
    total = 0
    for plat, cnt in rows:
        n = int(cnt)
        total += n
        if plat:
            counts[plat] = n
        else:
            counts["none"] = n
    counts["all"] = total
    return counts


async def destination_link_filters(db: AsyncSession) -> list[dict]:
    """Группы целей для сайдбара: Все + уникальные destination_url со счётчиками."""
    rows = (
        await db.execute(
            select(Link.destination_url, func.count())
            .group_by(Link.destination_url)
            .order_by(func.count().desc(), Link.destination_url.asc())
        )
    ).all()

    plat_rows = (
        await db.execute(
            select(Link.destination_url, Link.platform, func.count())
            .group_by(Link.destination_url, Link.platform)
        )
    ).all()
    majority_platform: dict[str, str | None] = {}
    plat_best: dict[str, tuple[int, str | None]] = {}
    for dest, plat, cnt in plat_rows:
        key = str(dest)
        n = int(cnt)
        prev = plat_best.get(key)
        if prev is None or n > prev[0]:
            plat_best[key] = (n, plat)
    for key, (_, plat) in plat_best.items():
        majority_platform[key] = plat

    items: list[dict] = []
    total = 0
    for url, cnt in rows:
        n = int(cnt)
        total += n
        raw = str(url)
        icon_url, platform_icon_url, icon_fallbacks = destination_icons(
            raw, platform_id=majority_platform.get(raw)
        )
        items.append(
            {
                "id": raw,
                "name": destination_display_label(raw),
                "count": n,
                "icon_url": icon_url,
                "platform_icon_url": platform_icon_url,
                "icon_fallbacks": icon_fallbacks,
            }
        )
    return [
        {
            "id": "all",
            "name": "Все цели",
            "count": total,
            "icon_url": None,
            "platform_icon_url": None,
            "icon_fallbacks": [],
        },
        *items,
    ]
