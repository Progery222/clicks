#!/bin/bash
CLICKS=$(docker ps --filter publish=8102 --format '{{.Names}}' | head -1)
docker exec "$CLICKS" python <<'PY'
import asyncio
import re
from urllib.parse import urlparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

CLICKS_URL = open('/proc/self/environ','rb').read().decode('latin1')
import os
# get from env
import os
cu = os.environ['DATABASE_URL'].replace('postgres://','postgresql+asyncpg://')
au = os.environ.get('ACCOUNTSTATS_DATABASE_URL','').replace('postgresql://','postgresql+asyncpg://')

def norm(url):
    u = urlparse(url.strip())
    host = (u.netloc or '').lower().removeprefix('www.')
    path = (u.path or '').rstrip('/')
    return f'{host}{path}'.casefold()

async def main():
    ce = create_async_engine(cu)
    ae = create_async_engine(au)
    async with ce.connect() as c, ae.connect() as a:
        links = (await c.execute(text("SELECT label, platform FROM links WHERE label IS NOT NULL"))).all()
        accounts = (await a.execute(text("SELECT url, profile_pic FROM accounts WHERE profile_pic IS NOT NULL AND profile_pic NOT ILIKE '%cdninstagram.com/rsrc%'"))).all()
        amap = {norm(url): pic for url, pic in accounts}
        matched = 0
        for label, plat in links:
            if not str(label).startswith('http'):
                continue
            n = norm(label)
            if n in amap:
                matched += 1
        print(f'links with http label: {sum(1 for l,_ in links if str(l).startswith("http"))}')
        print(f'accounts with pic: {len(amap)}')
        print(f'url matches: {matched}')

asyncio.run(main())
PY
