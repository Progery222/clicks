#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -c "SELECT id,name,uuid,git_repository FROM applications WHERE id=25;"
echo "=== env ==="
docker exec vjbih0pvgs6inosh9ramfqlm-144035652234 env | grep -iE 'DATABASE|POSTGRES|DB_|PRISMA' | sed 's/=.*/=***/'
