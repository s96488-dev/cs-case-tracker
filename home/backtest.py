"""Backtest report on the home database: python -m home.backtest [--split 2022-01-01] [--pop 60] [--gens 40]

Writes backtest_report.md (and backtest_trades.csv with the test-period trades of the best rule) next to
the repository. See common/backtest.py for how trades and the genetic search work.
"""
import argparse
import csv
import logging
import math
import time
from datetime import UTC, date, datetime

from common import backtest as bt
from common import drop_pool

from .db import ensure_database, open_pool, pool

log = logging.getLogger("backtest")


def _day(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) // bt.DAY


def _date(day: int) -> str:
    return datetime.fromtimestamp(day * bt.DAY, UTC).date().isoformat()


def load() -> list[bt.Case]:
    with pool.connection() as conn:
        rows = conn.execute(
            """SELECT i.market_hash_name AS name, (s.ts AT TIME ZONE 'UTC')::date AS day,
                      sum(s.median_cents::bigint * s.volume)::float / sum(s.volume) / 100 AS price,
                      sum(s.volume) AS volume
               FROM sales_history s JOIN items i ON i.id = s.item_id
               WHERE i.item_type = 'case' AND s.median_cents IS NOT NULL AND s.volume > 0
               GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
        evs = conn.execute("""SELECT i.market_hash_name AS name, e.day, e.ev_cents / 100.0 AS ev
                              FROM case_ev e JOIN items i ON i.id = e.item_id""").fetchall()
    daily: dict[str, list[tuple[int, float, float]]] = {}
    for r in rows:
        daily.setdefault(r["name"], []).append((_day(r["day"]), float(r["price"]), float(r["volume"])))
    ev: dict[str, dict[int, float]] = {}
    for r in evs:
        ev.setdefault(r["name"], {})[_day(r["day"])] = float(r["ev"])
    left = {n: _day(date.fromisoformat(lft)) for n, (_, lft) in drop_pool.CASES.items() if lft}
    return bt.build_cases(daily, ev, left)


def pct(x) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.1f}%"


def summary_row(label: str, s: dict) -> str:
    if not s.get("trades"):
        return f"| {label} | 0 | | | | | |"
    return (f"| {label} | {s['trades']} | {s['cases']} | {pct(s['mean_return'])} | {pct(s['median_return'])} "
            f"| {s['win_rate'] * 100:.0f}% | {pct(s['worst'])} |")


SUMMARY_HEAD = ("| | trades | cases | mean | median | win rate | worst |\n"
                "|---|---|---|---|---|---|---|")

BUCKETS: dict[str, list[float]] = {
    "market_dd": [-0.5, -0.4, -0.3, -0.2, -0.1],
    "case_dd": [-0.7, -0.5, -0.3, -0.15],
    "vs_market_z": [-2, -1, 0, 1, 2],
    "price_to_ev": [0.3, 0.5, 0.7, 1.0],
    "momentum_30d": [-0.2, -0.05, 0.05, 0.2],
    "market_turnover": [0.6, 0.8, 1.0, 1.25, 1.6],
}


def report(data: bt.Data, split: int, pop: int, gens: int, seed: int) -> tuple[str, list]:
    first = min(c.start for c in data.cases)
    out = ["# Backtest of case-buying signals", "",
           f"Data: {len(data.cases)} cases, {_date(first)} to {_date(data.end)}. "
           f"Training period: trades that close before {_date(split)}; test period: trades opened after it.",
           f"Every trade pays the Steam fee: the seller gets price / {bt.FEE}. Mean returns are geometric "
           "(the average of log returns), so one huge winner does not dominate.", ""]

    out += ["## Baseline: buy any case at random", "",
            "Buying every case every week. A signal is useful only if it does better than this.", "",
            SUMMARY_HEAD]
    for hold in (90, 180, 365, 730):
        out.append(summary_row(f"hold {hold} d, train", bt.baseline(data, hold, first, split, split).summary()))
        out.append(summary_row(f"hold {hold} d, test", bt.baseline(data, hold, split, data.end).summary()))
    out.append("")

    out += ["## Return after 365 days by the situation on the entry day", "",
            "All entries over the whole history, grouped by one feature at a time.", ""]
    for feat, buckets in BUCKETS.items():
        out += [f"**{feat}**", "", "| from | to | entries | mean | win rate |", "|---|---|---|---|---|"]
        for r in bt.forward_returns(data, feat, buckets, 365, first, data.end):
            out.append(f"| {'' if r['from'] is None else r['from']} | {'' if r['to'] is None else r['to']} "
                       f"| {r['entries']} | {pct(r['mean_return'])} | {r['win_rate'] * 100:.0f}% |")
        out.append("")

    out += ["## Buying the day after a case left the active drop pool", "",
            "| case | left | price | 180 d | 365 d | 730 d |", "|---|---|---|---|---|---|"]
    for r in sorted(bt.drop_pool_event(data, [180, 365, 730]), key=lambda r: r["left"]):
        out.append(f"| {r['case']} | {_date(r['left'])} | ${r['price']:.2f} | {pct(r[180])} | {pct(r[365])} "
                   f"| {pct(r[730])} |")
    out.append("")

    out += ["## Market index by calendar month", "",
            "Average change of the market index within each month, over all years.", "",
            "| month | years | mean change |", "|---|---|---|"]
    months: dict[int, list[float]] = {}
    days = sorted(data.market)
    by_month: dict[tuple[int, int], tuple[float, float]] = {}
    for d in days:
        dt = datetime.fromtimestamp(d * bt.DAY, UTC)
        key = (dt.year, dt.month)
        lo, _ = by_month.get(key, (data.market[d], 0.0))
        by_month[key] = (lo, data.market[d])
    for (_, m), (a, b) in by_month.items():
        months.setdefault(m, []).append(math.log(b / a))
    for m in sorted(months):
        v = months[m]
        out.append(f"| {date(2000, m, 1):%b} | {len(v)} | {pct(math.exp(sum(v) / len(v)) - 1)} |")
    out.append("")

    log.info("genetic search: %d rules x %d generations", pop, gens)
    t0 = time.time()
    best = bt.evolve(data, first, split, pop=pop, gens=gens, seed=seed, log=log.info)
    out += ["## Genetic search", "",
            f"{pop} rules x {gens} generations, {time.time() - t0:.0f} s. Fitness: how far the mean log return "
            "beats the baseline with the same holding period, divided by the spread of returns (a t-statistic), "
            "on the training period only. The test columns are the honest check: the search never saw them.", ""]
    trades: list = []
    shown: list[tuple[float, bt.Rule, dict]] = []
    for score, rule in best:         # rules with an extra condition that changes nothing are shown once
        train = bt.run(data, rule, first, split, split).summary()
        if all(train != s for _, _, s in shown):
            shown.append((score, rule, train))
    for rank, (score, rule, train) in enumerate(shown[:5], 1):
        test = bt.run(data, rule, split, data.end)
        base = bt.baseline(data, rule.hold, split, data.end).summary()
        out += [f"### {rank}. {rule.describe()}", "", f"Fitness on training: {score:.2f}", "", SUMMARY_HEAD,
                summary_row("train", train), summary_row("test", test.summary()),
                summary_row("test baseline", base), ""]
        if rank == 1:
            trades = test.trades
    if not best:
        out += ["No rule made enough trades. Try a longer history or an earlier --split.", ""]
    out += ["## How to read this", "",
            "- A rule is worth something only if its **test** mean beats the **test baseline** with the same "
            "holding period, with a decent number of trades over several cases.",
            "- The genetic search will always find something that looks great on training data. If the test "
            "result is much worse than training, the rule is fitted to noise.",
            "- Trades of different cases at the same time are not independent: a market-wide rally lifts "
            "them all, so 100 trades in one year are worth much less than 100 trades spread over ten.", ""]
    return "\n".join(out), trades


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="2022-01-01", help="start of the test period, YYYY-MM-DD")
    p.add_argument("--pop", type=int, default=60)
    p.add_argument("--gens", type=int, default=40)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="backtest_report.md")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ensure_database()
    open_pool()
    try:
        cases = load()
    finally:
        pool.close()
    log.info("loaded %d cases, computing features", len(cases))
    data = bt.prepare(cases)
    text, trades = report(data, _day(date.fromisoformat(args.split)), args.pop, args.gens, args.seed)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    with open(args.out.rsplit(".", 1)[0].replace("report", "trades") + ".csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case", "entry", "exit", "net_return"])
        for name, a, b, r in trades:
            w.writerow([name, _date(a), _date(b), f"{r - 1:.4f}"])
    log.info("report written to %s", args.out)


if __name__ == "__main__":
    main()
