#!/bin/bash
set -euo pipefail
PG=t14ip5v8bhxqxpt2n6ujilme

echo "=== search philredpill891 ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, url, left(profile_pic,60) FROM accounts WHERE username ILIKE '%philred%' OR url ILIKE '%philred%' OR name ILIKE '%philred%' LIMIT 10;"

echo "=== search yllazenspace ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, url, left(profile_pic,60) FROM accounts WHERE username ILIKE '%yllazen%' OR url ILIKE '%yllazen%' LIMIT 10;"

echo "=== all databases on postgres container ==="
docker exec "$PG" psql -U socialhub -d postgres -c '\l'

echo "=== sample urls in accounts ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT platform, username, left(url,60) FROM accounts ORDER BY id DESC LIMIT 15;"
