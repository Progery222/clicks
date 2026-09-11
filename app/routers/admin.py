import logging
import uuid
from collections.abc import Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_helpers import (
    apply_click_link_filters,
    apply_link_filters,
    build_filter_query,
    earliest_link_created_at,
    link_filter_predicates,
    resolve_stats_period,
)
from app.config import get_settings
from app.csrf import rotate_csrf_token
from app.csv_stream import stream_csv
from app.database import get_db
from app.models import Click, Link
from app.platforms import platform_label
from app.spa import spa_index_response
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
from app.services.links_meta import apply_link_label
from app.security import verify_env_password
from app.services.ip_lockout import (
    clear_admin_failures,
    client_ip,
    record_admin_password_failure,
)
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.stats import (
    bar_chart_items,
    click_counts_for_links_period,
    click_day_bucket_utc,
    dashboard_click_counts,
    stats_by_day,
    stats_summary,
    top_countries,
    top_device_types,
    top_os,
)
from app.services.stats_cache import invalidate_dashboard_counts_cache
from app.stats_range import stats_range
from app.utils.csv_import import MAX_IMPORT_BYTES, parse_links_import_csv
from app.utils.slug import random_slug
from app.url_validation import is_valid_destination_url

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request) -> None:
    if request.session.get("admin"):
        return
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/admin/login"},
    )


@router.get("/login")
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=302)
    return spa_index_response()


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Legacy form login → redirect; SPA uses /admin/api/auth/login."""
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
        return RedirectResponse("/admin/login?blocked=1", status_code=302)
    return RedirectResponse("/admin/login?error=1", status_code=302)


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


@router.get("")
async def dashboard(request: Request):
    return spa_index_response()





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


@router.get("/profiles")
async def profiles_page(request: Request):
    return spa_index_response()



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
):
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"

    if not _valid_url(destination_url):
        msg = "URL должен начинаться с http:// или https://"
        if modal:
            return JSONResponse({"error": msg}, status_code=400)
        raise HTTPException(status_code=400, detail=msg)
    slug = await _unique_slug(db)
    link = Link(slug=slug, destination_url=destination_url.strip())
    apply_link_label(link, label)
    db.add(link)
    await bootstrap_link_avatar(db, link)
    await db.commit()
    dest = f"/admin/links/{link.id}/stats"
    if modal:
        return JSONResponse({"redirect": dest})
    return RedirectResponse(dest, status_code=302)


@router.post("/links/import-csv")
async def link_import_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    _require_admin(request)
    modal = (request.headers.get("x-modal-form") or "").strip() == "1"
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
        db.add(link)
        imported.append(link)
        created += 1
    for link in imported:
        await bootstrap_link_avatar(db, link, allow_http=False)
    await db.commit()

    redirect = "/admin"
    if modal:
        return JSONResponse({"redirect": redirect, "created": created})
    return RedirectResponse(redirect, status_code=302)


@router.get("/links/{link_id}/edit")
async def link_edit_get(request: Request, link_id: uuid.UUID):
    return RedirectResponse(f"/admin/links/{link_id}/stats", status_code=302)


@router.post("/links/{link_id}/edit")
async def link_edit_post(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    destination_url: str = Form(...),
    label: str | None = Form(None),
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    if not _valid_url(destination_url):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
    link.destination_url = destination_url.strip()
    apply_link_label(link, label)
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
    platform: str = Query("all"),
    account: str | None = Query(None),
) -> RedirectResponse:
    """Удалить все ссылки, попадающие под текущие фильтры платформы/аккаунта."""
    _require_admin(request)
    stmt = delete(Link)
    for pred in link_filter_predicates(platform, account):
        stmt = stmt.where(pred)
    await db.execute(stmt)
    await db.commit()
    return RedirectResponse(
        "/admin" + build_filter_query(
            platform, account=account), status_code=302
    )


@router.post("/links/clicks/clear-all")
async def clear_all_link_clicks(
    request: Request,
    db: AsyncSession = Depends(get_db),
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
    stmt = apply_click_link_filters(stmt, platform=platform, account=account)
    await db.execute(stmt)
    await db.commit()
    invalidate_dashboard_counts_cache()
    return RedirectResponse(
        "/admin"
        + build_filter_query(
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


@router.get("/links/{link_id}/stats")
async def link_stats(request: Request, link_id: uuid.UUID):
    return spa_index_response()



@router.get("/indicators")
async def admin_indicators_alias():
    return spa_index_response()


@router.get("/export/links.csv")
async def export_links_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    platform: str = Query("all"),
    account: str | None = Query(None),
    destination: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
    """Список ссылок (фильтры + клики за период)."""
    _require_admin(request)
    earliest = await earliest_link_created_at(db)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    stmt = select(Link).order_by(Link.created_at.desc())
    stmt = apply_link_filters(
        stmt,
        platform=platform,
        account=account,
        destination=destination,
    )
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
    platform: str = Query("all"),
    account: str | None = Query(None),
    destination: str | None = Query(None),
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
        stmt = apply_click_link_filters(
            stmt,
            platform=platform,
            account=account,
            destination=destination,
        )
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
    platform: str = Query("all"),
    account: str | None = Query(None),
    destination: str | None = Query(None),
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
            select(Link.id),
            platform=platform,
            account=account,
            destination=destination,
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
