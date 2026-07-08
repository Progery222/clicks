"""Разбор User-Agent: ОС и тип устройства (без внешних зависимостей)."""

from __future__ import annotations

import re

_BOT_RE = re.compile(
    r"bot|crawler|spider|slurp|facebookexternalhit|HeadlessChrome|bingpreview",
    re.I,
)

_MOBILE_RE = re.compile(
    r"Mobile|iPhone|iPod|Android|iPad|Tablet|Kindle|Silk/|PlayBook|"
    r"webOS|BlackBerry|Opera Mini|IEMobile|Windows Phone",
    re.I,
)


def parse_device_type(user_agent: str | None) -> str:
    """Только «Мобильный» или «Десктоп» (боты, TV, планшеты без mobile → десктоп)."""
    if not user_agent or not str(user_agent).strip():
        return "Десктоп"
    s = str(user_agent)
    if _MOBILE_RE.search(s):
        return "Мобильный"
    return "Десктоп"


def parse_os(user_agent: str | None) -> str:
    if not user_agent or not str(user_agent).strip():
        return "Неизвестно"
    s = str(user_agent)
    if _BOT_RE.search(s):
        return "Другое"
    if re.search(r"Telegram", s, re.I):
        return "Telegram"
    if re.search(r"iPhone|iPad|iPod|CPU (?:iPhone )?OS", s):
        return "iOS"
    if "Android" in s:
        return "Android"
    if "Windows NT" in s or "Windows Phone" in s:
        return "Windows"
    if "Mac OS X" in s or "Macintosh" in s:
        return "macOS"
    if "CrOS" in s:
        return "Другое"
    if "Linux" in s:
        return "Другое"
    return "Другое"
