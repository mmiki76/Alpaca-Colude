import os, sys, glob, itertools, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
from multiprocessing import Pool
from alpaca_colude import backtest, StrategyParams
S = sys.argv[1]
SPLIT = pd.Timestamp("2024-11-06", tz="UTC")
VARIANTS = [dict(sl=sl, rr=rr, swing_n=sn, min_move_atr=mm)
            for sl in (0.015, 0.02) for rr in (2.0, 2.5) for sn in (3, 5, 8) for mm in (1.0, 2.0, 3.0)]

def agg(p):
    if p.empty:
        return dict(n=0, wins=0, net=0.0, sumsq=0.0)
    return dict(n=len(p), wins=int((p.pnl > 0).sum()), net=float(p.pnl.sum()), sumsq=float((p.pnl ** 2).sum()))

def job(path):
    coin = os.path.basename(path)[:-4]
    df = pd.read_pickle(path)
    rows = []
    for i, v in enumerate(VARIANTS):
        prm = StrategyParams(fixed_stop_pct=v["sl"], tp_rr=v["rr"], swing_n=v["swing_n"], min_move_atr=v["min_move_atr"])
        r = backtest(df, prm, side="short", initial_equity=1000, fixed_notional=100, slippage_bps=2, entry_fee_bps=4, exit_fee_bps=2)
        t = r.trades
        for per, sub in (("train", t[t.exit_time < SPLIT] if not t.empty else t), ("test", t[t.exit_time >= SPLIT] if not t.empty else t)):
            rows.append(dict(coin=coin, vid=i, **v, period=per, **agg(sub)))
    return rows

if __name__ == "__main__":
    files = sorted(glob.glob(f"{S}/new15/*.pkl"))
    t0 = time.time(); out = []
    with Pool(4) as p:
        for k, rows in enumerate(p.imap_unordered(job, files), 1):
            out += rows
            print(f"{k}/{len(files)} {time.time()-t0:.0f}s", flush=True)
    pd.DataFrame(out).to_csv(f"{S}/grid_short.csv", index=False)
    print("done")
