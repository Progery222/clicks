#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
docker exec $C curl -sS -m 20 -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  'https://www.tiktok.com/@philredpill891' | grep -oE 'https://[^"]+tiktokcdn[^"]+avata[^"]*' | head -5
echo "---"
docker exec $C curl -sS -m 20 -A "Mozilla/5.0" \
  'https://www.tiktok.com/@philredpill891' | grep -oE 'avatarLarger[^,]*' | head -3
