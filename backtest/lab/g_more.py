import grid, pandas as pd
cols=["strat","tf","mode","orb","trend","stop","offset","rr","fake_bars","fake_mid","rsi_confirm","rsi_div","ad_div","IS_n","IS_PF","IS_avgR","OOS_n","OOS_PF","OOS_avgR"]
R=dict(flat_mod=12*60)
a = grid.run_grid("ORB", [3, 5], dict(mode="retest", last_entry=690, expiry=45), dict(
    orb=[5, 15], trend=["none", "ema20_50"], stop=["mid", "atr"], offset=[-2.0, 0.0, 2.0, 5.0], rr=[1.5, 2.0, 3.0]), risk=R)
b = grid.run_grid("ORB", [3, 5], dict(mode="fakeout", last_entry=690), dict(
    orb=[5, 15, 30], trend=["none", "ema20_50"], fake_bars=[2, 4], fake_mid=[False, True], rr=[1.0, 2.0, 3.0], rsi_confirm=[0, 1]), risk=R)
c = grid.run_grid("Sweep", [3, 5], dict(last_entry=690, max_risk_atr=4, confirm=8, pivot=3, orb_levels=15), dict(
    entry=["market", "limit"], trend=["none", "ema20_50"], rsi_div=[False, True], ad_div=[False, True], rr=[1.5, 2.0, 3.0]), risk=R)
for name, df in (("ORB double tap / retest", a), ("ORB fakeout", b), ("Sweep+CHoCH with RSI/AD", c)):
    df.to_csv(f"/tmp/claude-0/g_more_{name[:5]}.csv", index=False)
    print("==", name, len(df), "variants")
    print(df[[k for k in cols if k in df]].sort_values("IS_PF", ascending=False).head(8).to_string(index=False))
    print("best OOS PF among variants with OOS_n>=50:", df[df.OOS_n >= 50].OOS_PF.max())
