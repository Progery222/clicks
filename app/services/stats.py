import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Click, Link, Link


async def stats_summary(
    session: AsyncSession,
    link_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    total_q = await session.execute(
        select(func.count())
        .select_from(Click)
        .where(Click.link_id == link_id, Click.created_at >= start, Click.created_at < end)
    )
    total = int(total_q.scalar_one())
    uniq_q = await session.execute(
        select(func.count(func.distinct(Click.dedupe_key)))
        .select_from(Click)
        .where(Click.link_id == link_id, Click.created_at >= start, Click.created_at < end)
    )
    uniq = int(uniq_q.scalar_one())
    return total, uniq


def click_day_bucket_utc():
    """Календарный день клика в UTC (для графиков и CSV)."""
    return func.date_trunc("day", func.timezone("UTC", Click.created_at))


async def stats_by_day(
    session: AsyncSession,
    link_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> list[dict]:
    day = click_day_bucket_utc().label("day")
    stmt: Select = (
        select(
            day,
            func.count().label("clicks"),
            func.count(func.distinct(Click.dedupe_key)).label("uniques"),
        )
        .where(Click.link_id == link_id, Click.created_at >= start, Click.created_at < end)
        .group_by(day)
        .order_by(day)
    )
    rows = (await session.execute(stmt)).all()
    out: list[dict] = []
    for r in rows:
        d = r.day
        if hasattr(d, "date"):
            day_s = d.date().isoformat()
        elif hasattr(d, "isoformat"):
            day_s = d.isoformat()[:10]
        else:
            day_s = str(d)[:10]
        out.append({"day": day_s, "clicks": int(r.clicks), "uniques": int(r.uniques)})
    return out


async def top_countries(
    session: AsyncSession,
    link_id: uuid.UUID,
    start: datetime,
    end: datetime,
    limit: int = 10,
) -> list[tuple[str | None, int]]:
    cc = Click.country_code
    stmt = (
        select(cc, func.count().label("c"))
        .where(
            Click.link_id == link_id,
            Click.created_at >= start,
            Click.created_at < end,
        )
        .group_by(cc)
        .order_by(func.count().desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(r[0], int(r[1])) for r in rows]


async def dashboard_click_counts(session: AsyncSession) -> dict[uuid.UUID, tuple[int, int]]:
    """По каждой ссылке: (всего кликов, кликов за текущие сутки UTC)."""
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    def _lid(x: object) -> uuid.UUID:
        return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))

    totals = (
        await session.execute(select(Click.link_id, func.count()).group_by(Click.link_id))
    ).all()
    today_rows = (
        await session.execute(
            select(Click.link_id, func.count())
            .where(Click.created_at >= day_start, Click.created_at < day_end)
            .group_by(Click.link_id)
        )
    ).all()

    out: dict[uuid.UUID, tuple[int, int]] = {}
    for lid_raw, cnt in totals:
        lid = _lid(lid_raw)
        out[lid] = (int(cnt), 0)
    for lid_raw, cnt in today_rows:
        lid = _lid(lid_raw)
        n = int(cnt)
        if lid in out:
            total, _ = out[lid]
            out[lid] = (total, n)
        else:
            out[lid] = (0, n)
    return out


async def click_counts_for_links_period(
    session: AsyncSession,
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> dict[uuid.UUID, tuple[int, int]]:
    """По каждой ссылке: (клики за период, уникальные за период)."""
    if not link_ids:
        return {}
    where = [Click.link_id.in_(link_ids), Click.created_at >= start, Click.created_at < end]
    totals = (
        await session.execute(
            select(Click.link_id, func.count()).where(*where).group_by(Click.link_id)
        )
    ).all()
    uniqs = (
        await session.execute(
            select(Click.link_id, func.count(func.distinct(Click.dedupe_key)))
            .where(*where)
            .group_by(Click.link_id)
        )
    ).all()
    out: dict[uuid.UUID, tuple[int, int]] = {}
    for lid_raw, cnt in totals:
        lid = lid_raw if isinstance(lid_raw, uuid.UUID) else uuid.UUID(str(lid_raw))
        out[lid] = (int(cnt), 0)
    for lid_raw, cnt in uniqs:
        lid = lid_raw if isinstance(lid_raw, uuid.UUID) else uuid.UUID(str(lid_raw))
        n = int(cnt)
        if lid in out:
            out[lid] = (out[lid][0], n)
        else:
            out[lid] = (0, n)
    return out


async def aggregate_clicks_for_links(
    session: AsyncSession,
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    if not link_ids:
        return 0, 0
    where = [Click.link_id.in_(link_ids), Click.created_at >= start, Click.created_at < end]
    total = int(
        (await session.execute(select(func.count()).select_from(Click).where(*where))).scalar_one()
    )
    uniq = int(
        (
            await session.execute(
                select(func.count(func.distinct(Click.dedupe_key))).select_from(Click).where(*where)
            )
        ).scalar_one()
    )
    return total, uniq


async def platform_click_stats(
    session: AsyncSession,
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> list[dict]:
    if not link_ids:
        return []
    plat = Link.platform.label("platform")
    stmt = (
        select(
            plat,
            func.count().label("clicks"),
            func.count(func.distinct(Click.dedupe_key)).label("uniques"),
        )
        .select_from(Click)
        .join(Link, Click.link_id == Link.id)
        .where(
            Click.link_id.in_(link_ids),
            Click.created_at >= start,
            Click.created_at < end,
        )
        .group_by(plat)
        .order_by(func.count().desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"platform": r.platform or "none", "clicks": int(r.clicks), "uniques": int(r.uniques)}
        for r in rows
    ]


def _referer_label(raw: str | None) -> str:
    if not raw or not raw.strip():
        return "(прямой / без referer)"
    s = raw.strip().replace("\n", " ")
    return s[:117] + "..." if len(s) > 120 else s


def _ua_label(raw: str | None) -> str:
    if not raw or not raw.strip():
        return "(не указан)"
    s = raw.strip().replace("\n", " ")
    return s[:97] + "..." if len(s) > 100 else s


async def top_referers(
    session: AsyncSession,
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    limit: int = 10,
) -> list[tuple[str, int]]:
    if not link_ids:
        return []
    rows = (
        await session.execute(
            select(Click.referer, func.count().label("c"))
            .where(
                Click.link_id.in_(link_ids),
                Click.created_at >= start,
                Click.created_at < end,
            )
            .group_by(Click.referer)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return [(_referer_label(r[0]), int(r[1])) for r in rows]


async def top_user_agents(
    session: AsyncSession,
    link_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    limit: int = 10,
) -> list[tuple[str, int]]:
    if not link_ids:
        return []
    rows = (
        await session.execute(
            select(Click.user_agent, func.count().label("c"))
            .where(
                Click.link_id.in_(link_ids),
                Click.created_at >= start,
                Click.created_at < end,
            )
            .group_by(Click.user_agent)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return [(_ua_label(r[0]), int(r[1])) for r in rows]
