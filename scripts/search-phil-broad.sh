#!/bin/bash
PG=t14ip5v8bhxqxpt2n6ujilme
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, name, left(url,70) FROM accounts WHERE name ILIKE '%phil%' OR url ILIKE '%phil%' OR username ILIKE '%phil%' LIMIT 20;"

docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, name FROM accounts WHERE campaign ILIKE '%phil%' OR campaign ILIKE '%yllazen%' LIMIT 20;" 2>/dev/null || echo "no campaign col"

docker exec "$PG" psql -U socialhub -d social_dashboard -c '\d accounts' | grep -i campaign
