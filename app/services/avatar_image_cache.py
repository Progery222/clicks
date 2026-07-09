"""In-memory кэш байтов аватаров (прокси /admin/avatar)."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class CachedAvatarImage:
    content: bytes
    media_type: str
    etag: str
    stored_at: float


_lock = Lock()
_store: dict[str, CachedAvatarImage] = {}
_max_entries = 800
_ttl_seconds = 7 * 24 * 3600


def _etag_for(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:32]


def _cache_key(link_id: str, pic_url: str) -> str:
    return f"{link_id}:{hashlib.sha256(pic_url.encode()).hexdigest()[:16]}"


def get_cached_avatar(link_id: str, pic_url: str) -> CachedAvatarImage | None:
    key = _cache_key(link_id, pic_url)
    now = time.time()
    with _lock:
        row = _store.get(key)
        if row is None:
            return None
        if now - row.stored_at > _ttl_seconds:
            _store.pop(key, None)
            return None
        return row


def put_cached_avatar(link_id: str, pic_url: str, content: bytes, media_type: str) -> CachedAvatarImage:
    key = _cache_key(link_id, pic_url)
    row = CachedAvatarImage(
        content=content,
        media_type=media_type,
        etag=_etag_for(content),
        stored_at=time.time(),
    )
    with _lock:
        if len(_store) >= _max_entries:
            oldest_key = min(_store, key=lambda k: _store[k].stored_at)
            _store.pop(oldest_key, None)
        _store[key] = row
    return row


def invalidate_link_avatar_cache(link_id: str | object) -> None:
    lid = str(link_id)
    with _lock:
        drop = [k for k in _store if k.startswith(f"{lid}:")]
        for k in drop:
            _store.pop(k, None)
