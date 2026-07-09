#!/bin/bash
set -euo pipefail

C=$(docker ps --filter publish=8102 --format '{{.Names}}' | head -1)
echo "CONTAINER=$C"
docker ps --filter publish=8102 --format 'status={{.Status}}'
docker inspect "$C" --format 'restarts={{.RestartCount}} started={{.State.StartedAt}}'

echo "=== HTTP via traefik ==="
for path in /health /admin /admin/login /static/style.css; do
  curl -sS -m 15 -o /dev/null -w "$path -> %{http_code} %{time_total}s redirects=%{num_redirects}\n" \
    -H 'Host: bytl.org' "http://127.0.0.1${path}"
done

echo "=== Redirect chain /admin ==="
curl -sS -m 15 -I -H 'Host: bytl.org' http://127.0.0.1/admin | head -15

echo "=== App errors last 50 lines ==="
docker logs "$C" --tail 50 2>&1 | grep -iE 'error|exception|traceback|failed' || echo "(no errors in tail)"
