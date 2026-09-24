"""NY-Open Liquidity-Sweep backtest for MNQ (Micro Nasdaq futures).

Replicates the rules of strategies/mnq_m5_sweep.pine bar by bar (no lookahead):

  1. Before 09:30 ET collect liquidity levels: previous RTH day high/low,
     overnight high/low, Asia (20:00-00:00) and London (02:00-05:00) high/low.
     From 08:00 on, confirmed intraday swing highs/lows are added as well.
  2. 09:30-11:00 ET: a bar trades through an untouched level  -> sweep.
  3. Within `confirm` bars a close back beyond the level AND beyond the sweep
     bar's opposite extreme (default) confirms the rejection, optionally
     leaving a fair value gap.
  4. Entry: market on the confirmation close, or limit at the OTE retracement
     of the displacement leg.  Stop beyond the sweep extreme.
  5. Protection: TP1 at 1R closes half, stop goes to breakeven; TP2 at `tp2_r`.

Conservative fill assumptions: if stop and target are touched in the same bar
the stop counts; no target can fill on the entry bar; 1 tick slippage on
market/stop fills; $0.62 commission per side and contract.

Usage:
    python backtest/sweep_backtest.py --tf 5m
    python backtest/sweep_backtest.py --tf 15m --entry ote
    python backtest/sweep_backtest.py --tf 5m --grid      # small parameter grid
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass, replace
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
TICK = 0.25
POINT_VALUE = 2.0  # MNQ: $2 per index point
COMMISSION = 0.62  # $ per side per contract


@dataclass(frozen=True)
class Params:
    tf: str = "5m"
    entry: str = "market"  # market | ote
    ote: float = 0.5  # retracement of the displacement leg for limit entries
    confirm: int = 3  # bars after the sweep to get the structure shift
    struct_lb: int = 0  # bars before the sweep that define the structure (0 = sweep bar itself)
    need_fvg: bool = False
    close_back: bool = False  # sweep bar must close back inside the level
    pending_bars: int = 6  # limit order lifetime
    min_risk: float = 10.0  # points
    max_risk: float = 150.0  # points
    tp1_r: float = 1.0
    tp2_r: float = 2.0
    be_after_tp1: bool = True
    contracts: int = 2
    max_trades: int = 2
    max_losses: int = 2
    start: time = time(9, 30)
    last_entry: time = time(11, 0)
    flat: time = time(11, 30)
    pivot: int = 2  # swing high/low strength for intraday levels
    intraday_levels: bool = True

    @classmethod
    def for_tf(cls, tf: str, **kw) -> "Params":
        if tf == "15m":
            base = dict(tf=tf, confirm=2, pending_bars=4,
                        min_risk=15.0, max_risk=225.0, flat=time(12, 0))
        else:
            base = dict(tf=tf)
        base.update(kw)
        return cls(**base)


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"mnq_{tf}.csv")
    step = {"5m": 300, "15m": 900}[tf]
    df = df[df.t % step == 0].reset_index(drop=True)  # drop the live partial bar
    df["dt"] = pd.to_datetime(df.t, unit="s", utc=True).dt.tz_convert("America/New_York")
    df["date"] = df.dt.dt.date
    df["tod"] = df.dt.dt.time
    return df


def build_levels(df: pd.DataFrame) -> dict:
    """Levels known at 09:30 for each trading date, with 'untouched' check up to 09:30."""
    out = {}
    dates = sorted(d for d in df.date.unique() if pd.Timestamp(d).weekday() < 5)
    ts = df.dt
    for i, d in enumerate(dates):
        day_open = pd.Timestamp.combine(d, time(9, 30)).tz_localize("America/New_York")
        prev = pd.Timestamp(d) - pd.Timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= pd.Timedelta(days=1)
        prev_d = prev.date()

        def win(a, b):
            return df[(ts >= a) & (ts < b)]

        tz = "America/New_York"
        rth_prev = win(pd.Timestamp.combine(prev_d, time(9, 30)).tz_localize(tz),
                       pd.Timestamp.combine(prev_d, time(16, 0)).tz_localize(tz))
        on_start = pd.Timestamp.combine(prev_d, time(18, 0)).tz_localize(tz)
        overnight = win(on_start, day_open)
        asia = win(on_start + pd.Timedelta(hours=2), on_start + pd.Timedelta(hours=6))
        london = win(pd.Timestamp.combine(d, time(2, 0)).tz_localize(tz),
                     pd.Timestamp.combine(d, time(5, 0)).tz_localize(tz))
        if overnight.empty or rth_prev.empty:
            continue
        lv = []
        for name, seg in (("PDH/PDL", rth_prev), ("ON", overnight), ("Asia", asia), ("London", london)):
            if seg.empty:
                continue
            after = win(seg.dt.iloc[-1] + pd.Timedelta(seconds=1), day_open)
            hi, lo = seg.h.max(), seg.l.min()
            if after.empty or after.h.max() < hi:
                lv.append((hi, +1, name + " high"))
            if after.empty or after.l.min() > lo:
                lv.append((lo, -1, name + " low"))
        out[d] = lv
    return out


@dataclass
class Trade:
    date: object
    side: int
    entry_time: object
    entry: float
    stop: float
    tp1: float
    tp2: float
    level: str
    exit_time: object = None
    pnl: float = 0.0
    r: float = 0.0
    result: str = ""


def run(df: pd.DataFrame, p: Params, levels: dict) -> list[Trade]:
    o, h, l, c = (df[k].to_numpy() for k in "ohlc")
    tod = df.tod.to_numpy()
    trades: list[Trade] = []
    for d, day_levels in levels.items():
        idx = np.flatnonzero((df.date == d).to_numpy())
        if idx.size == 0:
            continue
        sess = [i for i in idx if time(8, 0) <= tod[i] <= p.flat]
        if not sess:
            continue
        active = [list(x) for x in day_levels]  # [price, side, name]
        n_tr = n_loss = 0
        armed = None  # dict for an armed sweep
        pending = None
        pos = None
        for i in sess:
            t = tod[i]
            # --- intraday swing levels (confirmed `pivot` bars later) ---
            if p.intraday_levels and i - 2 * p.pivot >= 0:
                k = i - p.pivot
                if tod[k] >= time(8, 0) and df.date.iat[k] == d:
                    lo_r, hi_r = k - p.pivot, k + p.pivot + 1
                    if h[k] == h[lo_r:hi_r].max() and h[k] > h[k + 1:hi_r].max():
                        if h[k + 1:i + 1].max() < h[k]:
                            active.append([h[k], +1, "swing high"])
                    if l[k] == l[lo_r:hi_r].min() and l[k] < l[k + 1:hi_r].min():
                        if l[k + 1:i + 1].min() > l[k]:
                            active.append([l[k], -1, "swing low"])

            # --- levels traded through this bar are used up (every bar, any state) ---
            swept_hi = [lv for lv in active if lv[1] > 0 and h[i] > lv[0] + TICK]
            swept_lo = [lv for lv in active if lv[1] < 0 and l[i] < lv[0] - TICK]
            active = [lv for lv in active if lv not in swept_hi and lv not in swept_lo]

            # --- manage open position ---
            if pos is not None:
                tr, qty, stop, tp1_done, entry_bar = pos
                s = tr.side
                closed = False
                if i > entry_bar:
                    hit_stop = (h[i] >= stop) if s < 0 else (l[i] <= stop)
                    hit_tp1 = (l[i] <= tr.tp1) if s < 0 else (h[i] >= tr.tp1)
                    hit_tp2 = (l[i] <= tr.tp2) if s < 0 else (h[i] >= tr.tp2)
                    if hit_stop:
                        fill = stop - s * TICK
                        tr.pnl += qty * (fill - tr.entry) * s * POINT_VALUE
                        tr.result += "SL" if not tp1_done else "BE"
                        closed = True
                    else:
                        if not tp1_done and hit_tp1:
                            q1 = qty // 2
                            tr.pnl += q1 * abs(tr.tp1 - tr.entry) * POINT_VALUE
                            qty -= q1
                            tp1_done = True
                            tr.result = "TP1+"
                            if p.be_after_tp1:
                                stop = tr.entry
                        if tp1_done and hit_tp2:
                            tr.pnl += qty * abs(tr.tp2 - tr.entry) * POINT_VALUE
                            tr.result += "TP2"
                            closed = True
                if not closed and t >= p.flat:
                    tr.pnl += qty * (c[i] - s * TICK - tr.entry) * s * POINT_VALUE
                    tr.result += "TIME"
                    closed = True
                if closed:
                    tr.pnl -= 2 * COMMISSION * p.contracts
                    tr.exit_time = df.dt.iat[i]
                    risk_usd = abs(tr.entry - tr.stop) * POINT_VALUE * p.contracts
                    tr.r = tr.pnl / risk_usd
                    trades.append(tr)
                    n_tr += 1
                    n_loss += tr.pnl < 0
                    pos = None
                else:
                    pos = (tr, qty, stop, tp1_done, entry_bar)
                continue

            # --- pending limit order ---
            if pending is not None:
                tr, expiry = pending
                s = tr.side
                touched = (h[i] >= tr.entry) if s < 0 else (l[i] <= tr.entry)
                ran_away = (l[i] <= tr.tp1) if s < 0 else (h[i] >= tr.tp1)
                if touched:
                    tr.entry_time = df.dt.iat[i]
                    pos = (tr, p.contracts, tr.stop, False, i)
                    pending = None
                    # conservative: stop inside the fill bar counts
                    if (h[i] >= tr.stop) if s < 0 else (l[i] <= tr.stop):
                        tr.pnl = -p.contracts * (abs(tr.stop - tr.entry) + TICK) * POINT_VALUE
                        tr.pnl -= 2 * COMMISSION * p.contracts
                        tr.result = "SL"
                        tr.exit_time = df.dt.iat[i]
                        tr.r = tr.pnl / (abs(tr.entry - tr.stop) * POINT_VALUE * p.contracts)
                        trades.append(tr)
                        n_tr += 1
                        n_loss += 1
                        pos = None
                    continue
                if ran_away or i >= expiry or t >= p.flat:
                    pending = None
                else:
                    continue

            if t < p.start or t > p.last_entry or n_tr >= p.max_trades or n_loss >= p.max_losses:
                armed = None
                continue

            # --- detect new sweeps ---
            new = None
            if swept_hi:
                top = max(swept_hi, key=lambda x: x[0])
                if c[i] < top[0] or not p.close_back:
                    new = dict(side=-1, ext=h[i], bar=i, level=top[2], px=top[0],
                               struct=l[max(i - p.struct_lb, 0):i].min() if p.struct_lb else l[i])
            if swept_lo:
                bot = min(swept_lo, key=lambda x: x[0])
                if c[i] > bot[0] or not p.close_back:
                    new = dict(side=+1, ext=l[i], bar=i, level=bot[2], px=bot[0],
                               struct=h[max(i - p.struct_lb, 0):i].max() if p.struct_lb else h[i])
            if new is not None:
                armed = new

            # --- structure shift confirmation ---
            if armed is not None:
                s = armed["side"]
                armed["ext"] = max(armed["ext"], h[i]) if s < 0 else min(armed["ext"], l[i])
                if i - armed["bar"] > p.confirm:
                    armed = None
                    continue
                back = min(armed["struct"], armed["px"]) if s < 0 else max(armed["struct"], armed["px"])
                shifted = c[i] < back if s < 0 else c[i] > back
                if not shifted:
                    continue
                j0 = armed["bar"]
                if p.need_fvg:
                    has = any((h[k] < l[k - 2]) if s < 0 else (l[k] > h[k - 2])
                              for k in range(j0 + 1, i + 1))
                    if not has:
                        continue
                ext = armed["ext"]
                stop = ext + TICK * 2 if s < 0 else ext - TICK * 2
                if p.entry == "market":
                    entry = c[i] - s * TICK  # slippage against us
                else:
                    leg_end = l[j0:i + 1].min() if s < 0 else h[j0:i + 1].max()
                    entry = leg_end + (ext - leg_end) * p.ote
                    entry = round(entry / TICK) * TICK
                risk = abs(stop - entry)
                if risk > p.max_risk:
                    armed = None
                    continue
                if risk < p.min_risk:
                    stop = entry - s * p.min_risk
                    risk = p.min_risk
                tr = Trade(d, s, df.dt.iat[i], entry, stop,
                           entry + s * p.tp1_r * risk, entry + s * p.tp2_r * risk, armed["level"])
                armed = None
                if p.entry == "market":
                    pos = (tr, p.contracts, stop, False, i)
                else:
                    pending = (tr, i + p.pending_bars)
    return trades


def stats(trades: list[Trade], label: str) -> dict:
    if not trades:
        return {"set": label, "trades": 0}
    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r for t in trades])
    eq = pnl.cumsum()
    dd = (np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max()
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {
        "set": label, "trades": len(trades), "win%": round(100 * (pnl > 0).mean(), 1),
        "PF": round(gp / gl, 2) if gl else float("inf"), "avgR": round(r.mean(), 3),
        "net$": round(pnl.sum(), 0), "maxDD$": round(dd, 0),
    }


def split(trades, dates):
    cut = dates[int(len(dates) * 0.6)]
    return [t for t in trades if t.date < cut], [t for t in trades if t.date >= cut], cut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5m", choices=["5m", "15m"])
    ap.add_argument("--entry", default="market", choices=["market", "ote"])
    ap.add_argument("--ote", type=float, default=0.5)
    ap.add_argument("--tp2", type=float, default=2.0)
    ap.add_argument("--fvg", action="store_true")
    ap.add_argument("--no-intraday", action="store_true")
    ap.add_argument("--max-risk", type=float)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--trades", action="store_true", help="print trade list")
    a = ap.parse_args()

    df = load(a.tf)
    levels = build_levels(df)
    dates = sorted(levels)
    print(f"MNQ {a.tf}: {dates[0]} .. {dates[-1]}  ({len(dates)} trading days)")

    if a.grid:
        rows = []
        for entry, tp2, fvg, slb, cb, mr in itertools.product(
                ["market", "ote"], [1.5, 2.0, 3.0], [False, True], [0, 3], [False, True],
                [100.0, 150.0] if a.tf == "5m" else [150.0, 225.0]):
            p = Params.for_tf(a.tf, entry=entry, tp2_r=tp2, need_fvg=fvg, struct_lb=slb,
                              close_back=cb, max_risk=mr)
            tr = run(df, p, levels)
            ins, oos, cut = split(tr, dates)
            s_in, s_out = stats(ins, "IS"), stats(oos, "OOS")
            rows.append({"entry": entry, "tp2R": tp2, "fvg": fvg, "struct": slb, "closeBack": cb, "maxRisk": mr,
                         **{f"IS_{k}": v for k, v in s_in.items() if k != "set"},
                         **{f"OOS_{k}": v for k, v in s_out.items() if k != "set"}})
        pd.set_option("display.width", 250)
        print(pd.DataFrame(rows).to_string(index=False))
        return

    p = Params.for_tf(a.tf, entry=a.entry, ote=a.ote, tp2_r=a.tp2, need_fvg=a.fvg,
                      intraday_levels=not a.no_intraday,
                      **({"max_risk": a.max_risk} if a.max_risk else {}))
    tr = run(df, p, levels)
    ins, oos, cut = split(tr, dates)
    print(f"in-sample < {cut} <= out-of-sample")
    print(pd.DataFrame([stats(ins, "in-sample"), stats(oos, "out-of-sample"), stats(tr, "all")]).to_string(index=False))
    if a.trades:
        out = pd.DataFrame([t.__dict__ for t in tr])
        print(out[["entry_time", "side", "level", "entry", "stop", "tp1", "tp2", "result", "pnl", "r"]].to_string(index=False))


if __name__ == "__main__":
    main()
