"""Cloud-side buffer (SQLite). Keeps snapshots until the home machine pulls them.

Every row gets an increasing id. Home pulls rows with id > its cursor and acknowledges
(ack) the last id it stored. Acknowledged rows are deleted after RETENTION_HOURS (a safety
margin in case home loses data); unacknowledged rows are kept for up to MAX_DAYS.
"""
import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from common.models import Item, PriceTick, SalePoint

# Sales history format version: when it changes, the cloud re-sends the whole history to home once.
SALES_RESEND = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    market_hash_name TEXT PRIMARY KEY,
    item_type        TEXT NOT NULL,
    icon_url         TEXT
);
CREATE TABLE IF NOT EXISTS ticks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    ts               INTEGER NOT NULL,
    price_cents      INTEGER NOT NULL,
    currency         TEXT    NOT NULL,
    listings         INTEGER,
    UNIQUE (market_hash_name, source, ts)
);
CREATE TABLE IF NOT EXISTS sales (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    ts               INTEGER NOT NULL,
    median_cents     INTEGER,
    volume           INTEGER NOT NULL,
    currency         TEXT    NOT NULL,
    UNIQUE (market_hash_name, source, ts)
);
-- Last known sales-history point per item, so we do not send the whole history home
-- every hour. Separate from sales because sales is pruned after acknowledgement.
CREATE TABLE IF NOT EXISTS sales_seen (
    market_hash_name TEXT PRIMARY KEY,
    last_ts          INTEGER NOT NULL
);
-- Daily prices of items inside cases (skins, knives, gloves): median and volume per day.
-- Home uses them to compute case EV. Pruned after acknowledgement, like sales.
CREATE TABLE IF NOT EXISTS item_days (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT    NOT NULL,
    day              INTEGER NOT NULL,
    median_cents     INTEGER NOT NULL,
    volume           INTEGER NOT NULL,
    UNIQUE (market_hash_name, day)
);
-- When an item was last fetched and up to which day its history has been sent home.
CREATE TABLE IF NOT EXISTS item_seen (
    market_hash_name TEXT PRIMARY KEY,
    last_day         INTEGER NOT NULL,
    fetched_at       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, ok INTEGER NOT NULL,
    items INTEGER NOT NULL DEFAULT 0, error TEXT
);
"""


class Buffer:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        if "span" not in {r[1] for r in self.conn.execute("PRAGMA table_info(sales)")}:
            self.conn.execute("ALTER TABLE sales ADD COLUMN span INTEGER NOT NULL DEFAULT 3600")
        self.lock = threading.Lock()

    def save(self, ticks: list[PriceTick], items: Sequence[Item]) -> int:
        with self.lock, self.conn:
            self.conn.executemany(
                """INSERT INTO items VALUES (?, ?, ?) ON CONFLICT(market_hash_name) DO UPDATE
                   SET icon_url = COALESCE(excluded.icon_url, items.icon_url)""",
                [(i.market_hash_name, i.item_type, i.icon_url) for i in items])
            cur = self.conn.executemany(
                """INSERT OR IGNORE INTO ticks (market_hash_name, source, ts, price_cents, currency, listings)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(t.market_hash_name, t.source, t.ts, t.price_cents, t.currency, t.listings) for t in ticks])
            return cur.rowcount

    def case_names(self) -> list[str]:
        with self.lock:
            return [r[0] for r in self.conn.execute(
                "SELECT market_hash_name FROM items WHERE item_type = 'case' ORDER BY market_hash_name")]

    def cases_by_liquidity(self) -> list[str]:
        """Cases ordered by number of market listings in the latest snapshot, most listed first."""
        with self.lock:
            return [r[0] for r in self.conn.execute(
                """SELECT i.market_hash_name FROM items i
                   LEFT JOIN ticks t ON t.id = (SELECT MAX(id) FROM ticks WHERE market_hash_name = i.market_hash_name)
                   WHERE i.item_type = 'case' ORDER BY COALESCE(t.listings, 0) DESC, i.market_hash_name""")]

    def save_sales(self, name: str, points: list[SalePoint], revise_hours: int = 3) -> int:
        """Stores new sales-history points. Steam keeps updating the last revise_hours hours (the current
        hour is still growing), so those are rewritten with a new id and home pulls them again."""
        with self.lock, self.conn:
            # Re-send the full history of every case once per format version:
            # 1 - prices in USD (USD wallet account), 2 - points marked as hourly or daily.
            # Home merges new points with the ones it already has.
            if any(p.median_cents is not None for p in points) and self._state("sales_resend") != SALES_RESEND:
                self.conn.execute("DELETE FROM sales_seen")
                self.conn.execute("INSERT OR REPLACE INTO state VALUES ('sales_resend', ?)", (SALES_RESEND,))
            row = self.conn.execute("SELECT last_ts FROM sales_seen WHERE market_hash_name = ?", (name,)).fetchone()
            since = row[0] - revise_hours * 3600 if row else -1
            fresh = [p for p in points if p.ts >= since]
            for p in fresh:
                self.conn.execute("DELETE FROM sales WHERE market_hash_name=? AND source=? AND ts=?",
                                  (p.market_hash_name, p.source, p.ts))
            self.conn.executemany(
                """INSERT INTO sales (market_hash_name, source, ts, median_cents, volume, currency, span)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(p.market_hash_name, p.source, p.ts, p.median_cents, p.volume, p.currency, p.span) for p in fresh])
            if points:
                self.conn.execute("INSERT OR REPLACE INTO sales_seen VALUES (?, ?)", (name, max(p.ts for p in points)))
            return len(fresh)

    def save_item_days(self, name: str, days: list[tuple[int, int, int]], revise_days: int = 2) -> int:
        """Daily points of an item [(day, median, volume)]. The last revise_days days are still changing,
        so they are rewritten with a new id; older days were already sent home and are not re-sent."""
        now = int(time.time())
        with self.lock, self.conn:
            row = self.conn.execute("SELECT last_day FROM item_seen WHERE market_hash_name = ?", (name,)).fetchone()
            since = row[0] - revise_days * 86400 if row else -1
            fresh = [d for d in days if d[0] >= since]
            self.conn.executemany("DELETE FROM item_days WHERE market_hash_name = ? AND day = ?",
                                  [(name, d[0]) for d in fresh])
            self.conn.executemany(
                "INSERT INTO item_days (market_hash_name, day, median_cents, volume) VALUES (?, ?, ?, ?)",
                [(name, *d) for d in fresh])
            last = max([d[0] for d in days] + [row[0] if row else 0])
            self.conn.execute("INSERT OR REPLACE INTO item_seen VALUES (?, ?, ?)", (name, last, now))
            return len(fresh)

    def items_to_fetch(self, names: list[str], limit: int) -> list[str]:
        """Never-fetched items first (in the order of names, i.e. case by case), then the ones
        fetched longest ago. The sort is stable, so the order of names is preserved."""
        with self.lock:
            seen = dict(self.conn.execute("SELECT market_hash_name, fetched_at FROM item_seen").fetchall())
        return sorted(names, key=lambda n: seen.get(n, 0))[:limit]

    def read_item_days(self, after_id: int, limit: int) -> dict:
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM item_days WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit))]
            max_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM item_days").fetchone()[0]
        return {"items": rows, "max_id": max_id, "has_more": bool(rows) and rows[-1]["id"] < max_id}

    def log_fetch(self, ts: int, ok: bool, items: int = 0, error: str | None = None):
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO fetch_log (ts, ok, items, error) VALUES (?,?,?,?)",
                              (ts, int(ok), items, error))
            self.conn.execute("DELETE FROM fetch_log WHERE ts < ?", (ts - 7 * 86400,))

    def read_sales(self, after_id: int, limit: int) -> dict:
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM sales WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit))]
            max_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM sales").fetchone()[0]
        return {"sales": rows, "max_id": max_id, "has_more": bool(rows) and rows[-1]["id"] < max_id}

    def read(self, after_id: int, limit: int) -> dict:
        with self.lock:
            ticks = [dict(r) for r in self.conn.execute(
                "SELECT * FROM ticks WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit))]
            names = sorted({t["market_hash_name"] for t in ticks})
            marks = ",".join("?" * len(names))
            items = [dict(r) for r in self.conn.execute(
                f"SELECT * FROM items WHERE market_hash_name IN ({marks})", names)] if names else []
            max_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM ticks").fetchone()[0]
        return {"ticks": ticks, "items": items, "max_id": max_id,
                "has_more": bool(ticks) and ticks[-1]["id"] < max_id}

    def ack(self, up_to_id: int, key: str = "acked_id"):
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO state VALUES (?, ?) ON CONFLICT(key) DO UPDATE
                   SET value = MAX(CAST(state.value AS INTEGER), CAST(excluded.value AS INTEGER))""",
                (key, str(up_to_id)))
            self.conn.execute("INSERT OR REPLACE INTO state VALUES ('acked_at', ?)", (str(int(time.time())),))

    def prune(self, retention_hours: int, max_days: int) -> int:
        now = int(time.time())
        with self.lock, self.conn:
            acked = int(self._state("acked_id") or 0)
            n = self.conn.execute("DELETE FROM ticks WHERE id <= ? AND ts < ?",
                                  (acked, now - retention_hours * 3600)).rowcount
            n += self.conn.execute("DELETE FROM ticks WHERE ts < ?", (now - max_days * 86400,)).rowcount
            # Sales history (it spans years) is pruned by arrival time, not by the point timestamp.
            sacked = int(self._state("sales_acked_id") or 0)
            n += self.conn.execute("DELETE FROM sales WHERE id <= ?", (sacked,)).rowcount
            iacked = int(self._state("items_acked_id") or 0)
            n += self.conn.execute("DELETE FROM item_days WHERE id <= ?", (iacked,)).rowcount
        return n

    def _state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def stats(self) -> dict:
        with self.lock:
            acked = int(self._state("acked_id") or 0)
            last_ok = self.conn.execute("SELECT MAX(ts) FROM fetch_log WHERE ok = 1").fetchone()[0]
            last = self.conn.execute("SELECT ts, ok, items, error FROM fetch_log ORDER BY id DESC LIMIT 1").fetchone()
            day = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(ok), 0) FROM fetch_log WHERE ts >= ?",
                                    (int(time.time()) - 86400,)).fetchone()
            return {
                "buffered_ticks": self.conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0],
                "pending_ticks": self.conn.execute("SELECT COUNT(*) FROM ticks WHERE id > ?", (acked,)).fetchone()[0],
                "acked_id": acked,
                "last_ack_at": int(self._state("acked_at") or 0) or None,
                "last_success_at": last_ok,
                "last_fetch": dict(last) if last else None,
                "fetches_24h": day[0], "successful_24h": day[1],
                "pending_sales": self.conn.execute("SELECT COUNT(*) FROM sales WHERE id > ?",
                                                   (int(self._state("sales_acked_id") or 0),)).fetchone()[0],
                "history_last_ok_at": int(self._state("history_ok_at") or 0) or None,
                "history_last_error": self._state("history_error"),
                "login_expires_at": int(self._state("login_expires_at") or 0) or None,
                "pending_item_days": self.conn.execute("SELECT COUNT(*) FROM item_days WHERE id > ?",
                                                       (int(self._state("items_acked_id") or 0),)).fetchone()[0],
                "items_fetched": self.conn.execute("SELECT COUNT(*) FROM item_seen").fetchone()[0],
                "items_total": int(self._state("items_total") or 0),
            }

    def get_state(self, key: str) -> str | None:
        with self.lock:
            return self._state(key)

    def set_state(self, key: str, value: str | None):
        with self.lock, self.conn:
            if value is None:
                self.conn.execute("DELETE FROM state WHERE key = ?", (key,))
            else:
                self.conn.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, value))
