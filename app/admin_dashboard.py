"""Сбор данных для главной админки (/admin)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.label_match import account_label_display
from app.admin_helpers import (
    apply_link_filters,
    build_filter_query,
    normalize_table_order,
    normalize_table_sort,
)
from app.models import Click, Link
from app.platforms import PLATFORMS, platform_color, platform_label
from app.services.account_avatar import sync_avatars_from_accountstats
from app.services.admin_avatar import admin_avatar_href
from app.services.stats import (
    aggregate_clicks_for_links,
    click_counts_for_links_period,
    dashboard_click_counts,
    platform_click_stats,
)
from app.stats_range import (
    DASHBOARD_DEFAULT_PRESET,
    active_preset,
    dashboard_stats_range,
    form_period_dates,
)


def _period_query_kwargs(active_preset: str, period_from: str, period_to: str) -> dict:
    return {
        "preset": active_preset if active_preset != "custom" else None,
        "date_from": period_from if active_preset == "custom" else None,
        "date_to": period_to if active_preset == "custom" else None,
    }


def admin_filter_href_for(
    profile: str,
    platform: str,
    *,
    account: str | None = None,
    active_preset: str,
    period_from: str,
    period_to: str,
    sort: str | None = None,
    order: str | None = None,
) -> str:
    return "/admin" + build_filter_query(
        profile,
        platform,
        account=account,
        sort=sort,
        order=order,
        **_period_query_kwargs(active_preset, period_from, period_to),
    )


def export_qs_for(
    profile: str,
    platform: str,
    *,
    account: str | None = None,
    active_preset: str,
    period_from: str,
    period_to: str,
    sort: str | None = None,
    order: str | None = None,
) -> str:
    return build_filter_query(
        profile,
        platform,
        account=account,
        sort=sort,
        order=order,
        **_period_query_kwargs(active_preset, period_from, period_to),
    )


def sort_column_href_for(
    profile: str,
    platform: str,
    *,
    account: str | None = None,
    active_preset: str,
    period_from: str,
    period_to: str,
    column: str,
    current_sort: str | None,
    current_order: str | None,
) -> str:
    if current_sort == column:
        next_order = "asc" if current_order == "desc" else "desc"
    else:
        next_order = "desc"
    return "/admin" + build_filter_query(
        profile,
        platform,
        account=account,
        sort=column,
        order=next_order,
        **_period_query_kwargs(active_preset, period_from, period_to),
    )


def sort_link_rows(
    rows: list[dict],
    *,
    sort: str | None,
    order: str | None,
) -> list[dict]:
    sort_key = normalize_table_sort(sort)
    if not sort_key:
        return rows
    reverse = normalize_table_order(order, sort=sort_key) == "desc"

    def key(row: dict) -> tuple:
        primary = int(row.get("total" if sort_key == "total" else "today", 0))
        link = row["link"]
        created = link.created_at.timestamp() if link.created_at else 0.0
        return (primary, created)

    return sorted(rows, key=key, reverse=reverse)


async def load_dashboard_page_data(
    db: AsyncSession,
    *,
    profile: str,
    platform: str,
    account: str | None = None,
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
    sort: str | None = None,
    order: str | None = None,
) -> dict:
    sort_by = normalize_table_sort(sort)
    sort_order = normalize_table_order(order, sort=sort_by)
    account_term = (account or "").strip()
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc())
    stmt = apply_link_filters(stmt, profile=profile, platform=platform, account=account_term)
    links = list((await db.execute(stmt)).scalars().all())
    await sync_avatars_from_accountstats(db, links, limit=max(len(links), 1))
    link_ids = [link.id for link in links]

    earliest_row = await db.execute(select(func.min(Link.created_at)))
    earliest = earliest_row.scalar_one_or_none()

    active = active_preset(date_from, date_to, preset, default=DASHBOARD_DEFAULT_PRESET)
    start, end = dashboard_stats_range(
        date_from, date_to, preset, earliest=earliest, default_preset=DASHBOARD_DEFAULT_PRESET
    )
    period_from, period_to = form_period_dates(start, end)

    try:
        all_time = await dashboard_click_counts(db)
    except Exception:
        all_time = {}

    try:
        period_map = await click_counts_for_links_period(db, link_ids, start, end)
    except Exception:
        period_map = {}

    try:
        period_total, period_uniques = await aggregate_clicks_for_links(db, link_ids, start, end)
    except Exception:
        period_total, period_uniques = 0, 0

    try:
        plat_stats_raw = await platform_click_stats(db, link_ids, start, end)
    except Exception:
        plat_stats_raw = []

    plat_by_id = {p["id"]: p for p in PLATFORMS}
    platform_stats = []
    for row in plat_stats_raw:
        pid = row["platform"]
        meta = plat_by_id.get(pid)
        platform_stats.append(
            {
                "platform": pid,
                "label": meta["label"] if meta else ("Без платформы" if pid == "none" else pid),
                "color": meta["color"] if meta else "#525a70",
                "clicks": row["clicks"],
                "uniques": row["uniques"],
            }
        )

    period_label = {
        "today": "Сегодня (UTC)",
        "week": "Неделя",
        "all": "Всё время",
        "custom": f"{period_from} — {period_to}",
    }.get(active, period_from)

    link_rows = []
    for link in links:
        total_all, today = all_time.get(link.id, (0, 0))
        period_clicks, period_uniq_link = period_map.get(link.id, (0, 0))
        link_rows.append(
            {
                "link": link,
                "account_display": account_label_display(link.label),
                "account_avatar_url": admin_avatar_href(link.id),
                "total": total_all,
                "today": today,
                "period_clicks": period_clicks,
                "period_uniques": period_uniq_link,
                "platform_label": platform_label(link.platform),
                "platform_color": platform_color(link.platform),
            }
        )

    link_rows = sort_link_rows(link_rows, sort=sort_by, order=sort_order)

    filter_qs = export_qs_for(
        profile,
        platform,
        account=account_term or None,
        active_preset=active,
        period_from=period_from,
        period_to=period_to,
        sort=sort_by,
        order=sort_order,
    )
    period_hrefs = {
        "today": "/admin"
        + build_filter_query(
            profile,
            platform,
            account=account_term or None,
            preset="today",
            sort=sort_by,
            order=sort_order,
        ),
        "week": "/admin"
        + build_filter_query(
            profile,
            platform,
            account=account_term or None,
            preset="week",
            sort=sort_by,
            order=sort_order,
        ),
        "all": "/admin"
        + build_filter_query(
            profile,
            platform,
            account=account_term or None,
            sort=sort_by,
            order=sort_order,
        ),
    }

    return {
        "link_rows": link_rows,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "filter_profile": profile,
        "filter_platform": platform,
        "filter_account": account_term,
        "filter_qs": filter_qs,
        "period_hrefs": period_hrefs,
        "active_preset": active,
        "period_from": period_from,
        "period_to": period_to,
        "period_label": period_label,
        "period_total": period_total,
        "period_uniques": period_uniques,
        "platform_stats": platform_stats,
        "admin_filter_href": lambda prof, plat: admin_filter_href_for(
            prof,
            plat,
            account=account_term or None,
            active_preset=active,
            period_from=period_from,
            period_to=period_to,
            sort=sort_by,
            order=sort_order,
        ),
        "sort_href": lambda col: sort_column_href_for(
            profile,
            platform,
            account=account_term or None,
            active_preset=active,
            period_from=period_from,
            period_to=period_to,
            column=col,
            current_sort=sort_by,
            current_order=sort_order,
        ),
    }
