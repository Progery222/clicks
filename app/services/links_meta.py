"""Обновление полей ссылки: платформа из аккаунта, профиль."""

from __future__ import annotations

import uuid

from app.models import Link
from app.platforms import detect_platform_from_text
from app.utils.bulk_labels import parse_label_lines


def apply_link_title(link: Link, title: str | None) -> None:
    link.title = (title or "").strip() or None


def apply_link_label(link: Link, label: str | None) -> None:
    """Один или несколько аккаунтов (по строке) — храним через перевод строки."""
    accounts = parse_label_lines(label or "")
    link.label = "\n".join(accounts) if accounts else None
    platform = None
    for acc in accounts:
        platform = detect_platform_from_text(acc)
        if platform:
            break
    if platform is None and link.label:
        platform = detect_platform_from_text(link.label)
    link.platform = platform
    link.account_avatar_url = None
    link.account_avatar_mode = "auto"


def apply_link_profile(link: Link, profile_id: uuid.UUID | None) -> None:
    link.profile_id = profile_id
