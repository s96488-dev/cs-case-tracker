"""Буфер в облаке (SQLite). Хранит снимки, пока домашний компьютер их не заберёт.

Каждая запись получает возрастающий id. Дом забирает записи с id > своего курсора и
подтверждает (ack) последний сохранённый id. Подтверждённые записи удаляются через
RETENTION_HOURS (запас на случай сбоя дома), неподтверждённые хранятся до MAX_DAYS.
"""
import sqlite3
import threading
import time
from pathlib import Path

from common.models import Item, PriceTick

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
        self.lock = threading.Lock()

    def save(self, ticks: list[PriceTick], items: list[Item]) -> int:
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

    def log_fetch(self, ts: int, ok: bool, items: int = 0, error: str | None = None):
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO fetch_log (ts, ok, items, error) VALUES (?,?,?,?)",
                              (ts, int(ok), items, error))
            self.conn.execute("DELETE FROM fetch_log WHERE ts < ?", (ts - 7 * 86400,))

    def read(self, after_id: int, limit: int) -> dict:
        with self.lock:
            ticks = [dict(r) for r in self.conn.execute(
                "SELECT * FROM ticks WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit))]
            names = sorted({t["market_hash_name"] for t in ticks})
            items = [dict(r) for r in self.conn.execute(
                f"SELECT * FROM items WHERE market_hash_name IN ({','.join('?' * len(names))})", names)] if names else []
            max_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM ticks").fetchone()[0]
        return {"ticks": ticks, "items": items, "max_id": max_id,
                "has_more": bool(ticks) and ticks[-1]["id"] < max_id}

    def ack(self, up_to_id: int):
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO state VALUES ('acked_id', ?) ON CONFLICT(key) DO UPDATE
                   SET value = MAX(CAST(state.value AS INTEGER), CAST(excluded.value AS INTEGER))""",
                (str(up_to_id),))
            self.conn.execute("INSERT OR REPLACE INTO state VALUES ('acked_at', ?)", (str(int(time.time())),))

    def prune(self, retention_hours: int, max_days: int) -> int:
        now = int(time.time())
        with self.lock, self.conn:
            acked = int(self._state("acked_id") or 0)
            n = self.conn.execute("DELETE FROM ticks WHERE id <= ? AND ts < ?",
                                  (acked, now - retention_hours * 3600)).rowcount
            n += self.conn.execute("DELETE FROM ticks WHERE ts < ?", (now - max_days * 86400,)).rowcount
        return n

    def _state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def stats(self) -> dict:
        with self.lock:
            acked = int(self._state("acked_id") or 0)
            last_ok = self.conn.execute("SELECT MAX(ts) FROM fetch_log WHERE ok = 1").fetchone()[0]
            last = self.conn.execute("SELECT ts, ok, items, error FROM fetch_log ORDER BY id DESC LIMIT 1").fetchone()
            day = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(ok), 0) FROM fetch_log WHERE ts >= ?", (int(time.time()) - 86400,)).fetchone()
            return {
                "buffered_ticks": self.conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0],
                "pending_ticks": self.conn.execute("SELECT COUNT(*) FROM ticks WHERE id > ?", (acked,)).fetchone()[0],
                "acked_id": acked,
                "last_ack_at": int(self._state("acked_at") or 0) or None,
                "last_success_at": last_ok,
                "last_fetch": dict(last) if last else None,
                "fetches_24h": day[0], "successful_24h": day[1],
            }
