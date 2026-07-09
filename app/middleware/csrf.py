"""Проверка CSRF на изменяющих запросах в /admin."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.csrf import CSRF_FORM_FIELD, CSRF_HEADER, CSRF_SESSION_KEY

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# POST без CSRF: первый вход (сессии ещё нет токена до ответа login)
_CSRF_EXEMPT = frozenset({"/admin/login"})


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.csrf_enabled:
            return await call_next(request)

        if request.method in _SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/admin"):
            return await call_next(request)
        if path in _CSRF_EXEMPT:
            return await call_next(request)

        expected = request.session.get(CSRF_SESSION_KEY)
        if not expected or not isinstance(expected, str):
            return JSONResponse(
                {"detail": "CSRF token missing"},
                status_code=403,
            )

        provided = request.headers.get(CSRF_HEADER) or request.headers.get("X-CSRF-Token")
        if not provided:
            ctype = (request.headers.get("content-type") or "").lower()
            if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
                try:
                    form = await request.form()
                    provided = form.get(CSRF_FORM_FIELD)
                except Exception:
                    provided = None

        if not provided or not secrets.compare_digest(str(provided), expected):
            return JSONResponse(
                {"detail": "CSRF validation failed"},
                status_code=403,
            )

        return await call_next(request)
