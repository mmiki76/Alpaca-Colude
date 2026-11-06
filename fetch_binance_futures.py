"""Descarca klines 4H USDⓈ-M Futures din arhiva publica Binance (data.binance.vision) si le salveaza ca data/<SIMBOL>_4H.csv.
API-ul fapi.binance.com este blocat geografic din mediul cloud, de aceea folosim arhiva publica."""
import io, sys, zipfile, urllib.request, urllib.error, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "tb_vol", "tb_quote", "ignore"]

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise

def parse(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None, names=COLS, dtype=str)
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]           # scoate header-ul daca exista
    return df.astype({c: float for c in ("open", "high", "low", "close", "volume")}).assign(open_time=lambda d: d.open_time.astype("int64"))

def fetch(sym, start=(2019, 9)):
    today = dt.datetime.now(dt.timezone.utc).date()
    months = []; y, m = start
    while (y, m) < (today.year, today.month):
        months.append(f"{y}-{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    urls = [f"{BASE}/monthly/klines/{sym}/4h/{sym}-4h-{x}.zip" for x in months]
    # zilele lunii curente (luna incompleta)
    d = today.replace(day=1)
    while d < today:
        urls.append(f"{BASE}/daily/klines/{sym}/4h/{sym}-4h-{d:%Y-%m-%d}.zip"); d += dt.timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        raws = list(ex.map(get, urls))
    parts = [parse(r) for r in raws if r]
    df = pd.concat(parts).drop_duplicates("open_time").sort_values("open_time")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["time", "open", "high", "low", "close", "volume"]], sum(r is not None for r in raws), len(urls)

if __name__ == "__main__":
    for sym in sys.argv[1:]:
        df, ok, tot = fetch(sym)
        df.to_csv(f"data/{sym}_4H.csv", index=False)
        gaps = (df.time.diff().dropna() > pd.Timedelta(hours=4)).sum()
        print(f"{sym}: {len(df)} bare {df.time.min():%Y-%m-%d} -> {df.time.max():%Y-%m-%d} | fisiere {ok}/{tot} | goluri {gaps}")
