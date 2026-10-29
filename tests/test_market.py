import math
import random

import pytest

from common import market
from common.market import DAY, SEASON_DAYS, SMOOTH_DAYS, market_index, smoothed


@pytest.fixture
def no_season(monkeypatch):
    monkeypatch.setattr(market, "SEASON_DAYS", 0)


def test_index_starts_at_100_and_follows_equal_weight_log_returns(no_season):
    # constant prices fill the smoothing window, then one case doubles and the other halves for good
    days = {d * DAY: {1: 1.0, 2: 4.0} for d in range(SMOOTH_DAYS)}
    days.update({d * DAY: {1: 2.0, 2: 2.0} for d in range(SMOOTH_DAYS, 3 * SMOOTH_DAYS)})
    out = market_index(days)
    assert out[0] == {"time": 0, "value": 100.0, "cases": 2, "turnover": 0.0}
    assert out[-1]["value"] == pytest.approx(100.0)        # +log2 and -log2 cancel out


def test_lasting_move_is_followed(no_season):
    days = {d * DAY: {1: 1.0 if d < 10 else 1.5} for d in range(30)}
    assert market_index(days)[-1]["value"] == pytest.approx(150.0)


def test_one_day_spike_is_ignored(no_season):
    days = {d * DAY: {1: 1.0, 2: 1.0} for d in range(20)}
    days[10 * DAY] = {1: 30.0, 2: 1.0}
    assert {p["value"] for p in market_index(days)} == {100.0}


def test_new_case_does_not_shift_index(no_season):
    days = {0: {1: 1.0}, DAY: {1: 1.0, 2: 50.0}, 2 * DAY: {1: 1.0, 2: 50.0}}
    assert [p["value"] for p in market_index(days)] == [100.0, 100.0, 100.0]


def test_smoothing_drops_highest_and_lowest_day():
    s = smoothed({0: {1: 1.0}, DAY: {1: 9.0}, 2 * DAY: {1: 3.0}, 3 * DAY: {1: 100.0}})
    assert s[DAY][1] == pytest.approx(3.0)                  # two days: geometric mean
    assert s[2 * DAY][1] == pytest.approx(3.0)              # 1, 3, 9 -> 3
    assert s[3 * DAY][1] == pytest.approx(math.sqrt(27))    # 1, 3, 9, 100 -> mean of logs of 3 and 9


def test_release_crash_is_left_out():
    # A case released at $3 falls to $0.05 over its first months, then stays flat: the index stays flat too.
    days = {}
    for d in range(SEASON_DAYS + 100):
        days[d * DAY] = {1: max(0.05, 3.0 * math.exp(-d / 20))}
    out = market_index(days)
    assert out[0]["time"] == SEASON_DAYS * DAY
    assert {p["value"] for p in out} == {100.0}


def test_turnover_is_passed_through(no_season):
    out = market_index({0: {1: 1.0}, DAY: {1: 1.0}}, {0: 12.5})
    assert [p["turnover"] for p in out] == [12.5, 0.0]


def test_noisy_history_does_not_drift_to_zero(no_season):
    # Regression: clipped daily changes turned frequent one-day outliers into a steady fall towards zero.
    rng = random.Random(1)
    days: dict[int, dict[int, float]] = {}
    for case in range(20):
        for d in range(2000):
            price = 1.0 * (rng.choice([3, 0.3]) if rng.random() < 0.02 else math.exp(rng.gauss(0, 0.01)))
            days.setdefault(d * DAY, {})[case] = price
    values = [p["value"] for p in market_index(days)]
    assert min(values) > 90 and max(values) < 110
