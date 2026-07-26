#!/bin/bash
# Script de instalare pe Oracle VPS (Ubuntu 22.04)
set -e

echo "=== Clode - Binance Bot Install ==="

# Update sistem
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw nginx

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

# Configureaza nginx ca reverse proxy (port 80 → 8080)
sudo cp scripts/nginx-clode.conf /etc/nginx/sites-available/clode-binance
sudo ln -sf /etc/nginx/sites-available/clode-binance /etc/nginx/sites-enabled/clode-binance
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx

# Firewall - permite port 80 (nginx) si SSH
sudo ufw allow 80/tcp
sudo ufw allow OpenSSH
sudo ufw --force enable

echo ""
echo "=== Instalare completa! ==="
echo "1. Editeaza .env: nano $APP_DIR/.env"
echo "2. Asigura-te ca PORT=8080 in .env (nginx face proxy pe 80→8080)"
echo "3. Porneste serviciul: sudo systemctl start clode-binance"
echo "4. Vezi loguri: sudo journalctl -u clode-binance -f"
echo ""
echo "URL webhook pentru TradingView: http://IP_VPS_TAU/webhook"
