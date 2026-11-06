import sys, numpy as np, pandas as pd, backtest as bt
pd.set_option("display.width", 220)
for sym in sys.argv[1:]:
    df = pd.read_csv(f"data/{sym}_4H.csv", parse_dates=["time"])
    rows = []
    for side in ("long", "short"):
        for v in "ABC":
            for tr in (False, True):
                for ex in ("1", "2", "3", "swing"):
                    t = bt.run(df, v, side, ex, trend=tr)
                    if len(t) < 30: continue
                    se = t["gross"].std() / np.sqrt(len(t))
                    low = (t["gross"] - 2*0.0010/t["risk_pct"]).mean()
                    h = t["time"].iloc[len(t)//2]
                    rows.append(dict(side=side, var=v, ema=tr, exit=ex, n=len(t), win=(t.gross>0).mean()*100, gross=t.gross.mean(),
                        t=t.gross.mean()/se, net=t.net.mean(), net_lowcost=low, g_H1=t[t.time<h].gross.mean(), g_H2=t[t.time>=h].gross.mean(), risk=t.risk_pct.median()*100))
    r = pd.DataFrame(rows)
    print(f"\n=== {sym}: {len(df)} bare {df.time.min():%Y-%m-%d}..{df.time.max():%Y-%m-%d}, {len(r)} combinatii ===")
    print(f"net (0.30%/parte) > 0: {(r.net>0).sum()} | net_lowcost (0.10%/parte) > 0: {(r.net_lowcost>0).sum()} | gross>0: {(r.gross>0).sum()} | |t|>2: {(r.t.abs()>2).sum()}")
    print(f"gross: min {r.gross.min():.3f} max {r.gross.max():.3f} | net: min {r.net.min():.3f} max {r.net.max():.3f} | mediana risc stop {r.risk.median():.2f}%")
    print(r.sort_values("t", ascending=False).head(5).round(3).to_string(index=False))
    r.to_csv(f"results_{sym}.csv", index=False)
