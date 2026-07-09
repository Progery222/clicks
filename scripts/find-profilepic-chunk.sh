#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" grep -rl "profilePic" /app/.next/server/chunks 2>/dev/null | head -10
for f in $(docker exec "$C" grep -rl "profilePic" /app/.next/server/chunks 2>/dev/null | head -3); do
  echo "=== $f ==="
  docker exec "$C" strings "$f" 2>/dev/null | grep -i profilePic | head -5
done
