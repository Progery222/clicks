import asyncio
import logging
import uuid
from datetime import UTC, date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Click
from app.services.dedupe import dedupe_key_for_visitor
from app.services.geoip import lookup_ip
from app.services.stats_cache import bump_dashboard_counts_on_click, invalidate_dashboard_counts_cache

log = logging.getLogger(__name__)


async def insert_click(
    session: AsyncSession,
    *,
    link_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
    referer: str | None,
    visitor_uuid: uuid.UUID,
    dedupe_key: str | None = None,
) -> None:
    """Persist one click row. visitor_uuid — из cookie или новый (совпадает с Set-Cookie на первом заходе)."""
    dedupe = dedupe_key or dedupe_key_for_visitor(visitor_uuid)
    geo = await asyncio.to_thread(lookup_ip, ip)
    row = Click(
        link_id=link_id,
        ip=ip,
        user_agent=user_agent,
        referer=referer,
        country_code=geo.country_code,
        region=geo.region,
        city=geo.city,
        visitor_id=visitor_uuid,
        dedupe_key=dedupe,
    )
    session.add(row)
    await session.commit()
    bump_dashboard_counts_on_click(link_id)


async def log_click_background(
    *,
    link_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
    referer: str | None,
    visitor_uuid: uuid.UUID,
    dedupe_key: str | None = None,
) -> None:
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await insert_click(
                session,
                link_id=link_id,
                ip=ip,
                user_agent=user_agent,
                referer=referer,
                visitor_uuid=visitor_uuid,
                dedupe_key=dedupe_key,
            )
    except Exception:
        log.exception("Failed to record click for link_id=%s", link_id)
