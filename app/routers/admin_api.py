"""Session JSON API for SPA admin (cookie + CSRF)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin_dashboard import load_dashboard_page_data
from app.admin_helpers import (
    apply_link_filters,
    cached_sidebar_link_counts,
    earliest_link_created_at,
    load_profiles,
    parse_profile_id,
    resolve_stats_period,
)
from app.config import get_settings
from app.csrf import get_or_create_csrf_token, rotate_csrf_token
from app.database import get_db
from app.models import Click, Link, Profile
from app.platforms import PLATFORMS, PROFILE_COLORS, platform_color, platform_label
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
from app.services.links_meta import apply_link_label, apply_link_profile
from app.services.stats import (
    aggregate_clicks_for_links,
    bar_chart_items,
    platform_click_stats,
    profile_click_stats,
    stats_by_day,
    stats_summary,
    top_countries,
    top_device_types,
    top_device_types_for_links,
    top_os,
    top_os_for_links,
)
from app.services.stats_cache import invalidate_dashboard_counts_cache
from app.stats_range import DASHBOARD_DEFAULT_PRESET, active_preset, form_period_dates, stats_range
from app.url_validation import is_valid_destination_url
from app.utils.bulk_labels import MAX_BULK_LABELS, parse_label_lines
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


def _serialize_link(link: Link) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "slug": link.slug,
        "destination_url": link.destination_url,
        "label": link.label,
        "platform": link.platform,
        "platform_label": platform_label(link.platform),
        "platform_color": platform_color(link.platform),
        "profile_id": str(link.profile_id) if link.profile_id else None,
        "profile": (
            {"id": str(link.profile.id), "name": link.profile.name, "color": link.profile.color}
            if getattr(link, "profile", None)
            else None
        ),
        "account_avatar_url": admin_avatar_href(link),
        "avatar_mode": link.account_avatar_mode or "auto",
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


def _serialize_link_row(row: dict) -> dict[str, Any]:
    link: Link = row["link"]
    return {
        **_serialize_link(link),
        "account_display": row.get("account_display") or link.label or link.slug,
        "total": int(row.get("total") or 0),
        "today": int(row.get("today") or 0),
        "period_clicks": int(row.get("period_clicks") or 0),
        "period_uniques": int(row.get("period_uniques") or 0),
    }


def _serialize_profile(p: Profile) -> dict[str, Any]:
    return {"id": str(p.id), "name": p.name, "color": p.color}


class LoginBody(BaseModel):
    password: str


class LinkCreateBody(BaseModel):
    destination_url: str
    label: str | None = None
    profile_id: str | None = ""


class LinkBulkBody(BaseModel):
    destination_url: str
    labels: str
    profile_id: str | None = ""


class LinkUpdateBody(BaseModel):
    destination_url: str | None = None
    label: str | None = None
    profile_id: str | None = Field(default=None)


class BulkDestBody(BaseModel):
    destination_url: str
    link_ids: list[str] = Field(default_factory=list)


class ProfileCreateBody(BaseModel):
    name: str
    color: str | None = None


class ProfileUpdateBody(BaseModel):
    name: str | None = None
    color: str | None = None


# ——— Auth ———


@router.get("/auth/me")
async def auth_me(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    ip = client_ip(request)
    banned, _ = await is_ip_banned_now(db, ip)
    admin = bool(request.session.get("admin"))
    csrf = get_or_create_csrf_token(request) if admin or True else None
    # Always issue CSRF so login POST can send it after first GET /me
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
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
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
            profile=profile,
            platform=platform,
            account=account,
            date_from=date_from,
            date_to=date_to,
            preset=preset,
            sort=sort,
            order=order,
        )
    except Exception:
        log.exception("dashboard_json failed")
        raise HTTPException(status_code=500, detail="Dashboard load failed") from None

    profiles = await load_profiles(db)
    prof_counts, plat_counts = await cached_sidebar_link_counts(db)

    profile_filters = [
        {"id": "all", "name": "Все профили", "color": None, "count": prof_counts.get("all", 0)},
        {"id": "none", "name": "Без профиля", "color": None, "count": prof_counts.get("none", 0)},
    ]
    for p in profiles:
        profile_filters.append(
            {
                "id": str(p.id),
                "name": p.name,
                "color": p.color,
                "count": prof_counts.get(str(p.id), 0),
            }
        )

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
            "profiles": [_serialize_profile(p) for p in profiles],
            "profile_filters": profile_filters,
            "platform_filters": platform_filters,
            "platforms": PLATFORMS,
            "filter_profile": dash["filter_profile"],
            "filter_platform": dash["filter_platform"],
            "filter_account": dash["filter_account"],
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
    slug = await _unique_slug(db)
    link = Link(slug=slug, destination_url=body.destination_url.strip())
    apply_link_label(link, body.label)
    apply_link_profile(link, parse_profile_id(body.profile_id or ""))
    db.add(link)
    await bootstrap_link_avatar(db, link)
    await db.commit()
    await db.refresh(link, attribute_names=["profile"])
    invalidate_dashboard_counts_cache()
    return JSONResponse({"link": _serialize_link(link)}, status_code=201)


@router.post("/links/bulk")
async def bulk_create_links(
    request: Request,
    body: LinkBulkBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    if not _valid_url(body.destination_url):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
    label_list = parse_label_lines(body.labels)
    if not label_list:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы один аккаунт")
    if len(label_list) > MAX_BULK_LABELS:
        raise HTTPException(status_code=400, detail=f"Не больше {MAX_BULK_LABELS} аккаунтов")
    pid = parse_profile_id(body.profile_id or "")
    dest_url = body.destination_url.strip()
    new_links: list[Link] = []
    for label in label_list:
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=dest_url)
        apply_link_label(link, label)
        apply_link_profile(link, pid)
        db.add(link)
        new_links.append(link)
    for link in new_links:
        await bootstrap_link_avatar(db, link, allow_http=False)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"created": len(label_list)})


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
    result = await db.execute(
        update(Link).where(Link.id.in_(unique_ids)).values(destination_url=body.destination_url.strip())
    )
    await db.commit()
    return JSONResponse({"updated": int(result.rowcount or 0)})


@router.post("/links/import-csv")
async def import_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    profile_id: str = "",
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
    pid = parse_profile_id(profile_id)
    created = 0
    for row in rows:
        if not _valid_url(row.destination_url):
            continue
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=row.destination_url.strip())
        apply_link_label(link, row.label)
        apply_link_profile(link, pid)
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
    link = (
        await db.execute(select(Link).options(selectinload(Link.profile)).where(Link.id == link_id))
    ).scalar_one_or_none()
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
    link = (
        await db.execute(select(Link).options(selectinload(Link.profile)).where(Link.id == link_id))
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Not found")
    if body.destination_url is not None:
        if not _valid_url(body.destination_url):
            raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
        link.destination_url = body.destination_url.strip()
    if body.label is not None:
        apply_link_label(link, body.label)
    if body.profile_id is not None:
        apply_link_profile(link, parse_profile_id(body.profile_id))
    await db.commit()
    await db.refresh(link, attribute_names=["profile"])
    invalidate_link_avatar_cache(link.id)
    invalidate_dashboard_counts_cache()
    return JSONResponse({"link": _serialize_link(link)})


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
    link = (
        await db.execute(select(Link).options(selectinload(Link.profile)).where(Link.id == link_id))
    ).scalar_one_or_none()
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


# ——— Profiles ———


@router.get("/profiles")
async def list_profiles(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    _require_admin(request)
    profiles = await load_profiles(db)
    counts, _ = await cached_sidebar_link_counts(db)
    items = []
    for p in profiles:
        items.append({**_serialize_profile(p), "count": counts.get(str(p.id), 0)})
    return JSONResponse({"profiles": items, "palette": PROFILE_COLORS})


@router.post("/profiles")
async def create_profile(
    request: Request,
    body: ProfileCreateBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя обязательно")
    color = (body.color or PROFILE_COLORS[0]).strip()
    p = Profile(name=name, color=color)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    invalidate_dashboard_counts_cache()
    return JSONResponse({"profile": _serialize_profile(p)}, status_code=201)


@router.patch("/profiles/{profile_id}")
async def update_profile(
    request: Request,
    profile_id: uuid.UUID,
    body: ProfileUpdateBody,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    p = await db.get(Profile, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Имя обязательно")
        p.name = name
    if body.color is not None:
        p.color = body.color.strip()
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"profile": _serialize_profile(p)})


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    request: Request,
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    p = await db.get(Profile, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    await db.execute(update(Link).where(Link.profile_id == profile_id).values(profile_id=None))
    await db.delete(p)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return JSONResponse({"ok": True})


# ——— Indicators ———


@router.get("/indicators")
async def indicators_json(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
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

    id_stmt = apply_link_filters(select(Link.id), profile=profile, platform=platform)
    link_ids = [row[0] for row in (await db.execute(id_stmt)).all()]
    period_total, period_uniques = await aggregate_clicks_for_links(db, link_ids, start, end)
    os_rows = await top_os_for_links(db, link_ids, start, end)
    device_rows = await top_device_types_for_links(db, link_ids, start, end)
    profile_stats = await profile_click_stats(db, link_ids, start, end)
    plat_stats_raw = await platform_click_stats(db, link_ids, start, end)

    profiles = await load_profiles(db)
    prof_counts, _ = await cached_sidebar_link_counts(db)
    profile_filters = [
        {"id": "all", "name": "Все профили", "color": None, "count": prof_counts.get("all", 0)},
        {"id": "none", "name": "Без профиля", "color": None, "count": prof_counts.get("none", 0)},
    ]
    for p in profiles:
        profile_filters.append(
            {
                "id": str(p.id),
                "name": p.name,
                "color": p.color,
                "count": prof_counts.get(str(p.id), 0),
            }
        )

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

    return JSONResponse(
        {
            "filter_profile": profile,
            "filter_platform": platform,
            "active_preset": active,
            "period_from": period_from,
            "period_to": period_to,
            "period_label": period_label,
            "period_total": period_total,
            "period_uniques": period_uniques,
            "profile_filters": profile_filters,
            "platform_filters": platform_filters,
            "charts": {
                "os": bar_chart_items(os_rows),
                "devices": bar_chart_items(device_rows),
                "profiles": bar_chart_items(
                    [(p["name"], p["clicks"]) for p in profile_stats],
                    colors={p["name"]: p["color"] for p in profile_stats},
                ),
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


@router.get("/links-picker")
async def links_picker(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str = Query(""),
) -> JSONResponse:
    _require_admin(request)
    term = (q or "").strip().lower()
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc()).limit(80)
    links = list((await db.execute(stmt)).scalars().all())
    items = []
    for link in links:
        label = (link.label or link.slug or "").lower()
        if term and term not in label and term not in link.slug.lower():
            continue
        items.append(
            {
                "id": str(link.id),
                "slug": link.slug,
                "label": link.label,
                "display": link.label or link.slug,
            }
        )
    return JSONResponse({"items": items[:40]})
