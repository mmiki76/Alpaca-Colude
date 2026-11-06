"""Sweep la nivel HTF (low/high zi sau saptamana precedenta) pe 4H + simulare cont (equity 100 USD, 60% din equity per trade)."""
import sys, numpy as np, pandas as pd

START_EQ, FRAC = 100.0, 0.60
MAXBARS, SWING_N = 120, 20
COSTS = {"cost 0.30%/parte": 0.0030, "cost 0.10%/parte": 0.0010}   # fee + slippage per parte

def levels(df, kind):
    t = df["time"].dt.tz_localize(None)
    key = t.dt.floor("D") if kind == "D" else t.dt.to_period("W").dt.start_time
    step = pd.Timedelta(days=1 if kind == "D" else 7)
    lo = df.groupby(key)["low"].min(); hi = df.groupby(key)["high"].max()
    prev = key - step
    return lo.reindex(prev).values, hi.reindex(prev).values

def signal(df, kind, variant, side):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    plo, phi = levels(df, kind)
    po, ph, pl = (np.roll(x, 1) for x in (o, h, l))
    if side == "long":
        s = (l < plo) & (c > plo) & (np.roll(l, 1) >= plo)           # sweep proaspat + reclaim
        if variant == "B": s &= (c > po) & (c > o)
        if variant == "C": s &= (c > ph) & (c > o)
    else:
        s = (h > phi) & (c < phi) & (np.roll(h, 1) <= phi)
        if variant == "B": s &= (c < po) & (c < o)
        if variant == "C": s &= (c < pl) & (c < o)
    s[:2] = False
    return s

def trades(df, sig, side, exit_, trend):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    ema = df["close"].ewm(span=200, adjust=False).mean().values
    sg = 1 if side == "long" else -1
    out, i, n = [], 1, len(df)
    while i < n - 2:
        if not sig[i] or (trend and not ((c[i] > ema[i]) if sg == 1 else (c[i] < ema[i]))):
            i += 1; continue
        entry = o[i + 1]; stop = l[i] if sg == 1 else h[i]; risk = (entry - stop) * sg
        if risk <= 0: i += 1; continue
        if exit_ == "swing":
            tgt = h[max(0, i - SWING_N):i + 1].max() if sg == 1 else l[max(0, i - SWING_N):i + 1].min()
            if (tgt - entry) * sg <= 0: i += 1; continue
        else:
            tgt = entry + sg * float(exit_) * risk
        ex, j = None, i + 1
        for j in range(i + 1, min(n, i + 1 + MAXBARS)):
            if (l[j] <= stop) if sg == 1 else (h[j] >= stop): ex = stop; break
            if (h[j] >= tgt) if sg == 1 else (l[j] <= tgt): ex = tgt; break
        if ex is None: ex = c[j]
        out.append((df["time"].iloc[i + 1], (ex - entry) * sg / entry, risk / entry))   # return pe notional
        i = j + 1
    return pd.DataFrame(out, columns=["time", "ret", "risk_pct"])

def account(t, cost):
    eq, curve = START_EQ, [START_EQ]
    for r in t["ret"].values:
        eq += eq * FRAC * (r - 2 * cost)
        curve.append(eq)
    curve = np.array(curve); dd = (curve / np.maximum.accumulate(curve) - 1).min() * 100
    net = t["ret"].values - 2 * cost
    return dict(n=len(t), win=(net > 0).mean() * 100 if len(t) else np.nan, final=eq, ret=(eq / START_EQ - 1) * 100, mdd=dd)

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "ETHUSD"
    df = pd.read_csv(f"data/{sym}_4H.csv", parse_dates=["time"])
    half = df["time"].iloc[len(df) // 2]
    rows = []
    for kind in ("D", "W"):
        for side in ("long", "short"):
            for v in "ABC":
                sig = signal(df, kind, v, side)
                for tr in (False, True):
                    for ex in ("1", "2", "3", "swing"):
                        t = trades(df, sig, side, ex, tr)
                        if len(t) < 20: continue
                        g = (t["ret"] / t["risk_pct"])
                        row = dict(level=kind, side=side, var=v, ema=tr, exit=ex, n=len(t), gross_R=g.mean(),
                                   t=g.mean() / (g.std() / np.sqrt(len(t))), stop_med=t.risk_pct.median() * 100)
                        for name, cst in COSTS.items():
                            a = account(t, cst); b = account(t[t.time < half], cst); c2 = account(t[t.time >= half], cst)
                            row.update({f"{name}|all": a["ret"], f"{name}|mdd": a["mdd"], f"{name}|H1": b["ret"], f"{name}|H2": c2["ret"], f"{name}|win": a["win"]})
                        rows.append(row)
    r = pd.DataFrame(rows); r.to_csv(f"results_htf_{sym}.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    k = "cost 0.30%/parte"; k2 = "cost 0.10%/parte"
    print(f"{sym} | {len(r)} combinatii | impartire: H1 < {half:%Y-%m-%d} <= H2")
    print(f"Profitabile la {k}: {(r[k+'|all']>0).sum()} | la {k2}: {(r[k2+'|all']>0).sum()} | gross_R>0: {(r.gross_R>0).sum()} | |t|>2: {(r.t.abs()>2).sum()}")
    print("\nMediana pe nivel/latura (gross_R, return% cost 0.30, return% cost 0.10):")
    print(r.groupby(["level", "side"])[["gross_R", k+"|all", k2+"|all"]].median().round(3))
    print("\nTop 8 dupa t-stat:")
    cols = ["level", "side", "var", "ema", "exit", "n", "gross_R", "t", "stop_med", k+"|all", k+"|H1", k+"|H2", k2+"|all", k2+"|H1", k2+"|H2", k2+"|mdd"]
    print(r.sort_values("t", ascending=False)[cols].head(8).round(2).to_string(index=False))
    # selectie pe H1 (cost 0.10), validare pe H2
    best = r.sort_values(k2 + "|H1", ascending=False).head(5)
    print("\nTop 5 alesi pe H1 (cost 0.10%/parte), apoi verificati pe H2 (out-of-sample):")
    print(best[cols].round(2).to_string(index=False))
