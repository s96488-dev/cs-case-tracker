"""Market index of cases: all cases equally weighted, chain-linked by day.

Each day moves the index by the average log change of the daily median over cases that have sales on
both that day and their previous day with sales, so a case entering or leaving does not shift the index.
"""
import math

START = 100.0
# Each case's daily change is clipped to about -50%..+50% so a single random trade does not move the index.
MIN_MOVE, MAX_MOVE = -0.7, 0.4


def market_index(prices: dict[int, dict[int, float]]) -> list[dict]:
    """prices: {day: {case id: daily price}} -> [{time, value, cases}] ascending, starting at START."""
    out, level, prev = [], START, None
    for day in sorted(prices):
        cur = prices[day]
        if prev is not None:
            moves = [max(MIN_MOVE, min(MAX_MOVE, math.log(cur[i] / prev[i]))) for i in cur if i in prev]
            if moves:
                level *= math.exp(sum(moves) / len(moves))
        out.append({"time": day, "value": round(level, 3), "cases": len(cur)})
        prev = {**(prev or {}), **cur}
    return out
