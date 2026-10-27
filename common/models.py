"""Data model shared by the cloud and home parts.

For now only cases are tracked; they have no attributes of their own, so the base Item is enough.
Skins will later add wear, float, StatTrak, rarity, etc. Those go into `attributes`
(JSON/JSONB in the items table) and into an Item subclass in code. The price table stays the same.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Item:
    market_hash_name: str          # unique item name on Steam
    item_type: str = "case"        # case | skin | sticker | ...
    icon_url: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Case(Item):
    item_type: str = "case"


@dataclass
class PriceTick:
    """One price snapshot of an item on the Steam Market."""
    market_hash_name: str
    ts: int                        # snapshot unix time, UTC seconds (minute-aligned)
    price_cents: int               # lowest sell price, in cents
    listings: int | None = None    # number of listings for sale
    currency: str = "USD"
    source: str = "steam"


@dataclass
class SalePoint:
    """A Steam sales-history point (pricehistory): median price and units sold over a period.
    The last ~30 days are hourly, older ones daily."""
    market_hash_name: str
    ts: int                        # period start, unix time UTC
    median_cents: int | None       # median sale price in USD cents; None if Steam returned another currency
    volume: int                    # units sold in the period
    currency: str = "USD"
    source: str = "steam"
    span: int = 3600               # period length, seconds: 3600 (hour) or 86400 (day)
