"""Market index of cases: all cases equally weighted, chain-linked by day.

- Each case's daily price is smoothed: the mean of the logs of its last SMOOTH_DAYS days with sales, without
  the highest and lowest day. One odd trade does not move it, and cheap cases (a few cents, where Steam's
  one-cent steps are 20-30%) do not move in jumps.
- A case joins the index SEASON_DAYS after its first sale. A new case starts expensive and loses most of its
  price in its first months; counting that would make the index fall for years only because cases keep being
  released. The index shows how the existing cases move, not the release cycle.
- Each day moves the index by the average change over cases in the index on both that day and their previous
  day with sales, so a case joining or going quiet does not shift the index. Changes are not clipped:
  clipping breaks the chain and over years drags the index to zero.
"""
import math
from collections import deque

START = 100.0
SMOOTH_DAYS = 7
SEASON_DAYS = 180
DAY = 86400


def smoothed(prices: dict[int, dict[int, float]]) -> dict[int, dict[int, float]]:
    """{day: {case: price}} -> the same with each price smoothed over the case's last SMOOTH_DAYS days."""
    windows: dict[int, deque] = {}
    out: dict[int, dict[int, float]] = {}
    for day in sorted(prices):
        for case, price in prices[day].items():
            w = windows.setdefault(case, deque(maxlen=SMOOTH_DAYS))
            w.append(math.log(price))
            logs = sorted(w)[1:-1] if len(w) >= 3 else list(w)
            out.setdefault(day, {})[case] = math.exp(sum(logs) / len(logs))
    return out


def market_index(prices: dict[int, dict[int, float]], turnover: dict[int, float] | None = None) -> list[dict]:
    """prices: {day: {case id: daily price}} -> [{time, value, cases, turnover}] ascending, starting at START
    on the first day any case is in the index. turnover: {day: dollars traded over all cases}, passed through."""
    first: dict[int, int] = {}
    for day in sorted(prices):
        for case in prices[day]:
            first.setdefault(case, day)
    out: list[dict] = []
    log_level = math.log(START)
    prev: dict[int, float] = {}
    for day, cur in sorted(smoothed(prices).items()):
        cur = {c: p for c, p in cur.items() if day >= first[c] + SEASON_DAYS * DAY}
        if not cur and not out:
            continue
        moves = [math.log(cur[i] / prev[i]) for i in cur if i in prev]
        if moves:
            log_level += sum(moves) / len(moves)
        out.append({"time": day, "value": round(math.exp(log_level), 4), "cases": len(cur),
                    "turnover": round((turnover or {}).get(day, 0.0), 2)})
        prev.update(cur)
    return out
