#!/bin/bash
docker exec vjbih0pvgs6inosh9ramfqlm-144035652234 env | grep -iE 'DATABASE|DIRECT|POSTGRES|SUPABASE|NEON' | sed 's/=.*/=***/'

echo "=== account count ==="
docker exec t14ip5v8bhxqxpt2n6ujilme psql -U socialhub -d social_dashboard -t -A -c 'SELECT count(*) FROM accounts;'

echo "=== search by url pattern tiktok phil ==="
docker exec t14ip5v8bhxqxpt2n6ujilme psql -U socialhub -d social_dashboard -c \
  "SELECT id, platform, username, left(profile_pic,50) FROM accounts WHERE url ILIKE '%tiktok.com/@phil%' LIMIT 10;"

echo "=== clicks: philredpill link ==="
docker exec ns4nylsxbxjslgqgx73jog4s psql -U postgres -d postgres -c \
  "SELECT label, platform, account_avatar_url FROM links WHERE label ILIKE '%philredpill%';"
