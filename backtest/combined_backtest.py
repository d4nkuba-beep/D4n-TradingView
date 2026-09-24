"""Sweep + ORB5 combined, as the Pine strategy trades them: first signal wins,
one position at a time, max 2 trades per day, both with the M5 EMA20/50 trend filter.

Usage:
    python backtest/combined_backtest.py [--trades]
"""

import argparse

import numpy as np
import pandas as pd

import orb_backtest as ob
import sweep_backtest as sb


def combine(*sets, max_per_day=2):
    out, busy, cnt = [], None, {}
    for t in sorted((t for s in sets for t in s), key=lambda t: t.entry_time):
        if busy is not None and t.entry_time <= busy:
            continue
        if cnt.get(t.date, 0) >= max_per_day:
            continue
        out.append(t)
        busy = t.exit_time
        cnt[t.date] = cnt.get(t.date, 0) + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", action="store_true")
    a = ap.parse_args()
    df = sb.load("5m")
    levels = sb.build_levels(df)
    dates = sorted(levels)
    tr = combine(sb.run(df, sb.Params.for_tf("5m"), levels), ob.run(df, ob.OrbParams(), 5))
    ins, oos, cut = sb.split(tr, dates)
    print(f"MNQ 5m sweep+ORB5, EMA20/50 filter: {dates[0]} .. {dates[-1]}, in-sample < {cut} <= out-of-sample")
    print(pd.DataFrame([sb.stats(ins, "in-sample"), sb.stats(oos, "out-of-sample"), sb.stats(tr, "all")]).to_string(index=False))
    blocks = np.array_split(np.array(dates), 4)
    print("net $ per quarter of the period:", [round(sum(t.pnl for t in tr if b[0] <= t.date <= b[-1])) for b in blocks])
    r = np.array([t.r for t in tr])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(r, len(r)).mean() for _ in range(10000)])
    print(f"bootstrap P(mean R > 0) = {(boot > 0).mean():.2f}")
    if a.trades:
        out = pd.DataFrame([t.__dict__ for t in tr])
        print(out[["entry_time", "side", "level", "entry", "stop", "tp1", "tp2", "result", "pnl", "r"]].to_string(index=False))


if __name__ == "__main__":
    main()
