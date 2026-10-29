"""Backtest of case-buying signals on daily Steam prices, and a genetic search over signal parameters.

A trade buys a case the day after a signal at that day's price and sells it `hold` days later; the seller
gets what Steam pays out after its 5% and the game's 10% fee, each at least 1 cent (`proceeds`), so a case sold
for $0.03 pays out $0.01. Signals are checked once a week, and a case is not bought again
while it is held, so one long rally does not count as dozens of trades.

Every result is compared with a baseline: buying every case every week with the same holding period. Case
prices rose a lot over the years, so almost any rule makes money on paper; a signal is only useful if it beats
buying at random.

The genetic search fits parameters on the training period (trades that close before `split`) and reports
them on the test period (trades opened after `split`), which the search never saw. Its fitness is measured over
calendar quarters rather than single trades: trades of many cases bought during one market event are one bet,
not dozens.
"""
import math
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .market import market_index

STEP = 7            # days between signal checks
DAY = 86400
MIN_QUARTERS = 6    # a rule must trade in at least this many quarters


def proceeds(price: float) -> float:
    """What the seller receives for a sale at `price` dollars: the largest amount S (cents) with
    S + max(1, S * 5%) + max(1, S * 10%) <= price, as Steam computes its and the game's fee."""
    p = round(price * 100)
    s = int(p / 1.15) + 3      # the floors make the fees a bit under 15%
    while s > 0 and s + max(1, s * 5 // 100) + max(1, s * 10 // 100) > p:
        s -= 1
    return s / 100


def quarter(day: int) -> int:
    """Calendar quarter of an epoch day, counted from year 0."""
    d = datetime.fromtimestamp(day * DAY, UTC)
    return d.year * 4 + (d.month - 1) // 3


def _ret(buy: float, sell: float) -> float:
    """Net return (x) of buying at `buy` and selling at `sell`. A sale that pays out nothing counts as 0.1 cent so
    the log stays finite; the buy price is at least 1 cent."""
    return max(proceeds(sell), 0.001) / max(buy, 0.01)


@dataclass
class Case:
    """Dense daily series of one case from its first sale: price is carried over days without sales."""
    name: str
    start: int                  # first day (epoch day number)
    price: list[float]
    volume: list[float]
    ev: list[float | None] = field(default_factory=list)
    left_day: int | None = None     # day it left the active drop pool


@dataclass
class Data:
    cases: list[Case]
    end: int                                # last day with data
    market: dict[int, float]                # day -> market index
    feats: dict[str, list[list[float]]]     # feature -> per case -> per day (index from case.start)


def build_cases(daily: dict[str, list[tuple[int, float, float]]], ev: dict[str, dict[int, float]] | None = None,
                left: dict[str, int] | None = None) -> list[Case]:
    """daily: {case: [(epoch day, price, volume)] ascending} -> dense series."""
    out = []
    for name, rows in daily.items():
        if not rows:
            continue
        start, last = rows[0][0], rows[-1][0]
        by_day = {d: (p, v) for d, p, v in rows}
        price, volume, evs, p = [], [], [], rows[0][1]
        for d in range(start, last + 1):
            if d in by_day:
                p = by_day[d][0]
            price.append(p)
            volume.append(by_day[d][1] if d in by_day else 0.0)
            evs.append((ev or {}).get(name, {}).get(d))
        out.append(Case(name, start, price, volume, evs, (left or {}).get(name)))
    return out


def _smooth(xs: list[float], n: int = 7) -> list[float]:
    """Trailing geometric mean over n days."""
    out, acc = [], 0.0
    logs = [math.log(x) for x in xs]
    for i, v in enumerate(logs):
        acc += v
        if i >= n:
            acc -= logs[i - n]
        out.append(math.exp(acc / min(i + 1, n)))
    return out


def _rolling_mean(xs: list[float], window: int) -> list[float]:
    out, acc = [], 0.0
    for i, v in enumerate(xs):
        acc += v
        if i >= window:
            acc -= xs[i - window]
        out.append(acc / min(i + 1, window))
    return out


def _rolling_max(xs: list[float], window: int) -> list[float]:
    out: list[float] = []
    q: deque = deque()          # indexes with decreasing values
    for i, v in enumerate(xs):
        while q and xs[q[-1]] <= v:
            q.pop()
        q.append(i)
        if q[0] <= i - window:
            q.popleft()
        out.append(xs[q[0]])
    return out


def _rolling_z(xs: list[float], window: int, min_count: int = 60) -> list[float]:
    """z-score of each value against the non-NaN values of the last `window` days (including it)."""
    nan = float("nan")
    out, s, s2, cnt = [], 0.0, 0.0, 0
    for i, v in enumerate(xs):
        if not math.isnan(v):
            s, s2, cnt = s + v, s2 + v * v, cnt + 1
        if i >= window and not math.isnan(old := xs[i - window]):
            s, s2, cnt = s - old, s2 - old * old, cnt - 1
        if math.isnan(v) or cnt < min_count:
            out.append(nan)
            continue
        m = s / cnt
        sd = math.sqrt(max(s2 / cnt - m * m, 0.0))
        out.append((v - m) / sd if sd > 1e-12 else nan)
    return out


def prepare(cases: list[Case]) -> Data:
    """Computes the features every signal can use. All of them use only data up to that day."""
    nan = float("nan")
    end = max(c.start + len(c.price) - 1 for c in cases)
    prices: dict[int, dict[int, float]] = {c.start + i: {} for c in cases for i in range(len(c.price))}
    turnover: dict[int, float] = {}
    for k, c in enumerate(cases):
        for i, (p, v) in enumerate(zip(c.price, c.volume, strict=True)):
            if v > 0:
                prices[c.start + i][k] = p
                turnover[c.start + i] = turnover.get(c.start + i, 0.0) + p * v
    idx = {r["time"]: r["value"] for r in market_index({d * DAY: v for d, v in prices.items() if v},
                                                        {d * DAY: v for d, v in turnover.items()})}
    market: dict[int, float] = {}
    last_v = None
    for d in range(min(prices), end + 1):
        last_v = idx.get(d * DAY, last_v)
        if last_v is not None:
            market[d] = last_v
    # Market drawdown from its running peak and turnover of the last 30 days vs the last 365.
    mdd: dict[int, float] = {}
    peak = 0.0
    for d in sorted(market):
        peak = max(peak, market[d])
        mdd[d] = market[d] / peak - 1
    days = sorted(turnover)
    tday = [turnover.get(d, 0.0) for d in range(days[0], end + 1)] if days else []
    t30, t365 = _rolling_mean(tday, 30), _rolling_mean(tday, 365)
    turn = {days[0] + i: (t30[i] / t365[i] if t365[i] else nan) for i in range(len(tday))} if days else {}

    feats: dict[str, list[list[float]]] = {k: [] for k in FEATURES}
    for c in cases:
        sp = _smooth(c.price)
        n = len(sp)
        peak365 = _rolling_max(sp, 365)
        vol30 = _rolling_mean(c.volume, 30)
        rel = [math.log(sp[i] / market[c.start + i]) if c.start + i in market else nan for i in range(n)]
        relz = _rolling_z(rel, 365)
        feats["market_dd"].append([mdd.get(c.start + i, nan) for i in range(n)])
        feats["market_turnover"].append([turn.get(c.start + i, nan) for i in range(n)])
        feats["case_dd"].append([sp[i] / peak365[i] - 1 for i in range(n)])
        feats["momentum_30d"].append([sp[i] / sp[i - 30] - 1 if i >= 30 else nan for i in range(n)])
        feats["vs_market_z"].append(relz)
        feats["price_to_ev"].append([sp[i] / e if (e := c.ev[i]) else nan for i in range(n)])
        feats["days_since_left_pool"].append(
            [float(c.start + i - c.left_day) if c.left_day is not None and c.start + i >= c.left_day else nan
             for i in range(n)])
        feats["age_days"].append([float(i) for i in range(n)])
        feats["volume_30d"].append(vol30)
    return Data(cases, end, market, feats)


# Feature: (low, high) range the genetic search draws thresholds from.
FEATURES = {
    "market_dd": (-0.8, 0.0),
    "market_turnover": (0.3, 3.0),
    "case_dd": (-0.95, 0.0),
    "momentum_30d": (-0.6, 0.6),
    "vs_market_z": (-3.0, 3.0),
    "price_to_ev": (0.1, 2.0),
    "days_since_left_pool": (0.0, 1500.0),
    "age_days": (0.0, 3000.0),
    "volume_30d": (0.0, 3000.0),
}
HOLD = (30, 730)


@dataclass
class Rule:
    """Buy when every enabled condition holds: feature <= threshold (op "<=") or >= threshold (op ">=")."""
    conds: dict[str, tuple[str, float]]
    hold: int

    def describe(self) -> str:
        parts = [f"{k} {op} {v:.2f}" for k, (op, v) in sorted(self.conds.items())]
        return (" and ".join(parts) or "always") + f", hold {self.hold} days"


@dataclass
class Result:
    trades: list[tuple[str, int, int, float]]     # case, entry day, exit day, net return (x)

    @property
    def n(self) -> int:
        return len(self.trades)

    def logs(self) -> list[float]:
        return [math.log(t[3]) for t in self.trades]

    def summary(self) -> dict:
        if not self.trades:
            return {"trades": 0}
        lg = sorted(self.logs())
        mean = sum(lg) / len(lg)
        return {"trades": self.n, "cases": len({t[0] for t in self.trades}),
                "quarters": len({quarter(t[1]) for t in self.trades}),
                "mean_return": math.exp(mean) - 1, "median_return": math.exp(lg[len(lg) // 2]) - 1,
                "win_rate": sum(x > 0 for x in lg) / len(lg), "worst": math.exp(lg[0]) - 1,
                "best": math.exp(lg[-1]) - 1}


def run(data: Data, rule: Rule, first: int, last: int, exit_by: int | None = None) -> Result:
    """Trades with entries in [first, last] (epoch days); with exit_by, only trades that close by then."""
    trades = []
    limit = min(data.end, exit_by if exit_by is not None else data.end)
    for k, c in enumerate(data.cases):
        i = max(0, first - c.start)
        n = len(c.price)
        while i < n and c.start + i <= last:
            entry = i + 1
            exit_ = entry + rule.hold
            if exit_ >= n or c.start + exit_ > limit:
                break
            if _signal(data, k, i, rule):
                trades.append((c.name, c.start + entry, c.start + exit_, _ret(c.price[entry], c.price[exit_])))
                i = exit_
            else:
                i += STEP
    return Result(trades)


def _signal(data: Data, k: int, i: int, rule: Rule) -> bool:
    for name, (op, thr) in rule.conds.items():
        v = data.feats[name][k][i]
        if math.isnan(v) or (v > thr if op == "<=" else v < thr):
            return False
    return True


def baseline(data: Data, hold: int, first: int, last: int, exit_by: int | None = None) -> Result:
    """Every case bought every STEP days (positions overlap), held `hold` days."""
    trades = []
    limit = min(data.end, exit_by if exit_by is not None else data.end)
    for c in data.cases:
        n = len(c.price)
        for i in range(max(0, first - c.start), n, STEP):
            entry, exit_ = i + 1, i + 1 + hold
            if c.start + i > last or exit_ >= n or c.start + exit_ > limit:
                break
            trades.append((c.name, c.start + entry, c.start + exit_, _ret(c.price[entry], c.price[exit_])))
    return Result(trades)


def fitness(res: Result, base: Result, min_quarters: int = MIN_QUARTERS) -> float:
    """t-statistic of the mean log return above the baseline's, with calendar quarters of entry as the samples.

    Trades opened in the same quarter ride the same market moves, so each quarter is one observation: its mean
    excess log return. A rule needs trades in `min_quarters` quarters and at least 4 cases to score at all."""
    if not base.n or len({t[0] for t in res.trades}) < 4:
        return -1e9
    b = sum(base.logs()) / base.n
    by_q: dict[int, list[float]] = {}
    for t in res.trades:
        by_q.setdefault(quarter(t[1]), []).append(math.log(t[3]) - b)
    if len(by_q) < min_quarters:
        return -1e9
    qs = [sum(v) / len(v) for v in by_q.values()]
    m = sum(qs) / len(qs)
    sd = max(math.sqrt(sum((x - m) ** 2 for x in qs) / (len(qs) - 1)), 0.05)
    return m / sd * math.sqrt(len(qs))


def _random_rule(rng: random.Random) -> Rule:
    conds = {}
    for name, (lo, hi) in FEATURES.items():
        if rng.random() < 0.3:
            conds[name] = (rng.choice(["<=", ">="]), rng.uniform(lo, hi))
    return Rule(conds, rng.randint(*HOLD))


def _mutate(rule: Rule, rng: random.Random) -> Rule:
    conds = dict(rule.conds)
    for name, (lo, hi) in FEATURES.items():
        if rng.random() < 0.1:              # switch the condition on or off
            if name in conds:
                del conds[name]
            else:
                conds[name] = (rng.choice(["<=", ">="]), rng.uniform(lo, hi))
        elif name in conds and rng.random() < 0.3:
            op, v = conds[name]
            if rng.random() < 0.1:
                op = "<=" if op == ">=" else ">="
            conds[name] = (op, min(hi, max(lo, v + rng.gauss(0, (hi - lo) * 0.1))))
    hold = rule.hold
    if rng.random() < 0.3:
        hold = int(min(HOLD[1], max(HOLD[0], hold + rng.gauss(0, 60))))
    return Rule(conds, hold)


def _cross(a: Rule, b: Rule, rng: random.Random) -> Rule:
    conds = {}
    for name in FEATURES:
        src = a if rng.random() < 0.5 else b
        if name in src.conds:
            conds[name] = src.conds[name]
    return Rule(conds, a.hold if rng.random() < 0.5 else b.hold)


def evolve(data: Data, first: int, split: int, pop: int = 40, gens: int = 25, seed: int = 1,
           min_quarters: int = MIN_QUARTERS, log=None) -> list[tuple[float, Rule]]:
    """Genetic search on trades opened from `first` and closed before `split`. Returns the best distinct rules."""
    rng = random.Random(seed)
    base_cache: dict[int, Result] = {}

    def score(rule: Rule) -> float:
        if rule.hold not in base_cache:
            base_cache[rule.hold] = baseline(data, rule.hold, first, split, exit_by=split)
        return fitness(run(data, rule, first, split, exit_by=split), base_cache[rule.hold], min_quarters)

    people = [_random_rule(rng) for _ in range(pop)]
    seen: dict[str, tuple[float, Rule]] = {}
    for g in range(gens):
        scored = []
        for r in people:
            key = r.describe()
            if key not in seen:
                seen[key] = (score(r), r)
            scored.append(seen[key])
        scored.sort(key=lambda x: -x[0])
        if log:
            log(f"generation {g + 1}/{gens}: best {scored[0][0]:.2f}  {scored[0][1].describe()}")

        people = [s[1] for s in scored[:2]]       # elitism
        while len(people) < pop:
            a, b = (max(rng.sample(scored, 3), key=lambda x: x[0])[1] for _ in range(2))
            people.append(_mutate(_cross(a, b, rng), rng))
    best = sorted(seen.values(), key=lambda x: -x[0])
    return [b for b in best if b[0] > -1e9][:10]


def forward_returns(data: Data, feature: str, buckets: list[float], hold: int, first: int, last: int) -> list[dict]:
    """Average net return of buying `hold` days, grouped by the value of a feature on the entry day."""
    groups: dict[int, list[float]] = {}
    for k, c in enumerate(data.cases):
        n = len(c.price)
        for i in range(max(0, first - c.start), n, STEP):
            if c.start + i > last or i + 1 + hold >= n:
                break
            v = data.feats[feature][k][i]
            if math.isnan(v):
                continue
            b = sum(v >= x for x in buckets)
            groups.setdefault(b, []).append(math.log(_ret(c.price[i + 1], c.price[i + 1 + hold])))
    out = []
    for b in sorted(groups):
        lg = groups[b]
        lo = buckets[b - 1] if b > 0 else None
        hi = buckets[b] if b < len(buckets) else None
        out.append({"from": lo, "to": hi, "entries": len(lg), "mean_return": math.exp(sum(lg) / len(lg)) - 1,
                    "win_rate": sum(x > 0 for x in lg) / len(lg)})
    return out


def drop_pool_event(data: Data, holds: list[int]) -> list[dict]:
    """Buying each case the day after it left the active drop pool."""
    out = []
    for c in data.cases:
        if c.left_day is None or not c.start <= c.left_day + 1 < c.start + len(c.price):
            continue
        i = c.left_day + 1 - c.start
        row: dict = {"case": c.name, "left": c.left_day, "price": c.price[i]}
        for h in holds:
            row[h] = _ret(c.price[i], c.price[i + h]) - 1 if i + h < len(c.price) else None
        out.append(row)
    return out
