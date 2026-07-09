"""CSRF-токены для форм админки (сессия Starlette)."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token or not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def rotate_csrf_token(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request) -> None:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not isinstance(expected, str):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing")

    provided = request.headers.get(CSRF_HEADER)
    if not provided:
        provided = request.headers.get("X-CSRF-Token")
    if not provided and hasattr(request, "_form"):
        pass
    if not provided:
        # FormData читается в middleware до роутера — передаём через state
        provided = getattr(request.state, "csrf_form_token", None)

    if not provided or not secrets.compare_digest(str(provided), expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
