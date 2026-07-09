#!/bin/bash
set -euo pipefail
PG=t14ip5v8bhxqxpt2n6ujilme

docker exec "$PG" psql -U socialhub -d social_dashboard -c '\d accounts'

echo "=== sample rows ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, profile_pic FROM accounts WHERE profile_pic IS NOT NULL AND profile_pic != '' LIMIT 10;"

echo "=== yllazen samples ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT platform, username, left(profile_pic,120) as pic FROM accounts WHERE username ILIKE '%yllazen%' LIMIT 15;"
