import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import get_settings
from app.database import get_db
from app.models import Link
from app.request_utils import get_client_ip
from app.services.redirect_rate_limit import allow_redirect
from app.services.clicks import log_click_background
from app.services.dedupe import parse_vid_cookie

router = APIRouter(tags=["redirect"])

VID_COOKIE = "vid"


@router.get("/r/{slug}")
async def redirect_slug(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    res = await db.execute(select(Link).where(Link.slug == slug))
    link = res.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")

    ip = get_client_ip(request) or None
    settings = get_settings()
    if not allow_redirect(ip, limit_per_minute=settings.redirect_rate_limit_per_minute):
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": "60"},
        )
    ua = request.headers.get("user-agent")
    ref = request.headers.get("referer")

    raw_vid = request.cookies.get(VID_COOKIE)
    incoming = parse_vid_cookie(raw_vid)
    set_cookie_val: str | None = None
    if incoming:
        visitor_uuid = incoming
    else:
        visitor_uuid = uuid.uuid4()
        set_cookie_val = str(visitor_uuid)

    asyncio.create_task(
        log_click_background(
            link_id=link.id,
            ip=ip,
            user_agent=ua,
            referer=ref,
            visitor_uuid=visitor_uuid,
        )
    )

    secure = request.url.scheme == "https"
    out = Response(status_code=302, headers={"Location": link.destination_url})
    if set_cookie_val is not None:
        out.set_cookie(
            key=VID_COOKIE,
            value=set_cookie_val,
            max_age=365 * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )
    return out
