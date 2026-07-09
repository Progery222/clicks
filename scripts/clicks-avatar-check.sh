#!/bin/bash
C=q11rqz2pmrlq4auva577uapd-144811929297
docker exec $C printenv ACCOUNTSTATS_DATABASE_URL | head -c 80
echo "..."
docker exec $C python -c "
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    url = os.environ.get('ACCOUNTSTATS_DATABASE_URL','').replace('postgresql://','postgresql+asyncpg://')
    e = create_async_engine(url)
    async with e.connect() as c:
        n = (await c.execute(text('select count(*) from accounts where profile_pic is not null'))).scalar()
        print('accounts with pic:', n)
        rows = (await c.execute(text(\"select platform, username, left(profile_pic,60) from accounts limit 5\"))).all()
        for r in rows: print(r)
    await e.dispose()

asyncio.run(main())
"
