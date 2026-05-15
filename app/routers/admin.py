import json
import logging
import uuid
from collections.abc import Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin_helpers import (
    apply_link_filters,
    build_filter_query,
    load_profiles,
    parse_profile_id,
    platform_link_counts,
    profile_link_counts,
)
from app.config import get_settings
from app.csv_stream import stream_csv
from app.database import get_db
from app.models import Click, Link, Profile
from app.platforms import PLATFORMS, platform_color, platform_label
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
    click_day_bucket_utc,
    dashboard_click_counts,
    stats_summary,
    top_countries,
)
from app.stats_range import active_preset, form_period_dates, parse_range, stats_range
from app.utils.bulk_labels import MAX_BULK_LABELS, parse_label_lines
from app.utils.slug import random_slug

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

_templates_dir = str(Path(__file__).resolve().parent.parent / "templates")
templates = Jinja2Templates(directory=_templates_dir)
templates.env.globals["admin_filter_href"] = (
    lambda prof, plat: "/admin" + build_filter_query(prof, plat)
)


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
        request.session["admin"] = True
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


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    new: str | None = Query(None),
    profile: str = Query("all"),
    platform: str = Query("all"),
):
    _require_admin(request)
    stmt = select(Link).options(selectinload(Link.profile)).order_by(Link.created_at.desc())
    stmt = apply_link_filters(stmt, profile=profile, platform=platform)
    links = list((await db.execute(stmt)).scalars().all())
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("dashboard_click_counts failed")
        counts = {}
    link_rows = [
        {
            "link": link,
            "total": counts.get(link.id, (0, 0))[0],
            "today": counts.get(link.id, (0, 0))[1],
            "platform_label": platform_label(link.platform),
            "platform_color": platform_color(link.platform),
        }
        for link in links
    ]
    profiles = await load_profiles(db)
    prof_counts = await profile_link_counts(db)
    plat_counts = await platform_link_counts(db)
    profile_filters = [
        {"id": "all", "name": "Все", "color": None, "count": prof_counts.get("all", 0)},
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
            "link_rows": link_rows,
            "open_new_link_modal": new == "1",
            "profiles": profiles,
            "platforms": PLATFORMS,
            "filter_profile": profile,
            "filter_platform": platform,
            "profile_filters": profile_filters,
            "platform_filters": platform_filters,
            "filter_qs": build_filter_query(profile, platform),
            "selected_profile_id": default_profile_id,
        },
    )


@router.get("/api/link-counts")
async def api_link_counts(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Актуальные «всего» и «сегодня» (UTC) по ссылкам для обновления без перезагрузки."""
    _require_admin(request)
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_link_counts: dashboard_click_counts failed")
        counts = {}
    payload = {str(lid): {"total": t, "today": d} for lid, (t, d) in counts.items()}
    return JSONResponse({"counts": payload})


def _valid_url(url: str) -> bool:
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


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
    c = (color or "#6366f1").strip()
    if not c.startswith("#") or len(c) > 7:
        c = "#6366f1"
    db.add(Profile(name=name.strip(), color=c))
    await db.commit()
    return RedirectResponse("/admin/profiles", status_code=302)


@router.post("/profiles/{profile_id}/delete")
async def profile_delete(
    request: Request,
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    _require_admin(request)
    await db.execute(delete(Profile).where(Profile.id == profile_id))
    await db.commit()
    return RedirectResponse("/admin/profiles", status_code=302)


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
    for label in label_list:
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=dest_url)
        apply_link_label(link, label)
        apply_link_profile(link, pid)
        db.add(link)
    await db.commit()

    prof_q = str(pid) if pid else "all"
    redirect = "/admin" + build_filter_query(prof_q, "all")
    if modal:
        return JSONResponse({"redirect": redirect, "created": len(label_list)})
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
    await db.execute(delete(Link).where(Link.id == link_id))
    await db.commit()
    return RedirectResponse("/admin", status_code=302)


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
    start, end = stats_range(link, date_from, date_to, preset)
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)
    geoip_db_present = (
        resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
    )
    countries_missing_code = any((not cc) for cc, _ in countries)
    return JSONResponse(
        {
            "total": total,
            "uniques": uniq,
            "countries": [{"code": c or "", "count": n} for c, n in countries],
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
    start, end = stats_range(link, date_from, date_to, preset)
    active = active_preset(date_from, date_to, preset)
    period_from, period_to = form_period_dates(start, end)
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)

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
            "period_from": period_from,
            "period_to": period_to,
            "active_preset": active,
            "short_url": short_url,
            "geoip_db_present": geoip_db_present,
            "countries_missing_code": countries_missing_code,
        },
    )


@router.get("/export/clicks.csv")
async def export_clicks_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    link_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> StreamingResponse:
    _require_admin(request)
    start, end = parse_range(date_from, date_to)
    stmt = select(Click).where(Click.created_at >= start, Click.created_at < end)
    if link_id is not None:
        stmt = stmt.where(Click.link_id == link_id)
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
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> StreamingResponse:
    _require_admin(request)
    start, end = parse_range(date_from, date_to)
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
