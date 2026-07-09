#!/bin/bash
set -euo pipefail
PG=t14ip5v8bhxqxpt2n6ujilme
CLICKS_PG=ns4nylsxbxjslgqgx73jog4s

echo "=== accountstats: phil / yllazen samples ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT platform, username, left(name,30) as name, left(profile_pic,70) as pic FROM accounts WHERE username ILIKE '%phil%' OR username ILIKE '%yllazen%' OR name ILIKE '%yllazen%' OR url ILIKE '%yllazen%' LIMIT 20;"

echo "=== clicks links sample ==="
docker exec "$CLICKS_PG" psql -U postgres -d postgres -c \
  "SELECT label, platform, left(account_avatar_url,80) FROM links WHERE label ILIKE '%yllazen%' OR label ILIKE '%phil%' LIMIT 15;"

echo "=== accountstats count with pics ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -t -A -c \
  "SELECT count(*) FROM accounts WHERE profile_pic IS NOT NULL AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc%';"
