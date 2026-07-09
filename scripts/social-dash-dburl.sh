#!/bin/bash
set -euo pipefail

echo "=== Full DATABASE_URL (internal) ==="
docker exec vjbih0pvgs6inosh9ramfqlm-144035652234 sh -c 'echo "$DATABASE_URL"'

echo "=== Related containers same project ==="
docker ps -a --format '{{.Names}}' | grep vjbih0 || true
