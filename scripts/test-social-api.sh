#!/bin/bash
SD=vjbih0pvgs6inosh9ramfqlm-144035652234
C=q11rqz2pmrlq4auva577uapd-144811929297
# internal hostname from docker network
SD_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $SD)
echo "social-dashboard ip: $SD_IP"
docker exec $C curl -sS -m 15 -X POST "http://${SD_IP}:3000/api/accounts/check-url" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.tiktok.com/@philredpill891"}' | head -c 500
echo ""
docker exec $C curl -sS -m 5 "http://${SD_IP}:3000/api/accounts" | head -c 300
echo ""
