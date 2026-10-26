"""Расчёт EV кейсов по дням из дневных цен предметов (см. common/ev.py) раз в час, если пришли новые цены.

Состав кейсов и шансы — common/case_contents.py (открытый набор ByMykel/CSGO-API, скачивается раз в сутки).
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from common.case_contents import CRATES_URL, SKINS_URL, build
from common.ev import DAY, case_ev

from . import config
from .db import pool

log = logging.getLogger("ev")


def _epoch(d) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def compute_all(contents: dict[str, dict[str, float]]) -> int:
    with pool.connection() as conn:
        cases = conn.execute("SELECT id, market_hash_name FROM items WHERE item_type = 'case'").fetchall()
    today = int(time.time()) // DAY * DAY
    done = 0
    for case in cases:
        probs = contents.get(case["market_hash_name"])
        if not probs:
            continue
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT market_hash_name, day, median_cents, volume FROM item_days
                   WHERE market_hash_name = ANY(%s) ORDER BY day""", (list(probs),)).fetchall()
        if not rows:
            continue
        item_days: dict[str, list] = {}
        for r in rows:
            item_days.setdefault(r["market_hash_name"], []).append((_epoch(r["day"]), r["median_cents"], r["volume"]))
        start = min(d[0][0] for d in item_days.values())
        series = case_ev(probs, item_days, start, today)
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM case_ev WHERE item_id = %s", (case["id"],))
            cur.executemany("INSERT INTO case_ev VALUES (%s, %s, %s, %s)",
                            [(case["id"], datetime.fromtimestamp(d, timezone.utc).date(), ev, cov)
                             for d, ev, cov in series])
        done += 1
    return done


def run_forever(stop):
    contents, loaded_at, last_cursor = {}, 0.0, None
    with httpx.Client(timeout=120) as client:
        while not stop.is_set():
            try:
                if time.time() - loaded_at > 86400:
                    contents = build(client.get(CRATES_URL).json(), client.get(SKINS_URL).json())
                    loaded_at = time.time()
                with pool.connection() as conn:
                    row = conn.execute("SELECT value FROM sync_state WHERE key = 'cloud_items_cursor'").fetchone()
                cursor = row["value"] if row else None
                if cursor and cursor != last_cursor:
                    n = compute_all(contents)
                    last_cursor = cursor
                    log.info("EV пересчитан для %d кейсов", n)
            except Exception as e:  # нет сети до GitHub и т.п.: попробуем позже
                log.warning("EV не посчитан: %r", e)
            stop.wait(config.EV_INTERVAL)
