"""Ожидаемая стоимость открытия кейса (EV) по дням.

Цена предмета на день D — «цена по последним продажам»: идём от дня D назад по дням с продажами,
пока не наберём не меньше MIN_SALES штук, и берём медиану цен этих дней, взвешенную по числу продаж.
Steam не отдаёт отдельные сделки, только медиану и объём за час/день, поэтому это ближайший аналог
«средней по 10 последним продажам»: у неликвидных предметов окно само растягивается на недели,
и одна случайная покупка почти не сдвигает цену.
"""
from collections import deque

MIN_SALES = 10
DAY = 86400


def weighted_median(points) -> float | None:
    """points: [(цена, объём)]."""
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
    """Часовые/дневные точки истории Steam -> [(начало дня UTC, медиана дня в центах, продано за день)]."""
    by_day: dict[int, list[tuple[int, int]]] = {}
    for p in points:
        if p.median_cents is not None and p.volume > 0:
            by_day.setdefault(p.ts // DAY * DAY, []).append((p.median_cents, p.volume))
    return [(d, round(weighted_median(v)), sum(x for _, x in v)) for d, v in sorted(by_day.items())]


def price_series(days: list[tuple[int, int, int]], start: int, end: int) -> dict[int, int]:
    """Цена предмета на каждый день [start, end] (начала дней UTC) по последним MIN_SALES продажам.
    days — [(день, медиана, объём)] по возрастанию. До первой продажи цены нет."""
    out: dict[int, int] = {}
    window: deque = deque()
    vol = 0
    i = 0
    for d in range(start, end + 1, DAY):
        while i < len(days) and days[i][0] <= d:
            window.append(days[i])
            vol += days[i][2]
            i += 1
            # лишние старые дни выкидываем, пока без них всё ещё набирается MIN_SALES
            while len(window) > 1 and vol - window[0][2] >= MIN_SALES:
                vol -= window.popleft()[2]
        if window:
            out[d] = round(weighted_median((m, v) for _, m, v in window))
    return out


def case_ev(probs: dict[str, float], item_days: dict[str, list[tuple[int, int, int]]],
            start: int, end: int) -> list[tuple[int, int, float]]:
    """[(день, EV в центах, покрытие)] — покрытие: доля вероятности предметов, у которых на этот день
    уже есть цена (у редких ножей StatTrak FN продаж может не быть вовсе)."""
    ev = {d: 0.0 for d in range(start, end + 1, DAY)}
    cov = dict.fromkeys(ev, 0.0)
    for name, p in probs.items():
        for d, price in price_series(item_days.get(name, []), start, end).items():
            ev[d] += p * price
            cov[d] += p
    return [(d, round(ev[d]), round(cov[d], 4)) for d in ev if cov[d] > 0]
