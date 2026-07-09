#!/bin/bash
set -euo pipefail
PG=t14ip5v8bhxqxpt2n6ujilme

docker exec "$PG" psql -U socialhub -d social_dashboard -c '\dt'

echo "=== columns with avatar ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT table_name,column_name FROM information_schema.columns WHERE column_name ILIKE '%avatar%' OR column_name ILIKE '%photo%' OR column_name ILIKE '%image%' OR column_name ILIKE '%pic%' ORDER BY table_name;"

echo "=== sample accounts ==="
docker exec "$PG" psql -U socialhub -d social_dashboard -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name ILIKE '%account%';"
