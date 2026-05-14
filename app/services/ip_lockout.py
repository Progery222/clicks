"""Блокировка IP на 24 ч после 3 неудачных попыток (админ-пароль или API-токен)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IpAuthLockout

log = logging.getLogger(__name__)

MAX_FAILURES = 3
BAN_DURATION = timedelta(hours=24)

MSG_BAN_JSON = (
    "Слишком много неудачных попыток с этого IP. Доступ к API временно заблокирован на 24 часа."
)
MSG_BAN_HTML = (
    "Слишком много неудачных попыток с этого адреса. Вход временно недоступен на 24 часа."
)


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        part = xff.split(",")[0].strip()
        if part:
            return part[:45]
    if request.client and request.client.host:
        return request.client.host[:45]
    return "0.0.0.0"


async def _get_row(db: AsyncSession, ip: str) -> IpAuthLockout | None:
    return await db.get(IpAuthLockout, ip)


async def is_ip_banned_now(db: AsyncSession, ip: str) -> tuple[bool, datetime | None]:
    """Активен ли бан сейчас. Просроченный бан снимает и обнуляет счётчики."""
    row = await _get_row(db, ip)
    if row is None:
        return False, None
    now = datetime.now(UTC)
    bu = row.banned_until
    if bu is not None:
        if bu.tzinfo is None:
            bu = bu.replace(tzinfo=UTC)
        else:
            bu = bu.astimezone(UTC)
        if bu <= now:
            row.banned_until = None
            row.admin_failures = 0
            row.api_failures = 0
            await db.commit()
            return False, None
        return True, bu
    return False, None


def retry_after_seconds(until: datetime) -> int:
    now = datetime.now(UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    else:
        until = until.astimezone(UTC)
    sec = int((until - now).total_seconds()) + 1
    return max(1, sec)


async def record_admin_password_failure(db: AsyncSession, ip: str) -> bool:
    """Возвращает True, если после этой попытки IP забанен."""
    now = datetime.now(UTC)
    row = await _get_row(db, ip)
    if row is None:
        row = IpAuthLockout(ip=ip, admin_failures=1, api_failures=0)
        db.add(row)
    else:
        row.admin_failures += 1
    banned = False
    if row.admin_failures >= MAX_FAILURES:
        row.banned_until = now + BAN_DURATION
        banned = True
        log.warning("ip_auth_lockout: admin ban ip=%s until=%s", ip, row.banned_until)
    await db.commit()
    return banned


async def record_api_token_failure(db: AsyncSession, ip: str) -> bool:
    """Неверный/отсутствующий токен при настроенном API. True если IP забанен."""
    now = datetime.now(UTC)
    row = await _get_row(db, ip)
    if row is None:
        row = IpAuthLockout(ip=ip, admin_failures=0, api_failures=1)
        db.add(row)
    else:
        row.api_failures += 1
    banned = False
    if row.api_failures >= MAX_FAILURES:
        row.banned_until = now + BAN_DURATION
        banned = True
        log.warning("ip_auth_lockout: api ban ip=%s until=%s", ip, row.banned_until)
    await db.commit()
    return banned


async def clear_admin_failures(db: AsyncSession, ip: str) -> None:
    row = await _get_row(db, ip)
    if row is None:
        return
    row.admin_failures = 0
    await db.commit()


async def clear_api_failures(db: AsyncSession, ip: str) -> None:
    row = await _get_row(db, ip)
    if row is None:
        return
    row.api_failures = 0
    await db.commit()
