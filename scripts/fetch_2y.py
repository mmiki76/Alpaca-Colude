# Folosire: python scripts/fetch_2y.py <dir_date>  si apoi  python scripts/grid.py <dir_date>
# (<dir_date> contine subfolderul f2y/ cu CSV-uri, vezi fetch_2y.py)
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from concurrent.futures import ThreadPoolExecutor
from alpaca_colude.data import fetch_binance_vision
S = sys.argv[1]
COINS = ("SOL","ETH","INJ","STX","ZEC","BTC","BNB","XRP","DOGE","AVAX","ADA","LINK","LTC","DOT","SUI")
TFS = ("15m","30m","1h","2h","4h")
def job(a):
    c, tf = a
    path = f"{S}/f2y/{c}_{tf}.csv"
    if os.path.exists(path):
        return f"{c} {tf} cached"
    try:
        df = fetch_binance_vision(f"{c}USDT", tf, 730, "futures/um")
        df.to_csv(path)
        return f"{c} {tf} {len(df)} {df.index[0].date()} -> {df.index[-1].date()}"
    except Exception as e:
        return f"{c} {tf} ERR {e}"
with ThreadPoolExecutor(4) as ex:
    for r in ex.map(job, [(c, tf) for c in COINS for tf in TFS]):
        print(r, flush=True)
