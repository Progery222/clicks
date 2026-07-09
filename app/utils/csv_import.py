"""Разбор CSV для импорта ссылок."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass
class ImportLinkRow:
    destination_url: str
    label: str | None


MAX_IMPORT_ROWS = 500
MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _norm_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_")


def _col_index(headers: list[str], *names: str) -> int | None:
    norm = [_norm_header(h) for h in headers]
    for name in names:
        if name in norm:
            return norm.index(name)
    return None


def parse_links_import_csv(text: str) -> list[ImportLinkRow]:
    """
    Колонки (регистр не важен):
    - destination_url / url / цель
    - label / account / аккаунт (необязательно)
    """
    raw = text.strip()
    if not raw:
        raise ValueError("Файл пустой")

    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(raw), dialect)
    rows = list(reader)
    if not rows:
        raise ValueError("Нет строк в CSV")

    headers = rows[0]
    dest_i = _col_index(headers, "destination_url", "url", "цель", "destination")
    label_i = _col_index(headers, "label", "account", "аккаунт")

    data_rows = rows[1:] if dest_i is not None else rows
    if dest_i is None:
        if len(rows[0]) < 1:
            raise ValueError("Нужна колонка destination_url или url")
        dest_i = 0
        label_i = 1 if len(rows[0]) > 1 else None

    out: list[ImportLinkRow] = []
    for row in data_rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        if dest_i >= len(row):
            continue
        dest = (row[dest_i] or "").strip()
        if not dest:
            continue
        label = None
        if label_i is not None and label_i < len(row):
            lab = (row[label_i] or "").strip()
            label = lab or None
        out.append(ImportLinkRow(destination_url=dest, label=label))

    if not out:
        raise ValueError("Нет валидных строк (нужен destination_url)")
    if len(out) > MAX_IMPORT_ROWS:
        raise ValueError(f"Не больше {MAX_IMPORT_ROWS} строк за импорт")
    return out
