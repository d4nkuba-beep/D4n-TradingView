"""Backtest engine: signals on M3/M5 closes, execution resolved on M1 bars.

Why M1 execution: on a 5-minute bar you cannot know whether the stop or the
target was hit first. Walking the 1-minute bars inside it answers that for
almost every case; only if both are touched inside the *same minute* the stop
is assumed (conservative).

Fill rules (all conservative):
  * market order  -> next M1 open + 1 tick slippage
  * limit order   -> only if price trades *through* the limit by 1 tick
  * stop exit     -> stop price + 1 tick slippage (gaps: worse of open/stop)
  * target exit   -> limit fill at the target (needs a touch)
  * commission    -> $0.80 per contract and side (prop-firm all-in rate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TICK = 0.25
POINT_VALUE = 2.0  # MNQ
COMMISSION = 0.80  # $ per contract per side
SLIP = TICK


# ----------------------------------------------------------------------------- data

def load_m1(source: str = "nas100") -> pd.DataFrame:
    if source == "nas100":
        df = pd.read_csv(ROOT / "data" / "hist" / "nas100_m1.csv.gz")
    elif source == "mnq":
        df = pd.read_csv(ROOT / "data" / "mnq_1m.csv")[["t", "o", "h", "l", "c", "v"]]
    else:
        raise ValueError(source)
    df = df[df.t % 60 == 0].drop_duplicates("t").sort_values("t").reset_index(drop=True)
    if "v" not in df:
        df["v"] = np.nan
    return df


def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    step = minutes * 60
    g = m1.groupby(m1.t // step * step)
    df = pd.DataFrame({"o": g.o.first(), "h": g.h.max(), "l": g.l.min(), "c": g.c.last(),
                       "v": g.v.sum(min_count=1)})
    df.index.name = "t"
    return df.reset_index()


def add_time(df: pd.DataFrame) -> pd.DataFrame:
    dt = pd.to_datetime(df.t, unit="s", utc=True).dt.tz_convert("America/New_York")
    df["dt"] = dt
    df["date"] = dt.dt.date
    df["mod"] = (dt.dt.hour * 60 + dt.dt.minute).astype(int)  # minute of day of the bar OPEN
    return df


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([df.h - df.l, (df.h - df.c.shift()).abs(), (df.l - df.c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    for n in (9, 20, 21, 50, 200):
        df[f"ema{n}"] = ema(df.c, n)
    df["rsi"] = rsi(df.c, 14)
    df["atr"] = atr(df, 14)
    # Chaikin accumulation/distribution line; with no volume (index CFD) the
    # close-location value alone is accumulated (volume = 1).
    rng = (df.h - df.l).replace(0, np.nan)
    clv = (((df.c - df.l) - (df.h - df.c)) / rng).fillna(0)
    vol = df.v.fillna(1.0) if df.v.notna().any() else 1.0
    df["ad"] = (clv * vol).cumsum()
    # session VWAP from 09:30 (index has no volume -> equal weights = TWAP)
    tp = (df.h + df.l + df.c) / 3
    rth = df["mod"] >= 570
    w = (df.v.fillna(1.0) if df.v.notna().any() else pd.Series(1.0, index=df.index)).where(rth, 0.0)
    key = df.date.astype(str)
    df["vwap"] = ((tp * w).groupby(key).cumsum() / w.groupby(key).cumsum().replace(0, np.nan)).where(rth)
    return df


def prepare(tf: int, source: str = "nas100", m1: pd.DataFrame | None = None):
    m1 = load_m1(source) if m1 is None else m1
    bars = add_indicators(add_time(resample(m1, tf)))
    m1 = add_time(m1.copy())
    return bars, m1


def day_levels(bars: pd.DataFrame) -> dict:
    """Per trading date: prior RTH high/low/close, overnight high/low (18:00-09:30), London (02-05)."""
    out = {}
    d_arr = bars.date.to_numpy()
    mod = bars["mod"].to_numpy()
    h, l, c = bars.h.to_numpy(), bars.l.to_numpy(), bars.c.to_numpy()
    rth_by_date = {}
    rth_mask = (mod >= 570) & (mod < 960)
    for d, idx in pd.Series(np.arange(len(d_arr))).groupby(d_arr):
        idx = idx.to_numpy()
        r = idx[rth_mask[idx]]
        if r.size:
            rth_by_date[d] = (h[r].max(), l[r].min(), c[r[-1]], r[0], r[-1])
    rth_dates = sorted(rth_by_date)
    ranges = [rth_by_date[x][0] - rth_by_date[x][1] for x in rth_dates]
    for k in range(1, len(rth_dates)):
        d, pd_ = rth_dates[k], rth_dates[k - 1]
        start = rth_by_date[pd_][4] + 1
        end = rth_by_date[d][3]  # first RTH bar of d
        on = slice(start, end)
        idx = np.arange(start, end)
        lon = idx[(d_arr[idx] == d) & (mod[idx] >= 120) & (mod[idx] < 300)]
        out[d] = dict(pdh=rth_by_date[pd_][0], pdl=rth_by_date[pd_][1], pdc=rth_by_date[pd_][2],
                      onh=h[on].max() if end > start else np.nan, onl=l[on].min() if end > start else np.nan,
                      lonh=h[lon].max() if lon.size else np.nan, lonl=l[lon].min() if lon.size else np.nan,
                      datr=float(np.mean(ranges[max(0, k - 14):k])))
    return out


# ----------------------------------------------------------------------------- orders & trades

@dataclass
class Order:
    side: int  # +1 long, -1 short
    kind: str  # market | limit
    price: float  # limit price (ignored for market)
    stop: float
    target: float
    expiry_mod: int = 10_000  # cancel if not filled by this minute of day
    be_at_r: float = 0.0  # move stop to entry + be_lock*R once price reaches this R (0 = off)
    be_lock: float = 0.0
    tag: str = ""


@dataclass
class Trade:
    date: object
    side: int
    tag: str
    entry_time: object
    entry: float
    stop: float
    target: float
    qty: int
    exit_time: object = None
    exit: float = 0.0
    pnl: float = 0.0
    r: float = 0.0
    result: str = ""


@dataclass
class Risk:
    risk_usd: float = 250.0  # $ risk per trade (sizes the number of MNQ)
    max_qty: int = 30
    fixed_qty: int = 0  # >0: ignore risk_usd
    max_trades: int = 2
    max_losses: int = 2
    daily_loss: float = 600.0  # stop trading the day after this realised loss
    flat_mod: int = 15 * 60 + 55


def qty_for(risk_pts: float, r: Risk) -> int:
    if r.fixed_qty:
        return r.fixed_qty
    per = risk_pts * POINT_VALUE + 2 * COMMISSION + SLIP * POINT_VALUE
    return int(max(1, min(r.max_qty, r.risk_usd // per)))


class Strategy:
    """Per-day state machine. `on_bar(i)` sees every signal bar close of the
    session and may return an Order when the engine is flat."""

    def start_day(self, d, idx: np.ndarray, ctx: dict) -> None:
        raise NotImplementedError

    def on_bar(self, i: int, flat: bool):
        raise NotImplementedError


_CACHE: dict = {}


def cached(bars: pd.DataFrame, m1: pd.DataFrame) -> dict:
    key = (id(bars), id(m1))
    if key not in _CACHE:
        cols = ("o", "h", "l", "c", "mod", "ema9", "ema20", "ema21", "ema50", "ema200", "rsi", "atr", "ad", "vwap")
        _CACHE[key] = dict(levels=day_levels(bars), arr={k: bars[k].to_numpy() for k in cols},
                           m1dt=m1.dt.to_numpy() if False else m1.dt)
    return _CACHE[key]


def run(bars: pd.DataFrame, m1: pd.DataFrame, strat_factory, risk: Risk,
        session=(570, 15 * 60 + 55), dates=None) -> list[Trade]:
    cc = cached(bars, m1)
    levels = cc["levels"]
    b_date = bars.date.to_numpy()
    b_mod = bars["mod"].to_numpy()
    b_t = bars.t.to_numpy()
    tf = int(np.median(np.diff(b_t[:500])))
    m_t = m1.t.to_numpy()
    mo, mh, ml, mc = (m1[k].to_numpy() for k in "ohlc")
    m_mod = m1["mod"].to_numpy()
    trades: list[Trade] = []
    all_dates = [d for d in pd.unique(b_date) if d in levels]
    if dates is not None:
        dset = set(dates)
        all_dates = [d for d in all_dates if d in dset]
    date_index = pd.Series(np.arange(len(b_date))).groupby(b_date).agg(["min", "max"])

    for d in all_dates:
        lo, hi = date_index.loc[d]
        idx = np.arange(lo, hi + 1)
        idx = idx[(b_mod[idx] >= session[0]) & (b_mod[idx] < risk.flat_mod)]
        if idx.size < 3:
            continue
        strat = strat_factory()
        strat.start_day(d, idx, dict(levels=levels[d], bars=bars, arr=cc["arr"]))
        n_tr = n_loss = 0
        day_pnl = 0.0
        pending: Order | None = None
        pos = None  # dict
        for i in idx:
            # ---- simulate the M1 bars inside signal bar i (only if something is working)
            if pending is not None or pos is not None:
                j0 = np.searchsorted(m_t, b_t[i])
                j1 = np.searchsorted(m_t, b_t[i] + tf)
                for j in range(j0, j1):
                    if pending is not None and pos is None:
                        o = pending
                        if m_mod[j] >= o.expiry_mod:
                            pending = None
                        else:
                            fill = None
                            if o.kind == "market":
                                fill = mo[j] + o.side * SLIP
                            elif o.side > 0 and ml[j] <= o.price - TICK:
                                fill = min(o.price, mo[j])
                            elif o.side < 0 and mh[j] >= o.price + TICK:
                                fill = max(o.price, mo[j])
                            if fill is not None:
                                risk_pts = abs(fill - o.stop)
                                if (fill - o.stop) * o.side <= 0 or (o.target - fill) * o.side <= 0:
                                    pending = None  # gapped beyond stop/target: skip
                                    continue
                                q = qty_for(risk_pts, risk)
                                tr = Trade(d, o.side, o.tag, m1.dt.iat[j], fill, o.stop, o.target, q)
                                pos = dict(tr=tr, stop=o.stop, risk=risk_pts, o=o, j=j)
                                pending = None
                                # same minute: adverse extreme may already hit the stop
                                if (o.side > 0 and ml[j] <= o.stop) or (o.side < 0 and mh[j] >= o.stop):
                                    pos["exit"] = (o.stop - o.side * SLIP, "SL")
                    if pos is not None:
                        tr, s = pos["tr"], pos["tr"].side
                        ex = pos.pop("exit", None)
                        if ex is None and j > pos["j"]:
                            if (s > 0 and ml[j] <= pos["stop"]) or (s < 0 and mh[j] >= pos["stop"]):
                                px = min(pos["stop"], mo[j]) if s > 0 else max(pos["stop"], mo[j])
                                ex = (px - s * SLIP, "SL" if pos["stop"] == tr.stop else "BE")
                            elif (s > 0 and mh[j] >= tr.target) or (s < 0 and ml[j] <= tr.target):
                                ex = (tr.target, "TP")
                            elif m_mod[j] >= risk.flat_mod - 1:
                                ex = (mc[j] - s * SLIP, "TIME")
                        if ex is None and j >= pos["j"] and pos["o"].be_at_r > 0 and pos["stop"] == tr.stop:
                            fav = (mh[j] - tr.entry) if s > 0 else (tr.entry - ml[j])
                            if fav >= pos["o"].be_at_r * pos["risk"]:
                                pos["stop"] = tr.entry + s * pos["o"].be_lock * pos["risk"]
                        if ex is not None:
                            tr.exit, tr.result, tr.exit_time = ex[0], ex[1], m1.dt.iat[j]
                            tr.pnl = (tr.exit - tr.entry) * s * POINT_VALUE * tr.qty - 2 * COMMISSION * tr.qty
                            tr.r = (tr.exit - tr.entry) * s / pos["risk"]
                            trades.append(tr)
                            n_tr += 1
                            n_loss += tr.pnl < 0
                            day_pnl += tr.pnl
                            pos = None
                            strat_exit = getattr(strat, "on_exit", None)
                            if strat_exit:
                                strat_exit(tr)
            # ---- signal bar close
            flat = pos is None and pending is None
            can = (n_tr < risk.max_trades and n_loss < risk.max_losses and day_pnl > -risk.daily_loss)
            order = strat.on_bar(i, flat and can)
            if order is not None and flat and can:
                pending = order
        # force exit at end of data for the day (should be covered by TIME exit)
        if pos is not None:
            tr, s = pos["tr"], pos["tr"].side
            j = np.searchsorted(m_t, b_t[idx[-1]] + tf) - 1
            tr.exit, tr.result, tr.exit_time = mc[j] - s * SLIP, "EOD", m1.dt.iat[j]
            tr.pnl = (tr.exit - tr.entry) * s * POINT_VALUE * tr.qty - 2 * COMMISSION * tr.qty
            tr.r = (tr.exit - tr.entry) * s / pos["risk"]
            trades.append(tr)
    return trades


# ----------------------------------------------------------------------------- evaluation

def stats(trades: list[Trade], label: str = "") -> dict:
    if not trades:
        return {"set": label, "n": 0}
    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r for t in trades])
    eq = np.concatenate([[0], pnl.cumsum()])
    dd = (np.maximum.accumulate(eq) - eq).max()
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    days = pd.Series(pnl, index=[t.date for t in trades]).groupby(level=0).sum()
    return {"set": label, "n": len(trades), "win%": round(100 * (pnl > 0).mean(), 1),
            "PF": round(gp / gl, 2) if gl else float("inf"), "avgR": round(r.mean(), 3),
            "net$": round(pnl.sum()), "maxDD$": round(dd), "worstDay$": round(days.min()),
            "avg$/tr": round(pnl.mean(), 1)}


def by_period(trades: list[Trade], freq: str = "Y") -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    key = (lambda d: d.year) if freq == "Y" else (lambda d: f"{d.year}-H{1 + (d.month > 6)}")
    groups: dict = {}
    for t in trades:
        groups.setdefault(key(t.date), []).append(t)
    return pd.DataFrame([stats(v, str(k)) for k, v in sorted(groups.items())])


def prop_sim(trades: list[Trade], target: float = 3000, max_dd: float = 2000,
             daily_limit: float = 1000, eod_trailing: bool = True, sessions=None) -> dict:
    """Start a fresh 50k evaluation on every trading day in the sample and run
    it forward: pass at +target, fail when equity falls `max_dd` below its
    trailing (end-of-day) high or a day loses more than `daily_limit`
    (Topstep-style 50k rules)."""
    if not trades:
        return {}
    days = pd.Series([t.pnl for t in trades], index=[t.date for t in trades]).groupby(level=0)
    # intraday path per day to catch intraday trailing breaches
    paths = {d: np.cumsum(g.to_numpy()) for d, g in days}
    for d in sessions or []:  # sessions without a trade still count as days
        paths.setdefault(d, np.zeros(1))
    ds = sorted(paths)
    res = []
    for k in range(len(ds)):
        eq, peak, n_days = 0.0, 0.0, 0
        outcome = "open"
        for d in ds[k:]:
            n_days += 1
            p = paths[d]
            intr = eq + p
            if (intr.min() - eq) <= -daily_limit or intr.min() <= peak - max_dd:
                outcome = "fail"
                break
            eq = intr[-1]
            if not eod_trailing:
                peak = max(peak, intr.max())
            else:
                peak = max(peak, eq)
            if eq >= target:
                outcome = "pass"
                break
        res.append((outcome, n_days))
    out = pd.DataFrame(res, columns=["o", "days"])
    done = out[out.o != "open"]
    return {"starts": len(out), "pass%": round(100 * (done.o == "pass").mean(), 1) if len(done) else np.nan,
            "fail%": round(100 * (done.o == "fail").mean(), 1) if len(done) else np.nan,
            "open": int((out.o == "open").sum()),
            "med_days_to_pass": float(done[done.o == "pass"].days.median()) if (done.o == "pass").any() else np.nan}


def trades_df(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for t in trades])
