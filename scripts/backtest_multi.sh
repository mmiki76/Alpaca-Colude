#!/bin/bash
cd /opt/clode-binance

for SYMBOL in HYPE/USDT QNT/USDT; do
  for TF in 5m 15m 30m 1h 4h; do
    echo "--- $SYMBOL $TF ---"
    python3 scripts/backtest.py $TF $SYMBOL 90 2 2>&1 | grep -E "^ >>>"
  done
done
