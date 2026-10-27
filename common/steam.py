"""Price collection from the Steam Community Market.

We use the market search (search/render, norender=1): Steam's own JSON endpoint, the same one
the market page calls. Steam returns at most 10 items per request (count above 10 is ignored),
so all ~45 cases take ~5 requests with pauses within one minute. No browser scrapers or
proxies are needed at this rate.

priceoverview (24h median and volume) needs a separate request per item: ~45 cases a minute
would always hit the rate limit, so it is not used here.
"""
import asyncio
import logging
import os

from curl_cffi.requests import AsyncSession

from .models import Case, PriceTick, SalePoint

SEARCH_URL = "https://steamcommunity.com/market/search/render/"
log = logging.getLogger("steam")
PAGE_PAUSE = float(os.getenv("STEAM_PAGE_PAUSE", "4"))
ICON_CDN = "https://community.cloudflare.steamstatic.com/economy/image/"
IMPERSONATE = os.getenv("STEAM_IMPERSONATE", "chrome")


class SteamRateLimited(Exception):
    pass


def is_case(name: str) -> bool:
    """Weapon cases are named '... Case'. Capsules, souvenir packages and keys
    ('... Case Key') are excluded."""
    return name.endswith(" Case")


def parse_search_page(data: dict, ts: int) -> tuple[list[PriceTick], list[Case]]:
    ticks, items = [], []
    for res in data.get("results") or []:
        name = res.get("hash_name") or res.get("name")
        price = res.get("sell_price")
        if not name or not is_case(name) or not price:
            continue
        icon = (res.get("asset_description") or {}).get("icon_url")
        ticks.append(PriceTick(name, ts, int(price), res.get("sell_listings")))
        items.append(Case(name, icon_url=ICON_CDN + icon if icon else None))
    return ticks, items


async def fetch_cases(client: AsyncSession, ts: int) -> tuple[list[PriceTick], list[Case]]:
    ticks: list[PriceTick] = []
    items: list[Case] = []
    start, total = 0, None
    while total is None or start < total:
        r = await client.get(SEARCH_URL, params={
            "appid": 730, "norender": 1, "count": 10, "start": start,
            "query": "Case", "category_730_Type[]": "tag_CSGO_Type_WeaponCase",
            "sort_column": "name", "sort_dir": "asc",
        })
        if r.status_code == 429:
            if ticks:  # some pages already arrived: keep them, the rest comes next minute
                log.warning("Steam returned 429 on page start=%d, keeping %d prices", start, len(ticks))
                return ticks, items
            raise SteamRateLimited("Steam returned 429 (too many requests)")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not data.get("success"):
            raise RuntimeError(f"Steam returned success=false: {str(data)[:200]}")
        total = data.get("total_count", 0)
        page = data.get("results") or []
        if not page:
            break
        t, i = parse_search_page(data, ts)
        ticks += t
        items += i
        start += len(page)
        if start < total:
            await asyncio.sleep(PAGE_PAUSE)  # pause between pages
    return ticks, items


def make_client(proxy: str | None = None) -> AsyncSession:
    """HTTP client with the TLS fingerprint and headers of a real Chrome. Plain Python clients
    (httpx, requests, urllib) are recognized by Steam from the TLS handshake and get 429."""
    return AsyncSession(impersonate=IMPERSONATE, timeout=30, proxy=proxy,
                        headers={"Accept-Language": "en-US,en;q=0.9"})


# ---------- Sales history (login required) ----------

HISTORY_URL = "https://steamcommunity.com/market/pricehistory/"
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
# pricehistory returns prices in the account wallet currency and ignores the currency parameter.
_CURRENCY_BY_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "₴": "UAH", "pуб.": "RUB", "руб.": "RUB",
                       "₸": "KZT", "zł": "PLN", "¥": "CNY", "R$": "BRL", "₺": "TRY", "CHF": "CHF"}


class SteamAuthError(Exception):
    pass


def parse_history_date(s: str) -> int:
    """'Oct 24 2026 01: +0' -> unix time (UTC)."""
    from calendar import timegm
    mon, day, year, hour = s.split()[:4]
    return timegm((int(year), _MONTHS[mon], int(day), int(hour.rstrip(":")), 0, 0))


def parse_history(name: str, data: dict) -> list[SalePoint]:
    sym = (data.get("price_prefix") or data.get("price_suffix") or "").strip()
    currency = _CURRENCY_BY_SYMBOL.get(sym, sym or "USD")
    # Only USD is stored. If Steam returned the median in another currency (account wallet/country; it
    # ignores the currency parameter), the median is dropped: converting past prices at today's rate would
    # distort the data. The number of sales does not depend on currency and is always kept.
    usd = currency == "USD"
    rows = [(parse_history_date(r[0]), r[1], r[2]) for r in data.get("prices") or []]
    # Steam returns the last ~30 days hourly and everything older daily: one point per day at hour 01.
    # The hourly part starts on the first day with more than one point.
    per_day: dict[int, int] = {}
    for ts, _, _ in rows:
        per_day[ts // 86400] = per_day.get(ts // 86400, 0) + 1
    hourly_from = min((d for d, n in per_day.items() if n > 1), default=None)
    out = []
    for ts, median, volume in rows:
        daily = (hourly_from is None or ts // 86400 < hourly_from) and ts % 86400 == 3600
        out.append(SalePoint(name, ts, round(float(median) * 100) if usd else None,
                             int(str(volume).replace(",", "")), "USD", span=86400 if daily else 3600))
    return out


async def fetch_price_history(client: AsyncSession, name: str, login_secure: str) -> list[SalePoint]:
    r = await client.get(HISTORY_URL, params={"appid": 730, "market_hash_name": name, "currency": 1},
                         cookies={"steamLoginSecure": login_secure})
    if r.status_code == 429:
        raise SteamRateLimited("Steam returned 429 on pricehistory")
    if r.status_code in (400, 401, 403):
        raise SteamAuthError(f"pricehistory: HTTP {r.status_code}, steamLoginSecure cookie expired or invalid")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("success"):
        raise SteamAuthError("pricehistory: success=false, steamLoginSecure cookie expired or invalid")
    return parse_history(name, data)


# ---------- Login renewal ----------
#
# steamLoginSecure = "<steamid>%7C%7C<access token>", and Steam issues the access token for exactly one day.
# The browser renews it with a long-lived refresh token (steamRefresh_steam cookie on
# login.steampowered.com): login.steampowered.com/jwt/refresh redirects to
# steamcommunity.com/login/settoken, which sets a fresh steamLoginSecure. We do the same.
# (IAuthenticationService/GenerateAccessTokenForApp does not accept the browser token.)

JWT_REFRESH_URL = "https://login.steampowered.com/jwt/refresh"


def split_login_cookie(value: str) -> tuple[str, str]:
    """'7656...%7C%7CeyJ...' -> ('7656...', 'eyJ...')."""
    from urllib.parse import unquote
    steamid, sep, token = unquote(value.strip()).partition("||")
    if not sep or not steamid.isdigit() or token.count(".") != 2:
        raise SteamAuthError("cookie value does not look like a Steam token (no '%7C%7C' or JWT)")
    return steamid, token


def jwt_expires_at(token: str) -> int:
    import base64
    import json
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])


async def refresh_login_secure(refresh_cookie: str, proxy: str | None = None) -> str:
    """Gets a fresh steamLoginSecure from the refresh token, following the browser flow.
    A separate session so the received cookies do not mix with the main client."""
    from urllib.parse import urlparse
    split_login_cookie(refresh_cookie)  # format check
    async with make_client(proxy) as s:
        s.cookies.set("steamRefresh_steam", refresh_cookie.strip(), domain=urlparse(JWT_REFRESH_URL).hostname)
        r = await s.get(JWT_REFRESH_URL, params={"redir": "https://steamcommunity.com/"}, allow_redirects=False)
        location = r.headers.get("location", "")
        if r.status_code not in (301, 302, 303) or "/login/settoken" not in location:
            raise SteamAuthError(f"token renewal: Steam returned {r.status_code} without redirecting to settoken, "
                                 "refresh token expired or revoked")
        await s.get(location, allow_redirects=False)
        value = next((c.value for c in s.cookies.jar if c.name == "steamLoginSecure"), None)
    if not value:
        raise SteamAuthError("token renewal: Steam did not issue steamLoginSecure, refresh token expired or revoked")
    split_login_cookie(value)
    return value
