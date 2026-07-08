"""Платформы соцсетей: детект по URL аккаунта, метки и цвета для фильтров."""

from __future__ import annotations

from typing import TypedDict


class PlatformInfo(TypedDict):
    id: str
    label: str
    color: str


# Порядок как в dashboard (основные для фильтра)
PLATFORMS: list[PlatformInfo] = [
    {"id": "tiktok", "label": "TikTok", "color": "#ff2d55"},
    {"id": "instagram", "label": "Instagram", "color": "#ec4899"},
    {"id": "youtube", "label": "YouTube", "color": "#ff4444"},
    {"id": "x", "label": "X", "color": "#dddddd"},
    {"id": "threads", "label": "Threads", "color": "#9aa0aa"},
    {"id": "facebook", "label": "Facebook", "color": "#1877F2"},
    {"id": "telegram", "label": "Telegram", "color": "#26a5e4"},
    {"id": "rumble", "label": "Rumble", "color": "#85c742"},
    {"id": "reddit", "label": "Reddit", "color": "#ff5700"},
]

PLATFORM_BY_ID: dict[str, PlatformInfo] = {p["id"]: p for p in PLATFORMS}

PROFILE_COLORS = [
    "#6366f1",
    "#4ade80",
    "#fb923c",
    "#ec4899",
    "#6aa9ff",
    "#f59e0b",
    "#22d3ee",
    "#a78bfa",
]


def detect_platform_from_text(text: str | None) -> str | None:
    """Определить платформу по URL или тексту аккаунта (как в dashboard _parseBulkLine)."""
    if not text or not text.strip():
        return None
    t = text.lower()
    if "tiktok.com" in t:
        return "tiktok"
    if "instagram.com" in t:
        return "instagram"
    if "youtube.com" in t or "youtu.be" in t:
        return "youtube"
    if "threads.net" in t or "threads.com" in t:
        return "threads"
    if "twitter.com" in t or "x.com" in t:
        return "x"
    if "facebook.com" in t or "fb.com" in t or "fb.watch" in t:
        return "facebook"
    if "t.me" in t or "telegram.me" in t or "telegram.org" in t:
        return "telegram"
    if "reddit.com" in t:
        return "reddit"
    if "rumble.com" in t:
        return "rumble"
    return None


def platform_label(platform_id: str | None) -> str:
    if not platform_id:
        return "—"
    return PLATFORM_BY_ID.get(platform_id, {}).get("label", platform_id)


def platform_color(platform_id: str | None) -> str:
    if not platform_id:
        return "#9ca3af"
    return PLATFORM_BY_ID.get(platform_id, {}).get("color", "#9ca3af")


def is_valid_platform(platform_id: str | None) -> bool:
    return platform_id is None or platform_id in PLATFORM_BY_ID


_PLATFORM_FAVICON_DOMAINS: dict[str, str] = {
    "tiktok": "tiktok.com",
    "instagram": "instagram.com",
    "youtube": "youtube.com",
    "x": "x.com",
    "threads": "threads.net",
    "facebook": "facebook.com",
    "telegram": "telegram.org",
    "rumble": "rumble.com",
    "reddit": "reddit.com",
}


def platform_favicon_url(platform_id: str | None) -> str | None:
    """Логотип платформы (favicon) для превью аккаунта."""
    if not platform_id:
        return None
    domain = _PLATFORM_FAVICON_DOMAINS.get(platform_id)
    if not domain:
        return None
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
