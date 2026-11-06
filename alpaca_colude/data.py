"""Surse de date: CSV, Alpaca (alpaca-py) și date sintetice pentru teste."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    tcol = next(c for c in ("timestamp", "time", "date", "datetime") if c in df.columns)
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    return df.set_index(tcol).sort_index()[COLS]


def fetch_alpaca(symbol: str, timeframe: str = "15Min", days: int = 30, crypto: bool = False) -> pd.DataFrame:
    """Descarcă bare de la Alpaca. Cheile se citesc din ALPACA_API_KEY / ALPACA_SECRET_KEY."""
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    key, secret = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    num, unit = int("".join(ch for ch in timeframe if ch.isdigit())), "".join(ch for ch in timeframe if ch.isalpha())
    tf = TimeFrame(num, {"Min": TimeFrameUnit.Minute, "Hour": TimeFrameUnit.Hour, "Day": TimeFrameUnit.Day}[unit])
    start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)

    if crypto:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        bars = CryptoHistoricalDataClient(key, secret).get_crypto_bars(
            CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)).df
    else:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        bars = StockHistoricalDataClient(key, secret).get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)).df
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.droplevel(0)
    return bars[COLS].sort_index()


def synthetic_bars(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    """Random walk cu regimuri de trend (sus/jos/lateral) – doar pentru teste și demo."""
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    i = 0
    while i < n:
        L = int(rng.integers(150, 500))
        drift[i:i + L] = rng.choice([-0.0006, 0.0, 0.0008])
        i += L
    ret = drift + rng.normal(0, 0.003, n)
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    spread = np.abs(rng.normal(0, 0.002, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.lognormal(10, 0.5, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
