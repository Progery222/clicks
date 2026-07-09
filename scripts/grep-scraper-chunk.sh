#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" find /app/.next/server/chunks -name '*scraper*' -o -name '*account*' 2>/dev/null | head -20
docker exec "$C" strings /app/.next/server/chunks/src_lib_video-scraper_ts_cddca6b6._.js 2>/dev/null | grep -iE 'profilePic|profile_pic|avatar|userpic|og:image' | head -20
