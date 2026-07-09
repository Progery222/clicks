"""Общие функции для Jinja2-шаблонов."""

from __future__ import annotations

from pathlib import Path

_STATIC_ROOT = Path(__file__).resolve().parent / "static"
_ASSET_VERSION: dict[str, int] = {}


def _asset_mtime(name: str) -> int:
    try:
        return int((_STATIC_ROOT / name).stat().st_mtime)
    except OSError:
        return 0


def static_url(name: str) -> str:
    """URL статики с версией по mtime (сброс кэша браузера после деплоя)."""
    name = name.lstrip("/")
    if name not in _ASSET_VERSION:
        _ASSET_VERSION[name] = _asset_mtime(name)
    return f"/static/{name}?v={_ASSET_VERSION[name]}"


def register_template_globals(env) -> None:
    env.globals.setdefault("static_url", static_url)
