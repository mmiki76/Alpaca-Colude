#!/usr/bin/env python3
"""Scanner în timp real pentru VET (short, 15m) cu mărime COMPUSĂ (intri cu tot equity-ul curent).

NU trimite ordine: îți spune când să intri, cu ce mărime și unde să pui SL/TP; apoi urmărește poziția
și, când lumânările ating SL sau TP, actualizează equity-ul (câștigul/pierderea intră în mărimea următorului trade).

  python scan_live.py --equity 100                  # pornește scanner continuu (stare în vet_state.json)
  python scan_live.py --once                        # o singură verificare, apoi iese (bun pentru cron)
  python scan_live.py --equity 100 --leverage 3     # intri cu 3 x equity
  python scan_live.py --set-equity 107.5            # sincronizează equity-ul cu contul tău real
  python scan_live.py --replay data.csv --replay-bars 4000 --equity 100   # test offline pe istoric

Surse de date (publice, fără chei): Binance USDT-M futures (implicit) sau --market spot.
Dacă Binance e blocat în țara/rețeaua ta, folosește --replay cu un CSV sau alt acces la API.
"""
import argparse
import os
import sys
import time

import pandas as pd

from alpaca_colude.live import BEST_PARAMS, LiveScanner, ScannerState, fetch_klines

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def now() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")


def load_state(a) -> ScannerState:
    if os.path.exists(a.state):
        s = ScannerState.load(a.state)
        s.leverage = a.leverage if a.leverage is not None else s.leverage
        return s
    return ScannerState(equity=a.equity, leverage=a.leverage or 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="VETUSDT")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--market", default="futures", choices=["futures", "spot"])
    ap.add_argument("--equity", type=float, default=100.0, help="equity de pornire (doar la prima rulare)")
    ap.add_argument("--leverage", type=float, default=None, help="notional = equity * leverage (implicit 1 = tot equity)")
    ap.add_argument("--state", default="vet_state.json", help="fișier cu starea (equity, poziție, istoric)")
    ap.add_argument("--poll", type=int, default=15, help="secunde între verificări")
    ap.add_argument("--window", type=int, default=1500, help="câte lumânări folosește strategia")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--set-equity", type=float, help="suprascrie equity-ul din stare (sincronizare cu contul real)")
    ap.add_argument("--close-position", action="store_true", help="uită poziția deschisă (ai închis-o manual)")
    ap.add_argument("--replay", help="CSV/PKL cu istoric: simulează scannerul pe ultimele --replay-bars lumânări")
    ap.add_argument("--replay-bars", type=int, default=4000)
    a = ap.parse_args()

    if a.replay:
        from alpaca_colude.data import load_csv
        df = pd.read_pickle(a.replay) if a.replay.endswith(".pkl") else load_csv(a.replay)
        st = ScannerState(equity=a.equity, leverage=a.leverage or 1.0,
                          last_bar=df.index[len(df) - a.replay_bars - 1].isoformat())
        sc = LiveScanner(st, BEST_PARAMS, a.window)
        for line in sc.process(df):
            print(line)
        print(f"\nReplay {a.replay_bars} lumânări: {len(st.trades)} trade-uri închise, equity {a.equity:.2f} -> {st.equity:.2f} "
              f"({(st.equity / a.equity - 1) * 100:+.1f}%)" + (f" | poziție deschisă acum" if st.position else ""))
        return

    st = load_state(a)
    if a.set_equity is not None:
        st.equity = a.set_equity
        st.save(a.state)
        print(f"Equity setat la {st.equity:.2f}")
        return
    if a.close_position:
        st.position = None
        st.save(a.state)
        print("Poziția a fost ștearsă din stare.")
        return

    sc = LiveScanner(st, BEST_PARAMS, a.window)
    print(f"[{now()}] Scanner {a.symbol} {a.interval} ({a.market}) | SHORT | SL 2% / TP 5% | equity {st.equity:.2f} x {st.leverage:g} | stare: {a.state}")
    last_print_bar, last_print_t = None, 0.0
    while True:
        try:
            df = fetch_klines(a.symbol, a.interval, a.window + 5, a.market)
            for line in sc.process(df):
                print(f"[{now()}] {line}", flush=True)
                if "SEMNAL" in line or "STOP" in line or "TARGET" in line:
                    print("\a", end="", flush=True)                 # beep în terminal
            st.save(a.state)
            if df.index[-1] != last_print_bar or time.time() - last_print_t > 300:     # lumânare nouă sau heartbeat la 5 min
                print(f"[{now()}] {df.index[-1]} închis @ {df['close'].iloc[-1]:.5f} | {sc.status(df['close'].iloc[-1])}", flush=True)
                last_print_bar, last_print_t = df.index[-1], time.time()
        except Exception as e:                                       # rețea, rate-limit etc.: reîncearcă
            print(f"[{now()}] eroare: {e}", file=sys.stderr, flush=True)
        if a.once:
            return
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
