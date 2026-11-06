import numpy as np
import pandas as pd
import pytest

from alpaca_colude import PocPullbackStrategy, StrategyParams, backtest, fixed_range_volume_profile
from alpaca_colude.data import synthetic_bars

P = StrategyParams(swing_n=2, atr_period=5, min_move_atr=1.0, min_move_bars=3, stop_buffer_atr=0.0)


def bars_from_path(waypoints, per_leg=6, vols=None):
    """Lumânări din drum liniar pe waypoints; fiecare lumânare are fitil de ±0.3."""
    closes = [waypoints[0]]
    for a, b in zip(waypoints[:-1], waypoints[1:]):
        closes += list(np.linspace(a, b, per_leg + 1)[1:])
    c = np.array(closes)
    o = np.concatenate([[c[0]], c[:-1]])
    h, l = np.maximum(o, c) + 0.3, np.minimum(o, c) - 0.3
    v = np.ones(len(c)) if vols is None else vols(c)
    idx = pd.date_range("2024-01-01", periods=len(c), freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_poc_is_where_volume_traded():
    high = np.array([10.5, 20.5, 15.5])
    low = np.array([9.5, 19.5, 14.5])
    vol = np.array([1.0, 1.0, 100.0])
    vp = fixed_range_volume_profile(high, low, vol, n_bins=20)
    assert 14.5 <= vp.poc <= 15.5


def test_poc_without_volume_falls_back_to_time():
    vp = fixed_range_volume_profile(np.array([11.0, 11.0, 21.0]), np.array([10.0, 10.0, 20.0]), np.zeros(3), 10)
    assert 10.0 <= vp.poc <= 11.0


# HH/HL clar -> BOS -> HH nou -> pullback în POC -> respingere -> target = HH.
WAY = [100, 110, 105, 120, 112, 130, 135, 121, 129, 137, 140]
# volum mare în zona 124-128, deci POC-ul mișcării 112->135 e acolo
def heavy_mid(c):
    return np.where((c > 123) & (c < 129), 50.0, 1.0)


def test_handcrafted_long_follows_every_rule():
    df = bars_from_path(WAY, vols=heavy_mid)
    trades = PocPullbackStrategy(P).run(df, "long")
    assert trades, "trebuia să apară un setup long"
    t = trades[0]
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    assert t.side == "long"
    assert t.bos_idx < t.entry_idx and t.high_idx < t.entry_idx          # intră DUPĂ pullback
    assert 123 < t.poc < 129                                              # POC din zona cu volum
    assert l[t.entry_idx] <= t.poc < t.entry_price                        # a atins POC și l-a respins
    assert t.target == pytest.approx(h[t.start_idx: t.entry_idx + 1].max())  # target = higher high
    assert t.stop < l[t.entry_idx] + 1e-9                                 # stop sub fitilul reacției
    assert t.stop > l[t.start_idx]                                        # structura (HL) intactă
    assert t.planned_rr >= P.min_rr
    assert t.exit_reason == "target"


def test_structure_break_cancels_setup():
    # după BOS prețul cade sub HL (112) fără să atingă înainte POC-ul bun -> fără intrare
    way = [100, 110, 105, 120, 112, 130, 135, 100, 95]
    trades = PocPullbackStrategy(P).run(bars_from_path(way, vols=heavy_mid), "long")
    assert trades == []


def test_no_lookahead():
    df = synthetic_bars(3000, seed=3)
    full = PocPullbackStrategy().run(df)
    k = 1800
    part = PocPullbackStrategy().run(df.iloc[:k])
    key = lambda t: (t.side, t.entry_idx, round(t.entry_price, 9), round(t.stop, 9), round(t.target, 9))
    assert [key(t) for t in part] == [key(t) for t in full if t.entry_idx < k]


def test_invariants_on_random_data():
    for seed in range(5):
        df = synthetic_bars(3000, seed=seed)
        for t in PocPullbackStrategy().run(df):
            d = 1 if t.side == "long" else -1
            assert d * (t.target - t.entry_price) > 0 > d * (t.stop - t.entry_price)
            assert t.planned_rr >= 1.0 - 1e-9
            assert t.exit_idx > t.entry_idx or t.exit_reason == "open"


def test_short_is_mirror_of_long():
    df = synthetic_bars(3000, seed=1)
    mirror = df.copy()
    mirror[["open", "close"]] = 1000 - df[["open", "close"]]
    mirror["high"], mirror["low"] = 1000 - df["low"], 1000 - df["high"]
    longs = PocPullbackStrategy().run(df, "long")
    shorts = PocPullbackStrategy().run(mirror, "short")
    assert len(longs) == len(shorts) > 0
    for a, b in zip(longs, shorts):
        assert a.entry_idx == b.entry_idx and a.r_multiple == pytest.approx(b.r_multiple, abs=1e-6)


def test_backtest_risk_is_about_one_percent():
    res = backtest(synthetic_bars(4000, seed=0), risk_pct=0.01, slippage_bps=0)
    assert res.stats["trades"] > 0
    stops = res.trades[res.trades.reason == "stop"]
    assert (stops.r.between(-1.2, -0.99)).all()
