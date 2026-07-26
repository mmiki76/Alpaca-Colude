#!/bin/bash
# Actualizeaza botul pe VPS
set -e

APP_DIR="/opt/clode-binance"
cd "$APP_DIR"

echo "Opresc serviciul..."
sudo systemctl stop clode-binance

echo "Pull cod nou..."
git pull origin claude/binance-interconectare-rlrvke

echo "Actualizez dependintele..."
source venv/bin/activate
pip install -r requirements.txt

echo "Repornesc serviciul..."
sudo systemctl start clode-binance
sudo systemctl status clode-binance --no-pager

echo "=== Update complet! ==="
