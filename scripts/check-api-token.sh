#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
docker exec "$C" printenv API_TOKEN | awk '{ if (length($0)>0) print "API_TOKEN=set len=" length($0); else print "API_TOKEN=empty" }'
