import pytest

from common.market import market_index

D = 86400


def test_index_starts_at_100_and_follows_equal_weight_log_returns():
    out = market_index({0: {1: 1.0, 2: 2.0}, D: {1: 1.25, 2: 1.6}})
    assert out[0] == {"time": 0, "value": 100.0, "cases": 2}
    # +log(1.25) and log(0.8) cancel out
    assert out[1]["value"] == pytest.approx(100.0)


def test_new_case_does_not_shift_index():
    out = market_index({0: {1: 1.0}, D: {1: 1.0, 2: 50.0}, 2 * D: {1: 1.0, 2: 50.0}})
    assert [p["value"] for p in out] == [100.0, 100.0, 100.0]


def test_case_with_gap_compares_to_its_last_price():
    out = market_index({0: {1: 1.0}, D: {2: 3.0}, 2 * D: {1: 1.1}})
    assert out[2]["value"] == pytest.approx(110.0)


def test_single_day_moves_are_clipped():
    out = market_index({0: {1: 1.0}, D: {1: 100.0}})
    assert out[1]["value"] == pytest.approx(100 * 2.718281828 ** 0.4, abs=1e-3)
