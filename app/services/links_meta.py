"""Обновление полей ссылки: платформа из аккаунта, профиль."""

from __future__ import annotations

import uuid

from app.models import Link
from app.platforms import detect_platform_from_text


def apply_link_label(link: Link, label: str | None) -> None:
    link.label = (label or "").strip() or None
    link.platform = detect_platform_from_text(link.label)
    link.account_avatar_url = None
    link.account_avatar_mode = "auto"


def apply_link_profile(link: Link, profile_id: uuid.UUID | None) -> None:
    link.profile_id = profile_id
