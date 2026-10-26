"""Проверка продления токена Steam: python -m cloud.check_token (внутри контейнера сборщика).
Выводит только срок действия и валюту истории цен, сами токены не печатает."""
import asyncio
import time

from common.steam import (HISTORY_URL, SteamAuthError, jwt_expires_at, make_client, refresh_login_secure,
                          split_login_cookie)

from . import config


def _fmt(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


async def main():
    if not config.STEAM_REFRESH_TOKEN:
        print("STEAM_REFRESH_TOKEN не задан")
        return
    print("refresh token действует до", _fmt(jwt_expires_at(split_login_cookie(config.STEAM_REFRESH_TOKEN)[1])))
    try:
        value = await refresh_login_secure(config.STEAM_REFRESH_TOKEN, config.STEAM_PROXY)
    except SteamAuthError as e:
        print("ПРОДЛЕНИЕ НЕ РАБОТАЕТ:", e)
        return
    print("ПРОДЛЕНИЕ РАБОТАЕТ, новый steamLoginSecure до", _fmt(jwt_expires_at(split_login_cookie(value)[1])))
    async with make_client(config.STEAM_PROXY) as s:
        r = await s.get(HISTORY_URL, params={"appid": 730, "market_hash_name": "Kilowatt Case", "currency": 1},
                        cookies={"steamLoginSecure": value})
    data = r.json() if r.status_code == 200 else {}
    if not data.get("success"):
        print("ИСТОРИЯ ЦЕН НЕ ОТДАЁТСЯ: HTTP", r.status_code, "(Steam может закрывать площадку новым аккаунтам)")
        return
    sym = (data.get("price_prefix") or data.get("price_suffix") or "").strip()
    print("ИСТОРИЯ ЦЕН В USD: да" if sym == "$" else f"ИСТОРИЯ ЦЕН В USD: нет, валюта аккаунта {sym}")


if __name__ == "__main__":
    asyncio.run(main())
