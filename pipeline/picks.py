"""每日當沖 5 檔候選（規則版本 R1，2026-11-15 定稿；改規則要先回測並換版本號）。

母體：上市＋上櫃 4 位數普通股，非處置股，20 日均成交值 ≥ 2 億，股價 20–50（1 張 ≤ NT$50,000），ATR14 ≥ 1.5%。
分數：20 日隔夜累計低、20 日最大單日漲幅低、ATR% 低、接近 52 週高、5 日報酬低，各取百分位相加，取前 5。
操作：A 版開盤集合競價買、收盤集合競價賣；B 版只在開盤價 ≤ 昨收 × 0.99 才買。盤中跌破開盤價 × 0.97 停損。
回測（2023-06 到 2026-11）：A 版扣成本後為負；B 版是事後發現的假說，要靠上線後的紀錄驗證。這裡只做模擬追蹤。
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from twcosts import BrokerFees

VERSION = "R1"
UA = {"User-Agent": "Mozilla/5.0"}
MIN_VALUE, MIN_PRICE, MAX_PRICE, MIN_ATR = 2e8, 20.0, 50.0, 0.015
STOP, B_GAP, TOP = 0.97, 0.99, 5
FACTORS = [("on20", -1), ("max20", -1), ("atr", -1), ("h52", 1), ("r5", -1)]


# ── 純計算（有測試） ─────────────────────────────────────────────
def tick(p: float) -> float:
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5


def floor_tick(x: float) -> float:
    t = tick(x)
    return round(math.floor(x / t + 1e-9) * t, 2)


def features(bars: list[dict]) -> dict | None:
    """bars：日線 {d,o,h,l,c,v}，由舊到新。資料不足 260 根回傳 None。"""
    if len(bars) < 260:
        return None
    last = len(bars) - 1
    c = [b["c"] for b in bars]
    on = [bars[i]["o"] / c[i - 1] - 1 for i in range(last - 19, last + 1)]
    ret = [c[i] / c[i - 1] - 1 for i in range(last - 19, last + 1)]
    tr = [max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - c[i - 1]), abs(bars[i]["l"] - c[i - 1]))
          for i in range(last - 13, last + 1)]
    val = [c[i] * bars[i]["v"] for i in range(last - 19, last + 1)]
    return {"date": bars[last]["d"], "close": c[last], "on20": sum(on), "max20": max(ret),
            "atr": sum(tr) / 14 / c[last], "h52": c[last] / max(c[-250:]), "r5": c[last] / c[last - 5] - 1,
            "val20": sum(val) / 20}


def _pct_rank(values: list[float]) -> list[float]:
    """同 pandas rank(pct=True)：同值取平均名次，再除以筆數。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return [r / len(values) for r in ranks]


def rank(rows: list[dict], top: int = TOP) -> tuple[list[dict], int]:
    """過濾母體、算分數，回傳（前 top 名, 母體檔數）。只用最新一個交易日的資料。"""
    if not rows:
        return [], 0
    last = max(r["date"] for r in rows)
    pool = [dict(r) for r in rows if r["date"] == last and r["val20"] >= MIN_VALUE
            and MIN_PRICE <= r["close"] <= MAX_PRICE and r["atr"] >= MIN_ATR]
    for r in pool:
        r["score"] = 0.0
    for key, sign in FACTORS:
        for r, p in zip(pool, _pct_rank([r[key] for r in pool])):
            r["score"] += p if sign > 0 else 1 - p
    best = sorted(pool, key=lambda r: -r["score"])[:top]
    return [{"code": r["code"], "name": r["name"], "mkt": r["mkt"], "close": round(r["close"], 2),
             "score": round(r["score"], 2), "atr_pct": round(r["atr"] * 100, 2),
             "buy_b_max": floor_tick(r["close"] * B_GAP)} for r in best], len(pool)


def score(pick: dict, bar: dict, fees: BrokerFees | None = None) -> dict:
    """用交易日當天的 OHLC 算 1 張的模擬損益（元），成本用元大費率模型。"""
    fees = fees or BrokerFees()
    o, low, c = bar["o"], bar["l"], bar["c"]
    stop = o * STOP
    hit = low <= stop
    exit_p = floor_tick(stop) if hit else c
    net0 = fees.round_trip(o, exit_p, 1000, daytrade=True)["net_pnl"]
    net1 = fees.round_trip(o + tick(o), exit_p - tick(exit_p), 1000, daytrade=True)["net_pnl"]
    taken = o <= pick["buy_b_max"]
    return {"code": pick["code"], "name": pick["name"], "open": round(o, 2), "close": round(c, 2),
            "gap_pct": round((o / pick["close"] - 1) * 100, 2), "stop_hit": hit,
            "a_net": round(net0), "a_net_tick1": round(net1), "b_taken": taken,
            "b_net": round(net0) if taken else 0, "b_net_tick1": round(net1) if taken else 0}


def totals(results: list[dict]) -> dict:
    """累計模擬成績。results：所有已結算的單筆。"""
    out = {}
    for v in ("a", "b"):
        rows = results if v == "a" else [r for r in results if r.get("b_taken")]
        n = len(rows)
        out[v] = {"n": n, "net": sum(r[v + "_net"] for r in rows), "net_tick1": sum(r[v + "_net_tick1"] for r in rows),
                  "win_rate_pct": round(sum(1 for r in rows if r[v + "_net"] > 0) / n * 100) if n else None}
    return out


# ── 抓資料 ───────────────────────────────────────────────────────
def _json(cl: httpx.Client, url: str):
    for k in range(4):
        try:
            r = cl.get(url)
            r.raise_for_status()
            return r.json()
        except Exception:
            if k == 3:
                raise
            time.sleep(2 + 3 * k)


def universe(cl: httpx.Client) -> list[tuple[str, str, str]]:
    tw = _json(cl, "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    tp = _json(cl, "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
    u = [(x["Code"], x["Name"], "TW") for x in tw] + [(x["SecuritiesCompanyCode"], x["CompanyName"], "TWO") for x in tp]
    return [x for x in u if len(x[0]) == 4 and x[0].isdigit() and x[0][0] != "0"]


def punished(cl: httpx.Client) -> set[str]:
    out = {x.get("Code") for x in _json(cl, "https://openapi.twse.com.tw/v1/announcement/punish")}
    try:
        out |= {x.get("SecuritiesCompanyCode") for x in _json(cl, "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information")}
    except Exception:
        pass
    return out


def daily(cl: httpx.Client, code: str, mkt: str, rng: str = "2y") -> list[dict]:
    r = cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.{mkt}", params={"range": rng, "interval": "1d"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    off = res["meta"].get("gmtoffset", 0)
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, low, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, low, c, v) or v <= 0 or o <= 0:
            continue
        d = time.strftime("%Y-%m-%d", time.gmtime(ts + off))
        if out and out[-1]["d"] == d:
            continue
        out.append({"d": d, "o": o, "h": h, "l": low, "c": c, "v": v})
    return out


def build(workers: int = 6) -> dict:
    """掃全市場，回傳 {signal_date, version, universe_n, items}。約 3 到 5 分鐘。"""
    with httpx.Client(timeout=30, headers=UA, follow_redirects=True) as cl:
        uni, pun = universe(cl), punished(cl)

        def one(u):
            code, name, mkt = u
            if code in pun:
                return None
            for k in range(3):
                try:
                    f = features(daily(cl, code, mkt))
                    return dict(f, code=code, name=name, mkt=mkt) if f else None
                except Exception:
                    time.sleep(1 + k)
            return None

        with ThreadPoolExecutor(workers) as ex:
            rows = [r for r in ex.map(one, uni) if r]
    if len(rows) < len(uni) * 0.5:
        raise RuntimeError(f"only {len(rows)}/{len(uni)} symbols fetched")
    items, n = rank(rows)
    return {"signal_date": max(r["date"] for r in rows), "version": VERSION, "universe_n": n, "items": items}
