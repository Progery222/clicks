"""Middleware: активный бан IP блокирует /admin (кроме GET логина и выхода) и /api/v1."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import AsyncSessionLocal
from app.services.ip_lockout import MSG_BAN_JSON, is_api_ip_blocked, is_ip_banned_now, client_ip, retry_after_seconds

log = logging.getLogger(__name__)


class IpAuthBanMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/admin") and not path.startswith("/api/v1"):
            return await call_next(request)

        ip = client_ip(request)
        if path.startswith("/admin/avatar/"):
            return await call_next(request)

        try:
            async with AsyncSessionLocal() as session:
                if path.startswith("/api/v1"):
                    api_blocked = await is_api_ip_blocked(session, ip)
                    if api_blocked:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": MSG_BAN_JSON},
                            headers={"Retry-After": "3600"},
                        )
                    return await call_next(request)

                banned, until = await is_ip_banned_now(session, ip)
        except Exception:
            log.exception("IpAuthBanMiddleware: DB error, пропуск проверки ban для ip=%s", ip)
            return await call_next(request)

        if not banned:
            return await call_next(request)

        assert until is not None
        ra = str(retry_after_seconds(until))

        if path.startswith("/admin/api/"):
            return JSONResponse(
                status_code=429,
                content={"detail": MSG_BAN_JSON},
                headers={"Retry-After": ra},
            )

        if path == "/admin/login" and request.method == "GET":
            return await call_next(request)

        if path == "/admin/logout":
            return await call_next(request)

        return RedirectResponse(url="/admin/login?blocked=1", status_code=302)
