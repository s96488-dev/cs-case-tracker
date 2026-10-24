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

from .models import Case, PriceTick

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
