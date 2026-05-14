import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Click


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
