#!/bin/bash
CLICKS=$(docker ps --filter publish=8102 --format '{{.Names}}' | head -1)
docker exec "$CLICKS" python -c "
import asyncio
from app.services.accountstats_avatar import lookup_profile_pics_batch, _normalize_profile_url
from app.services.account_avatar import account_profile_url

samples = [
  ('https://www.tiktok.com/@yllazenspace', 'tiktok'),
  ('https://www.threads.com/@yllazenspace', 'threads'),
  ('https://instagram.com/yllazensound', 'instagram'),
  ('philgodlewski.atom', 'telegram'),
]

for label, plat in samples:
    pu = account_profile_url(label, plat)
    print('LABEL', label, 'PLAT', plat)
    print('  profile_url', pu)
    print('  norm', _normalize_profile_url(pu) if pu else None)
    if label.startswith('http'):
        print('  norm_label', _normalize_profile_url(label))

async def main():
    r = await lookup_profile_pics_batch(samples)
    print('BATCH', r)
asyncio.run(main())
"
