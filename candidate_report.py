"""Candidatul comun: sweep pe low-ul zilei precedente, long, varianta A, filtru EMA200. Cont 100 USD, 60% din equity, compounding."""
import numpy as np, pandas as pd, htf_backtest as hb
pd.set_option("display.width", 220)
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    df = pd.read_csv(f"data/{sym}_4H.csv", parse_dates=["time"])
    bh = (df.close.iloc[-1] / df.open.iloc[0] - 1) * 100
    sig = hb.signal(df, "D", "A", "long")
    print(f"\n=== {sym} | {df.time.iloc[0]:%Y-%m-%d} -> {df.time.iloc[-1]:%Y-%m-%d} | buy&hold {bh:+.0f}% ===")
    for ex in ("2", "3", "swing"):
        t = hb.trades(df, sig, "long", ex, True)
        line = [f"RR{ex}" if ex != "swing" else "swing", f"n={len(t)}"]
        for name, c in (("0.07%", 0.0007), ("0.15%", 0.0015)):
            eq = 100.0; yr = {}
            for tm, r in zip(t.time, t.ret):
                y = tm.year; yr.setdefault(y, [eq, eq]); eq += eq * hb.FRAC * (r - 2 * c); yr[y][1] = eq
            a = hb.account(t, c)
            line.append(f"cost {name}: 100->{a['final']:.0f} ({a['ret']:+.0f}%, win {a['win']:.0f}%, DD {a['mdd']:.0f}%)")
            if name == "0.07%":
                yrs = "  ".join(f"{y}:{(v[1]/v[0]-1)*100:+.0f}%" for y, v in sorted(yr.items()))
        print("  " + " | ".join(line)); print("     pe ani (0.07%): " + yrs)
