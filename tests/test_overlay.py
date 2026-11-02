import numpy as np
import pandas as pd

from quant.overlay import OverlayCosts, run_overlay, synth_leveraged, weights_for


def _core(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, n))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    return pd.DataFrame({"open": open_, "close": close}, index=idx)


def test_full_exposure_zero_cost_matches_buy_hold_from_first_open():
    core = _core()
    lev = synth_leveraged(core, 0.0)
    tgt = pd.Series(1.0, index=core.index)
    res = run_overlay(core, lev, tgt, costs=OverlayCosts(mult=0.0))
    eq = res["equity"]
    # 第 0 天的訊號在第 1 天開盤成交
    expect = core["close"].iloc[1:] / core["open"].iloc[1]
    assert np.isclose(eq.iloc[0], 1.0)
    assert np.allclose(eq.iloc[1:].values, expect.values)


def test_zero_exposure_is_flat_without_cash_rate():
    core = _core()
    res = run_overlay(core, synth_leveraged(core, 0.0), pd.Series(0.0, index=core.index), costs=OverlayCosts(mult=0.0))
    assert np.allclose(res["equity"].values, 1.0)


def test_signal_executes_next_day():
    core = _core()
    tgt = pd.Series(0.0, index=core.index)
    tgt.iloc[100:] = 1.0
    res = run_overlay(core, synth_leveraged(core, 0.0), tgt, costs=OverlayCosts(mult=0.0))
    assert res["exposure"].iloc[100] == 0.0
    assert res["exposure"].iloc[101] > 0.9


def test_weights_mapping():
    assert weights_for(0.5) == (0.5, 0.0)
    assert weights_for(1.5) == (0.5, 0.5)
    assert weights_for(3.0) == (0.0, 1.0)


def test_synth_two_x_daily():
    core = _core()
    lev = synth_leveraged(core, 0.0, expense=0.0, spread=0.0)
    r = core["close"].pct_change().dropna()
    rl = lev["close"].pct_change().dropna()
    assert np.allclose(rl.values, 2 * r.values)
