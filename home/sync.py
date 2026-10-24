"""Синхронизатор: забирает новые снимки из облачного буфера и пишет в локальный PostgreSQL.

Если компьютер был выключен, при следующем запуске он догонит всё, что накопилось в облаке.
Запись идемпотентна (первичный ключ item_id+source+ts), поэтому повторная загрузка не создаёт дублей.
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from . import config
from .db import pool

log = logging.getLogger("sync")


def _cursor(conn) -> int:
    row = conn.execute("SELECT value FROM sync_state WHERE key = 'cloud_cursor'").fetchone()
    return row["value"] if row else 0


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
    conn.execute(
        """INSERT INTO sync_state VALUES ('cloud_cursor', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (new_cursor,))


def sync_once(client: httpx.Client) -> int:
    """Забирает всё, что накопилось. Возвращает число полученных снимков."""
    total = 0
    while True:
        with pool.connection() as conn:
            cursor = _cursor(conn)
        r = client.get(f"{config.CLOUD_URL}/api/ticks", params={"after_id": cursor, "limit": config.SYNC_BATCH})
        r.raise_for_status()
        batch = r.json()
        if batch["max_id"] < cursor:
            # Облачный буфер пересоздали и нумерация началась заново: забираем с начала,
            # дубли отсеются первичным ключом.
            log.warning("буфер в облаке пересоздан (max_id %s < курсора %s), сбрасываю курсор",
                        batch["max_id"], cursor)
            with pool.connection() as conn:
                conn.execute("UPDATE sync_state SET value = 0 WHERE key = 'cloud_cursor'")
            continue
        if not batch["ticks"]:
            return total
        new_cursor = batch["ticks"][-1]["id"]
        with pool.connection() as conn:  # одна транзакция: данные + курсор
            _store(conn, batch, new_cursor)
        client.post(f"{config.CLOUD_URL}/api/ack", json={"up_to_id": new_cursor}).raise_for_status()
        total += len(batch["ticks"])
        log.info("получено %d снимков, курсор %d", len(batch["ticks"]), new_cursor)
        if not batch["has_more"]:
            return total


def run_forever(stop=None):
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {config.CLOUD_TOKEN}"}) as client:
        while not (stop and stop.is_set()):
            try:
                sync_once(client)
            except Exception as e:  # облако недоступно, нет интернета и т.п. — попробуем позже
                log.warning("синхронизация не удалась: %r", e)
            if stop:
                stop.wait(config.SYNC_INTERVAL)
            else:
                time.sleep(config.SYNC_INTERVAL)
