"""Chart preview of backtest trades, drawn like the Pine strategy:
candles, liquidity levels (from where they formed until broken = solid end,
or end of session = dotted), M15 support/resistance zones (until a M5 close
breaks them) and trade boxes (red = risk, green = target, dashed = TP1).

Usage:
    python backtest/plot_trades.py                 # all trade days of the combined strategy
    python backtest/plot_trades.py 2026-09-18 ...  # specific dates
Images go to backtest/charts/.
"""

import sys
from datetime import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

import combined_backtest as cb
import orb_backtest as ob
import sweep_backtest as sb

OUT = Path(__file__).parent / "charts"
START, END = time(7, 0), time(12, 0)
Z15_PIVOT = 3


def m15_zones(d15: pd.DataFrame) -> list[dict]:
    """Confirmed M15 swing zones; 'known' = time the zone becomes visible (close of confirming bar)."""
    h, l, o, c, t = (d15[k].to_numpy() for k in ("h", "l", "o", "c", "t"))
    p, zones = Z15_PIVOT, []
    for k in range(p, len(d15) - p):
        win_h, win_l = h[k - p:k + p + 1], l[k - p:k + p + 1]
        known = t[k + p] + 900
        if h[k] == win_h.max() and (win_h == h[k]).sum() == 1:
            zones.append(dict(side=1, t0=t[k], known=known, top=h[k], bot=max(o[k], c[k])))
        if l[k] == win_l.min() and (win_l == l[k]).sum() == 1:
            zones.append(dict(side=-1, t0=t[k], known=known, top=min(o[k], c[k]), bot=l[k]))
    return zones


def plot_day(df, d15, levels, trades, d):
    day = df[(df.date == d) & (df.tod >= START) & (df.tod <= END)].reset_index(drop=True)
    if day.empty:
        return None
    x_of = {t: i for i, t in enumerate(day.t)}
    fig, ax = plt.subplots(figsize=(14, 7))
    # candles
    for i, r in day.iterrows():
        col = "#26a69a" if r.c >= r.o else "#ef5350"
        ax.plot([i, i], [r.l, r.h], color=col, lw=0.8)
        ax.add_patch(Rectangle((i - 0.3, min(r.o, r.c)), 0.6, max(abs(r.c - r.o), 0.25), color=col))
    last = len(day) - 1
    first_t = day.t.iloc[0]

    # M15 zones visible during this window
    for z in m15_zones(d15[(d15.t > first_t - 3 * 86400) & (d15.t <= day.t.iloc[-1])]):
        if z["known"] > day.t.iloc[-1]:
            continue
        after = df[(df.t + 300 > z["known"]) & (df.t <= day.t.iloc[-1])]
        brk = after[(after.c > z["top"]) if z["side"] > 0 else (after.c < z["bot"])]
        end_t = brk.t.iloc[0] if not brk.empty else None
        if end_t is not None and end_t < first_t:
            continue  # already broken before the chart window
        x0 = x_of.get(z["t0"], 0) if z["t0"] >= first_t else 0
        x1 = x_of.get(end_t, last) if end_t is not None else last
        col = "#ef5350" if z["side"] > 0 else "#26a69a"
        ax.add_patch(Rectangle((x0, z["bot"]), x1 - x0, max(z["top"] - z["bot"], 0.5), color=col, alpha=0.12, lw=0))

    # liquidity levels from the backtest (known at 09:30) + their break
    for px, side, name in levels.get(d, []):
        rng = day[day.tod >= time(9, 30)]
        hit = rng[(rng.h > px + sb.TICK) if side > 0 else (rng.l < px - sb.TICK)]
        x1 = hit.index[0] if not hit.empty else last
        col = "#d32f2f" if side > 0 else "#00897b"
        ax.hlines(px, 0, x1, colors=col, lw=1.2, linestyles="solid" if not hit.empty else "dotted")
        ax.text(0, px, f" {name}", color=col, fontsize=8, va="bottom" if side > 0 else "top")

    # M5 swing highs/lows from 08:00 (same rule as the strategy), until traded through
    piv = sb.Params().pivot
    h, l = day.h.to_numpy(), day.l.to_numpy()
    for k in range(piv, len(day) - piv):
        if day.tod[k] < time(8, 0):
            continue
        for side, arr, px in ((1, h, h[k]), (-1, l, l[k])):
            left, right = arr[k - piv:k], arr[k + 1:k + piv + 1]
            ok = (px >= left.max() and px > right.max()) if side > 0 else (px <= left.min() and px < right.min())
            if not ok:
                continue
            fut = arr[k + piv + 1:]
            brk = np.flatnonzero(fut > px + sb.TICK) if side > 0 else np.flatnonzero(fut < px - sb.TICK)
            x1 = k + piv + 1 + brk[0] if brk.size else last
            col = "#d32f2f" if side > 0 else "#00897b"
            ax.hlines(px, k, x1, colors=col, lw=0.9, alpha=0.7)
            ax.text(k, px, "swing H" if side > 0 else "swing L", color=col, fontsize=6,
                    va="bottom" if side > 0 else "top", alpha=0.8)

    # trades
    for tr in [t for t in trades if t.date == d]:
        e = x_of.get(int(tr.entry_time.timestamp()))
        x = x_of.get(int(tr.exit_time.timestamp()), last)
        if e is None:
            continue
        w = max(x - e, 1)
        ax.add_patch(Rectangle((e, min(tr.entry, tr.stop)), w, abs(tr.entry - tr.stop), color="red", alpha=0.22))
        ax.add_patch(Rectangle((e, min(tr.entry, tr.tp2)), w, abs(tr.tp2 - tr.entry), color="green", alpha=0.22))
        ax.hlines(tr.tp1, e, e + w, colors="green", linestyles="dashed", lw=1)
        ax.annotate(f"{'LONG' if tr.side > 0 else 'SHORT'} {tr.level}\n{tr.result}  {tr.pnl:+.0f} $",
                    (e + w, tr.tp2), fontsize=9, fontweight="bold",
                    color="green" if tr.pnl >= 0 else "red", va="center")

    ticks = [i for i, t in enumerate(day.tod) if t.minute == 0]
    ax.set_xticks(ticks, [day.tod[i].strftime("%H:%M") for i in ticks])
    ax.axvspan(x_of.get(day.t[day.tod >= time(9, 30)].iloc[0], 0), last, color="#1e88e5", alpha=0.03)
    ax.set_title(f"MNQ 5m  {d}  (New York time)  -  levels, M15 zones, trade boxes")
    ax.set_xlim(-1, last + 12)
    ax.grid(alpha=0.2)
    OUT.mkdir(exist_ok=True)
    f = OUT / f"mnq_{d}.png"
    fig.tight_layout()
    fig.savefig(f, dpi=110)
    plt.close(fig)
    return f


def main():
    df = sb.load("5m")
    d15 = sb.load("15m")
    levels = sb.build_levels(df)
    trades = cb.combine(sb.run(df, sb.Params.for_tf("5m"), levels), ob.run(df, ob.OrbParams(), 5))
    dates = [pd.Timestamp(a).date() for a in sys.argv[1:]] or sorted({t.date for t in trades})
    for d in dates:
        f = plot_day(df, d15, levels, trades, d)
        if f:
            print(f)


if __name__ == "__main__":
    main()
