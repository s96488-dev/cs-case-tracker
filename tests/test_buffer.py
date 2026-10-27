from cloud.buffer import Buffer
from common.models import Case, PriceTick, SalePoint


def make(tmp_path):
    return Buffer(tmp_path / "buffer.db")


def test_save_is_idempotent_and_read_pages(tmp_path):
    buf = make(tmp_path)
    ticks = [PriceTick("A Case", 60 * i, 100 + i, 5) for i in range(5)]
    assert buf.save(ticks, [Case("A Case")]) == 5
    assert buf.save(ticks, [Case("A Case")]) == 0          # same minute again: no duplicates
    page = buf.read(0, 2)
    assert [t["price_cents"] for t in page["ticks"]] == [100, 101]
    assert page["has_more"] and page["max_id"] == 5
    assert page["items"][0]["market_hash_name"] == "A Case"
    rest = buf.read(page["ticks"][-1]["id"], 10)
    assert len(rest["ticks"]) == 3 and not rest["has_more"]


def test_icon_is_not_overwritten_with_empty(tmp_path):
    buf = make(tmp_path)
    buf.save([], [Case("A Case", icon_url="http://icon")])
    buf.save([PriceTick("A Case", 0, 1)], [Case("A Case")])
    assert buf.read(0, 10)["items"][0]["icon_url"] == "http://icon"


def test_ack_never_moves_back_and_prune_keeps_unacked(tmp_path):
    buf = make(tmp_path)
    buf.save([PriceTick("A Case", 60 * i, 100) for i in range(4)], [Case("A Case")])
    buf.ack(3)
    buf.ack(1)
    assert buf.stats()["acked_id"] == 3
    assert buf.prune(retention_hours=0, max_days=10**6) == 3
    assert [t["id"] for t in buf.read(0, 10)["ticks"]] == [4]


def test_cases_by_liquidity_uses_latest_snapshot(tmp_path):
    buf = make(tmp_path)
    buf.save([PriceTick("A Case", 0, 1, 10), PriceTick("B Case", 0, 1, 5), PriceTick("C Case", 0, 1, 7)],
             [Case("A Case"), Case("B Case"), Case("C Case")])
    buf.save([PriceTick("A Case", 60, 1, 1)], [Case("A Case")])
    assert buf.cases_by_liquidity() == ["C Case", "B Case", "A Case"]


def test_save_sales_resends_only_recent_hours(tmp_path):
    buf = make(tmp_path)
    h = 3600
    pts = [SalePoint("A Case", i * h, 100, 1) for i in range(10)]
    assert buf.save_sales("A Case", pts) == 10
    pts.append(SalePoint("A Case", 10 * h, 100, 1))
    # the last 3 hours before the previous newest point are rewritten, plus the new one
    assert buf.save_sales("A Case", pts) == 5
    rows = buf.read_sales(0, 100)["sales"]
    assert sorted(r["ts"] for r in rows) == [i * h for i in range(11)]


def test_items_to_fetch_keeps_case_order(tmp_path):
    buf = make(tmp_path)
    buf.save_item_days("b", [(0, 100, 1)])
    assert buf.items_to_fetch(["c", "b", "a"], 10) == ["c", "a", "b"]
    assert buf.items_to_fetch(["c", "b", "a"], 1) == ["c"]
