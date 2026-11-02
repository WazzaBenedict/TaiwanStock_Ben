import numpy as np
import pandas as pd
import pytest

from tradeplan import PlanRules, make_plan, position_size, round_tick, simulate, summarize, tick_size
from tradeplan.rules import levels_at
from tradeplan.service import build_card


def frame(bars):
    """bars: list of (open, high, low, close)."""
    d = pd.bdate_range("2024-01-01", periods=len(bars))
    return pd.DataFrame({"日期": d, "開盤價": [b[0] for b in bars], "最高價": [b[1] for b in bars],
                         "最低價": [b[2] for b in bars], "收盤價": [b[3] for b in bars],
                         "成交股數": 1_000_000})


def flat(n, px=100.0, rng=1.0):
    return [(px, px + rng, px - rng, px)] * n


def setup_at(n, idx):
    s = pd.Series(False, index=range(n))
    s.iloc[idx] = True
    return s


def test_tick_ladder():
    assert tick_size(9.99) == 0.01 and tick_size(10) == 0.05 and tick_size(55) == 0.1
    assert tick_size(120) == 0.5 and tick_size(600) == 1 and tick_size(1200) == 5
    assert tick_size(60, etf=True) == 0.05
    assert round_tick(523.4417) == 523.0
    assert round_tick(50.03) == 50.0
    assert round_tick(49.97) == 49.95
    assert round_tick(101.26, direction="up") == 101.5


def test_levels_are_valid_ticks_and_2r():
    lv = levels_at(100.0, 99.0, 2.0)
    assert lv["entry"] == 99.0 and lv["stop"] == 95.0 and lv["target"] == 107.0
    assert lv["stop"] < lv["entry"] < lv["target"]
    for k in ("entry", "stop", "target"):
        assert abs(lv[k] / tick_size(lv[k]) - round(lv[k] / tick_size(lv[k]))) < 1e-6


def test_risk_cap_8pct():
    lv = levels_at(100.0, 100.0, 10.0)   # 2×ATR = 20% → 上限 8%
    assert lv["stop"] == 92.0


def test_entry_never_more_than_3pct_below_close():
    lv = levels_at(100.0, 90.0, 1.0)
    assert lv["entry"] == 97.0


def _base(n=30):
    return flat(n)   # ATR = 2, MA5 = 100 → entry 100? (min(close, max(ma5, 97))) = 100


def test_limit_fill_requires_trading_below_limit():
    bars = _base() + [(100.5, 101, 100.0, 100.5)] * 3 + flat(5)   # 最低價剛好碰到 100，不成交
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29))
    assert tr == []


def test_gap_down_through_stop_exits_at_open():
    bars = _base() + [(100.5, 101, 99.5, 100.5), (90, 91, 89, 90)] + flat(5, 90)
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29))
    assert len(tr) == 1 and tr[0]["reason"] == "停損" and tr[0]["exit"] == 90
    assert tr[0]["entry"] == 100.0


def test_stop_and_target_same_bar_assumes_stop():
    bars = _base() + [(100.5, 101, 99.5, 100.5), (100, 120, 80, 100)] + flat(5)
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29))
    assert tr[0]["reason"] == "停損" and tr[0]["exit"] == tr[0]["stop0"]


def test_time_exit_after_max_hold():
    bars = _base() + [(100.5, 101, 99.5, 100.5)] + flat(40, 100.5, 0.5)
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29), PlanRules(max_hold_days=20))
    assert tr[0]["reason"] == "時間出場" and tr[0]["days"] == 20
    assert tr[0]["ret"] < 0.006   # 幾乎沒漲，扣成本後接近或小於 0


def test_breakeven_then_trailing():
    up = [(100 + i, 101 + i, 99.5 + i, 100.5 + i) for i in range(1, 12)]
    bars = _base() + [(100.5, 101, 99.5, 100.5)] + up + [(111, 111.5, 103, 104)] + flat(5, 104)
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29), PlanRules(target_r=10))
    assert tr[0]["reason"] == "移動停利"
    assert 104 < tr[0]["exit"] < 111.5   # 以移動停損價出場，鎖住大部分獲利
    gap = _base() + [(100.5, 101, 99.5, 100.5)] + up + [(95, 95.5, 94, 94.5)] + flat(5, 94.5)
    tg = simulate(frame(gap), setup_at(len(gap), 29), PlanRules(target_r=10))
    assert tg[0]["exit"] == 95   # 跳空跌破移動停損 → 開盤價賣


def test_locked_limit_down_defers_exit():
    bars = _base() + [(100.5, 101, 99.5, 100.5), (90.5, 90.5, 90.5, 90.5), (88, 89, 87, 88)] + flat(5, 88)
    df = frame(bars)
    tr = simulate(df, setup_at(len(df), 29))
    assert tr[0]["exit_date"] == df["日期"].iloc[32].strftime("%Y-%m-%d") and tr[0]["exit"] == 88


def test_no_lookahead_levels_fixed_at_setup_day():
    a = _base() + [(100.5, 101, 99.5, 100.5)] + flat(25)
    b = _base() + [(100.5, 101, 99.5, 100.5)] + flat(25, 100, 5)   # 之後波動變大
    ta = simulate(frame(a), setup_at(len(a), 29))
    tb = simulate(frame(b), setup_at(len(b), 29))
    assert ta[0]["stop0"] == tb[0]["stop0"] and ta[0]["target"] == tb[0]["target"]


def test_costs_make_flat_round_trip_negative():
    bars = _base() + [(99, 101, 98, 100)] + flat(40, 99)
    tr = simulate(frame(bars), setup_at(len(bars), 29), PlanRules(max_hold_days=5))
    assert tr[0]["exit"] == tr[0]["entry"] and tr[0]["ret"] < -0.005


def test_position_size():
    p = position_size(1_000_000, 0.01, 100.0, 95.0)
    assert 1700 < p["shares"] < 2000 and p["lots"] == 1
    assert p["risk_amount"] <= 10_000
    small = position_size(30_000, 0.01, 100.0, 95.0)
    assert "min_fee_warning" in small


def test_make_plan_and_card_status():
    df = frame(_base(60))
    plan = make_plan(df)
    assert plan["entry"] == 100.0 and plan["as_of"] == df["日期"].iloc[-1].strftime("%Y-%m-%d")
    card = build_card("2330", df, pd.Series(False, index=df.index), capital=500_000)
    assert card["status"] == "NOT_TRIGGERED" and card["plan"]["position"]["shares"] > 0
    assert len(card["plan"]["sell_rules"]) == 4


def test_card_negative_ev_never_says_setup():
    rng = np.random.default_rng(1)
    bars, px = [], 100.0
    for _ in range(300):
        nxt = px * (1 + rng.normal(-0.002, 0.02))
        bars.append((px, max(px, nxt) * 1.01, min(px, nxt) * 0.99, nxt))
        px = nxt
    df = frame(bars)
    setup = pd.Series(np.arange(len(df)) % 7 == 0)
    setup.iloc[-1] = True
    card = build_card("2330", df, setup)
    assert card["history"]["n"] > 0
    if card["history"]["avg_ret_pct"] <= 0:
        assert card["status"] == "NEGATIVE_EV"
    assert card["random_control"]["runs"] > 0


def test_no_history_is_never_setup():
    df = frame(_base(60))
    setup = pd.Series(False, index=df.index)
    setup.iloc[-1] = True
    card = build_card("2330", df, setup)
    assert card["history"]["n"] == 0 and card["status"] == "UNVERIFIED"


def test_open_below_stop_cancels_order():
    bars = _base() + [(80, 81, 79, 80)] + flat(10, 80)
    tr = simulate(frame(bars), setup_at(len(bars), 29))
    assert tr == []


def test_bond_etf_has_no_tax():
    from tradeplan.costs import Costs, is_etf
    assert is_etf("00679B") == "bond" and is_etf("0050") is True and is_etf("2330") is False
    c = Costs()
    assert c.sell_rate("bond") < c.sell_rate(True) < c.sell_rate(False)


def test_ci_hidden_for_small_samples():
    trades = [{"ret": 0.01, "r_mult": 0.5, "days": 3, "reason": "目標", "entry_date": "2024-01-01",
               "exit_date": "2024-01-04"}] * 5
    assert summarize(trades)["avg_ret_ci95_pct"] is None


def test_nan_ohlc_filled_with_close():
    bars = _base() + [(100.5, 101, 99.5, 100.5), (float("nan"), float("nan"), float("nan"), 90)] + flat(5, 90)
    tr = simulate(frame(bars), setup_at(len(bars), 29))
    assert tr and tr[0]["reason"] == "停損"
