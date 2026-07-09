#!/bin/bash
PG=t14ip5v8bhxqxpt2n6ujilme
docker exec "$PG" psql -U socialhub -d social_dashboard -c '\dt'
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT count(*) FROM accounts WHERE is_active = false;"
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, left(url,60) FROM accounts WHERE is_active = false LIMIT 10;" 2>/dev/null

echo "=== overlap clicks <-> accountstats by url ==="
docker exec ns4nylsxbxjslgqgx73jog4s psql -U postgres -d postgres -c \
  "SELECT l.label, l.platform, a.profile_pic IS NOT NULL as has_pic
   FROM links l
   LEFT JOIN dblink('host=t14ip5v8bhxqxpt2n6ujilme dbname=social_dashboard user=socialhub password=b344548afd818cc1332669cba0ef2ffd',
     'SELECT url, profile_pic FROM accounts') AS a(url text, profile_pic text)
   ON lower(regexp_replace(regexp_replace(rtrim(l.label, '/'), '^https?://(www\.)?', ''), '\?.*$', '')) = lower(regexp_replace(regexp_replace(rtrim(a.url, '/'), '^https?://(www\.)?', ''), '\?.*$', ''))
   LIMIT 10;" 2>&1 | head -15
