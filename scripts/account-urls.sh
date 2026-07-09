#!/bin/bash
docker exec t14ip5v8bhxqxpt2n6ujilme psql -U socialhub -d social_dashboard -c \
  "SELECT platform, username, url, left(profile_pic,60) FROM accounts WHERE platform='TIKTOK' LIMIT 5;"
