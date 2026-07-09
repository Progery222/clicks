#!/usr/bin/env python3
"""Compare clicks links vs accountstats accounts on server."""
import asyncio
import os
import re
from urllib.parse import urlparse

import asyncpg

CLICKS = os.environ.get("CLICKS_DB", "postgresql://clicks:clicks@t14ip5v8bhxqxpt2n6ujilme:5432/clicks")
STATS = os.environ.get("STATS_DB", "postgresql://socialhub:socialhub@t14ip5v8bhxqxpt2n6ujilme:5432/social_dashboard")


def norm_url(url: str) -> str:
    u = urlparse(url.strip())
    host = (u.netloc or "").lower().removeprefix("www.")
    path = (u.path or "").rstrip("/")
    return f"{host}{path}".casefold()


async def main():
    c = await asyncpg.connect(CLICKS)
    s = await asyncpg.connect(STATS)

    links = await c.fetch(
        "SELECT id, label, platform, account_avatar_url FROM links WHERE label IS NOT NULL ORDER BY created_at DESC LIMIT 200"
    )
    accounts = await s.fetch(
        "SELECT id, platform, username, url, left(profile_pic, 80) AS pic FROM accounts WHERE profile_pic IS NOT NULL AND btrim(profile_pic) <> ''"
    )

    by_norm: dict[str, list] = {}
    by_user: dict[tuple[str, str], list] = {}
    for a in accounts:
        if a["url"]:
            by_norm.setdefault(norm_url(a["url"]), []).append(a)
        key = (str(a["platform"]).upper(), str(a["username"]).casefold())
        by_user.setdefault(key, []).append(a)

    print(f"accounts with pic: {len(accounts)}")
    print(f"links sample: {len(links)}")
    matched = 0
    for ln in links:
        label = str(ln["label"]).strip()
        plat = (ln["platform"] or "").upper()
        # simple username from label
        user = label.lstrip("@").split("/")[-1].split("?")[0]
        if re.match(r"^https?://", label, re.I):
            nu = norm_url(label)
            hit = by_norm.get(nu)
        else:
            hit = by_user.get((plat, user.casefold()))
        if hit:
            matched += 1
            if matched <= 5:
                print("MATCH", ln["label"][:50], "->", hit[0]["pic"][:60])
    print("matched", matched, "of", len(links))

    phil = await c.fetch(
        "SELECT label, platform, account_avatar_url FROM links WHERE label ILIKE '%phil%' OR label ILIKE '%yllazen%' LIMIT 15"
    )
    print("\nphil/yllazen links:")
    for r in phil:
        print(" ", r["platform"], r["label"][:60], "avatar=", r["account_avatar_url"])

    phil_acc = await s.fetch(
        "SELECT platform, username, left(url,50), left(profile_pic,50) FROM accounts WHERE username ILIKE '%phil%' OR username ILIKE '%yllazen%' OR url ILIKE '%phil%' OR url ILIKE '%yllazen%' LIMIT 15"
    )
    print("\nphil/yllazen accounts:")
    for r in phil_acc:
        print(" ", r)

    await c.close()
    await s.close()


if __name__ == "__main__":
    asyncio.run(main())
