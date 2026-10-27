"""Valve CS news: pulls official announcements from the Steam News API and links them to cases.

The first run loads the whole feed for all years, then new items are fetched hourly.
A news item is linked to a case if its title or text contains the exact case name.
"""
import logging
import re
from datetime import UTC, datetime

import httpx

from . import config
from .db import pool

log = logging.getLogger("news")

NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
FEED = "steam_community_announcements"
PAGE = 100


def _fetch_page(client: httpx.Client, enddate: int | None) -> list[dict]:
    params: dict[str, int | str] = {"appid": 730, "count": PAGE, "maxlength": 0, "feeds": FEED}
    if enddate:
        params["enddate"] = enddate
    r = client.get(NEWS_URL, params=params)
    r.raise_for_status()
    return r.json().get("appnews", {}).get("newsitems", [])


def _known(conn) -> tuple[set[str], int | None]:
    rows = conn.execute("SELECT gid FROM news").fetchall()
    newest = conn.execute("SELECT extract(epoch FROM max(ts))::bigint AS t FROM news").fetchone()["t"]
    return {r["gid"] for r in rows}, newest


def fetch_news(client: httpx.Client) -> int:
    """Fetches news from newest to oldest until it reaches already stored items or the end of the feed."""
    with pool.connection() as conn:
        known, newest = _known(conn)
    added, enddate = [], None
    while True:
        page = _fetch_page(client, enddate)
        fresh = [n for n in page if n["gid"] not in known]
        added += fresh
        known.update(n["gid"] for n in fresh)
        if not fresh or len(page) < PAGE:
            break
        oldest = min(n["date"] for n in page)
        if newest and oldest <= newest:
            break
        # enddate is inclusive: items with the same second come again and are filtered out by gid.
        enddate = oldest
    if added:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO news (gid, ts, title, url, contents) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                [(n["gid"], datetime.fromtimestamp(n["date"], UTC), n["title"], n["url"],
                  n.get("contents") or "") for n in added])
    return len(added)


def _patterns(name: str) -> list[re.Pattern]:
    """'CS:GO Weapon Case' must not match 'CS:GO Weapon Case 2', so the name must not be followed by a digit."""
    names = {name}
    if name.endswith(" Weapon Case"):
        names.add(name[: -len(" Weapon Case")] + " Case")
    return [re.compile(r"(?<![\w])" + re.escape(n) + r"(?!\s*\d)(?![\w])", re.I) for n in names]


def link_news() -> int:
    """Rebuilds news-to-case links (thousands of news, dozens of cases, so it is fast)."""
    with pool.connection() as conn:
        items = conn.execute("SELECT id, market_hash_name FROM items WHERE item_type = 'case'").fetchall()
        news = conn.execute("SELECT gid, title, contents FROM news").fetchall()
        pairs = []
        for it in items:
            pats = _patterns(it["market_hash_name"])
            for n in news:
                text = n["title"] + "\n" + n["contents"]
                if any(p.search(text) for p in pats):
                    pairs.append((it["id"], n["gid"]))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO item_news VALUES (%s, %s) ON CONFLICT DO NOTHING", pairs)
    return len(pairs)


def run_forever(stop):
    with httpx.Client(timeout=30, headers={"User-Agent": "cs-case-tracker"}) as client:
        while not stop.is_set():
            try:
                added = fetch_news(client)
                links = link_news()
                if added:
                    log.info("news added: %s, links to cases: %s", added, links)
            except Exception as e:  # network or Steam unavailable: try next time
                log.warning("news failed to load: %s", e)
            stop.wait(config.NEWS_INTERVAL)
