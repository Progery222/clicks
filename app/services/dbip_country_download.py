"""
Скачивание DB-IP Country (MMDB) без ключа — зеркало npm/jsDelivr.

Пакет: https://www.npmjs.com/package/@ip-location-db/dbip-country-mmdb
Данные DB-IP Community Edition, лицензия CC BY 4.0 (нужна атрибуция в продукте / политике).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_URL = (
    "https://cdn.jsdelivr.net/npm/@ip-location-db/dbip-country-mmdb@latest/dbip-country.mmdb"
)
DEFAULT_FILENAME = "dbip-country.mmdb"


def project_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def download_dbip_country(out_file: Path, url: str | None = None) -> None:
    """Скачать MMDB потоком во временный файл и атомарно заменить out_file."""
    u = (url or DEFAULT_DOWNLOAD_URL).strip()
    if not u:
        raise ValueError("empty download url")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(out_file.suffix + ".tmp")

    with httpx.Client(follow_redirects=True, timeout=300.0) as client:
        with client.stream("GET", u) as r:
            if r.status_code != 200:
                raise RuntimeError(f"DB-IP download HTTP {r.status_code}")
            size = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1024 * 256):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
            if size < 100_000:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"Подозрительно маленький ответ ({size} байт)")

    try:
        tmp.replace(out_file)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    mib = out_file.stat().st_size // 1024 // 1024
    log.info("DB-IP Country MMDB записан: %s (~%s МиБ)", out_file, mib)


def ensure_dbip_country_db(
    *,
    geoip_country_db_path: str | None,
    auto_download: bool,
    download_url: str | None = None,
) -> bool:
    """
    Возвращает True, только если в этом запуске был скачан новый MMDB.
    Если файл уже есть — False.
    """
    if geoip_country_db_path:
        target = Path(geoip_country_db_path)
    else:
        target = project_data_dir() / DEFAULT_FILENAME

    if target.is_file():
        return False

    if not auto_download:
        log.info(
            "DB-IP Country: файл не найден (%s). Включите GEOIP_COUNTRY_AUTO_DOWNLOAD=true "
            "или скачайте: python scripts/download_dbip_country.py",
            target,
        )
        return False

    try:
        download_dbip_country(target, download_url)
        return target.is_file()
    except Exception:
        log.exception("DB-IP Country: не удалось скачать базу")
        return False
