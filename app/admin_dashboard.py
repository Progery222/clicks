"""Сбор данных для главной админки (/admin)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin_helpers import apply_link_filters, build_filter_query
from app.models import Click, Link
from app.platforms import PLATFORMS, platform_color, platform_label
from app.services.stats import (
    aggregate_clicks_for_links,
    click_counts_for_links_period,
    dashboard_click_counts,
    platform_click_stats,
    top_referers,
    top_user_agents,
)
from app.stats_range import active_preset, dashboard_stats_range, form_period_dates


def admin_filter_href_for(
    profile: str,
    platform: str,
    *,
    active_preset: str,
    period_from: str,
    period_to: str,
) -> str:
    return "/admin" + build_filter_query(
        profile,
        platform,
        preset=active_preset if active_preset != "custom" else None,
        date_from=period_from if active_preset == "custom" else None,
        date_to=period_to if active_preset == "custom" else None,
    )


def export_qs_for(
    profile: str,
    platform: str,
    *,
    active_preset: str,
    period_from: str,
    period_to: str,
) -> str:
    return build_filter_query(
        profile,
        platform,
        preset=active_preset if active_preset != "custom" else None,
        date_from=period_from if active_preset == "custom" else None,
        date_to=period_to if active_preset == "custom" else None,
    )


async def load_dashboard_page_data(
    db: AsyncSession,
    *,
    profile: str,
    platform: str,
    date_from: str | None,
    date_to: str | None,
    preset: str | None,
) -> dict:
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc())
    stmt = apply_link_filters(stmt, profile=profile, platform=platform)
    links = list((await db.execute(stmt)).scalars().all())
    link_ids = [link.id for link in links]

    earliest_row = await db.execute(select(func.min(Link.created_at)))
    earliest = earliest_row.scalar_one_or_none()

    active = active_preset(date_from, date_to, preset)
    start, end = dashboard_stats_range(date_from, date_to, preset, earliest=earliest)
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

    try:
        referers = await top_referers(db, link_ids, start, end)
        user_agents = await top_user_agents(db, link_ids, start, end)
    except Exception:
        referers, user_agents = [], []

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
                "total": total_all,
                "today": today,
                "period_clicks": period_clicks,
                "period_uniques": period_uniq_link,
                "platform_label": platform_label(link.platform),
                "platform_color": platform_color(link.platform),
            }
        )

    filter_qs = export_qs_for(
        profile, platform, active_preset=active, period_from=period_from, period_to=period_to
    )
    period_hrefs = {
        "today": "/admin" + build_filter_query(profile, platform),
        "week": "/admin" + build_filter_query(profile, platform, preset="week"),
        "all": "/admin" + build_filter_query(profile, platform, preset="all"),
    }

    return {
        "link_rows": link_rows,
        "filter_profile": profile,
        "filter_platform": platform,
        "filter_qs": filter_qs,
        "period_hrefs": period_hrefs,
        "active_preset": active,
        "period_from": period_from,
        "period_to": period_to,
        "period_label": period_label,
        "period_total": period_total,
        "period_uniques": period_uniques,
        "platform_stats": platform_stats,
        "top_referers": referers,
        "top_user_agents": user_agents,
        "admin_filter_href": lambda prof, plat: admin_filter_href_for(
            prof, plat, active_preset=active, period_from=period_from, period_to=period_to
        ),
    }
