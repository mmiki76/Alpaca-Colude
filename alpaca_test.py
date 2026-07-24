"""Quick connectivity test for the Alpaca paper-trading API.

Reads credentials from environment variables (never hardcode secrets):
    ALPACA_API_KEY_ID
    ALPACA_API_SECRET_KEY
    ALPACA_BASE_URL (defaults to the paper endpoint)

Fetches account info and submits a 1-share market buy order for GOOGL.
"""

import os
import sys

import requests

BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")
API_KEY = os.environ["ALPACA_API_KEY_ID"]
API_SECRET = os.environ["ALPACA_API_SECRET_KEY"]

HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
}


def get_account():
    resp = requests.get(f"{BASE_URL}/account", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def buy_googl(qty=1):
    order = {
        "symbol": "GOOGL",
        "qty": qty,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }
    resp = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json=order, timeout=10)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    account = get_account()
    print(f"Account status: {account['status']}, buying power: {account['buying_power']}")

    order = buy_googl()
    print(f"Order submitted: id={order['id']} status={order['status']} symbol={order['symbol']} qty={order['qty']}")
