"""Surse de date: CSV, Alpaca (alpaca-py) și date sintetice pentru teste."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    tcol = next((c for c in ("timestamp", "time", "date", "datetime", "t") if c in df.columns), df.columns[0])
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


def fetch_coinbase(product: str, granularity_s: int = 3600, days: int = 365) -> pd.DataFrame:
    """Candele publice Coinbase (fără chei), cu volum real. product ex: 'SOL-USD'."""
    import time
    import requests

    end = pd.Timestamp.now(tz="UTC").floor("s")
    start = end - pd.Timedelta(days=days)
    step = pd.Timedelta(seconds=granularity_s * 300)
    rows, cur = [], start
    while cur < end:
        nxt = min(cur + step, end)
        for attempt in range(5):
            r = requests.get(
                f"https://api.exchange.coinbase.com/products/{product}/candles",
                params={"granularity": granularity_s, "start": cur.isoformat(), "end": nxt.isoformat()},
                timeout=20)
            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            rows += r.json()
            break
        cur = nxt
        time.sleep(0.15)
    df = pd.DataFrame(rows, columns=["t", "low", "high", "open", "close", "volume"])
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    return df.drop_duplicates("t").set_index("t").sort_index()[COLS]


def fetch_binance_vision(symbol: str, interval: str = "1h", days: int = 365, market: str = "spot") -> pd.DataFrame:
    """Istoric Binance din arhiva publică data.binance.vision (fără chei, fără restricții de locație).

    symbol ex: 'SOLUSDT'; interval ex: '15m', '1h', '4h', '6h', '1d';
    market: 'spot' sau 'futures/um'. Luni complete = fișiere lunare, luna curentă = fișiere zilnice.
    """
    import io
    import zipfile
    from concurrent.futures import ThreadPoolExecutor

    import requests

    base = f"https://data.binance.vision/data/{market}"
    today = pd.Timestamp.now(tz="UTC").normalize()
    start = today - pd.Timedelta(days=days)
    urls = []
    for m in pd.period_range(start, today, freq="M"):
        if m.end_time.tz_localize("UTC") < today:                       # lună încheiată
            urls.append(f"{base}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{m.strftime("%Y-%m")}.zip")
        else:                                                           # luna curentă: zilnic
            for d in pd.date_range(max(m.start_time.tz_localize("UTC"), start), today - pd.Timedelta(days=1)):
                urls.append(f"{base}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m-%d}.zip")

    def get(url):
        r = requests.get(url, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            return pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6),
                               names=["t", "open", "high", "low", "close", "volume"])

    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(get, urls) if p is not None]
    if not parts:
        raise ValueError(f"Nicio dată pentru {symbol} {interval} ({market})")
    df = pd.concat(parts)
    df = df[pd.to_numeric(df["t"], errors="coerce").notna()].astype(float)   # elimină eventuale header-e
    # spot 2025+ folosește microsecunde, fișierele vechi milisecunde (pot fi amestecate): normalizează per rând
    df["t"] = np.where(df["t"] > 1e14, df["t"] // 1000, df["t"])
    df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)
    df = df.drop_duplicates("t").set_index("t").sort_index()[COLS]
    return df[df.index >= start]


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
