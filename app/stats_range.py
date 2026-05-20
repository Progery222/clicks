"""Диапазоны дат для статистики (UTC): пресеты и произвольный период."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Link


def parse_range(from_s: str | None, to_s: str | None) -> tuple[datetime, datetime]:
    from datetime import date as date_cls
    from datetime import time as time_cls

    tz = ZoneInfo("UTC")
    now = datetime.now(tz)

    def parse_day(s: str, *, end_exclusive_next_day: bool) -> datetime:
        if len(s) == 10:
            d = date_cls.fromisoformat(s)
            if end_exclusive_next_day:
                d = d + timedelta(days=1)
            return datetime.combine(d, time_cls.min, tzinfo=tz)
        return datetime.fromisoformat(s).replace(tzinfo=tz)

    if to_s:
        try:
            if len(to_s) == 10:
                end = parse_day(to_s, end_exclusive_next_day=True)
            else:
                end = datetime.fromisoformat(to_s).replace(tzinfo=tz)
        except ValueError:
            end = now
    else:
        end = now

    if from_s:
        try:
            if len(from_s) == 10:
                start = parse_day(from_s, end_exclusive_next_day=False)
            else:
                start = datetime.fromisoformat(from_s).replace(tzinfo=tz)
        except ValueError:
            start = end - timedelta(days=30)
    else:
        start = end - timedelta(days=30)

    if start >= end:
        start = end - timedelta(days=1)
    return start, end


def active_preset(
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
    *,
    default: str = "today",
) -> str:
    if (date_from and date_from.strip()) or (date_to and date_to.strip()):
        return "custom"
    p = (preset or "").strip().lower()
    if p in ("week", "all", "today"):
        return p
    return default


def stats_range(
    link: Link,
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
    *,
    default_preset: str = "today",
) -> tuple[datetime, datetime]:
    from datetime import date as date_cls
    from datetime import time as time_cls

    tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    today: date_cls = now.date()

    custom = (date_from and date_from.strip()) or (date_to and date_to.strip())
    if custom:
        return parse_range(date_from, date_to)

    def day_start(d: date_cls) -> datetime:
        return datetime.combine(d, time_cls.min, tzinfo=tz)

    p = (preset or "").strip().lower() or default_preset
    if p == "week":
        start_d = today - timedelta(days=6)
        return day_start(start_d), day_start(today + timedelta(days=1))
    if p == "all":
        lc = link.created_at
        if lc.tzinfo is None:
            lc = lc.replace(tzinfo=tz)
        else:
            lc = lc.astimezone(tz)
        start = day_start(lc.date())
        end = day_start(today + timedelta(days=1))
        if start >= end:
            start = day_start(today)
        return start, end
    if p == "today":
        return day_start(today), day_start(today + timedelta(days=1))
    return day_start(today), day_start(today + timedelta(days=1))


def dashboard_stats_range(
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
    *,
    earliest: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Диапазон для главной админки (без привязки к одной ссылке)."""
    from datetime import date as date_cls
    from datetime import time as time_cls

    tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    today: date_cls = now.date()

    custom = (date_from and date_from.strip()) or (date_to and date_to.strip())
    if custom:
        return parse_range(date_from, date_to)

    def day_start(d: date_cls) -> datetime:
        return datetime.combine(d, time_cls.min, tzinfo=tz)

    p = (preset or "").strip().lower()
    if p == "week":
        start_d = today - timedelta(days=6)
        return day_start(start_d), day_start(today + timedelta(days=1))
    if p == "all":
        if earliest is not None:
            lc = earliest
            if lc.tzinfo is None:
                lc = lc.replace(tzinfo=tz)
            else:
                lc = lc.astimezone(tz)
            start = day_start(lc.date())
        else:
            start = day_start(today - timedelta(days=365))
        end = day_start(today + timedelta(days=1))
        if start >= end:
            start = day_start(today)
        return start, end
    return day_start(today), day_start(today + timedelta(days=1))


def form_period_dates(start: datetime, end: datetime) -> tuple[str, str]:
    pf = start.date().isoformat()
    if end.hour == 0 and end.minute == 0 and end.second == 0 and end.microsecond == 0:
        last = end.date() - timedelta(days=1)
    else:
        last = end.date()
    pt = last.isoformat()
    if pf > pt:
        pt = pf
    return pf, pt
