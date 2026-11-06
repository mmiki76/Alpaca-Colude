import os, sys, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pandas as pd
from multiprocessing import Pool
from alpaca_colude import backtest, StrategyParams
S = sys.argv[1]
PRM = StrategyParams(fixed_stop_pct=0.02, tp_rr=2.5, swing_n=5, min_move_atr=3.0)
def job(path):
    coin = os.path.basename(path)[:-4]
    df = pd.read_pickle(path)
    out = {}
    for tag, (fi, fo) in {"base": (4, 2), "stress": (5, 5)}.items():     # base = fees tale; stress = 0,05% taker pe ambele părți
        t = backtest(df, PRM, side="short", initial_equity=1000, fixed_notional=100, slippage_bps=2, entry_fee_bps=fi, exit_fee_bps=fo).trades
        if not t.empty:
            t.insert(0, "coin", coin); t["fees"] = tag
        out[tag] = t
    return pd.concat(out.values())
if __name__ == "__main__":
    with Pool(4) as p:
        res = pd.concat(p.map(job, sorted(glob.glob(f"{S}/new15/*.pkl"))))
    res.to_csv(f"{S}/best_trades/vid32_trades.csv", index=False)
    print(len(res), res.fees.value_counts().to_dict())
