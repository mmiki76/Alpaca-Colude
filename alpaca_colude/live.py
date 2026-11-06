"""Scanner în timp real (PAPER – nu trimite ordine) cu mărime COMPUSĂ.

La fiecare lumânare ÎNCHISĂ:
  * dacă ai poziție deschisă: verifică stop / target pe high/low-ul lumânării;
  * dacă ești flat: rulează strategia pe ultimele `window` lumânări și, dacă apare semnal chiar pe
    ultima lumânare, îți spune ce ordine să pui (intrare, SL, TP, cantitate).

Mărimea: notional = equity_curent * leverage (cu leverage = 1 intri cu TOT equity-ul).
După fiecare trade equity-ul se actualizează cu profitul/pierderea (inclusiv comisioane și slippage),
deci următorul trade intră cu 100 -> 107 după un câștig de 7, apoi 107 -> 95 după o pierdere de 12 etc.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import pandas as pd

from .strategy import PocPullbackStrategy, StrategyParams

# Varianta aleasă în studiul short 15m: SL 2%, TP 2,5 x SL (=5%), swing 5, mișcare >= 3 ATR.
BEST_PARAMS = StrategyParams(fixed_stop_pct=0.02, tp_rr=2.5, swing_n=5, min_move_atr=3.0)


@dataclass(frozen=True)
class Costs:
    slippage_bps: float = 2.0     # slippage advers la intrare și la stop
    entry_fee_bps: float = 4.0    # short: intrarea e o VÂNZARE (0,04%)
    exit_fee_bps: float = 2.0     # ieșirea e o CUMPĂRARE (0,02%)


@dataclass
class ScannerState:
    equity: float
    leverage: float = 1.0
    last_bar: str | None = None          # open-time ISO al ultimei lumânări procesate
    position: dict | None = None
    trades: list = field(default_factory=list)

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "ScannerState":
        with open(path) as f:
            return cls(**json.load(f))


def fetch_klines(symbol: str = "VETUSDT", interval: str = "15m", limit: int = 1500,
                 market: str = "futures") -> pd.DataFrame:
    """Lumânări ÎNCHISE de la Binance (publice, fără chei). market: 'futures' (USDT-M) sau 'spot'."""
    import time

    import requests

    url = {"futures": "https://fapi.binance.com/fapi/v1/klines",
           "spot": "https://api.binance.com/api/v3/klines"}[market]
    limit = min(limit, 1500 if market == "futures" else 1000)
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    return parse_klines(r.json(), now_ms=int(time.time() * 1000))


def parse_klines(rows: list, now_ms: int) -> pd.DataFrame:
    df = pd.DataFrame(rows).iloc[:, :7]
    df.columns = ["t", "open", "high", "low", "close", "volume", "close_t"]
    df = df[df["close_t"].astype("int64") < now_ms]                 # doar lumânări închise
    df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)
    out = df.set_index("t")[["open", "high", "low", "close", "volume"]].astype(float)
    return out.sort_index()


class LiveScanner:
    def __init__(self, state: ScannerState, params: StrategyParams = BEST_PARAMS, window: int = 1500,
                 costs: Costs = Costs(), min_notional: float = 5.0):
        self.s, self.params, self.window, self.costs, self.min_notional = state, params, window, costs, min_notional
        self.strategy = PocPullbackStrategy(params)
        self.setup: dict = {"state": "IDLE"}       # ultima stare a setup-ului (pentru afișare)

    # ------------------------------------------------------------------ API
    def process(self, df: pd.DataFrame) -> list[str]:
        """df = lumânări ÎNCHISE, crescător în timp. Procesează lumânările noi; întoarce mesaje."""
        events: list[str] = []
        n = len(df)
        if n == 0:
            return events
        if self.s.last_bar is None:                 # prima pornire: doar ultima lumânare, fără istoric
            start = n - 1
        else:
            last = pd.Timestamp(self.s.last_bar)
            start = int(df.index.searchsorted(last, side="right"))
        for i in range(start, n):
            events += self._on_bar(df.iloc[max(0, i + 1 - self.window): i + 1])
            self.s.last_bar = df.index[i].isoformat()
        return events

    # ------------------------------------------------------------- internals
    def _on_bar(self, w: pd.DataFrame) -> list[str]:
        t, bar = w.index[-1], w.iloc[-1]
        if self.s.position is not None:
            return self._manage(t, bar)
        if self.s.equity * self.s.leverage < self.min_notional:
            return [f"{t}: equity {self.s.equity:.2f} prea mic pentru o poziție (min {self.min_notional}) – scanner oprit."]
        trades = self.strategy.run(w, "short")
        self.setup = self.strategy.last_state_short
        sig = [x for x in trades if x.entry_idx == len(w) - 1]
        if not sig:
            return []
        return self._open(t, sig[0])

    def _open(self, t, tr) -> list[str]:
        c, notional = self.costs, self.s.equity * self.s.leverage
        fill = tr.entry_price * (1 - c.slippage_bps / 1e4)          # short: vinzi puțin mai jos
        qty = notional / fill
        self.s.position = dict(entry_time=t.isoformat(), entry_price=tr.entry_price, entry_fill=fill, stop=tr.stop,
                               target=tr.target, poc=tr.poc, notional=notional, qty=qty,
                               equity_at_entry=self.s.equity)
        return [f"{t} | SEMNAL SHORT | vinde ~{tr.entry_price:.5f} | SL (buy stop) {tr.stop:.5f} (+{(tr.stop/tr.entry_price-1)*100:.2f}%) | "
                f"TP (buy limit) {tr.target:.5f} (-{(1-tr.target/tr.entry_price)*100:.2f}%) | "
                f"mărime {notional:.2f} USDT = {qty:.2f} unități (equity {self.s.equity:.2f} x {self.s.leverage:g}) | POC {tr.poc:.5f}"]

    def _manage(self, t, bar) -> list[str]:
        p, c = self.s.position, self.costs
        if bar["high"] >= p["stop"]:                                 # stop primul (conservator)
            raw, reason = max(p["stop"], bar["open"]), "STOP"
            fill = raw * (1 + c.slippage_bps / 1e4)
        elif bar["low"] <= p["target"]:
            raw, reason = min(p["target"], bar["open"]), "TARGET"
            fill = raw
        else:
            return []
        q = p["qty"]
        pnl = q * (p["entry_fill"] - fill) - q * (p["entry_fill"] * c.entry_fee_bps + fill * c.exit_fee_bps) / 1e4
        before = self.s.equity
        self.s.equity = before + pnl
        self.s.trades.append(dict(entry_time=p["entry_time"], exit_time=t.isoformat(), entry=p["entry_fill"], exit=fill,
                                  reason=reason, notional=p["notional"], pnl=pnl, equity_after=self.s.equity))
        self.s.position = None
        return [f"{t} | {reason} | ieșire ~{fill:.5f} | PnL {pnl:+.2f} USDT ({pnl / before * 100:+.2f}% din equity) | "
                f"equity {before:.2f} -> {self.s.equity:.2f} | următorul trade intră cu {self.s.equity * self.s.leverage:.2f} USDT"]

    # ------------------------------------------------------------ afișare
    def status(self, price: float) -> str:
        s = self.s
        if s.position:
            p = s.position
            unreal = p["qty"] * (p["entry_fill"] - price)
            return (f"POZIȚIE SHORT deschisă din {p['entry_time']} @ {p['entry_price']:.5f} | preț {price:.5f} | "
                    f"PnL nerealizat {unreal:+.2f} | SL {p['stop']:.5f} TP {p['target']:.5f} | equity (realizat) {s.equity:.2f}")
        st = self.setup
        if st.get("state") == "ACTIVE":
            return (f"flat | setup SHORT în așteptare: BOS în jos făcut, aștept pullback în POC {st['poc']:.5f} "
                    f"(preț {price:.5f}; anulat dacă urcă peste {st['invalidation']:.5f}) | equity {s.equity:.2f}")
        return f"flat | fără setup activ | preț {price:.5f} | equity {s.equity:.2f}"
