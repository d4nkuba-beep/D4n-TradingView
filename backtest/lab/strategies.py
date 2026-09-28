"""Candidate intraday setups for MNQ, all evaluated at signal-bar closes.

ORB      : opening range breakout (range = first `orb` minutes from 09:30)
           mode "break"   -> market entry after the first close outside the range
           mode "retest"  -> "double tap": after the break, limit order back at the
                             range edge (+/- offset), i.e. the second touch
           mode "fakeout" -> close outside, then close back inside -> fade
SWEEP    : ICT style: liquidity sweep of a known level, then change of character
           (close beyond the last opposite swing) -> limit entry in the displacement
           leg (FVG / 50 %) with an offset
BOS      : trend continuation: EMA stack + break of structure, limit entry at the
           broken swing level on the pullback
"""

from __future__ import annotations

import numpy as np

from engine import TICK, Order, Strategy


def rnd(x: float) -> float:
    return round(x / TICK) * TICK


class Base(Strategy):
    def __init__(self, **p):
        self.p = p

    def start_day(self, d, idx, ctx):
        a = ctx["arr"]
        self.lv = ctx["levels"]
        self.idx = idx
        self.o, self.h, self.l, self.c = a["o"], a["h"], a["l"], a["c"]
        self.mod = a["mod"]
        self.a = a
        self.t0 = idx[0]
        self.init()

    def init(self):
        pass

    def trend(self, i, side) -> bool:
        f = self.p.get("trend", "none")
        a, c = self.a, self.c[i]
        if f == "none":
            return True
        if f == "ema20_50":
            return (a["ema20"][i] - a["ema50"][i]) * side > 0
        if f == "ema9_21":
            return (a["ema9"][i] - a["ema21"][i]) * side > 0
        if f == "ema200":
            return (c - a["ema200"][i]) * side > 0
        if f == "vwap":
            return (c - a["vwap"][i]) * side > 0
        if f == "ema20_50_200":
            return (a["ema20"][i] - a["ema50"][i]) * side > 0 and (c - a["ema200"][i]) * side > 0
        raise ValueError(f)

    def in_window(self, i) -> bool:
        m = self.mod[i]
        return self.p.get("start", 570) <= m < self.p.get("last_entry", 690)

    def swings(self, i, k):
        """Most recent confirmed swing high / low (pivot k left/right) up to bar i, today only."""
        hs = ls = None
        for j in range(i - k, max(self.t0 - 1, i - 60), -1):
            if j - k < 0:
                break
            if hs is None and self.h[j] == self.h[j - k:j + k + 1].max():
                hs = (j, self.h[j])
            if ls is None and self.l[j] == self.l[j - k:j + k + 1].min():
                ls = (j, self.l[j])
            if hs and ls:
                break
        return hs, ls


class ORB(Base):
    def init(self):
        self.n_or = self.p.get("orb", 15)
        self.rh = self.rl = None
        self.state = None  # (side, bar) after first close outside
        self.done = False
        self.fake = None

    def make(self, side, entry_kind, price, stop, i, tag):
        p = self.p
        entry_ref = price if entry_kind == "limit" else self.c[i]
        risk = abs(entry_ref - stop)
        if risk < p.get("min_risk", 8) or risk > p.get("max_risk_atr", 99) * self.a["atr"][i]:
            return None
        tgt = entry_ref + side * p.get("rr", 2.0) * risk
        return Order(side, entry_kind, rnd(price), rnd(stop), rnd(tgt),
                     expiry_mod=self.mod[i] + p.get("expiry", 60) + self._tf(),
                     be_at_r=p.get("be_at", 0.0), be_lock=p.get("be_lock", 0.0), tag=tag)

    def _tf(self):
        return int(self.mod[self.idx[1]] - self.mod[self.idx[0]])

    def on_bar(self, i, flat):
        p = self.p
        m = self.mod[i]
        tf = self._tf()
        if m + tf <= 570 + self.n_or:  # still building the range
            j = self.idx[(self.mod[self.idx] >= 570) & (self.mod[self.idx] <= m)]
            self.rh, self.rl = self.h[j].max(), self.l[j].min()
            return None
        if self.rh is None or self.done or not self.in_window(i):
            return None
        rh, rl, mid = self.rh, self.rl, (self.rh + self.rl) / 2
        width = rh - rl
        if width > p.get("max_width_atr", 99) * self.a["atr"][i] * (15 / tf) ** 0.5:
            self.done = True
            return None
        mode = p.get("mode", "break")
        c = self.c[i]
        side = 1 if c > rh else -1 if c < rl else 0
        if mode in ("break", "retest"):
            if self.state is None:
                if side == 0:
                    return None
                if p.get("first_only", True) and not self.trend(i, side):
                    self.done = True  # first break against the trend: skip the day
                    return None
                if not self.trend(i, side):
                    return None
                self.state = (side, i)
                if mode == "break" and flat:
                    stop = self.stop_for(side, i)
                    self.done = True
                    return self.make(side, "market", c, stop, i, "ORB-break")
                if mode == "retest":
                    edge = rh if side > 0 else rl
                    price = edge + side * p.get("offset", 0.0)
                    stop = self.stop_for(side, i)
                    self.done = True
                    if flat:
                        return self.make(side, "limit", price, stop, i, "ORB-retest")
            return None
        if mode == "fakeout":
            if self.fake is None:
                if side != 0:
                    self.fake = [side, i, self.h[i] if side > 0 else self.l[i]]
                return None
            fs, fb, ext = self.fake
            self.fake[2] = max(ext, self.h[i]) if fs > 0 else min(ext, self.l[i])
            ext = self.fake[2]
            if i - fb > p.get("fake_bars", 3):
                self.done = True  # it was a real breakout
                return None
            back_in = c < rh if fs > 0 else c > rl
            if p.get("fake_mid", False):
                back_in = c < mid if fs > 0 else c > mid
            if not back_in:
                return None
            s = -fs
            self.done = True
            if not flat or not self.trend(i, s):
                return None
            if p.get("rsi_confirm", 0):
                # RSI divergence proxy: RSI at the fake extreme did not exceed the level
                r = self.a["rsi"][fb:i + 1]
                if fs > 0 and r.max() > 100 - p["rsi_confirm"]:
                    pass
                if fs > 0 and not (r.max() < 70):
                    return None
                if fs < 0 and not (r.min() > 30):
                    return None
            stop = ext + s * -1 * (p.get("stop_buf", 2) * TICK)
            stop = ext - s * p.get("stop_buf", 2) * TICK
            return self.make(s, "market", c, stop, i, "ORB-fake")
        return None

    def stop_for(self, side, i):
        p = self.p
        kind = p.get("stop", "mid")
        if kind == "mid":
            ref = (self.rh + self.rl) / 2
        elif kind == "opp":
            ref = self.rl if side > 0 else self.rh
        elif kind == "atr":
            edge = self.rh if side > 0 else self.rl
            ref = edge - side * p.get("stop_atr", 1.0) * self.a["atr"][i]
        elif kind == "bar":
            ref = self.l[i] if side > 0 else self.h[i]
        else:
            raise ValueError(kind)
        return ref - side * p.get("stop_buf", 2) * TICK


class Sweep(Base):
    """Liquidity sweep -> CHoCH -> entry in the displacement leg."""

    def init(self):
        lv = self.lv
        use = self.p.get("levels", ("pdh", "pdl", "onh", "onl", "lonh", "lonl"))
        self.levels = [(lv[k], 1 if k.endswith("h") else -1, k) for k in use
                       if k in lv and np.isfinite(lv[k])]
        self.armed = None
        self.orh = self.orl = None

    def on_bar(self, i, flat):
        p = self.p
        m = self.mod[i]
        h, l, c = self.h, self.l, self.c
        # opening-range levels as extra liquidity once the range is done
        if p.get("orb_levels", 0) and m + self._tf() == 570 + p["orb_levels"]:
            j = self.idx[(self.mod[self.idx] >= 570) & (self.mod[self.idx] <= m)]
            self.levels += [(h[j].max(), 1, "orh"), (l[j].min(), -1, "orl")]
            return None
        # sweeps (levels are consumed when taken)
        swept = [x for x in self.levels if (x[1] > 0 and h[i] > x[0]) or (x[1] < 0 and l[i] < x[0])]
        if swept:
            self.levels = [x for x in self.levels if x not in swept]
            if self.in_window(i):
                x = max(swept, key=lambda z: z[0]) if any(z[1] > 0 for z in swept) else min(swept, key=lambda z: z[0])
                s = -x[1]  # sweep of a high -> short idea
                k = p.get("pivot", 2)
                hs, ls = self.swings(i, k)
                ref = ls if s < 0 else hs  # structure to break for the CHoCH
                if ref is not None:
                    self.armed = dict(side=s, bar=i, ext=h[i] if s < 0 else l[i], ref=ref[1], lvl=x[0], name=x[2])
                else:
                    self.armed = dict(side=s, bar=i, ext=h[i] if s < 0 else l[i],
                                      ref=l[i] if s < 0 else h[i], lvl=x[0], name=x[2])
        a = self.armed
        if a is None:
            return None
        s = a["side"]
        a["ext"] = max(a["ext"], h[i]) if s < 0 else min(a["ext"], l[i])
        if i - a["bar"] > p.get("confirm", 6) or not self.in_window(i):
            self.armed = None
            return None
        choch = c[i] < a["ref"] if s < 0 else c[i] > a["ref"]
        if not choch:
            return None
        self.armed = None
        if not flat or not self.trend(i, s):
            return None
        if p.get("rsi_div", False):
            # RSI at the sweep extreme must not confirm (bearish/bullish divergence proxy)
            r = self.a["rsi"][a["bar"]:i + 1]
            if s < 0 and r.max() > p.get("rsi_hi", 70):
                return None
            if s > 0 and r.min() < p.get("rsi_lo", 30):
                return None
        if p.get("ad_div", False):
            ad = self.a["ad"]
            lb = p.get("ad_lb", 12)
            j0 = max(self.t0 - lb, a["bar"] - lb)
            if j0 >= a["bar"]:
                return None
            # price made a new extreme at the sweep, AD did not
            if s < 0 and not (ad[a["bar"]] < ad[j0:a["bar"]].max()):
                return None
            if s > 0 and not (ad[a["bar"]] > ad[j0:a["bar"]].min()):
                return None
        ext = a["ext"]
        stop = ext - s * p.get("stop_buf", 2) * TICK
        entry_kind = p.get("entry", "limit")
        if entry_kind == "market":
            price = c[i]
        else:
            leg_end = l[a["bar"]:i + 1].min() if s < 0 else h[a["bar"]:i + 1].max()
            price = leg_end + (ext - leg_end) * p.get("fib", 0.5)
            price = price - s * p.get("offset", 0.0)
        risk = abs(price - stop)
        if risk < p.get("min_risk", 8) or risk > p.get("max_risk_atr", 4) * self.a["atr"][i]:
            return None
        tgt = price + s * p.get("rr", 2.0) * risk
        return Order(s, entry_kind, rnd(price), rnd(stop), rnd(tgt),
                     expiry_mod=m + self._tf() + p.get("expiry", 30),
                     be_at_r=p.get("be_at", 0.0), be_lock=p.get("be_lock", 0.0), tag="SW-" + a["name"])

    def _tf(self):
        return int(self.mod[self.idx[1]] - self.mod[self.idx[0]])


class BOS(Base):
    """Trend continuation after a break of structure, entry on the retest."""

    def init(self):
        self.last_break = None

    def on_bar(self, i, flat):
        p = self.p
        if not self.in_window(i) or not flat:
            return None
        k = p.get("pivot", 3)
        hs, ls = self.swings(i, k)
        c = self.c
        for s, sw, opp in ((1, hs, ls), (-1, ls, hs)):
            if sw is None or opp is None:
                continue
            broke = c[i] > sw[1] and c[i - 1] <= sw[1] if s > 0 else c[i] < sw[1] and c[i - 1] >= sw[1]
            if not broke or not self.trend(i, s):
                continue
            if p.get("rsi_filter", False):
                r = self.a["rsi"][i]
                if (s > 0 and r > p.get("rsi_max", 75)) or (s < 0 and r < 100 - p.get("rsi_max", 75)):
                    continue
            price = sw[1] + s * p.get("offset", 0.0)
            stop_ref = opp[1] if p.get("stop", "swing") == "swing" else price - s * p.get("stop_atr", 1.5) * self.a["atr"][i]
            stop = stop_ref - s * p.get("stop_buf", 2) * TICK
            risk = abs(price - stop)
            if risk < p.get("min_risk", 8) or risk > p.get("max_risk_atr", 4) * self.a["atr"][i]:
                continue
            tgt = price + s * p.get("rr", 2.0) * risk
            kind = p.get("entry", "limit")
            if kind == "market":
                price = c[i]
            return Order(s, kind, rnd(price), rnd(stop), rnd(tgt),
                         expiry_mod=self.mod[i] + p.get("expiry", 30),
                         be_at_r=p.get("be_at", 0.0), be_lock=p.get("be_lock", 0.0), tag="BOS")
        return None


class FirstCandle(Base):
    """5-minute opening range momentum: trade in the direction of the first
    `orb`-minute candle of the cash session (research: Zarattini & Aziz 2023)."""

    def init(self):
        self.done = False

    def on_bar(self, i, flat):
        p = self.p
        m = self.mod[i]
        n = p.get("orb", 5)
        tf = int(self.mod[self.idx[1]] - self.mod[self.idx[0]])
        if self.done or m + tf != 570 + n:
            return None
        self.done = True
        j = self.idx[(self.mod[self.idx] >= 570) & (self.mod[self.idx] <= m)]
        o, c, hi, lo = self.o[j[0]], self.c[i], self.h[j].max(), self.l[j].min()
        datr = self.lv["datr"]
        body = c - o
        if abs(body) < p.get("min_body", 0.0) * datr:
            return None
        side = 1 if body > 0 else -1
        if p.get("fade", False):
            side = -side
        if not flat or not self.trend(i, side):
            return None
        if p.get("gap_filter", 0):
            gap = (o - self.lv["pdc"]) / datr
            if p["gap_filter"] == 1 and gap * side > 0.25:  # do not chase a big gap
                return None
        entry_kind = p.get("entry", "market")
        if entry_kind == "market":
            price = c
        else:  # limit pullback into the candle
            price = c - side * p.get("pull", 0.3) * (hi - lo)
        stop_kind = p.get("stop", "atr")
        if stop_kind == "atr":
            stop = price - side * p.get("stop_atr", 0.1) * datr
        elif stop_kind == "orb":
            stop = (lo if side > 0 else hi) - side * 2 * TICK
        else:  # mid of the candle
            stop = (hi + lo) / 2 - side * 2 * TICK
        risk = abs(price - stop)
        if risk < p.get("min_risk", 8):
            return None
        tgt = price + side * p.get("rr", 10.0) * risk
        return Order(side, entry_kind, rnd(price), rnd(stop), rnd(tgt), expiry_mod=m + tf + p.get("expiry", 30),
                     be_at_r=p.get("be_at", 0.0), be_lock=p.get("be_lock", 0.0), tag="FC")
