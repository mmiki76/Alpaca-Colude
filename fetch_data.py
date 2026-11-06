"""Descarca bare istorice crypto de la Alpaca (nu necesita chei API pentru crypto)."""
import sys, json, urllib.request, urllib.parse
import pandas as pd

def fetch(symbol="SOL/USD", timeframe="4Hour", start="2021-01-01T00:00:00Z"):
    rows, token = [], None
    while True:
        q = {"symbols": symbol, "timeframe": timeframe, "start": start, "limit": 10000}
        if token:
            q["page_token"] = token
        url = "https://data.alpaca.markets/v1beta3/crypto/us/bars?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.load(r)
        rows += d["bars"].get(symbol, [])
        token = d.get("next_page_token")
        if not token:
            break
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df[["time", "open", "high", "low", "close", "volume"]].drop_duplicates("time").sort_values("time")

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "SOL/USD"
    df = fetch(sym)
    out = f"data/{sym.replace('/', '')}_4H.csv"
    df.to_csv(out, index=False)
    print(out, len(df), df.time.min(), df.time.max())
