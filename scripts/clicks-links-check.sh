#!/bin/bash
C=q11rqz2pmrlq4auva577uapd-144811929297
docker exec $C python -c "
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    url = os.environ.get('DATABASE_URL','')
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+asyncpg://', 1)
    elif url.startswith('postgresql://') and '+asyncpg' not in url:
        url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    e = create_async_engine(url)
    async with e.connect() as c:
        total = (await c.execute(text('select count(*) from links'))).scalar()
        av = (await c.execute(text('select count(*) from links where account_avatar_url is not null'))).scalar()
        print('links total', total, 'with avatar', av)
        rows = (await c.execute(text(\"select platform, left(label,55), left(account_avatar_url,55) from links where label ilike '%phil%' or label ilike '%yllazen%' limit 8\"))).all()
        for r in rows: print(r)
    await e.dispose()

asyncio.run(main())
"
