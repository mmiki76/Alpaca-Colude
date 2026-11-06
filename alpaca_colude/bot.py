"""Bot PAPER pentru Binance Futures (testnet/demo): strategia POC-pullback, mărime compusă, leverage setabil.

Fluxul (la fiecare `tick`, ~10 s):
  1. citește lumânările ÎNCHISE (date mainnet publice, ca în backtest, sau de pe testnet);
  2. reconciliază poziția: dacă exchange-ul a închis-o (SL/TP), calculează PnL-ul real din fill-uri,
     actualizează equity-ul (=> trade-ul următor intră cu equity-ul nou, compus);
  3. SL software de rezervă (dacă SL-ul de pe exchange n-a funcționat);
  4. dacă ești flat și apare semnal pe ultima lumânare: ordin MARKET + SL + TP calculate din prețul de fill.
Garanții: dacă SL-ul nu se poate plasa, poziția se închide imediat; nu se intră dacă pe exchange există deja
o poziție necunoscută; nu se acceptă mainnet.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

import pandas as pd

from .exchange import ALLOWED_BASES, BinanceError, round_to
from .live import fetch_klines, parse_klines
from .strategy import PocPullbackStrategy, StrategyParams

INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def utc_iso(ms: float | None = None) -> str:
    t = datetime.fromtimestamp((ms if ms is not None else time.time() * 1000) / 1000, tz=timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class BotConfig:
    symbol: str = "VETUSDT"                # VETUSDC nu există ca perpetuu pe Binance Futures (doar spot)
    interval: str = "15m"
    side: str = "short"                    # varianta testată în backtest: short
    leverage: int = 1
    size_pct: float = 98.0                 # % din equity folosit ca marjă*leverage (restul = rezervă pentru comisioane)
    capital_mode: str = "virtual"          # virtual: pornești de la start_equity și compui PnL-ul real; account: tot soldul
    start_equity: float = 100.0
    stop_pct: float = 2.0                  # SL în % față de prețul de fill
    tp_rr: float = 2.5                     # TP = tp_rr x SL
    swing_n: int = 5
    min_move_atr: float = 3.0
    margin_type: str = "ISOLATED"
    trading_enabled: bool = True           # False = doar semnale (fără ordine)
    software_stop: bool = True             # SL/TP de rezervă în software
    data_source: str = "mainnet"           # mainnet = date publice (ca în backtest) | exchange = lumânări de pe testnet
    base_url: str = ALLOWED_BASES[0]
    poll_seconds: int = 10
    window: int = 1500

    def validate(self) -> "BotConfig":
        if not re.fullmatch(r"[A-Z0-9]{4,20}", self.symbol) or not self.symbol.endswith(("USDT", "USDC")):
            raise ValueError("symbol invalid (ex. VETUSDT)")
        if self.interval not in INTERVAL_MS:
            raise ValueError(f"interval invalid: {list(INTERVAL_MS)}")
        if self.side not in ("short", "long"):
            raise ValueError("side: short | long")
        if not (isinstance(self.leverage, int) and 1 <= self.leverage <= 25):
            raise ValueError("leverage: întreg între 1 și 25")
        for name, lo, hi in (("size_pct", 1, 100), ("start_equity", 1, 10_000_000), ("stop_pct", 0.3, 10),
                             ("tp_rr", 0.5, 10), ("min_move_atr", 0, 10)):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi):
                raise ValueError(f"{name} trebuie să fie între {lo} și {hi}")
        if not (isinstance(self.swing_n, int) and 2 <= self.swing_n <= 12):
            raise ValueError("swing_n: întreg între 2 și 12")
        if self.margin_type not in ("ISOLATED", "CROSSED"):
            raise ValueError("margin_type: ISOLATED | CROSSED")
        if self.capital_mode not in ("virtual", "account"):
            raise ValueError("capital_mode: virtual | account")
        if self.data_source not in ("mainnet", "exchange"):
            raise ValueError("data_source: mainnet | exchange")
        if self.base_url.rstrip("/") not in ALLOWED_BASES:
            raise ValueError("base_url: doar testnet/demo")
        if not (2 <= self.poll_seconds <= 300) or not (300 <= self.window <= 1500):
            raise ValueError("poll_seconds 2..300, window 300..1500")
        return self

    @property
    def quote(self) -> str:
        return "USDC" if self.symbol.endswith("USDC") else "USDT"

    def strategy_params(self) -> StrategyParams:
        return StrategyParams(fixed_stop_pct=self.stop_pct / 100, tp_rr=self.tp_rr, swing_n=self.swing_n,
                              min_move_atr=self.min_move_atr)

    @classmethod
    def from_dict(cls, d: dict) -> "BotConfig":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names}).validate()


@dataclass
class BotState:
    equity: float
    start_equity: float
    position: dict | None = None
    trades: list = field(default_factory=list)
    curve: list = field(default_factory=list)       # [[iso, equity], ...]
    events: list = field(default_factory=list)      # [[iso, level, text], ...]
    paused: bool = False
    last_bar: str | None = None


def make_data_fn(exchange=None):
    def fn(cfg: BotConfig) -> pd.DataFrame:
        if cfg.data_source == "exchange" and exchange is not None:
            return parse_klines(exchange.klines(cfg.symbol, cfg.interval, cfg.window + 5), int(time.time() * 1000))
        return fetch_klines(cfg.symbol, cfg.interval, cfg.window + 5, "futures")
    return fn


class PaperBot:
    GUARD_EXTRA = 0.003      # SL software: acționează doar dacă prețul depășește SL-ul cu >0,3% (exchange-ul trebuia să fi acționat)

    def __init__(self, cfg: BotConfig, exchange, data_fn, state_path: str | None = None, cfg_path: str | None = None):
        self.cfg, self.ex, self.data_fn = cfg.validate(), exchange, data_fn
        self.state_path, self.cfg_path = state_path, cfg_path
        self.lock = threading.RLock()
        self.setup: dict = {"state": "IDLE"}
        self.last_price: float | None = None
        self.last_tick: str | None = None
        self._applied: tuple | None = None            # (symbol, leverage, margin) deja setate pe exchange
        self.state = self._load_state()

    # ---------------------------------------------------------------- stare
    def _load_state(self) -> BotState:
        if self.state_path and os.path.exists(self.state_path):
            with open(self.state_path) as f:
                return BotState(**json.load(f))
        s = BotState(equity=self.cfg.start_equity, start_equity=self.cfg.start_equity)
        s.curve.append([utc_iso(), s.equity])
        return s

    def _save(self) -> None:
        if self.state_path:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(asdict(self.state), f, indent=1)
            os.replace(tmp, self.state_path)

    def log(self, level: str, text: str) -> None:
        self.state.events.append([utc_iso(self._now_ms()), level, text])
        del self.state.events[:-300]

    def _now_ms(self) -> int:
        return int(getattr(self.ex, "now_ms", 0) or time.time() * 1000)

    def _equity(self) -> float:
        if self.cfg.capital_mode == "account":
            return self.ex.balance(self.cfg.quote)["balance"]
        return self.state.equity

    # ----------------------------------------------------------------- tick
    def tick(self) -> None:
        with self.lock:
            try:
                df = self.data_fn(self.cfg)
                self.last_tick = utc_iso()
                self.last_price = self.ex.last_price(self.cfg.symbol)
                self._reconcile()
                self._software_guard()
                self._on_bar(df)
            except Exception as e:                                  # rețea/API: loghează și continuă
                self.log("error", f"{type(e).__name__}: {e}")
            self._save()

    def _on_bar(self, df: pd.DataFrame) -> None:
        if len(df) == 0:
            return
        t = df.index[-1]
        if self.state.last_bar is not None and t.isoformat() <= self.state.last_bar:
            return
        first_run = self.state.last_bar is None
        self.state.last_bar = t.isoformat()
        if self.state.position is not None or self.state.paused:
            return
        w = df.iloc[-self.cfg.window:]
        strat = PocPullbackStrategy(self.cfg.strategy_params())
        sigs = [x for x in strat.run(w, self.cfg.side) if x.entry_idx == len(w) - 1]
        self.setup = strat.last_state_short if self.cfg.side == "short" else strat.last_state_long
        if not sigs:
            return
        if not getattr(self.ex, "is_sim", False):
            age = self._now_ms() - (t.timestamp() * 1000 + INTERVAL_MS[self.cfg.interval])
            if age > 2 * INTERVAL_MS[self.cfg.interval]:
                self.log("warn", f"semnal vechi ignorat ({t}), lumânarea nu mai e proaspătă")
                return
        if first_run:
            self.log("info", "prima pornire: semnalul de pe ultima lumânare e luat în considerare")
        self._enter(t, sigs[0])

    # ---------------------------------------------------------------- intrare
    def _enter(self, bar_time, sig) -> None:
        c, ex = self.cfg, self.ex
        if not c.trading_enabled:
            self.log("signal", f"SEMNAL {c.side.upper()} {c.symbol} ~{sig.entry_price:.6g} (trading dezactivat – nu trimit ordine)")
            return
        if abs(ex.position(c.symbol)["amt"]) > 0:
            self.log("warn", "pe exchange există deja o poziție necunoscută pe acest simbol – nu intru")
            return
        rules, price = ex.rules(c.symbol), ex.last_price(c.symbol)
        bal = ex.balance(c.quote)
        notional = self._equity() * c.size_pct / 100 * c.leverage
        notional = min(notional, bal["available"] * c.leverage * 0.98)          # nu depăși marja disponibilă
        qty = round_to(notional / price, rules.step, "down")
        if qty < rules.min_qty or qty * price < rules.min_notional:
            self.log("warn", f"mărime sub minim ({qty*price:.2f} < {rules.min_notional} {c.quote}) – nu intru")
            return
        key = (c.symbol, c.leverage, c.margin_type)
        if self._applied != key:
            ex.set_margin_type(c.symbol, c.margin_type)
            ex.set_leverage(c.symbol, c.leverage)
            self._applied = key
        d = -1 if c.side == "short" else 1
        side, close_side = ("SELL", "BUY") if c.side == "short" else ("BUY", "SELL")
        fill = ex.market_order(c.symbol, side, qty)
        entry = fill["avg_price"] or price
        stop = round_to(entry * (1 - d * c.stop_pct / 100), rules.tick, "nearest")
        target = round_to(entry * (1 + d * c.stop_pct * c.tp_rr / 100), rules.tick, "nearest")
        entry_ms = self._now_ms()
        self.state.position = dict(side=c.side, qty=fill["qty"] or qty, entry=entry, stop=stop, target=target,
                                   entry_time=utc_iso(entry_ms), entry_ms=entry_ms, signal_bar=bar_time.isoformat(),
                                   notional=(fill["qty"] or qty) * entry, leverage=c.leverage,
                                   equity_at_entry=self._equity(), tp_ok=True)
        try:
            ex.stop_close_order(c.symbol, close_side, stop)
        except Exception as e:                                                   # NICIODATĂ fără SL (nici la erori de rețea)
            self.log("error", f"SL nu s-a putut plasa ({e}) – închid poziția imediat")
            self._force_close("SL EȘUAT – poziție închisă imediat")
            return
        try:
            ex.limit_order(c.symbol, close_side, fill["qty"] or qty, target, reduce_only=True)
        except Exception as e:
            self.state.position["tp_ok"] = False
            self.log("warn", f"TP nu s-a putut plasa ({e}) – rămâne SL + TP software")
        self.log("trade", f"INTRARE {c.side.upper()} {c.symbol}: {qty} @ {entry:.6g} | SL {stop:.6g} | TP {target:.6g} | "
                          f"mărime {qty*entry:.2f} {c.quote} (equity {self._equity():.2f} x {c.leverage})")

    # ------------------------------------------------------- reconciliere/ieșire
    def _reconcile(self, reason_override: str | None = None) -> None:
        p = self.state.position
        if p is None:
            return
        rules = self.ex.rules(self.cfg.symbol)
        if abs(self.ex.position(self.cfg.symbol)["amt"]) >= rules.step / 2:
            return                                                                  # încă deschisă
        close_side = "BUY" if p["side"] == "short" else "SELL"
        fills = self.ex.user_trades(self.cfg.symbol, p["entry_ms"] - 5000)
        q = self.cfg.quote
        pnl = sum(f["realized"] for f in fills) - sum(f["commission"] for f in fills if f["asset"] == q)
        closing = [f for f in fills if f["side"] == close_side]
        exit_px = (sum(f["price"] * f["qty"] for f in closing) / sum(f["qty"] for f in closing)) if closing else p["entry"]
        d = -1 if p["side"] == "short" else 1
        if d * (exit_px - p["target"]) >= -abs(p["target"]) * 0.0005:
            reason = "TARGET"
        elif d * (exit_px - p["stop"]) <= abs(p["stop"]) * 0.0005:
            reason = "STOP"
        else:
            reason = "ALTUL (închis manual/software)"
        reason = reason_override or reason
        self.ex.cancel_all(self.cfg.symbol)
        before = self._equity() if self.cfg.capital_mode == "account" else self.state.equity
        if self.cfg.capital_mode == "virtual":
            self.state.equity += pnl
            after = self.state.equity
        else:
            after = self.ex.balance(q)["balance"]
        self.state.trades.append(dict(entry_time=p["entry_time"], exit_time=utc_iso(self._now_ms()), side=p["side"],
                                      entry=p["entry"], exit=exit_px, qty=p["qty"], notional=p["notional"],
                                      leverage=p["leverage"], reason=reason, pnl=pnl,
                                      pnl_pct=pnl / p["equity_at_entry"] * 100 if p["equity_at_entry"] else 0.0,
                                      equity_after=after))
        if getattr(self.ex, "is_sim", False) and len(self.state.curve) == 1:      # în simulare: punctul de start = momentul simulat
            self.state.curve[0][0] = p["entry_time"]
        self.state.curve.append([utc_iso(self._now_ms()), after])
        self.state.position = None
        self.log("trade", f"{reason} | ieșire ~{exit_px:.6g} | PnL {pnl:+.4f} {q} | equity {before:.2f} -> {after:.2f} "
                          f"| următorul trade: {after * self.cfg.size_pct / 100 * self.cfg.leverage:.2f} {q}")

    def _software_guard(self) -> None:
        p, c = self.state.position, self.cfg
        if p is None or not c.software_stop or self.last_price is None:
            return
        d = -1 if p["side"] == "short" else 1
        beyond_stop = d * (self.last_price - p["stop"]) <= -abs(p["stop"]) * self.GUARD_EXTRA
        hit_target = (not p.get("tp_ok", True)) and d * (self.last_price - p["target"]) >= 0
        if beyond_stop or hit_target:
            self.log("warn", f"SL/TP software activat la {self.last_price:.6g}")
            self._force_close()

    def _force_close(self, reason: str | None = None) -> None:
        p = self.state.position
        if p is None:
            return
        close_side = "BUY" if p["side"] == "short" else "SELL"
        amt = abs(self.ex.position(self.cfg.symbol)["amt"])
        if amt > 0:
            self.ex.market_order(self.cfg.symbol, close_side, amt, reduce_only=True)
        self.ex.cancel_all(self.cfg.symbol)
        self._reconcile(reason)

    # ------------------------------------------------------------ control (dashboard)
    def pause(self) -> None:
        with self.lock:
            self.state.paused = True
            self.log("info", "pauză: nu mai intru în trade-uri noi (poziția existentă rămâne cu SL/TP)")
            self._save()

    def resume(self) -> None:
        with self.lock:
            self.state.paused = False
            self.log("info", "reluat")
            self._save()

    def close_position(self) -> None:
        with self.lock:
            if self.state.position is None:
                return
            self.log("warn", "închidere manuală din dashboard")
            self._force_close()
            self._save()

    def update_config(self, patch: dict) -> BotConfig:
        with self.lock:
            allowed = {f.name for f in fields(BotConfig)} - {"base_url"}
            bad = set(patch) - allowed
            if bad:
                raise ValueError(f"setări necunoscute/needitabile: {sorted(bad)}")
            new = BotConfig(**{**asdict(self.cfg), **patch}).validate()
            if self.state.position is not None and new.symbol != self.cfg.symbol:
                raise ValueError("nu poți schimba simbolul cât timp ai poziție deschisă")
            changed = {k: v for k, v in asdict(new).items() if getattr(self.cfg, k) != v}
            self.cfg = new
            if "start_equity" in changed and not self.state.trades and self.state.position is None:
                self.state.equity = self.state.start_equity = new.start_equity
                self.state.curve = [[utc_iso(), new.start_equity]]
            if changed:
                self.log("info", f"setări schimbate: {changed}" + (" (leverage se aplică la următoarea intrare)" if "leverage" in changed else ""))
            if self.cfg_path:
                with open(self.cfg_path, "w") as f:
                    json.dump(asdict(new), f, indent=1)
            self._save()
            return new

    # --------------------------------------------------------------- dashboard
    def snapshot(self) -> dict:
        with self.lock:
            s, c = self.state, self.cfg
            pos = None
            if s.position:
                pos = dict(s.position)
                try:
                    u = self.ex.position(c.symbol)["unrealized"]
                except Exception:
                    u = float("nan")
                pos["unrealized"] = None if (isinstance(u, float) and math.isnan(u)) else u
            trades = s.trades
            wins = [t for t in trades if t["pnl"] > 0]
            vals = [x[1] for x in s.curve]
            peak, dd = (vals[0] if vals else s.equity), 0.0
            for v in vals:
                peak = max(peak, v)
                dd = min(dd, v / peak - 1)
            daily: dict[str, dict] = {}
            for t in trades:
                day = t["exit_time"][:10]
                d = daily.setdefault(day, {"day": day, "trades": 0, "pnl": 0.0})
                d["trades"] += 1
                d["pnl"] += t["pnl"]
            cum = 0.0
            for d in sorted(daily.values(), key=lambda x: x["day"]):
                cum += d["pnl"]
                d["cum"] = cum
            eq = self._equity() if c.capital_mode == "virtual" else s.equity
            return dict(
                config=asdict(c), paused=s.paused, mode="SIM" if getattr(self.ex, "is_sim", False) else "TESTNET",
                last_tick=self.last_tick, last_bar=s.last_bar, price=self.last_price, setup=self.setup,
                equity=eq, start_equity=s.start_equity, return_pct=(eq / s.start_equity - 1) * 100 if s.start_equity else 0.0,
                next_size=eq * c.size_pct / 100 * c.leverage, position=pos,
                stats=dict(trades=len(trades), wins=len(wins), win_rate=(len(wins) / len(trades) * 100 if trades else None),
                           pnl=sum(t["pnl"] for t in trades), max_dd_pct=dd * 100),
                trades=list(reversed(trades[-50:])), curve=s.curve[-500:], events=list(reversed(s.events[-60:])),
                daily=sorted(daily.values(), key=lambda x: x["day"], reverse=True)[:14])


# ----------------------------------------------------------------- selftest
def selftest(ex, cfg: BotConfig, say=print) -> bool:
    """Parcurge tot ciclul pe contul de testnet cu mărime MINIMĂ: reguli, sold, leverage, intrare, SL, TP, anulare, ieșire."""
    sym, q, ok = cfg.symbol, cfg.quote, True

    def step(name, fn):
        nonlocal ok
        try:
            r = fn()
            say(f"  OK    {name}: {r}")
            return r
        except Exception as e:
            ok = False
            say(f"  EȘEC  {name}: {e}")
            return None

    say(f"Selftest {sym} pe {getattr(ex, 'base', 'SIM')} (mărime minimă, bani de test)")
    rules = step("reguli simbol (tick/step/min notional)", lambda: ex.rules(sym))
    price = step("preț curent", lambda: ex.last_price(sym))
    step("sold", lambda: ex.balance(q))
    if not rules or not price:
        return False
    step("margin type", lambda: ex.set_margin_type(sym, cfg.margin_type) or "ok")
    step("leverage", lambda: ex.set_leverage(sym, cfg.leverage) and "ok")
    qty = round_to(max(rules.min_qty, rules.min_notional * 1.3 / price), rules.step, "up")
    side, close_side = ("SELL", "BUY") if cfg.side == "short" else ("BUY", "SELL")
    d = -1 if cfg.side == "short" else 1
    fill = step(f"ordin MARKET {side} {qty}", lambda: ex.market_order(sym, side, qty))
    if fill:
        entry = fill["avg_price"] or price
        step("SL (STOP_MARKET închide poziția, endpoint algo)", lambda: ex.stop_close_order(sym, close_side, round_to(entry * (1 - d * 0.03), rules.tick, "nearest")))
        step("TP (LIMIT reduce-only)", lambda: ex.limit_order(sym, close_side, qty, round_to(entry * (1 + d * 0.05), rules.tick, "nearest")))
        step("poziția apare pe exchange", lambda: ex.position(sym))
        step("anulare ordine deschise", lambda: ex.cancel_all(sym) or "ok")
        step(f"închidere poziție (MARKET {close_side} reduce-only)", lambda: ex.market_order(sym, close_side, qty, reduce_only=True))
        pos = step("poziția e 0 după închidere", lambda: ex.position(sym))
        if pos and abs(pos["amt"]) > 0:
            ok = False
        step("istoric fill-uri (userTrades)", lambda: f"{len(ex.user_trades(sym, int(time.time() * 1000) - 120_000))} fill-uri")
    say("REZULTAT: " + ("TOT OK – poți porni botul." if ok else "UNELE PASE AU EȘUAT – nu porni botul înainte să le rezolvi."))
    return ok


def run_forever(bot: PaperBot, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    while not stop.is_set():
        bot.tick()
        stop.wait(bot.cfg.poll_seconds)
