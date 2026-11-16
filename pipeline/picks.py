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


def ceil_tick(x: float) -> float:
    t = tick(x)
    return round(math.ceil(x / t - 1e-9) * t, 2)


def plan_levels(close: float, atr: float) -> dict:
    """給報告看的操作價位：進場價＝B 版限價、停損約＝進場價×0.97（實際用開盤價×0.97）、
    參考目標＝進場價＋1 個 ATR（沒有回測，R1 規則仍是收盤賣）。"""
    lim = floor_tick(close * B_GAP)
    return {"entry_limit": lim, "entry_time": "08:30-09:00 掛限價，09:00 開盤成交",
            "stop_est": floor_tick(lim * STOP), "ref_target": ceil_tick(lim * (1 + atr)),
            "exit_time": "13:25-13:30 收盤集合競價"}


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
             "buy_b_max": floor_tick(r["close"] * B_GAP), **plan_levels(r["close"], r["atr"])} for r in best], len(pool)


MAX_NOTIONAL = 50_000   # 單筆買進上限（元）


def score(pick: dict, bar: dict, fees: BrokerFees | None = None) -> dict:
    """用交易日當天的 OHLC 算 1 張的模擬損益（元），成本用元大費率模型。"""
    fees = fees or BrokerFees()
    o, low, c = bar["o"], bar["l"], bar["c"]
    stop = o * STOP
    hit = low <= stop
    exit_p = floor_tick(stop) if hit else c
    net0 = fees.round_trip(o, exit_p, 1000, daytrade=True)["net_pnl"]
    net1 = fees.round_trip(o + tick(o), exit_p - tick(exit_p), 1000, daytrade=True)["net_pnl"]
    # 開盤跳空讓 1 張超過單筆上限 NT$50,000 時，照規則不買
    over_cap = o * 1000 > MAX_NOTIONAL
    taken = o <= pick["buy_b_max"] and not over_cap
    if over_cap:
        net0 = net1 = 0
    return {"code": pick["code"], "name": pick["name"], "open": round(o, 2), "close": round(c, 2),
            "gap_pct": round((o / pick["close"] - 1) * 100, 2), "stop_hit": hit,
            "over_cap": over_cap, "a_net": round(net0), "a_net_tick1": round(net1), "b_taken": taken,
            "b_net": round(net0) if taken else 0, "b_net_tick1": round(net1) if taken else 0}


# ── 個股回測（R1.1：候選先回測再給；定義與研究串 bt5.py 相同，另加「到參考目標就賣」） ──
BT_START, BT_OOS = "2023-06-01", "2025-01-01"


def _net_pct(buy: float, sell: float, fees: BrokerFees) -> float:
    return fees.round_trip(buy, sell, 1000, daytrade=True)["net_pnl"] / (buy * 1000) * 100


def bt_trade(o: float, h: float, low: float, c: float, target: float | None, fees: BrokerFees, slip: int = 0) -> float:
    """一天的當沖結果（%，扣元大成本）。開盤買；跌破開盤×0.97 停損；有 target 時漲到就賣，
    同一天停損與目標都碰到時保守算先停損（日線看不出先後）；都沒碰到就收盤賣。"""
    buy = o + slip * tick(o)
    stop = o * STOP
    if low <= stop:
        ex = floor_tick(stop)
    elif target is not None and h >= target:
        ex = target
    else:
        ex = c
    return _net_pct(buy, ex - slip * tick(ex), fees)


def backtest(bars: list[dict], start: str = BT_START, fees: BrokerFees | None = None) -> dict:
    """bars 由舊到新。回傳各版本的筆數、平均淨報酬%、勝率、2025 後平均。
    A：每天開盤買（同一檔隨便哪天進場，當作對照組）；B：開盤 ≤ 昨收×0.99 才買。
    close＝收盤賣（R1 原規則）；target＝漲到 開盤×(1+前一日 ATR14%) 就賣。"""
    fees = fees or BrokerFees()
    rows = {"A_close": [], "B_close": [], "B_close_t1": [], "A_target": [], "B_target": []}
    for i in range(15, len(bars)):
        b, pb = bars[i], bars[i - 1]
        if b["d"] < start:
            continue
        tr = [max(bars[k]["h"] - bars[k]["l"], abs(bars[k]["h"] - bars[k - 1]["c"]), abs(bars[k]["l"] - bars[k - 1]["c"]))
              for k in range(i - 14, i)]
        atr = sum(tr) / 14 / pb["c"]
        o, h, low, c = b["o"], b["h"], b["l"], b["c"]
        tgt = ceil_tick(o * (1 + atr))
        a0 = bt_trade(o, h, low, c, None, fees)
        at = bt_trade(o, h, low, c, tgt, fees)
        rows["A_close"].append((b["d"], a0))
        rows["A_target"].append((b["d"], at))
        if o <= pb["c"] * B_GAP:
            rows["B_close"].append((b["d"], a0))
            rows["B_close_t1"].append((b["d"], bt_trade(o, h, low, c, None, fees, slip=1)))
            rows["B_target"].append((b["d"], at))

    def stat(xs):
        n = len(xs)
        if not n:
            return {"n": 0, "avg": None, "win": None, "oos": None, "oos_n": 0}
        oo = [v for d, v in xs if d >= BT_OOS]
        return {"n": n, "avg": round(sum(v for _, v in xs) / n, 2), "win": round(sum(1 for _, v in xs if v > 0) / n * 100),
                "oos": round(sum(oo) / len(oo), 2) if oo else None, "oos_n": len(oo)}
    out = {k: stat(v) for k, v in rows.items()}
    bc, bt_ = out["B_close"], out["B_target"]
    out["from"] = start
    out["pass"] = bool(bc["n"] >= 20 and (bc["avg"] or 0) > 0 and (bc["oos"] or 0) > 0)
    out["target_better"] = bool(bc["n"] and bt_["avg"] is not None and bt_["avg"] > bc["avg"])
    return out


def attach_bt(items: list[dict], cl: httpx.Client | None = None) -> list[dict]:
    """幫每檔候選加上 bt（抓 5 年日線）。抓不到的那檔 bt=None，不影響其他檔。"""
    own = cl is None
    cl = cl or httpx.Client(timeout=30, headers=UA, follow_redirects=True)
    try:
        for x in items:
            if x.get("bt"):
                continue
            try:
                x["bt"] = backtest(daily(cl, x["code"], x.get("mkt", "TW"), "5y"))
            except Exception as e:
                print("bt failed", x.get("code"), type(e).__name__, str(e)[:80])
                x["bt"] = None
    finally:
        if own:
            cl.close()
    return items


def totals(results: list[dict]) -> dict:
    """累計模擬成績。results：所有已結算的單筆。"""
    out = {}
    for v in ("a", "b"):
        ok = [r for r in results if not r.get("over_cap")]
        rows = ok if v == "a" else [r for r in ok if r.get("b_taken")]
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
    attach_bt(items)
    return {"signal_date": max(r["date"] for r in rows), "version": VERSION, "universe_n": n, "items": items}
