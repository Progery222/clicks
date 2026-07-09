#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
docker exec $C curl -sS 'https://www.tiktok.com/oembed?url=https://www.tiktok.com/@philredpill891' | python3 -m json.tool 2>/dev/null | head -30
