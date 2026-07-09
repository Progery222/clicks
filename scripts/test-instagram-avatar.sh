#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
docker exec $C curl -sS -m 20 -A "Mozilla/5.0" \
  'https://www.instagram.com/phildecoded/' | grep -oiE 'profile_pic_url[^,]*' | head -3
echo "---og---"
docker exec $C curl -sS -m 20 -A "Mozilla/5.0" \
  'https://www.instagram.com/phildecoded/' | grep -oi 'property="og:image"[^>]*' | head -2
