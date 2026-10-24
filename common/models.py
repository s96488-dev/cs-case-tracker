"""Модель данных, общая для облака и дома.

Сейчас отслеживаем только кейсы, у них нет своих параметров: хватает базового Item.
Для скинов позже появятся износ, float, StatTrak, редкость и т.д. Они пойдут в `attributes`
(JSON/JSONB в таблице items), а в коде — в наследника Item. Таблица цен при этом не меняется.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Item:
    market_hash_name: str          # уникальное имя предмета в Steam
    item_type: str = "case"        # case | skin | sticker | ...
    icon_url: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Case(Item):
    item_type: str = "case"


@dataclass
class PriceTick:
    """Один снимок цены предмета на Steam Market."""
    market_hash_name: str
    ts: int                        # unix-время снимка, секунды UTC (кратно минуте)
    price_cents: int               # минимальная цена продажи, в центах
    listings: int | None = None    # сколько лотов выставлено на продажу
    currency: str = "USD"
    source: str = "steam"


@dataclass
class SalePoint:
    """Точка истории продаж Steam (pricehistory): медианная цена и число продаж за период.
    Последние ~30 дней — по часам, раньше — по дням."""
    market_hash_name: str
    ts: int                        # начало периода, unix-время UTC
    median_cents: int
    volume: int                    # сколько штук продано за период
    currency: str = "USD"
    source: str = "steam"
