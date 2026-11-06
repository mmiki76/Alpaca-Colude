import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from concurrent.futures import ThreadPoolExecutor
from alpaca_colude.data import fetch_binance_vision
S = sys.argv[1]
COINS = ("NEAR ATOM APT ARB OP FIL ETC TRX BCH AAVE UNI MKR SEI TIA TON 1000PEPE 1000SHIB WIF FET RUNE ICP HBAR XLM ALGO "
         "SAND MANA AXS GALA CRV LDO IMX JUP ENA TAO WLD ONDO RENDER GRT SNX COMP EGLD THETA VET EOS XMR DASH KAVA "
         "SUSHI 1INCH ENS STRK PYTH BLUR DYDX ORDI").split()
def job(c):
    path = f"{S}/new15/{c}.pkl"
    if os.path.exists(path):
        return f"{c} cached"
    try:
        df = fetch_binance_vision(f"{c}USDT", "15m", 1461, "futures/um")
        if len(df) < 5000:
            return f"{c} too short {len(df)}"
        df.to_pickle(path)
        return f"{c} {len(df)} {df.index[0].date()} -> {df.index[-1].date()}"
    except Exception as e:
        return f"{c} ERR {str(e)[:60]}"
with ThreadPoolExecutor(4) as ex:
    for r in ex.map(job, COINS):
        print(r, flush=True)
