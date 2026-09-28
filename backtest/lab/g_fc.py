import grid, sys
df = grid.run_grid("FirstCandle", [5], dict(min_body=0.1, trend="ema20_50", min_risk=5), dict(
    stop_atr=[0.075, 0.1, 0.15, 0.2], rr=[1.5, 2, 3, 4, 6, 10], be_at=[0, 1.0, 2.0]),
    risk=dict(flat_mod=955, max_trades=1))
df2 = grid.run_grid("FirstCandle", [5], dict(min_body=0.1, trend="ema20_50", min_risk=5), dict(
    stop_atr=[0.1, 0.15], rr=[2, 3, 10], be_at=[0]), risk=dict(flat_mod=720, max_trades=1))
df3 = grid.run_grid("FirstCandle", [5], dict(min_body=0.1, trend="ema20_50", min_risk=5, stop="orb"), dict(
    rr=[1, 1.5, 2, 3, 10], be_at=[0, 1.0]), risk=dict(flat_mod=955, max_trades=1))
import pandas as pd
df = pd.concat([df, df2, df3]); df.to_csv("/tmp/claude-0/g_fc.csv", index=False)
cols=[c for c in df.columns if c not in ("strat","tf","min_body","trend","min_risk")]
print(df[cols].sort_values("IS_PF", ascending=False).to_string(index=False))
