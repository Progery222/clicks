"""Отдача собранного SPA (Vite → app/static/spa)."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, Response

_STATIC = Path(__file__).resolve().parent / "static"
_SPA_INDEX = _STATIC / "spa" / "index.html"


def spa_index_response() -> Response:
    if not _SPA_INDEX.is_file():
        return HTMLResponse(
            "<!doctype html><title>SPA</title><p>Frontend не собран. "
            "Выполните <code>cd frontend && npm ci && npm run build</code>.</p>",
            status_code=503,
        )
    return FileResponse(
        _SPA_INDEX,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )
