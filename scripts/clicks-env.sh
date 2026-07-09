#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -c \
  "SELECT key, left(value,40) FROM environment_variables WHERE resourceable_type LIKE '%Application%' AND resourceable_id=14;"
