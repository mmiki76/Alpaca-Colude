# Clode - Setup Notes
Data: 2026-07-26

## VPS Oracle Cloud
- **IP**: 92.5.99.56
- **OS**: Ubuntu 22.04 aarch64
- **User**: ubuntu
- **SSH key**: ssh-key-2026-07-25.key (in ~/Downloads pe laptop)
- **Conectare**: `ssh -i ~/Downloads/ssh-key-2026-07-25.key ubuntu@92.5.99.56`

## Servicii active pe VPS

### 1. Clode Bot (MEXC Trading)
- **Serviciu**: `clode-binance.service` (systemd)
- **Director**: `/opt/clode-binance/`
- **Port intern**: 8080 (nginx face proxy pe 80)
- **Config**: `/opt/clode-binance/.env`
- **Loguri**: `sudo journalctl -u clode-binance -f`
- **Restart**: `sudo systemctl restart clode-binance`

#### .env (structura)
```
EXCHANGE=mexc
API_KEY=...
API_SECRET=...
TESTNET=False
MARKET_TYPE=SPOT
WEBHOOK_SECRET=*** (vezi .env pe VPS)
ORDER_SIZE_USDT=20.0
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=929910942
PORT=8080
```

#### TradingView Webhook
- **URL**: `http://92.5.99.56/webhook`
- **Secret**: Mmiki76Clode2026xK9mP2qR
- **Pereche**: SNDKONUSDT
- **Exchange**: MEXC Spot
- **Strategie**: MACD pe 4h

### 2. Alpaca Trading Monitor
- **Script**: `/home/ubuntu/notify_telegram.py`
- **Log**: `/home/ubuntu/notify_telegram.log`
- **Cron**: `0 */3 * * *` (la fiecare 3 ore)
- **Conturi monitorizate**: Alpaca Claude Automat Trading, TradingView, Alpaca-100.000
- **Telegram Chat ID**: 929910942

### 3. Trailing Stop Bot
- **Script**: `/home/ubuntu/trailing_stop_bot.py`
- **Log**: `/home/ubuntu/trailing_stop_bot.log`
- **State**: `/home/ubuntu/trailing_stop_state.json`
- **Pornire**: `@reboot` via cron (cu variabile ALPACA_API_KEY_ID si ALPACA_API_SECRET_KEY)

## Nginx
- **Config**: `/etc/nginx/sites-available/clode-binance`
- **Rol**: Proxy port 80 → localhost:8080
- **Restart**: `sudo systemctl restart nginx`

## Firewall (iptables)
- Port 22 (SSH) - ACCEPT
- Port 80 (nginx) - ACCEPT
- Port 8080 (bot direct) - ACCEPT
- Salvat cu: `sudo netfilter-persistent save`

## Comenzi utile
```bash
# Status servicii
sudo systemctl status clode-binance
sudo systemctl status nginx
crontab -l

# Loguri bot
sudo journalctl -u clode-binance -f

# Update bot din GitHub
cd /opt/clode-binance
sudo git pull origin claude/binance-interconectare-rlrvke
sudo systemctl restart clode-binance

# Test webhook local
curl http://localhost/health

# Rulare manuala Alpaca monitor
python3 ~/notify_telegram.py
```

## GitHub
- **Repo**: https://github.com/mmiki76/Alpaca-Colude
- **Branch activ**: `claude/binance-interconectare-rlrvke`
