import pandas as pd
import pytest

from alpaca_colude import PocPullbackStrategy
from alpaca_colude.data import synthetic_bars
from alpaca_colude.live import BEST_PARAMS, Costs, LiveScanner, ScannerState, parse_klines

DF = synthetic_bars(1200, seed=19)      # 5 trade-uri short (și stop, și target)
C = Costs()


def expected_chain(trades, equity=100.0, lev=1.0):
    """Calcul de mână al mărimii compuse pe trade-urile ÎNCHISE ale strategiei (short)."""
    out = []
    for t in trades:
        if t.exit_reason == "open":
            break
        fill = t.entry_price * (1 - C.slippage_bps / 1e4)
        qty = equity * lev / fill
        x = t.exit_price * (1 + C.slippage_bps / 1e4) if t.exit_reason == "stop" else t.exit_price
        pnl = qty * (fill - x) - qty * (fill * C.entry_fee_bps + x * C.exit_fee_bps) / 1e4
        out.append((t.entry_idx, equity * lev, pnl, equity + pnl))
        equity += pnl
    return out


def run_scanner(df, lev=1.0, chunks=1):
    st = ScannerState(equity=100.0, leverage=lev, last_bar=df.index[0].isoformat())
    sc = LiveScanner(st, BEST_PARAMS, window=len(df))       # fereastră = tot istoricul -> identic cu strategia
    events = []
    step = len(df) // chunks
    for k in range(chunks):
        end = len(df) if k == chunks - 1 else (k + 1) * step
        events += sc.process(df.iloc[:end])
    return st, events


@pytest.mark.parametrize("lev", [1.0, 3.0])
def test_scanner_compounds_and_matches_strategy(lev):
    trades = PocPullbackStrategy(BEST_PARAMS).run(DF, "short")
    exp = expected_chain(trades, lev=lev)
    assert len(exp) >= 5 and {t.exit_reason for t in PocPullbackStrategy(BEST_PARAMS).run(DF, "short")} >= {"stop", "target"}
    st, _ = run_scanner(DF, lev)
    assert len(st.trades) == len(exp)
    for got, (idx, notional, pnl, eq_after) in zip(st.trades, exp):
        assert got["entry_time"] == DF.index[idx].isoformat()
        assert got["notional"] == pytest.approx(notional)           # intră cu tot equity-ul (x leverage)
        assert got["pnl"] == pytest.approx(pnl)
        assert got["equity_after"] == pytest.approx(eq_after)


def test_next_trade_uses_updated_equity():
    st, _ = run_scanner(DF)
    prev = 100.0
    for tr in st.trades:
        assert tr["notional"] == pytest.approx(prev)                # mărimea = equity-ul de după trade-ul anterior
        prev = tr["equity_after"]


def test_restart_gives_same_result():
    a, _ = run_scanner(DF, chunks=1)
    b, _ = run_scanner(DF, chunks=5)                                 # procesare în bucăți, ca după repornire
    assert [t["pnl"] for t in a.trades] == pytest.approx([t["pnl"] for t in b.trades])
    assert a.equity == pytest.approx(b.equity)


def test_state_roundtrip(tmp_path):
    st, _ = run_scanner(DF)
    p = str(tmp_path / "s.json")
    st.save(p)
    back = ScannerState.load(p)
    assert back.equity == pytest.approx(st.equity) and back.trades == st.trades and back.last_bar == st.last_bar


def test_parse_klines_drops_unclosed_candle():
    rows = [[0, "1", "2", "0.5", "1.5", "10", 899999, 0, 0, 0, 0, 0],
            [900000, "1.5", "2", "1", "1.2", "10", 1799999, 0, 0, 0, 0, 0],
            [1800000, "1.2", "1.3", "1.1", "1.25", "5", 2699999, 0, 0, 0, 0, 0]]   # încă se formează
    df = parse_klines(rows, now_ms=2000000)
    assert len(df) == 2 and df["close"].tolist() == [1.5, 1.2]
    assert df.index[0] == pd.Timestamp(0, unit="ms", tz="UTC")


def test_first_run_only_looks_at_latest_bar():
    st = ScannerState(equity=100.0)
    sc = LiveScanner(st, BEST_PARAMS, window=500)
    sc.process(DF)
    assert st.last_bar == DF.index[-1].isoformat() and st.trades == []   # nu reface istoricul la prima pornire
