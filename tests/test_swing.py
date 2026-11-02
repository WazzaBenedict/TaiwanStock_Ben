import numpy as np
import pandas as pd

from quant.swing import Context, SwingConfig, blend_with_core, run_swing, systems
from tests.synth import synth_panel


def test_no_signal_tracks_0050():
    p = synth_panel(50)
    ctx = Context(p)
    r = run_swing(ctx, SwingConfig(name="x", score_fn=lambda c, d: pd.Series(dtype=float), start="2013-01-02"))
    eq = r["equity"]
    b = p["benchmark_close"].loc[eq.index]
    first = p["benchmark_open"].loc[eq.index[0]]
    expect = b / first * (1 - (0.001425 + 0.0005))
    assert np.allclose(eq.values, expect.values, rtol=1e-9)


def test_trades_execute_next_open_and_respect_slots():
    ctx = Context(synth_panel(80))
    r = run_swing(ctx, SwingConfig(name="S1", start="2013-01-02", **systems()["S1"]))
    tr = r["trades"]
    assert len(tr) > 0
    assert (tr["exit_day"] > tr["entry_day"]).all()
    # 同時持股不超過 N
    days = pd.date_range(tr["entry_day"].min(), tr["exit_day"].max(), freq="B")
    held = [((tr["entry_day"] <= d) & (tr["exit_day"] > d)).sum() for d in days[::20]]
    assert max(held) <= 10


def test_delisted_stock_is_closed_out():
    p = synth_panel(30)
    ctx = Context(p)
    sid = p["close"].columns[0]
    first_ok = p["close"].index[300]
    score = lambda c, d: pd.Series({sid: 1.0}) if d >= first_ok else pd.Series(dtype=float)
    r = run_swing(ctx, SwingConfig(name="x", score_fn=score, stop_atr=None, trail_atr=None, regime=False,
                                   start="2013-01-02"))
    tr = r["trades"]
    assert (tr["reason"] == "delist").any()


def test_blend_weights():
    idx = pd.bdate_range("2020-01-01", periods=60)
    a = pd.Series(np.linspace(1, 2, 60), index=idx)
    out = blend_with_core(a, a, 0.6)
    assert np.isclose(out.iloc[-1], 2.0, rtol=0.01)
