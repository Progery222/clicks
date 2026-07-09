#!/bin/bash
docker exec ns4nylsxbxjslgqgx73jog4s psql -U postgres -d postgres -c \
  "SELECT count(*) FILTER (WHERE account_avatar_url IS NOT NULL AND account_avatar_url != '') as with_avatar,
          count(*) as total FROM links;"
docker exec ns4nylsxbxjslgqgx73jog4s psql -U postgres -d postgres -c \
  "SELECT label, left(account_avatar_url,70) FROM links WHERE account_avatar_url IS NOT NULL AND account_avatar_url != '' LIMIT 10;"
