#!/bin/bash
PG=t14ip5v8bhxqxpt2n6ujilme
docker exec $PG psql -U socialhub -d social_dashboard -c "\d accounts"
docker exec $PG psql -U socialhub -d social_dashboard -c "SELECT count(*), campaign FROM accounts GROUP BY campaign ORDER BY count DESC LIMIT 15;"
docker exec $PG psql -U socialhub -d social_dashboard -c "SELECT platform, username, left(url,50), campaign FROM accounts WHERE platform='TIKTOK' LIMIT 10;"
