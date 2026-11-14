"""每日快照：把「今日」頁需要的資料一次算好，輸出成 JSON。

用法：python -m pipeline.snapshot [輸出檔]   （預設 public/data/today.json）

原則（見 methodology/premarket_rules.md 的實測結果）：
- 隔夜指標（費半、台積電 ADR、台指期夜盤）只用來預估 0050「開盤跳空」，不預測收盤。
- 美股與夜盤矛盾時以夜盤為準。
- 200 日線與波動只當風險參考，不是買賣訊號。
- 任何一個來源失敗都不能讓整份快照失敗：該區塊標 ok=false 並附原因。
"""
from __future__ import annotations

import email.utils as eu
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

TPE = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
FINMIND = "https://api.finmindtrade.com/api/v4/data"
DEFAULT_WATCH = ["0050", "00631L", "2409", "1802", "3481"]
OVERNIGHT = [("^SOX", "費城半導體"), ("TSM", "台積電 ADR"), ("^IXIC", "那斯達克"), ("^GSPC", "標普 500")]
VOL_YELLOW = 25.0   # 20 日年化波動（%）高於此值亮黃燈


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, headers=UA, follow_redirects=True)


# ── 純計算（有測試） ─────────────────────────────────────────────
def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not b:
        return None
    return round((a / b - 1) * 100, 2)


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def realized_vol(closes: list[float], n: int = 20) -> float | None:
    """n 日年化波動（%）。"""
    if len(closes) < n + 1:
        return None
    r = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    m = sum(r) / n
    return round(math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1)) * math.sqrt(252) * 100, 1)


def fit_gap_model(xs: list[float], ys: list[float]) -> dict | None:
    """最小平方法：0050 開盤跳空% = a + b × 費半前一晚漲跌%。回傳係數、相關係數與樣本數。"""
    n = len(xs)
    if n < 60 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if not sxx or not syy:
        return None
    b = sxy / sxx
    return {"a": round(my - b * mx, 4), "b": round(b, 4), "corr": round(sxy / math.sqrt(sxx * syy), 2), "n": n}


def estimate_gap(night_pct: float | None, sox_pct: float | None, model: dict | None) -> dict:
    """夜盤優先；沒有夜盤才用費半回歸。"""
    if night_pct is not None:
        note = "以台指期夜盤漲跌幅估計"
        if sox_pct is not None and night_pct * sox_pct < 0:
            note += "（美股與夜盤方向相反，以夜盤為準）"
        if sox_pct is not None and model:
            note += f"；費半回歸為 {model['a'] + model['b'] * sox_pct:+.2f}%"
        return {"ok": True, "pct": round(night_pct, 2), "basis": "night", "note": note}
    if sox_pct is not None and model:
        return {"ok": True, "pct": round(model["a"] + model["b"] * sox_pct, 2), "basis": "sox",
                "note": f"以費半回歸估計（近 {model['n']} 日，相關 {model['corr']}）"}
    return {"ok": False, "pct": None, "basis": None, "note": "隔夜資料不足，無法估計"}


def risk_light(close: float | None, ma200: float | None, vol20: float | None) -> dict:
    if close is None or ma200 is None:
        return {"ok": False, "color": "unknown", "label": "資料不足", "text": "無法計算 200 日線"}
    dist = round((close / ma200 - 1) * 100, 1)
    if close < ma200:
        color, label, text = "red", "紅燈", "加權跌破 200 日線：槓桿部位（00631L）風險最高，避免加碼"
    elif vol20 is not None and vol20 >= VOL_YELLOW:
        color, label, text = "yellow", "黃燈", f"加權在 200 日線上，但 20 日波動 {vol20}% 偏高：槓桿部位宜縮小"
    else:
        color, label, text = "green", "綠燈", "加權在 200 日線上、波動正常"
    return {"ok": True, "color": color, "label": label, "text": text, "dist_ma200_pct": dist, "vol20_pct": vol20,
            "note": "風險參考，不是買賣訊號"}


def fresh_night(night: dict | None, last_tw_day: str | None) -> dict | None:
    """夜盤資料的日期標為「次一交易日」。只有晚於最近一根台股日線時，才是還沒開盤的那一晚。"""
    if not night or not last_tw_day or night.get("pct") is None:
        return None
    return night if night["date"] > last_tw_day else None


def conclusion(gap: dict, light: dict) -> str:
    parts = ["0050 持有，當沖今天不做"]
    if gap.get("ok"):
        g = gap["pct"]
        parts.append("0050 預估" + ("開高" if g > 0.15 else "開低" if g < -0.15 else "平盤附近開出") + f"（{g:+.2f}%）")
    if light.get("ok"):
        parts.append("大盤" + light["label"])
    return "；".join(parts) + "。"


def gap_pairs(sox: list[dict], tw: list[dict]) -> tuple[list[float], list[float]]:
    """把每個台股交易日的 0050 跳空，配上「該日之前最近一個美股收盤日」的費半漲跌。"""
    sox_ret = {}
    for i in range(1, len(sox)):
        if sox[i]["c"] and sox[i - 1]["c"]:
            sox_ret[sox[i]["d"]] = (sox[i]["c"] / sox[i - 1]["c"] - 1) * 100
    sdays = sorted(sox_ret)
    xs, ys = [], []
    j = 0
    for i in range(1, len(tw)):
        o, pc, d = tw[i]["o"], tw[i - 1]["c"], tw[i]["d"]
        if not o or not pc:
            continue
        while j + 1 < len(sdays) and sdays[j + 1] < d:
            j += 1
        if not sdays or sdays[j] >= d or sdays[j] < tw[i - 1]["d"]:
            continue   # 沒有落在兩個台股交易日之間的美股收盤（例如美股休市）
        xs.append(sox_ret[sdays[j]])
        ys.append((o / pc - 1) * 100)
    return xs, ys


# ── 抓資料 ───────────────────────────────────────────────────────
def yahoo_daily(cl: httpx.Client, symbol: str, rng: str = "2y") -> list[dict]:
    r = cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"range": rng, "interval": "1d"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    off = res["meta"].get("gmtoffset", 0)
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
        out.append({"d": d, "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": c})
    return out


def night_session(cl: httpx.Client, today: date) -> dict | None:
    """台指期夜盤（FinMind，日期標為次一交易日）。回傳漲跌幅 %。"""
    token = os.getenv("FINMIND_TOKEN", "").strip()
    r = cl.get(FINMIND, params={"dataset": "TaiwanFuturesDaily", "data_id": "TX",
                                "start_date": (today - timedelta(days=6)).isoformat()},
               headers={"Authorization": f"Bearer {token}"} if token else None)
    r.raise_for_status()
    rows = [x for x in r.json().get("data", []) if x.get("trading_session") == "after_market" and x.get("close")]
    if not rows:
        return None
    last_day = max(x["date"] for x in rows)
    rows = [x for x in rows if x["date"] == last_day]
    x = max(rows, key=lambda v: v.get("volume") or 0)      # 近月合約
    prev = x["close"] - x["spread"]
    return {"date": last_day, "close": x["close"], "change": x["spread"], "pct": pct(x["close"], prev),
            "contract": x.get("contract_date")}


def monthly_revenue(cl: httpx.Client, codes: list[str]) -> dict:
    out = {}
    for u in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        try:
            for r in cl.get(u).json():
                c = r.get("公司代號")
                if c in codes:
                    out[c] = {"ym": r.get("資料年月"), "yoy_pct": round(float(r["營業收入-去年同月增減(%)"]), 1)}
        except Exception:
            continue
    return out


def disposition(cl: httpx.Client) -> list[str]:
    return sorted({x.get("Code") for x in cl.get("https://openapi.twse.com.tw/v1/announcement/punish").json() if x.get("Code")})


def news(cl: httpx.Client, now: datetime, hours: int = 18, limit: int = 12) -> list[dict]:
    lo = now - timedelta(hours=hours)
    seen, out = set(), []
    for q in ("台股", "台指期 夜盤", "美股 費半", "台積電 ADR"):
        try:
            x = cl.get("https://news.google.com/rss/search", params={"q": q + " when:2d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"}).content
            for it in ET.fromstring(x).findall(".//item"):
                d = eu.parsedate_to_datetime(it.findtext("pubDate"))
                t = it.findtext("title") or ""
                if lo <= d <= now and t[:18] not in seen:
                    seen.add(t[:18])
                    out.append({"time": d.astimezone(TPE).strftime("%m/%d %H:%M"), "title": t, "link": it.findtext("link")})
        except Exception:
            continue
    return sorted(out, key=lambda r: r["time"], reverse=True)[:limit]


def _section(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def watch_row(code: str, bars: list[dict], rev: dict, punished: set) -> dict:
    closes = [b["c"] for b in bars]
    ma200 = sma(closes, 200)
    last, prev = bars[-1], bars[-2]
    return {"code": code, "date": last["d"], "close": round(last["c"], 2), "chg_pct": pct(last["c"], prev["c"]),
            "dist_ma200_pct": pct(last["c"], ma200), "vol20_pct": realized_vol(closes),
            "rev_yoy_pct": (rev.get(code) or {}).get("yoy_pct"), "rev_ym": (rev.get(code) or {}).get("ym"),
            "disposition": code in punished}


def build(now: datetime | None = None, watch: list[str] | None = None) -> dict:
    now = now or datetime.now(TPE)
    watch = watch or DEFAULT_WATCH
    errors: dict[str, str] = {}
    snap: dict = {"schema": 1, "generated_at": now.isoformat(timespec="seconds"),
                  "phase": "premarket" if now.hour < 9 else ("intraday" if (now.hour, now.minute) < (13, 30) else "close")}
    with _client() as cl:
        # 隔夜
        overnight, sox_bars = [], []
        for sym, name in OVERNIGHT:
            bars, err = _section(yahoo_daily, cl, sym, "2y" if sym == "^SOX" else "1mo")
            if err or not bars or len(bars) < 2:
                errors[sym] = err or "no data"
                continue
            if sym == "^SOX":
                sox_bars = bars
            overnight.append({"symbol": sym, "name": name, "date": bars[-1]["d"], "close": round(bars[-1]["c"], 2),
                              "chg_pct": pct(bars[-1]["c"], bars[-2]["c"])})
        night, err = _section(night_session, cl, now.date())
        if err:
            errors["night"] = err
        snap["overnight"] = {"us": overnight, "night": night}

        # 觀察名單與 0050
        rev, err = _section(monthly_revenue, cl, watch)
        if err:
            errors["revenue"] = err
        punished, err = _section(disposition, cl)
        if err:
            errors["disposition"] = err
        rows, bars0050 = [], []
        for code in watch:
            bars, err = _section(yahoo_daily, cl, code + ".TW", "2y")
            if err or not bars or len(bars) < 2:
                errors[code] = err or "no data"
                continue
            if code == "0050":
                bars0050 = bars
            rows.append(watch_row(code, bars, rev or {}, set(punished or [])))
            time.sleep(0.3)
        snap["watchlist"] = rows
        snap["disposition_count"] = len(punished) if punished is not None else None

        # 開盤預估
        xs, ys = gap_pairs(sox_bars, bars0050) if sox_bars and bars0050 else ([], [])
        model = fit_gap_model(xs[-500:], ys[-500:])
        sox_pct = next((o["chg_pct"] for o in overnight if o["symbol"] == "^SOX"), None)
        live_night = fresh_night(night, bars0050[-1]["d"] if bars0050 else None)
        if night:
            night["fresh"] = live_night is not None
        gap = estimate_gap(live_night["pct"] if live_night else None, sox_pct, model)
        gap["model"] = model
        snap["gap_estimate"] = gap

        # 今日實際（收盤後才有意義）
        if bars0050 and bars0050[-1]["d"] == now.date().isoformat() and bars0050[-1]["o"]:
            snap["actual"] = {"date": bars0050[-1]["d"], "gap_pct": pct(bars0050[-1]["o"], bars0050[-2]["c"]),
                              "close_chg_pct": pct(bars0050[-1]["c"], bars0050[-2]["c"])}

        # 大盤風險燈
        twii, err = _section(yahoo_daily, cl, "^TWII", "2y")
        if err or not twii:
            errors["^TWII"] = err or "no data"
            snap["risk"] = risk_light(None, None, None)
        else:
            closes = [b["c"] for b in twii]
            snap["risk"] = risk_light(closes[-1], sma(closes, 200), realized_vol(closes))
            snap["risk"].update({"index_close": round(closes[-1], 2), "index_date": twii[-1]["d"]})

        snap["news"], err = _section(news, cl, now)
        if err:
            errors["news"] = err
            snap["news"] = []

    snap["conclusion"] = conclusion(snap["gap_estimate"], snap["risk"])
    snap["errors"] = errors
    return snap


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "public" / "data" / "today.json"
    snap = build()
    try:   # 命中紀錄失敗不影響快照本身
        from pipeline import history
        log = history.update(history.load(), snap)
        snap["hit_log"] = history.summarize(log)
        snap["hit_log"]["persisted"] = history.save(log)
    except Exception as e:
        snap["errors"]["hit_log"] = f"{type(e).__name__}: {str(e)[:120]}"
    core_ok = bool(snap.get("watchlist")) and snap.get("risk", {}).get("ok")
    if not core_ok:
        print("snapshot incomplete, not writing:", json.dumps(snap.get("errors"), ensure_ascii=False))
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out, "| errors:", json.dumps(snap["errors"], ensure_ascii=False))
    print(snap["conclusion"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
