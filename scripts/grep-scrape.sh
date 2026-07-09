#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
for f in /app/.next/server/app/api/accounts/check-url/route.js /app/.next/server/app/api/update/route.js; do
  echo "=== $f ==="
  docker exec "$C" strings "$f" 2>/dev/null | grep -iE 'profile|avatar|scrape|pic|image|puppeteer|tiktok|instagram' | head -25
done
