"""Локальные загруженные аватары (файлы на диске)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

UPLOAD_URL_PREFIX = "upload:"
MAX_AVATAR_UPLOAD_BYTES = 2 * 1024 * 1024
_ALLOWED_MEDIA = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})

_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP — проверим ниже
]


def avatars_dir() -> Path:
    root = Path(__file__).resolve().parent.parent.parent / "data" / "avatars"
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_marker(link_id: uuid.UUID) -> str:
    return f"{UPLOAD_URL_PREFIX}{link_id}"


def is_upload_avatar_url(url: str | None) -> bool:
    return bool(url and str(url).strip().startswith(UPLOAD_URL_PREFIX))


def _upload_path(link_id: uuid.UUID) -> Path:
    return avatars_dir() / f"{link_id}.img"


def detect_image_media_type(content: bytes) -> str | None:
    if len(content) < 12:
        return None
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    for magic, media in _MAGIC:
        if media == "image/webp":
            continue
        if content.startswith(magic):
            return media
    return None


def validate_avatar_upload(content: bytes, declared_type: str | None = None) -> str:
    if not content:
        raise ValueError("Файл пустой")
    if len(content) > MAX_AVATAR_UPLOAD_BYTES:
        raise ValueError(f"Файл больше {MAX_AVATAR_UPLOAD_BYTES // (1024 * 1024)} МБ")
    detected = detect_image_media_type(content)
    if not detected:
        raise ValueError("Допустимы только изображения JPEG, PNG, WebP или GIF")
    if declared_type:
        ct = declared_type.split(";")[0].strip().lower()
        if ct in _ALLOWED_MEDIA and ct != detected:
            log.debug("avatar upload: declared %s detected %s", ct, detected)
    return detected


def save_link_avatar_upload(link_id: uuid.UUID, content: bytes, media_type: str) -> None:
    path = _upload_path(link_id)
    path.write_bytes(content)
    meta = path.with_suffix(".meta")
    meta.write_text(media_type, encoding="utf-8")


def read_link_avatar_upload(link_id: uuid.UUID) -> tuple[bytes, str] | None:
    path = _upload_path(link_id)
    if not path.is_file():
        return None
    meta = path.with_suffix(".meta")
    media_type = "image/jpeg"
    if meta.is_file():
        media_type = meta.read_text(encoding="utf-8").strip() or media_type
    return path.read_bytes(), media_type


def delete_link_avatar_upload(link_id: uuid.UUID) -> None:
    for suffix in (".img", ".meta"):
        p = avatars_dir() / f"{link_id}{suffix}"
        if p.is_file():
            try:
                p.unlink()
            except OSError as exc:
                log.warning("failed to delete avatar upload %s: %s", p, exc)
