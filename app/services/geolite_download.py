"""
Скачивание GeoLite2-City с download.maxmind.com в data/GeoLite2-City.mmdb (или в GEOIP_CITY_DB_PATH).

Используется скриптом scripts/download_geolite.py и при старте приложения (если задан MAXMIND_LICENSE_KEY).
"""

from __future__ import annotations

import io
import logging
import tarfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

EDITION = "GeoLite2-City"
DEFAULT_FILENAME = "GeoLite2-City.mmdb"


def project_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def download_geolite_city(license_key: str, out_file: Path) -> None:
    """Скачать tar.gz и записать только GeoLite2-City.mmdb в out_file."""
    key = license_key.strip()
    if not key:
        raise ValueError("empty license key")

    url = (
        "https://download.maxmind.com/app/geoip_download"
        f"?edition_id={EDITION}&license_key={key}&suffix=tar.gz"
    )

    with httpx.Client(follow_redirects=True, timeout=180.0) as client:
        r = client.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"MaxMind HTTP {r.status_code}")
        data = r.content

    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as e:
        head = data[:800].decode("utf-8", errors="replace")
        raise RuntimeError(f"Ответ не tar.gz: {e}; начало: {head!r}") from e

    with tar:
        mmdb_member = None
        for m in tar.getmembers():
            if m.isfile() and m.name.endswith("GeoLite2-City.mmdb"):
                mmdb_member = m
                break
        if mmdb_member is None:
            raise RuntimeError("В архиве нет GeoLite2-City.mmdb")
        f = tar.extractfile(mmdb_member)
        if f is None:
            raise RuntimeError("extractfile вернул None")
        blob = f.read()
        if len(blob) < 1000:
            raise RuntimeError("Слишком маленький .mmdb")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(out_file.suffix + ".tmp")
    try:
        tmp.write_bytes(blob)
        tmp.replace(out_file)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    mib = out_file.stat().st_size // 1024 // 1024
    log.info("GeoLite2-City записан: %s (~%s МиБ)", out_file, mib)


def ensure_geolite_city_db(license_key: str | None, *, geoip_city_db_path: str | None = None) -> bool:
    """
    Возвращает True, только если в этом запуске был скачан новый MMDB.
    Если файл уже существует — False (reader откроется при первом lookup).
    """
    if geoip_city_db_path:
        p = Path(geoip_city_db_path)
        if p.is_file():
            return False
        target = p
    else:
        target = project_data_dir() / DEFAULT_FILENAME
        if target.is_file():
            return False

    key = (license_key or "").strip()
    if not key:
        log.info(
            "GeoLite2: база не найдена (%s). Задайте MAXMIND_LICENSE_KEY для автоскачивания при старте "
            "или скачайте вручную: python scripts/download_geolite.py",
            target,
        )
        return False

    try:
        download_geolite_city(key, target)
        return target.is_file()
    except Exception:
        log.exception("GeoLite2: не удалось скачать базу")
        return False
