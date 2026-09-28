import pickle, sys, os
from pathlib import Path
import pandas as pd
import engine as E
CACHE = Path(os.environ.get("LAB_CACHE", Path(__file__).resolve().parents[1] / "data" / "hist"))

def data(tf, source="nas100"):
    f = CACHE / f"prep_{source}_{tf}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    bars, m1 = E.prepare(tf, source)
    f.write_bytes(pickle.dumps((bars, m1)))
    return bars, m1

def split(trades, cut=pd.Timestamp("2025-01-01").date()):
    return [t for t in trades if t.date < cut], [t for t in trades if t.date >= cut]
