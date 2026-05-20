"""Общие хелперы админки: профили, фильтры ссылок."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Click, Link, Profile
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


def build_filter_query(
    profile: str,
    platform: str,
    *,
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
) -> list:
    """Условия WHERE для фильтра профиля/платформы (select и delete)."""
    preds: list = []
    if profile == "none":
        preds.append(Link.profile_id.is_(None))
    elif profile and profile != "all":
        pid = parse_profile_id(profile)
        if pid is not None:
            preds.append(Link.profile_id == pid)
    if platform and platform != "all":
        preds.append(Link.platform == platform)
    return preds


def apply_link_filters(
    stmt: Select[tuple[Link]],
    *,
    profile: str | None,
    platform: str | None,
) -> Select[tuple[Link]]:
    for pred in link_filter_predicates(profile, platform):
        stmt = stmt.where(pred)
    return stmt


async def load_profiles(db: AsyncSession) -> list[Profile]:
    res = await db.execute(select(Profile).order_by(Profile.name))
    return list(res.scalars().all())


async def profile_link_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(select(Link.profile_id, func.count()).group_by(Link.profile_id))
    ).all()
    counts: dict[str, int] = {"none": 0}
    total = 0
    for pid, cnt in rows:
        n = int(cnt)
        total += n
        key = "none" if pid is None else str(pid)
        counts[key] = n
    counts["all"] = total
    return counts


async def earliest_link_created_at(db: AsyncSession):
    row = await db.execute(select(func.min(Link.created_at)))
    return row.scalar_one_or_none()


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


def apply_click_link_filters(stmt, profile: str, platform: str):
    link_ids = apply_link_filters(select(Link.id), profile=profile, platform=platform)
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
