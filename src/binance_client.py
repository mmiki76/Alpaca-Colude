from binance.client import Client
from binance.exceptions import BinanceAPIException
from loguru import logger
from .config import get_settings


def get_client() -> Client:
    settings = get_settings()
    client = Client(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=settings.binance_testnet,
    )
    return client


def clean_symbol(symbol: str) -> str:
    # Elimina sufixele TradingView (.P, .1, etc.)
    return symbol.upper().replace("/", "").replace("-", "").split(".")[0]


def round_quantity(quantity: float, step_size: float) -> float:
    precision = len(str(step_size).rstrip("0").split(".")[-1])
    return round(round(quantity / step_size) * step_size, precision)


def get_current_price_spot(client: Client, symbol: str) -> float:
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def get_current_price_futures(client: Client, symbol: str) -> float:
    ticker = client.futures_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def get_futures_step_size(client: Client, symbol: str) -> float:
    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])
    raise ValueError(f"Step size negasit pentru {symbol}")


def get_spot_step_size(client: Client, symbol: str) -> float:
    info = client.get_symbol_info(symbol)
    if not info:
        raise ValueError(f"Symbol {symbol} nu exista pe Binance Spot")
    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            return float(f["stepSize"])
    raise ValueError(f"LOT_SIZE filter negasit pentru {symbol}")


def place_futures_order(client: Client, symbol: str, side: str, quantity: float) -> dict:
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
        )
        logger.info(f"Futures ordin executat: {side} {quantity} {symbol} | ID: {order['orderId']}")
        return order
    except BinanceAPIException as e:
        logger.error(f"Eroare Binance Futures API: {e}")
        raise


def place_spot_order(client: Client, symbol: str, side: str, quantity: float) -> dict:
    try:
        order = client.order_market(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )
        logger.info(f"Spot ordin executat: {side} {quantity} {symbol} | ID: {order['orderId']}")
        return order
    except BinanceAPIException as e:
        logger.error(f"Eroare Binance Spot API: {e}")
        raise


def place_market_order(client: Client, symbol: str, side: str, quantity: float, futures: bool = False) -> dict:
    if futures:
        return place_futures_order(client, symbol, side, quantity)
    return place_spot_order(client, symbol, side, quantity)


def calculate_quantity(client: Client, symbol: str, usdt_amount: float, futures: bool = False) -> float:
    if futures:
        price = get_current_price_futures(client, symbol)
        step_size = get_futures_step_size(client, symbol)
    else:
        price = get_current_price_spot(client, symbol)
        step_size = get_spot_step_size(client, symbol)

    raw_qty = usdt_amount / price
    qty = round_quantity(raw_qty, step_size)
    logger.debug(f"{symbol}: pret={price}, suma={usdt_amount} USDT → cantitate={qty}")
    return qty
