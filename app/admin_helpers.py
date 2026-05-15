"""Общие хелперы админки: профили, фильтры ссылок."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Link, Profile


def parse_profile_id(raw: str | None) -> uuid.UUID | None:
    if not raw or raw.strip() in ("", "none"):
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


def build_filter_query(profile: str, platform: str) -> str:
    params: dict[str, str] = {}
    if profile and profile != "all":
        params["profile"] = profile
    if platform and platform != "all":
        params["platform"] = platform
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
