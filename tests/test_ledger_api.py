import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ledger import importer
from ledger.api import make_router


async def fake_history(code, days):
    if code == "0050":
        return pd.DataFrame({"日期": ["2026-11-03", "2026-11-04", "2026-11-05"], "開盤價": [100.0, 101.0, 102.0],
                             "收盤價": [101.0, 102.0, 103.0]}), "fake"
    if code == "2409":
        return pd.DataFrame({"日期": ["2026-11-05"], "開盤價": [33.0], "收盤價": [33.5]}), "fake"
    return pd.DataFrame(), "none"


def client():
    app = FastAPI()
    app.include_router(make_router(fake_history))
    return TestClient(app)


def test_compute_fetches_0050_and_last_prices():
    fills = [{"date": "2026-11-03", "code": "2409", "side": "buy", "price": 30, "shares": 2000},
             {"date": "2026-11-04", "code": "2409", "side": "sell", "price": 31, "shares": 1000},
             {"date": "2026-11-04", "code": "9999", "side": "buy", "price": 10, "shares": 1000}]
    r = client().post("/api/ledger/compute", json={"fills": fills, "fee_discount": 0.5}).json()
    assert r["fees"]["fee_discount"] == 0.5 and len(r["trades"]) == 1
    assert r["trades"][0]["shadow_0050"] == round(30000 * (102 / 101 - 1), 2)
    pos = {p["code"]: p for p in r["positions"]}
    assert pos["2409"]["last_price"] == 33.5 and pos["9999"]["last_price"] is None
    assert r["data"]["missing_last_price"] == ["9999"] and r["data"]["last_0050_date"] == "2026-11-05"


def test_compute_rejects_bad_payload_and_ignores_unknown_rules():
    c = client()
    assert c.post("/api/ledger/compute", json={"fills": "x"}).status_code == 400
    r = c.post("/api/ledger/compute", json={"fills": [], "rules": {"max_notional": 1, "hack": 2}, "fee_discount": 9}).json()
    assert r["rules"]["max_notional"] == 1 and "hack" not in r["rules"] and r["fees"]["fee_discount"] == 0.6


CSV = """元大證券 成交明細,,,,,,,,
帳號,98X-XXXXXXX,,,,,,,
成交日期,成交時間,股票名稱,買賣別,成交股數,成交價,價金,手續費,交易稅
115/11/09,09:05:12,友達(2409),現股買進,"2,000",15.50,"31,000",26,0
115/11/09,10:31:00,友達(2409),現股賣出,"2,000",15.70,"31,400",26,47
2026/11/10,,元大台灣50(0050),現股買進,100,60.00,"6,000",5,0
,,,,,,,,
合計,,,,,,,,
壞列,,台積電,現股買進,1000,xx,,,
"""


def test_import_roc_dates_codes_in_name_and_reports_bad_rows():
    r = importer.parse(CSV)
    assert r["error"] is None and len(r["fills"]) == 3
    a, b, c = r["fills"]
    assert (a["date"], a["time"], a["code"], a["side"], a["price"], a["shares"], a["fee"]) == ("2026-11-09", "09:05", "2409", "buy", 15.5, 2000, 26)
    assert b["side"] == "sell" and b["tax"] == 47 and c["code"] == "0050" and c["date"] == "2026-11-10"
    assert len(r["skipped"]) == 1 and r["skipped"][0]["reason"] == "日期看不懂"
    assert importer.parse(CSV)["fills"][0]["id"] == a["id"]             # 重複匯入 id 不變，可去重


def test_import_tab_text_lots_and_duplicates_kept():
    t = "日期\t代號\t買賣\t張數\t成交價\n20261112\t3481\t買\t1\t12.5\n20261112\t3481\t買\t1\t12.5\n1151112\t3481\t賣\t2\t12.6\n"
    r = importer.parse(t)
    assert [f["shares"] for f in r["fills"]] == [1000, 1000, 2000] and len({f["id"] for f in r["fills"]}) == 3
    assert r["fills"][2]["date"] == "2026-11-12"


def test_import_no_header_and_implied_discount():
    assert importer.parse("hello\nworld")["error"]
    fills = [{"price": 100.0, "shares": 1000 * k, "fee": int(100000 * k * 0.001425 * 0.28)} for k in (1, 2, 3, 4)]
    assert importer.implied_discount(fills)["discount"] == 0.28
    assert importer.implied_discount(fills[:2]) is None


def test_import_endpoint():
    r = client().post("/api/ledger/import", json={"text": CSV}).json()
    assert len(r["fills"]) == 3 and r["columns"]["price"] == "成交價"


YUANTA_APP = """交易日期,證券名稱,交易類別,價格,股數,應收付,已實現損益
2026/11/02,友達,現沖買進,30,1000,"-30,025",--
2026/11/02,友達,現沖買進,29.95,1000,"-29,975",--
2026/11/02,友達,現沖買進,29.9,1000,"-29,925",--
2026/11/02,友達,現沖賣出,30.65,3000,"91,735","1,810"
2026/11/03,友達,現沖賣出,29.2,6000,"174,789","-4,764"
2026/11/03,友達,現沖買進,29.9,6000,"-179,553",--
2026/11/03,不存在公司,現沖買進,10,1000,"-10,020",--
"""


def test_yuanta_app_format_name_lookup_net_amount_and_untimed_daytrades():
    import ledger
    r = importer.parse(YUANTA_APP, name_to_code=lambda n: {"友達": "2409"}.get(n))
    f = r["fills"]
    assert len(f) == 6 and all(x["code"] == "2409" for x in f)
    assert (f[0]["fee"], f[0]["tax"]) == (25, 0) and (f[3]["fee"], f[3]["tax"]) == (78, 137)
    assert (f[4]["fee"], f[4]["tax"]) == (149, 262) and f[5]["fee"] == 153
    assert r["skipped"][0]["reason"] == "找不到股票代號"
    assert r["implied_fee_discount"] is None or r["implied_fee_discount"]["discount"] == 0.6
    out = ledger.compute(f, {})
    by_day = {}
    for t in out["trades"]:
        by_day[t["close_date"]] = by_day.get(t["close_date"], 0) + t["net"]
    assert round(by_day["2026-11-02"]) == 1810 and round(by_day["2026-11-03"]) == -4764   # 與元大 App 的已實現損益一致
    assert not [v for v in out["violations"] if v["rule"] == "short_first"]           # 沒有時間時不誤判先賣後買
    assert all(t["daytrade"] for t in out["trades"])
