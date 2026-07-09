#!/bin/bash
C=$(docker ps --format '{{.Names}}' | grep q11rqz2pmrlq4auva577uapd | head -1)
docker exec $C python -c "
import asyncio, os, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def main():
    url = os.environ['DATABASE_URL']
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+asyncpg://', 1)
    elif url.startswith('postgresql://') and '+asyncpg' not in url:
        url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    e = create_async_engine(url)
    Session = sessionmaker(e, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        row = (await db.execute(text(\"select id, label, platform from links where label ilike '%philredpill891%' limit 1\"))).first()
        print('link', row)
        if not row:
            return
        from app.models import Link
        from app.services.admin_avatar import resolve_and_cache_link_avatar
        link = await db.get(Link, row[0])
        pic = await resolve_and_cache_link_avatar(db, link)
        print('resolved', pic[:100] if pic else None)
    await e.dispose()

asyncio.run(main())
"
