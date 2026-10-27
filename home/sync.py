"""Sync: pulls new snapshots from the cloud buffer and writes them to the local PostgreSQL.

If the computer was off, on the next start it catches up with everything accumulated in the cloud.
Writes are idempotent (primary key item_id+source+ts), so re-loading creates no duplicates.
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from . import config
from .db import pool

log = logging.getLogger("sync")


def _cursor(conn, key: str = "cloud_cursor") -> int:
    row = conn.execute("SELECT value FROM sync_state WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else 0


def _set_cursor(conn, key: str, value: int):
    conn.execute("""INSERT INTO sync_state VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (key, value))


def _store(conn, batch: dict, new_cursor: int):
    ids: dict[str, int] = {}
    for it in batch["items"]:
        row = conn.execute(
            """INSERT INTO items (market_hash_name, item_type, icon_url) VALUES (%s, %s, %s)
               ON CONFLICT (market_hash_name) DO UPDATE
               SET icon_url = COALESCE(EXCLUDED.icon_url, items.icon_url)
               RETURNING id""",
            (it["market_hash_name"], it["item_type"], it["icon_url"])).fetchone()
        ids[it["market_hash_name"]] = row["id"]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO price_ticks (item_id, source, ts, price_cents, currency, listings)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            [(ids[t["market_hash_name"]], t["source"], datetime.fromtimestamp(t["ts"], timezone.utc),
              t["price_cents"], t["currency"], t["listings"]) for t in batch["ticks"]])
    _set_cursor(conn, "cloud_cursor", new_cursor)


def sync_once(client: httpx.Client) -> int:
    """Pulls everything accumulated. Returns the number of snapshots received."""
    total = 0
    while True:
        with pool.connection() as conn:
            cursor = _cursor(conn)
        r = client.get(f"{config.CLOUD_URL}/api/ticks", params={"after_id": cursor, "limit": config.SYNC_BATCH})
        r.raise_for_status()
        batch = r.json()
        if batch["max_id"] < cursor:
            # The cloud buffer was recreated and ids restarted: pull from the beginning,
            # duplicates are filtered out by the primary key.
            log.warning("cloud buffer recreated (max_id %s < cursor %s), resetting the cursor",
                        batch["max_id"], cursor)
            with pool.connection() as conn:
                _set_cursor(conn, "cloud_cursor", 0)
            continue
        if not batch["ticks"]:
            return total
        new_cursor = batch["ticks"][-1]["id"]
        with pool.connection() as conn:  # one transaction: data + cursor
            _store(conn, batch, new_cursor)
        client.post(f"{config.CLOUD_URL}/api/ack", json={"up_to_id": new_cursor}).raise_for_status()
        total += len(batch["ticks"])
        log.info("received %d snapshots, cursor %d", len(batch["ticks"]), new_cursor)
        if not batch["has_more"]:
            return total


def _store_sales(conn, rows: list[dict], new_cursor: int):
    names = sorted({r["market_hash_name"] for r in rows})
    ids = {r["market_hash_name"]: r["id"] for r in conn.execute(
        "SELECT id, market_hash_name FROM items WHERE market_hash_name = ANY(%s)", (names,)).fetchall()}
    for n in names:
        if n not in ids:  # history arrived before the first price of this item
            ids[n] = conn.execute(
                """INSERT INTO items (market_hash_name, item_type) VALUES (%s, 'case')
                   ON CONFLICT (market_hash_name) DO UPDATE SET item_type = items.item_type
                   RETURNING id""", (n,)).fetchone()["id"]
    with conn.cursor() as cur:
        # A daily point replaces hourly points of the same day stored earlier (Steam has since folded
        # that day into one point). Otherwise that day's sales would be counted twice.
        daily = [r for r in rows if r.get("span", 3600) == 86400]
        cur.executemany(
            """DELETE FROM sales_history WHERE item_id = %s AND source = %s
               AND ts >= %s AND ts < %s + interval '1 day' AND ts <> %s""",
            [(ids[r["market_hash_name"]], r["source"], day, day, ts)
             for r in daily
             for ts in [datetime.fromtimestamp(r["ts"], timezone.utc)]
             for day in [datetime.fromtimestamp(r["ts"] // 86400 * 86400, timezone.utc)]])
        cur.executemany(
            """INSERT INTO sales_history (item_id, source, ts, median_cents, volume, currency, span_secs)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (item_id, source, ts) DO UPDATE
               SET median_cents = EXCLUDED.median_cents, volume = EXCLUDED.volume, currency = EXCLUDED.currency,
                   span_secs = EXCLUDED.span_secs""",
            [(ids[r["market_hash_name"]], r["source"], datetime.fromtimestamp(r["ts"], timezone.utc),
              r["median_cents"], r["volume"], r["currency"], r.get("span", 3600)) for r in rows])
    _set_cursor(conn, "cloud_sales_cursor", new_cursor)


def sync_sales_once(client: httpx.Client) -> int:
    """Pulls accumulated sales history (the first time it spans years, possibly 100k+ points)."""
    total = 0
    while True:
        with pool.connection() as conn:
            cursor = _cursor(conn, "cloud_sales_cursor")
        r = client.get(f"{config.CLOUD_URL}/api/sales", params={"after_id": cursor, "limit": config.SYNC_BATCH})
        if r.status_code == 404:  # cloud runs an older version without sales history
            return 0
        r.raise_for_status()
        batch = r.json()
        if batch["max_id"] < cursor:
            log.warning("cloud sales buffer recreated, resetting the cursor")
            with pool.connection() as conn:
                _set_cursor(conn, "cloud_sales_cursor", 0)
            continue
        if not batch["sales"]:
            return total
        new_cursor = batch["sales"][-1]["id"]
        with pool.connection() as conn:
            _store_sales(conn, batch["sales"], new_cursor)
        client.post(f"{config.CLOUD_URL}/api/ack", json={"sales_up_to_id": new_cursor}).raise_for_status()
        total += len(batch["sales"])
        log.info("received %d sales-history points, cursor %d", len(batch["sales"]), new_cursor)
        if not batch["has_more"]:
            return total


def sync_items_once(client: httpx.Client) -> int:
    """Daily prices of items inside cases (for EV). The first time it is years of history for ~10k items."""
    total = 0
    while True:
        with pool.connection() as conn:
            cursor = _cursor(conn, "cloud_items_cursor")
        r = client.get(f"{config.CLOUD_URL}/api/item_days", params={"after_id": cursor, "limit": config.SYNC_BATCH})
        if r.status_code == 404:  # cloud runs an older version
            return 0
        r.raise_for_status()
        batch = r.json()
        if batch["max_id"] < cursor:
            log.warning("cloud item-price buffer recreated, resetting the cursor")
            with pool.connection() as conn:
                _set_cursor(conn, "cloud_items_cursor", 0)
            continue
        if not batch["items"]:
            return total
        new_cursor = batch["items"][-1]["id"]
        with pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO item_days (market_hash_name, day, median_cents, volume)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (market_hash_name, day) DO UPDATE
                   SET median_cents = EXCLUDED.median_cents, volume = EXCLUDED.volume""",
                [(r["market_hash_name"], datetime.fromtimestamp(r["day"], timezone.utc).date(),
                  r["median_cents"], r["volume"]) for r in batch["items"]])
            _set_cursor(conn, "cloud_items_cursor", new_cursor)
        client.post(f"{config.CLOUD_URL}/api/ack", json={"items_up_to_id": new_cursor}).raise_for_status()
        total += len(batch["items"])
        log.info("received %d daily item prices, cursor %d", len(batch["items"]), new_cursor)
        if not batch["has_more"]:
            return total


def run_forever(stop=None):
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {config.CLOUD_TOKEN}"}) as client:
        while not (stop and stop.is_set()):
            try:
                sync_once(client)
                sync_sales_once(client)
                sync_items_once(client)
            except Exception as e:  # cloud unreachable, no internet, etc.: try again later
                log.warning("sync failed: %r", e)
            if stop:
                stop.wait(config.SYNC_INTERVAL)
            else:
                time.sleep(config.SYNC_INTERVAL)
