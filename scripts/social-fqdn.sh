#!/bin/bash
docker exec coolify-db psql -U coolify -d coolify -c "SELECT id,name,fqdn FROM applications WHERE id=25;"
docker ps --filter name=vjbih0 --format '{{.Names}} {{.Ports}}'
