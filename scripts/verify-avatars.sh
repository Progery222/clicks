#!/bin/bash
set -euo pipefail
CLICKS=$(docker ps --filter publish=8102 --format '{{.Names}}' | head -1)
echo "CONTAINER=$CLICKS"
sleep 3
curl -fsS -m 10 http://127.0.0.1:8102/health && echo

echo "=== env ACCOUNTSTATS ==="
docker exec "$CLICKS" env | grep ACCOUNTSTATS | sed 's/=.*/=***/'

echo "=== test lookup from app ==="
docker exec "$CLICKS" python -c "
import asyncio
from app.services.accountstats_avatar import lookup_profile_pic

async def main():
    pic = await lookup_profile_pic('https://www.tiktok.com/@perez3lily', 'tiktok')
    print('perez3lily', (pic or '')[:80])
    pic2 = await lookup_profile_pic('https://www.tiktok.com/@yllazenofficial', 'tiktok')
    print('yllazenofficial', pic2)
asyncio.run(main())
"

echo "=== sample links avatars after reload ==="
PG=ns4nylsxbxjslgqgx73jog4s
docker exec "$PG" psql -U postgres -d postgres -c \
  "SELECT label, left(account_avatar_url,90) FROM links WHERE label ILIKE '%perez3lily%' OR label ILIKE '%yllazenofficial%' LIMIT 5;"
