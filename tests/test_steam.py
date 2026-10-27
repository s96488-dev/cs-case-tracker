import base64
import json

import pytest

from common.steam import (
    ICON_CDN,
    SteamAuthError,
    is_case,
    jwt_expires_at,
    parse_history,
    parse_history_date,
    parse_search_page,
    split_login_cookie,
)

DAY = 86400


def test_is_case_excludes_keys_capsules_and_packages():
    assert is_case("Kilowatt Case")
    assert not is_case("Kilowatt Case Key")
    assert not is_case("Paris 2023 Legends Sticker Capsule")
    assert not is_case("Copenhagen 2024 Mirage Souvenir Package")


def test_parse_search_page_keeps_only_priced_cases():
    data = {"results": [
        {"hash_name": "Clutch Case", "sell_price": 56, "sell_listings": 120000,
         "asset_description": {"icon_url": "abc"}},
        {"hash_name": "Clutch Case Key", "sell_price": 249, "sell_listings": 10},
        {"hash_name": "Fracture Case", "sell_price": 0, "sell_listings": 0},
        {"name": "Recoil Case", "sell_price": 31},
    ]}
    ticks, items = parse_search_page(data, ts=1_700_000_040)
    assert [(t.market_hash_name, t.price_cents, t.listings, t.ts) for t in ticks] == [
        ("Clutch Case", 56, 120000, 1_700_000_040), ("Recoil Case", 31, None, 1_700_000_040)]
    assert items[0].icon_url == ICON_CDN + "abc"
    assert items[1].icon_url is None
    assert all(t.currency == "USD" for t in ticks)


def test_parse_search_page_handles_empty_results():
    assert parse_search_page({"results": None}, 0) == ([], [])


def test_parse_history_date_is_utc():
    assert parse_history_date("Oct 24 2026 01: +0") == 1792803600


def _history(prefix, prices):
    return {"price_prefix": prefix, "prices": prices}


def test_parse_history_marks_daily_and_hourly_points():
    data = _history("$", [
        ["Jan 01 2026 01: +0", 1.5, "1,200"],   # old daily point
        ["Jan 02 2026 01: +0", 1.6, "900"],     # old daily point
        ["Feb 01 2026 00: +0", 1.7, "40"],      # hourly part starts here
        ["Feb 01 2026 01: +0", 1.75, "35"],
    ])
    pts = parse_history("Clutch Case", data)
    assert [p.span for p in pts] == [DAY, DAY, 3600, 3600]
    assert pts[0].volume == 1200
    assert pts[1].median_cents == 160
    assert pts[3].median_cents == 175


def test_parse_history_drops_non_usd_median_but_keeps_volume():
    pts = parse_history("Clutch Case", {"price_suffix": "₴", "prices": [["Jan 01 2026 01: +0", 22.5, "7"]]})
    assert pts[0].median_cents is None
    assert pts[0].volume == 7
    assert pts[0].currency == "USD"


def _jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def test_split_login_cookie_and_expiry():
    token = _jwt({"exp": 1_800_000_000, "sub": "76561198000000000"})
    steamid, tok = split_login_cookie("76561198000000000%7C%7C" + token)
    assert steamid == "76561198000000000"
    assert jwt_expires_at(tok) == 1_800_000_000


@pytest.mark.parametrize("value", ["", "not-a-cookie", "abc%7C%7Ceyx.y.z", "7656%7C%7Conly.two"])
def test_split_login_cookie_rejects_garbage(value):
    with pytest.raises(SteamAuthError):
        split_login_cookie(value)
