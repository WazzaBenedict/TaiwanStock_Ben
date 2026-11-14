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


RULES = [
    {"id": "dt_2409", "name": "友達每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "2409", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "dt_3481", "name": "群創每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "3481", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "dt_1802", "name": "台玻每天當沖做多", "desc": "開盤買、收盤賣，每天做", "code": "1802", "fn": rule_daytrade_long, "kind": "當沖"},
    {"id": "gap_2409", "name": "友達開高 1% 追多當沖", "desc": "開盤比昨收高 1% 以上才進場，收盤賣", "code": "2409", "fn": rule_gap_up_daytrade, "kind": "當沖"},
    {"id": "on_0050", "name": "0050 買收盤賣開盤", "desc": "每天收盤買、隔天開盤賣", "code": "0050", "fn": rule_overnight, "kind": "隔夜"},
    {"id": "dip_2409", "name": "友達大跌 3% 後接", "desc": "單日跌 3% 以上，收盤買，抱 5 個交易日", "code": "2409", "fn": rule_dip_buy, "args": {"drop": 3.0}, "kind": "波段"},
    {"id": "dip_0050", "name": "0050 大跌 2% 後接", "desc": "單日跌 2% 以上，收盤買，抱 5 個交易日", "code": "0050", "fn": rule_dip_buy, "args": {"drop": 2.0}, "kind": "波段", "bench": "uncond"},
    {"id": "ma200_0050", "name": "0050 站上 200 日線才持有", "desc": "跌破 200 日線就出場，站回再買", "code": "0050", "fn": rule_ma200, "kind": "擇時", "timing": True},
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


def evaluate(rule: dict, bars: list[dict], bench: list[dict], today: str, fees=None) -> dict:
    fees = fees or broker()
    bmap = {b["d"]: b for b in bench}
    oos_start = (date.fromisoformat(today) - timedelta(days=OOS_DAYS)).isoformat()
    seg = {"is": [], "oos": [], "live": []}
    uncond = None
    if rule.get("bench") == "uncond":      # 標的本身就是 0050：改和「任何一天買進、抱同樣天數」的平均比
        h = rule.get("args", {}).get("hold", 5)
        w = [bench[i + h]["c"] / bench[i]["c"] - 1 for i in range(len(bench) - h)]
        uncond = sum(w) / len(w) if w else 0.0
    for t in rule["fn"](bars, **rule.get("args", {})):
        bi, bo = bmap.get(t["d_in"]), bmap.get(t["d_out"])
        if not bi or not bo or not t["buy"] or not t["sell"]:
            continue
        base = bi["o"] if t["daytrade"] else bi["c"]
        if not base:
            continue
        row = {"net": trade_net(t["buy"], t["sell"], rule["code"], t["daytrade"], fees), "bench": uncond if uncond is not None else bo["c"] / base - 1}
        key = "live" if t["d_in"] >= LIVE_START else "oos" if t["d_in"] >= oos_start else "is"
        seg[key].append(row)
    s = {k: _stats(v) for k, v in seg.items()}
    lab, why = label(s["is"], s["oos"])
    if rule.get("timing") and s["oos"]["n"] < MIN_N:      # 擇時規則交易次數天生很少，用整段結果說明
        allr = seg["is"] + seg["oos"] + seg["live"]
        a = _stats(allr)
        why = f"交易次數少（全部 {a.get('n', 0)} 筆），不能用筆數下結論；全期間合計比同期抱 0050 {'多' if a.get('sum_excess_pct', 0) > 0 else '少'} {abs(a.get('sum_excess_pct', 0))}%"
    return {"id": rule["id"], "name": rule["name"], "desc": rule["desc"], "code": rule["code"], "kind": rule["kind"],
            "label": lab, "why": why, "is": s["is"], "oos": s["oos"], "live": s["live"],
            "first_day": bars[0]["d"] if bars else None}


def yahoo(cl: httpx.Client, code: str, rng: str = "10y") -> list[dict]:
    from pipeline.snapshot import yahoo_daily
    for suf in (".TW", ".TWO"):
        try:
            rows = yahoo_daily(cl, code + suf, rng)
            if len(rows) > 250:
                return [r for r in rows if r["c"] and r["c"] > 0]
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
                if r["code"] not in cache:
                    cache[r["code"]] = yahoo(cl, r["code"])
                bars = cache[r["code"]]
                if not bars or not bench:
                    raise RuntimeError("抓不到日線")
                cards.append(evaluate(r, bars, bench, today, fees))
            except Exception as e:
                errors[r["id"]] = f"{type(e).__name__}: {str(e)[:100]}"
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "today": today, "live_start": LIVE_START,
           "oos_days": OOS_DAYS, "min_n": MIN_N, "trade_size": TRADE_SIZE, "fee_discount": fees.fee_discount, "cards": cards, "errors": errors,
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
