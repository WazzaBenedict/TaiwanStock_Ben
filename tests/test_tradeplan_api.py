"""API 煙霧測試：不連網，以合成資料取代 fetch_tw_history。"""
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import app as appmod


def _fake_hist(n=400, seed=3):
    rng = np.random.default_rng(seed)
    px, rows = 100.0, []
    for i, d in enumerate(pd.bdate_range("2023-01-02", periods=n)):
        nxt = px * (1 + rng.normal(0.0008, 0.018))
        rows.append({"日期": d, "開盤價": px, "最高價": max(px, nxt) * 1.008, "最低價": min(px, nxt) * 0.992,
                     "收盤價": nxt, "成交股數": int(1e6 * (1 + rng.random()))})
        px = nxt
    return pd.DataFrame(rows)


def test_health_ok():
    c = TestClient(appmod.app)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_tradeplan_endpoint(monkeypatch):
    async def fake(sid, lookback_days=400):
        return _fake_hist(seed=int(sid) % 97), "test"
    monkeypatch.setattr(appmod, "fetch_tw_history", fake)
    appmod._tp_cache.clear()
    c = TestClient(appmod.app)
    r = c.get("/api/v2/tradeplan/2330", params={"capital": 500000, "risk_pct": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] in ("SETUP", "NOT_TRIGGERED", "NEGATIVE_EV", "UNVERIFIED")
    p = d["plan"]
    assert p["stop"] < p["entry"] < p["target"]
    assert p["position"]["risk_amount"] <= 5000
    assert "研究" in d["label"]
    assert c.get("/api/v2/tradeplan/abc").status_code == 400


def test_partial_intraday_bar_dropped():
    from datetime import datetime
    df = _fake_hist(100)
    today = datetime(2026, 11, 2, 11, 0)
    df.loc[len(df) - 1, "日期"] = pd.Timestamp(today.date())
    out = appmod._tp_clean(df, today, closed=False)
    assert len(out) == len(df) - 1
    assert len(appmod._tp_clean(df, today, closed=True)) == len(df)
