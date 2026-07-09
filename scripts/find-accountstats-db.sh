#!/bin/bash
set -euo pipefail

echo "=== social-dashboard containers ==="
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' | grep -i vjbih0 || true

APP_UUID=vjbih0pvgs6inosh9ramfqlm
find /data/coolify -name 'docker-compose*.y*ml' 2>/dev/null | while read f; do
  if grep -q "$APP_UUID" "$f" 2>/dev/null; then echo "COMPOSE=$f"; fi
done

echo "=== Coolify app 25 ==="
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT id,name,uuid,git_repository,ports_mappings FROM applications WHERE id=25;"

echo "=== Postgres containers ==="
docker ps --format '{{.Names}}\t{{.Image}}' | grep -i postgres | head -20
