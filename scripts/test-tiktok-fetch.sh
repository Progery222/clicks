#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
URL="https://www.tiktok.com/@philredpill891"
echo "=== oembed ==="
docker exec $C curl -sS -m 15 "https://www.tiktok.com/oembed?url=$URL" | head -c 400
echo ""
echo "=== og page head ==="
docker exec $C curl -sS -m 15 -A "Mozilla/5.0" -L "$URL" | grep -oi 'og:image[^>]*content="[^"]*"' | head -3
