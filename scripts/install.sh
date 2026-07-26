#!/bin/bash
# Script de instalare pe Oracle VPS (Ubuntu 22.04)
set -e

echo "=== Clode - Binance Bot Install ==="

# Update sistem
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw

# Cloneaza repo (daca nu exista deja)
APP_DIR="/opt/clode-binance"
if [ ! -d "$APP_DIR" ]; then
    sudo git clone https://github.com/mmiki76/alpaca-colude.git "$APP_DIR"
fi
sudo chown -R $USER:$USER "$APP_DIR"

# Creeaza virtual environment
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install pydantic-settings
pip install -r requirements.txt

# Copiaza .env
if [ ! -f "$APP_DIR/.env" ]; then
    cp config/.env.example .env
    echo ""
    echo "IMPORTANT: Editeaza $APP_DIR/.env cu cheile tale Binance!"
    echo "  nano $APP_DIR/.env"
fi

# Creeaza directorul de loguri
mkdir -p "$APP_DIR/logs"

# Instaleaza serviciu systemd
sudo cp scripts/clode-binance.service /etc/systemd/system/
sudo sed -i "s|/opt/clode-binance|$APP_DIR|g" /etc/systemd/system/clode-binance.service
sudo sed -i "s|USER_PLACEHOLDER|$USER|g" /etc/systemd/system/clode-binance.service
sudo systemctl daemon-reload
sudo systemctl enable clode-binance

# Firewall - permite port 8080
sudo ufw allow 8080/tcp
sudo ufw allow OpenSSH
sudo ufw --force enable

echo ""
echo "=== Instalare completa! ==="
echo "1. Editeaza .env: nano $APP_DIR/.env"
echo "2. Porneste serviciul: sudo systemctl start clode-binance"
echo "3. Vezi loguri: sudo journalctl -u clode-binance -f"
echo ""
echo "URL webhook pentru TradingView: http://IP_VPS_TAU:8080/webhook"
