import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Click

log = logging.getLogger(__name__)


async def cleanup_old_clicks() -> None:
    days = get_settings().click_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Click).where(Click.created_at < cutoff))
            await session.commit()
    except Exception:
        log.exception("cleanup_old_clicks failed")
