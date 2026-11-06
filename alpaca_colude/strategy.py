"""Strategia „BOS -> Fixed Range Volume Profile -> pullback în POC”.

Regulile (din transcript), în ordine:

1. TREND        – structură HH + HL (ultimele 2 swing-high-uri și 2 swing-low-uri
                  cresc). Pentru short, oglinda (LH + LL).
2. BOS          – o lumânare ÎNCHIDE peste ultimul swing high (break of structure
                  în direcția trendului).
3. MIȘCAREA     – de la higher low (cel mai jos punct dintre swing high-ul rupt și
                  BOS) până la higher high (maximul mișcării, actualizat cât timp
                  se fac maxime noi).
4. VOLUME PROFILE – fixed range pe toată mișcarea HL -> HH; ne uităm la POC.
5. INTRAREA     – NU la POC-ul „de-a gata”: așteptăm pullback-ul în POC. Intrăm
                  la închiderea lumânării care atinge POC și respinge (închide
                  deasupra lui).
6. VALIDARE     – trendul trebuie să fie încă valid: HL-ul mișcării nu a fost
                  încălcat (altfel setup-ul e anulat).
7. STOP         – sub cel mai adânc fitil al reacției (+ un buffer mic din ATR).
8. TARGET       – higher high-ul anterior (maximul mișcării).

Fără look-ahead: pivoții sunt confirmați abia după `swing_n` lumânări, iar
intrarea se face la închiderea lumânării-semnal.

Shortul se obține rulând exact aceeași logică pe prețuri negate (oglindă).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .volume_profile import fixed_range_volume_profile

Side = Literal["long", "short"]


@dataclass(frozen=True)
class StrategyParams:
    swing_n: int = 5               # lumânări stânga/dreapta pentru un pivot
    atr_period: int = 14
    n_bins: int = 50               # rezoluția volume profile
    min_move_atr: float = 2.0      # mișcarea HL->BOS trebuie să fie >= x ATR
    min_move_bars: int = 5         # ...și să dureze minim atâtea lumânări
    min_rr: float = 1.0            # raport minim target/risc
    stop_buffer_atr: float = 0.1   # buffer sub fitil, în ATR
    max_wait_bars: int = 60        # cât așteptăm pullback-ul după HH
    strict_structure: bool = True  # True: și fitilul sub HL anulează setup-ul;
                                   # False: doar închiderea sub HL
    min_stop_pct: float = 0.0      # distanța minimă intrare->SL ca fracție din preț (0.02 = 2%);
                                   # dacă stop-ul structural e mai aproape, e mutat la această distanță
    tp_rr: float | None = None     # None: target = higher high; altfel TP = intrare ± tp_rr * risc


@dataclass
class Trade:
    side: Side
    start_idx: int      # HL (începutul mișcării)
    bos_idx: int        # lumânarea care a rupt structura
    high_idx: int       # HH (sfârșitul mișcării) la momentul intrării
    poc: float
    entry_idx: int
    entry_price: float
    stop: float
    target: float
    exit_idx: int = -1
    exit_price: float = float("nan")
    exit_reason: str = "open"   # "stop" | "target" | "open" (date terminate)

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop)

    @property
    def planned_rr(self) -> float:
        return abs(self.target - self.entry_price) / self.risk

    @property
    def r_multiple(self) -> float:
        d = 1.0 if self.side == "long" else -1.0
        return d * (self.exit_price - self.entry_price) / self.risk


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> np.ndarray:
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().to_numpy()


class PocPullbackStrategy:
    def __init__(self, params: StrategyParams | None = None):
        self.p = params or StrategyParams()

    # ------------------------------------------------------------------ API
    def run(self, df: pd.DataFrame, side: Literal["long", "short", "both"] = "both") -> list[Trade]:
        """Rulează strategia pe un DataFrame OHLCV (coloane: open, high, low, close, volume)."""
        o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume"))
        trades: list[Trade] = []
        if side in ("long", "both"):
            trades += self._run_long(o, h, l, c, v, "long")
        if side in ("short", "both"):
            # oglindă: preț -> -preț, high <-> low
            for t in self._run_long(-o, -l, -h, -c, v, "short"):
                t.entry_price, t.stop, t.target, t.poc = -t.entry_price, -t.stop, -t.target, -t.poc
                t.exit_price = -t.exit_price
                trades.append(t)
        return sorted(trades, key=lambda t: t.entry_idx)

    # ----------------------------------------------------------- state machine
    def _run_long(self, o, h, l, c, v, side: Side) -> list[Trade]:
        p = self.p
        n = len(c)
        atr = _atr(h, l, c, p.atr_period)
        sh: list[tuple[int, float]] = []   # swing highs confirmate
        sl: list[tuple[int, float]] = []   # swing lows confirmate
        used_sh: set[int] = set()          # swing high-uri deja rupte (un BOS / nivel)
        out: list[Trade] = []

        state = "IDLE"
        start_idx = start_low = high_idx = bos_idx = -1
        move_high = poc = 0.0
        touch_low: float | None = None
        trade: Trade | None = None

        for t in range(n):
            # 1) pivoți confirmați (fără look-ahead: pivotul t-n se vede abia acum)
            k = t - p.swing_n
            if k >= p.swing_n:
                left, right = slice(k - p.swing_n, k), slice(k + 1, t + 1)
                if h[k] > h[left].max() and h[k] >= h[right].max():
                    sh.append((k, h[k]))
                if l[k] < l[left].min() and l[k] <= l[right].min():
                    sl.append((k, l[k]))

            # 2) poziție deschisă: management stop / target
            if state == "IN_TRADE":
                assert trade is not None
                if l[t] <= trade.stop:                      # stop primul (conservator)
                    trade.exit_idx, trade.exit_price, trade.exit_reason = t, min(trade.stop, o[t]), "stop"
                elif h[t] >= trade.target:
                    trade.exit_idx, trade.exit_price, trade.exit_reason = t, max(trade.target, o[t]), "target"
                if trade.exit_idx >= 0:
                    out.append(trade)
                    trade, state = None, "IDLE"
                continue

            # 3) caută BOS în direcția trendului
            if state == "IDLE":
                if np.isnan(atr[t]) or len(sh) < 2 or len(sl) < 2:
                    continue
                last_sh = sh[-1]
                if last_sh[0] in used_sh or c[t] <= last_sh[1]:
                    continue
                used_sh.add(last_sh[0])
                trend_up = sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]
                if not trend_up:
                    continue
                s = last_sh[0] + int(np.argmin(l[last_sh[0]: t + 1]))
                if l[s] < sl[-1][1]:                        # nu e higher low
                    continue
                if c[t] - l[s] < p.min_move_atr * atr[t] or t - s < p.min_move_bars:
                    continue
                state, start_idx, start_low, bos_idx = "ACTIVE", s, l[s], t
                high_idx = s + int(np.argmax(h[s: t + 1]))
                move_high = h[high_idx]
                poc = fixed_range_volume_profile(
                    h[s: high_idx + 1], l[s: high_idx + 1], v[s: high_idx + 1], p.n_bins).poc
                touch_low = None
                continue

            # 4) setup activ: așteptăm pullback în POC + reacție
            broken = (l[t] <= start_low) if p.strict_structure else (c[t] <= start_low)
            if broken:                                      # trend invalid -> anulează
                state = "IDLE"
                continue
            if h[t] > move_high:                            # HH nou -> reface profilul
                high_idx, move_high = t, h[t]
                poc = fixed_range_volume_profile(
                    h[start_idx: t + 1], l[start_idx: t + 1], v[start_idx: t + 1], p.n_bins).poc
                touch_low = None
                continue
            if t - high_idx > p.max_wait_bars:
                state = "IDLE"
                continue
            if l[t] <= poc:                                 # prețul a atins POC-ul
                touch_low = l[t] if touch_low is None else min(touch_low, l[t])
                if c[t] > poc:                              # reacție: respinge POC-ul
                    entry = c[t]
                    stop = touch_low - p.stop_buffer_atr * atr[t]
                    stop = min(stop, entry - p.min_stop_pct * abs(entry))   # SL minim
                    risk = entry - stop
                    target = move_high if p.tp_rr is None else entry + p.tp_rr * risk
                    if risk > 0 and (target - entry) >= p.min_rr * risk:
                        trade = Trade(side, start_idx, bos_idx, high_idx, poc, t, entry, stop, target)
                        state = "IN_TRADE"
                    else:
                        state = "IDLE"

        if trade is not None:                               # date terminate cu poziție deschisă
            trade.exit_idx, trade.exit_price, trade.exit_reason = n - 1, c[-1], "open"
            out.append(trade)
        return out
