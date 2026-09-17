"""Обновление полей ссылки: платформа из аккаунта."""

from __future__ import annotations

from app.models import Link
from app.platforms import detect_platform_from_text
from app.utils.bulk_labels import parse_label_lines


def apply_link_title(link: Link, title: str | None) -> None:
    link.title = (title or "").strip() or None


def apply_destination_title(link: Link, destination_title: str | None) -> None:
    link.destination_title = (destination_title or "").strip() or None


def group_accounts_by_platform(label: str | None) -> list[tuple[str | None, list[str]]]:
    """Разбить аккаунты на группы по детектированной платформе (порядок первого появления)."""
    accounts = parse_label_lines(label or "")
    if not accounts:
        return []
    groups: dict[str | None, list[str]] = {}
    order: list[str | None] = []
    for acc in accounts:
        plat = detect_platform_from_text(acc)
        if plat not in groups:
            groups[plat] = []
            order.append(plat)
        groups[plat].append(acc)
    return [(plat, groups[plat]) for plat in order]


def apply_link_accounts(link: Link, accounts: list[str]) -> None:
    """Записать список аккаунтов и выставить platform по первому детектируемому."""
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


def apply_link_label(link: Link, label: str | None) -> None:
    """Один или несколько аккаунтов (строка / запятая) — храним через перевод строки."""
    apply_link_accounts(link, parse_label_lines(label or ""))

