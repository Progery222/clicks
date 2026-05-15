"""JSON API v1: один секретный токен (Authorization: Bearer … или X-Api-Key)."""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.csv_stream import stream_csv
from app.database import get_db
from app.models import Click, Link
from app.services.ip_lockout import clear_api_failures, client_ip, record_api_token_failure
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.stats import (
    click_day_bucket_utc,
    dashboard_click_counts,
    stats_summary,
    top_countries,
)
from app.stats_range import active_preset, form_period_dates, parse_range, stats_range
from app.utils.bulk_labels import MAX_BULK_LABELS, normalize_bulk_labels
from app.utils.slug import random_slug

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _safe_token_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


async def require_api_token(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    settings = get_settings()
    expected = (settings.api_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API token is not configured",
        )
    auth = (request.headers.get("Authorization") or "").strip()
    api_key = (request.headers.get("X-Api-Key") or "").strip()
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif api_key:
        token = api_key
    ip = client_ip(request)
    if token and _safe_token_compare(token, expected):
        await clear_api_failures(db, ip)
        return
    await record_api_token_failure(db, ip)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
    )


ApiTokenDep = Annotated[None, Depends(require_api_token)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


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


class LinkCreate(BaseModel):
    destination_url: str
    label: str | None = None


class LinkBulkCreate(BaseModel):
    """Одна целевая ссылка и несколько аккаунтов — по одной короткой ссылке на аккаунт."""

    destination_url: str
    labels: list[str] | None = None
    labels_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class LinksBulkOut(BaseModel):
    created: int
    items: list["LinkOut"]


class LinkPatch(BaseModel):
    destination_url: str | None = None
    label: str | None = None

    model_config = ConfigDict(extra="forbid")


class LinkOut(BaseModel):
    id: uuid.UUID
    slug: str
    destination_url: str
    label: str | None
    created_at: str
    updated_at: str
    total_clicks: int = 0
    today_clicks: int = 0

    @classmethod
    def from_link(
        cls,
        link: Link,
        *,
        total_clicks: int = 0,
        today_clicks: int = 0,
    ) -> LinkOut:
        return cls(
            id=link.id,
            slug=link.slug,
            destination_url=link.destination_url,
            label=link.label,
            created_at=link.created_at.isoformat() if link.created_at else "",
            updated_at=link.updated_at.isoformat() if link.updated_at else "",
            total_clicks=total_clicks,
            today_clicks=today_clicks,
        )


class LinksListOut(BaseModel):
    items: list[LinkOut]
    total: int


class StatsOut(BaseModel):
    total: int
    uniques: int
    period_from: str
    period_to: str
    active_preset: str
    countries: list[dict[str, object]]
    countries_missing_code: bool
    geoip_db_present: bool


class ClickOut(BaseModel):
    id: uuid.UUID
    link_id: uuid.UUID
    created_at: str
    ip: str | None
    user_agent: str | None
    referer: str | None
    country_code: str | None
    region: str | None
    city: str | None
    visitor_id: uuid.UUID | None
    dedupe_key: str


class ClicksPageOut(BaseModel):
    items: list[ClickOut]
    total: int
    page: int
    page_size: int


@router.get("/me")
async def api_me(_: ApiTokenDep) -> dict[str, object]:
    return {
        "api": "v1",
        "geoip_db_present": (
            resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
        ),
    }


@router.get("/links", response_model=LinksListOut)
async def list_links(
    _: ApiTokenDep,
    db: DbDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> LinksListOut:
    count_q = await db.execute(select(func.count()).select_from(Link))
    total = int(count_q.scalar_one())
    res = await db.execute(select(Link).order_by(Link.created_at.desc()).limit(limit).offset(offset))
    links = list(res.scalars().all())
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_v1 list_links: dashboard_click_counts failed")
        counts = {}
    items = [
        LinkOut.from_link(
            link,
            total_clicks=counts.get(link.id, (0, 0))[0],
            today_clicks=counts.get(link.id, (0, 0))[1],
        )
        for link in links
    ]
    return LinksListOut(items=items, total=total)


@router.post("/links", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(_: ApiTokenDep, db: DbDep, body: LinkCreate) -> LinkOut:
    if not _valid_url(body.destination_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )
    slug = await _unique_slug(db)
    link = Link(
        slug=slug,
        destination_url=body.destination_url.strip(),
        label=(body.label or "").strip() or None,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return LinkOut.from_link(link)


def _resolve_bulk_labels(body: LinkBulkCreate) -> list[str]:
    raw: list[str] = []
    if body.labels:
        raw.extend(body.labels)
    if body.labels_text:
        raw.extend(body.labels_text.splitlines())
    if not body.labels and not body.labels_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide accounts via labels (array) or labels_text (multiline string)",
        )
    label_list = normalize_bulk_labels(raw)
    if not label_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one non-empty account is required",
        )
    if len(label_list) > MAX_BULK_LABELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_BULK_LABELS} accounts per request",
        )
    return label_list


@router.post("/links/bulk", response_model=LinksBulkOut, status_code=status.HTTP_201_CREATED)
async def create_links_bulk(_: ApiTokenDep, db: DbDep, body: LinkBulkCreate) -> LinksBulkOut:
    if not _valid_url(body.destination_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )
    label_list = _resolve_bulk_labels(body)
    dest_url = body.destination_url.strip()
    created_links: list[Link] = []
    for label in label_list:
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=dest_url, label=label)
        db.add(link)
        created_links.append(link)
    await db.commit()
    for link in created_links:
        await db.refresh(link)
    items = [LinkOut.from_link(link) for link in created_links]
    return LinksBulkOut(created=len(items), items=items)


@router.get("/links/{link_id}", response_model=LinkOut)
async def get_link(link_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> LinkOut:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_v1 get_link: dashboard_click_counts failed")
        counts = {}
    t, d = counts.get(link.id, (0, 0))
    return LinkOut.from_link(link, total_clicks=t, today_clicks=d)


@router.patch("/links/{link_id}", response_model=LinkOut)
async def patch_link(
    link_id: uuid.UUID,
    _: ApiTokenDep,
    db: DbDep,
    body: LinkPatch,
) -> LinkOut:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        await db.refresh(link)
        try:
            counts = await dashboard_click_counts(db)
        except Exception:
            log.exception("api_v1 patch_link: dashboard_click_counts failed")
            counts = {}
        t, d = counts.get(link.id, (0, 0))
        return LinkOut.from_link(link, total_clicks=t, today_clicks=d)
    if "destination_url" in data:
        url = data["destination_url"]
        assert isinstance(url, str)
        if not _valid_url(url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL must start with http:// or https://",
            )
        link.destination_url = url.strip()
    if "label" in data:
        raw = data["label"]
        if raw is None:
            link.label = None
        else:
            assert isinstance(raw, str)
            link.label = raw.strip() or None
    await db.commit()
    await db.refresh(link)
    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_v1 patch_link: dashboard_click_counts failed")
        counts = {}
    t, d = counts.get(link.id, (0, 0))
    return LinkOut.from_link(link, total_clicks=t, today_clicks=d)


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> Response:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    await db.execute(delete(Link).where(Link.id == link_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/links/{link_id}/stats", response_model=StatsOut)
async def link_stats(
    link_id: uuid.UUID,
    _: ApiTokenDep,
    db: DbDep,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StatsOut:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    start, end = stats_range(link, date_from, date_to, preset)
    active = active_preset(date_from, date_to, preset)
    period_from, period_to = form_period_dates(start, end)
    total, uniq = await stats_summary(session=db, link_id=link.id, start=start, end=end)
    countries = await top_countries(session=db, link_id=link.id, start=start, end=end)
    geoip_db_present = (
        resolved_city_mmdb_path() is not None or resolved_country_mmdb_path() is not None
    )
    countries_missing_code = any((not cc) for cc, _ in countries)
    return StatsOut(
        total=total,
        uniques=uniq,
        period_from=period_from,
        period_to=period_to,
        active_preset=active,
        countries=[{"code": c or "", "count": n} for c, n in countries],
        countries_missing_code=countries_missing_code,
        geoip_db_present=geoip_db_present,
    )


@router.get("/links/{link_id}/clicks", response_model=ClicksPageOut)
async def list_clicks(
    link_id: uuid.UUID,
    _: ApiTokenDep,
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ClicksPageOut:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    count_q = await db.execute(
        select(func.count()).select_from(Click).where(Click.link_id == link_id)
    )
    total = int(count_q.scalar_one())
    offset = (page - 1) * page_size
    res = await db.execute(
        select(Click)
        .where(Click.link_id == link_id)
        .order_by(Click.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    rows = res.scalars().all()
    items = [
        ClickOut(
            id=c.id,
            link_id=c.link_id,
            created_at=c.created_at.isoformat() if c.created_at else "",
            ip=c.ip,
            user_agent=c.user_agent,
            referer=c.referer,
            country_code=c.country_code,
            region=c.region,
            city=c.city,
            visitor_id=c.visitor_id,
            dedupe_key=c.dedupe_key,
        )
        for c in rows
    ]
    return ClicksPageOut(items=items, total=total, page=page, page_size=page_size)


@router.delete("/links/{link_id}/clicks", status_code=status.HTTP_204_NO_CONTENT)
async def clear_clicks(link_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> Response:
    link = await db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
    await db.execute(delete(Click).where(Click.link_id == link_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export/clicks.csv")
async def export_clicks_csv(
    _: ApiTokenDep,
    db: DbDep,
    link_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> StreamingResponse:
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
    _: ApiTokenDep,
    db: DbDep,
    link_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> StreamingResponse:
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
