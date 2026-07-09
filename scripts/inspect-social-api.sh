#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" grep -r "profilePic\|profile_pic\|avatar" /app/.next/server/app --include='*.js' 2>/dev/null | head -20
docker exec "$C" find /app/.next/server/app/api -type f 2>/dev/null | head -30
