"""Download free Nasdaq-100 (NSXUSD) 1-minute bars from HistData.com.

TradingView/Yahoo only serve a few weeks of M5 for MNQ. The Nasdaq-100 index
moves minute for minute like MNQ (checked against MNQ=F 1m, Sep 2026: correlation
of 1-minute changes 0.97 in RTH, same timestamps); only a slowly drifting
carry basis (~+300 pts) differs, which does not matter for intraday points.

HistData timestamps for NSXUSD are New York wall-clock time (DST aware), which
was verified against MNQ in summer and winter.

Output: backtest/data/hist/nas100_m1.csv.gz  with t = unix seconds UTC, o h l c
Usage:  python backtest/fetch_histdata.py [first_year] [last_year] [last_month]
"""

from __future__ import annotations

import glob
import http.cookiejar
import io
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "data" / "hist"
PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/nsxusd/{p}"


def download(year: int, month: int | None) -> None:
    path = f"{year}" if month is None else f"{year}/{month}"
    ref = PAGE.format(p=path)
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", "Mozilla/5.0")]
    html = op.open(ref).read().decode("utf-8", "ignore")
    tk = re.search(r'id="tk" value="([^"]+)"', html).group(1)
    form = {"tk": tk, "date": str(year), "datemonth": f"{year}" if month is None else f"{year}{month:02d}",
            "platform": "ASCII", "timeframe": "M1", "fxpair": "NSXUSD"}
    req = urllib.request.Request("https://www.histdata.com/get.php",
                                 data=urllib.parse.urlencode(form).encode(), headers={"Referer": ref})
    raw = op.open(req).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if name.endswith(".csv"):
                (OUT / name).write_bytes(z.read(name))
    print("got", path, flush=True)


def build() -> None:
    files = sorted(glob.glob(str(OUT / "DAT_ASCII_NSXUSD_M1_*.csv")))
    df = pd.concat([pd.read_csv(f, sep=";", header=None, names=["ts", "o", "h", "l", "c", "v"]) for f in files])
    loc = pd.to_datetime(df.ts, format="%Y%m%d %H%M%S").dt.tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT")
    df["t"] = (loc - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    df = df.dropna(subset=["t"])
    df["t"] = df.t.astype("int64")
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df = fix_clock(df)
    df[["t", "o", "h", "l", "c"]].to_csv(OUT / "nas100_m1.csv.gz", index=False, compression="gzip")
    print(len(df), "bars ->", OUT / "nas100_m1.csv.gz")


def fix_clock(df: pd.DataFrame) -> pd.DataFrame:
    """HistData's clock is New York time except in the weeks where US and EU
    daylight saving differ (March / late October): there it runs one hour
    behind. The index CFD pauses daily at 16:15 ET, so a pause that starts at
    15:15 marks a session whose stamps need +1 h. Days whose 09:30-16:00 data
    is incomplete after the fix (holes in the 2023 files) are dropped."""
    t = df.t.to_numpy()
    mod = lambda ts: ((pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").hour * 60 +
                       pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").minute))
    gap = np.flatnonzero(np.diff(t) >= 40 * 60)  # index of the last bar before a pause
    start_mod = np.asarray(mod(t[gap] + 60))
    shift = np.zeros(len(t), dtype="int64")
    prev_end = 0
    for g, sm in zip(gap, start_mod):
        if sm in (975, 915):  # daily pause at 16:15 (ok) or 15:15 (clock 1 h behind)
            if sm == 915:
                shift[prev_end:g + 1] = 3600
            prev_end = g + 1
    df = df.assign(t=t + shift).drop_duplicates("t").sort_values("t").reset_index(drop=True)
    loc = pd.to_datetime(df.t, unit="s", utc=True).dt.tz_convert("America/New_York")
    m = (loc.dt.hour * 60 + loc.dt.minute)
    rth = (m >= 570) & (m < 960)
    cnt = rth.groupby(loc.dt.date).sum()
    bad = set(cnt[(cnt > 0) & (cnt < 380)].index)  # 390 minutes in a full session
    keep = ~(loc.dt.date.isin(bad) & (m >= 240) & (m < 1020))  # drop that day's session hours
    print("clock-fixed bars:", int((shift > 0).sum()), " days dropped for holes:", len(bad))
    return df[keep.to_numpy()].reset_index(drop=True)


def main() -> None:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    last = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    last_month = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    OUT.mkdir(parents=True, exist_ok=True)
    for y in range(first, last + 1):
        try:  # finished years come as one file, the running year per month
            download(y, None)
        except Exception:
            for m in range(1, (last_month if y == last else 12) + 1):
                try:
                    download(y, m)
                except Exception as e:
                    print("missing", y, m, e)
    build()


if __name__ == "__main__":
    main()
