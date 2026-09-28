import grid
df = grid.run_grid("Sweep", [3, 5], dict(last_entry=690, stop_buf=2, max_risk_atr=4), dict(
    entry=["market", "limit"], fib=[0.5], trend=["none", "ema20_50"], confirm=[4, 8], pivot=[2, 3],
    rr=[1.5, 2.0, 3.0], orb_levels=[0, 15]),
    risk=dict(flat_mod=12*60))
df.to_csv("/tmp/claude-0/g_sweep.csv", index=False)
print(df.sort_values("IS_PF", ascending=False).head(30).to_string(index=False))
