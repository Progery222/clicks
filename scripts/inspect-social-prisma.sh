#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" find /app -name 'schema.prisma' 2>/dev/null
docker exec "$C" cat /app/prisma/schema.prisma 2>/dev/null | head -80
docker exec "$C" grep -r "profile_pic\|profilePic\|avatar" /app/.next/server --include='*.js' -l 2>/dev/null | head -5
docker exec "$C" ls -la /app 2>/dev/null | head -20
