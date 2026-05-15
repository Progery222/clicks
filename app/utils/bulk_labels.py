"""Разбор списка аккаунтов для массового создания ссылок."""

from __future__ import annotations

from collections.abc import Iterable

MAX_BULK_LABELS = 200


def normalize_bulk_labels(raw: Iterable[str]) -> list[str]:
    """Пустые строки пропускаются; дубликаты (без учёта регистра) — одна запись; до 255 символов."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        label = item.strip()
        if not label:
            continue
        if len(label) > 255:
            label = label[:255]
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def parse_label_lines(text: str) -> list[str]:
    return normalize_bulk_labels(text.splitlines())
