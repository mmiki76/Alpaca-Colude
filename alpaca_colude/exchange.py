"""Client Binance USDT-M Futures (DOAR testnet/demo) + simulator offline cu aceeași interfață.

IMPORTANT: clientul real NU a putut fi testat împotriva Binance din mediul de dezvoltare (rețea blocată).
Ce e testat: semnarea cererilor, rotunjirile, logica botului pe simulator. Ce NU e verificat: numele exacte ale
parametrilor la endpoint-ul de ordine condiționale `/fapi/v1/algoOrder` (Binance le-a mutat acolo la 2025-12-09,
vezi README) -> rulează `python paper_bot.py --selftest` pe contul tău de testnet înainte de orice altceva.

Mainnet este INTENȚIONAT neacceptat: `base_url` trebuie să fie în ALLOWED_BASES.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

ALLOWED_BASES = ("https://testnet.binancefuture.com", "https://demo-fapi.binance.com")


class BinanceError(RuntimeError):
    def __init__(self, msg: str, code: int | None = None, status: int | None = None):
        super().__init__(f"{msg} (code={code}, http={status})")
        self.code, self.status = code, status


@dataclass(frozen=True)
class SymbolRules:
    tick: float = 0.00001
    step: float = 1.0
    min_qty: float = 1.0
    min_notional: float = 5.0


# ------------------------------------------------------------------ utilitare
def sign_query(query: str, secret: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def round_to(x: float, unit: float, mode: str = "down") -> float:
    """Rotunjește la multiplu de `unit` (tick/step) fără erori de float. mode: down | up | nearest."""
    d = Decimal(str(unit))
    q = Decimal(str(x)) / d
    rounding = {"down": ROUND_FLOOR, "up": ROUND_CEILING, "nearest": ROUND_HALF_UP}[mode]
    return float(q.to_integral_value(rounding) * d)


def fmt(x: float, unit: float) -> str:
    """Formatează cu exact precizia lui `unit` (Binance respinge zecimale în plus)."""
    exp = Decimal(str(unit)).normalize().as_tuple().exponent
    return f"{x:.{max(0, -exp)}f}"


def parse_rules(exchange_info: dict, symbol: str) -> SymbolRules:
    s = next(x for x in exchange_info["symbols"] if x["symbol"] == symbol)
    f = {x["filterType"]: x for x in s["filters"]}
    mn = f.get("MIN_NOTIONAL", {})
    return SymbolRules(tick=float(f["PRICE_FILTER"]["tickSize"]), step=float(f["LOT_SIZE"]["stepSize"]),
                       min_qty=float(f["LOT_SIZE"]["minQty"]), min_notional=float(mn.get("notional", mn.get("minNotional", 5))))


# ---------------------------------------------------------------- client real
class BinanceFuturesTestnet:
    def __init__(self, api_key: str, api_secret: str, base_url: str = ALLOWED_BASES[0], session=None, recv_window: int = 5000):
        if base_url.rstrip("/") not in ALLOWED_BASES:
            raise ValueError(f"base_url trebuie să fie testnet/demo: {ALLOWED_BASES}")
        import requests
        self.base, self.key, self.secret, self.recv = base_url.rstrip("/"), api_key, api_secret, recv_window
        self.http = session or requests.Session()
        self._rules: dict[str, SymbolRules] = {}

    # ---- HTTP
    def _req(self, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"X-MBX-APIKEY": self.key}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv
            q = urlencode(params)
            q += "&signature=" + sign_query(q, self.secret)
            url = f"{self.base}{path}?{q}"
            r = self.http.request(method, url, headers=headers, timeout=15)
        else:
            r = self.http.request(method, f"{self.base}{path}", params=params, headers=headers, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = None
        if r.status_code >= 400 or (isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0):
            code = data.get("code") if isinstance(data, dict) else None
            msg = data.get("msg") if isinstance(data, dict) else r.text[:200]
            raise BinanceError(msg or "eroare", code, r.status_code)
        return data

    # ---- date publice
    def rules(self, symbol: str) -> SymbolRules:
        if symbol not in self._rules:
            self._rules[symbol] = parse_rules(self._req("GET", "/fapi/v1/exchangeInfo"), symbol)
        return self._rules[symbol]

    def last_price(self, symbol: str) -> float:
        return float(self._req("GET", "/fapi/v1/ticker/price", {"symbol": symbol})["price"])

    def klines(self, symbol: str, interval: str, limit: int):
        return self._req("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    # ---- cont
    def balance(self, asset: str) -> dict:
        for b in self._req("GET", "/fapi/v2/balance", signed=True):
            if b["asset"] == asset:
                return {"balance": float(b["balance"]), "available": float(b["availableBalance"])}
        return {"balance": 0.0, "available": 0.0}

    def position(self, symbol: str) -> dict:
        rows = self._req("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
        amt = sum(float(r["positionAmt"]) for r in rows)
        r0 = rows[0] if rows else {}
        return {"amt": amt, "entry": float(r0.get("entryPrice", 0) or 0), "unrealized": float(r0.get("unRealizedProfit", 0) or 0)}

    def set_leverage(self, symbol: str, leverage: int):
        return self._req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)}, signed=True)

    def set_margin_type(self, symbol: str, margin_type: str):
        try:
            return self._req("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}, signed=True)
        except BinanceError as e:
            if e.code == -4046:                          # "No need to change margin type"
                return {}
            raise

    # ---- ordine
    def market_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> dict:
        r = self.rules(symbol)
        o = self._req("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty, r.step),
            "reduceOnly": "true" if reduce_only else None, "newOrderRespType": "RESULT"}, signed=True)
        return {"id": o.get("orderId"), "avg_price": float(o.get("avgPrice") or 0), "qty": float(o.get("executedQty") or 0)}

    def limit_order(self, symbol: str, side: str, qty: float, price: float, reduce_only: bool = True) -> dict:
        r = self.rules(symbol)
        o = self._req("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC", "quantity": fmt(qty, r.step),
            "price": fmt(price, r.tick), "reduceOnly": "true" if reduce_only else None}, signed=True)
        return {"id": o.get("orderId")}

    def stop_close_order(self, symbol: str, side: str, trigger: float) -> dict:
        """SL de tip STOP_MARKET care închide toată poziția. De la 2025-12-09 ordinele condiționale merg pe
        /fapi/v1/algoOrder; dacă răspunde cu eroare încercăm endpoint-ul clasic (pentru medii vechi)."""
        r = self.rules(symbol)
        trig = fmt(trigger, r.tick)
        try:
            o = self._req("POST", "/fapi/v1/algoOrder", {
                "algoType": "CONDITIONAL", "symbol": symbol, "side": side, "type": "STOP_MARKET",
                "triggerPrice": trig, "closePosition": "true", "workingType": "MARK_PRICE"}, signed=True)
            return {"id": o.get("algoId"), "via": "algo"}
        except BinanceError as algo_err:
            try:
                o = self._req("POST", "/fapi/v1/order", {
                    "symbol": symbol, "side": side, "type": "STOP_MARKET", "stopPrice": trig,
                    "closePosition": "true", "workingType": "MARK_PRICE"}, signed=True)
                return {"id": o.get("orderId"), "via": "classic"}
            except BinanceError as classic_err:
                raise BinanceError(f"SL eșuat: algo={algo_err} | classic={classic_err}") from classic_err

    def cancel_all(self, symbol: str) -> None:
        for method, path in (("DELETE", "/fapi/v1/allOpenOrders"), ("DELETE", "/fapi/v1/algoOpenOrders")):
            try:
                self._req(method, path, {"symbol": symbol}, signed=True)
            except BinanceError:
                pass                                        # endpoint-ul poate lipsi în anumite medii

    def user_trades(self, symbol: str, since_ms: int) -> list[dict]:
        rows = self._req("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": since_ms, "limit": 100}, signed=True)
        return [{"time": int(x["time"]), "side": x["side"], "price": float(x["price"]), "qty": float(x["qty"]),
                 "realized": float(x["realizedPnl"]), "commission": float(x["commission"]), "asset": x["commissionAsset"]}
                for x in rows]


# ----------------------------------------------------------------- simulator
class SimExchange:
    """Simulează un cont de futures (one-way) pe lumânări; aceeași interfață ca clientul real.
    `feed(bar)` avansează piața cu o lumânare și execută TP/SL. Comision taker 0,04% / maker 0,02%."""

    is_sim = True

    def __init__(self, balance: float = 10_000.0, quote: str = "USDT", rules: SymbolRules = SymbolRules(),
                 slippage_bps: float = 2.0, fail_stop: bool = False):
        self.cash, self.quote, self._rules, self.slip, self.fail_stop = balance, quote, rules, slippage_bps / 1e4, fail_stop
        self.price, self.now_ms = 0.0, 0
        self.pos_amt, self.pos_entry = 0.0, 0.0
        self.tp: dict | None = None          # {"side","qty","price"}
        self.sl: dict | None = None          # {"side","trigger"}
        self.trades: list[dict] = []
        self.leverage, self.margin_type = 1, "ISOLATED"
        self.calls: list[tuple] = []

    # ---- piață
    def feed(self, ts_ms: int, o: float, h: float, l: float, c: float) -> None:
        self.now_ms = ts_ms
        if self.pos_amt != 0:
            short = self.pos_amt < 0
            if self.sl and ((short and h >= self.sl["trigger"]) or (not short and l <= self.sl["trigger"])):
                px = max(self.sl["trigger"], o) if short else min(self.sl["trigger"], o)
                self._fill(ts_ms, self.sl["side"], abs(self.pos_amt), px * (1 + self.slip if short else 1 - self.slip), 0.0004)
            elif self.tp and ((short and l <= self.tp["price"]) or (not short and h >= self.tp["price"])):
                px = min(self.tp["price"], o) if short else max(self.tp["price"], o)
                self._fill(ts_ms, self.tp["side"], abs(self.pos_amt), px, 0.0002)
            if self.pos_amt == 0:
                self.tp = self.sl = None
        self.price = c

    def _fill(self, ts: int, side: str, qty: float, price: float, fee_rate: float) -> None:
        signed = qty if side == "BUY" else -qty
        realized = 0.0
        if self.pos_amt != 0 and (self.pos_amt > 0) != (signed > 0):          # reduce/close
            closed = min(abs(self.pos_amt), qty)
            realized = closed * ((price - self.pos_entry) if self.pos_amt > 0 else (self.pos_entry - price))
        new = self.pos_amt + signed
        if self.pos_amt == 0 or (self.pos_amt > 0) == (signed > 0):
            tot = abs(self.pos_amt) + qty
            self.pos_entry = (abs(self.pos_amt) * self.pos_entry + qty * price) / tot if tot else 0.0
        self.pos_amt = 0.0 if abs(new) < 1e-9 else new
        commission = qty * price * fee_rate
        self.cash += realized - commission
        self.trades.append({"time": ts, "side": side, "price": price, "qty": qty, "realized": realized,
                            "commission": commission, "asset": self.quote})

    # ---- interfața
    def rules(self, symbol: str) -> SymbolRules:
        return self._rules

    def last_price(self, symbol: str) -> float:
        return self.price

    def balance(self, asset: str) -> dict:
        unreal = self.position("")["unrealized"]
        used = abs(self.pos_amt) * self.pos_entry / max(self.leverage, 1)
        return {"balance": self.cash + unreal, "available": max(0.0, self.cash + unreal - used)}

    def position(self, symbol: str) -> dict:
        unreal = 0.0
        if self.pos_amt:
            unreal = abs(self.pos_amt) * ((self.price - self.pos_entry) if self.pos_amt > 0 else (self.pos_entry - self.price))
        return {"amt": self.pos_amt, "entry": self.pos_entry, "unrealized": unreal}

    def set_leverage(self, symbol: str, leverage: int):
        self.leverage = int(leverage); self.calls.append(("leverage", int(leverage)))

    def set_margin_type(self, symbol: str, margin_type: str):
        self.margin_type = margin_type; self.calls.append(("margin", margin_type))

    def market_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> dict:
        px = self.price * (1 + self.slip if side == "BUY" else 1 - self.slip)
        self._fill(self.now_ms, side, qty, px, 0.0004)
        self.calls.append(("market", side, qty))
        return {"id": len(self.trades), "avg_price": px, "qty": qty}

    def limit_order(self, symbol: str, side: str, qty: float, price: float, reduce_only: bool = True) -> dict:
        self.tp = {"side": side, "qty": qty, "price": price}; self.calls.append(("tp", side, qty, price))
        return {"id": 1}

    def stop_close_order(self, symbol: str, side: str, trigger: float) -> dict:
        if self.fail_stop:
            raise BinanceError("simulated stop failure", -4120, 400)
        self.sl = {"side": side, "trigger": trigger}; self.calls.append(("sl", side, trigger))
        return {"id": 2, "via": "sim"}

    def cancel_all(self, symbol: str) -> None:
        self.tp = self.sl = None; self.calls.append(("cancel_all",))

    def user_trades(self, symbol: str, since_ms: int) -> list[dict]:
        return [t for t in self.trades if t["time"] >= since_ms]
