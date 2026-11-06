import numpy as np, pandas as pd, backtest as bt
df = pd.read_csv("data/SOLUSD_4H.csv", parse_dates=["time"])
rows = []
for side in ("long", "short"):
    for v in "ABC":
        for tr in (False, True):
            for ex in ("1", "2", "3", "swing"):
                t = bt.run(df, v, side, ex, trend=tr)
                if len(t) < 100: continue
                half = t["time"].iloc[len(t)//2]
                a, b = t[t.time < half], t[t.time >= half]
                se = t["gross"].std() / np.sqrt(len(t))
                # costuri reduse 0.10%/parte total (fee+slip) si doar stopuri >=2%
                big = t[t.risk_pct >= 0.02]
                lowcost = (t["gross"] - 2*0.0010/t["risk_pct"]).mean()
                lowcost_big = (big["gross"] - 2*0.0010/big["risk_pct"]).mean() if len(big) else np.nan
                rows.append(dict(side=side, var=v, trend=tr, exit=ex, n=len(t), gross=t.gross.mean(), t_stat=t.gross.mean()/se,
                                 gross_H1=a.gross.mean(), gross_H2=b.gross.mean(), net_cost0p1=lowcost, n_big=len(big), net0p1_stop2pct=lowcost_big))
r = pd.DataFrame(rows).sort_values("t_stat", ascending=False)
pd.set_option("display.width", 220)
print(r.head(8).round(3).to_string(index=False))
print("\nmax net cu cost 0.10%/parte:", r.net_cost0p1.max().round(3), " | max net + stop>=2%:", r.net0p1_stop2pct.max().round(3))
print("combinatii cu |t|>2:", (r.t_stat.abs() > 2).sum(), "din", len(r), "(de asteptat ~5% la intamplare)")
