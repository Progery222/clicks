#!/bin/bash
# Redeploy Bio links (Coolify app id=14) on Mobile Farm.
# Usage: bash coolify-redeploy-clicks.sh [commit-ish]
set -euo pipefail

COMMIT="${1:-HEAD}"
UUID=$(openssl rand -hex 12)

echo "=== Queue deploy uuid=$UUID commit=$COMMIT ==="
docker exec coolify-db psql -U coolify -d coolify -v ON_ERROR_STOP=1 -c "
INSERT INTO application_deployment_queues (
  application_id, deployment_uuid, pull_request_id, force_rebuild, commit, status,
  is_webhook, restart_only, server_id, destination_id, created_at, updated_at,
  only_this_server, rollback, is_api, application_name, server_name
) VALUES (
  '14', '${UUID}', 0, true, '${COMMIT}', 'queued',
  true, false, 0, 0, NOW(), NOW(), false, false, true,
  'clicks:analytics', 'atom@10.20.87.230'
);
"

QUEUE_ID=$(docker exec coolify-db psql -U coolify -d coolify -t -A -c \
  "SELECT id FROM application_deployment_queues WHERE deployment_uuid='${UUID}';")
echo "QUEUE_ID=$QUEUE_ID"

echo "=== Dispatch ApplicationDeploymentJob ==="
docker exec coolify php artisan tinker --execute="
App\Jobs\ApplicationDeploymentJob::dispatch((int) ${QUEUE_ID});
echo 'dispatched\n';
"

echo "=== Waiting up to 450s ==="
for i in $(seq 1 90); do
  STATUS=$(docker exec coolify-db psql -U coolify -d coolify -t -A -c \
    "SELECT status FROM application_deployment_queues WHERE id=${QUEUE_ID};")
  COMMIT_ROW=$(docker exec coolify-db psql -U coolify -d coolify -t -A -c \
    "SELECT commit FROM application_deployment_queues WHERE id=${QUEUE_ID};")
  echo "[$i] status=$STATUS commit=$COMMIT_ROW"
  if [ "$STATUS" = "finished" ]; then break; fi
  if [ "$STATUS" = "failed" ]; then
    docker exec coolify-db psql -U coolify -d coolify -c \
      "SELECT id,status,commit,created_at,finished_at FROM application_deployment_queues WHERE id=${QUEUE_ID};"
    exit 1
  fi
  sleep 5
done

CONTAINER=$(docker ps --filter publish=8102 --format '{{.Names}}' | head -1)
echo "IMAGE=$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')"
curl -fsS -m 5 http://127.0.0.1:8102/health && echo
curl -fsS -m 5 -H 'Host: bytl.org' http://127.0.0.1/health && echo " bytl.org OK"
