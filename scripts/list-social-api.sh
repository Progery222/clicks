#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" find /app/.next/server/app/api -name 'route.js' | sed 's|/app/.next/server/app||;s|/route.js||'
