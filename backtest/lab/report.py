"""Final strategy report: MNQ Opening Drive (M5).

    python backtest/lab/report.py          # needs data/hist/nas100_m1.csv.gz (fetch_histdata.py)
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import common as C, engine as E, strategies as S

FINAL = dict(orb=5, min_body=0.10, trend="ema20_50", stop_atr=0.10, rr=10.0, be_at=2.0, min_risk=5)
RISK = dict(risk_usd=150, flat_mod=955, max_trades=1)
OUT = Path(__file__).resolve().parents[1] / "results"


def run(tf=5, params=FINAL, risk=RISK, bars_m1=None):
    b, m = bars_m1 or C.data(tf)
    return E.run(b, m, lambda: S.FirstCandle(**params), E.Risk(**risk)), b


def main():
    pd.set_option("display.width", 200)
    OUT.mkdir(exist_ok=True)
    tr, b = run()
    sessions = sorted(E.cached(b, C.data(5)[1])["levels"])
    i, o = C.split(tr)
    print("MNQ Opening Drive, M5, $150 risk/trade, costs: $0.80/side/contract + 1 tick slippage")
    print(pd.DataFrame([E.stats(i, "2023-2024 (in-sample)"), E.stats(o, "2025-2026 (out-of-sample)"),
                        E.stats(tr, "all")]).to_string(index=False))
    print("\nper year"); print(E.by_period(tr).to_string(index=False))
    print("\nlong / short")
    print(pd.DataFrame([E.stats([t for t in tr if t.side > 0], "long"), E.stats([t for t in tr if t.side < 0], "short")]).to_string(index=False))
    rows = []
    for risk in (100, 150, 200, 250):
        t2, _ = run(risk=dict(RISK, risk_usd=risk))
        for name, kw in (("Topstep-like 50k (EOD trail 2000, DLL 1000)", dict(max_dd=2000, daily_limit=1000, eod_trailing=True)),
                         ("Apex-like 50k (intraday trail 2500)", dict(max_dd=2500, daily_limit=1e9, eod_trailing=False))):
            rows.append(dict(risk_usd=risk, rules=name, **E.prop_sim(t2, target=3000, sessions=sessions, **kw)))
    print("\nprop challenge simulation (a new challenge started on every session)")
    print(pd.DataFrame(rows).to_string(index=False))
    df = E.trades_df(tr)
    df.to_csv(OUT / "opening_drive_trades.csv", index=False)
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        eq = df.pnl.cumsum()
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(pd.to_datetime(df.date), eq, color="#1f6feb")
        ax.axvline(pd.Timestamp("2025-01-01"), color="grey", ls="--", lw=1)
        ax.text(pd.Timestamp("2025-01-10"), eq.min(), "out-of-sample", color="grey")
        ax.set_title("MNQ Opening Drive (M5) - equity, $150 risk per trade, net of costs")
        ax.set_ylabel("$"); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(OUT / "opening_drive_equity.png", dpi=110)
        print("\nwrote", OUT / "opening_drive_equity.png")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
