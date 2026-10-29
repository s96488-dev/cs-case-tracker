"""Market index of cases: all cases equally weighted, chain-linked by day.

Each case's daily price is first replaced by the median of its last SMOOTH_DAYS days with sales, so a day
with one odd trade does not move the index. Each day then moves the index by the average log change of these
prices over cases that have sales on both that day and their previous day with sales, so a case entering or
leaving does not shift the index.

Changes are not clipped: clipping breaks the chain (a one-day spike clipped on the way up and on the way back
leaves a permanent step), and over years of history such steps pile up and drag the index towards zero.
"""
import math
from collections import deque
from statistics import median

START = 100.0
SMOOTH_DAYS = 7


def smoothed(prices: dict[int, dict[int, float]]) -> dict[int, dict[int, float]]:
    """{day: {case: price}} -> the same with each price replaced by the median of the case's last SMOOTH_DAYS."""
    windows: dict[int, deque] = {}
    out: dict[int, dict[int, float]] = {}
    for day in sorted(prices):
        for case, price in prices[day].items():
            w = windows.setdefault(case, deque(maxlen=SMOOTH_DAYS))
            w.append(price)
            out.setdefault(day, {})[case] = median(w)
    return out


def market_index(prices: dict[int, dict[int, float]]) -> list[dict]:
    """prices: {day: {case id: daily price}} -> [{time, value, cases}] ascending, starting at START."""
    out, log_level, prev = [], math.log(START), {}
    for day, cur in sorted(smoothed(prices).items()):
        moves = [math.log(cur[i] / prev[i]) for i in cur if i in prev]
        if moves:
            log_level += sum(moves) / len(moves)
        out.append({"time": day, "value": round(math.exp(log_level), 4), "cases": len(cur)})
        prev.update(cur)
    return out
