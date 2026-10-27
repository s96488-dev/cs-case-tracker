"""Daily case EV from daily item prices (see common/ev.py).

Every minute we check for new prices and recompute at most every EV_INTERVAL.

Case contents and odds come from common/case_contents.py (the open ByMykel/CSGO-API dataset, downloaded daily).
"""
import logging
import time
from datetime import UTC, datetime

import httpx

from common.case_contents import CRATES_URL, SKINS_URL, build
from common.ev import DAY, case_ev

from . import config
from .db import pool

log = logging.getLogger("ev")
MIN_COVERAGE = 0.8


def _epoch(d) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


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
        # The cloud collects cases one by one: until a case's prices are mostly collected its EV is too low, so skip it.
        if not series or series[-1][2] < MIN_COVERAGE:
            continue
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM case_ev WHERE item_id = %s", (case["id"],))
            cur.executemany("INSERT INTO case_ev VALUES (%s, %s, %s, %s)",
                            [(case["id"], datetime.fromtimestamp(d, UTC).date(), ev, cov)
                             for d, ev, cov in series])
        done += 1
    return done


def run_forever(stop):
    contents, loaded_at, last_cursor, computed_at = {}, 0.0, None, 0.0
    with httpx.Client(timeout=120) as client:
        while not stop.is_set():
            try:
                if time.time() - loaded_at > 86400:
                    contents = build(client.get(CRATES_URL).json(), client.get(SKINS_URL).json())
                    loaded_at = time.time()
                with pool.connection() as conn:
                    row = conn.execute("SELECT value FROM sync_state WHERE key = 'cloud_items_cursor'").fetchone()
                cursor = row["value"] if row else None
                if cursor and cursor != last_cursor and time.time() - computed_at >= config.EV_INTERVAL:
                    n = compute_all(contents)
                    last_cursor, computed_at = cursor, time.time()
                    log.info("EV recomputed for %d cases", n)
            except Exception as e:  # no network to GitHub etc.: try again later
                log.warning("EV not computed: %r", e)
            stop.wait(60)
