"""Сбор цен с Steam Community Market.

Используем поиск маркета (search/render, norender=1) — это JSON-эндпоинт самого Steam, тот же,
что дёргает страница маркета. Steam отдаёт не больше 10 предметов за запрос
(параметр count больше 10 игнорируется), поэтому все ~45 кейсов — это ~5 запросов с паузами
внутри одной минуты. Браузерные скраперы и прокси для такой частоты не нужны.

priceoverview (медиана и объём за 24 ч) требует отдельный запрос на каждый предмет: ~45 кейсов
в минуту гарантированно упрутся в лимит, поэтому он здесь не используется.
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
    """Оружейные кейсы называются '... Case'. Капсулы, сувенирные наборы и ключи
    ('... Case Key') сюда не попадают."""
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
            if ticks:  # часть страниц уже получена: сохраняем их, остальное возьмём в следующую минуту
                log.warning("Steam ответил 429 на странице start=%d, сохраняю %d цен", start, len(ticks))
                return ticks, items
            raise SteamRateLimited("Steam ответил 429 (слишком много запросов)")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not data.get("success"):
            raise RuntimeError(f"Steam ответил success=false: {str(data)[:200]}")
        total = data.get("total_count", 0)
        page = data.get("results") or []
        if not page:
            break
        t, i = parse_search_page(data, ts)
        ticks += t
        items += i
        start += len(page)
        if start < total:
            await asyncio.sleep(PAGE_PAUSE)  # не частим между страницами
    return ticks, items


def make_client(proxy: str | None = None) -> AsyncSession:
    """HTTP-клиент с TLS-отпечатком и заголовками настоящего Chrome. Обычные Python-клиенты
    (httpx, requests, urllib) Steam распознаёт по TLS-рукопожатию и отвечает им 429."""
    return AsyncSession(impersonate=IMPERSONATE, timeout=30, proxy=proxy,
                        headers={"Accept-Language": "en-US,en;q=0.9"})


# ---------- История продаж (нужен логин) ----------

HISTORY_URL = "https://steamcommunity.com/market/pricehistory/"
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
# pricehistory отдаёт цены в валюте кошелька аккаунта, параметр currency игнорирует.
_CURRENCY_BY_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "₴": "UAH", "pуб.": "RUB", "руб.": "RUB",
                       "₸": "KZT", "zł": "PLN", "¥": "CNY", "R$": "BRL", "₺": "TRY", "CHF": "CHF"}


class SteamAuthError(Exception):
    pass


def parse_history_date(s: str) -> int:
    """'Oct 24 2026 01: +0' -> unix-время (UTC)."""
    from calendar import timegm
    mon, day, year, hour = s.split()[:4]
    return timegm((int(year), _MONTHS[mon], int(day), int(hour.rstrip(":")), 0, 0))


def parse_history(name: str, data: dict) -> list[SalePoint]:
    sym = (data.get("price_prefix") or data.get("price_suffix") or "").strip()
    currency = _CURRENCY_BY_SYMBOL.get(sym, sym or "USD")
    # Храним только доллары. Если Steam отдал медиану в другой валюте (валюта/страна аккаунта, параметр
    # currency он игнорирует), медиану отбрасываем: пересчёт прошлых цен по сегодняшнему курсу исказил бы
    # данные. Число продаж от валюты не зависит, его сохраняем всегда.
    usd = currency == "USD"
    out = []
    for row in data.get("prices") or []:
        date, median, volume = row[0], row[1], row[2]
        out.append(SalePoint(name, parse_history_date(date), round(float(median) * 100) if usd else None,
                             int(str(volume).replace(",", "")), "USD"))
    return out


async def fetch_price_history(client: AsyncSession, name: str, login_secure: str) -> list[SalePoint]:
    r = await client.get(HISTORY_URL, params={"appid": 730, "market_hash_name": name, "currency": 1},
                         cookies={"steamLoginSecure": login_secure})
    if r.status_code == 429:
        raise SteamRateLimited("Steam ответил 429 на pricehistory")
    if r.status_code in (400, 401, 403):
        raise SteamAuthError(f"pricehistory: HTTP {r.status_code}, cookie steamLoginSecure устарел или неверный")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("success"):
        raise SteamAuthError("pricehistory: success=false, cookie steamLoginSecure устарел или неверный")
    return parse_history(name, data)


# ---------- Продление логина ----------
#
# steamLoginSecure = "<steamid>%7C%7C<access token>", а access token Steam выдаёт ровно на сутки.
# Браузер продлевает его через долгоживущий refresh token (cookie steamRefresh_steam на
# login.steampowered.com): login.steampowered.com/jwt/refresh перенаправляет на
# steamcommunity.com/login/settoken, и тот ставит свежий steamLoginSecure. Делаем то же самое.
# (IAuthenticationService/GenerateAccessTokenForApp токен из браузера не принимает.)

JWT_REFRESH_URL = "https://login.steampowered.com/jwt/refresh"


def split_login_cookie(value: str) -> tuple[str, str]:
    """'7656...%7C%7CeyJ...' -> ('7656...', 'eyJ...')."""
    from urllib.parse import unquote
    steamid, sep, token = unquote(value.strip()).partition("||")
    if not sep or not steamid.isdigit() or token.count(".") != 2:
        raise SteamAuthError("значение cookie не похоже на токен Steam (нет '%7C%7C' или JWT)")
    return steamid, token


def jwt_expires_at(token: str) -> int:
    import base64
    import json
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])


async def refresh_login_secure(refresh_cookie: str, proxy: str | None = None) -> str:
    """Получает свежий steamLoginSecure по refresh token, повторяя путь браузера.
    Отдельная сессия, чтобы полученные cookie не смешивались с основным клиентом."""
    from urllib.parse import urlparse
    split_login_cookie(refresh_cookie)  # проверка формата
    async with make_client(proxy) as s:
        s.cookies.set("steamRefresh_steam", refresh_cookie.strip(), domain=urlparse(JWT_REFRESH_URL).hostname)
        r = await s.get(JWT_REFRESH_URL, params={"redir": "https://steamcommunity.com/"}, allow_redirects=False)
        location = r.headers.get("location", "")
        if r.status_code not in (301, 302, 303) or "/login/settoken" not in location:
            raise SteamAuthError(f"продление токена: Steam ответил {r.status_code} без перехода на settoken, "
                                 "refresh token устарел или отозван")
        await s.get(location, allow_redirects=False)
        value = next((c.value for c in s.cookies.jar if c.name == "steamLoginSecure"), None)
    if not value:
        raise SteamAuthError("продление токена: Steam не выдал steamLoginSecure, refresh token устарел или отозван")
    split_login_cookie(value)
    return value
