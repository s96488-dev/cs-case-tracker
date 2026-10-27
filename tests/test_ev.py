from common.ev import DAY, MIN_SALES, case_ev, daily_points, price_series, weighted_median
from common.models import SalePoint


def test_weighted_median():
    assert weighted_median([]) is None
    assert weighted_median([(100, 0), (None, 5)]) is None
    assert weighted_median([(100, 1), (200, 1), (300, 1)]) == 200
    # one heavy day dominates
    assert weighted_median([(100, 1), (200, 10), (300, 1)]) == 200
    assert weighted_median([(100, 9), (500, 1)]) == 100


def test_daily_points_groups_by_utc_day_and_skips_unpriced():
    pts = [SalePoint("x", 0 * DAY + 3600, 100, 3), SalePoint("x", 0 * DAY + 7200, 200, 1),
           SalePoint("x", 1 * DAY + 3600, None, 5), SalePoint("x", 2 * DAY, 300, 0),
           SalePoint("x", 3 * DAY + 60, 400, 2)]
    assert daily_points(pts) == [(0, 100, 4), (3 * DAY, 400, 2)]


def test_price_series_window_covers_min_sales():
    days = [(0, 100, MIN_SALES), (DAY, 300, 1), (2 * DAY, 300, MIN_SALES)]
    s = price_series(days, -DAY, 3 * DAY)
    assert -DAY not in s                 # no price before the first sale
    assert s[0] == 100
    assert s[DAY] == 100                 # a single sale barely moves the price
    assert s[2 * DAY] == 300             # the old day falls out once newer days cover MIN_SALES
    assert s[3 * DAY] == 300             # days without sales keep the last price


def test_case_ev_and_coverage():
    probs = {"a": 0.5, "b": 0.3, "c": 0.2}
    item_days = {"a": [(0, 100, 20)], "b": [(DAY, 1000, 20)]}   # "c" never sold
    assert case_ev(probs, item_days, 0, DAY) == [(0, 50, 0.5), (DAY, 350, 0.8)]
