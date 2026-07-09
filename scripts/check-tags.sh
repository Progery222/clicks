#!/bin/bash
PG=t14ip5v8bhxqxpt2n6ujilme
docker exec "$PG" psql -U socialhub -d social_dashboard -c '\d snapshots'
docker exec "$PG" psql -U socialhub -d social_dashboard -c 'SELECT * FROM snapshots LIMIT 3;'
docker exec "$PG" psql -U socialhub -d social_dashboard -c 'SELECT id, name FROM tags LIMIT 20;'
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT t.name, count(*) FROM tags t JOIN account_tags at ON at.tag_id=t.id JOIN accounts a ON a.id=at.account_id GROUP BY t.name;"
