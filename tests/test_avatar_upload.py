"""Тесты загрузки аватаров."""

import uuid

import pytest

from app.services.avatar_upload import (
    MAX_AVATAR_UPLOAD_BYTES,
    delete_link_avatar_upload,
    read_link_avatar_upload,
    save_link_avatar_upload,
    upload_marker,
    validate_avatar_upload,
)

# minimal 1x1 PNG
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_validate_and_roundtrip_upload():
    lid = uuid.uuid4()
    try:
        mt = validate_avatar_upload(_TINY_PNG, "image/png")
        assert mt == "image/png"
        save_link_avatar_upload(lid, _TINY_PNG, mt)
        assert upload_marker(lid).startswith("upload:")
        row = read_link_avatar_upload(lid)
        assert row is not None
        assert row[0] == _TINY_PNG
    finally:
        delete_link_avatar_upload(lid)


def test_rejects_oversized():
    with pytest.raises(ValueError, match="МБ"):
        validate_avatar_upload(b"x" * (MAX_AVATAR_UPLOAD_BYTES + 1))
