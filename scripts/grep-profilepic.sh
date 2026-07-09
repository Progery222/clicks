#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" grep -o '.{0,80}profilePic.{0,80}' /app/.next/server/app/api/accounts/route.js 2>/dev/null | head -5
docker exec "$C" strings /app/.next/server/app/api/accounts/route.js 2>/dev/null | grep -iE 'avatar|profilePic|image-proxy|proxy' | head -20
docker exec "$C" find /app/.next/server/app/api -name '*avatar*' -o -name '*image*' -o -name '*proxy*' 2>/dev/null
