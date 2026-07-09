#!/bin/bash
set -euo pipefail
PG=ns4nylsxbxjslgqgx73jog4s
docker exec "$PG" psql -U postgres -d postgres -c \
  "SELECT label, platform, left(account_avatar_url,100) FROM links WHERE label ILIKE '%yllazen%' OR label ILIKE '%karen%' LIMIT 20;"
