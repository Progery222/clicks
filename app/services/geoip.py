import ipaddress
import logging
from pathlib import Path
from typing import NamedTuple

import geoip2.database
import geoip2.errors

from app.config import get_settings

log = logging.getLogger(__name__)
_reader: geoip2.database.Reader | None = None
_reader_resolved: str | None = None


class GeoResult(NamedTuple):
    country_code: str | None
    region: str | None
    city: str | None


def _default_data_mmdb() -> Path:
    """Проект/data/GeoLite2-City.mmdb (после scripts/download_geolite.py)."""
    return Path(__file__).resolve().parents[2] / "data" / "GeoLite2-City.mmdb"


def _resolved_mmdb_path() -> Path | None:
    """Приоритет: GEOIP_CITY_DB_PATH → ./data/GeoLite2-City.mmdb."""
    cfg = get_settings().geoip_city_db_path
    if cfg:
        p = Path(cfg)
        if p.is_file():
            return p
        log.warning("GeoIP: файл из GEOIP_CITY_DB_PATH не найден: %s", cfg)
        return None
    fb = _default_data_mmdb()
    if fb.is_file():
        return fb
    return None


def _get_reader() -> geoip2.database.Reader | None:
    global _reader, _reader_resolved
    p = _resolved_mmdb_path()
    if p is None:
        return None
    resolved = str(p.resolve())
    if _reader is not None and _reader_resolved == resolved:
        return _reader
    if _reader is not None:
        try:
            _reader.close()
        except Exception:
            pass
        _reader = None
        _reader_resolved = None
    _reader = geoip2.database.Reader(resolved)
    _reader_resolved = resolved
    return _reader


def lookup_ip(ip_str: str | None) -> GeoResult:
    if not ip_str:
        return GeoResult(None, None, None)
    try:
        ipaddress.ip_address(ip_str)
    except ValueError:
        return GeoResult(None, None, None)
    reader = _get_reader()
    if reader is None:
        return GeoResult(None, None, None)
    try:
        rec = reader.city(ip_str)
        cc = rec.country.iso_code
        region = rec.subdivisions.most_specific.name if rec.subdivisions else None
        city = rec.city.name
        return GeoResult(cc, region, city)
    except (geoip2.errors.AddressNotFoundError, ValueError):
        return GeoResult(None, None, None)
