"""Expected value (EV) of opening a case, per day.

An item's price on day D is its "price over recent sales": walk back from D over days with sales
until at least MIN_SALES units are collected, and take the median of those days weighted by volume.
Steam does not expose individual trades, only the median and volume per hour/day, so this is the
closest analogue of "the average of the last 10 sales": for illiquid items the window stretches
over weeks by itself, and a single random purchase barely moves the price.
"""
from collections import deque

MIN_SALES = 10
DAY = 86400


def weighted_median(points) -> float | None:
    """points: [(price, volume)]."""
    pts = sorted((p, v) for p, v in points if p is not None and v > 0)
    total = sum(v for _, v in pts)
    if not total:
        return None
    acc = 0
    for p, v in pts:
        acc += v
        if acc * 2 >= total:
            return p
    return pts[-1][0]


def daily_points(points) -> list[tuple[int, int, int]]:
    """Hourly/daily Steam history points -> [(UTC day start, day median in cents, units sold that day)]."""
    by_day: dict[int, list[tuple[int, int]]] = {}
    for p in points:
        if p.median_cents is not None and p.volume > 0:
            by_day.setdefault(p.ts // DAY * DAY, []).append((p.median_cents, p.volume))
    out = []
    for d, v in sorted(by_day.items()):
        m = weighted_median(v)
        if m is not None:
            out.append((d, round(m), sum(x for _, x in v)))
    return out


def price_series(days: list[tuple[int, int, int]], start: int, end: int) -> dict[int, int]:
    """Item price for every day in [start, end] (UTC day starts) over the last MIN_SALES sales.
    days - [(day, median, volume)] ascending. No price before the first sale."""
    out: dict[int, int] = {}
    window: deque = deque()
    vol = 0
    i = 0
    for d in range(start, end + 1, DAY):
        while i < len(days) and days[i][0] <= d:
            window.append(days[i])
            vol += days[i][2]
            i += 1
            # drop old days while the window still has MIN_SALES without them
            while len(window) > 1 and vol - window[0][2] >= MIN_SALES:
                vol -= window.popleft()[2]
        price = weighted_median((m, v) for _, m, v in window)
        if price is not None:
            out[d] = round(price)
    return out


def case_ev(probs: dict[str, float], item_days: dict[str, list[tuple[int, int, int]]],
            start: int, end: int) -> list[tuple[int, int, float]]:
    """[(day, EV in cents, coverage)] - coverage: probability share of items that already have a price
    on that day (rare StatTrak FN knives may have no sales at all)."""
    ev = {d: 0.0 for d in range(start, end + 1, DAY)}
    cov = dict.fromkeys(ev, 0.0)
    for name, p in probs.items():
        for d, price in price_series(item_days.get(name, []), start, end).items():
            ev[d] += p * price
            cov[d] += p
    return [(d, round(ev[d]), round(cov[d], 4)) for d in ev if cov[d] > 0]
