#!/bin/bash
set -e
POSTGRES=$(docker ps --format '{{.Names}}' | grep t14ip5v8bhxqxpt2n6ujilme | head -1)
CLICKS=$(docker ps --format '{{.Names}}' | grep -E '8102|clicks' | head -1)
echo "postgres=$POSTGRES clicks=$CLICKS"

docker exec "$POSTGRES" psql -U socialhub -d social_dashboard -t -c "SELECT count(*) FROM accounts WHERE profile_pic IS NOT NULL AND btrim(profile_pic)<>'';"

docker exec "$POSTGRES" psql -U socialhub -d social_dashboard -c "SELECT platform, username, left(url,45), left(profile_pic,50) FROM accounts WHERE username ILIKE '%phil%' OR url ILIKE '%phil%' OR username ILIKE '%yllazen%' LIMIT 10;"

docker exec "$POSTGRES" psql -U clicks -d clicks -c "SELECT platform, left(label,50), left(account_avatar_url,50) FROM links WHERE label ILIKE '%phil%' OR label ILIKE '%yllazen%' LIMIT 10;"

docker exec "$POSTGRES" psql -U clicks -d clicks -c "SELECT count(*) FILTER (WHERE account_avatar_url IS NOT NULL) AS with_avatar, count(*) AS total FROM links;"
