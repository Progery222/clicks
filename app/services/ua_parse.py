"""Разбор User-Agent: ОС и тип устройства (без внешних зависимостей)."""

from __future__ import annotations

import re

_BOT_RE = re.compile(
    r"bot|crawler|spider|slurp|facebookexternalhit|HeadlessChrome|bingpreview",
    re.I,
)


def parse_device_type(user_agent: str | None) -> str:
    if not user_agent or not str(user_agent).strip():
        return "Неизвестно"
    s = str(user_agent)
    if _BOT_RE.search(s):
        return "Бот"
    if re.search(r"iPad|Tablet|Kindle|Silk/|PlayBook", s, re.I):
        return "Планшет"
    if re.search(
        r"Mobile|iPhone|iPod|Android.*Mobile|webOS|BlackBerry|Opera Mini|IEMobile|Windows Phone",
        s,
        re.I,
    ):
        return "Мобильный"
    if re.search(r"Smart-?TV|SmartTV|AppleTV|CrKey|HbbTV|GoogleTV", s, re.I):
        return "TV"
    return "Десктоп"


def parse_os(user_agent: str | None) -> str:
    if not user_agent or not str(user_agent).strip():
        return "Неизвестно"
    s = str(user_agent)
    if _BOT_RE.search(s):
        return "Бот"
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
        return "Chrome OS"
    if "Linux" in s:
        return "Linux"
    return "Другое"
