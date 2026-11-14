"""研究室評分表（v14.3）：每個交易日自動重算，讓標籤跟著新資料自己更新。

每條規則都拆成三段來看：
- 樣本內：較早的歷史（規則是看著這段想出來的，最不可信）
- 樣本外：最近兩年（不含上線後）
- 上線後：從 LIVE_START 起，規則寫死之後才發生的日子，每天自動累積，最可信

每筆交易都扣元大成本（twcosts），並和「同一筆錢同期放 0050」比較。
標籤由程式依固定門檻判定，不靠人工挑選。價格未含股利，對買進持有略為不利。
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cloudstore  # noqa: E402
from twcosts import broker, is_etf  # noqa: E402

LIVE_START = "2026-11-16"     # 規則定稿後的第一個交易日
OOS_DAYS = 730
MIN_N = 30
ROUND_TRIP_ETF = 0.00271       # ETF 一買一賣的成本（手續費 6 折兩次加交易稅 0.1%）
TRADE_SIZE = 50000          # 每筆約 5 萬元，和帳本的每筆上限一致
LOG_FILE = Path(__file__).resolve().parent / "research_log.json"
UA = {"User-Agent": "Mozilla/5.0"}


def trade_net(buy: float, sell: float, code: str, daytrade: bool, fees) -> float:
    """每筆約 TRADE_SIZE 元（整張）的扣成本報酬率（小數）。"""
    sh = max(1, round(TRADE_SIZE / buy / 1000)) * 1000
    cost = buy * sh + fees.fee(buy, sh)
    got = sell * sh - fees.fee(sell, sh) - fees.tax(sell, sh, is_etf(code), daytrade=daytrade)
    return got / cost - 1


# ── 規則：輸入日線，輸出交易清單 {d_in, d_out, buy, sell, daytrade} ──
def rule_daytrade_long(bars, **_):
    return [{"d_in": b["d"], "d_out": b["d"], "buy": b["o"], "sell": b["c"], "daytrade": True} for b in bars if b["o"]]


def rule_gap_up_daytrade(bars, gap=1.0, **_):
    out = []
    for p, b in zip(bars, bars[1:]):
        if b["o"] and (b["o"] / p["c"] - 1) * 100 >= gap:
            out.append({"d_in": b["d"], "d_out": b["d"], "buy": b["o"], "sell": b["c"], "daytrade": True})
    return out


def rule_overnight(bars, **_):
    return [{"d_in": p["d"], "d_out": b["d"], "buy": p["c"], "sell": b["o"], "daytrade": False}
            for p, b in zip(bars, bars[1:]) if b["o"]]


def rule_dip_buy(bars, drop=3.0, hold=5, **_):
    out, i = [], 1
    while i < len(bars) - hold:
        if (bars[i]["c"] / bars[i - 1]["c"] - 1) * 100 <= -drop:
            out.append({"d_in": bars[i]["d"], "d_out": bars[i + hold]["d"], "buy": bars[i]["c"], "sell": bars[i + hold]["c"], "daytrade": False})
            i += hold
        else:
            i += 1
    return out


def rule_ma200(bars, **_):
    """收盤站上 200 日線就持有、跌破就出場（以當天收盤成交）。"""
    out, entry = [], None
    for i in range(200, len(bars)):
        ma = sum(b["c"] for b in bars[i - 199:i + 1]) / 200
        above = bars[i]["c"] > ma
        if above and entry is None:
            entry = bars[i]
        elif not above and entry is not None:
            out.append({"d_in": entry["d"], "d_out": bars[i]["d"], "buy": entry["c"], "sell": bars[i]["c"], "daytrade": False})
            entry = None
    return out


def rule_hold_blocks(bars, block=10, **_):
    """長期持有：切成每 10 個交易日一段來和 0050 比，不換手所以不計買賣成本；用還原股利的價格。"""
    out = []
    for i in range(0, len(bars) - block, block):
        a, b = bars[i], bars[i + block]
        out.append({"d_in": a["d"], "d_out": b["d"], "buy": a.get("a") or a["c"], "sell": b.get("a") or b["c"], "daytrade": False, "free": True})
    return out


def rule_trend_blocks(bars, block=10, ref=None, **_):
    """每 10 個交易日檢查一次：0050 收盤在 200 日線之上才持有，否則空手。進出各算一次成本。"""
    ref = ref or bars
    closes = {b["d"]: i for i, b in enumerate(ref)}
    out, held = [], False
    for i in range(0, len(bars) - block, block):
        a, b = bars[i], bars[i + block]
        j = closes.get(a["d"])
        if j is None or j < 199:
            continue
        on = ref[j]["c"] > sum(x["c"] for x in ref[j - 199:j + 1]) / 200
        out.append({"d_in": a["d"], "d_out": b["d"], "buy": a.get("a") or a["c"], "sell": b.get("a") or b["c"], "daytrade": False,
                    "free": True, "flat": not on, "switch": on != held})
        held = on
    return out


def rule_pre_exdiv(bars, before=10, **_):
    """除息日前 10 個交易日收盤買，除息前一天收盤賣。"""
    out = []
    for i, b in enumerate(bars):
        if b.get("div") and i - before >= 0:
            out.append({"d_in": bars[i - before]["d"], "d_out": bars[i - 1]["d"], "buy": bars[i - before]["c"], "sell": bars[i - 1]["c"], "daytrade": False})
    return out


RULES = [
    {"id": "dt_2409", "name": "友達每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "2409", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "dt_3481", "name": "群創每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "3481", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "dt_1802", "name": "台玻每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "1802", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "gap_2409", "name": "友達開高 1% 追多當沖", "desc": "開盤比昨收高 1% 以上才進場，收盤賣", "code": "2409", "fn": rule_gap_up_daytrade, "kind": "當沖"},
    {"id": "on_0050", "name": "0050 買收盤賣開盤", "desc": "每天收盤買、隔天開盤賣", "code": "0050", "fn": rule_overnight, "kind": "隔夜"},
    {"id": "dip_2409", "name": "友達大跌 3% 後接", "desc": "單日跌 3% 以上，收盤買，抱 5 個交易日", "code": "2409", "fn": rule_dip_buy, "args": {"drop": 3.0}, "kind": "波段"},
    {"id": "dip_0050", "name": "0050 大跌 2% 後接", "desc": "單日跌 2% 以上，收盤買，抱 5 個交易日", "code": "0050", "fn": rule_dip_buy, "args": {"drop": 2.0}, "kind": "波段", "bench": "uncond"},
    {"id": "hold_00631L", "name": "長期持有 00631L（正2）", "desc": "買進後不動，每 10 個交易日和 0050 比一次", "code": "00631L", "fn": rule_hold_blocks, "kind": "持有",
     "caution": "報酬較高是用更大的波動換來的：2014 到 2026 年最大跌幅約 55%（0050 約 34%），花了近兩年才回到原點"},
    {"id": "trend_00631L", "name": "00631L 搭配 200 日線", "desc": "0050 在 200 日線之上才持有正2，跌破就空手，每 10 個交易日檢查", "code": "00631L", "fn": rule_trend_blocks, "kind": "擇時", "ref0050": True,
     "caution": "目的是避開大跌，不是多賺；多頭年會少賺"},
    {"id": "exdiv_hd", "name": "高股息 ETF 除息前行情", "desc": "0056、00878、00919 除息前 10 個交易日買、除息前一天賣", "code": "0056", "codes": ["0056", "00878", "00919"], "fn": rule_pre_exdiv, "kind": "事件",
     "caution": "研究顯示除息前有買盤推升，但 2025 年 7 月收益平準金新制後效果可能變弱"},
    {"id": "ma200_0050", "name": "0050 站上 200 日線才持有", "desc": "跌破 200 日線就出場，站回再買", "code": "0050", "fn": rule_ma200, "kind": "擇時", "timing": True},
]


# 2026-11-14 資料搜集的摘要。grade：A 學術論文或官方統計；B 媒體轉述官方數字或工作論文；C 業者回測。
EVIDENCE = [
    {"topic": "當沖的整體結果", "grade": "B", "year": "2020–2025",
     "text": "證交所與金管會公布的統計顯示，當沖客扣掉稅費後每年合計都是淨損：2024 年約 246 億元，2025 年約 272 億元。扣成本前其實是賺的，是手續費和交易稅把它變成虧損。"},
    {"topic": "有多少人能穩定獲利", "grade": "A", "year": "1992–2006（資料較舊）",
     "text": "Barber、Lee、Liu、Odean 研究台灣全部當沖帳戶：每年整體都虧，能預期隔年繼續獲利的不到 1%；2020 年的後續論文估計 97% 的人長期會虧。過去有長期獲利紀錄，是唯一有用的預測指標。"},
    {"topic": "降稅之後", "grade": "B", "year": "2016–2017",
     "text": "Chen 與 Lin（2025 工作論文）：當沖稅減半後小帳戶交易量增加 45%，年虧損從約 6% 擴大到約 9%。平均每筆扣成本前只賺 0.28%，而元大 6 折一買一賣的成本約 0.32%。"},
    {"topic": "停損與上限有沒有用", "grade": "A", "year": "2014–2022",
     "text": "自動停損能逼自己認賠，減少「賺一點就賣、賠了死抱」（RFS 2017 實驗）；外部強制的部位上限改善了散戶績效（Heimer 與 Imas 2022）。停損本身不會創造獲利，它的作用是限制虧損擴大。"},
    {"topic": "月營收選股", "grade": "C", "year": "2010–2026",
     "text": "營收公布後股價確實會續漲（Chen 與 Yu 2022 有學術佐證），但做成只買不放空的策略，報酬 17.7% 對 0050 的 16.4%，風險調整後反而輸，成本每年吃掉約 7 個百分點。適合當篩選條件，不適合單獨當策略。"},
    {"topic": "動能與追強勢股", "grade": "A", "year": "1987–2019",
     "text": "台股是少數整體沒有動能效應的市場（Fu 與 Hsieh 2024），一月還會反轉。追過去半年最強的股票沒有穩定優勢。"},
    {"topic": "投信買超", "grade": "C", "year": "2015–2026",
     "text": "投信買超比外資買超有參考性，但單獨使用報酬 9.7%，遠輸 0050 的 20.6%。持有 6 到 15 天才勉強打平成本。"},
    {"topic": "處置股", "grade": "C", "year": "2011–2026",
     "text": "過去處置期間進場曾是很大的優勢，但 2026 年 8 月 10 日新制（處置期縮短為 5 天、約 2 分鐘撮合一次）之後，141 筆交易平均只剩 +0.35%，低於成本。這個做法已經失效。"},
    {"topic": "正2（00631L）長期持有", "grade": "B", "year": "2014–2026",
     "text": "年化報酬 33.4% 對 0050 的 20.7%，但最大跌幅 55% 對 34%，跌下去後花了 492 個交易日才回到原點。報酬是用更大的波動換來的。"},
    {"topic": "高股息 ETF 除息前", "grade": "B", "year": "到 2025 年 12 月",
     "text": "臺灣銀行季刊統計 187 次除息：除息前 10 天累計多漲 1.42%，除息當天跌 0.89%。2025 年 7 月收益平準金新制後效果可能變弱，尚無新數據。"},
]

# 需要定期複查的規則與日期
RULE_WATCH = [
    {"date": "2026-08-10", "text": "處置股新制已上路：處置期 5 個營業日，約每 2 分鐘撮合一次。處置股不能當沖。"},
    {"date": "2026-12-07", "text": "盤中零股改為 08:30 開始收單、09:00 第一次撮合（目前是 09:10）。零股不能當沖。"},
    {"date": "2026-12-18", "text": "006208（富邦台50）受益人會議表決分割，結果未定。"},
    {"date": "2026-12-31", "text": "債券 ETF 免證交稅到這天為止，延長案審議中。"},
    {"date": "2027-12-31", "text": "現股當沖交易稅減半（0.15%）到這天為止。"},
]


def _stats(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    net = [r["net"] for r in rows]
    ex = [r["net"] - r["bench"] for r in rows]
    m = sum(ex) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "win_rate_pct": round(sum(1 for x in net if x > 0) / n * 100),
            "avg_net_pct": round(sum(net) / n * 100, 3), "sum_net_pct": round(sum(net) * 100, 1),
            "avg_excess_pct": round(m * 100, 3), "sum_excess_pct": round(sum(ex) * 100, 1),
            "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0}


def label(is_: dict, oos: dict) -> tuple[str, str]:
    """固定門檻：樣本外至少 30 筆才下結論。"""
    if oos.get("n", 0) < MIN_N:
        return "研究中", f"樣本外只有 {oos.get('n', 0)} 筆，不足 {MIN_N} 筆"
    if oos["avg_net_pct"] <= 0:
        return "未通過", "樣本外扣成本後平均是虧的"
    if oos["avg_excess_pct"] <= 0:
        return "未通過", "樣本外有賺，但輸給同期放 0050"
    if oos["t"] >= 2 and is_.get("n", 0) >= MIN_N and is_.get("avg_excess_pct", 0) > 0:
        return "可用", "樣本內、樣本外都贏 0050，且差距在統計上站得住"
    return "研究中", "樣本外贏 0050，但差距還不夠穩定或樣本內不一致"


def evaluate(rule: dict, bars, bench: list[dict], today: str, fees=None) -> dict:
    """bars 可以是單一標的的日線，或 [(代號, 日線), ...]（一條規則套用多檔）。"""
    fees = fees or broker()
    series = bars if bars and isinstance(bars[0], tuple) else [(rule["code"], bars)]
    bars = series[0][1]
    bmap = {b["d"]: b for b in bench}
    oos_start = (date.fromisoformat(today) - timedelta(days=OOS_DAYS)).isoformat()
    seg = {"is": [], "oos": [], "live": []}
    uncond = None
    if rule.get("bench") == "uncond":      # 標的本身就是 0050：改和「任何一天買進、抱同樣天數」的平均比
        h = rule.get("args", {}).get("hold", 5)
        w = [bench[i + h]["c"] / bench[i]["c"] - 1 for i in range(len(bench) - h)]
        uncond = sum(w) / len(w) if w else 0.0
    extra = {"ref": bench} if rule.get("ref0050") else {}
    trades = [(code, t) for code, bs in series for t in rule["fn"](bs, **rule.get("args", {}), **extra)]
    trades.sort(key=lambda x: x[1]["d_in"])
    for code, t in trades:
        bi, bo = bmap.get(t["d_in"]), bmap.get(t["d_out"])
        if not bi or not bo or not t["buy"] or not t["sell"]:
            continue
        if t.get("free"):                               # 持有類：用還原價，0050 也用還原價
            b_in, b_out = bi.get("a") or bi["c"], bo.get("a") or bo["c"]
            net = 0.0 if t.get("flat") else t["sell"] / t["buy"] - 1
            if t.get("switch"):
                net -= ROUND_TRIP_ETF / 2
            row = {"net": net, "bench": b_out / b_in - 1}
        else:
            base = bi["o"] if t["daytrade"] else bi["c"]
            if not base:
                continue
            row = {"net": trade_net(t["buy"], t["sell"], code, t["daytrade"], fees), "bench": uncond if uncond is not None else bo["c"] / base - 1}
        key = "live" if t["d_in"] >= LIVE_START else "oos" if t["d_in"] >= oos_start else "is"
        seg[key].append(row)
    s = {k: _stats(v) for k, v in seg.items()}
    lab, why = label(s["is"], s["oos"])
    if rule.get("timing") and s["oos"]["n"] < MIN_N:      # 擇時規則交易次數天生很少，用整段結果說明
        allr = seg["is"] + seg["oos"] + seg["live"]
        a = _stats(allr)
        why = f"交易次數少（全部 {a.get('n', 0)} 筆），不能用筆數下結論；全期間合計比同期抱 0050 {'多' if a.get('sum_excess_pct', 0) > 0 else '少'} {abs(a.get('sum_excess_pct', 0))}%"
    return {"id": rule["id"], "name": rule["name"], "desc": rule["desc"], "code": rule["code"], "kind": rule["kind"],
            "label": lab, "why": why, "caution": rule.get("caution"), "is": s["is"], "oos": s["oos"], "live": s["live"],
            "first_day": bars[0]["d"] if bars else None}


def yahoo(cl: httpx.Client, code: str, rng: str = "10y") -> list[dict]:
    """日線，附還原收盤價 a 與除息日標記 div。"""
    for suf in (".TW", ".TWO"):
        try:
            r = cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suf}", params={"range": rng, "interval": "1d", "events": "div"})
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or []
            off = res["meta"].get("gmtoffset", 0)
            day = lambda ts: datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
            divs = {day(v["date"]) for v in (res.get("events", {}).get("dividends") or {}).values()}
            rows = []
            for k, ts in enumerate(res.get("timestamp") or []):
                c = q["close"][k]
                if not c or c <= 0:
                    continue
                d = day(ts)
                rows.append({"d": d, "o": q["open"][k], "h": q["high"][k], "l": q["low"][k], "c": c,
                             "a": adj[k] if k < len(adj) and adj[k] else c, "div": d in divs})
            if len(rows) > 250:
                return rows
        except Exception:
            continue
    return []


def track_changes(cards: list[dict], today: str) -> list[dict]:
    """把每次標籤變動記到雲端，頁面上看得到規則是哪一天被升級或淘汰的。"""
    cloudstore.pull(LOG_FILE)
    try:
        log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        log = {}
    last, changes = log.get("labels", {}), log.get("changes", [])
    for c in cards:
        old = last.get(c["id"])
        if old and old != c["label"]:
            changes.append({"date": today, "id": c["id"], "name": c["name"], "from": old, "to": c["label"]})
        last[c["id"]] = c["label"]
    log = {"labels": last, "changes": changes[-100:], "runs": log.get("runs", 0) + 1, "first_run": log.get("first_run") or today}
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
    log["persisted"] = cloudstore.push(LOG_FILE)
    return log


def build() -> dict:
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    fees = broker()
    errors, cards, cache = {}, [], {}
    with httpx.Client(timeout=30, headers=UA, follow_redirects=True) as cl:
        bench = yahoo(cl, "0050")
        cache["0050"] = bench
        for r in RULES:
            try:
                codes = r.get("codes") or [r["code"]]
                for c in codes:
                    if c not in cache:
                        cache[c] = yahoo(cl, c)
                got = [(c, cache[c]) for c in codes if cache[c]]
                if not got or not bench:
                    raise RuntimeError("抓不到日線")
                cards.append(evaluate(r, got if r.get("codes") else got[0][1], bench, today, fees))
            except Exception as e:
                errors[r["id"]] = f"{type(e).__name__}: {str(e)[:100]}"
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "today": today, "live_start": LIVE_START,
           "oos_days": OOS_DAYS, "min_n": MIN_N, "trade_size": TRADE_SIZE, "fee_discount": fees.fee_discount, "cards": cards, "errors": errors, "evidence": EVIDENCE, "rule_watch": RULE_WATCH, "evidence_date": "2026-11-14",
           "counts": {k: sum(1 for c in cards if c["label"] == k) for k in ("可用", "研究中", "未通過")}}
    try:
        log = track_changes(cards, today)
        out["changes"] = log["changes"][-20:]
        out["runs"] = log["runs"]
        out["first_run"] = log["first_run"]
        out["persisted"] = log["persisted"]
    except Exception as e:
        errors["log"] = f"{type(e).__name__}: {str(e)[:100]}"
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "public" / "data" / "research.json"
    out = build()
    if len(out["cards"]) < len(RULES) // 2:
        print("research incomplete, not writing:", json.dumps(out["errors"], ensure_ascii=False))
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", path, out["counts"], "| errors:", json.dumps(out["errors"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
