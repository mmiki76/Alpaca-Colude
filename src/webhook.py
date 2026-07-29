from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
import asyncio
import sys

from .models import TradingViewAlert, OrderResult
from .config import get_settings
from .exchange_client import (
    get_exchange, clean_symbol, calculate_quantity,
    place_market_order, get_current_price, get_usdt_balance,
)
from .telegram_notifier import send_telegram, format_order_message, format_error_message, format_status_message

logger.remove()
logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level="INFO")
logger.add(
    "logs/trading.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="DEBUG",
)

REPORT_INTERVAL_SECONDS = 3 * 60 * 60  # 3 ore
STATUS_SYMBOL = "SNDKON/USDT"


async def periodic_report():
    await asyncio.sleep(60)  # asteapta 1 minut la start
    while True:
        try:
            settings = get_settings()
            exchange = get_exchange()
            exchange.load_markets()
            is_futures = settings.market_type.upper() == "FUTURES"
            price = get_current_price(exchange, STATUS_SYMBOL)
            balance = get_usdt_balance(exchange, is_futures)
            msg = format_status_message(STATUS_SYMBOL, price, balance)
            await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, msg)
            logger.info("Raport periodic trimis pe Telegram")
        except Exception as e:
            logger.warning(f"Eroare raport periodic: {e}")
        await asyncio.sleep(REPORT_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(periodic_report())
    yield
    task.cancel()


app = FastAPI(
    title="Clode - Trading Bot",
    description="Webhook server pentru semnale TradingView",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    settings = get_settings()
    return {"status": "online", "exchange": settings.exchange, "market": settings.market_type}


@app.get("/health")
async def health():
    return {"status": "ok"}


async def process_order(settings, symbol: str, action: str, alert):
    try:
        is_futures = settings.market_type.upper() == "FUTURES"
        exchange = get_exchange()
        exchange.load_markets()

        quantity = alert.quantity if alert.quantity else calculate_quantity(exchange, symbol, settings.order_size_usdt)
        order = place_market_order(exchange, symbol, action, quantity)
        order_id = str(order["id"])

        price = float(order.get("average") or order.get("price") or 0) or get_current_price(exchange, symbol)
        balance = get_usdt_balance(exchange, is_futures)

        tg_msg = format_order_message(action, symbol, quantity, price, order_id, balance)
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, tg_msg)
    except Exception as e:
        logger.error(f"Eroare {action} {symbol}: {e}")
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id,
                            format_error_message(action, symbol, str(e)))


@app.post("/webhook")
async def receive_alert(alert: TradingViewAlert):
    settings = get_settings()

    if alert.secret != settings.webhook_secret:
        logger.warning("Webhook primit cu secret gresit!")
        raise HTTPException(status_code=403, detail="Secret invalid")

    is_futures = settings.market_type.upper() == "FUTURES"
    symbol = clean_symbol(alert.symbol, settings.exchange, is_futures)
    action = alert.action.upper()

    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail=f"Actiune invalida: {action}")

    logger.info(f"Alert: {action} {symbol} | {settings.exchange.upper()} {settings.market_type} | {alert.comment}")

    # Raspunde imediat la TradingView, proceseaza ordinul in background
    asyncio.create_task(process_order(settings, symbol, action, alert))

    return JSONResponse(status_code=200, content={"status": "accepted", "symbol": symbol, "action": action})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Eroare neasteptata: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Eroare interna server"})
