import sys, grid
df = grid.run_grid("ORB", [3, 5], dict(mode="break", last_entry=690), dict(
    orb=[5, 15, 30], trend=["none", "ema20_50", "vwap"], stop=["mid", "opp", "atr"], rr=[1.0, 1.5, 2.0, 3.0]),
    risk=dict(flat_mod=12*60))
df.to_csv("/tmp/claude-0/g_orb.csv", index=False)
print(df.sort_values("IS_PF", ascending=False).head(30).to_string(index=False))
