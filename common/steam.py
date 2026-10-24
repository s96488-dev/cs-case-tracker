"""Сбор цен с Steam Community Market.

Используем поиск маркета (search/render, norender=1) — это JSON-эндпоинт самого Steam, тот же,
что дёргает страница маркета. Один запрос возвращает до 100 кейсов сразу с минимальной ценой
продажи и числом лотов. Итого 1 запрос в минуту — примерно в 20 раз ниже порога, при котором
Steam начинает отвечать 429. Браузерные скраперы и прокси для такой частоты не нужны.

priceoverview (медиана и объём за 24 ч) требует отдельный запрос на каждый предмет: ~45 кейсов
в минуту гарантированно упрутся в лимит, поэтому он здесь не используется.
"""
import asyncio

import httpx

from .models import Case, PriceTick

SEARCH_URL = "https://steamcommunity.com/market/search/render/"
ICON_CDN = "https://community.cloudflare.steamstatic.com/economy/image/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


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


async def fetch_cases(client: httpx.AsyncClient, ts: int) -> tuple[list[PriceTick], list[Case]]:
    ticks: list[PriceTick] = []
    items: list[Case] = []
    start, total = 0, None
    while total is None or start < total:
        r = await client.get(SEARCH_URL, params={
            "appid": 730, "norender": 1, "count": 100, "start": start,
            "q": "Case", "category_730_Type[]": "tag_CSGO_Type_WeaponCase",
            "sort_column": "name", "sort_dir": "asc",
        })
        if r.status_code == 429:
            raise SteamRateLimited("Steam ответил 429 (слишком много запросов)")
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
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
            await asyncio.sleep(5)  # если страниц несколько, не частим
    return ticks, items


def make_client(proxy: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, proxy=proxy, follow_redirects=True,
                             headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
