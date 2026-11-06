"""Backtest: sweep + engulfing pe 4H (strategia din transcripturi).
Variante semnal: A (sweep+close peste low anterior), B (engulfing strict: close>open anterior),
C (engulfing larg: close>high anterior). Intrare la open-ul lumanarii urmatoare, SL la extremul sweep-ului.
Rezultate in R (1R = distanta entry-SL). Costuri: fee per parte + slippage per parte, in % din pret.
"""
import sys, numpy as np, pandas as pd

FEE = 0.0025      # Alpaca crypto taker tier 1: 0.25% / parte
SLIP = 0.0005     # 0.05% / parte
MAXBARS = 120     # time stop (20 zile)
SWING_N = 20

def signals(df, variant, side):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    po, ph, pl, pc = (np.roll(x, 1) for x in (o, h, l, c))
    if side == "long":
        sweep = l < pl
        if variant == "A": ok = c > pl
        elif variant == "B": ok = (c > po) & (c > o)
        else: ok = (c > ph) & (c > o)
    else:
        sweep = h > ph
        if variant == "A": ok = c < ph
        elif variant == "B": ok = (c < po) & (c < o)
        else: ok = (c < pl) & (c < o)
    s = sweep & ok
    s[0] = False
    return s

def run(df, variant, side, exit_, trend=False, costs=True):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    ema = df["close"].ewm(span=200, adjust=False).mean().values
    sig = signals(df, variant, side)
    sgn = 1 if side == "long" else -1
    n = len(df); trades = []; i = 1
    while i < n - 2:
        if not sig[i]:
            i += 1; continue
        if trend and not ((c[i] > ema[i]) if side == "long" else (c[i] < ema[i])):
            i += 1; continue
        entry = o[i + 1]
        stop = l[i] if side == "long" else h[i]
        risk = (entry - stop) * sgn
        if risk <= 0:
            i += 1; continue
        if exit_ == "swing":
            tgt = h[max(0, i - SWING_N):i + 1].max() if side == "long" else l[max(0, i - SWING_N):i + 1].min()
            if (tgt - entry) * sgn <= 0:
                i += 1; continue
        else:
            tgt = entry + sgn * float(exit_) * risk
        ex, j = None, i + 1
        for j in range(i + 1, min(n, i + 1 + MAXBARS)):
            hit_s = (l[j] <= stop) if side == "long" else (h[j] >= stop)
            hit_t = (h[j] >= tgt) if side == "long" else (l[j] <= tgt)
            if hit_s: ex = stop; break          # conservator: SL primul daca ambele in aceeasi bara
            if hit_t: ex = tgt; break
        if ex is None:
            ex = c[j]
        gross = (ex - entry) * sgn / risk
        cost = (2 * (FEE + SLIP) * entry / risk) if costs else 0.0
        trades.append((df["time"].iloc[i + 1], gross, gross - cost, risk / entry))
        i = j + 1                                  # o singura pozitie odata
    return pd.DataFrame(trades, columns=["time", "gross", "net", "risk_pct"])

def stats(t):
    if len(t) == 0:
        return dict(n=0, win=np.nan, exp_g=np.nan, exp_n=np.nan, pf=np.nan, totR=np.nan, mdd=np.nan, risk=np.nan)
    net = t["net"].values; cum = net.cumsum()
    gp, gl = net[net > 0].sum(), -net[net < 0].sum()
    return dict(n=len(t), win=(t["gross"] > 0).mean() * 100, exp_g=t["gross"].mean(), exp_n=net.mean(),
                pf=gp / gl if gl > 0 else np.inf, totR=cum[-1], mdd=(cum - np.maximum.accumulate(cum)).min(),
                risk=t["risk_pct"].median() * 100)

if __name__ == "__main__":
    df = pd.read_csv("data/SOLUSD_4H.csv", parse_dates=["time"])
    # verifica goluri in date
    gaps = (df["time"].diff().dropna() > pd.Timedelta(hours=4)).sum()
    print(f"Bare: {len(df)}  {df.time.min():%Y-%m-%d} -> {df.time.max():%Y-%m-%d}  goluri: {gaps}\n")
    exits = ["1", "2", "3", "swing"]
    rows = []
    for side in ("long", "short"):
        for v in "ABC":
            for tr in (False, True):
                for ex in exits:
                    t = run(df, v, side, ex, trend=tr)
                    s = stats(t); s.update(side=side, var=v, trend="EMA200" if tr else "-", exit="RR" + ex if ex != "swing" else "swing")
                    rows.append(s)
    r = pd.DataFrame(rows)[["side", "var", "trend", "exit", "n", "win", "exp_g", "exp_n", "pf", "totR", "mdd", "risk"]]
    pd.set_option("display.width", 200, "display.max_rows", 500)
    r.to_csv("results_all.csv", index=False)
    print(r.round(3).to_string(index=False))
