"""Проверка продления токена Steam: python -m cloud.check_token (внутри контейнера сборщика).
Выводит только срок действия, сами токены не печатает."""
import asyncio
import time

from common.steam import SteamAuthError, jwt_expires_at, refresh_login_secure, split_login_cookie

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


if __name__ == "__main__":
    asyncio.run(main())
