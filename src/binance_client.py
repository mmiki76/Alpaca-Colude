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


def get_symbol_info(client: Client, symbol: str) -> dict:
    info = client.get_symbol_info(symbol)
    if not info:
        raise ValueError(f"Symbol {symbol} nu exista pe Binance")
    return info


def get_lot_size_filter(symbol_info: dict) -> tuple[float, float, float]:
    """Returneaza (min_qty, max_qty, step_size) din LOT_SIZE filter."""
    for f in symbol_info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            return float(f["minQty"]), float(f["maxQty"]), float(f["stepSize"])
    raise ValueError("LOT_SIZE filter negasit")


def round_quantity(quantity: float, step_size: float) -> float:
    """Rotunjeste cantitatea la step_size-ul corect."""
    precision = len(str(step_size).rstrip("0").split(".")[-1])
    return round(round(quantity / step_size) * step_size, precision)


def get_current_price(client: Client, symbol: str) -> float:
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def place_market_order(client: Client, symbol: str, side: str, quantity: float) -> dict:
    """
    side: 'BUY' sau 'SELL'
    """
    try:
        order = client.order_market(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )
        logger.info(f"Ordin executat: {side} {quantity} {symbol} | ID: {order['orderId']}")
        return order
    except BinanceAPIException as e:
        logger.error(f"Eroare Binance API: {e}")
        raise


def calculate_quantity(client: Client, symbol: str, usdt_amount: float) -> float:
    price = get_current_price(client, symbol)
    raw_qty = usdt_amount / price

    symbol_info = get_symbol_info(client, symbol)
    _, _, step_size = get_lot_size_filter(symbol_info)
    qty = round_quantity(raw_qty, step_size)

    logger.debug(f"{symbol}: pret={price}, suma={usdt_amount} USDT → cantitate={qty}")
    return qty
