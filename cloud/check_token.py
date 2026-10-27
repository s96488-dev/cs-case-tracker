"""Checks Steam token renewal: python -m cloud.check_token (inside the collector container).
Prints only expiry dates and the price-history currency, never the tokens themselves."""
import asyncio
import time

from common.steam import (
    HISTORY_URL,
    SteamAuthError,
    jwt_expires_at,
    make_client,
    refresh_login_secure,
    split_login_cookie,
)

from . import config


def _fmt(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


async def main():
    if not config.STEAM_REFRESH_TOKEN:
        print("STEAM_REFRESH_TOKEN is not set")
        return
    print("refresh token valid until", _fmt(jwt_expires_at(split_login_cookie(config.STEAM_REFRESH_TOKEN)[1])))
    try:
        value = await refresh_login_secure(config.STEAM_REFRESH_TOKEN, config.STEAM_PROXY)
    except SteamAuthError as e:
        print("RENEWAL FAILED:", e)
        return
    print("RENEWAL WORKS, new steamLoginSecure valid until", _fmt(jwt_expires_at(split_login_cookie(value)[1])))
    async with make_client(config.STEAM_PROXY) as s:
        r = await s.get(HISTORY_URL, params={"appid": 730, "market_hash_name": "Kilowatt Case", "currency": 1},
                        cookies={"steamLoginSecure": value})
    data = r.json() if r.status_code == 200 else {}
    if not data.get("success"):
        print("PRICE HISTORY NOT AVAILABLE: HTTP", r.status_code, "(Steam may restrict the market for new accounts)")
        return
    sym = (data.get("price_prefix") or data.get("price_suffix") or "").strip()
    print("PRICE HISTORY IN USD: yes" if sym == "$" else f"PRICE HISTORY IN USD: no, account currency {sym}")


if __name__ == "__main__":
    asyncio.run(main())
