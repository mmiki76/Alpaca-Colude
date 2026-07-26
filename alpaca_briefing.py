"""Prints a briefing of Alpaca paper-trading account activity for the last N hours.

Reads credentials from environment variables (never hardcode secrets):
    ALPACA_API_KEY_ID
    ALPACA_API_SECRET_KEY
    ALPACA_BASE_URL (defaults to the paper endpoint)

Usage:
    python3 alpaca_briefing.py [hours]

Defaults to 12 hours if not specified.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

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


def get_positions():
    resp = requests.get(f"{BASE_URL}/positions", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_activities(after_iso):
    resp = requests.get(
        f"{BASE_URL}/account/activities",
        headers=HEADERS,
        params={"after": after_iso, "direction": "asc"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_recent_orders(after_iso):
    resp = requests.get(
        f"{BASE_URL}/orders",
        headers=HEADERS,
        params={"status": "all", "after": after_iso, "direction": "asc", "limit": 100},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"=== Alpaca briefing: last {hours}h (since {since_iso}) ===\n")

    account = get_account()
    print("-- Account --")
    print(f"status: {account['status']}")
    print(f"equity: {account['equity']}")
    print(f"cash: {account['cash']}")
    print(f"buying_power: {account['buying_power']}")
    print()

    positions = get_positions()
    print(f"-- Open positions ({len(positions)}) --")
    for p in positions:
        print(f"{p['symbol']}: qty={p['qty']} avg_entry={p['avg_entry_price']} "
              f"current={p['current_price']} unrealized_pl={p['unrealized_pl']}")
    print()

    orders = get_recent_orders(since_iso)
    print(f"-- Orders in window ({len(orders)}) --")
    for o in orders:
        print(f"{o['submitted_at']} {o['side']} {o['qty']} {o['symbol']} "
              f"type={o['type']} status={o['status']}")
    print()

    activities = get_activities(since_iso)
    print(f"-- Account activities in window ({len(activities)}) --")
    for a in activities:
        print(a)
