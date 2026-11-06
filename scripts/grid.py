import sys, os, itertools, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
from multiprocessing import Pool
from alpaca_colude import backtest, StrategyParams
from alpaca_colude.data import load_csv
S = sys.argv[1]
COINS = ("SOL","ETH","INJ","STX","ZEC","BTC","BNB","XRP","DOGE","AVAX","ADA","LINK","LTC","DOT","SUI")
TFS = ("15m","30m","1h","2h","4h")
COMBOS = [(sl, rr) for sl in (0.015, 0.02) for rr in (2.0, 2.5)]

def stats(t):
    if t.empty:
        return dict(trades=0, wins=0, win_rate=np.nan, net_pnl=0.0, avg_pnl=np.nan, max_dd=0.0, profit_factor=np.nan)
    t = t.sort_values("exit_time")
    cum = np.concatenate([[0.0], t.pnl.cumsum().to_numpy()])
    w, lo = t.loc[t.pnl > 0, "pnl"].sum(), -t.loc[t.pnl <= 0, "pnl"].sum()
    return dict(trades=len(t), wins=int((t.pnl > 0).sum()), win_rate=float((t.pnl > 0).mean()), net_pnl=float(t.pnl.sum()),
                avg_pnl=float(t.pnl.mean()), max_dd=float((cum - np.maximum.accumulate(cum)).min()),
                profit_factor=float(w / lo) if lo > 0 else np.inf)

def job(a):
    coin, tf = a
    df = load_csv(f"{S}/f2y/{coin}_{tf}.csv")
    mid = df.index[0] + (df.index[-1] - df.index[0]) / 2
    rows = []
    for sl, rr in COMBOS:
        prm = StrategyParams(fixed_stop_pct=sl, tp_rr=rr)
        r = backtest(df, prm, side="both", initial_equity=1000, fixed_notional=100, slippage_bps=2, entry_fee_bps=2, exit_fee_bps=4)
        t = r.trades
        if not t.empty:
            t = t.assign(period=np.where(t.exit_time < mid, "y1", "y2"))
        for side in ("all", "long", "short"):
            ts = t if (side == "all" or t.empty) else t[t.side == side]
            for per in ("all", "y1", "y2"):
                tp = ts if (per == "all" or ts.empty) else ts[ts.period == per]
                rows.append(dict(coin=coin, tf=tf, sl=sl, rr=rr, side=side, period=per, **stats(tp)))
        t.to_csv(f"{S}/grid_trades/{coin}_{tf}_sl{sl}_rr{rr}.csv", index=False)
    return rows

if __name__ == "__main__":
    os.makedirs(f"{S}/grid_trades", exist_ok=True)
    jobs = [(c, tf) for tf in TFS[::-1] for c in COINS]    # 4h primele (rapide), 15m ultimele
    t0 = time.time(); out = []
    with Pool(os.cpu_count()) as p:
        for i, rows in enumerate(p.imap_unordered(job, jobs), 1):
            out += rows
            print(f"{i}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    pd.DataFrame(out).to_csv(f"{S}/grid_results.csv", index=False)
    print("done")
