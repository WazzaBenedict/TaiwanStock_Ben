from datetime import datetime

from pipeline import snapshot as S


def test_pct_sma_vol():
    assert S.pct(110, 100) == 10.0
    assert S.pct(None, 100) is None and S.pct(1, 0) is None
    assert S.sma([1, 2, 3, 4], 2) == 3.5 and S.sma([1], 2) is None
    assert S.realized_vol([100.0] * 30) == 0.0
    assert S.realized_vol([100.0] * 5) is None


def test_gap_model_recovers_slope():
    xs = [(-1) ** i * (1 + i % 5) for i in range(120)]
    ys = [0.1 + 0.4 * x for x in xs]
    m = S.fit_gap_model(xs, ys)
    assert abs(m["b"] - 0.4) < 1e-6 and abs(m["a"] - 0.1) < 1e-6 and m["corr"] == 1.0 and m["n"] == 120
    assert S.fit_gap_model(xs[:10], ys[:10]) is None


def test_estimate_prefers_night_session_and_flags_conflict():
    model = {"a": 0.0, "b": 0.4, "corr": 0.7, "n": 400}
    g = S.estimate_gap(1.27, -0.54, model)          # 2026-11-13：費半跌、夜盤漲，實際開高
    assert g["basis"] == "night" and g["pct"] == 1.27 and "以夜盤為準" in g["note"]
    g = S.estimate_gap(None, -3.0, model)
    assert g["basis"] == "sox" and g["pct"] == -1.2
    assert S.estimate_gap(None, None, model)["ok"] is False
    assert S.estimate_gap(None, -1.0, None)["ok"] is False


def test_stale_night_session_is_ignored():
    night = {"date": "2026-11-13", "pct": 1.27}
    assert S.fresh_night(night, "2026-11-13") is None       # 已經開過盤的那一晚
    assert S.fresh_night(night, "2026-11-12") == night
    assert S.fresh_night(None, "2026-11-12") is None


def test_risk_light():
    assert S.risk_light(90, 100, 15)["color"] == "red"
    assert S.risk_light(110, 100, 40)["color"] == "yellow"
    g = S.risk_light(110, 100, 15)
    assert g["color"] == "green" and g["dist_ma200_pct"] == 10.0
    assert S.risk_light(None, None, None)["ok"] is False


def test_conclusion_defaults_to_no_daytrade():
    c = S.conclusion({"ok": True, "pct": -1.24}, {"ok": True, "label": "黃燈"})
    assert c.startswith("0050 持有，當沖今天不做") and "開低" in c and "黃燈" in c
    assert S.conclusion({"ok": False}, {"ok": False}) == "0050 持有，當沖今天不做。"


def test_gap_pairs_uses_us_close_between_tw_sessions():
    sox = [{"d": "2026-11-09", "c": 100}, {"d": "2026-11-10", "c": 102}, {"d": "2026-11-11", "c": 101},
           {"d": "2026-11-13", "c": 99}]
    tw = [{"d": "2026-11-10", "o": 50, "c": 50}, {"d": "2026-11-11", "o": 51, "c": 51},
          {"d": "2026-11-12", "o": 50.49, "c": 50}, {"d": "2026-11-13", "o": 50.5, "c": 50}]
    xs, ys = S.gap_pairs(sox, tw)
    # 11/11 開盤對 11/10 美股收盤；11/12 對 11/11；11/13 沒有 11/12 的美股收盤 → 略過
    assert [round(x, 2) for x in xs] == [2.0, -0.98]
    assert [round(y, 2) for y in ys] == [2.0, -1.0]


def test_phase_and_schema(monkeypatch):
    monkeypatch.setattr(S, "yahoo_daily", lambda cl, sym, rng="2y": [{"d": f"2026-01-{i:02d}", "o": 100 + i, "h": 0, "l": 0, "c": 100 + i} for i in range(1, 29)])
    monkeypatch.setattr(S, "night_session", lambda cl, today: None)
    monkeypatch.setattr(S, "monthly_revenue", lambda cl, codes: {"2409": {"ym": "11510", "yoy_pct": -0.7}})
    monkeypatch.setattr(S, "disposition", lambda cl: ["2409"])
    monkeypatch.setattr(S, "news", lambda cl, now: (_ for _ in ()).throw(RuntimeError("rss down")))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    snap = S.build(datetime(2026, 11, 16, 6, 50, tzinfo=S.TPE), watch=["0050", "2409"])
    assert snap["phase"] == "premarket" and len(snap["watchlist"]) == 2
    row = snap["watchlist"][1]
    assert row["disposition"] is True and row["rev_yoy_pct"] == -0.7
    assert snap["news"] == [] and "news" in snap["errors"]          # 一個來源失敗不影響其他區塊
    assert snap["conclusion"].startswith("0050 持有")


def test_hit_log_records_prediction_then_actual():
    from pipeline import history as Hh
    pre = {"generated_at": "2026-11-16T06:50:00+08:00", "phase": "premarket",
           "gap_estimate": {"ok": True, "pct": -1.2, "basis": "sox"},
           "overnight": {"us": [{"symbol": "^SOX", "chg_pct": -3.4}]}}
    log = Hh.update([], pre)
    assert log == [{"date": "2026-11-16", "pred_pct": -1.2, "basis": "sox", "sox_pct": -3.4, "actual_pct": None}]
    assert Hh.summarize(log)["n"] == 0
    close = {"generated_at": "2026-11-16T13:45:00+08:00", "phase": "close", "gap_estimate": {"ok": True, "pct": 9.9},
             "actual": {"date": "2026-11-16", "gap_pct": -0.8}}
    log = Hh.update(log, close)
    assert log[0]["actual_pct"] == -0.8 and log[0]["pred_pct"] == -1.2      # 收盤那次不能覆蓋盤前預估
    s = Hh.summarize(log)
    assert s["n"] == 1 and s["hits"] == 1 and s["baseline_hits"] == 1 and s["mean_abs_error_pct"] == 0.4


def test_hit_log_counts_misses_and_baseline_separately():
    from pipeline import history as Hh
    log = [{"date": "d1", "pred_pct": 1.3, "sox_pct": -0.5, "actual_pct": 1.9},     # 預估中、基準錯
           {"date": "d2", "pred_pct": -0.5, "sox_pct": 0.4, "actual_pct": 1.3},     # 預估錯、基準中
           {"date": "d3", "pred_pct": 0.5, "sox_pct": 0.4, "actual_pct": None}]     # 尚未有結果
    s = Hh.summarize(log)
    assert (s["n"], s["hits"], s["baseline_hits"], s["hit_rate_pct"]) == (2, 1, 1, 50)
