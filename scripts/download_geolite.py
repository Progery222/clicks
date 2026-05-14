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

import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

EDITION = "GeoLite2-City"
LICENSE_ENV = "MAXMIND_LICENSE_KEY"


def main() -> None:
    key = os.environ.get(LICENSE_ENV, "").strip()
    if not key:
        print(
            f"Укажите переменную окружения {LICENSE_ENV} (ключ с maxmind.com).",
            file=sys.stderr,
        )
        sys.exit(1)

    root = Path(__file__).resolve().parents[1]
    out_dir = root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "GeoLite2-City.mmdb"

    url = (
        "https://download.maxmind.com/app/geoip_download"
        f"?edition_id={EDITION}&license_key={key}&suffix=tar.gz"
    )

    with httpx.Client(follow_redirects=True, timeout=180.0) as client:
        r = client.get(url)
        if r.status_code != 200:
            print(f"Ошибка HTTP {r.status_code}: проверьте ключ {LICENSE_ENV}.", file=sys.stderr)
            sys.exit(1)
        data = r.content

    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as e:
        head = data[:1200].decode("utf-8", errors="replace")
        print(f"Ответ не похож на tar.gz ({e}). Начало ответа:\n{head}", file=sys.stderr)
        sys.exit(1)

    with tar:
        mmdb_member = None
        for m in tar.getmembers():
            if not m.isfile():
                continue
            if m.name.endswith("GeoLite2-City.mmdb"):
                mmdb_member = m
                break
        if mmdb_member is None:
            print("В архиве не найден GeoLite2-City.mmdb", file=sys.stderr)
            sys.exit(1)
        f = tar.extractfile(mmdb_member)
        if f is None:
            sys.exit(1)
        blob = f.read()
        if len(blob) < 1000:
            print("Слишком маленький файл .mmdb", file=sys.stderr)
            sys.exit(1)
        out_file.write_bytes(blob)

    mib = out_file.stat().st_size // 1024 // 1024
    print(f"Готово: {out_file} (~{mib} МиБ)")


if __name__ == "__main__":
    main()
