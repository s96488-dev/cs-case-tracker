from datetime import date, timedelta

from common import drop_pool


def test_mean_lifetime_uses_only_retired_cases():
    retired = [(date.fromisoformat(left) - date.fromisoformat(released)).days
               for released, left in drop_pool.CASES.values() if left]
    assert round(sum(retired) / len(retired)) == drop_pool.MEAN_DAYS


def test_info_for_active_case_has_forecast():
    i = drop_pool.info("Kilowatt Case")
    assert i["left_active"] is None
    assert i["forecast"] == (date(2024, 2, 6) + timedelta(days=drop_pool.MEAN_DAYS)).isoformat()


def test_info_for_retired_and_unknown_cases():
    assert drop_pool.info("Clutch Case")["forecast"] is None
    assert drop_pool.info("Clutch Case")["left_active"] == "2023-04-08"
    assert drop_pool.info("Operation Bravo Case") is None
