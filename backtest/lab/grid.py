"""Evaluate many strategy configs in parallel. Selection is done on the
in-sample years (2023-2024) only; 2025-2026 is reported as out-of-sample."""
import itertools, multiprocessing as mp, sys
import pandas as pd
import common as C, engine as E, strategies as S

G = {}

def _one(args):
    name, tf, params, risk = args
    b, m = G[tf]
    cls = getattr(S, name)
    tr = E.run(b, m, lambda: cls(**params), E.Risk(**risk))
    i, o = C.split(tr)
    si, so = E.stats(i), E.stats(o)
    row = {"strat": name, "tf": tf, **params, **{f"r_{k}": v for k, v in risk.items()}}
    for pre, s in (("IS_", si), ("OOS_", so)):
        for k in ("n", "win%", "PF", "avgR", "net$", "maxDD$"):
            row[pre + k] = s.get(k)
    return row

def expand(base: dict, grid: dict):
    keys = list(grid)
    for vals in itertools.product(*grid.values()):
        d = dict(base); d.update(zip(keys, vals)); yield d

def run_grid(name, tfs, base, grid, risk=None, procs=4):
    risk = risk or {}
    for tf in tfs:
        G[tf] = C.data(tf)
    jobs = [(name, tf, p, risk) for tf in tfs for p in expand(base, grid)]
    with mp.get_context("fork").Pool(procs) as pool:
        rows = pool.map(_one, jobs, chunksize=1)
    return pd.DataFrame(rows)

pd.set_option("display.width", 300); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 500)
