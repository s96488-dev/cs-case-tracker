"""Fills an empty database with synthetic demo data, so the chart page can be tried without the cloud
collector or a Steam account.

Real case names, made-up prices: a random walk per case for years of daily sales, the last 30 days hourly,
two days of minute snapshots and a daily EV line. Run: python -m home.demo [--force]
"""
import logging
import math
import random
import sys
import time
from datetime import UTC, datetime

from common.ev import DAY

from .db import ensure_database, open_pool, pool

log = logging.getLogger("demo")
H = 3600
# Case, price in dollars today, years of history.
CASES = [("Kilowatt Case", 0.95, 2.7), ("Revolution Case", 0.62, 3.7), ("Dreams & Nightmares Case", 1.45, 4.7),
         ("Recoil Case", 0.55, 4.3), ("Fracture Case", 0.48, 6), ("Clutch Case", 0.56, 8),
         ("Prisma 2 Case", 1.10, 6), ("Gallery Case", 2.30, 1.9)]


def _walk(rng: random.Random, n: int, end: float, vol: float) -> list[float]:
    """n daily prices of a random walk ending at `end`."""
    x, out = 0.0, []
    for _ in range(n):
        x += rng.gauss(0, vol)
        out.append(x)
    return [end * math.exp(v - out[-1]) for v in out]


def seed(force: bool = False) -> None:
    ensure_database()
    open_pool()
    try:
        _seed(force)
    finally:
        pool.close()


def _seed(force: bool) -> None:
    with pool.connection() as conn:
        if conn.execute("SELECT 1 FROM items LIMIT 1").fetchone() and not force:
            log.info("database is not empty, demo data not added (use --force to add anyway)")
            return
    rng = random.Random(42)
    now = int(time.time()) // 60 * 60
    today = now // DAY * DAY
    for name, price, years in CASES:
        days = int(years * 365)
        daily = _walk(rng, days, price, 0.025)
        ratio = _walk(rng, days, rng.uniform(0.35, 0.7), 0.02)
        with pool.connection() as conn, conn.cursor() as cur:
            row = conn.execute(
                """INSERT INTO items (market_hash_name, item_type) VALUES (%s, 'case')
                   ON CONFLICT (market_hash_name) DO UPDATE SET item_type = 'case' RETURNING id""",
                (name,)).fetchone()
            assert row is not None
            item_id = row["id"]
            sales, ev = [], []
            for i, p in enumerate(daily):
                day = today - (days - 1 - i) * DAY
                volume = int(rng.lognormvariate(math.log(4000 / math.sqrt(p)), 0.4))
                ev.append((item_id, _ts(day).date(), round(p / ratio[i] * 100), 1.0))
                if day < today - 30 * DAY:
                    sales.append((item_id, _ts(day + H), round(p * 100), volume, DAY))
                else:
                    for h in range(24):
                        q = p * math.exp(rng.gauss(0, 0.01))
                        sales.append((item_id, _ts(day + h * H), round(q * 100), max(1, volume // 24), H))
            cur.executemany(
                """INSERT INTO sales_history (item_id, ts, median_cents, volume, currency, span_secs)
                   VALUES (%s, %s, %s, %s, 'USD', %s) ON CONFLICT DO NOTHING""", sales)
            cur.executemany("INSERT INTO case_ev VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", ev)
            # Two days of minute snapshots of the lowest sell price, slightly below the sales median.
            p, ticks = daily[-2], []
            for t in range(now - 2 * DAY, now + 1, 60):
                p *= math.exp(rng.gauss(0, 0.0015) + (daily[-1] / p - 1) * 0.002)
                ticks.append((item_id, _ts(t), round(p * 97), int(rng.uniform(20000, 120000) / p)))
            cur.executemany(
                """INSERT INTO price_ticks (item_id, ts, price_cents, listings)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""", ticks)
        log.info("demo data: %s, %d days of sales, %d snapshots", name, days, len(ticks))


def _ts(t: int) -> datetime:
    return datetime.fromtimestamp(t, UTC)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    seed(force="--force" in sys.argv)
