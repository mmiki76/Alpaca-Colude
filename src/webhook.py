from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
import asyncio
import json
import time
import sys
from pathlib import Path

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

REPORT_INTERVAL_SECONDS = 3 * 60 * 60
STATUS_SYMBOL = "SNDKON/USDT"
STATE_FILE = Path("position_state.json")
MIN_HOLD_SECONDS = 120  # minim 2 minute intre BUY si SELL

position_lock = asyncio.Lock()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"position": None, "last_buy_time": 0}


def save_state(position: str | None, last_buy_time: float):
    STATE_FILE.write_text(json.dumps({"position": position, "last_buy_time": last_buy_time}))


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
    async with position_lock:
        state = load_state()
        position = state["position"]
        last_buy_time = state["last_buy_time"]
        now = time.time()

        if action == "BUY" and position == "BUY":
            logger.info(f"BUY ignorat — deja in pozitie pe {symbol}")
            await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id,
                                f"⏭️ <b>BUY ignorat</b> — pozitie deja deschisa pe {symbol}")
            return

        if action == "SELL" and position != "BUY":
            logger.info(f"SELL ignorat — fara pozitie pe {symbol}")
            await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id,
                                f"⏭️ <b>SELL ignorat</b> — nicio pozitie deschisa pe {symbol}")
            return

        if action == "SELL" and (now - last_buy_time) < MIN_HOLD_SECONDS:
            wait = int(MIN_HOLD_SECONDS - (now - last_buy_time))
            logger.info(f"SELL ignorat — prea devreme dupa BUY ({wait}s ramase)")
            await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id,
                                f"⏭️ <b>SELL ignorat</b> — prea devreme dupa BUY ({wait}s)")
            return

        # Seteaza starea inainte de executie (previne race condition)
        new_position = "BUY" if action == "BUY" else None
        new_buy_time = now if action == "BUY" else last_buy_time
        save_state(new_position, new_buy_time)

    try:
        is_futures = settings.market_type.upper() == "FUTURES"
        exchange = get_exchange()
        exchange.load_markets()

        if alert.quantity:
            quantity = alert.quantity
        elif settings.fixed_quantity > 0:
            quantity = settings.fixed_quantity
        else:
            quantity = calculate_quantity(exchange, symbol, settings.order_size_usdt)
        order = place_market_order(exchange, symbol, action, quantity)
        order_id = str(order["id"])

        price = float(order.get("average") or order.get("price") or 0) or get_current_price(exchange, symbol)
        balance = get_usdt_balance(exchange, is_futures)

        tg_msg = format_order_message(action, symbol, quantity, price, order_id, balance)
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, tg_msg)
    except Exception as e:
        logger.error(f"Eroare {action} {symbol}: {e}")
        # Reseteaza starea daca ordinul a esuat
        async with position_lock:
            save_state(position, last_buy_time)
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
