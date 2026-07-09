import json
import logging
import uuid
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin_dashboard import load_dashboard_page_data
from app.admin_helpers import (
    apply_click_link_filters,
    apply_link_filters,
    build_filter_query,
    earliest_link_created_at,
    link_filter_predicates,
    load_profiles,
    parse_profile_id,
    platform_link_counts,
    profile_link_counts,
    cached_sidebar_link_counts,
    resolve_stats_period,
)
from app.config import get_settings
from app.csrf import get_or_create_csrf_token, rotate_csrf_token
from app.csv_stream import stream_csv
from app.database import get_db
from app.models import Click, Link, Profile
from app.platforms import PLATFORMS, platform_color, platform_label
from app.services.label_match import account_label_display
from app.services.account_avatar import (
    AVATAR_MODES,
    bootstrap_link_avatar,
    scrape_link_avatar,
    set_custom_avatar_url,
    set_link_avatar_mode,
    set_uploaded_avatar,
)
from app.services.admin_avatar import admin_avatar_href, stream_link_avatar
from app.services.avatar_image_cache import invalidate_link_avatar_cache
from app.services.avatar_upload import delete_link_avatar_upload, is_upload_avatar_url
from app.services.links_meta import apply_link_label, apply_link_profile
from app.security import verify_env_password
from app.services.ip_lockout import (
    clear_admin_failures,
    client_ip,
    is_ip_banned_now,
    record_admin_password_failure,
    MSG_BAN_HTML,
)
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.stats import (
    aggregate_clicks_for_links,
    bar_chart_items,
    click_counts_for_links_period,
    click_day_bucket_utc,
    dashboard_click_counts,
    platform_click_stats,
    profile_click_stats,
    stats_by_day,
    stats_summary,
    top_countries,
    top_device_types,
    top_device_types_for_links,
    top_os,
    top_os_for_links,
    top_referers,
    top_user_agents,
)
from app.services.stats_cache import (
    invalidate_dashboard_counts_cache,
    invalidate_sidebar_counts_cache,
)
from app.stats_range import (
    DASHBOARD_DEFAULT_PRESET,
    active_preset,
    dashboard_stats_range,
    form_period_dates,
    parse_range,
    stats_range,
)
from app.utils.bulk_labels import MAX_BULK_LABELS, parse_label_lines
from app.utils.csv_import import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS, parse_links_import_csv
from app.template_globals import register_template_globals
from app.utils.slug import random_slug
from app.url_validation import is_valid_destination_url

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
MAX_BULK_DEST_UPDATE = 500

_templates_dir = str(Path(__file__).resolve().parent.parent / "templates")
templates = Jinja2Templates(directory=_templates_dir)
register_template_globals(templates.env)
templates.env.globals["admin_filter_href"] = (
    lambda prof, plat: "/admin" + build_filter_query(prof, plat)
)


def _indicators_filter_href(
    profile: str,
    platform: str,
    *,
    active_preset: str,
    period_from: str,
    period_to: str,
    preset: str | None = None,
) -> str:
    p = preset
    if p is None and active_preset != "custom":
        p = active_preset if active_preset != "all" else None
    return "/indicators" + build_filter_query(
        profile,
        platform,
        preset=p,
        date_from=period_from if active_preset == "custom" else None,
        date_to=period_to if active_preset == "custom" else None,
    )


templates.env.globals["indicators_filter_href"] = (
    lambda prof, plat: _indicators_filter_href(prof, plat, active_preset="all", period_from="", period_to="")
)
templates.env.globals["get_csrf_token"] = get_or_create_csrf_token


def _require_admin(request: Request) -> None:
    if request.session.get("admin"):
        return
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/admin/login"},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=302)
    ip = client_ip(request)
    blocked = request.query_params.get("blocked") == "1"
    banned_now, _ = await is_ip_banned_now(db, ip)
    if banned_now:
        blocked = True
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "blocked": blocked,
            "block_message": MSG_BAN_HTML if blocked else None,
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    ip = client_ip(request)
    if verify_env_password(password, settings.admin_password):
        await clear_admin_failures(db, ip)
        request.session.clear()
        request.session["admin"] = True
        rotate_csrf_token(request)
        return RedirectResponse("/admin", status_code=302)
    banned = await record_admin_password_failure(db, ip)
    if banned:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": None,
                "blocked": True,
                "block_message": MSG_BAN_HTML,
            },
        )
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Неверный пароль",
            "blocked": False,
            "block_message": None,
        },
    )


@router.post("/logout")
async def logout_post(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


@router.get("/logout")
async def logout_get(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


@router.get("/avatar/{link_id}")
async def link_avatar(
    link_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    return await stream_link_avatar(db, link, request)


@router.get("/links/{link_id}/avatar/state")
async def link_avatar_state(
    link_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    return JSONResponse(
        {
            "mode": link.account_avatar_mode or "auto",
            "avatar_url": admin_avatar_href(link),
            "label": link.label or link.slug,
            "custom_url": (
                link.account_avatar_url
                if link.account_avatar_url
                and not is_upload_avatar_url(link.account_avatar_url)
                and str(link.account_avatar_url).startswith(("http://", "https://"))
                else ""
            ),
        }
    )


@router.post("/links/{link_id}/avatar/url")
async def link_avatar_set_url(
    link_id: uuid.UUID,
    request: Request,
    url: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    try:
        await set_custom_avatar_url(db, link, url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    await db.refresh(link)
    return JSONResponse(
        {
            "ok": True,
            "mode": link.account_avatar_mode,
            "avatar_url": admin_avatar_href(link),
        }
    )


@router.post("/links/{link_id}/avatar/upload")
async def link_avatar_upload(
    link_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    content = await file.read()
    try:
        await set_uploaded_avatar(db, link, content, declared_type=file.content_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    await db.refresh(link)
    return JSONResponse(
        {
            "ok": True,
            "mode": link.account_avatar_mode,
            "avatar_url": admin_avatar_href(link),
        }
    )


@router.post("/links/{link_id}/avatar/scrape")
async def link_avatar_scrape(
    link_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    pic = await scrape_link_avatar(db, link)
    await db.commit()
    await db.refresh(link)
    return JSONResponse(
        {
            "ok": bool(pic),
            "mode": link.account_avatar_mode,
            "avatar_url": admin_avatar_href(link),
        }
    )


@router.post("/links/{link_id}/avatar/mode")
async def link_avatar_mode_post(
    link_id: uuid.UUID,
    request: Request,
    mode: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _require_admin(request)
    if mode not in AVATAR_MODES:
        raise HTTPException(status_code=400, detail="invalid mode")
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    await set_link_avatar_mode(db, link, mode)
    await db.commit()
    await db.refresh(link)
    return JSONResponse(
        {
            "ok": True,
            "mode": link.account_avatar_mode,
            "avatar_url": admin_avatar_href(link),
        }
    )


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    new: str | None = Query(None),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
    sort: str | None = Query(None),
    order: str | None = Query(None),
):
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
        log.exception("load_dashboard_page_data failed")
        dash = {
            "link_rows": [],
            "filter_profile": profile,
            "filter_platform": platform,
            "filter_account": (account or "").strip(),
            "filter_qs": build_filter_query(profile, platform, account=account),
            "active_preset": "all",
            "period_from": "",
            "period_to": "",
            "period_label": "Всё время",
            "period_total": 0,
            "period_uniques": 0,
            "platform_stats": [],
            "period_hrefs": {
                "today": "/admin"
                + build_filter_query(profile, platform, account=account, preset="today"),
                "week": "/admin"
                + build_filter_query(profile, platform, account=account, preset="week"),
                "all": "/admin" + build_filter_query(profile, platform, account=account),
            },
            "admin_filter_href": lambda prof, plat: "/admin"
            + build_filter_query(prof, plat, account=account),
        }
    profiles = await load_profiles(db)
    prof_counts, plat_counts = await cached_sidebar_link_counts(db)
    profile_filters = [
        {"id": "all", "name": "Все профили", "color": None, "count": prof_counts.get("all", 0)},
        {
            "id": "none",
            "name": "Без профиля",
            "color": None,
            "count": prof_counts.get("none", 0),
        },
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
    platform_filters = [{"id": "all", "label": "Все", "color": None, "count": plat_counts.get("all", 0)}]
    platform_filters.append(
        {
            "id": "none",
            "label": "Без платформы",
            "color": None,
            "count": plat_counts.get("none", 0),
        }
    )
    for p in PLATFORMS:
        platform_filters.append(
            {
                "id": p["id"],
                "label": p["label"],
                "color": p["color"],
                "count": plat_counts.get(p["id"], 0),
            }
        )
    default_profile_id = None
    if profile not in ("all", "none"):
        default_profile_id = parse_profile_id(profile)
    return templates.TemplateResponse(
        "link_list.html",
        {
            "request": request,
            "open_new_link_modal": new == "1",
            "profiles": profiles,
            "platforms": PLATFORMS,
            "profile_filters": profile_filters,
            "platform_filters": platform_filters,
            "selected_profile_id": default_profile_id,
            **dash,
        },
    )


@router.get("/api/link-counts")
async def api_link_counts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> JSONResponse:
    """Счётчики по ссылкам для polling: всего, сегодня UTC, за выбранный период."""
    _require_admin(request)
    stmt = select(Link.id)
    stmt = apply_link_filters(stmt, profile=profile, platform=platform, account=account)
    link_ids = list((await db.execute(stmt)).scalars().all())
    earliest = await earliest_link_created_at(db)
    start, end = dashboard_stats_range(date_from, date_to, preset, earliest=earliest)
    try:
        all_time = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_link_counts: dashboard_click_counts failed")
        all_time = {}
    try:
        period_map = await click_counts_for_links_period(db, link_ids, start, end)
    except Exception:
        period_map = {}
    payload = {}
    for lid in link_ids:
        t, d = all_time.get(lid, (0, 0))
        pc, pu = period_map.get(lid, (0, 0))
        payload[str(lid)] = {"total": t, "today": d, "period": pc, "period_uniques": pu}
    return JSONResponse({"counts": payload})


@router.get("/api/traffic-insights")
async def api_traffic_insights(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> JSONResponse:
    """Топ referer и user-agent за период (для модалки на /admin)."""
    _require_admin(request)
    stmt = select(Link.id)
    stmt = apply_link_filters(stmt, profile=profile, platform=platform, account=account)
    link_ids = list((await db.execute(stmt)).scalars().all())
    earliest_row = await db.execute(select(func.min(Link.created_at)))
    earliest = earliest_row.scalar_one_or_none()
    start, end = dashboard_stats_range(date_from, date_to, preset, earliest=earliest)
    try:
        referers = await top_referers(db, link_ids, start, end)
        user_agents = await top_user_agents(db, link_ids, start, end)
    except Exception:
        log.exception("api_traffic_insights failed")
        referers, user_agents = [], []
    return JSONResponse(
        {
            "referers": [{"label": label, "count": cnt} for label, cnt in referers],
            "user_agents": [{"label": label, "count": cnt} for label, cnt in user_agents],
        }
    )


def _valid_url(url: str) -> bool:
    settings = get_settings()
    return is_valid_destination_url(
        url,
        allow_private_hosts=settings.allow_private_destination_urls,
    )


async def _unique_slug(db: AsyncSession) -> str:
    for _ in range(40):
        s = random_slug(7)
        exists = await db.execute(select(Link.id).where(Link.slug == s))
        if exists.scalar_one_or_none() is None:
            return s
    raise RuntimeError("Could not allocate slug")


@router.get("/profiles", response_class=HTMLResponse)
async def profiles_page(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    profiles = await load_profiles(db)
    counts = await profile_link_counts(db)
    profile_counts: dict[uuid.UUID, int] = {p.id: counts.get(str(p.id), 0) for p in profiles}
    return templates.TemplateResponse(
        "profiles.html",
        {"request": request, "profiles": profiles, "profile_counts": profile_counts},
    )


@router.post("/profiles/new")
async def profile_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    color: str = Form("#6366f1"),
):
    _require_admin(request)
    n = (name or "").strip()
    if not n:
        raise HTTPException(status_code=400, detail="Имя профиля обязательно")
    c = (color or "#6366f1").strip()
    if not c.startswith("#") or len(c) > 7:
        c = "#6366f1"
    db.add(Profile(name=n, color=c))
    await db.commit()
    return RedirectResponse("/admin/profiles", status_code=302)


@router.post("/profiles/{profile_id}/edit")
async def profile_edit(
    request: Request,
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    color: str = Form("#6366f1"),
    next: str = Form("/admin"),
) -> RedirectResponse:
    _require_admin(request)
    p = await db.get(Profile, profile_id)
    if p is None:
        raise HTTPException(404)
    n = (name or "").strip()
    if not n:
        raise HTTPException(status_code=400, detail="Имя профиля обязательно")
    c = (color or "#6366f1").strip()
    if not c.startswith("#") or len(c) > 7:
        c = "#6366f1"
    p.name = n
    p.color = c
    await db.commit()
    dest = (next or "/admin").strip()
    if not dest.startswith("/admin"):
        dest = "/admin"
    return RedirectResponse(dest, status_code=302)


@router.post("/profiles/{profile_id}/delete")
async def profile_delete(
    request: Request,
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    next: str = Form("/admin/profiles"),
) -> RedirectResponse:
    _require_admin(request)
    await db.execute(delete(Profile).where(Profile.id == profile_id))
    await db.commit()
    dest = (next or "/admin/profiles").strip()
    if not dest.startswith("/admin"):
        dest = "/admin/profiles"
    return RedirectResponse(dest, status_code=302)


@router.get("/links/new")
async def link_new_get(request: Request) -> RedirectResponse:
    """Создание ссылки — только модальное окно на /admin (редирект для старых закладок)."""
    _require_admin(request)
    return RedirectResponse("/admin?new=1", status_code=302)


@router.post("/links/new")
async def link_new_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    destination_url: str = Form(...),
    label: str | None = Form(None),
    profile_id: str = Form(""),
):
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"
    profiles = await load_profiles(db)

    if not _valid_url(destination_url):
        msg = "URL должен начинаться с http:// или https://"
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        return templates.TemplateResponse(
            "link_form.html",
            {
                "request": request,
                "link": None,
                "error": msg,
                "title": "Новая ссылка",
                "profiles": profiles,
                "selected_profile_id": parse_profile_id(profile_id),
            },
            status_code=400,
        )
    slug = await _unique_slug(db)
    link = Link(slug=slug, destination_url=destination_url.strip())
    apply_link_label(link, label)
    apply_link_profile(link, parse_profile_id(profile_id))
    db.add(link)
    await bootstrap_link_avatar(db, link)
    await db.commit()
    dest = f"/admin/links/{link.id}/stats"
    if modal:
        return JSONResponse({"redirect": dest})
    return RedirectResponse(dest, status_code=302)


@router.post("/links/bulk")
async def link_bulk_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    destination_url: str = Form(...),
    labels: str = Form(...),
    profile_id: str = Form(""),
):
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"
    pid = parse_profile_id(profile_id)

    if not _valid_url(destination_url):
        msg = "URL должен начинаться с http:// или https://"
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)

    label_list = parse_label_lines(labels)
    if not label_list:
        msg = "Добавьте хотя бы один аккаунт (по одному на строку)."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)
    if len(label_list) > MAX_BULK_LABELS:
        msg = f"Не больше {MAX_BULK_LABELS} аккаунтов за раз."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)

    dest_url = destination_url.strip()
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

    prof_q = str(pid) if pid else "all"
    redirect = "/admin" + build_filter_query(prof_q, "all")
    if modal:
        return JSONResponse({"redirect": redirect, "created": len(label_list)})
    return RedirectResponse(redirect, status_code=302)


@router.get("/api/links-picker")
async def api_links_picker(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
) -> JSONResponse:
    """Ссылки для модалки массовой смены целевого URL (фильтр профиля и платформы)."""
    _require_admin(request)
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc())
    stmt = apply_link_filters(stmt, profile=profile, platform=platform)
    links = list((await db.execute(stmt)).scalars().all())
    items = []
    for link in links:
        items.append(
            {
                "id": str(link.id),
                "slug": link.slug,
                "account": account_label_display(link.label) or "—",
                "profile_id": str(link.profile_id) if link.profile_id else None,
                "profile_name": link.profile.name if link.profile else None,
                "platform": link.platform,
                "platform_label": platform_label(link.platform) if link.platform else None,
                "destination_url": link.destination_url,
            }
        )
    return JSONResponse({"items": items})


@router.post("/links/bulk-destination")
async def links_bulk_destination(
    request: Request,
    db: AsyncSession = Depends(get_db),
    destination_url: str = Form(...),
    link_ids: Annotated[list[str], Form()] = [],
):
    """Обновить целевой URL у выбранных ссылок."""
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"

    if not _valid_url(destination_url):
        msg = "URL должен начинаться с http:// или https://"
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)

    raw_ids = [x.strip() for x in link_ids if x and x.strip()]
    if not raw_ids:
        msg = "Выберите хотя бы одну ссылку."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)
    if len(raw_ids) > MAX_BULK_DEST_UPDATE:
        msg = f"Не больше {MAX_BULK_DEST_UPDATE} ссылок за раз."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)

    try:
        ids = [uuid.UUID(x) for x in raw_ids]
    except ValueError:
        msg = "Некорректный идентификатор ссылки."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)

    unique_ids = list(dict.fromkeys(ids))
    dest = destination_url.strip()
    result = await db.execute(
        update(Link).where(Link.id.in_(unique_ids)).values(destination_url=dest)
    )
    await db.commit()
    updated = int(result.rowcount or 0)
    if updated == 0:
        msg = "Не найдено ссылок для обновления."
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=404, detail=msg)

    redirect = "/admin"
    if modal:
        return JSONResponse({"redirect": redirect, "updated": updated})
    return RedirectResponse(redirect, status_code=302)


@router.post("/links/import-csv")
async def link_import_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    profile_id: str = Form(""),
):
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"
    pid = parse_profile_id(profile_id)
    try:
        raw_bytes = await file.read()
        if len(raw_bytes) > MAX_IMPORT_BYTES:
            msg = f"Файл слишком большой (максимум {MAX_IMPORT_BYTES // (1024 * 1024)} МБ)"
            if modal:
                return JSONResponse({"error": msg}, status_code=400)
            raise HTTPException(status_code=400, detail=msg)
        raw = raw_bytes.decode("utf-8-sig")
        rows = parse_links_import_csv(raw)
    except ValueError as e:
        msg = str(e)
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg) from e
    except UnicodeDecodeError as e:
        msg = "Файл должен быть в кодировке UTF-8"
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg) from e

    created = 0
    imported: list[Link] = []
    for row in rows:
        if not _valid_url(row.destination_url):
            msg = f"Неверный URL: {row.destination_url[:80]}"
            if modal:
                return JSONResponse({"error": msg}, status_code=400)
            raise HTTPException(status_code=400, detail=msg)
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=row.destination_url.strip())
        apply_link_label(link, row.label)
        apply_link_profile(link, pid)
        db.add(link)
        imported.append(link)
        created += 1
    for link in imported:
        await bootstrap_link_avatar(db, link, allow_http=False)
    await db.commit()

    prof_q = str(pid) if pid else "all"
    redirect = "/admin" + build_filter_query(prof_q, "all")
    if modal:
        return JSONResponse({"redirect": redirect, "created": created})
    return RedirectResponse(redirect, status_code=302)


@router.get("/links/{link_id}/edit", response_class=HTMLResponse)
async def link_edit_get(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    profiles = await load_profiles(db)
    return templates.TemplateResponse(
        "link_form.html",
        {
            "request": request,
            "link": link,
            "error": None,
            "title": "Правка ссылки",
            "profiles": profiles,
            "selected_profile_id": link.profile_id,
        },
    )


@router.post("/links/{link_id}/edit", response_class=HTMLResponse)
async def link_edit_post(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    destination_url: str = Form(...),
    label: str | None = Form(None),
    profile_id: str = Form(""),
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    profiles = await load_profiles(db)
    if not _valid_url(destination_url):
        return templates.TemplateResponse(
            "link_form.html",
            {
                "request": request,
                "link": link,
                "error": "URL должен начинаться с http:// или https://",
                "title": "Правка ссылки",
                "profiles": profiles,
                "selected_profile_id": link.profile_id,
            },
            status_code=400,
        )
    link.destination_url = destination_url.strip()
    apply_link_label(link, label)
    apply_link_profile(link, parse_profile_id(profile_id))
    await bootstrap_link_avatar(db, link)
    await db.commit()
    return RedirectResponse(f"/admin/links/{link.id}/stats", status_code=302)


@router.post("/links/{link_id}/delete")
async def link_delete(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    invalidate_link_avatar_cache(link_id)
    delete_link_avatar_upload(link_id)
    await db.execute(delete(Link).where(Link.id == link_id))
    await db.commit()
    return RedirectResponse("/admin", status_code=302)


@router.post("/links/delete-all")
async def links_delete_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
) -> RedirectResponse:
    """Удалить все ссылки, попадающие под текущие фильтры профиля и платформы."""
    _require_admin(request)
    stmt = delete(Link)
    for pred in link_filter_predicates(profile, platform, account):
        stmt = stmt.where(pred)
    await db.execute(stmt)
    await db.commit()
    return RedirectResponse(
        "/admin" + build_filter_query(profile, platform, account=account), status_code=302
    )


@router.post("/links/clicks/clear-all")
async def clear_all_link_clicks(
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
) -> RedirectResponse:
    """Удалить записи кликов по ссылкам из текущих фильтров (сами ссылки остаются)."""
    _require_admin(request)
    stmt = delete(Click)
    stmt = apply_click_link_filters(stmt, profile=profile, platform=platform, account=account)
    await db.execute(stmt)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return RedirectResponse(
        "/admin"
        + build_filter_query(
            profile,
            platform,
            account=account,
            preset=preset,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            order=order,
        ),
        status_code=302,
    )


@router.post("/links/{link_id}/clicks/clear")
async def clear_link_clicks(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Удалить все записи кликов по ссылке (сама ссылка остаётся)."""
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    await db.execute(delete(Click).where(Click.link_id == link_id))
    await db.commit()
    invalidate_dashboard_counts_cache()
    return RedirectResponse(f"/admin/links/{link.id}/stats", status_code=302)


@router.get("/links/{link_id}/stats/data")
async def link_stats_data(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> JSONResponse:
    """JSON для страницы статистики: обновление KPI и топа стран без перезагрузки."""
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    start, end = stats_range(
        link, date_from, date_to, preset, default_preset="all"
    )
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)
    os_rows = await top_os(session=db, link_id=link.id, start=start, end=end)
    device_rows = await top_device_types(session=db, link_id=link.id, start=start, end=end)
    day_rows = await stats_by_day(session=db, link_id=link.id, start=start, end=end)
    geoip_db_present = (
        resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
    )
    countries_missing_code = any((not cc) for cc, _ in countries)
    return JSONResponse(
        {
            "total": total,
            "uniques": uniq,
            "countries": [{"code": c or "", "count": n} for c, n in countries],
            "os": [{"label": label, "count": n} for label, n in os_rows],
            "devices": [{"label": label, "count": n} for label, n in device_rows],
            "charts": {
                "clicks_by_day": bar_chart_items(
                    [(d["day"], d["clicks"]) for d in day_rows]
                ),
                "countries": bar_chart_items([(c or "—", n) for c, n in countries]),
                "os": bar_chart_items(os_rows),
                "devices": bar_chart_items(device_rows),
            },
            "countries_missing_code": countries_missing_code,
            "geoip_db_present": geoip_db_present,
        }
    )


@router.get("/links/{link_id}/stats", response_class=HTMLResponse)
async def link_stats(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    if (link.account_avatar_mode or "auto") == "auto" and not link.account_avatar_url:
        await bootstrap_link_avatar(db, link, allow_http=False)
        await db.commit()
    start, end = stats_range(
        link, date_from, date_to, preset, default_preset="all"
    )
    active = active_preset(date_from, date_to, preset, default="all")
    period_from, period_to = form_period_dates(start, end)
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)
    os_rows = await top_os(session=db, link_id=link.id, start=start, end=end)
    device_rows = await top_device_types(session=db, link_id=link.id, start=start, end=end)
    day_rows = await stats_by_day(session=db, link_id=link.id, start=start, end=end)
    clicks_chart = bar_chart_items([(d["day"], d["clicks"]) for d in day_rows])
    countries_chart = bar_chart_items([(c or "—", n) for c, n in countries])
    os_chart = bar_chart_items(os_rows)
    device_chart = bar_chart_items(device_rows)

    geoip_db_present = (
        resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
    )
    countries_missing_code = any((not cc) for cc, _ in countries)
    base = str(request.base_url).rstrip("/")
    short_url = f"{base}/r/{link.slug}"
    return templates.TemplateResponse(
        "link_stats.html",
        {
            "request": request,
            "link": link,
            "total": total,
            "uniques": uniq,
            "countries": countries,
            "os_rows": os_rows,
            "device_rows": device_rows,
            "clicks_chart": clicks_chart,
            "countries_chart": countries_chart,
            "os_chart": os_chart,
            "device_chart": device_chart,
            "period_from": period_from,
            "period_to": period_to,
            "active_preset": active,
            "short_url": short_url,
            "geoip_db_present": geoip_db_present,
            "countries_missing_code": countries_missing_code,
            "avatar_src": admin_avatar_href(link),
            "avatar_mode": link.account_avatar_mode or "auto",
        },
    )


async def render_indicators_page(
    request: Request,
    db: AsyncSession,
    *,
    profile: str = "all",
    platform: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    preset: str | None = None,
):
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    active = active_preset(
        date_from, date_to, preset, default=DASHBOARD_DEFAULT_PRESET
    )
    start, end = resolve_stats_period(
        date_from, date_to, preset, earliest=earliest
    )
    period_from, period_to = form_period_dates(start, end)

    id_stmt = apply_link_filters(select(Link.id), profile=profile, platform=platform)
    link_ids = [row[0] for row in (await db.execute(id_stmt)).all()]

    period_total, period_uniques = await aggregate_clicks_for_links(
        db, link_ids, start, end
    )
    os_rows = await top_os_for_links(db, link_ids, start, end)
    device_rows = await top_device_types_for_links(db, link_ids, start, end)
    profile_stats = await profile_click_stats(db, link_ids, start, end)
    plat_stats_raw = await platform_click_stats(db, link_ids, start, end)

    os_chart = bar_chart_items(os_rows)
    device_chart = bar_chart_items(device_rows)
    profile_chart = bar_chart_items(
        [(p["name"], p["clicks"]) for p in profile_stats],
        colors={p["name"]: p["color"] for p in profile_stats},
    )
    platform_chart = bar_chart_items(
        [
            (
                "Без платформы" if p["platform"] == "none" else platform_label(p["platform"]),
                p["clicks"],
            )
            for p in plat_stats_raw
        ],
        colors={
            (
                "Без платформы" if p["platform"] == "none" else platform_label(p["platform"])
            ): (
                "#525a70" if p["platform"] == "none" else platform_color(p["platform"])
            )
            for p in plat_stats_raw
        },
    )

    platform_filters = [
        {"id": "all", "label": "Все", "color": None},
    ]
    for p in PLATFORMS:
        platform_filters.append(
            {
                "id": p["id"],
                "label": p["label"],
                "color": p["color"],
            }
        )
    platform_filters.append(
        {"id": "none", "label": "Без платформы", "color": "#525a70"}
    )

    period_hrefs = {
        "today": _indicators_filter_href(
            profile, platform, active_preset=active, period_from=period_from,
            period_to=period_to, preset="today",
        ),
        "week": _indicators_filter_href(
            profile, platform, active_preset=active, period_from=period_from,
            period_to=period_to, preset="week",
        ),
        "all": _indicators_filter_href(
            profile, platform, active_preset=active, period_from=period_from,
            period_to=period_to, preset="all",
        ),
    }

    if active == "today":
        period_label = "Сегодня (UTC)"
    elif active == "week":
        period_label = "7 дней"
    elif active == "all":
        period_label = "Всё время"
    else:
        period_label = f"{period_from} — {period_to}"

    def indicators_href(prof: str, plat: str) -> str:
        return _indicators_filter_href(
            prof,
            plat,
            active_preset=active,
            period_from=period_from,
            period_to=period_to,
            preset=active if active != "custom" else None,
        )

    return templates.TemplateResponse(
        "indicators.html",
        {
            "request": request,
            "filter_profile": profile,
            "filter_platform": platform,
            "active_preset": active,
            "period_from": period_from,
            "period_to": period_to,
            "period_label": period_label,
            "period_total": period_total,
            "period_uniques": period_uniques,
            "period_hrefs": period_hrefs,
            "platform_filters": platform_filters,
            "os_chart": os_chart,
            "device_chart": device_chart,
            "profile_chart": profile_chart,
            "platform_chart": platform_chart,
            "indicators_filter_href": indicators_href,
        },
    )


@router.get("/indicators", response_class=HTMLResponse)
async def admin_indicators_alias(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
):
    return await render_indicators_page(
        request,
        db,
        profile=profile,
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        preset=preset,
    )


@router.get("/export/links.csv")
async def export_links_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
    """Список ссылок (фильтры + клики за период)."""
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc())
    stmt = apply_link_filters(stmt, profile=profile, platform=platform, account=account)
    links = list((await db.execute(stmt)).scalars().all())
    link_ids = [link.id for link in links]
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("export_links_csv: dashboard_click_counts failed")
        counts = {}
    try:
        period_map = await click_counts_for_links_period(db, link_ids, start, end)
    except Exception:
        period_map = {}
    base = str(request.base_url).rstrip("/")

    def row_iter() -> Iterator[list[object]]:
        for link in links:
            total, today = counts.get(link.id, (0, 0))
            period_clicks, period_uniques = period_map.get(link.id, (0, 0))
            yield [
                str(link.id),
                link.slug,
                f"{base}/r/{link.slug}",
                link.profile.name if link.profile else "",
                platform_label(link.platform) if link.platform else "",
                link.platform or "",
                link.label or "",
                link.destination_url,
                total,
                today,
                period_clicks,
                period_uniques,
                link.created_at.isoformat() if link.created_at else "",
            ]

    header = [
        "id",
        "slug",
        "short_url",
        "profile",
        "platform_label",
        "platform",
        "account",
        "destination_url",
        "clicks_total",
        "clicks_today",
        "clicks_period",
        "uniques_period",
        "created_at",
    ]
    name = "links.csv"
    return StreamingResponse(
        stream_csv(row_iter(), header),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{quote(name)}"'},
    )


@router.get("/export/clicks.csv")
async def export_clicks_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    link_id: uuid.UUID | None = Query(None),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    stmt = select(Click).where(Click.created_at >= start, Click.created_at < end)
    if link_id is not None:
        stmt = stmt.where(Click.link_id == link_id)
    else:
        stmt = apply_click_link_filters(stmt, profile=profile, platform=platform, account=account)
    stmt = stmt.order_by(Click.created_at)
    res = await db.execute(stmt)
    rows = res.scalars().all()

    def row_iter() -> Iterator[list[object]]:
        for c in rows:
            yield [
                str(c.id),
                str(c.link_id),
                c.created_at.isoformat() if c.created_at else "",
                c.ip or "",
                (c.user_agent or "").replace("\n", " "),
                (c.referer or "").replace("\n", " "),
                c.country_code or "",
                c.region or "",
                c.city or "",
                str(c.visitor_id) if c.visitor_id else "",
                c.dedupe_key,
            ]

    header = [
        "id",
        "link_id",
        "created_at",
        "ip",
        "user_agent",
        "referer",
        "country_code",
        "region",
        "city",
        "visitor_id",
        "dedupe_key",
    ]
    name = f"clicks_{start.date()}_{end.date()}.csv"
    return StreamingResponse(
        stream_csv(row_iter(), header),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{quote(name)}"'},
    )


@router.get("/export/summary.csv")
async def export_summary_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    link_id: uuid.UUID | None = Query(None),
    profile: str = Query("all"),
    platform: str = Query("all"),
    account: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    day = click_day_bucket_utc().label("day")
    stmt = (
        select(
            Click.link_id,
            day,
            func.count().label("clicks"),
            func.count(func.distinct(Click.dedupe_key)).label("uniques"),
        )
        .where(Click.created_at >= start, Click.created_at < end)
        .group_by(Click.link_id, day)
        .order_by(Click.link_id, day)
    )
    if link_id is not None:
        stmt = stmt.where(Click.link_id == link_id)
    else:
        link_ids = apply_link_filters(
            select(Link.id), profile=profile, platform=platform, account=account
        )
        stmt = stmt.where(Click.link_id.in_(link_ids))
    res = await db.execute(stmt)
    raw = res.all()

    def row_iter() -> Iterator[list[object]]:
        for r in raw:
            d = r.day
            day_s = d.date().isoformat() if hasattr(d, "date") else str(d)
            yield [str(r.link_id), day_s, int(r.clicks), int(r.uniques)]

    name = f"summary_{start.date()}_{end.date()}.csv"
    return StreamingResponse(
        stream_csv(row_iter(), ["link_id", "day", "clicks", "uniques"]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{quote(name)}"'},
    )
