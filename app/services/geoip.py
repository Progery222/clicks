import ipaddress
import logging
from pathlib import Path
from typing import Literal, NamedTuple

import geoip2.database
import geoip2.errors
import maxminddb

from app.config import get_settings

log = logging.getLogger(__name__)

_city_reader: geoip2.database.Reader | None = None
_city_reader_resolved: str | None = None

_country_reader: maxminddb.Reader | None = None
_country_reader_resolved: str | None = None


class GeoResult(NamedTuple):
    country_code: str | None
    region: str | None
    city: str | None


def _default_data_mmdb() -> Path:
    """Проект/data/GeoLite2-City.mmdb (после scripts/download_geolite.py)."""
    return Path(__file__).resolve().parents[2] / "data" / "GeoLite2-City.mmdb"


def _default_country_mmdb() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "dbip-country.mmdb"


def reset_geoip_reader() -> None:
    """Закрыть все reader (после появления нового .mmdb)."""
    global _city_reader, _city_reader_resolved, _country_reader, _country_reader_resolved
    if _city_reader is not None:
        try:
            _city_reader.close()
        except Exception:
            pass
    _city_reader = None
    _city_reader_resolved = None
    if _country_reader is not None:
        try:
            _country_reader.close()
        except Exception:
            pass
    _country_reader = None
    _country_reader_resolved = None


def resolved_city_mmdb_path() -> Path | None:
    """Путь к GeoLite2-City (или другому city-MMDB), если файл существует."""
    cfg = get_settings().geoip_city_db_path
    if cfg:
        p = Path(cfg)
        if p.is_file():
            return p
        return None
    fb = _default_data_mmdb()
    if fb.is_file():
        return fb
    return None


def _resolved_country_mmdb_path() -> Path | None:
    cfg = get_settings().geoip_country_db_path
    if cfg:
        p = Path(cfg)
        if p.is_file():
            return p
        return None
    fb = _default_country_mmdb()
    if fb.is_file():
        return fb
    return None


def resolved_country_mmdb_path() -> Path | None:
    """Путь к DB-IP Country MMDB (или своему country .mmdb), если файл существует."""
    return _resolved_country_mmdb_path()


def _geo_lookup_target(ip_str: str) -> str:
    """
    Адрес для запроса к MMDB. Реальный IP в Click.ip не меняется.
    Для неглобальных адресов (localhost, LAN) можно задать GEOIP_DEBUG_FALLBACK_IP.
    """
    try:
        parsed = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return ip_str
    if parsed.is_global:
        return ip_str
    raw = (get_settings().geoip_debug_fallback_ip or "").strip()
    if not raw:
        return ip_str
    try:
        fb = ipaddress.ip_address(raw)
    except ValueError:
        log.warning("GEOIP_DEBUG_FALLBACK_IP не является валидным IP")
        return ip_str
    if not fb.is_global:
        log.warning("GEOIP_DEBUG_FALLBACK_IP должен быть публичным (глобальным) IP")
        return ip_str
    return raw


def _get_city_reader() -> geoip2.database.Reader | None:
    global _city_reader, _city_reader_resolved
    p = resolved_city_mmdb_path()
    if p is None:
        return None
    resolved = str(p.resolve())
    if _city_reader is not None and _city_reader_resolved == resolved:
        return _city_reader
    if _city_reader is not None:
        try:
            _city_reader.close()
        except Exception:
            pass
        _city_reader = None
        _city_reader_resolved = None
    _city_reader = geoip2.database.Reader(resolved)
    _city_reader_resolved = resolved
    return _city_reader


def _get_country_reader() -> maxminddb.Reader | None:
    global _country_reader, _country_reader_resolved
    p = _resolved_country_mmdb_path()
    if p is None:
        return None
    resolved = str(p.resolve())
    if _country_reader is not None and _country_reader_resolved == resolved:
        return _country_reader
    if _country_reader is not None:
        try:
            _country_reader.close()
        except Exception:
            pass
        _country_reader = None
        _country_reader_resolved = None
    _country_reader = maxminddb.open_database(resolved)
    _country_reader_resolved = resolved
    return _country_reader


def _active_backend() -> Literal["city", "country_raw"] | None:
    if resolved_city_mmdb_path() is not None:
        return "city"
    if _resolved_country_mmdb_path() is not None:
        return "country_raw"
    return None


def lookup_ip(ip_str: str | None) -> GeoResult:
    if not ip_str:
        return GeoResult(None, None, None)
    ip_str = ip_str.strip()
    try:
        ipaddress.ip_address(ip_str)
    except ValueError:
        return GeoResult(None, None, None)

    lookup_addr = _geo_lookup_target(ip_str)

    backend = _active_backend()
    if backend == "city":
        reader = _get_city_reader()
        if reader is None:
            return GeoResult(None, None, None)
        try:
            rec = reader.city(lookup_addr)
            cc = rec.country.iso_code
            region = rec.subdivisions.most_specific.name if rec.subdivisions else None
            city = rec.city.name
            return GeoResult(cc, region, city)
        except (geoip2.errors.AddressNotFoundError, ValueError):
            return GeoResult(None, None, None)

    if backend == "country_raw":
        reader = _get_country_reader()
        if reader is None:
            return GeoResult(None, None, None)
        try:
            data = reader.get(lookup_addr)
        except ValueError:
            return GeoResult(None, None, None)
        if not data:
            return GeoResult(None, None, None)
        cc = data.get("country_code")
        if isinstance(cc, str) and len(cc) == 2:
            return GeoResult(cc.upper(), None, None)
        return GeoResult(None, None, None)

    return GeoResult(None, None, None)
