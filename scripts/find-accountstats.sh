#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -t -A -c \
  "SELECT id,name,fqdn,ports_mappings FROM applications WHERE name ILIKE '%account%' OR name ILIKE '%stats%';"

echo "=== all apps short ==="
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT id,name,ports_mappings FROM applications ORDER BY id;"
