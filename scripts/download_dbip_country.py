"""
Скачать DB-IP Country MMDB (~8 МиБ) без регистрации (jsDelivr / npm @ip-location-db/dbip-country-mmdb).

Лицензия CC BY 4.0 — укажите атрибуцию DB-IP в продукте, см. https://db-ip.com

  python scripts/download_dbip_country.py

Свой URL (опционально):

  set GEOIP_COUNTRY_DB_URL=https://...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.dbip_country_download import DEFAULT_DOWNLOAD_URL, download_dbip_country, project_data_dir

DEFAULT_FILENAME = "dbip-country.mmdb"


def main() -> None:
    out_file = project_data_dir() / DEFAULT_FILENAME
    url = os.environ.get("GEOIP_COUNTRY_DB_URL", "").strip() or None
    try:
        download_dbip_country(out_file, url)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    mib = out_file.stat().st_size // 1024 // 1024
    print(f"Готово: {out_file} (~{mib} МиБ)")
    if not url:
        print(f"Источник по умолчанию: {DEFAULT_DOWNLOAD_URL}")


if __name__ == "__main__":
    main()
