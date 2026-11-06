import numpy as np
import pytest

from alpaca_colude import PocPullbackStrategy, StrategyParams
from alpaca_colude.data import synthetic_bars
from reference_impl import reference_long


def arrays(df):
    return [df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")]


@pytest.mark.parametrize("params", [
    StrategyParams(),
    StrategyParams(min_stop_pct=0.02, tp_rr=2.0),
    StrategyParams(fixed_stop_pct=0.015, tp_rr=2.5, strict_structure=False),
])
def test_main_matches_independent_reference(params):
    for seed in range(4):
        df = synthetic_bars(2500, seed=seed)
        main = PocPullbackStrategy(params).run(df, "long")
        ref = reference_long(*arrays(df), params)
        assert len(main) == len(ref) > 0
        for t, r in zip(main, ref):
            assert (t.entry_idx, t.exit_idx, t.exit_reason) == (r[0], r[4], r[6])
            for a, b in ((t.entry_price, r[1]), (t.stop, r[2]), (t.target, r[3]), (t.exit_price, r[5]), (t.poc, r[7])):
                assert a == pytest.approx(b, rel=1e-9)
