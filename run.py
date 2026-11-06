#!/usr/bin/env python3
"""CLI: backtest sau scanare de semnale.

  python run.py --demo
  python run.py --csv date.csv --side both
  python run.py --symbol AAPL --timeframe 15Min --days 60
  python run.py --symbol BTC/USD --crypto --timeframe 1Hour --days 120 --scan
"""
import argparse
from dataclasses import fields

import pandas as pd

from alpaca_colude import StrategyParams, backtest
from alpaca_colude.data import fetch_alpaca, load_csv, synthetic_bars
from alpaca_colude.strategy import PocPullbackStrategy


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv"), ap.add_argument("--symbol")
    ap.add_argument("--demo", action="store_true", help="date sintetice")
    ap.add_argument("--crypto", action="store_true")
    ap.add_argument("--timeframe", default="15Min", help="ex: 5Min, 15Min, 1Hour, 1Day")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--side", default="both", choices=["long", "short", "both"])
    ap.add_argument("--risk", type=float, default=0.01, help="risc per trade (fracție din equity)")
    ap.add_argument("--scan", action="store_true", help="arată doar semnalul de pe ultima lumânare")
    for f in fields(StrategyParams):
        t = (lambda s: s.lower() in ("1", "true", "yes")) if f.type in (bool, "bool") else type(f.default)
        ap.add_argument(f"--{f.name.replace('_', '-')}", type=t, default=f.default)
    a = ap.parse_args()

    params = StrategyParams(**{f.name: getattr(a, f.name) for f in fields(StrategyParams)})
    if a.csv:
        df = load_csv(a.csv)
    elif a.symbol:
        df = fetch_alpaca(a.symbol, a.timeframe, a.days, a.crypto)
    elif a.demo:
        df = synthetic_bars()
    else:
        ap.error("dă --csv, --symbol sau --demo")

    if a.scan:
        last = len(df) - 1
        sig = [t for t in PocPullbackStrategy(params).run(df, a.side) if t.entry_idx == last]
        if not sig:
            print(f"{df.index[-1]}: niciun semnal pe ultima lumânare.")
        for t in sig:
            print(f"{df.index[-1]}: {t.side.upper()} entry={t.entry_price:.4f} stop={t.stop:.4f} "
                  f"target={t.target:.4f} RR={t.planned_rr:.2f} POC={t.poc:.4f}")
        return

    res = backtest(df, params, a.side, risk_pct=a.risk)
    pd.set_option("display.width", 200)
    print(res.trades.tail(15).to_string() if not res.trades.empty else "Niciun trade.")
    print("\n".join(f"{k:>14}: {v:.4f}" if isinstance(v, float) else f"{k:>14}: {v}" for k, v in res.stats.items()))


if __name__ == "__main__":
    main()
