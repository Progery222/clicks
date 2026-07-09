#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT resourceable_id, key FROM environment_variables WHERE key ILIKE '%DATABASE%' OR key ILIKE '%SUPABASE%' OR value ILIKE '%supabase%' LIMIT 30;"
