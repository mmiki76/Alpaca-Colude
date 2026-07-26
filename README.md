# Clode - Binance Interconectare

Bot de trading automat: **TradingView → Oracle VPS → Binance**

## Arhitectura

```
TradingView Alert
       │
       │ HTTP POST (JSON)
       ▼
 Oracle VPS :8080
 FastAPI Webhook Server
       │
       │ Binance API
       ▼
  Executie Ordin
  (BUY / SELL)
```

## Structura proiect

```
├── main.py                  # Entry point
├── requirements.txt
├── config/
│   └── .env.example         # Template configurare
├── src/
│   ├── config.py            # Setari din .env
│   ├── models.py            # Structura alertei TradingView
│   ├── binance_client.py    # Conexiune Binance API
│   └── webhook.py           # FastAPI server
├── scripts/
│   ├── install.sh           # Instalare pe Oracle VPS
│   ├── update.sh            # Update rapid
│   └── clode-binance.service # Systemd service
└── logs/                    # Loguri tranzactii
```

## Instalare pe Oracle VPS

### 1. Conecteaza-te la VPS
```bash
ssh ubuntu@IP_VPS_TAU
```

### 2. Cloneaza si instaleaza
```bash
git clone https://github.com/mmiki76/alpaca-colude.git /opt/clode-binance
cd /opt/clode-binance
bash scripts/install.sh
```

### 3. Configureaza .env
```bash
nano /opt/clode-binance/.env
```

Completeaza:
```
BINANCE_API_KEY=cheia_ta_api
BINANCE_API_SECRET=secretul_tau_api
BINANCE_TESTNET=True          # Schimba pe False pentru real money!
WEBHOOK_SECRET=un_secret_lung_si_random
ORDER_SIZE_USDT=10.0
MARKET_TYPE=SPOT
```

### 4. Porneste botul
```bash
sudo systemctl start clode-binance
sudo systemctl status clode-binance
```

### 5. Verifica ca merge
```bash
curl http://localhost:8080/health
# Raspuns asteptat: {"status":"ok"}
```

## Configurare TradingView

### Pasul 1 - Creaza un Alert in TradingView
1. Deschide graficul → click **Alerts** (iconita clopot)
2. Seteaza conditia dorita (indicator, crossover, etc.)
3. La **Notifications** → activeaza **Webhook URL**
4. URL: `http://IP_VPS_TAU:8080/webhook`

### Pasul 2 - Mesajul alertei (JSON)
In campul **Message** al alertei, pune exact asa:
```json
{
  "secret": "secretul_tau_din_env",
  "symbol": "{{ticker}}",
  "action": "BUY",
  "comment": "{{strategy.order.comment}}"
}
```

Pentru SELL:
```json
{
  "secret": "secretul_tau_din_env",
  "symbol": "{{ticker}}",
  "action": "SELL",
  "comment": "{{strategy.order.comment}}"
}
```

> **Nota**: `{{ticker}}` e placeholder TradingView — se inlocuieste automat cu simbolul graficului (ex: BTCUSDT)

### Pasul 3 - Cu Pine Script Strategy
Daca ai o strategie Pine Script, adauga in `strategy.entry`:
```pine
strategy("Strategia Mea", overlay=true)

longCondition = ta.crossover(ta.sma(close, 14), ta.sma(close, 28))
if longCondition
    strategy.entry("Long", strategy.long, alert_message='{"secret":"SECRET","symbol":"{{ticker}}","action":"BUY","comment":"SMA Cross"}')

shortCondition = ta.crossunder(ta.sma(close, 14), ta.sma(close, 28))
if shortCondition
    strategy.entry("Short", strategy.short, alert_message='{"secret":"SECRET","symbol":"{{ticker}}","action":"SELL","comment":"SMA Cross"}')
```

## Oracle VPS - Port deschis

Pe Oracle Cloud trebuie sa deschizi portul **8080** in doua locuri:

### 1. Security List (OCI Console)
- Networking → Virtual Cloud Networks → VCN → Security Lists
- Add Ingress Rule: TCP, port 8080, source 0.0.0.0/0

### 2. Pe VPS (iptables)
```bash
sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT
sudo netfilter-persistent save
```

## Loguri

```bash
# Loguri sistemd (live)
sudo journalctl -u clode-binance -f

# Fisier log
tail -f /opt/clode-binance/logs/trading.log
```

## Testare manuala

```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "secretul_tau",
    "symbol": "BTCUSDT",
    "action": "BUY",
    "comment": "test manual"
  }'
```

## Securitate

- Tine `BINANCE_TESTNET=True` pana testezi complet
- Foloseste un `WEBHOOK_SECRET` lung si random (min 32 caractere)
- Pe Binance API, activeaza **numai** permisiunea de trading (nu retrageri!)
- Considera un reverse proxy (nginx) cu HTTPS pentru productie

## Update

```bash
cd /opt/clode-binance
bash scripts/update.sh
```
