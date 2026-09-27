import grid
df = grid.run_grid("BOS", [3, 5], dict(last_entry=690, stop_buf=2, max_risk_atr=4, expiry=30), dict(
    entry=["market", "limit"], trend=["ema20_50", "ema9_21", "vwap"], pivot=[2, 3, 5], rr=[1.5, 2.0, 3.0], offset=[0, 2]),
    risk=dict(flat_mod=12*60))
df.to_csv("/tmp/claude-0/g_bos.csv", index=False)
print(df.sort_values("IS_PF", ascending=False).head(30).to_string(index=False))
