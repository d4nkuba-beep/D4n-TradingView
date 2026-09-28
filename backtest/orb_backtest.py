"""Opening-range breakout (ORB) backtest for MNQ, same costs and fill rules as
sweep_backtest.py.

  - Opening range = high/low of the first `or_min` minutes after 09:30 ET.
  - Entry: first bar that closes beyond the range (until `last_entry`),
    optional VWAP / EMA trend filter, market on that close.
  - Stop: opposite side of the range ("far") or its midpoint ("mid").
  - TP1 at 1R closes half, stop to breakeven, TP2 at `tp2_r`; flat at `flat`.
  - One trade per day.

Usage:
    python backtest/orb_backtest.py --tf 5m
    python backtest/orb_backtest.py --tf 5m --grid
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from datetime import time

import numpy as np
import pandas as pd

from sweep_backtest import (COMMISSION, POINT_VALUE, TICK, Trade, apply_events, bar_events, gate, load,
                            split, stats)


@dataclass(frozen=True)
class OrbParams:
    or_min: int = 5
    stop: str = "mid"  # far | mid
    trend: str = "ema5"  # none | vwap | ema5 | ema1h | vwap+ema1h
    tp1_r: float = 0.5
    tp2_r: float = 2.0
    be_after_tp1: bool = True
    contracts: int = 2
    last_entry: time = time(11, 0)
    flat: time = time(11, 30)
    max_risk: float = 100.0
    direction: str = "both"
    ema_fast: int = 20
    ema_slow: int = 50
    atr_len: int = 14
    min_atr: float = 0.0
    er_len: int = 10
    er_min: float = 0.0
    intrabar: str = "stop_first"


def trend_ok(f: str, s: int, row) -> bool:
    ok = True
    if "vwap" in f:
        ok &= (row.c - row.vwap) * s > 0
    # "ema5": EMA lengths are applied in gate()
    if "ema1h" in f:
        ok &= (row.c - row.ema_h1) * s > 0
    return bool(ok)


def manage(day: pd.DataFrame, k: int, tr: Trade, p: OrbParams) -> Trade:
    """Walk bars after the entry bar k; conservative: stop first on ambiguous bars."""
    s, qty, stop, tp1_done = tr.side, p.contracts, tr.stop, False
    for j in range(k + 1, len(day)):
        b = day.iloc[j]
        qty, stop, tp1_done, closed = apply_events(
            tr, qty, stop, tp1_done, p,
            bar_events(s, b.o, b.h, b.l, stop, tr.tp1, tr.tp2, tp1_done, p.intrabar))
        if closed:
            tr.exit_time = b["dt"]
            break
        if b.tod >= p.flat or j == len(day) - 1:
            tr.pnl += qty * (b.c - s * TICK - tr.entry) * s * POINT_VALUE
            tr.result += "TIME"
            tr.exit_time = b["dt"]
            break
    tr.pnl -= 2 * COMMISSION * p.contracts
    tr.r = tr.pnl / (abs(tr.entry - tr.stop) * POINT_VALUE * p.contracts)
    return tr


def run(df: pd.DataFrame, p: OrbParams, step_min: int) -> list[Trade]:
    trades = []
    or_end = (pd.Timestamp("2000-01-01 09:30") + pd.Timedelta(minutes=p.or_min)).time()
    for d, day in df[(df.tod >= time(9, 30)) & (df.tod <= p.flat)].groupby("date"):
        if pd.Timestamp(d).weekday() >= 5:
            continue
        day = day.reset_index()  # column "index" = row in df (for the shared filters)
        rng = day[day.tod < or_end]
        if len(rng) < p.or_min // step_min:
            continue
        hi, lo = rng.h.max(), rng.l.min()
        for k in range(len(rng), len(day)):
            b = day.iloc[k]
            if b.tod > p.last_entry:
                break
            s = 1 if b.c > hi else -1 if b.c < lo else 0
            if s == 0:
                continue
            if not trend_ok(p.trend, s, b) or not gate(df, int(b["index"]), s, p):
                break  # first breakout decides the day
            entry = b.c + s * TICK
            stop = (lo if s > 0 else hi) if p.stop == "far" else (hi + lo) / 2
            stop -= s * 2 * TICK
            risk = abs(entry - stop)
            if risk > p.max_risk or risk <= 0:
                break
            tr = Trade(d, s, b["dt"], entry, stop, entry + s * p.tp1_r * risk,
                       entry + s * p.tp2_r * risk, f"ORB{p.or_min}")
            trades.append(manage(day, k, tr, p))
            break
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5m", choices=["5m", "15m"])
    ap.add_argument("--or-min", type=int, default=5)
    ap.add_argument("--stop", default="mid", choices=["far", "mid"])
    ap.add_argument("--trend", default="ema5")
    ap.add_argument("--tp2", type=float, default=2.0)
    ap.add_argument("--flat", default="11:30")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--trades", action="store_true")
    a = ap.parse_args()
    step = int(a.tf[:-1])
    df = load(a.tf)
    dates = sorted(d for d in df.date.unique() if pd.Timestamp(d).weekday() < 5)[1:]

    if a.grid:
        rows = []
        for orm, st, tf_, tp2, fl in itertools.product(
                [15, 30] if a.tf == "15m" else [5, 15, 30], ["far", "mid"],
                ["none", "vwap", "ema5", "ema1h", "vwap+ema1h"], [1.5, 2.0, 3.0],
                [time(11, 30), time(15, 45)]):
            p = OrbParams(or_min=orm, stop=st, trend=tf_, tp2_r=tp2, flat=fl)
            tr = run(df, p, step)
            ins, oos, _ = split(tr, dates)
            A, B, C = stats(ins, ""), stats(oos, ""), stats(tr, "")
            rows.append(dict(orm=orm, stop=st, trend=tf_, tp2=tp2, flat=str(fl)[:5], n=C.get("trades", 0),
                             PF=C.get("PF"), net=C.get("net$"), IS=A.get("net$"), OOS=B.get("net$"),
                             OOS_PF=B.get("PF"), dd=C.get("maxDD$")))
        d = pd.DataFrame(rows)
        pd.set_option("display.width", 200)
        print(d.groupby("trend")[["net", "IS", "OOS"]].median())
        print(d.sort_values("net", ascending=False).head(20).to_string(index=False))
        print("share profitable in both halves:", round(((d.IS > 0) & (d.OOS > 0)).mean(), 2))
        return

    hh, mm = map(int, a.flat.split(":"))
    p = OrbParams(or_min=a.or_min, stop=a.stop, trend=a.trend, tp2_r=a.tp2, flat=time(hh, mm))
    tr = run(df, p, step)
    ins, oos, cut = split(tr, dates)
    print(f"MNQ {a.tf} ORB{p.or_min} stop={p.stop} trend={p.trend}  in-sample < {cut} <= out-of-sample")
    print(pd.DataFrame([stats(ins, "in-sample"), stats(oos, "out-of-sample"), stats(tr, "all")]).to_string(index=False))
    if a.trades:
        out = pd.DataFrame([t.__dict__ for t in tr])
        print(out[["entry_time", "side", "entry", "stop", "tp1", "tp2", "result", "pnl", "r"]].to_string(index=False))


if __name__ == "__main__":
    main()
