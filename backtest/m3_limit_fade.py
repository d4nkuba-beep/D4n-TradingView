"""NQ M3 choppy-market limit fade (long only), data from the TradingView MCP
(CME_MINI:NQ1!, backtest/data/nq_3m.csv and nq_1m.csv).

Rules (defaults):
  1. NQ 3-minute candles, signals 09:00-11:00 CT, long only, one order or position at a time.
  2. Choppy filter: efficiency ratio of the last 15 closes <= 0.35
     ER = |close - close[14]| / sum(|close - close[1]|, 14).
  3. At the candle close rest a buy limit at close - 1.0 x ATR(14).
  4. Fill only if price trades 1 tick through the limit; cancel after 9 min.
  5. Target: middle of the signal candle.  Stop: 1.5 x ATR below the limit.
  6. Time stop 15 min after the fill (market), flat at 11:00 CT.
  7. 1 tick slippage on stops and market exits. Inside each bar the losing move
     comes first (long: open -> low -> high -> close), so a bar touching stop and
     target is a loss, and by default no target fills on the fill bar.
     The target limit also needs a 1-tick trade-through.

`--res 1m` walks the fills and exits on the 1-minute bars (only the last days
are available), signals still come from the 3-minute candles.

Usage:
    python backtest/m3_limit_fade.py                 # default rules
    python backtest/m3_limit_fade.py --trades        # plus trade list
    python backtest/m3_limit_fade.py --grid          # parameter grid
    python backtest/m3_limit_fade.py --sens          # one parameter at a time
    python backtest/m3_limit_fade.py --plot          # chart per trade day -> backtest/charts/nq_m3_*.png
"""

from __future__ import annotations

import argparse
import itertools
import math
from dataclasses import dataclass, replace
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
TZ = "America/Chicago"
TICK = 0.25


@dataclass(frozen=True)
class P:
    er_len: int = 15  # closes in the efficiency ratio
    er_max: float = 0.35  # 1.0 = filter off
    atr_len: int = 14
    entry_atr: float = 1.0  # limit = close - entry_atr * ATR
    stop_atr: float = 1.5  # stop = limit - stop_atr * ATR
    target: float = 0.5  # 0.5 = middle of the signal candle (0 = low, 1 = high)
    cancel_min: int = 9
    time_stop_min: int = 15  # 0 = off
    fill_through: int = 1  # ticks the price must trade through a limit
    fill_bar_target: bool = False  # allow the target on the fill bar (low first, then high)
    side: str = "long"  # long | short | both
    trend: str = "none"  # none | ema (EMA20 > EMA50 for longs)
    min_atr: float = 0.0  # skip signals with ATR below this (points)
    start: time = time(9, 0)
    end: time = time(11, 0)  # last signal close < end, flat at end
    max_trades: int = 99  # per day
    point_value: float = 20.0  # NQ
    commission: float = 2.25  # $ per side per contract
    contracts: int = 1


@dataclass
class Trade:
    date: object
    side: int
    signal_time: object
    entry_time: object
    entry: float
    stop: float
    target: float
    exit_time: object = None
    exit: float = 0.0
    result: str = ""
    pnl: float = 0.0
    r: float = 0.0


def load(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{name}.csv").sort_values("t").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df.t, unit="s", utc=True).dt.tz_convert(TZ)
    df["date"] = df.dt.dt.date
    df["tod"] = df.dt.dt.time
    return df


def indicators(df: pd.DataFrame, er_len: int, atr_len: int) -> None:
    c = df.c
    df["er"] = (c - c.shift(er_len - 1)).abs() / c.diff().abs().rolling(er_len - 1).sum()
    tr = pd.concat([df.h - df.l, (df.h - c.shift()).abs(), (df.l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / atr_len, adjust=False).mean()  # Wilder, like ta.atr
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()


def rtick(x: float, how: str) -> float:
    f = {"down": math.floor, "up": math.ceil, "near": round}[how]
    return f(x / TICK + 1e-9 if how == "down" else x / TICK - 1e-9 if how == "up" else x / TICK) * TICK


class Market:
    """Signal bars (3m) plus the bars used to walk fills and exits (3m or 1m)."""

    def __init__(self, m3: pd.DataFrame, path: pd.DataFrame, step: int):
        self.m3, self.step = m3, step
        self.pt = path.t.to_numpy()
        self.po, self.ph, self.pl, self.pc = (path[k].to_numpy() for k in "ohlc")
        self.ptod = path.tod.to_numpy()
        self.pdate = path.date.to_numpy()
        self.pdt = path.dt.to_numpy()
        self.cache = {}
        self.dates = None  # restrict signals to these dates

    def ind(self, p: P) -> dict:
        key = (p.er_len, p.atr_len)
        if key not in self.cache:
            d = self.m3.copy()
            indicators(d, p.er_len, p.atr_len)
            self.cache[key] = {k: d[k].to_numpy() for k in ("t", "o", "h", "l", "c", "er", "atr", "ema20", "ema50")}
            self.cache[key]["tod_close"] = (d.dt + pd.Timedelta(minutes=3)).dt.time.to_numpy()
            self.cache[key]["date"] = d.date.to_numpy()
        return self.cache[key]


def run(mk: Market, p: P, cancelled: list | None = None) -> list[Trade]:
    a = mk.ind(p)
    dates = mk.dates
    tick = TICK
    trades: list[Trade] = []
    busy_until = -1  # unix time until which an order or position blocks new signals
    per_day: dict = {}
    n = len(a["t"])
    for i in range(max(p.er_len, p.atr_len) + 50, n):
        tc = a["tod_close"][i]
        d = a["date"][i]
        if dates is not None and d not in dates:
            continue
        if not (p.start < tc < p.end) or a["t"][i] + 180 < busy_until:
            continue
        if per_day.get(d, 0) >= p.max_trades:
            continue
        er, atr = a["er"][i], a["atr"][i]
        if not (er <= p.er_max) or atr < p.min_atr or np.isnan(atr):
            continue
        sides = {"long": [1], "short": [-1], "both": [1, -1]}[p.side]
        if p.trend == "ema":
            sides = [s for s in sides if (a["ema20"][i] - a["ema50"][i]) * s > 0]
        if not sides:
            continue
        s = sides[0] if len(sides) == 1 else (1 if a["c"][i] <= (a["h"][i] + a["l"][i]) / 2 else -1)
        lim = rtick(a["c"][i] - s * p.entry_atr * atr, "down" if s > 0 else "up")
        tgt = rtick(a["l"][i] + (a["h"][i] - a["l"][i]) * (p.target if s > 0 else 1 - p.target), "near")
        stop = rtick(lim - s * p.stop_atr * atr, "down" if s > 0 else "up")
        if (tgt - lim) * s <= tick:
            continue
        t_close = a["t"][i] + 180
        tr = simulate(mk, p, s, t_close, lim, stop, tgt)
        if tr is None:
            if cancelled is not None:
                cancelled.append((t_close, lim))
            busy_until = t_close + p.cancel_min * 60
            continue
        tr.signal_time = pd.Timestamp(t_close, unit="s", tz="UTC").tz_convert(TZ)
        trades.append(tr)
        per_day[d] = per_day.get(d, 0) + 1
        busy_until = int(tr.exit_time.timestamp())
    return trades


def simulate(mk: Market, p: P, s: int, t0: int, lim: float, stop: float, tgt: float):
    """Walk path bars from t0. Returns a Trade, or None if the order was cancelled."""
    pt, po, ph, pl = mk.pt, mk.po, mk.ph, mk.pl
    j = int(np.searchsorted(pt, t0))
    if j >= len(pt) or pt[j] - t0 > 3600:
        return None
    day = mk.pdate[j]
    th = p.fill_through * TICK
    # --- entry ---
    fill_j, entry = None, None
    while j < len(pt) and pt[j] < t0 + p.cancel_min * 60 and mk.pdate[j] == day and mk.ptod[j] < p.end:
        if (pl[j] <= lim - th) if s > 0 else (ph[j] >= lim + th):
            fill_j = j
            entry = min(po[j], lim) if s > 0 else max(po[j], lim)
            break
        j += 1
    if fill_j is None:
        return None
    t_fill = pt[fill_j]
    tr = Trade(day, s, None, pd.Timestamp(mk.pdt[fill_j]), entry, stop, tgt)
    # --- exits: losing move first inside each bar ---
    j = fill_j
    while True:
        o, h, l = po[j], ph[j], pl[j]
        first = j == fill_j
        if not first:
            if mk.pdate[j] != day or mk.ptod[j] >= p.end:
                tr.exit, tr.result = o - s * TICK, "FLAT"
                break
            if p.time_stop_min and pt[j] >= t_fill + p.time_stop_min * 60:
                tr.exit, tr.result = o - s * TICK, "TIME"
                break
        if (l <= stop) if s > 0 else (h >= stop):
            px = stop if first else (min(o, stop) if s > 0 else max(o, stop))
            tr.exit, tr.result = px - s * TICK, "SL"
            break
        if (not first or p.fill_bar_target) and ((h >= tgt + p.fill_through * TICK) if s > 0
                                                  else (l <= tgt - p.fill_through * TICK)):
            tr.exit, tr.result = (max(o, tgt) if s > 0 else min(o, tgt)) if not first else tgt, "TP"
            break
        j += 1
        if j >= len(pt):
            j -= 1
            tr.exit, tr.result = mk.pc[j] - s * TICK, "END"
            break
    tr.exit_time = pd.Timestamp(mk.pdt[j]) + (pd.Timedelta(0) if tr.result in ("TIME", "FLAT") else pd.Timedelta(seconds=mk.step))
    pts = (tr.exit - tr.entry) * s
    tr.pnl = p.contracts * (pts * p.point_value - 2 * p.commission)
    tr.r = tr.pnl / (p.contracts * abs(tr.entry - tr.stop) * p.point_value)
    return tr


def stats(trades: list[Trade], label: str = "") -> dict:
    if not trades:
        return {"set": label, "trades": 0}
    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r for t in trades])
    eq = np.concatenate([[0], pnl.cumsum()])
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    res = pd.Series([t.result for t in trades]).value_counts()
    return {
        "set": label, "trades": len(trades), "win%": round(100 * (pnl > 0).mean(), 1),
        "PF": round(gp / gl, 2) if gl else float("inf"), "avgR": round(r.mean(), 3),
        "avg$": round(pnl.mean(), 0), "net$": round(pnl.sum(), 0),
        "maxDD$": round((np.maximum.accumulate(eq) - eq).max(), 0),
        "TP/SL/TIME/FLAT": "/".join(str(res.get(k, 0)) for k in ("TP", "SL", "TIME", "FLAT")),
    }


def split_dates(mk: Market):
    dates = sorted(d for d, tod in zip(mk.m3.date, mk.m3.tod)
                   if tod == time(9, 0) and (mk.dates is None or d in mk.dates))
    cut = dates[int(len(dates) * 0.6)]
    return dates, cut


def report(mk: Market, p: P, title: str):
    tr = run(mk, p)
    dates, cut = split_dates(mk)
    ins = [t for t in tr if t.date < cut]
    oos = [t for t in tr if t.date >= cut]
    print(title)
    print(pd.DataFrame([stats(ins, f"< {cut}"), stats(oos, f">= {cut}"), stats(tr, "all")]).to_string(index=False))
    return tr


GRID = dict(
    er_max=[0.25, 0.35, 0.45, 1.0],
    er_len=[10, 15, 20],
    entry_atr=[0.5, 0.75, 1.0, 1.25, 1.5],
    stop_atr=[1.0, 1.5, 2.0, 3.0],
    target=[0.25, 0.5, 0.75],
    cancel_min=[6, 9, 15],
    time_stop_min=[9, 15, 30, 0],
)

SENS = dict(
    er_max=[0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 1.0],
    er_len=[10, 12, 15, 20, 30],
    entry_atr=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
    stop_atr=[0.75, 1.0, 1.5, 2.0, 3.0],
    target=[0.25, 0.5, 0.75, 1.0],
    cancel_min=[3, 6, 9, 15, 30],
    time_stop_min=[6, 9, 15, 30, 0],
    fill_through=[0, 1, 2],
    fill_bar_target=[False, True],
    side=["long", "short", "both"],
    trend=["none", "ema"],
    start=[time(8, 30), time(9, 0), time(9, 30)],
    end=[time(10, 0), time(10, 30), time(11, 0), time(12, 0)],
    max_trades=[1, 2, 3, 99],
)


def plot_days(mk: Market, p: P, trades: list[Trade], cancelled: list[tuple]):
    """Trade-day charts in the style of plot_trades.py: red box = risk, green box = target."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    a = mk.ind(p)
    m3 = mk.m3.assign(er=a["er"], atr=a["atr"])
    out = Path(__file__).parent / "charts"
    out.mkdir(exist_ok=True)
    for d in sorted({t.date for t in trades}):
        day = m3[(m3.date == d) & (m3.tod >= time(8, 30)) & (m3.tod < time(11, 15))].reset_index(drop=True)
        x_of = {int(t): i for i, t in enumerate(day.t)}
        xt = lambda ts: (int(pd.Timestamp(ts).timestamp()) - int(day.t.iloc[0])) / 180
        fig, ax = plt.subplots(figsize=(14, 7))
        for i, r in day.iterrows():
            col = "#26a69a" if r.c >= r.o else "#ef5350"
            ax.plot([i, i], [r.l, r.h], color=col, lw=0.8)
            ax.add_patch(Rectangle((i - 0.3, min(r.o, r.c)), 0.6, max(abs(r.c - r.o), 0.25), color=col))
            tc = (r["dt"] + pd.Timedelta(minutes=3)).time()
            if p.start < tc < p.end and r.er <= p.er_max:
                ax.axvspan(i - 0.5, i + 0.5, color="#ff9800", alpha=0.08, lw=0)
        for t0, lim in cancelled:
            if pd.Timestamp(t0, unit="s", tz="UTC").tz_convert(TZ).date() == d:
                x0 = xt(pd.Timestamp(t0, unit="s", tz="UTC"))
                ax.hlines(lim, x0 - 0.5, x0 - 0.5 + p.cancel_min / 3, colors="#1e88e5", linestyles="dotted", lw=1.5)
        for tr in [t for t in trades if t.date == d]:
            xs, e, x = xt(tr.signal_time) - 0.5, xt(tr.entry_time), xt(tr.exit_time)
            w = max(x - e, 0.4)
            ax.hlines(tr.entry, xs, e, colors="#1e88e5", lw=1.5)
            ax.plot(xs - 0.5, day.l[int(round(xs - 0.5))] if 0 <= round(xs - 0.5) < len(day) else tr.entry,
                    marker="^", color="#1e88e5", ms=6)
            ax.add_patch(Rectangle((e - 0.5, min(tr.entry, tr.stop)), w, abs(tr.entry - tr.stop), color="red", alpha=0.22))
            ax.add_patch(Rectangle((e - 0.5, min(tr.entry, tr.target)), w, abs(tr.target - tr.entry), color="green", alpha=0.22))
            ax.annotate(f"{'LONG' if tr.side > 0 else 'SHORT'}\n{tr.result}  {tr.pnl:+.0f} $", (e - 0.5 + w, tr.target),
                        fontsize=9, fontweight="bold", color="green" if tr.pnl >= 0 else "red", va="bottom")
        ticks = [i for i, t in enumerate(day.tod) if t.minute % 15 == 0]
        ax.set_xticks(ticks, [day.tod[i].strftime("%H:%M") for i in ticks])
        ax.axvline(xt(pd.Timestamp.combine(d, p.end).tz_localize(TZ)) - 0.5, color="grey", ls="--", lw=0.8)
        ax.set_title(f"NQ 3m  {d}  (Chicago time) - orange = choppy (ER <= {p.er_max}), blue = buy limit, "
                     f"boxes red = risk / green = target")
        ax.set_xlim(-1, len(day) + 3)
        ax.grid(alpha=0.2)
        f = out / f"nq_m3_{d}.png"
        fig.tight_layout()
        fig.savefig(f, dpi=110)
        plt.close(fig)
        print(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="3m", choices=["3m", "1m"])
    ap.add_argument("--mnq", action="store_true", help="MNQ costs ($2/pt, $0.62/side)")
    ap.add_argument("--trades", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--sens", action="store_true")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--csv", help="write trades or grid to this CSV")
    for k, v in P().__dict__.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args()
    base = P(**{k: getattr(a, k) for k, v in P().__dict__.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    if a.mnq:
        base = replace(base, point_value=2.0, commission=0.62)
    pd.set_option("display.width", 220)

    m3 = load("nq_3m")
    path = load("nq_1m") if a.res == "1m" else m3
    mk = Market(m3, path, 60 if a.res == "1m" else 180)
    if a.res == "1m":  # only days fully covered by the 1m data
        mk.dates = {d for d, tod in zip(path.date, path.tod) if tod == time(8, 0)}
    dates, cut = split_dates(mk)
    print(f"NQ M3 limit fade | {dates[0]} .. {dates[-1]} ({len(dates)} days) | fills on {a.res} bars | "
          f"${base.point_value}/pt x{base.contracts}, ${base.commission}/side")

    if a.sens:
        rows = []
        for k, vals in SENS.items():
            for v in vals:
                p = replace(base, **{k: v})
                tr = run(mk, p)
                ins = [t for t in tr if t.date < cut]
                oos = [t for t in tr if t.date >= cut]
                st, si, so = stats(tr), stats(ins), stats(oos)
                rows.append(dict(param=k, value=str(v)[:5], mark="*" if getattr(base, k) == v else "",
                                 n=st.get("trades", 0), win=st.get("win%"), PF=st.get("PF"), avgR=st.get("avgR"),
                                 net=st.get("net$"), IS=si.get("net$", 0), OOS=so.get("net$", 0), dd=st.get("maxDD$")))
        out = pd.DataFrame(rows)
        print(out.to_string(index=False))
        if a.csv:
            out.to_csv(a.csv, index=False)
        return

    if a.grid:
        rows = []
        keys = list(GRID)
        for vals in itertools.product(*GRID.values()):
            p = replace(base, **dict(zip(keys, vals)))
            tr = run(mk, p)
            if not tr:
                continue
            pnl = np.array([t.pnl for t in tr])
            ins = sum(t.pnl for t in tr if t.date < cut)
            gl = -pnl[pnl < 0].sum()
            rows.append(dict(zip(keys, vals), n=len(tr), win=round(100 * (pnl > 0).mean(), 1),
                             PF=round(pnl[pnl > 0].sum() / gl, 2) if gl else np.inf,
                             avgR=round(np.mean([t.r for t in tr]), 3), net=round(pnl.sum()),
                             IS=round(ins), OOS=round(pnl.sum() - ins)))
        g = pd.DataFrame(rows)
        print(f"{len(g)} combinations, profitable: {(g.net > 0).mean():.0%}, "
              f"profitable in both halves: {((g.IS > 0) & (g.OOS > 0)).mean():.0%}")
        for k in keys:
            print(g.groupby(k)[["net", "IS", "OOS", "avgR", "n"]].median().round(2).to_string(), "\n")
        print("top 15 (min. 15 trades):")
        print(g[g.n >= 15].sort_values("net", ascending=False).head(15).to_string(index=False))
        d = base.__dict__
        me = g[np.all([g[k] == d[k] for k in keys], axis=0)]
        print("\ndefault rules rank:", int((g.net > me.net.iloc[0]).sum()) + 1 if len(me) else "-", "of", len(g))
        if a.csv:
            g.to_csv(a.csv, index=False)
        return

    tr = report(mk, base, "rules: " + ", ".join(f"{k}={v}" for k, v in base.__dict__.items()
                                                 if v != getattr(P(), k)) if base != P() else "default rules")
    if a.plot:
        cx = []
        plot_days(mk, base, run(mk, base, cx), cx)
    if a.trades:
        out = pd.DataFrame([t.__dict__ for t in tr])
        out["signal_time"] = out.signal_time.dt.strftime("%m-%d %H:%M")
        out["entry_time"] = out.entry_time.dt.tz_localize("UTC").dt.tz_convert(TZ).dt.strftime("%H:%M") \
            if out.entry_time.dt.tz is None else out.entry_time.dt.tz_convert(TZ).dt.strftime("%H:%M")
        print(out[["signal_time", "entry_time", "entry", "stop", "target", "exit", "result", "pnl", "r"]]
              .round(2).to_string(index=False))
        if a.csv:
            out.to_csv(a.csv, index=False)


if __name__ == "__main__":
    main()
