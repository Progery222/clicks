#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -t -A -c "SELECT value FROM environment_variables WHERE resourceable_id=14 AND key='DATABASE_URL' LIMIT 1;"
