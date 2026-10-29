import math
import random

import pytest

from common.market import SMOOTH_DAYS, market_index, smoothed

D = 86400


def test_index_starts_at_100_and_follows_equal_weight_log_returns():
    # constant prices fill the smoothing window, then one case doubles and the other halves for good
    days = {d * D: {1: 1.0, 2: 4.0} for d in range(SMOOTH_DAYS)}
    days.update({d * D: {1: 2.0, 2: 2.0} for d in range(SMOOTH_DAYS, 3 * SMOOTH_DAYS)})
    out = market_index(days)
    assert out[0] == {"time": 0, "value": 100.0, "cases": 2}
    assert out[-1]["value"] == pytest.approx(100.0)        # +log2 and -log2 cancel out


def test_lasting_move_is_followed():
    days = {d * D: {1: 1.0 if d < 10 else 1.5} for d in range(30)}
    assert market_index(days)[-1]["value"] == pytest.approx(150.0)


def test_one_day_spike_is_ignored():
    days = {d * D: {1: 1.0, 2: 1.0} for d in range(20)}
    days[10 * D] = {1: 30.0, 2: 1.0}
    assert {p["value"] for p in market_index(days)} == {100.0}


def test_new_case_does_not_shift_index():
    days = {0: {1: 1.0}, D: {1: 1.0, 2: 50.0}, 2 * D: {1: 1.0, 2: 50.0}}
    assert [p["value"] for p in market_index(days)] == [100.0, 100.0, 100.0]


def test_smoothing_is_a_trailing_median_per_case():
    s = smoothed({0: {1: 1.0}, D: {1: 9.0}, 2 * D: {1: 2.0, 2: 5.0}})
    assert s == {0: {1: 1.0}, D: {1: 5.0}, 2 * D: {1: 2.0, 2: 5.0}}


def test_noisy_history_does_not_drift_to_zero():
    # Regression: clipped daily changes turned frequent one-day outliers into a steady fall towards zero.
    rng = random.Random(1)
    days: dict[int, dict[int, float]] = {}
    for case in range(20):
        for d in range(2000):
            price = 1.0 * (rng.choice([3, 0.3]) if rng.random() < 0.02 else math.exp(rng.gauss(0, 0.01)))
            days.setdefault(d * D, {})[case] = price
    values = [p["value"] for p in market_index(days)]
    assert min(values) > 90 and max(values) < 110
