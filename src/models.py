from pydantic import BaseModel
from typing import Optional


class TradingViewAlert(BaseModel):
    """
    Structura alertei din TradingView.
    Mesajul JSON trimis de TradingView webhook.
    """
    secret: str
    symbol: str          # ex: "BTCUSDT"
    action: str          # "BUY" sau "SELL"
    price: Optional[float] = None
    quantity: Optional[float] = None
    comment: Optional[str] = None


class OrderResult(BaseModel):
    success: bool
    symbol: str
    action: str
    quantity: float
    price: float
    order_id: Optional[str] = None
    message: str
