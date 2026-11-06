"""Backtest cu risc fix pe trade (fixed fractional)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategy import PocPullbackStrategy, StrategyParams


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series      # equity realizat, indexat la momentul închiderii fiecărui trade
    stats: dict


def backtest(
    df: pd.DataFrame,
    params: StrategyParams | None = None,
    side: str = "both",
    initial_equity: float = 10_000.0,
    risk_pct: float = 0.01,       # % din equity riscat per trade
    max_leverage: float = 1.0,    # limită notional / equity
    slippage_bps: float = 1.0,    # slippage advers la intrare și la stop
    position_pct: float | None = None,  # dacă e setat: notional = position_pct * equity (ignoră risk_pct)
    fee_bps: float = 0.0,         # comision per parte (intrare și ieșire), în bps din notional
) -> BacktestResult:
    raw = PocPullbackStrategy(params).run(df, side)
    slip = slippage_bps / 1e4
    rows = []
    for t in raw:
        d = 1.0 if t.side == "long" else -1.0
        entry = t.entry_price * (1 + d * slip)
        exit_ = t.exit_price * (1 - d * slip) if t.exit_reason in ("stop", "open") else t.exit_price
        rows.append((t, d, entry, exit_))

    rows.sort(key=lambda r: r[0].entry_idx)
    realized = initial_equity
    pending: list[tuple[int, float]] = []   # (exit_idx, pnl) încă nerealizate
    records, curve = [], []
    for t, d, entry, exit_ in rows:
        for e_idx, pnl in [x for x in pending if x[0] <= t.entry_idx]:
            realized += pnl
        pending = [x for x in pending if x[0] > t.entry_idx]

        risk_per_unit = abs(entry - t.stop)
        if risk_per_unit <= 0:
            continue
        if position_pct is not None:
            qty = realized * position_pct / entry
        else:
            qty = min(realized * risk_pct / risk_per_unit, realized * max_leverage / entry)
        fees = qty * (entry + exit_) * fee_bps / 1e4
        pnl = qty * d * (exit_ - entry) - fees
        pending.append((t.exit_idx, pnl))
        records.append({
            "side": t.side,
            "entry_time": df.index[t.entry_idx], "entry": entry, "stop": t.stop, "target": t.target,
            "poc": t.poc, "exit_time": df.index[t.exit_idx], "exit": exit_, "reason": t.exit_reason,
            "qty": qty, "pnl": pnl, "r": d * (exit_ - entry) / risk_per_unit,
            "risk_pct_equity": qty * risk_per_unit / realized,
            "planned_rr": abs(t.target - entry) / risk_per_unit,
        })

    trades = pd.DataFrame(records)
    if trades.empty:
        return BacktestResult(trades, pd.Series(dtype=float), {"trades": 0})

    by_exit = trades.sort_values("exit_time")
    equity = initial_equity + by_exit["pnl"].cumsum()
    equity.index = by_exit["exit_time"]
    wins, losses = trades.loc[trades.pnl > 0, "pnl"], trades.loc[trades.pnl <= 0, "pnl"]
    dd = (equity / equity.cummax() - 1).min()
    stats = {
        "trades": len(trades),
        "win_rate": float((trades.pnl > 0).mean()),
        "avg_R": float(trades.r.mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "total_return": float(equity.iloc[-1] / initial_equity - 1),
        "max_drawdown": float(dd),
        "final_equity": float(equity.iloc[-1]),
    }
    return BacktestResult(trades, equity, stats)
