"""JSON API v1: один секретный токен (Authorization: Bearer … или X-Api-Key)."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.csv_stream import stream_csv
from app.admin_helpers import (
    apply_click_link_filters,
    apply_link_filters,
    earliest_link_created_at,
    resolve_stats_period,
)
from app.database import get_db
from app.models import Click, Link, Profile
from app.platforms import PLATFORMS, platform_label
from app.services.account_avatar import bootstrap_link_avatar
from app.services.avatar_image_cache import invalidate_link_avatar_cache
from app.services.links_meta import apply_link_label, apply_link_profile
from app.url_validation import is_valid_destination_url
from app.services.ip_lockout import clear_api_failures, client_ip, record_api_token_failure
from app.services.rate_limit import allow_request
from app.services.geoip import resolved_city_mmdb_path, resolved_country_mmdb_path
from app.services.stats import (
    click_day_bucket_utc,
    dashboard_click_counts,
    stats_summary,
    top_countries,
)
from app.stats_range import DASHBOARD_DEFAULT_PRESET, active_preset, form_period_dates, parse_range, stats_range
from app.services.label_match import normalize_account_label
from app.utils.bulk_labels import MAX_BULK_LABELS, normalize_bulk_labels
from app.utils.csv_import import MAX_IMPORT_BYTES, parse_links_import_csv
from app.utils.slug import random_slug

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _safe_token_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(
        hashlib.sha256(a.encode("utf-8")).digest(),
        hashlib.sha256(b.encode("utf-8")).digest(),
    )


async def require_api_token(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    settings = get_settings()
    ip = client_ip(request)
    if not allow_request(ip, limit_per_minute=settings.api_rate_limit_per_minute, bucket="api"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many API requests",
            headers={"Retry-After": "60"},
        )
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


class ProfileCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class ProfilePatch(BaseModel):
    name: str | None = None
    color: str | None = None

    model_config = ConfigDict(extra="forbid")


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    link_count: int = 0
    created_at: str
    updated_at: str


class ProfilesListOut(BaseModel):
    items: list[ProfileOut]
    total: int


class LinkCreate(BaseModel):
    destination_url: str
    label: str | None = None
    profile_id: uuid.UUID | None = None


class LinkBulkCreate(BaseModel):
    """Одна целевая ссылка и несколько аккаунтов — по одной короткой ссылке на аккаунт."""

    destination_url: str
    labels: list[str] | None = None
    labels_text: str | None = None
    profile_id: uuid.UUID | None = None

    model_config = ConfigDict(extra="forbid")


class LinksBulkOut(BaseModel):
    created: int
    items: list["LinkOut"]


class LinkPatch(BaseModel):
    destination_url: str | None = None
    label: str | None = None
    profile_id: uuid.UUID | None = None
    clear_profile: bool = False

    model_config = ConfigDict(extra="forbid")


class LinkOut(BaseModel):
    id: uuid.UUID
    slug: str
    destination_url: str
    label: str | None
    platform: str | None = None
    platform_label: str | None = None
    profile_id: uuid.UUID | None = None
    profile_name: str | None = None
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
        prof = link.profile if hasattr(link, "profile") else None
        return cls(
            id=link.id,
            slug=link.slug,
            destination_url=link.destination_url,
            label=link.label,
            platform=link.platform,
            platform_label=platform_label(link.platform),
            profile_id=link.profile_id,
            profile_name=prof.name if prof else None,
            created_at=link.created_at.isoformat() if link.created_at else "",
            updated_at=link.updated_at.isoformat() if link.updated_at else "",
            total_clicks=total_clicks,
            today_clicks=today_clicks,
        )


class LinksListOut(BaseModel):
    items: list[LinkOut]
    total: int


class LinkResolveClicksIn(BaseModel):
    """URL профилей из дашборда — вернуть total_clicks по совпадению label ссылки."""

    profile_urls: list[str]

    model_config = ConfigDict(extra="forbid")


class LinkResolveClicksItem(BaseModel):
    profile_url: str
    total_clicks: int = 0


class LinkResolveClicksOut(BaseModel):
    items: list[LinkResolveClicksItem]


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
        "platforms": PLATFORMS,
    }


async def _ensure_profile(db: AsyncSession, profile_id: uuid.UUID | None) -> uuid.UUID | None:
    if profile_id is None:
        return None
    if await db.get(Profile, profile_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile_id


@router.get("/profiles", response_model=ProfilesListOut)
async def list_profiles(_: ApiTokenDep, db: DbDep) -> ProfilesListOut:
    profiles = list((await db.execute(select(Profile).order_by(Profile.name))).scalars().all())
    counts_rows = (
        await db.execute(select(Link.profile_id, func.count()).group_by(Link.profile_id))
    ).all()
    counts = {str(pid) if pid else "none": int(c) for pid, c in counts_rows}
    items = [
        ProfileOut(
            id=p.id,
            name=p.name,
            color=p.color,
            link_count=counts.get(str(p.id), 0),
            created_at=p.created_at.isoformat() if p.created_at else "",
            updated_at=p.updated_at.isoformat() if p.updated_at else "",
        )
        for p in profiles
    ]
    return ProfilesListOut(items=items, total=len(items))


@router.post("/profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(_: ApiTokenDep, db: DbDep, body: ProfileCreate) -> ProfileOut:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Profile name is required")
    c = (body.color or "#6366f1").strip()
    if not c.startswith("#"):
        c = "#6366f1"
    p = Profile(name=name, color=c[:7])
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return ProfileOut(
        id=p.id,
        name=p.name,
        color=p.color,
        link_count=0,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


@router.get("/profiles/{profile_id}", response_model=ProfileOut)
async def get_profile(profile_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> ProfileOut:
    p = await db.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    cnt = int(
        (
            await db.execute(
                select(func.count()).select_from(Link).where(Link.profile_id == profile_id)
            )
        ).scalar_one()
    )
    return ProfileOut(
        id=p.id,
        name=p.name,
        color=p.color,
        link_count=cnt,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
async def patch_profile(
    profile_id: uuid.UUID,
    _: ApiTokenDep,
    db: DbDep,
    body: ProfilePatch,
) -> ProfileOut:
    p = await db.get(Profile, profile_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Name cannot be empty")
        p.name = name
    if body.color is not None:
        c = body.color.strip()
        if not c.startswith("#"):
            c = "#6366f1"
        p.color = c[:7]
    await db.commit()
    await db.refresh(p)
    cnt = int(
        (
            await db.execute(
                select(func.count()).select_from(Link).where(Link.profile_id == profile_id)
            )
        ).scalar_one()
    )
    return ProfileOut(
        id=p.id,
        name=p.name,
        color=p.color,
        link_count=cnt,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> Response:
    if await db.get(Profile, profile_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    await db.execute(delete(Profile).where(Profile.id == profile_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/links", response_model=LinksListOut)
async def list_links(
    _: ApiTokenDep,
    db: DbDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    profile_id: str | None = Query(None, description="UUID, none, or omit for all"),
    platform: str | None = Query(None, description="Platform slug or omit for all"),
) -> LinksListOut:
    prof_filter = profile_id if profile_id else "all"
    plat_filter = platform if platform else "all"
    id_subq = apply_link_filters(select(Link.id), profile=prof_filter, platform=plat_filter).subquery()
    count_q = await db.execute(select(func.count()).select_from(id_subq))
    total = int(count_q.scalar_one())
    stmt = apply_link_filters(
        select(Link).options(selectinload(Link.profile)),
        profile=prof_filter,
        platform=plat_filter,
    )
    res = await db.execute(stmt.order_by(Link.created_at.desc()).limit(limit).offset(offset))
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


@router.post("/links/resolve-clicks", response_model=LinkResolveClicksOut)
async def resolve_clicks_by_profile_urls(
    _: ApiTokenDep,
    db: DbDep,
    body: LinkResolveClicksIn,
) -> LinkResolveClicksOut:
    """
  Сумма total_clicks по всем коротким ссылкам, у которых label совпадает с URL профиля
  (нормализация как в AccountsStats). До 500 URL за запрос.
    """
    raw_urls = [str(u).strip() for u in (body.profile_urls or []) if str(u).strip()]
    if len(raw_urls) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At most 500 profile_urls per request",
        )
    if not raw_urls:
        return LinkResolveClicksOut(items=[])

    try:
        counts = await dashboard_click_counts(db)
    except Exception:
        log.exception("api_v1 resolve_clicks: dashboard_click_counts failed")
        counts = {}

    res = await db.execute(select(Link.id, Link.label))
    label_index: dict[str, int] = {}
    for link_id, label in res.all():
        key = normalize_account_label(label)
        if not key:
            continue
        t, _ = counts.get(link_id, (0, 0))
        label_index[key] = label_index.get(key, 0) + int(t)

    items: list[LinkResolveClicksItem] = []
    for pu in raw_urls:
        key = normalize_account_label(pu)
        total = int(label_index.get(key, 0)) if key else 0
        items.append(LinkResolveClicksItem(profile_url=pu, total_clicks=total))
    return LinkResolveClicksOut(items=items)


@router.post("/links", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(_: ApiTokenDep, db: DbDep, body: LinkCreate) -> LinkOut:
    if not _valid_url(body.destination_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )
    pid = await _ensure_profile(db, body.profile_id)
    slug = await _unique_slug(db)
    link = Link(slug=slug, destination_url=body.destination_url.strip())
    apply_link_label(link, body.label)
    apply_link_profile(link, pid)
    db.add(link)
    await bootstrap_link_avatar(db, link)
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
    pid = await _ensure_profile(db, body.profile_id)
    dest_url = body.destination_url.strip()
    created_links: list[Link] = []
    for label in label_list:
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=dest_url)
        apply_link_label(link, label)
        apply_link_profile(link, pid)
        db.add(link)
        created_links.append(link)
    for link in created_links:
        await bootstrap_link_avatar(db, link, allow_http=False)
    await db.commit()
    for link in created_links:
        await db.refresh(link)
    items = [LinkOut.from_link(link) for link in created_links]
    return LinksBulkOut(created=len(items), items=items)


@router.get("/links/{link_id}", response_model=LinkOut)
async def get_link(link_id: uuid.UUID, _: ApiTokenDep, db: DbDep) -> LinkOut:
    link = (
        await db.execute(
            select(Link).options(selectinload(Link.profile)).where(Link.id == link_id)
        )
    ).scalar_one_or_none()
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
        apply_link_label(link, None if raw is None else str(raw))
        await bootstrap_link_avatar(db, link)
    if body.clear_profile:
        apply_link_profile(link, None)
    elif "profile_id" in data:
        pid = data["profile_id"]
        apply_link_profile(link, await _ensure_profile(db, pid if isinstance(pid, uuid.UUID) else None))
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
    invalidate_link_avatar_cache(link_id)
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
    start, end = stats_range(
        link, date_from, date_to, preset, default_preset=DASHBOARD_DEFAULT_PRESET
    )
    active = active_preset(date_from, date_to, preset, default=DASHBOARD_DEFAULT_PRESET)
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


@router.post("/links/import-csv", status_code=status.HTTP_201_CREATED)
async def import_links_csv(
    _: ApiTokenDep,
    db: DbDep,
    file: UploadFile = File(...),
    profile_id: uuid.UUID | None = Query(None),
) -> dict[str, object]:
    pid = await _ensure_profile(db, profile_id)
    try:
        raw_bytes = await file.read()
        if len(raw_bytes) > MAX_IMPORT_BYTES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"CSV file too large (max {MAX_IMPORT_BYTES} bytes)",
            )
        raw = raw_bytes.decode("utf-8-sig")
        rows = parse_links_import_csv(raw)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except UnicodeDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="UTF-8 required") from e
    created_links: list[Link] = []
    for row in rows:
        if not _valid_url(row.destination_url):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid URL: {row.destination_url[:80]}",
            )
        slug = await _unique_slug(db)
        link = Link(slug=slug, destination_url=row.destination_url.strip())
        apply_link_label(link, row.label)
        apply_link_profile(link, pid)
        db.add(link)
        created_links.append(link)
    for link in created_links:
        await bootstrap_link_avatar(db, link, allow_http=False)
    await db.commit()
    for link in created_links:
        await db.refresh(link)
    return {
        "created": len(created_links),
        "items": [LinkOut.from_link(link) for link in created_links],
    }


@router.get("/export/clicks.csv")
async def export_clicks_csv(
    _: ApiTokenDep,
    db: DbDep,
    link_id: uuid.UUID | None = Query(None),
    profile_id: str | None = Query(None, description="UUID, none, or omit for all"),
    platform: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
    earliest = await earliest_link_created_at(db)
    start, end = resolve_stats_period(date_from, date_to, preset, earliest=earliest)
    stmt = select(Click).where(Click.created_at >= start, Click.created_at < end)
    if link_id is not None:
        stmt = stmt.where(Click.link_id == link_id)
    else:
        prof = profile_id if profile_id else "all"
        plat = platform if platform else "all"
        stmt = apply_click_link_filters(stmt, profile=prof, platform=plat)
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
    profile_id: str | None = Query(None, description="UUID, none, or omit for all"),
    platform: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    preset: str | None = Query(None),
) -> StreamingResponse:
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
        prof = profile_id if profile_id else "all"
        plat = platform if platform else "all"
        link_ids = apply_link_filters(select(Link.id), profile=prof, platform=plat)
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
