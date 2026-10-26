"""Домашний backend: синхронизация с облаком в фоне + API для графиков.

  /api/items     все кейсы с последней ценой и изменением за 24 ч
  /api/candles   OHLC-свечи для TradingView Lightweight Charts
  /api/news      новости Valve, связанные с кейсом
  /udf/*         UDF-датафид для полной библиотеки TradingView Charting Library

Запуск: python -m home
"""
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import news, sync
from .db import ensure_database, open_pool, pool

RESOLUTIONS = {"1": 60, "5": 300, "15": 900, "60": 3600, "240": 14400, "1D": 86400, "D": 86400}


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_database()
    open_pool()
    stop = threading.Event()
    t = threading.Thread(target=sync.run_forever, args=(stop,), daemon=True, name="sync")
    t.start()
    threading.Thread(target=news.run_forever, args=(stop,), daemon=True, name="news").start()
    yield
    stop.set()
    pool.close()


app = FastAPI(title="CS2 case prices (home)", lifespan=lifespan)
# Фронт (React) будет отдельным dev-сервером, поэтому разрешаем запросы с других портов.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def q(sql: str, args=()):
    with pool.connection() as conn:
        return conn.execute(sql, args).fetchall()


def candles(item_id: int, tf: int, start: int, end: int, source: str = "steam") -> list[dict]:
    """Свечи из минутных снимков минимальной цены продажи: open/close — первый/последний снимок.
    volume — настоящие продажи из истории Steam (есть только с шагом от часа, на меньших
    таймфреймах 0), listings — среднее число лотов на продаже."""
    rows = q(
        """SELECT extract(epoch FROM date_bin(make_interval(secs => %(tf)s), ts, 'epoch'))::bigint AS time,
                  (array_agg(price_cents ORDER BY ts))[1]      AS o,
                  max(price_cents)                             AS h,
                  min(price_cents)                             AS l,
                  (array_agg(price_cents ORDER BY ts DESC))[1] AS c,
                  round(avg(listings))::int                    AS v
           FROM price_ticks
           WHERE item_id = %(id)s AND source = %(src)s
             AND ts >= to_timestamp(%(start)s) AND ts < to_timestamp(%(end)s)
           GROUP BY 1 ORDER BY 1""",
        {"tf": tf, "id": item_id, "src": source, "start": start, "end": end})
    vol = {}
    if tf >= 3600:
        vol = {r["time"]: r["volume"] for r in sales(item_id, tf, start, end, source)}
    return [{"time": r["time"], "open": r["o"] / 100, "high": r["h"] / 100, "low": r["l"] / 100,
             "close": r["c"] / 100, "volume": vol.get(r["time"], 0), "listings": r["v"] or 0} for r in rows]


def sales(item_id: int, tf: int, start: int, end: int, source: str = "steam") -> list[dict]:
    """История продаж, сгруппированная по tf (не мельче часа): медиана, взвешенная по объёму, и сумма продаж."""
    tf = max(tf, 3600)
    rows = q(
        """SELECT extract(epoch FROM date_bin(make_interval(secs => %(tf)s), ts, 'epoch'))::bigint AS time,
                  sum(median_cents::bigint * volume) / NULLIF(sum(volume) FILTER (WHERE median_cents IS NOT NULL), 0) AS median,
                  avg(median_cents) AS median_plain,
                  sum(volume) AS volume, max(currency) AS currency
           FROM sales_history
           WHERE item_id = %(id)s AND source = %(src)s
             AND ts >= to_timestamp(%(start)s) AND ts < to_timestamp(%(end)s)
           GROUP BY 1 ORDER BY 1""",
        {"tf": tf, "id": item_id, "src": source, "start": start, "end": end})
    out = []
    for r in rows:
        m = r["median"] if r["median"] is not None else r["median_plain"]
        out.append({"time": r["time"], "median": round(float(m)) / 100 if m is not None else None,
                    "volume": int(r["volume"]), "currency": "USD"})
    return out


@app.get("/api/items")
def items():
    return q("""
        SELECT i.id, i.market_hash_name, i.item_type, i.icon_url,
               last.price_cents / 100.0 AS price, last.listings, extract(epoch FROM last.ts)::bigint AS ts,
               day.price_cents / 100.0  AS price_24h
        FROM items i
        CROSS JOIN LATERAL (SELECT price_cents, listings, ts FROM price_ticks p
                            WHERE p.item_id = i.id AND p.source = 'steam' ORDER BY ts DESC LIMIT 1) last
        LEFT JOIN LATERAL (SELECT price_cents FROM price_ticks p
                           WHERE p.item_id = i.id AND p.source = 'steam' AND p.ts >= now() - interval '24 hours'
                           ORDER BY ts LIMIT 1) day ON true
        ORDER BY i.market_hash_name""")


@app.get("/api/candles")
def api_candles(item_id: int, tf: str = Query("60", description="1, 5, 15, 60, 240 (минуты) или 1D"),
                start: int | None = None, end: int | None = None):
    if tf not in RESOLUTIONS:
        raise HTTPException(400, f"tf должен быть одним из {list(RESOLUTIONS)}")
    end = end or int(time.time()) + 60
    start = start or end - 2000 * RESOLUTIONS[tf]
    return candles(item_id, RESOLUTIONS[tf], start, end)


@app.get("/api/sales")
def api_sales(item_id: int, tf: str = Query("60", description="60, 240 (минуты) или 1D; мельче часа не бывает"),
              start: int = 0, end: int | None = None):
    if tf not in RESOLUTIONS:
        raise HTTPException(400, f"tf должен быть одним из {list(RESOLUTIONS)}")
    return sales(item_id, RESOLUTIONS[tf], start, end or int(time.time()) + 3600)


@app.get("/api/news")
def api_news(item_id: int | None = None, limit: int = 200):
    """Новости Valve: для кейса — где он упомянут, без item_id — все подряд. Новые сверху."""
    where, args = "", {"limit": limit}
    if item_id is not None:
        where, args["id"] = "WHERE n.gid IN (SELECT gid FROM item_news WHERE item_id = %(id)s)", item_id
    return q(f"""SELECT n.gid, extract(epoch FROM n.ts)::bigint AS ts, n.title, n.url, n.contents
                 FROM news n {where} ORDER BY n.ts DESC LIMIT %(limit)s""", args)


@app.get("/api/status")
def status():
    row = q("""SELECT count(*) AS ticks, extract(epoch FROM max(ts))::bigint AS last_ts,
                      (SELECT value FROM sync_state WHERE key = 'cloud_cursor') AS cursor,
                      (SELECT count(*) FROM sales_history) AS sales_points,
                      (SELECT extract(epoch FROM max(ts))::bigint FROM sales_history) AS sales_last_ts
               FROM price_ticks""")[0]
    return row


# ---------- TradingView UDF ----------

def _find_item(symbol: str) -> dict:
    sym = symbol.split(":")[-1]
    rows = q("SELECT * FROM items WHERE id::text = %s OR market_hash_name = %s", (sym, sym))
    if not rows:
        raise HTTPException(404, "unknown symbol")
    return rows[0]


@app.get("/udf/config")
def udf_config():
    return {"supported_resolutions": ["1", "5", "15", "60", "240", "1D"], "supports_search": True,
            "supports_group_request": False, "supports_marks": False, "supports_time": True,
            "exchanges": [{"value": "STEAM", "name": "Steam Market", "desc": "Steam Community Market"}],
            "symbols_types": [{"name": "case", "value": "case"}]}


@app.get("/udf/time")
def udf_time():
    return int(time.time())


def _symbol_info(it: dict) -> dict:
    return {"name": it["market_hash_name"], "ticker": f"STEAM:{it['id']}", "description": it["market_hash_name"],
            "type": it["item_type"], "exchange": "STEAM", "listed_exchange": "STEAM", "session": "24x7",
            "timezone": "Etc/UTC", "minmov": 1, "pricescale": 100, "has_intraday": True, "has_daily": True,
            "supported_resolutions": ["1", "5", "15", "60", "240", "1D"], "volume_precision": 0,
            "data_status": "streaming", "currency_code": "USD"}


@app.get("/udf/symbols")
def udf_symbols(symbol: str):
    return _symbol_info(_find_item(symbol))


@app.get("/udf/search")
def udf_search(query: str = "", limit: int = 30):
    rows = q("SELECT * FROM items WHERE market_hash_name ILIKE %s ORDER BY market_hash_name LIMIT %s",
             (f"%{query}%", limit))
    return [{"symbol": r["market_hash_name"], "full_name": f"STEAM:{r['id']}", "description": r["market_hash_name"],
             "exchange": "STEAM", "ticker": f"STEAM:{r['id']}", "type": r["item_type"]} for r in rows]


@app.get("/udf/history")
def udf_history(symbol: str, resolution: str, to: int, from_: int = Query(..., alias="from"),
                countback: int | None = None):
    it = _find_item(symbol)
    tf = RESOLUTIONS.get(resolution)
    if not tf:
        raise HTTPException(400, "unsupported resolution")
    start = min(from_, to - countback * tf) if countback else from_
    bars = candles(it["id"], tf, start, to)
    if not bars:
        prev = q("""SELECT extract(epoch FROM max(ts))::bigint AS t FROM price_ticks
                    WHERE item_id = %s AND ts < to_timestamp(%s)""", (it["id"], start))[0]["t"]
        return {"s": "no_data", "nextTime": prev} if prev else {"s": "no_data"}
    return {"s": "ok", "t": [b["time"] for b in bars], "o": [b["open"] for b in bars],
            "h": [b["high"] for b in bars], "l": [b["low"] for b in bars],
            "c": [b["close"] for b in bars], "v": [b["volume"] for b in bars]}


# Временная страница для проверки графиков, пока нет React-фронта.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
