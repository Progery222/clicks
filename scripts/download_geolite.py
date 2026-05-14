"""
Скачивание GeoLite2-City (tar.gz) с download.maxmind.com и распаковка в data/GeoLite2-City.mmdb.

Требуется бесплатный аккаунт MaxMind и ключ:
https://www.maxmind.com/en/geolite2/signup
https://www.maxmind.com/en/accounts/current/license-key

  set MAXMIND_LICENSE_KEY=ваш_ключ
  python scripts/download_geolite.py

Windows PowerShell:
  $env:MAXMIND_LICENSE_KEY="ваш_ключ"; python scripts/download_geolite.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.geolite_download import download_geolite_city, project_data_dir

LICENSE_ENV = "MAXMIND_LICENSE_KEY"
DEFAULT_FILENAME = "GeoLite2-City.mmdb"


def main() -> None:
    key = os.environ.get(LICENSE_ENV, "").strip()
    if not key:
        print(
            f"Укажите переменную окружения {LICENSE_ENV} (ключ с maxmind.com).",
            file=sys.stderr,
        )
        sys.exit(1)

    out_file = project_data_dir() / DEFAULT_FILENAME
    try:
        download_geolite_city(key, out_file)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    mib = out_file.stat().st_size // 1024 // 1024
    print(f"Готово: {out_file} (~{mib} МиБ)")


if __name__ == "__main__":
    main()
