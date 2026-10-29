import math
import random

import pytest

from common import backtest as bt


def series(prices, start=1000, volume=100.0):
    return [(start + i, p, volume) for i, p in enumerate(prices)]


def data_from(daily, left=None):
    return bt.prepare(bt.build_cases(daily, left=left))


def test_build_cases_carries_price_over_days_without_sales():
    (c,) = bt.build_cases({"A": [(10, 1.0, 5), (13, 2.0, 7)]})
    assert c.price == [1.0, 1.0, 1.0, 2.0]
    assert c.volume == [5, 0.0, 0.0, 7]


@pytest.mark.parametrize("price, paid", [(0.02, 0.0), (0.03, 0.01), (0.10, 0.08), (1.00, 0.88), (1.15, 1.00),
                                         (2.00, 1.75), (10.00, 8.70)])
def test_proceeds_follow_the_steam_fee_with_its_one_cent_minimum(price, paid):
    assert bt.proceeds(price) == pytest.approx(paid)


def test_fitness_counts_quarters_not_trades():
    base = bt.Result([("X", 0, 100, 1.0)])
    one_event = bt.Result([(f"C{k}", 1000 + k, 1100, 2.0) for k in range(40)])
    assert bt.fitness(one_event, base) == -1e9
    spread = bt.Result([(f"C{k % 5}", 1000 + 91 * k, 1100 + 91 * k, 1.5 + 0.1 * (k % 2)) for k in range(8)])
    assert bt.fitness(spread, base) > 3


def test_trade_buys_next_day_and_pays_the_fee():
    prices = [1.0] * 10 + [2.0] * 200
    d = data_from({"A": series(prices)})
    res = bt.run(d, bt.Rule({}, 30), 1000, 1000)
    (name, entry, exit_, net) = res.trades[0]
    assert (name, entry, exit_) == ("A", 1001, 1031)
    assert net == pytest.approx(1.75)


def test_positions_do_not_overlap_but_baseline_does():
    d = data_from({"A": series([1.0] * 400)})
    rule = bt.run(d, bt.Rule({}, 100), 1000, 1400)
    assert [t[1] for t in rule.trades] == [1001, 1102, 1203]   # next signal checked on the sell day
    base = bt.baseline(d, 100, 1000, 1400)
    assert [t[1] for t in base.trades][:3] == [1001, 1008, 1015]
    assert all(t[3] == pytest.approx(0.88) for t in base.trades)


def test_exit_by_keeps_training_trades_out_of_the_test_period():
    d = data_from({"A": series([1.0] * 400)})
    assert all(t[2] <= 1150 for t in bt.run(d, bt.Rule({}, 50), 1000, 1400, exit_by=1150).trades)


def test_conditions_filter_entries():
    # price falls 50% and then recovers: only the drawdown entries pass case_dd <= -0.3
    prices = [1.0] * 100 + [0.5] * 100 + [1.0] * 300
    d = data_from({"A": series(prices)})
    res = bt.run(d, bt.Rule({"case_dd": ("<=", -0.3)}, 60), 1000, 1500)
    assert res.trades and all(1100 <= t[1] <= 1210 for t in res.trades)


def test_features_do_not_look_ahead():
    rng = random.Random(3)
    prices = [math.exp(rng.gauss(0, 0.1)) for _ in range(500)]
    a = data_from({"A": series(prices), "B": series(prices[::-1])})
    changed = prices[:300] + [p * 10 for p in prices[300:]]
    b = data_from({"A": series(changed), "B": series(prices[::-1])})
    for feat in bt.FEATURES:
        for x, y in zip(a.feats[feat][0][:300], b.feats[feat][0][:300], strict=True):
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y), feat


def test_days_since_left_pool():
    d = data_from({"A": series([1.0] * 50)}, left={"A": 1020})
    f = d.feats["days_since_left_pool"][0]
    assert math.isnan(f[19]) and f[20] == 0 and f[30] == 10


def test_drop_pool_event():
    prices = [1.0] * 21 + [2.0] * 400
    d = data_from({"A": series(prices)}, left={"A": 1020})
    (row,) = bt.drop_pool_event(d, [180, 1000])
    assert row["price"] == 2.0 and row[180] == pytest.approx(0.875 - 1) and row[1000] is None


def test_forward_returns_groups_by_feature():
    d = data_from({"A": series([1.0] * 100 + [2.0] * 600)})
    rows = bt.forward_returns(d, "age_days", [50.0], 365, 1000, 1700)
    assert [r["entries"] for r in rows] == [8, len(range(56, 700 - 366, 7))]
    assert rows[0]["mean_return"] == pytest.approx(1.75 - 1)


def test_evolve_finds_a_planted_signal_and_is_deterministic():
    # Cases jump +50% two months after every 30% drawdown; otherwise flat.
    rng = random.Random(0)
    daily = {}
    for c in range(8):
        p, prices = 1.0, []
        for d in range(2700):
            if d % 200 == 50 + c:
                p *= 0.6
            if d % 200 == 110 + c:
                p *= 2.5
            prices.append(p * math.exp(rng.gauss(0, 0.01)))
        daily[f"C{c}"] = series(prices)
    d = data_from(daily)
    best = bt.evolve(d, 1000, 3200, pop=30, gens=15, seed=2)
    again = bt.evolve(d, 1000, 3200, pop=30, gens=15, seed=2)
    assert [r.describe() for _, r in best] == [r.describe() for _, r in again]
    top = best[0][1]
    res = bt.run(d, top, 1000, 3200, 3200).summary()
    base = bt.baseline(d, top.hold, 1000, 3200, 3200).summary()
    assert res["mean_return"] > base["mean_return"] + 0.2
