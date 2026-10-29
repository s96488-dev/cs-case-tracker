"""End to end: cloud buffer -> pull API -> home sync -> PostgreSQL -> chart API.

Needs a disposable PostgreSQL database in TEST_DATABASE_URL (CI starts one); skipped otherwise.
"""
import os

import pytest
from fastapi.testclient import TestClient

if not os.getenv("TEST_DATABASE_URL"):
    pytest.skip("TEST_DATABASE_URL is not set", allow_module_level=True)

from cloud import config as cloud_config  # noqa: E402
from cloud import server  # noqa: E402
from cloud.buffer import Buffer  # noqa: E402
from common.models import Case, PriceTick, SalePoint  # noqa: E402
from home import api, ev, sync  # noqa: E402
from home import config as home_config  # noqa: E402
from home.db import ensure_database, open_pool, pool  # noqa: E402

DAY, H = 86400, 3600
T0 = 1_790_000_000 // DAY * DAY   # a UTC midnight


@pytest.fixture(scope="module", autouse=True)
def database():
    ensure_database()
    open_pool()
    yield
    pool.close()


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    with pool.connection() as conn:
        conn.execute("TRUNCATE items, price_ticks, sales_history, sync_state, item_days, case_ev, "
                     "item_news, news RESTART IDENTITY CASCADE")
    monkeypatch.setattr(cloud_config, "API_TOKEN", "secret")
    monkeypatch.setattr(server, "buf", Buffer(tmp_path / "buffer.db"))
    monkeypatch.setattr(home_config, "CLOUD_URL", "http://testserver")
    monkeypatch.setattr(home_config, "SYNC_BATCH", 3)    # force several pages
    api._market_cache.update(at=0.0, data=[])
    return TestClient(server.app, headers={"Authorization": "Bearer secret"})


@pytest.fixture
def home():
    return TestClient(api.app)


def one(sql, args=()):
    with pool.connection() as conn:
        return conn.execute(sql, args).fetchone()


def test_ticks_sync_in_pages_and_build_candles(cloud, home):
    # 10 minute snapshots of one case: prices 100..109
    server.buf.save([PriceTick("A Case", T0 + 60 * i, 100 + i, 50 - i) for i in range(10)], [Case("A Case")])
    assert sync.sync_once(cloud) == 10
    assert one("SELECT count(*) AS n FROM price_ticks")["n"] == 10
    assert one("SELECT value FROM sync_state WHERE key = 'cloud_cursor'")["value"] == 10
    assert server.buf.stats()["pending_ticks"] == 0          # home acknowledged everything
    assert sync.sync_once(cloud) == 0                         # nothing new

    item_id = home.get("/api/items").json()[0]["id"]
    c = home.get("/api/candles", params={"item_id": item_id, "tf": "5", "start": T0, "end": T0 + DAY}).json()
    assert [(x["open"], x["high"], x["low"], x["close"]) for x in c] == [(1.0, 1.04, 1.0, 1.04),
                                                                        (1.05, 1.09, 1.05, 1.09)]
    assert home.get("/api/candles", params={"item_id": item_id, "tf": "7"}).status_code == 400


def test_recreated_cloud_buffer_resets_cursor_without_duplicates(cloud, tmp_path, monkeypatch):
    server.buf.save([PriceTick("A Case", T0 + 60 * i, 100) for i in range(5)], [Case("A Case")])
    sync.sync_once(cloud)
    fresh = Buffer(tmp_path / "new.db")
    fresh.save([PriceTick("A Case", T0 + 60 * i, 100) for i in range(3, 7)], [Case("A Case")])
    monkeypatch.setattr(server, "buf", fresh)
    sync.sync_once(cloud)
    assert one("SELECT count(*) AS n FROM price_ticks")["n"] == 7
    assert one("SELECT value FROM sync_state WHERE key = 'cloud_cursor'")["value"] == 4


def test_daily_sales_point_replaces_hourly_points_of_that_day(cloud, home):
    server.buf.save([PriceTick("A Case", T0, 100)], [Case("A Case")])
    sync.sync_once(cloud)
    server.buf.save_sales("A Case", [SalePoint("A Case", T0 + h * H, 100, 2) for h in range(5)])
    assert sync.sync_sales_once(cloud) == 5
    # Later Steam folds that day into one daily point at 01:00
    server.buf.save_sales("A Case", [SalePoint("A Case", T0 + H, 110, 10, span=DAY)])
    sync.sync_sales_once(cloud)
    item_id = home.get("/api/items").json()[0]["id"]
    s = home.get("/api/sales", params={"item_id": item_id, "tf": "1D", "start": T0, "end": T0 + DAY}).json()
    assert s == [{"time": T0, "median": 1.1, "volume": 10, "currency": "USD", "daily": False}]


def test_item_prices_ev_and_market_index(cloud, home, monkeypatch):
    server.buf.save([PriceTick("A Case", T0, 100), PriceTick("B Case", T0, 200)], [Case("A Case"), Case("B Case")])
    sync.sync_once(cloud)
    for name, price in (("Skin 1", 300), ("Skin 2", 500)):
        server.buf.save_item_days(name, [(T0 + d * DAY, price, 20) for d in range(3)])
    assert sync.sync_items_once(cloud) == 6
    monkeypatch.setattr(ev.time, "time", lambda: T0 + 2 * DAY + 100)
    contents = {"A Case": {"Skin 1": 0.5, "Skin 2": 0.5}, "B Case": {"Skin 1": 0.5, "Missing": 0.5}}
    assert ev.compute_all(contents) == 1                     # B Case is only 50% covered
    ids = {i["market_hash_name"]: i["id"] for i in home.get("/api/items").json()}
    e = home.get("/api/ev", params={"item_id": ids["A Case"]}).json()
    assert [(x["time"], x["ev"], x["coverage"]) for x in e] == [(T0 + d * DAY, 4.0, 1.0) for d in range(3)]
    assert home.get("/api/ev", params={"item_id": ids["B Case"]}).json() == []

    for name, prices in (("A Case", [100, 110]), ("B Case", [200, 220])):
        server.buf.save_sales(name, [SalePoint(name, T0 + d * DAY + H, p, 5, span=DAY) for d, p in enumerate(prices)])
    sync.sync_sales_once(cloud)
    m = home.get("/api/market").json()
    # both cases +10%; with two days of history the smoothing median sits halfway
    assert [round(x["value"], 1) for x in m] == [100.0, 105.0]
    assert home.get("/api/drop", params={"item_id": ids["A Case"]}).json() is None
