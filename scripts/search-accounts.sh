#!/bin/bash
set -euo pipefail
PG=t14ip5v8bhxqxpt2n6ujilme

echo "=== search by username/url ==="
for u in karen.martin520 yllazenspace yllazenlab yllazenofficial iamyllazen; do
  echo "--- $u ---"
  docker exec "$PG" psql -U socialhub -d social_dashboard -t -A -c \
    "SELECT platform, username, left(profile_pic,80) FROM accounts WHERE lower(username)=lower('$u') OR url ILIKE '%$u%' LIMIT 3;"
done

echo "=== platform values ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT platform, count(*) FROM accounts GROUP BY platform ORDER BY count DESC;"

echo "=== accounts with real tiktok pics count ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -t -A -c \
  "SELECT count(*) FROM accounts WHERE profile_pic IS NOT NULL AND profile_pic NOT LIKE '%cdninstagram.com/rsrc%' AND profile_pic != '';"
