#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -c "\d environment_variables"
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT id,key,left(value,20),is_preview FROM environment_variables WHERE resourceable_id=25 LIMIT 3;"
