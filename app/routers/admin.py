import csv
import io
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Click, Link
from app.security import verify_env_password
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.stats import (
    click_day_bucket_utc,
    dashboard_click_counts,
    stats_summary,
    top_countries,
)
from app.utils.slug import random_slug

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _require_admin(request: Request) -> None:
    if request.session.get("admin"):
        return
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/admin/login"},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    password: str = Form(...),
):
    settings = get_settings()
    if verify_env_password(password, settings.admin_password):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Неверный пароль"}
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
):
    _require_admin(request)
    res = await db.execute(select(Link).order_by(Link.created_at.desc()))
    links = list(res.scalars().all())
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("dashboard_click_counts failed")
        counts = {}
    link_rows = [{"link": link, "total": counts.get(link.id, (0, 0))[0], "today": counts.get(link.id, (0, 0))[1]} for link in links]
    return templates.TemplateResponse(
        "link_list.html",
        {
            "request": request,
            "link_rows": link_rows,
            "open_new_link_modal": new == "1",
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
        return templates.TemplateResponse(
            "link_form.html",
            {
                "request": request,
                "link": None,
                "error": msg,
                "title": "Новая ссылка",
            },
            status_code=400,
        )
    slug = await _unique_slug(db)
    link = Link(slug=slug, destination_url=destination_url.strip(), label=(label or "").strip() or None)
    db.add(link)
    await db.commit()
    dest = f"/admin/links/{link.id}/stats"
    if modal:
        return JSONResponse({"redirect": dest})
    return RedirectResponse(dest, status_code=302)


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
    return templates.TemplateResponse(
        "link_form.html",
        {"request": request, "link": link, "error": None, "title": "Правка ссылки"},
    )


@router.post("/links/{link_id}/edit", response_class=HTMLResponse)
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
        return templates.TemplateResponse(
            "link_form.html",
            {
                "request": request,
                "link": link,
                "error": "URL должен начинаться с http:// или https://",
                "title": "Правка ссылки",
            },
            status_code=400,
        )
    link.destination_url = destination_url.strip()
    link.label = (label or "").strip() or None
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


def _parse_range(
    from_s: str | None, to_s: str | None
) -> tuple[datetime, datetime]:
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


@router.get("/links/{link_id}/stats/data")
async def link_stats_data(
    request: Request,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> JSONResponse:
    """JSON для страницы статистики: обновление KPI и топа стран без перезагрузки."""
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    start, end = _parse_range(date_from, date_to)
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
):
    _require_admin(request)
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(404)
    start, end = _parse_range(date_from, date_to)
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
            "period_from": date_from if date_from else start.date().isoformat(),
            "period_to": date_to if date_to else end.date().isoformat(),
            "short_url": short_url,
            "geoip_db_present": geoip_db_present,
            "countries_missing_code": countries_missing_code,
        },
    )


def _csv_stream(rows_iter: Iterator[list[object]], header: list[str]) -> Iterator[bytes]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    yield "\ufeff".encode("utf-8")
    chunk = buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    yield chunk.encode("utf-8")
    for row in rows_iter:
        w.writerow(row)
        chunk = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        yield chunk.encode("utf-8")


@router.get("/export/clicks.csv")
async def export_clicks_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    link_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> StreamingResponse:
    _require_admin(request)
    start, end = _parse_range(date_from, date_to)
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
        _csv_stream(row_iter(), header),
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
    start, end = _parse_range(date_from, date_to)
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
        _csv_stream(row_iter(), ["link_id", "day", "clicks", "uniques"]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{quote(name)}"'},
    )
