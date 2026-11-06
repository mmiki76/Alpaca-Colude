#!/usr/bin/env python3
"""Bot PAPER pentru Binance Futures (testnet/demo) + dashboard local.

  # 1) chei de TESTNET (nu de cont real!) în variabile de mediu – NU le pune în fișiere sau în chat
  export BINANCE_TESTNET_API_KEY=...   BINANCE_TESTNET_API_SECRET=...
  python paper_bot.py --selftest            # verifică tot ciclul (ordine, SL, TP, anulare) cu mărime minimă
  python paper_bot.py                       # pornește botul + dashboard pe http://127.0.0.1:8765
  python paper_bot.py --leverage 3 --equity 100

  # fără chei: simulare pe istoric (dashboard live), ca să vezi cum arată
  python paper_bot.py --sim vet.pkl --sim-bars 6000 --sim-delay 0.02

Setările (leverage, mărime, SL, TP...) se schimbă din dashboard și se salvează în bot_config.json.
Mainnet NU e suportat intenționat.
"""
import argparse
import json
import os
import sys
import threading
import time
from dataclasses import asdict

import pandas as pd

from alpaca_colude.bot import BotConfig, PaperBot, make_data_fn, run_forever, selftest
from alpaca_colude.dashboard import serve
from alpaca_colude.exchange import BinanceFuturesTestnet, SimExchange


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="bot_config.json")
    ap.add_argument("--state", default="bot_state.json")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--symbol")
    ap.add_argument("--leverage", type=int)
    ap.add_argument("--equity", type=float, help="equity de start (doar dacă nu există încă stare)")
    ap.add_argument("--base-url", help="testnet.binancefuture.com (implicit) sau demo-fapi.binance.com")
    ap.add_argument("--sim", help="fișier .pkl/.csv cu istoric: rulează o SIMULARE (fără Binance)")
    ap.add_argument("--sim-bars", type=int, default=6000)
    ap.add_argument("--sim-delay", type=float, default=0.0, help="secunde între lumânări în simulare")
    a = ap.parse_args()

    cfg = BotConfig.from_dict(json.load(open(a.config))) if os.path.exists(a.config) else BotConfig()
    for name in ("symbol", "leverage", "base_url"):
        if getattr(a, name) is not None:
            setattr(cfg, name, getattr(a, name))
    if a.equity is not None:
        cfg.start_equity = a.equity
    cfg.validate()

    if a.sim:
        from alpaca_colude.data import load_csv
        df = pd.read_pickle(a.sim) if a.sim.endswith(".pkl") else load_csv(a.sim)
        ex = SimExchange()
        bot = PaperBot(cfg, ex, lambda c: df.iloc[: i + 1], None, None)       # stare în memorie, nu scrie fișiere
        step = 15 * 60 * 1000
        n0 = len(df) - a.sim_bars
        srv = None if a.no_dashboard else serve(bot, a.port)
        if srv:
            print(f"Dashboard simulare: http://127.0.0.1:{srv.server_address[1]}")
        for i in range(n0, len(df)):
            r = df.iloc[i]
            ex.feed(int(df.index[i].timestamp() * 1000), r.open, r.high, r.low, r.close)
            bot.tick()
            if a.sim_delay:
                time.sleep(a.sim_delay)
        s = bot.snapshot()
        print(f"Simulare gata: {s['stats']['trades']} trade-uri, equity {cfg.start_equity:.2f} -> {s['equity']:.2f} ({s['return_pct']:+.1f}%)")
        if srv:
            print("Dashboard rămâne pornit (Ctrl+C pentru ieșire).")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
        return 0

    key, secret = os.environ.get("BINANCE_TESTNET_API_KEY"), os.environ.get("BINANCE_TESTNET_API_SECRET")
    if not key or not secret:
        print("Lipsesc BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (chei de testnet, în variabile de mediu).", file=sys.stderr)
        return 2
    ex = BinanceFuturesTestnet(key, secret, cfg.base_url)
    if a.selftest:
        return 0 if selftest(ex, cfg) else 1

    bot = PaperBot(cfg, ex, make_data_fn(ex), a.state, a.config)
    with open(a.config, "w") as f:
        json.dump(asdict(bot.cfg), f, indent=1)
    srv = None if a.no_dashboard else serve(bot, a.port)
    print(f"PAPER {cfg.symbol} {cfg.interval} {cfg.side} | leverage {cfg.leverage}x | equity {bot.state.equity:.2f} | {cfg.base_url}")
    if srv:
        print(f"Dashboard: http://127.0.0.1:{srv.server_address[1]}   (Ctrl+C pentru oprire; starea se salvează în {a.state})")
    try:
        run_forever(bot)
    except KeyboardInterrupt:
        print("Oprit. Poziția deschisă (dacă există) rămâne pe exchange cu SL/TP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
