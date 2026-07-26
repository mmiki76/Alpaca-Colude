import ccxt
from loguru import logger
from .config import get_settings


def get_exchange() -> ccxt.Exchange:
    settings = get_settings()
    is_futures = settings.market_type.upper() == "FUTURES"

    if settings.exchange.lower() == "mexc":
        exchange = ccxt.mexc({
            "apiKey": settings.api_key,
            "secret": settings.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap" if is_futures else "spot"},
        })
    elif settings.exchange.lower() == "binance":
        exchange = ccxt.binance({
            "apiKey": settings.api_key,
            "secret": settings.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future" if is_futures else "spot"},
        })
    else:
        raise ValueError(f"Exchange necunoscut: {settings.exchange}")

    return exchange


def clean_symbol(raw: str, exchange_id: str, is_futures: bool) -> str:
    # Elimina sufixele TradingView (.P, .1, etc.)
    base = raw.upper().replace("/", "").replace("-", "").split(".")[0]
    # Converteste la formatul ccxt: SNDKUSDT → SNDK/USDT:USDT (futures) sau SNDK/USDT (spot)
    if base.endswith("USDT"):
        coin = base[:-4]
        if is_futures:
            return f"{coin}/USDT:USDT"
        return f"{coin}/USDT"
    return base


def get_current_price(exchange: ccxt.Exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker["last"])


def get_usdt_balance(exchange: ccxt.Exchange, is_futures: bool) -> float:
    try:
        balance = exchange.fetch_balance()
        if is_futures:
            return float(balance.get("USDT", {}).get("free", 0))
        return float(balance.get("USDT", {}).get("free", 0))
    except Exception as e:
        logger.warning(f"Nu am putut lua soldul: {e}")
        return 0.0


def calculate_quantity(exchange: ccxt.Exchange, symbol: str, usdt_amount: float) -> float:
    price = get_current_price(exchange, symbol)
    market = exchange.market(symbol)
    raw_qty = usdt_amount / price

    # Rotunjeste la precizia corecta
    precision = market.get("precision", {}).get("amount", 0)
    if precision and precision > 0:
        qty = exchange.amount_to_precision(symbol, raw_qty)
    else:
        qty = round(raw_qty, 4)

    logger.debug(f"{symbol}: pret={price}, suma={usdt_amount} USDT → cantitate={qty}")
    return float(qty)


def place_market_order(exchange: ccxt.Exchange, symbol: str, side: str, quantity: float) -> dict:
    try:
        order = exchange.create_order(
            symbol=symbol,
            type="market",
            side=side.lower(),
            amount=quantity,
        )
        logger.info(f"Ordin executat: {side} {quantity} {symbol} | ID: {order['id']}")
        return order
    except Exception as e:
        logger.error(f"Eroare la ordin {side} {symbol}: {e}")
        raise
