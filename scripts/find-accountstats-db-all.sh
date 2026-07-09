#!/bin/bash
echo "=== Coolify apps with account/stats in name ==="
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT id,name,uuid,ports_mappings FROM applications WHERE name ILIKE '%account%' OR name ILIKE '%stats%' OR name ILIKE '%social%';"

echo "=== Search philredpill in all postgres containers ==="
for c in $(docker ps --format '{{.Names}}' | grep -i postgres); do
  echo "--- $c ---"
  docker exec "$c" psql -U postgres -d postgres -t -A -c "SELECT 1" 2>/dev/null && \
    docker exec "$c" psql -U postgres -d postgres -c "\l" 2>/dev/null | head -8 || true
  for db in postgres social_dashboard accountstats; do
    for user in postgres socialhub; do
      docker exec "$c" psql -U "$user" -d "$db" -t -A -c \
        "SELECT count(*) FROM accounts WHERE username ILIKE '%philred%' OR url ILIKE '%philred%';" 2>/dev/null && \
        echo "  FOUND in $c db=$db user=$user" || true
    done
  done
done
