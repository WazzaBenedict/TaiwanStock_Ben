import numpy as np
import pandas as pd
import pytest

from quant.costs import TaiwanCosts
from quant.engine import BacktestConfig, FactorCache, run_backtest, select_picks
from quant.factors import revenue_yoy, momentum_12_1, low_volatility

ALL_W = {"momentum_12_1": 1.0, "low_vol": 0.5, "revenue_yoy": 0.5}


def make_panel(n_stocks=30, n_days=600, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n_days)
    cols = [f"{1000 + i}" for i in range(n_stocks)]
    rets = rng.normal(0.0003, 0.02, size=(n_days, n_stocks))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
    open_ = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.003, size=close.shape))
    value = pd.DataFrame(rng.uniform(5e7, 5e8, size=close.shape), index=idx, columns=cols)
    months = pd.date_range("2016-01-01", idx[-1], freq="MS")
    revenue = pd.DataFrame(rng.uniform(1e6, 2e6, size=(len(months), n_stocks)), index=months, columns=cols)
    bench = close.mean(axis=1)
    return {"close": close, "open": open_, "volume_value": value, "revenue": revenue,
            "benchmark_close": bench, "benchmark_open": bench}


def shocked(panel, after, factor=5.0):
    p = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in panel.items()}
    for key in ("close", "open"):
        df = p[key]
        mask = df.index > after
        df.loc[mask, df.columns[::2]] *= factor
    rev = p["revenue"]
    rev.loc[rev.index > after - pd.DateOffset(months=1), :] *= factor
    return p


# ── 不偷看未來 ────────────────────────────────────────────────────────────────
def test_future_price_shock_does_not_change_todays_picks():
    panel = make_panel()
    as_of = panel["close"].index[400]
    cfg = BacktestConfig(weights=ALL_W, top_n=5, min_avg_value=0)
    before = select_picks(panel, as_of, cfg)
    after = select_picks(shocked(panel, as_of), as_of, cfg)
    assert len(before) == 5
    pd.testing.assert_series_equal(before, after)


def test_factors_ignore_future_rows():
    panel = make_panel()
    as_of = panel["close"].index[350]
    p2 = shocked(panel, as_of)
    for f in (momentum_12_1, low_volatility):
        pd.testing.assert_series_equal(f(panel, as_of), f(p2, as_of))


def test_engine_equity_unchanged_before_shock():
    panel = make_panel()
    cal = panel["close"].index
    cfg = BacktestConfig(weights=ALL_W, top_n=5, min_avg_value=0, start=str(cal[300].date()))
    shock_day = cal[450]
    a = run_backtest(panel, cfg)["equity"]
    b = run_backtest(shocked(panel, shock_day), cfg)["equity"]
    pd.testing.assert_series_equal(a.loc[:shock_day], b.loc[:shock_day])
    assert not a.loc[shock_day:].equals(b.loc[shock_day:])


def test_trades_at_next_day_open():
    panel = make_panel()
    cal = panel["close"].index
    cfg = BacktestConfig(weights=ALL_W, top_n=5, min_avg_value=0, start=str(cal[300].date()))
    res = run_backtest(panel, cfg)
    for r in res["rebalances"]:
        assert cal.get_loc(r["trade_date"]) == cal.get_loc(r["signal_date"]) + 1


# ── 成本 ─────────────────────────────────────────────────────────────────────
def test_cost_rates():
    c = TaiwanCosts()
    assert c.buy_rate == pytest.approx(0.001425 + 0.001)
    assert c.sell_rate(False) == pytest.approx(0.001425 + 0.003 + 0.001)
    assert c.sell_rate(True) == pytest.approx(0.001425 + 0.001 + 0.001)
    assert c.round_trip(False) == pytest.approx(0.00785)
    assert TaiwanCosts(fee_discount=0.6).buy_rate == pytest.approx(0.001425 * 0.6 + 0.001)


def flat_panel(n_days=320, delist_at=None):
    idx = pd.bdate_range("2019-01-01", periods=n_days)
    close = pd.DataFrame({"1101": 100.0, "1102": 100.0}, index=idx)
    # 讓 1101 動能較高但最後一個月持平
    close.iloc[:200, 0] = np.linspace(50, 100, 200)
    if delist_at is not None:
        close.iloc[delist_at:, 0] = np.nan
    open_ = close.copy()
    value = pd.DataFrame(1e9, index=idx, columns=close.columns)
    bench = pd.Series(100.0, index=idx)
    return {"close": close, "open": open_, "volume_value": value,
            "benchmark_close": bench, "benchmark_open": bench}


def test_engine_charges_buy_cost_once_when_prices_flat():
    panel = flat_panel()
    cal = panel["close"].index
    start = cal[280]
    cfg = BacktestConfig(weights={"momentum_12_1": 1.0}, top_n=1, min_avg_value=0, start=str(start.date()))
    res = run_backtest(panel, cfg)
    # 同一檔一直入選：只付一次買進成本，之後月份不再換股
    assert res["equity"].iloc[-1] == pytest.approx(1 - cfg.costs.buy_rate)
    assert all(r["picks"] == ["1101"] for r in res["rebalances"])


def test_delisted_stock_exits_at_last_price_with_sell_cost():
    panel = flat_panel(n_days=320, delist_at=300)
    cal = panel["close"].index
    cfg = BacktestConfig(weights={"momentum_12_1": 1.0}, top_n=1, min_avg_value=0,
                         start=str(cal[280].date()), end=str(cal[310].date()))
    res = run_backtest(panel, cfg)
    c = cfg.costs
    first = res["rebalances"][0]
    assert first["picks"] == ["1101"]
    K = cfg.capital
    buy = c.order_cost(K, "buy", 0.001) / K           # 成交金額 10 億 → 滑價 0.1%
    sell = c.order_cost(K * (1 - buy), "sell", 0.005) / (K * (1 - buy))   # 下市強制出場用 0.5% 滑價
    assert res["equity"].loc[cal[300]] == pytest.approx((1 - buy) * (1 - sell))


# ── 營收公告延遲 ──────────────────────────────────────────────────────────────
def test_revenue_only_usable_from_11th_of_next_month():
    months = pd.date_range("2022-01-01", "2024-01-01", freq="MS")
    rev = pd.DataFrame({"1101": 100.0}, index=months)
    rev.loc["2024-01-01", "1101"] = 1000.0      # 2024 年 1 月營收暴增，2/11 才公告
    panel = {"revenue": rev}
    on_10th = revenue_yoy(panel, pd.Timestamp("2024-02-10"), months=1)
    on_11th = revenue_yoy(panel, pd.Timestamp("2024-02-11"), months=1)
    assert on_10th["1101"] == pytest.approx(0.0)       # 只看到 2023/12 對 2022/12
    assert on_11th["1101"] == pytest.approx(9.0)       # 1000 / 100 - 1


# ── 舊 App 回測修正 ───────────────────────────────────────────────────────────
def _price_df(prices, opens=None):
    idx = pd.bdate_range("2023-01-02", periods=len(prices))
    opens = prices if opens is None else opens
    return pd.DataFrame({"日期": idx, "開盤價": opens, "最高價": prices, "最低價": prices,
                         "收盤價": prices, "成交股數": 1_000_000})


def test_app_winrate_deducts_costs_and_does_not_overlap():
    import app
    zig = np.array([0.6 if i % 2 else -0.6 for i in range(200)])
    prices = list(np.linspace(50, 100, 200) + zig)
    wr = app._calc_winrate(app.compute_all_indicators(_price_df(prices)))
    rt = TaiwanCosts().round_trip(False)
    assert wr["trials"] > 0
    # 不重疊：交易次數不可能超過 天數 / (持有天數+1)
    assert wr["trials"] <= len(prices) // 6
    assert wr["avg_net_return_pct"] < wr["avg_gross_return_pct"]
    assert wr["avg_gross_return_pct"] - wr["avg_net_return_pct"] == pytest.approx(rt * 100, abs=0.1)


def test_app_advanced_backtest_flat_prices_lose_costs():
    import app
    # 價格 100/101 交錯；持有 5 天時進出場價相同 → 毛報酬 0，只剩成本
    prices = [100.0 + (i % 2) for i in range(200)]
    res = app.advanced_backtest(_price_df(prices), holding_days=5, min_score=0)
    rt = TaiwanCosts().round_trip(False)
    assert res["total_trades"] > 0
    assert res["wins"] == 0
    c = TaiwanCosts()
    expected = ((1 - c.sell_rate(False)) / (1 + c.buy_rate) - 1) * 100
    for t in res["trades"]:
        assert t["return_pct"] == pytest.approx(expected, abs=0.01)
        assert t["gross_return_pct"] == 0
    # 不重疊：下一筆的訊號日不早於上一筆的出場日
    tr = sorted(res["trades"], key=lambda t: t["date"])
    assert all(b["date"] >= a["exit_date"] for a, b in zip(tr, tr[1:]))
    assert "benchmark" in res and "buy_hold_return_pct" in res["benchmark"]


def test_clean_price_breaks_removes_spike_but_keeps_normal_moves():
    from quant.data import clean_price_breaks
    idx = pd.bdate_range("2024-01-01", periods=6)
    close = pd.DataFrame({"1101": [10, 11, 1100, 11, 12.1, 12.1]}, index=idx, dtype=float)
    new_close, new_open, n = clean_price_breaks(close, close.copy())
    assert n == 2
    r = new_close["1101"].pct_change().dropna().round(6).tolist()
    assert r == [0.1, 0.0, 0.0, 0.1, 0.0]


def test_trade_plan_uses_nearest_stop_and_target():
    import app
    row = pd.Series({"MA5": 100.0, "MA20": 95.0, "ATR": 4.0})
    plan = app.build_trade_plan(row, 100.0, "BUY", None)
    ep = plan["entry_price"]
    # 候選停損：97、93.575、94；最近且合理的是 97（舊版取最寬的 93.575）
    assert plan["stop_loss"] == pytest.approx(ep * 0.97)
    # 候選目標：105、110；取最近的 105（舊版取 110）
    assert plan["target_price"] == pytest.approx(ep * 1.05)


def test_confidence_has_no_in_sample_winrate_bonus():
    import app
    df = app.compute_all_indicators(_price_df(list(np.linspace(50, 100, 120) + np.tile([0.6, -0.6], 60))))
    row = df.iloc[-1]
    a = app.build_tw_ai_signal(row, float(row["收盤價"]), {"winrate": 90}, {}, 0, 1.0, df)
    b = app.build_tw_ai_signal(row, float(row["收盤價"]), {"winrate": 0}, {}, 0, 1.0, df)
    assert a["confidence"] == b["confidence"]


def test_trade_journal_pnl_net_of_fees_and_tax():
    import app
    r = app._calc_trade_result({"market": "tw", "stock_id": "2330", "entry_price": 100, "exit_price": 110, "shares": 1000})
    fees = 100_000 * 0.001425 + 110_000 * 0.001425 + 110_000 * 0.003
    assert r["pnl_gross"] == 10_000
    assert r["pnl"] == pytest.approx(10_000 - fees, abs=0.01)
    small = app._calc_trade_result({"market": "tw", "stock_id": "2330", "entry_price": 10, "exit_price": 10, "shares": 1})
    assert small["fees_and_tax"] == pytest.approx(20 + 20 + 0.03)   # 每筆最低手續費 20 元


def test_write_failure_is_reported(tmp_path):
    import app
    assert app._wjf(tmp_path / "ok.json", {"a": 1}) is True
    assert app._wjf(tmp_path / "missing_dir" / "x.json", {"a": 1}) is False


# ── 審查意見補強 ──────────────────────────────────────────────────────────────
def test_min_fee_and_tiered_slippage():
    from quant.costs import tiered_slippage
    c = TaiwanCosts()
    assert c.fee(1000) == 20                       # 1000 × 0.1425% = 1.4 元 → 最低 20 元
    assert c.fee(1_000_000) == pytest.approx(1425)
    assert c.order_cost(1_000_000, "sell", 0.002) == pytest.approx(1425 + 1_000_000 * (0.002 + 0.003))
    assert tiered_slippage(2e9) == 0.001 and tiered_slippage(2e8) == 0.003 and tiered_slippage(6e7) == 0.005


def test_small_capital_pays_relatively_more_fees():
    panel = flat_panel()
    cal = panel["close"].index
    kw = dict(weights={"momentum_12_1": 1.0}, top_n=1, min_avg_value=0, start=str(cal[280].date()))
    big = run_backtest(panel, BacktestConfig(capital=1e7, **kw))["equity"].iloc[-1]
    small = run_backtest(panel, BacktestConfig(capital=5_000, **kw))["equity"].iloc[-1]
    assert small < big


def test_stale_price_gets_no_momentum_score():
    panel = make_panel()
    as_of = panel["close"].index[400]
    panel["close"].loc[panel["close"].index[395]:, "1000"] = np.nan    # 停牌／下市 5 天
    assert pd.isna(momentum_12_1(panel, as_of).get("1000"))
    assert pd.isna(low_volatility(panel, as_of).get("1000"))


def test_revenue_yoy_aligns_by_month_label_when_a_month_is_missing():
    months = pd.date_range("2022-01-01", "2023-12-01", freq="MS")
    rev = pd.DataFrame({"1101": 100.0, "1102": 100.0}, index=months)
    rev.loc["2023-12-01", ["1101", "1102"]] = 200.0
    rev = rev.drop(pd.Timestamp("2023-05-01"))           # 全市場缺一個月的檔案
    out = revenue_yoy({"revenue": rev}, pd.Timestamp("2024-01-15"), months=1)
    assert out["1101"] == pytest.approx(1.0)              # 2023/12 對 2022/12，不是對 2023/01
    rev.loc[pd.Timestamp("2022-12-01"), "1102"] = np.nan    # 去年同月缺值 → 不給分
    out2 = revenue_yoy({"revenue": rev}, pd.Timestamp("2024-01-15"), months=1)
    assert pd.isna(out2["1102"])


def test_revenue_yoy_ignores_stale_filers():
    months = pd.date_range("2022-01-01", "2023-12-01", freq="MS")
    rev = pd.DataFrame({"1101": 100.0, "1102": 100.0}, index=months)
    rev.loc["2023-06-01":, "1102"] = np.nan               # 1102 半年沒申報
    out = revenue_yoy({"revenue": rev}, pd.Timestamp("2024-01-15"), months=1)
    assert pd.notna(out["1101"]) and pd.isna(out.get("1102"))


def test_institutional_flow_requires_data_through_as_of():
    from quant.factors import institutional_flow
    panel = make_panel()
    cal = panel["close"].index
    inst = panel["volume_value"] * 0.01
    inst.loc[cal[380]:, "1001"] = np.nan                   # 1001 的法人資料在 as_of 前就斷了
    inst = inst.drop(index=cal[390])                       # 另有一天整天缺檔（日期需對齊）
    panel["inst_net"] = inst
    out = institutional_flow(panel, cal[400])
    assert out["1000"] == pytest.approx(0.01)
    assert pd.isna(out["1001"])


def test_empty_factor_is_skipped_not_emptying_candidates():
    from quant.factors import composite_score
    panel = make_panel()
    as_of = panel["close"].index[400]
    info = {}
    score = composite_score(panel, as_of, {"momentum_12_1": 1.0, "inst_flow": 1.0},
                            universe=panel["close"].columns, info=info)
    assert len(score) == 30
    assert info["factors_skipped"] == ["inst_flow"] and info["factors_used"] == ["momentum_12_1"]


def test_rank_normalize_is_bounded_and_ordered():
    from quant.factors import rank_normalize
    r = rank_normalize(pd.Series([1.0, 1000.0, 2.0, np.nan]))
    assert r.max() < 0.5 and r.min() > -0.5
    assert r.idxmax() == 1 and len(r) == 3
