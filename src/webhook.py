from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
import sys

from .models import TradingViewAlert, OrderResult
from .config import get_settings
from .binance_client import get_client, calculate_quantity, place_market_order, get_current_price
from .telegram_notifier import send_telegram, format_order_message, format_error_message

# Logger setup
logger.remove()
logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level="INFO")
logger.add(
    "logs/trading.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="DEBUG",
)

app = FastAPI(
    title="Clode - Binance Trading Bot",
    description="Webhook server pentru semnale TradingView → Binance",
    version="1.0.0",
)


def get_usdt_balance(client) -> float:
    try:
        account = client.get_account()
        for asset in account["balances"]:
            if asset["asset"] == "USDT":
                return float(asset["free"])
    except Exception:
        pass
    return 0.0


@app.get("/")
async def root():
    return {"status": "online", "service": "Clode Binance Bot"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook", response_model=OrderResult)
async def receive_alert(alert: TradingViewAlert):
    settings = get_settings()

    # Verifica secretul
    if alert.secret != settings.webhook_secret:
        logger.warning(f"Webhook primit cu secret gresit!")
        raise HTTPException(status_code=403, detail="Secret invalid")

    # Normalizeaza
    symbol = alert.symbol.upper().replace("/", "").replace("-", "")
    action = alert.action.upper()

    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail=f"Actiune invalida: {action}. Foloseste BUY sau SELL.")

    logger.info(f"Alert primit: {action} {symbol} | comentariu: {alert.comment}")

    try:
        client = get_client()

        # Calculeaza cantitatea
        if alert.quantity:
            quantity = alert.quantity
        else:
            quantity = calculate_quantity(client, symbol, settings.order_size_usdt)

        # Executa ordinul
        order = place_market_order(client, symbol, action, quantity)

        price = float(order.get("fills", [{}])[0].get("price", 0)) or get_current_price(client, symbol)
        order_id = str(order["orderId"])

        # Sold USDT dupa trade
        balance = get_usdt_balance(client)

        # Notificare Telegram
        tg_msg = format_order_message(action, symbol, quantity, price, order_id, balance)
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, tg_msg)

        return OrderResult(
            success=True,
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            order_id=order_id,
            message=f"Ordin {action} executat cu succes pentru {quantity} {symbol}",
        )

    except Exception as e:
        logger.error(f"Eroare la executia ordinului {action} {symbol}: {e}")
        err_msg = format_error_message(action, symbol, str(e))
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, err_msg)
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Eroare neasteptata: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Eroare interna server"})
