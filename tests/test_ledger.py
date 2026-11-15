import ledger
from ledger.core import normalize

BARS = {"2026-11-03": {"o": 100.0, "c": 101.0}, "2026-11-04": {"o": 101.0, "c": 100.0},
        "2026-11-05": {"o": 100.0, "c": 102.0}, "2026-11-10": {"o": 102.0, "c": 104.04},
        "2026-11-11": {"o": 104.0, "c": 104.0}}


def F(d, code, side, price, shares, **k):
    return {"date": d, "code": code, "side": side, "price": price, "shares": shares, **k}


def test_daytrade_costs_match_yuanta_by_hand():
    # 友達 1 張 28.80 買、28.60 賣（2026-11-04 實際那筆）：手續費 0.0855%→24、24；當沖稅 0.15%→42
    r = ledger.compute([F("2026-11-04", "2409", "buy", 28.80, 1000), F("2026-11-04", "2409", "sell", 28.60, 1000)], BARS)
    t = r["trades"][0]
    assert t["daytrade"] is True and t["gross"] == -200.0 and t["cost"] == 24 + 24 + 42 and t["net"] == -290.0
    # 當天 0050 開 101 收 100：28,800 元放 0050 會虧 285.15
    assert t["shadow_0050"] == -285.15 and t["vs_0050"] == -4.85
    assert r["summary"]["daytrade"]["n"] == 1 and r["summary"]["swing"]["n"] == 0


def test_swing_uses_full_tax_and_close_to_close_shadow():
    r = ledger.compute([F("2026-11-03", "1802", "buy", 40.0, 1000), F("2026-11-05", "1802", "sell", 42.0, 1000)], BARS)
    t = r["trades"][0]
    assert t["daytrade"] is False and t["hold_days"] == 2
    assert t["cost"] == 34 + 35 + 126 and t["net"] == 2000 - 195          # 稅 0.3% of 42,000 = 126
    assert t["shadow_0050"] == round(40000 * (102 / 101 - 1), 2)


def test_etf_tax_and_actual_costs_override_estimates():
    r = ledger.compute([F("2026-11-03", "0050", "buy", 100.0, 1000, fee=50), F("2026-11-05", "0050", "sell", 102.0, 1000, fee=51, tax=102)], BARS)
    assert r["trades"][0]["cost"] == 50 + 51 + 102 and r["fees"]["fills_with_actual_costs"] == 2
    r2 = ledger.compute([F("2026-11-03", "0050", "buy", 100.0, 1000), F("2026-11-05", "0050", "sell", 102.0, 1000)], BARS)
    assert r2["trades"][0]["cost"] == 85 + 87 + 102                        # ETF 稅 0.1%


def test_fifo_partial_sell_and_open_position():
    fills = [F("2026-11-03", "2409", "buy", 30.0, 1000), F("2026-11-04", "2409", "buy", 31.0, 1000),
             F("2026-11-05", "2409", "sell", 32.0, 1500)]
    r = ledger.compute(fills, BARS, {"2409": 33.0})
    assert [(t["buy_price"], t["shares"]) for t in r["trades"]] == [(30.0, 1000), (31.0, 500)]
    assert abs(sum(t["cost"] for t in r["trades"]) - (25 + 26 * 0.5 + 40 + 144)) < 0.01
    p = r["positions"][0]
    assert p["shares"] == 500 and p["buy_price"] == 31.0 and p["last_price"] == 33.0
    assert p["unrealized_net"] == round(1000 - 13 - (14 + 49), 2)
    assert r["summary"]["open_positions"] == 1


def test_discipline_rules_are_flagged():
    fills = [F("2026-11-04", "2330", "buy", 1000.0, 100, time="09:10"),           # 100,000 > 50,000
             F("2026-11-04", "2330", "sell", 985.0, 100, time="09:40"),           # 虧約 1,600 → 過每日停損
             F("2026-11-04", "2409", "buy", 28.0, 1000, time="10:00"),            # 停損後仍進場
             F("2026-11-04", "2409", "sell", 27.0, 1000, time="10:30"),           # 累計過 2,500
             F("2026-11-05", "2409", "buy", 28.0, 1000, time="13:05"),            # 總停損後 + 13:00 後
             F("2026-11-05", "3481", "sell", 40.0, 1000)]                         # 先賣後買
    r = ledger.compute(fills, BARS, rules={"total_stop": 2500})  # 用較小的總停損測試規則本身
    rules = sorted(v["rule"] for v in r["violations"])
    assert rules == ["daily_stop", "late_entry", "max_notional", "short_first", "total_stop"]
    assert r["summary"]["violating_trades"]["n"] == 2
    assert len(r["trades"]) == 2                                                   # 先賣後買那筆不計損益


def test_weekly_rule_60pct_and_cushion_cap():
    fills = []
    for d, pnl in [("2026-11-03", 3.0), ("2026-11-10", 5.0), ("2026-11-11", -1.0)]:
        fills += [F(d, "2409", "buy", 30.0, 1000), F(d, "2409", "sell", 30.0 + pnl, 1000)]
    w = ledger.compute(fills, BARS, rules={"max_notional": 10**9})["weekly"]
    n1 = w[0]["daytrade_net"]
    assert w[0]["week"] == "2026-W45" and w[0]["to_0050"] == int(n1 * 0.6)
    assert w[0]["cushion_after"] == round(n1 - int(n1 * 0.6), 2) and w[0]["cushion_after"] < 2000
    assert w[1]["cushion_after"] == 2000                                           # 緩衝金到上限，超過的轉 0050
    assert w[1]["to_0050"] > int(w[1]["daytrade_net"] * 0.6)


def test_bad_rows_are_reported_not_crashed():
    ok, bad = normalize([{"date": "2026/11/04", "code": "2409", "side": "買進", "price": "28.8", "shares": "1,000"},
                         {"date": "x", "code": "2409", "side": "buy", "price": 1, "shares": 1},
                         {"date": "2026-11-04", "code": "", "side": "buy", "price": 1, "shares": 1},
                         {"date": "2026-11-04", "code": "2409", "side": "hold", "price": 1, "shares": 1}])
    assert len(ok) == 1 and ok[0]["side"] == "buy" and ok[0]["shares"] == 1000 and ok[0]["date"] == "2026-11-04"
    assert len(bad) == 3
    r = ledger.compute([], BARS)
    assert r["trades"] == [] and r["summary"]["all"]["n"] == 0


def test_missing_0050_bar_gives_no_shadow_not_zero():
    r = ledger.compute([F("2026-12-01", "2409", "buy", 30.0, 1000), F("2026-12-01", "2409", "sell", 31.0, 1000)], BARS)
    assert r["trades"][0]["shadow_0050"] is None and r["summary"]["all"]["shadow_0050"] is None


def test_equity_curve_and_plan_slip():
    fills = [F("2026-11-04", "2409", "buy", 28.80, 1000, plan_price=28.90), F("2026-11-04", "2409", "sell", 28.60, 1000)]
    r = ledger.compute(fills, BARS)
    assert r["equity"] == [{"date": "2026-11-04", "net": -290.0, "shadow_0050": -285.15}]
    assert r["trades"][0]["slip_vs_plan"] == -100.0 and r["summary"]["plan_slip"] == -100.0
