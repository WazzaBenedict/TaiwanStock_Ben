"""Run: python -m pytest -q tests/test_daytrade.py"""
import datetime as dt
import random

from daytrade.costs import DayTradeCosts, round_to_tick, tick_size
from daytrade.data import SESSION_BARS, bar_time, fill_quiet_bars, minute_rows_to_bars, parse_hhmm
from daytrade import timemachine as tm


def synth_sessions(n=40, seed=1, drift=0.0, start=100.0):
    rng = random.Random(seed)
    out, d, price = {}, dt.date(2026, 6, 1), start
    while len(out) < n:
        if d.weekday() < 5:
            bars = []
            for _ in range(SESSION_BARS):
                o = price
                c = max(1.0, o * (1 + rng.gauss(drift, 0.003)))
                h = max(o, c) * (1 + abs(rng.gauss(0, 0.0015)))
                l = min(o, c) * (1 - abs(rng.gauss(0, 0.0015)))
                bars.append([o, h, l, c, 1000.0])
                price = c
            out[d.isoformat()] = bars
        d += dt.timedelta(days=1)
    return out


def test_tick_table():
    assert tick_size(9.99) == 0.01 and tick_size(10) == 0.05 and tick_size(99.9) == 0.1
    assert tick_size(500) == 1.0 and tick_size(1000) == 5.0
    assert round_to_tick(101.3, "down") == 101.0 and round_to_tick(101.3, "up") == 101.5
    assert round_to_tick(50.0, "up") == 50.0


def test_costs_round_trip():
    c = DayTradeCosts(fee_discount=0.6, slip_ticks=1)
    # 1 lot at 100 flat: two fees of max(20, 100000*0.001425*0.6=85.5) + tax 150
    assert abs(c.net_pnl(100, 100, 1000) - (-(85.5 * 2 + 150))) < 1e-6
    # min fee applies to small orders
    assert abs(c.fee(1000) - 20) < 1e-9
    assert c.slip(100, "buy") == 100.5 and c.slip(100, "sell") == 99.9
    assert c.slip(50, "sell") == 49.95


def test_minute_aggregation_end_labels_and_auction():
    rows = []
    for m in range(1, 266):  # 09:01 .. 13:25 end-labelled
        t = 9 * 60 + m
        rows.append({"minute": "%02d:%02d:00" % (t // 60, t % 60), "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1})
    rows.append({"minute": "13:30:00", "open": 12, "high": 12, "low": 12, "close": 12, "volume": 5})
    bars = minute_rows_to_bars(rows)
    assert len(bars) == SESSION_BARS and all(b is not None for b in bars)
    assert bars[0][4] == 5 and bars[-1][3] == 12
    assert bar_time(parse_hhmm("10:15")) == "10:15"


def test_parse_yahoo_chart():
    from daytrade.data import parse_yahoo_chart
    base = int(dt.datetime(2026, 10, 30, 1, 0, tzinfo=dt.timezone.utc).timestamp())  # 09:00 Taipei
    ts = [base + 300 * i for i in range(SESSION_BARS)] + [base + 300 * SESSION_BARS]  # + 13:30 auction stamp
    n = len(ts)
    q = {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n, "close": [100.0] * (n - 1) + [102.0], "volume": [1] * n}
    q["close"][5] = None  # one missing bar gets filled
    payload = {"chart": {"result": [{"meta": {"gmtoffset": 28800}, "timestamp": ts, "indicators": {"quote": [q]}}]}}
    out = parse_yahoo_chart(payload)
    assert list(out) == ["2026-10-30"]
    bars = out["2026-10-30"]
    assert len(bars) == SESSION_BARS and bars[-1][3] == 102.0 and bars[5][4] == 0.0
    assert parse_yahoo_chart(payload, end_date="2026-10-29") == {}


def test_apply_daily_close():
    from daytrade.data import apply_daily_close
    bars = [[100.0, 100.0, 100.0, 100.0, 1.0]] * (SESSION_BARS - 1) + [[100.0, 100.0, 100.0, 100.0, 0.0]]
    s = {"2026-10-30": [list(b) for b in bars]}
    apply_daily_close(s, {"2026-10-30": 102.0})
    assert s["2026-10-30"][-1] == [100.0, 102.0, 100.0, 102.0, 0.0]


def test_fill_quiet_bars():
    b = [[1, 1, 1, 1, 1]] + [None] * 2 + [[2, 2, 2, 2, 1]] * (SESSION_BARS - 3)
    assert fill_quiet_bars(b)[1] == [1, 1, 1, 1, 0.0]
    assert fill_quiet_bars([None] + b[1:]) is None


def test_walk_stop_first_and_gap():
    c = DayTradeCosts(slip_ticks=0)
    # bar touches both: counts as stop
    assert tm.walk(100, 99, 101, [(100, 102, 98, 100)], c)[0] == "stop"
    # gap below stop fills at the open
    out = tm.walk(100, 99, 101, [(97, 98, 96, 97)], c)
    assert out[0] == "stop" and out[1] == 97


def test_run_is_reproducible_and_costs_hurt():
    s = synth_sessions(45)
    last = list(s)[-1]
    kw = dict(entry=s[last][6][0], entry_time="09:30", replays=2000, sessions=s)
    e = kw["entry"]
    kw.update(stop=round(e * 0.99, 2), target=round(e * 1.01, 2))
    a = tm.run("TEST", last, **kw)
    b = tm.run("TEST", last, **kw)
    assert a["mc"] == b["mc"]
    assert abs(a["mc"]["target_first"] + a["mc"]["stop_first"] + a["mc"]["neither"] - 100) < 0.2
    free = tm.run("TEST", last, costs=DayTradeCosts(fee_discount=0, min_fee=0, tax_rate=0, slip_ticks=0), **kw)
    # a zero-drift random walk is roughly break-even before costs and clearly negative after
    assert free["mc"]["avg_net_r"] > a["mc"]["avg_net_r"]
    assert a["mc"]["avg_net_r"] < 0
    assert a["verdict"] and "不是預測" in a["disclaimer"]


def test_orb_plan_and_history():
    s = synth_sessions(45, seed=3, drift=0.0004)
    days = list(s)
    for d in reversed(days):
        try:
            res = tm.run("TEST", d, replays=500, sessions={k: v for k, v in s.items() if k <= d})
            break
        except tm.TMError:
            continue
    p = res["plan"]
    assert p["source"] == "orb" and p["stop"] < p["entry"] < p["target"]
    assert res["history"]["sessions"] >= 20
    assert "trades" in res["history"]


def test_refuses_short_pool():
    s = synth_sessions(10)
    last = list(s)[-1]
    try:
        tm.run("TEST", last, entry=100, stop=99, target=101, entry_time="09:30", sessions=s)
        assert False
    except tm.TMError as e:
        assert "need at least" in str(e)


def test_screener_evaluate_and_codes():
    from daytrade import screener
    s = synth_sessions(45, seed=11)
    ev = screener.evaluate("TEST", s, tm.Rule(), DayTradeCosts())
    assert ev["sessions"] == 45 and ev["random"]["n"] == 45 * screener.RANDOM_DRAWS
    assert ev["orb"]["n"] >= 1 and ev["round_trip_cost_pct"] > 0.3
    # a driftless random walk should not pass after costs
    assert ev["passed"] is False
    payload = {"tables": [{"data": [["2330", "台積電", "Y"], ["0050", "ETF", ""], ["abc"]]}], "data": [["x", "2317"]]}
    assert screener._codes_in(payload) == {"2330", "2317"}


def test_plan_levels_states():
    from daytrade import screener
    c = DayTradeCosts()
    flat = [[100.0, 100.5, 99.5, 100.0, 1.0]] * 3
    lv = screener.plan_levels(flat[:2], tm.Rule(), c)
    assert lv["status"] == "waiting_range"
    lv = screener.plan_levels(flat, tm.Rule(), c)
    assert lv["status"] == "waiting_breakout" and lv["stop"] < lv["entry"] < lv["target"]
    up = flat + [[100.4, 101.0, 100.3, 100.9, 1.0]]
    assert screener.plan_levels(up, tm.Rule(), c)["status"] == "breakout_now"
    up2 = up + [[101.0, 101.2, 100.8, 101.0, 1.0]]
    lv = screener.plan_levels(up2, tm.Rule(), c)
    assert lv["status"] == "in_trade" and lv["entry_is_estimate"] is False
    up3 = up2 + [[101.0, 110.0, 101.0, 109.0, 1.0]]
    assert screener.plan_levels(up3, tm.Rule(), c)["status"] == "closed_target"
    # a finished (past) session never reports "in_trade"
    assert screener.plan_levels(up2, tm.Rule(), c, is_today=False)["status"] == "closed_close"
    assert screener._roc_date("1151030") == "2026-10-30"


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
