from datetime import date, timedelta

from pipeline import research as R


def bars(n, f, start=date(2022, 1, 3)):
    out, d = [], start
    for i in range(n):
        o, c = f(i)
        out.append({"d": d.isoformat(), "o": o, "h": max(o, c), "l": min(o, c), "c": c})
        d += timedelta(days=1)
    return out


def test_trade_net_uses_yuanta_costs_and_daytrade_tax():
    f = R.broker()
    r = R.trade_net(25.0, 25.0, "2409", True, f)           # 2 張 5 萬元：手續費 42+42，當沖稅 75
    assert abs(r - (-(42 + 42 + 75) / (50000 + 42))) < 1e-9
    assert R.trade_net(25.0, 25.0, "2409", False, f) < r   # 非當沖稅 0.3% 更貴


def test_flat_daytrade_fails_and_strong_edge_passes():
    bench = bars(1500, lambda i: (100.0, 100.0))
    today = bench[-1]["d"]
    flat = R.evaluate({"id": "x", "name": "x", "desc": "", "code": "2409", "kind": "當沖", "fn": R.rule_daytrade_long},
                      bars(1500, lambda i: (25.0, 25.0)), bench, today)
    assert flat["label"] == "未通過" and flat["oos"]["avg_net_pct"] < 0 and flat["is"]["n"] > 30
    good = R.evaluate({"id": "y", "name": "y", "desc": "", "code": "2409", "kind": "當沖", "fn": R.rule_daytrade_long},
                      bars(1500, lambda i: (25.0, 25.5 if i % 3 else 25.25)), bench, today)
    assert good["label"] == "可用" and good["oos"]["t"] >= 2


def test_small_sample_stays_in_research_and_live_segment_splits():
    bench = bars(1500, lambda i: (100.0, 100.0))
    b = bars(1500, lambda i: (50.0, 50.0 if i % 200 else 48.0))
    c = R.evaluate({"id": "d", "name": "d", "desc": "", "code": "2409", "kind": "波段", "fn": R.rule_dip_buy, "args": {"drop": 3.0}},
                   b, bench, bench[-1]["d"])
    assert c["label"] == "研究中" and c["oos"]["n"] < R.MIN_N
    late = bars(40, lambda i: (25.0, 25.0), start=date(2026, 11, 10))
    c2 = R.evaluate({"id": "x", "name": "x", "desc": "", "code": "2409", "kind": "當沖", "fn": R.rule_daytrade_long},
                    late, late, late[-1]["d"])
    assert c2["live"]["n"] == sum(1 for x in late if x["d"] >= R.LIVE_START) and c2["oos"]["n"] == 40 - c2["live"]["n"]


def test_label_thresholds_and_change_log(tmp_path, monkeypatch):
    assert R.label({"n": 100, "avg_excess_pct": 0.2}, {"n": 50, "avg_net_pct": 0.3, "avg_excess_pct": -0.1, "t": -1})[0] == "未通過"
    assert R.label({"n": 100, "avg_excess_pct": -0.2}, {"n": 50, "avg_net_pct": 0.3, "avg_excess_pct": 0.1, "t": 3})[0] == "研究中"
    monkeypatch.setattr(R, "LOG_FILE", tmp_path / "log.json")
    monkeypatch.setattr(R.cloudstore, "pull", lambda p: False)
    monkeypatch.setattr(R.cloudstore, "push", lambda p: False)
    R.track_changes([{"id": "a", "name": "A", "label": "研究中"}], "2026-11-16")
    log = R.track_changes([{"id": "a", "name": "A", "label": "未通過"}], "2026-11-17")
    assert log["runs"] == 2 and log["changes"] == [{"date": "2026-11-17", "id": "a", "name": "A", "from": "研究中", "to": "未通過"}]
