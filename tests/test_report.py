"""每日報告存檔與當沖 5 檔候選的純計算。"""
from datetime import datetime

from pipeline import picks as P
from pipeline import report as R
from twcosts import BrokerFees

SNAP = {"generated_at": "2026-11-16T06:52:00+08:00", "conclusion": "0050 持有",
        "gap_estimate": {"ok": True, "pct": -0.3, "note": "n"}, "risk": {"ok": True, "color": "yellow", "label": "黃燈"},
        "overnight": {"us": [{"symbol": "^SOX", "name": "費城半導體", "chg_pct": -3.4}], "night": {"pct": -0.3, "fresh": True}},
        "watchlist": [{"code": "0050", "date": "2026-11-13", "close": 102.5, "chg_pct": 1.5}],
        "news": [{"title": "t%d" % i, "link": "x"} for i in range(12)]}
PICKS = {"signal_date": "2026-11-13", "version": "R1", "universe_n": 80,
         "items": [{"code": "1102", "name": "亞泥", "mkt": "TW", "close": 35.75, "score": 4.25, "atr_pct": 2.36, "buy_b_max": 35.35}]}


def at(h, m, day=16):
    return datetime(2026, 11, day, h, m, tzinfo=R.TPE)


def test_phase_windows():
    assert R.phase(at(6, 50)) == "pre" and R.phase(at(10, 0)) is None and R.phase(at(13, 45)) == "close"
    assert R.phase(at(6, 50, day=15)) is None   # 週日


def test_pre_then_close_same_day_merges_and_is_idempotent():
    a = R.update({"days": []}, SNAP, at(6, 52), PICKS)
    a = R.update(a, SNAP, at(6, 58), {"items": [{"code": "9999"}]})   # 重跑不換掉已發布的候選
    assert len(a["days"]) == 1 and a["days"][0]["picks"]["items"][0]["code"] == "1102"
    assert len(a["days"][0]["pre"]["news"]) == 8 and a["days"][0]["pre"]["overnight"][-1]["name"] == "台指期夜盤"
    close = dict(SNAP, generated_at="2026-11-16T13:47:00+08:00", actual={"date": "2026-11-16", "gap_pct": -0.4, "close_chg_pct": 0.2})
    res = [P.score(PICKS["items"][0], {"o": 35.0, "h": 35.6, "l": 34.8, "c": 35.5})]
    a = R.update(a, close, at(13, 47), None, res)
    d = a["days"][0]
    assert d["close"]["gap_pct"] == -0.4 and d["results"][0]["b_taken"] is True
    assert a["picks_totals"]["a"]["n"] == 1 and a["picks_days"] == 1


def test_close_without_todays_bar_adds_nothing():
    a = R.update({"days": []}, dict(SNAP, actual={"date": "2026-11-13", "gap_pct": 1}), at(13, 47))
    assert a["days"] == []


def test_archive_is_capped():
    days = [{"date": "2026-%02d-%02d" % (m, d)} for m in (7, 8, 9) for d in range(1, 29)]
    assert len(R.update({"days": days}, SNAP, at(6, 52))["days"]) == R.MAX_DAYS


def test_score_uses_broker_costs_and_stop():
    f = BrokerFees()
    p = PICKS["items"][0]
    win = P.score(p, {"o": 35.0, "h": 35.6, "l": 34.8, "c": 35.5}, f)
    assert win["a_net"] == round(f.round_trip(35.0, 35.5, 1000, daytrade=True)["net_pnl"]) and win["a_net_tick1"] < win["a_net"]
    stopped = P.score(p, {"o": 36.0, "h": 36.0, "l": 34.0, "c": 35.9}, f)
    assert stopped["stop_hit"] and stopped["a_net"] < -1000 and stopped["b_taken"] is False and stopped["b_net"] == 0


def test_rank_filters_and_orders():
    base = {"date": "2026-11-13", "mkt": "TW", "val20": 3e8, "close": 30.0, "atr": 0.02, "on20": 0.0, "max20": 0.03, "h52": 0.9, "r5": 0.0}
    rows = [dict(base, code="A", name="a", on20=-0.05, h52=0.99), dict(base, code="B", name="b", on20=0.05, h52=0.7),
            dict(base, code="C", name="c", close=80.0), dict(base, code="D", name="d", val20=1e8), dict(base, code="E", name="e", date="2026-11-12")]
    top, n = P.rank(rows)
    assert n == 2 and [x["code"] for x in top] == ["A", "B"] and top[0]["buy_b_max"] == 29.7


def test_features_need_260_bars():
    bars = [{"d": "d%d" % i, "o": 30.0, "h": 30.5, "l": 29.5, "c": 30.0, "v": 1e7} for i in range(260)]
    assert P.features(bars[:259]) is None
    f = P.features(bars)
    assert abs(f["atr"] - 1 / 30) < 1e-9 and f["h52"] == 1 and f["val20"] == 3e8


def test_plan_levels_ticks():
    from pipeline.picks import plan_levels
    p = plan_levels(35.75, 0.0236)
    assert p["entry_limit"] == 35.35 and p["stop_est"] == 34.25 and p["ref_target"] == 36.2
    assert plan_levels(26.0, 0.0249)["ref_target"] == 26.35


def test_backtest_target_and_stop():
    from pipeline import picks as P
    def bar(d, o, h, l, c): return {"d": d, "o": o, "h": h, "l": l, "c": c, "v": 1}
    bars = [bar(f"2023-05-{i:02d}", 30, 30.6, 29.4, 30) for i in range(1, 17)]
    bars += [bar("2023-06-01", 29.5, 31.0, 29.4, 29.6),   # 開低 → B；碰到目標（約 29.5×1.04）就賣
             bar("2023-06-02", 29.0, 29.2, 28.0, 28.9),   # 開低，跌破停損
             bar("2023-06-03", 29.0, 30.6, 28.0, 30.0)]   # 同一天兩邊都碰到 → 算停損
    r = P.backtest(bars)
    assert r["A_close"]["n"] == 3 and r["B_close"]["n"] == 2  # 第 3 天開盤沒有比昨收低 1%
    assert r["B_target"]["avg"] > r["B_close"]["avg"] - 5
    stop_day = P.bt_trade(29.0, 30.6, 28.0, 30.0, 30.2, P.BrokerFees())
    assert stop_day < 0


def test_next_picks_flow():
    from datetime import datetime
    from pipeline import report as R
    tpe = R.TPE
    assert R.target_day(datetime(2026, 11, 20, 22, 0, tzinfo=tpe)) == "2026-11-23"   # 週五晚上 → 下週一
    assert R.target_day(datetime(2026, 11, 23, 3, 0, tzinfo=tpe)) == "2026-11-23"    # 週一清晨 → 當天
    assert R.target_day(datetime(2026, 11, 23, 11, 0, tzinfo=tpe)) == "2026-11-24"   # 盤中 → 明天
    arch = {"days": [{"date": "2026-11-20", "results": [{"code": "1"}]}],
            "next_picks": {"for_date": "2026-11-23", "version": "R1", "items": [{"code": "1102"}]}}
    assert R.place_next_picks(arch, "2026-11-21") is arch                              # 還沒到，不動
    out = R.place_next_picks(arch, "2026-11-23")
    assert "next_picks" not in out and out["days"][0]["date"] == "2026-11-23"
    assert out["days"][0]["picks"]["items"][0]["code"] == "1102" and "for_date" not in out["days"][0]["picks"]
    keep = R.all_results({"results_all": {"2026-01-01": [{"code": "x"}]}, "days": arch["days"]})
    assert set(keep) == {"2026-01-01", "2026-11-20"}


def test_rank_uses_common_date():
    from pipeline import picks as P
    base = {"val20": 3e8, "close": 30.0, "atr": 0.02, "on20": 0, "max20": 0.01, "h52": 0.9, "r5": 0}
    rows = [dict(base, code=str(1000 + i), name="x", mkt="TW", date="2026-11-20", on20=i / 100) for i in range(20)]
    rows += [dict(base, code=str(2000 + i), name="y", mkt="TW", date="2026-11-21") for i in range(3)]
    items, n = P.rank(rows)
    assert n == 20 and len(items) == 5
