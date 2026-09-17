"""Session JSON API for SPA admin (cookie + CSRF)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_dashboard import load_dashboard_page_data
from app.admin_helpers import (
    apply_link_filters,
    cached_platform_link_counts,
    destination_icons,
    destination_link_filters,
    destination_site_icon_url,
    earliest_link_created_at,
    resolve_stats_period,
)
from app.config import get_settings
from app.csrf import get_or_create_csrf_token, rotate_csrf_token
from app.database import get_db
from app.models import Click, Link
from app.platforms import PLATFORMS, platform_color, platform_favicon_url, platform_label
from app.security import verify_env_password
from app.services.account_avatar import bootstrap_link_avatar
from app.services.admin_avatar import admin_avatar_href
from app.services.avatar_image_cache import invalidate_link_avatar_cache
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.ip_lockout import (
    MSG_BAN_HTML,
    clear_admin_failures,
    client_ip,
    is_ip_banned_now,
    record_admin_password_failure,
)
from app.services.label_match import account_label_display
from app.services.links_meta import (
    apply_destination_title,
    apply_link_accounts,
    apply_link_label,
    apply_link_title,
    group_accounts_by_platform,
)
from app.services.stats import (
    aggregate_clicks_for_links,
    bar_chart_items,
    platform_click_stats,
    stats_by_day,
    stats_summary,
    top_countries,
    top_device_types,
    top_device_types_for_links,
    top_os,
    top_os_for_links,
)
from app.services.destination_favicon import resolve_destination_favicon
from app.services.stats_cache import invalidate_dashboard_counts_cache
from app.stats_range import DASHBOARD_DEFAULT_PRESET, active_preset, form_period_dates, stats_range
from app.url_validation import is_valid_destination_url
from app.utils.csv_import import MAX_IMPORT_BYTES, parse_links_import_csv
from app.utils.slug import random_slug

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/api", tags=["admin-api"])

MAX_BULK_DEST_UPDATE = 500


def _require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _valid_url(url: str) -> bool:
    return is_valid_destination_url(url)


async def _unique_slug(db: AsyncSession) -> str:
    for _ in range(20):
        slug = random_slug()
        exists = await db.scalar(select(Link.id).where(Link.slug == slug))
        if not exists:
            return slug
    raise HTTPException(status_code=500, detail="Could not allocate slug")


@router.get("/destination-favicon")
async def destination_favicon(
    request: Request,
    host: str = Query(..., min_length=3, max_length=253),
) -> Response:
    """Прокси favicon домена цели (без Google-заглушки-глобуса)."""
    _require_admin(request)
    cleaned = host.strip().lower().removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", cleaned):
        raise HTTPException(status_code=404, detail="Not found")
    cached = await resolve_destination_favicon(cleaned)
    if cached is None:
        raise HTTPException(status_code=404, detail="Not found")
    inm = request.headers.get("if-none-match")
    if inm and inm.strip('"') == cached.etag:
        return Response(status_code=304, headers={"ETag": f'"{cached.etag}"'})
    return Response(
        content=cached.content,
        media_type=cached.media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{cached.etag}"',
        },
    )


def _serialize_link(link: Link) -> dict[str, Any]:
    account_display = account_label_display(link.label) or link.label or link.slug
    display_name = (link.title or "").strip() or account_display
    dest_title = (link.destination_title or "").strip() or None
    dest_icon, dest_plat_icon, dest_fallbacks = destination_icons(link.destination_url)
    return {
        "id": str(link.id),
        "slug": link.slug,
        "destination_url": link.destination_url,
        "destination_title": dest_title,
        "destination_display": dest_title or link.destination_url,
        "title": link.title,
        "label": link.label,
        "platform": link.platform,
        "platform_label": platform_label(link.platform),
        "platform_color": platform_color(link.platform),
        "platform_icon_url": platform_favicon_url(link.platform),
        "destination_icon_url": dest_icon or destination_site_icon_url(link.destination_url),
        "destination_icon_fallback_url": dest_plat_icon,
        "destination_icon_fallbacks": dest_fallbacks,
        "account_avatar_url": admin_avatar_href(link),
        "account_display": account_display,
        "display_name": display_name,
        "avatar_mode": link.account_avatar_mode or "auto",
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


async def _existing_destination_title(db: AsyncSession, destination_url: str) -> str | None:
    raw = await db.scalar(
        select(Link.destination_title)
        .where(
            Link.destination_url == destination_url,
            Link.destination_title.isnot(None),
            Link.destination_title != "",
        )
        .limit(1)
    )
    title = (raw or "").strip()
    return title or None


async def _sync_destination_title(
    db: AsyncSession,
    destination_url: str,
    destination_title: str | None,
) -> None:
    cleaned = (destination_title or "").strip() or None
    await db.execute(
        update(Link)
        .where(Link.destination_url == destination_url)
        .values(destination_title=cleaned)
    )


def _serialize_link_row(row: dict) -> dict[str, Any]:
    link: Link = row["link"]
    base = _serialize_link(link)
    account_display = row.get("account_display") or base["account_display"]
    return {
        **base,
        "account_display": account_display,
        "display_name": (link.title or "").strip() or account_display,
        "total": int(row.get("total") or 0),
        "today": int(row.get("today") or 0),
        "period_clicks": int(row.get("period_clicks") or 0),
        "period_uniques": int(row.get("period_uniques") or 0),
    }


class LoginBody(BaseModel):
    password: str


class LinkCreateBody(BaseModel):
    destination_url: str
    destination_title: str | None = None
    title: str | None = None
    label: str | None = None


class LinkUpdateBody(BaseModel):
    destination_url: str | None = None
    destination_title: str | None = None
    title: str | None = None
    label: str | None = None


class BulkDestBody(BaseModel):
    destination_url: str
    destination_title: str | None = None
    link_ids: list[str] = Field(default_factory=list)


class BulkIdsBody(BaseModel):
    link_ids: list[str] = Field(default_factory=list)


# ——— Auth ———


@router.get("/auth/me")
async def auth_me(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    ip = client_ip(request)
    banned, _ = await is_ip_banned_now(db, ip)
    admin = bool(request.session.get("admin"))
    # CSRF выдаём всегда: SPA шлёт его на login после первого GET /me
    csrf = get_or_create_csrf_token(request)
    return JSONResponse(
        {
            "admin": admin,
            "csrf_token": csrf,
            "blocked": banned,
            "block_message": MSG_BAN_HTML if banned else None,
        }
    )


@router.post("/auth/login")
async def auth_login(
    request: Request,
    body: LoginBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    settings = get_settings()
    ip = client_ip(request)
    banned, _ = await is_ip_banned_now(db, ip)
    if banned:
        return JSONResponse(
            {"ok": False, "blocked": True, "error": MSG_BAN_HTML},
            status_code=403,
        )
    if verify_env_password(body.password, settings.admin_password):
        await clear_admin_failures(db, ip)
        request.session.clear()
        request.session["admin"] = True
        csrf = rotate_csrf_token(request)
        return JSONResponse({"ok": True, "csrf_token": csrf})
    banned_now = await record_admin_password_failure(db, ip)
    if banned_now:
        return JSONResponse(
            {"ok": False, "blocked": True, "error": MSG_BAN_HTML},
            status_code=403,
        )
    return JSONResponse({"ok": False, "error": "Неверный пароль"}, status_code=401)


@router.post("/auth/logout")
async def auth_logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


# ——— Dashboard ———


@router.get("/dashboard")
async def dashboard_json(
    request: Request,
    db: AsyncSession = Depends(get_db),
    platform: str = Query("all"),
    account: str | None = Query(None),
    destination: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
    sort: str | None = Query(None),
    order: str | None = Query(None),
) -> JSONResponse:
    _require_admin(request)
    try:
        dash = await load_dashboard_page_data(
            db,
            platform=platform,
            account=account,
            destination=destination,
            date_from=date_from,
            date_to=date_to,
            preset=preset,
            sort=sort,
            order=order,
        )
    except Exception:
        log.exception("dashboard_json failed")
        raise HTTPException(status_code=500, detail="Dashboard load failed") from None

    plat_counts = await cached_platform_link_counts(db)
    destination_filters = await destination_link_filters(db)

    platform_filters = [
        {"id": "all", "label": "Все", "color": None, "count": plat_counts.get("all", 0)},
        {
            "id": "none",
            "label": "Без платформы",
            "color": None,
            "count": plat_counts.get("none", 0),
        },
    ]
    for p in PLATFORMS:
        platform_filters.append(
            {
                "id": p["id"],
                "label": p["label"],
                "color": p["color"],
                "count": plat_counts.get(p["id"], 0),
            }
        )

    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "links": [_serialize_link_row(r) for r in dash["link_rows"]],
            "destination_filters": destination_filters,
            "platform_filters": platform_filters,
            "platforms": PLATFORMS,
            "filter_platform": dash["filter_platform"],
            "filter_account": dash["filter_account"],
            "filter_destination": dash["filter_destination"],
            "sort_by": dash.get("sort_by"),
            "sort_order": dash.get("sort_order"),
            "active_preset": dash["active_preset"],
            "period_from": dash["period_from"],
            "period_to": dash["period_to"],
            "period_label": dash["period_label"],
            "period_total": dash["period_total"],
            "period_uniques": dash["period_uniques"],
            "platform_stats": dash["platform_stats"],
            "filter_qs": dash["filter_qs"],
            "base_url": base,
        }
    )


# ——— Links ———


@router.post("/links")
async def create_link(
    request: Request,
    body: LinkCreateBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    if not _valid_url(body.destination_url):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
    dest_url = body.destination_url.strip()
    groups = group_accounts_by_platform(body.label)
    # Без аккаунтов или одна платформа — одна ссылка; разные платформы — по ссылке на группу
    if not groups:
        groups = [(None, [])]

    dest_title = (body.destination_title or "").strip() or None
    if dest_title is None:
        dest_title = await _existing_destination_title(db, dest_url)

    created: list[Link] = []
    for _, accounts in groups:
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=dest_url)
        apply_link_title(link, body.title)
        apply_destination_title(link, dest_title)
        apply_link_accounts(link, accounts)
        db.add(link)
        created.append(link)
    if dest_title is not None:
        await _sync_destination_title(db, dest_url, dest_title)
    for link in created:
        await bootstrap_link_avatar(db, link)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse(
        {
            "link": _serialize_link(created[0]),
            "links": [_serialize_link(l) for l in created],
            "created": len(created),
        },
        status_code=201,
    )


@router.post("/links/bulk-destination")
async def bulk_destination(
    request: Request,
    body: BulkDestBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    if not _valid_url(body.destination_url):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
    if not body.link_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну ссылку")
    if len(body.link_ids) > MAX_BULK_DEST_UPDATE:
        raise HTTPException(status_code=400, detail=f"Не больше {MAX_BULK_DEST_UPDATE} ссылок")
    try:
        ids = [uuid.UUID(x) for x in body.link_ids]
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Некорректный id") from e
    unique_ids = list(dict.fromkeys(ids))
    dest_url = body.destination_url.strip()
    dest_title = (body.destination_title or "").strip() or None
    if dest_title is None:
        dest_title = await _existing_destination_title(db, dest_url)
    result = await db.execute(
        update(Link)
        .where(Link.id.in_(unique_ids))
        .values(destination_url=dest_url, destination_title=dest_title)
    )
    if dest_title is not None:
        await _sync_destination_title(db, dest_url, dest_title)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"updated": int(result.rowcount or 0)})


@router.post("/links/bulk-delete")
async def bulk_delete_links(
    request: Request,
    body: BulkIdsBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    if not body.link_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну ссылку")
    if len(body.link_ids) > MAX_BULK_DEST_UPDATE:
        raise HTTPException(status_code=400, detail=f"Не больше {MAX_BULK_DEST_UPDATE} ссылок")
    try:
        ids = [uuid.UUID(x) for x in body.link_ids]
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Некорректный id") from e
    unique_ids = list(dict.fromkeys(ids))
    await db.execute(delete(Click).where(Click.link_id.in_(unique_ids)))
    result = await db.execute(delete(Link).where(Link.id.in_(unique_ids)))
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"deleted": int(result.rowcount or 0)})


@router.post("/links/import-csv")
async def import_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> JSONResponse:
    _require_admin(request)
    raw = await file.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой")
    try:
        text = raw.decode("utf-8-sig")
        rows = parse_links_import_csv(text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    created = 0
    for row in rows:
        if not _valid_url(row.destination_url):
            continue
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=row.destination_url.strip())
        apply_link_label(link, row.label)
        db.add(link)
        await bootstrap_link_avatar(db, link, allow_http=False)
        created += 1
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"created": created})


@router.get("/links/{link_id}")
async def get_link(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse({"link": _serialize_link(link)})


@router.patch("/links/{link_id}")
async def update_link(
    request: Request,
    link_id: uuid.UUID,
    body: LinkUpdateBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    if body.destination_url is not None:
        if not _valid_url(body.destination_url):
            raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
        link.destination_url = body.destination_url.strip()
    if body.title is not None:
        apply_link_title(link, body.title)
    if body.destination_title is not None:
        apply_destination_title(link, body.destination_title)
    elif body.destination_url is not None:
        inherited = await _existing_destination_title(db, link.destination_url)
        if inherited is not None:
            apply_destination_title(link, inherited)
    extra_links: list[Link] = []
    if body.label is not None:
        groups = group_accounts_by_platform(body.label)
        if not groups:
            apply_link_accounts(link, [])
        else:
            apply_link_accounts(link, groups[0][1])
            dest_url = link.destination_url
            title = link.title
            dest_title = link.destination_title
            for _, accounts in groups[1:]:
                slug = await _unique_slug(db)
                extra = Link(slug=slug, destination_url=dest_url)
                apply_link_title(extra, title)
                apply_destination_title(extra, dest_title)
                apply_link_accounts(extra, accounts)
                db.add(extra)
                extra_links.append(extra)
            for extra in extra_links:
                await bootstrap_link_avatar(db, extra)
    if body.destination_title is not None or (
        body.destination_url is not None and link.destination_title
    ):
        await _sync_destination_title(db, link.destination_url, link.destination_title)
    await db.commit()
    invalidate_link_avatar_cache(link.id)
    invalidate_dashboard_counts_cache()
    return JSONResponse(
        {
            "link": _serialize_link(link),
            "created_extra": len(extra_links),
            "extra_links": [_serialize_link(l) for l in extra_links],
        }
    )


@router.delete("/links/{link_id}")
async def delete_link(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    await db.execute(delete(Click).where(Click.link_id == link_id))
    await db.delete(link)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"ok": True})


@router.delete("/links/{link_id}/clicks")
async def clear_link_clicks(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    await db.execute(delete(Click).where(Click.link_id == link_id))
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"ok": True})


@router.get("/links/{link_id}/stats")
async def link_stats_json(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    if (link.account_avatar_mode or "auto") == "auto" and not link.account_avatar_url:
        await bootstrap_link_avatar(db, link, allow_http=False)
        await db.commit()
    start, end = stats_range(link, date_from, date_to, preset, default_preset="all")
    active = active_preset(date_from, date_to, preset, default="all")
    period_from, period_to = form_period_dates(start, end)
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)
    os_rows = await top_os(session=db, link_id=link.id, start=start, end=end)
    device_rows = await top_device_types(session=db, link_id=link.id, start=start, end=end)
    day_rows = await stats_by_day(session=db, link_id=link.id, start=start, end=end)
    geoip_db_present = (
        resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
    )
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "link": _serialize_link(link),
            "short_url": f"{base}/r/{link.slug}",
            "total": total,
            "uniques": uniq,
            "active_preset": active,
            "period_from": period_from,
            "period_to": period_to,
            "charts": {
                "clicks_by_day": bar_chart_items([(d["day"], d["clicks"]) for d in day_rows]),
                "countries": bar_chart_items([(c or "—", n) for c, n in countries]),
                "os": bar_chart_items(os_rows),
                "devices": bar_chart_items(device_rows),
            },
            "countries_missing_code": any((not cc) for cc, _ in countries),
            "geoip_db_present": geoip_db_present,
        }
    )


# ——— Indicators ———


@router.get("/indicators")
async def indicators_json(
    request: Request,
    db: AsyncSession = Depends(get_db),
    platform: str = Query("all"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> JSONResponse:
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    active = active_preset(date_from, date_to, preset, default=DASHBOARD_DEFAULT_PRESET)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    period_from, period_to = form_period_dates(start, end)

    id_stmt = apply_link_filters(select(Link.id), platform=platform)
    link_ids = [row[0] for row in (await db.execute(id_stmt)).all()]
    period_total, period_uniques = await aggregate_clicks_for_links(db, link_ids, start, end)
    os_rows = await top_os_for_links(db, link_ids, start, end)
    device_rows = await top_device_types_for_links(db, link_ids, start, end)
    plat_stats_raw = await platform_click_stats(db, link_ids, start, end)

    platform_filters = [{"id": "all", "label": "Все", "color": None}]
    for p in PLATFORMS:
        platform_filters.append({"id": p["id"], "label": p["label"], "color": p["color"]})
    platform_filters.append({"id": "none", "label": "Без платформы", "color": "#525a70"})

    period_label = {
        "today": "Сегодня (UTC)",
        "week": "7 дней",
        "all": "Всё время",
        "custom": f"{period_from} — {period_to}",
    }.get(active, period_from)

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

    return JSONResponse(
        {
            "filter_platform": platform,
            "active_preset": active,
            "period_from": period_from,
            "period_to": period_to,
            "period_label": period_label,
            "period_total": period_total,
            "period_uniques": period_uniques,
            "platform_filters": platform_filters,
            "platform_stats": platform_stats,
            "charts": {
                "os": bar_chart_items(os_rows),
                "devices": bar_chart_items(device_rows),
                "platforms": bar_chart_items(
                    [
                        (
                            "Без платформы"
                            if p["platform"] == "none"
                            else platform_label(p["platform"]),
                            p["clicks"],
                        )
                        for p in plat_stats_raw
                    ],
                    colors={
                        (
                            "Без платформы"
                            if p["platform"] == "none"
                            else platform_label(p["platform"])
                        ): (
                            "#525a70"
                            if p["platform"] == "none"
                            else platform_color(p["platform"])
                        )
                        for p in plat_stats_raw
                    },
                ),
            },
        }
    )


