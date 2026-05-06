"""
台股監測後端 V9 Stable + Firestore
- /api/stock/{stock_id}：輕量穩定查詢（不自動跑四面向）
- /api/analysis-4d/{stock_id}：按需四面向分析
- /api/stock-lite/{stock_id}：自選股卡片專用
- /api/watchlist：伺服器端備援（Firestore 為主，此為 fallback）
- AI 學習中心：weights.json + signal_history.json
- 保留 LINE 推播、AI 選股、進階回測
"""

import os, re, asyncio, json, time
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="台股監測 API V9", version="9.0-stable-firestore")

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8080,http://127.0.0.1:8080,"
    "http://localhost,http://127.0.0.1,"
    "https://taiwanstock-ben.web.app,https://taiwanstock-ben.firebaseapp.com"
)
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
if DEV_MODE: ALLOWED_ORIGINS = ["*"]

app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
    allow_credentials=not DEV_MODE, allow_methods=["GET","POST","OPTIONS"], allow_headers=["*"])

# ── LINE ─────────────────────────────────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN","")
LINE_TO_ID                = os.getenv("LINE_TO_ID","")
ENABLE_LINE_ALERTS        = os.getenv("ENABLE_LINE_ALERTS","false").lower() == "true"
LAST_ALERTS: dict[str, datetime] = {}
ALERT_COOLDOWN_MINUTES = 30

# ── 路徑 ──────────────────────────────────────────────────────────────────────
BASE_DIR            = Path(__file__).parent
WATCHLIST_FILE      = BASE_DIR / "watchlist.json"
STOCK_MASTER_FILE   = BASE_DIR / "stock_master.json"
WEIGHTS_FILE        = BASE_DIR / "weights.json"
SIGNAL_HISTORY_FILE = BASE_DIR / "signal_history.json"

FINMIND_BASE  = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL  = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

HTTP_TIMEOUT = 10  # 全局 timeout 統一 10 秒

# ── AI 選股池 ─────────────────────────────────────────────────────────────────
AI_SCAN_POOL = [
    "2330","2317","2454","2308","2382","2357","2379","3034","2303","2327",
    "2002","2412","1301","1303","1326","2886","2882","2881","2884","2891",
    "2892","2885","2883","2888","2603","2609","2615","2618","3008","3711",
    "2395","2376","2408","2344","2337","3661","3231","2356","4938","2207",
    "1216","1402","6505","0050","0056","6669","2449","1314","8422",
    "2345","2360","3005","4904","2353","2371","2385","5871","5876","5880",
    "2801","2812","2823","2836","2838","2845","2849","5841","6116",
    "2105","2201","2204","2206","2227","2231","2301","2323","2325","2332",
    "2338","2347","2352","2354","2355","2358","2388","2392","2393",
    "2404","2406","2409","2421","2423","2429",
]

# ── 股票名稱字典 fallback ──────────────────────────────────────────────────────
STOCK_NAME_MAP: dict[str, str] = {
    "2330":"台積電","2454":"聯發科","2317":"鴻海","2308":"台達電","2412":"中華電",
    "2357":"華碩","1314":"中石化","2327":"國巨","8422":"可寧衛","2881":"富邦金",
    "2882":"國泰金","2891":"中信金","2303":"聯電","2603":"長榮","3008":"大立光",
    "2382":"廣達","2379":"瑞昱","3034":"聯詠","3661":"世芯-KY","3231":"緯創",
    "2356":"英業達","4938":"和碩","1216":"統一","1301":"台塑","1303":"南亞",
    "2002":"中鋼","2207":"和泰車","0050":"元大台灣50","0056":"元大高股息",
    "2886":"兆豐金","2884":"玉山金","2885":"元大金","2892":"第一金","2883":"開發金",
    "2888":"新光金","2609":"陽明","2615":"萬海","2618":"長榮航","6505":"台塑化",
    "1326":"台化","1402":"遠東新","2395":"研華","2408":"南亞科","3711":"日月光投控",
    "2337":"旺宏","2344":"華邦電","2376":"技嘉","6669":"緯穎","2449":"京元電子",
    "2324":"仁寶","2325":"矽品","2332":"友訊","2338":"光罩","2347":"聯強",
    "2352":"佳世達","2354":"鴻準","2355":"敬鵬","2358":"廷鑫","2360":"致茂",
    "2371":"大同","2385":"群光","2388":"威盛","2392":"正崴","2393":"億光",
    "2404":"漢唐","2406":"國碩","2409":"友達","2415":"錩泰","2420":"新巨",
    "2421":"建準","2423":"固緯","2426":"鼎元","2429":"銘旺科","2431":"聯昌",
    "6182":"合晶","8240":"宏正","5871":"中租-KY","5876":"上海商銀","5880":"合庫金",
    "2801":"彰銀","2812":"台中銀","2823":"中壽","2836":"高雄銀","2838":"聯邦銀",
    "2845":"遠東銀","2849":"安泰銀","6116":"彩晶","2105":"正新","2201":"裕隆",
    "2204":"中華","2206":"三陽工業","2227":"裕日車","2231":"和泰工業",
    "2301":"光寶科","2323":"中環","2345":"智邦","2353":"宏碁","3005":"神基",
    "4904":"遠傳","5841":"合作金庫",
}

# ══════════════════════════════════════════════════════════════════════════════
# V9 AI 權重自我學習系統（完整保留自上傳版本）
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_WEIGHTS = {
    "technical": 0.35, "fundamental": 0.25, "chip": 0.25, "news": 0.15,
    "risk": 0.10, "macro": 0.05, "updated_at": "", "version": "9.0.0",
    "last_reason": "預設權重",
}
WEIGHT_LIMITS = {
    "technical": (0.20, 0.45), "fundamental": (0.10, 0.35),
    "chip": (0.10, 0.40), "news": (0.05, 0.25),
}

def _read_json_file(path: Path, default):
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except: pass
    return default

def _write_json_file(path: Path, data):
    try: path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def _normalize_weights(w: dict) -> dict:
    base = DEFAULT_WEIGHTS.copy()
    base.update({k: float(v) for k, v in (w or {}).items() if k in DEFAULT_WEIGHTS and isinstance(v, (int, float))})
    for k, (lo, hi) in WEIGHT_LIMITS.items():
        base[k] = max(lo, min(hi, float(base.get(k, DEFAULT_WEIGHTS[k]))))
    total = sum(base[k] for k in ["technical", "fundamental", "chip", "news"])
    if total <= 0: total = 1.0
    for k in ["technical", "fundamental", "chip", "news"]:
        base[k] = round(base[k] / total, 4)
    base["risk"] = float(base.get("risk", DEFAULT_WEIGHTS["risk"]))
    base["macro"] = float(base.get("macro", DEFAULT_WEIGHTS["macro"]))
    base["updated_at"] = base.get("updated_at") or ""
    return base

def load_ai_weights() -> dict:
    return _normalize_weights(_read_json_file(WEIGHTS_FILE, DEFAULT_WEIGHTS.copy()))

def save_ai_weights(weights: dict):
    weights = _normalize_weights(weights)
    weights["updated_at"] = datetime.now().isoformat()
    _write_json_file(WEIGHTS_FILE, weights)
    return weights

def load_signal_history() -> list:
    data = _read_json_file(SIGNAL_HISTORY_FILE, {"signals": []})
    if isinstance(data, list): return data
    return data.get("signals", []) if isinstance(data, dict) else []

def save_signal_history(history: list):
    _write_json_file(SIGNAL_HISTORY_FILE, {"updated_at": datetime.now().isoformat(), "signals": history[-2000:]})

def _a4_scores_for_learning(analysis_4d: dict | None) -> dict:
    a = analysis_4d or {}
    return {k: a.get(k, {}).get("score") for k in ["technical","fundamental","chip","news"]}

def record_ai_signal(stock_id: str, stock_name: str, ai: dict, analysis_4d: dict | None = None, source: str = "stock"):
    try:
        signal = ai.get("signal"); confidence = ai.get("confidence", 0) or 0
        if signal not in {"BUY","WATCH"} or confidence < 55: return
        today = datetime.now().strftime("%Y-%m-%d")
        history = load_signal_history()
        if any(x.get("stock_id") == stock_id and str(x.get("created_at","")).startswith(today) and x.get("signal") == signal for x in history): return
        item = {
            "id": f"{stock_id}_{datetime.now().isoformat(timespec='seconds')}",
            "stock_id": stock_id, "stock_name": stock_name,
            "created_at": datetime.now().isoformat(), "source": source,
            "signal": signal, "confidence": confidence,
            "entry_price": ai.get("entry_price"), "target_price": ai.get("target_price"),
            "stop_loss": ai.get("stop_loss"), "holding_days": ai.get("holding_days"),
            "scores": _a4_scores_for_learning(analysis_4d),
            "weights_at_time": {k: load_ai_weights()[k] for k in ["technical","fundamental","chip","news"]},
            "evaluated": False, "result": None,
        }
        history.append(item); save_signal_history(history)
    except: pass

def _learning_stats(history: list) -> dict:
    evaluated = [x for x in history if x.get("evaluated") and x.get("result")]
    last30 = evaluated[-30:]
    winrate30 = round(sum(1 for x in last30 if x.get("result",{}).get("success")) / len(last30) * 100, 1) if last30 else 0
    return {"total": len(history), "evaluated": len(evaluated), "pending": len(history) - len(evaluated), "winrate_30": winrate30}

async def evaluate_signal_history() -> dict:
    history = load_signal_history(); updated = 0; errors = []; now = datetime.now()
    for item in history:
        if item.get("evaluated"): continue
        try: created = datetime.fromisoformat(str(item.get("created_at","")).replace("Z",""))
        except: continue
        if (now - created).days < 5: continue
        stock_id = item.get("stock_id"); entry = item.get("entry_price") or 0
        if not stock_id or not entry: continue
        try:
            df, _ = await fetch_price_with_fallback(stock_id, lookback_days=40)
            if df.empty: continue
            df = df[df["日期"] >= pd.to_datetime(created.date())].head(10)
            if df.empty: continue
            closes = pd.to_numeric(df["收盤價"], errors="coerce").dropna()
            highs  = pd.to_numeric(df.get("最高價", df["收盤價"]), errors="coerce").dropna()
            lows   = pd.to_numeric(df.get("最低價", df["收盤價"]), errors="coerce").dropna()
            if closes.empty: continue
            max_return   = round((highs.max() - entry) / entry * 100, 2) if not highs.empty else 0
            min_return   = round((lows.min()  - entry) / entry * 100, 2) if not lows.empty else 0
            final_return = round((closes.iloc[-1] - entry) / entry * 100, 2)
            target = item.get("target_price"); stop = item.get("stop_loss")
            hit_target = bool(target and not highs.empty and highs.max() >= target)
            hit_stop   = bool(stop   and not lows.empty  and lows.min() <= stop)
            success = (hit_target or final_return > 2) and not hit_stop if item.get("signal") == "BUY" else final_return > 0
            item["evaluated"] = True; item["evaluated_at"] = now.isoformat()
            item["result"] = {"max_return_pct": max_return, "min_return_pct": min_return,
                              "final_return_pct": final_return, "hit_target": hit_target,
                              "hit_stop": hit_stop, "success": success}
            updated += 1
        except Exception as e: errors.append({"stock_id": stock_id, "error": str(e)})
    save_signal_history(history)
    return {"updated": updated, "errors": errors[:20], "stats": _learning_stats(history)}

def retrain_ai_weights() -> dict:
    history = load_signal_history()
    evaluated = [x for x in history if x.get("evaluated") and x.get("result")]
    if len(evaluated) < 30:
        return {"updated": False, "message": "樣本不足，至少需要 30 筆已評估訊號", "sample_count": len(evaluated), "weights": load_ai_weights()}
    success = [x for x in evaluated if x.get("result",{}).get("success")]
    fail    = [x for x in evaluated if not x.get("result",{}).get("success")]
    if not success or not fail:
        return {"updated": False, "message": "成功或失敗樣本不足，暫不調整", "sample_count": len(evaluated), "weights": load_ai_weights()}
    weights = load_ai_weights(); old = {k: weights[k] for k in ["technical","fundamental","chip","news"]}
    deltas = {k: 0.0 for k in old}; reasons = []
    for k in old:
        sv = [x.get("scores",{}).get(k) for x in success if x.get("scores",{}).get(k) is not None]
        fv = [x.get("scores",{}).get(k) for x in fail    if x.get("scores",{}).get(k) is not None]
        if len(sv) < 5 or len(fv) < 5: continue
        diff = sum(sv)/len(sv) - sum(fv)/len(fv)
        if diff >= 5:   deltas[k] = 0.02;  reasons.append(f"{k} 成功樣本高出 {diff:.1f}，+2%")
        elif diff <= -5: deltas[k] = -0.02; reasons.append(f"{k} 失敗樣本偏高 {abs(diff):.1f}，-2%")
    if not any(deltas.values()):
        return {"updated": False, "message": "本次樣本沒有明顯調整訊號", "sample_count": len(evaluated), "weights": weights}
    for k, d in deltas.items():
        lo, hi = WEIGHT_LIMITS[k]; weights[k] = max(lo, min(hi, weights[k] + d))
    weights["last_reason"] = "；".join(reasons)
    weights = save_ai_weights(weights)
    return {"updated": True, "sample_count": len(evaluated), "old_weights": old,
            "new_weights": {k: weights[k] for k in old}, "deltas": deltas, "reasons": reasons, "weights": weights}

# ══════════════════════════════════════════════════════════════════════════════
# 全市場股票主檔
# ══════════════════════════════════════════════════════════════════════════════
STOCK_MASTER: dict[str, dict] = {}
_master_updated_at = ""
_master_loading = False

def _load_master_from_file() -> bool:
    global STOCK_MASTER, _master_updated_at
    try:
        if STOCK_MASTER_FILE.exists():
            d = json.loads(STOCK_MASTER_FILE.read_text(encoding="utf-8"))
            STOCK_MASTER = d.get("stocks", {}); _master_updated_at = d.get("updated_at","")
            return bool(STOCK_MASTER)
    except: pass
    return False

def _save_master_to_file():
    try: STOCK_MASTER_FILE.write_text(json.dumps({"updated_at": datetime.now().isoformat(), "stocks": STOCK_MASTER}, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def _is_master_stale() -> bool:
    if not _master_updated_at: return True
    try: return (datetime.now() - datetime.fromisoformat(_master_updated_at)).total_seconds() > 86400
    except: return True

async def fetch_stock_master_list():
    global STOCK_MASTER, _master_updated_at, _master_loading
    if _master_loading: return
    _master_loading = True
    master: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for url, market in [
                ("https://www.twse.com.tw/rwd/zh/api/basic?type=MS&response=json","tse"),
                ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L","tse"),
            ]:
                if master: break
                try:
                    r = await client.get(url)
                    if r.status_code != 200: continue
                    rows = r.json() if "openapi" in url else r.json().get("data",[])
                    for row in rows:
                        if isinstance(row, list) and len(row) >= 2: sid, name = str(row[0]).strip(), str(row[1]).strip()
                        elif isinstance(row, dict):
                            sid  = str(row.get("公司代號","") or row.get("有價證券代號","")).strip()
                            name = str(row.get("公司簡稱","") or row.get("有價證券名稱","")).strip()
                        else: continue
                        if re.match(r"^\d{4,6}$", sid) and name: master[sid] = {"name": name, "market": "tse"}
                except: pass
            for url in ["https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_information",
                        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]:
                try:
                    r = await client.get(url)
                    if r.status_code != 200: continue
                    for row in r.json():
                        sid  = str(row.get("SecuritiesCompanyCode","") or row.get("公司代號","")).strip()
                        name = str(row.get("CompanyName","") or row.get("公司簡稱","")).strip()
                        if re.match(r"^\d{4,6}$", sid) and name and sid not in master:
                            master[sid] = {"name": name, "market": "otc"}
                except: pass
    except: pass
    for sid, name in STOCK_NAME_MAP.items():
        if sid not in master: master[sid] = {"name": name, "market": "tse"}
    if master: STOCK_MASTER.update(master); _master_updated_at = datetime.now().isoformat(); _save_master_to_file()
    _master_loading = False

def get_stock_name(stock_id: str, api_name: str | None = None) -> str:
    cleaned = str(api_name).strip() if api_name else ""
    if cleaned and cleaned != stock_id: return cleaned
    if stock_id in STOCK_MASTER: return STOCK_MASTER[stock_id]["name"]
    return STOCK_NAME_MAP.get(stock_id, stock_id)

# ══════════════════════════════════════════════════════════════════════════════
# 自選股（伺服器端備援，Firestore 為主）
# ══════════════════════════════════════════════════════════════════════════════
def _normalize_wl(raw: list) -> list[dict]:
    result, seen = [], set()
    for item in raw:
        if isinstance(item, str):
            sid = item.strip()
            if sid and sid not in seen: seen.add(sid); result.append({"stock_id": sid, "stock_name": get_stock_name(sid)})
        elif isinstance(item, dict):
            sid = str(item.get("stock_id","")).strip()
            if sid and sid not in seen:
                seen.add(sid); result.append({"stock_id": sid, "stock_name": item.get("stock_name") or get_stock_name(sid)})
    return result

def _read_watchlist() -> list[dict]:
    try:
        if WATCHLIST_FILE.exists():
            return _normalize_wl(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("watchlist",[]))
    except: pass
    return []

def _write_watchlist(items: list[dict]):
    try: WATCHLIST_FILE.write_text(json.dumps({"watchlist": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

class WatchlistUpdateBody(BaseModel): watchlist: list
class WatchlistBody(BaseModel): watchlist: list[str]

# ── 關鍵字 ────────────────────────────────────────────────────────────────────
BULLISH_KW = ["獲利","營收成長","突破","漲停","利多","買超","法人買","創新高",
    "增資","配息","配股","股利","超預期","優於預期","轉盈","擴廠",
    "新訂單","拿下訂單","合作","策略聯盟","上調目標價","買進評等"]
BEARISH_KW = ["虧損","營收衰退","跌停","利空","賣超","法人賣","創新低",
    "減資","下調目標價","賣出評等","警示","財務危機","停工",
    "違約","下修","低於預期","遭罰","裁員","關廠"]
RISK_KEYWORDS = ["下修","虧損","違約","裁員","調查","警示","停工","財務危機","關廠","遭罰"]

def score_sentiment(text: str) -> str:
    b = sum(1 for kw in BULLISH_KW if kw in text)
    e = sum(1 for kw in BEARISH_KW if kw in text)
    return "利多" if b > e else "利空" if e > b else "中性"

# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════
def calc_rsi(s: pd.Series, p=14) -> pd.Series:
    d = s.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/p, min_periods=p).mean(); al = l.ewm(alpha=1/p, min_periods=p).mean()
    return 100 - (100 / (1 + ag / al.replace(0, np.nan)))

def calc_macd(s: pd.Series, fast=12, slow=26, signal=9):
    ef = s.ewm(span=fast, adjust=False).mean(); es = s.ewm(span=slow, adjust=False).mean()
    m = ef - es; sig = m.ewm(span=signal, adjust=False).mean()
    return m, sig, m - sig

def _f(v, d=2): return round(float(v), d) if pd.notna(v) else None

def _num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(",","")
    if not s or s in {"-","--","－","null","None"}: return None
    if "_" in s:
        for p in s.split("_"):
            n = _num(p)
            if n is not None: return n
        return None
    try: return float(s)
    except: return None

def _int_num(v): n = _num(v); return int(n) if n is not None else 0

def _quote_time(d, t):
    d = (d or "").strip(); t = (t or "").strip()
    if len(d) == 8 and d.isdigit(): return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t}".strip()
    return f"{d} {t}".strip() or None

def _make_empty_df():
    return pd.DataFrame(columns=["日期","成交股數","開盤價","最高價","最低價","收盤價"])

# ══════════════════════════════════════════════════════════════════════════════
# 即時報價（TWSE MIS 優先）
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_realtime_quote(stock_id: str) -> dict | None:
    ts = int(datetime.now().timestamp() * 1000)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=headers, follow_redirects=True) as client:
            for mkt in ("tse", "otc"):
                try:
                    r = await client.get(TWSE_MIS_URL, params={"ex_ch": f"{mkt}_{stock_id}.tw", "json":"1", "delay":"0", "_": str(ts)})
                    arr = r.json().get("msgArray") or []
                    if not arr: continue
                    q = arr[0]
                    price = _num(q.get("z")) or _num(q.get("a")) or _num(q.get("b"))
                    prev  = _num(q.get("y"))
                    change = round(price - prev, 2) if price and prev else None
                    chg_pct = round(change / prev * 100, 2) if change and prev else None
                    return {"stock_id": str(q.get("c") or stock_id), "stock_name": get_stock_name(stock_id, q.get("n")),
                            "market": mkt, "realtime": price is not None, "price": price,
                            "open": _num(q.get("o")), "high": _num(q.get("h")), "low": _num(q.get("l")),
                            "previous_close": prev, "change": change, "change_pct": chg_pct,
                            "volume": _int_num(q.get("v")), "quote_time": _quote_time(q.get("d"), q.get("t")),
                            "source": "TWSE MIS", "note": "盤中即時或延遲報價"}
                except: continue
    except: pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
# 歷史股價：Yahoo → TWSE → FinMind（V9 優先順序）
# ══════════════════════════════════════════════════════════════════════════════
def _parse_raw_to_df(rows):
    raw = pd.DataFrame(rows); df = pd.DataFrame()
    df["日期"]   = pd.to_datetime(raw.get("date"),           errors="coerce")
    df["成交股數"] = pd.to_numeric(raw.get("Trading_Volume"), errors="coerce")
    df["開盤價"]  = pd.to_numeric(raw.get("open"),           errors="coerce")
    df["最高價"]  = pd.to_numeric(raw.get("max"),            errors="coerce")
    df["最低價"]  = pd.to_numeric(raw.get("min"),            errors="coerce")
    df["收盤價"]  = pd.to_numeric(raw.get("close"),          errors="coerce")
    return df.dropna(subset=["日期","收盤價"]).sort_values("日期").reset_index(drop=True)

async def _fetch_from_yahoo(stock_id, lookback_days, client):
    p2 = int(datetime.now().timestamp())
    p1 = int((datetime.now() - timedelta(days=lookback_days)).timestamp())
    for sfx in (".TW", ".TWO"):
        try:
            r = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{sfx}"
                f"?period1={p1}&period2={p2}&interval=1d&events=history",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=HTTP_TIMEOUT, follow_redirects=True)
            if r.status_code != 200: continue
            res = r.json().get("chart", {}).get("result")
            if not res: continue
            res = res[0]; ts_a = res.get("timestamp",[])
            q = res.get("indicators",{}).get("quote",[{}])[0]
            o, h, l, c, v = q.get("open",[]), q.get("high",[]), q.get("low",[]), q.get("close",[]), q.get("volume",[])
            if not ts_a or not c: continue
            recs = [{"日期": pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Taipei").date(),
                     "成交股數": (v[i] if i<len(v) else 0) or 0,
                     "開盤價": o[i] if i<len(o) else c[i], "最高價": h[i] if i<len(h) else c[i],
                     "最低價": l[i] if i<len(l) else c[i], "收盤價": c[i]}
                    for i, ts in enumerate(ts_a) if i<len(c) and c[i] is not None]
            if not recs: continue
            df = pd.DataFrame(recs); df["日期"] = pd.to_datetime(df["日期"])
            return df.sort_values("日期").reset_index(drop=True)
        except: continue
    return None

async def _fetch_from_twse_official(stock_id, client):
    frames = []; today = datetime.today()
    for dm in range(3):
        dt = today - timedelta(days=30 * dm); ym = dt.strftime("%Y%m")
        try:
            r = await client.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}01&stockNo={stock_id}&response=json", timeout=HTTP_TIMEOUT)
            rows = r.json().get("data", [])
            if not rows: continue
            recs = []
            for row in rows:
                try:
                    pts = row[0].replace(",","").split("/"); yr = int(pts[0]) + 1911
                    dobj = pd.to_datetime(f"{yr}/{pts[1]}/{pts[2]}")
                    vol = int(str(row[1]).replace(",","")) if row[1] else 0
                    def _p(x): return float(str(x).replace(",","")) if x and x != "--" else None
                    op, hp, lp, cp = _p(row[3]), _p(row[4]), _p(row[5]), _p(row[6])
                    if cp is None: continue
                    recs.append({"日期":dobj,"成交股數":vol*1000,"開盤價":op or cp,"最高價":hp or cp,"最低價":lp or cp,"收盤價":cp})
                except: continue
            if recs: frames.append(pd.DataFrame(recs))
        except: continue
    if not frames: return None
    df = pd.concat(frames, ignore_index=True).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)
    return df if not df.empty else None

async def _fetch_from_finmind(stock_id, lookback_days, client):
    ed = datetime.today(); sd = ed - timedelta(days=lookback_days)
    try:
        r = await client.get(FINMIND_BASE, params={"dataset":"TaiwanStockPrice","data_id":stock_id,
            "start_date":sd.strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")}, timeout=HTTP_TIMEOUT)
        if r.status_code in (402,403,429): return None
        r.raise_for_status(); rows = r.json().get("data",[])
        if not rows: return None
        df = _parse_raw_to_df(rows); return df if not df.empty else None
    except: return None

async def fetch_price_with_fallback(stock_id: str, lookback_days: int = 400) -> tuple[pd.DataFrame, str]:
    """V9 優先順序：Yahoo → TWSE → FinMind（FinMind 有配額限制放最後）"""
    try:
        async with httpx.AsyncClient() as client:
            df = await _fetch_from_yahoo(stock_id, lookback_days, client)
            if df is not None and not df.empty: return df, "Yahoo Finance"
            df = await _fetch_from_twse_official(stock_id, client)
            if df is not None and not df.empty: return df, "TWSE Official"
            df = await _fetch_from_finmind(stock_id, lookback_days, client)
            if df is not None and not df.empty: return df, "FinMind"
    except: pass
    return _make_empty_df(), "none"

async def _fetch_stock_name_from_api(stock_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(TWSE_NAME_URL, params={"stockNo": stock_id})
            data = r.json()
            if isinstance(data, dict):
                for key in ["data","msgArray"]:
                    arr = data.get(key)
                    if arr and isinstance(arr, list) and arr:
                        row = arr[0]
                        if isinstance(row, list) and len(row) > 1: return row[1]
                        if isinstance(row, dict): return row.get("公司名稱", row.get("Name",""))
    except: pass
    return ""

# ══════════════════════════════════════════════════════════════════════════════
# 新聞（僅供四面向分析使用）
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_news(stock_id: str, stock_name: str = "") -> list:
    query = stock_name if stock_name and stock_name != stock_id else stock_id
    items = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for url in [f"https://news.google.com/rss/search?q={query}+台股&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
                        f"https://news.google.com/rss/search?q={stock_id}&hl=zh-TW&gl=TW&ceid=TW:zh-TW"]:
                try:
                    r = await client.get(url, follow_redirects=True)
                    root = ET.fromstring(r.content)
                    for el in root.findall(".//item")[:10]:
                        title = el.findtext("title","")
                        items.append({"title":title,"link":el.findtext("link",""),
                                      "pub_date":el.findtext("pubDate",""),"sentiment":score_sentiment(title)})
                    if items: break
                except: continue
    except: pass
    seen, unique = set(), []
    for n in items:
        if n["title"] not in seen: seen.add(n["title"]); unique.append(n)
    return unique[:10]

# ══════════════════════════════════════════════════════════════════════════════
# 宏觀資料（帶快取）
# ══════════════════════════════════════════════════════════════════════════════
_macro_cache: dict = {}; _macro_ts: float = 0.0; MACRO_TTL = 300

async def fetch_macro_context() -> dict:
    global _macro_cache, _macro_ts
    if _macro_cache and (time.time() - _macro_ts) < MACRO_TTL: return _macro_cache
    result = {"usd_twd": None, "dxy": None, "risk_note": ""}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for sym, key in [("TWD=X","usd_twd"),("DX-Y.NYB","dxy")]:
                try:
                    r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d",
                        headers={"User-Agent":"Mozilla/5.0"}, follow_redirects=True)
                    if r.status_code == 200:
                        res = r.json().get("chart",{}).get("result")
                        if res:
                            closes = res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
                            valid = [c for c in closes if c is not None]
                            if valid: result[key] = round(valid[-1], 3 if key=="usd_twd" else 2)
                except: pass
    except: pass
    notes = []
    usd, dxy = result["usd_twd"], result["dxy"]
    if usd and usd > 32.0: notes.append(f"USD/TWD {usd}，匯率偏強")
    if dxy and dxy > 104:  notes.append(f"DXY {dxy}，美元指數偏強")
    result["risk_note"] = "，".join(notes) if notes else ("宏觀資料暫時無法取得" if not usd and not dxy else "宏觀環境無明顯壓力")
    _macro_cache = result; _macro_ts = time.time()
    return result

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標
# ══════════════════════════════════════════════════════════════════════════════
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    c = df["收盤價"]
    df["MA5"]  = c.rolling(5).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["RSI"]  = calc_rsi(c, 14)
    df["MACD"], df["Signal"], df["Hist"] = calc_macd(c)
    df["BB_mid"] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["BB_upper"] = df["BB_mid"] + 2 * bb_std
    df["BB_lower"] = df["BB_mid"] - 2 * bb_std
    hi = df.get("最高價", c); lo = df.get("最低價", c)
    if hi is not None and lo is not None:
        prev_c = c.shift(1)
        tr = pd.concat([hi - lo, (hi - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()
    return df

def technical_score(row: pd.Series) -> dict:
    score, reasons = 0, []
    if pd.notna(row.get("MA20")) and row["收盤價"] > row["MA20"]:
        score += 1; reasons.append("✅ 收盤價 > MA20（中線偏多）")
    else: reasons.append("❌ 收盤價 < MA20（中線偏弱）")
    if pd.notna(row.get("MA5")) and pd.notna(row.get("MA20")) and row["MA5"] > row["MA20"]:
        score += 1; reasons.append("✅ MA5 > MA20（均線多頭排列）")
    else: reasons.append("❌ MA5 < MA20（均線空頭排列）")
    if pd.notna(row.get("RSI")):
        if 40 <= row["RSI"] <= 70: score += 1; reasons.append(f"✅ RSI={row['RSI']:.1f}（健康區間）")
        elif row["RSI"] > 70: reasons.append(f"⚠️ RSI={row['RSI']:.1f}（過熱）")
        else: reasons.append(f"❌ RSI={row['RSI']:.1f}（偏弱）")
    if pd.notna(row.get("MACD")) and pd.notna(row.get("Signal")) and row["MACD"] > row["Signal"]:
        score += 1; reasons.append("✅ MACD > Signal（動能偏多）")
    else: reasons.append("❌ MACD < Signal（動能偏空）")
    if pd.notna(row.get("MA20")) and pd.notna(row.get("MA60")) and row["MA20"] > row["MA60"]:
        score += 1; reasons.append("✅ MA20 > MA60（長線向上）")
    else: reasons.append("❌ MA20 < MA60（長線向下）")
    return {"score": score, "max": 5, "reasons": reasons}

def backtest_winrate(df: pd.DataFrame) -> dict:
    if df.empty: return {"trials":0,"wins":0,"winrate":0}
    req = [c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df2 = df.dropna(subset=req) if req else df
    if len(df2) < 10: return {"trials":0,"wins":0,"winrate":0}
    cond = ((df2["收盤價"]>df2["MA20"])&(df2["MA5"]>df2["MA20"])&(df2["RSI"]>50)&(df2["MACD"]>df2["Signal"]))
    wins = trials = 0
    for idx in df2[cond].index:
        pos = df2.index.get_loc(idx)
        if pos + 5 < len(df2):
            trials += 1
            if df2.iloc[pos+5]["收盤價"] > df2.iloc[pos]["收盤價"]: wins += 1
    return {"trials":trials,"wins":wins,"winrate":round(wins/trials*100,1) if trials else 0}

def volume_analysis(df: pd.DataFrame) -> dict:
    if df.empty: return {"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False}
    avg_vol = df.tail(20)["成交股數"].mean(); latest_vol = df.iloc[-1]["成交股數"]
    ratio = round(float(latest_vol/avg_vol),2) if avg_vol and avg_vol > 0 else 1.0
    return {"latest_volume": int(latest_vol) if pd.notna(latest_vol) else 0,
            "avg_volume_20d": int(avg_vol) if pd.notna(avg_vol) else 0, "ratio":ratio,"alert":bool(ratio>=1.5)}

# ══════════════════════════════════════════════════════════════════════════════
# 四面向分析（按需，保留完整邏輯）
# ══════════════════════════════════════════════════════════════════════════════
def _score_rating(score) -> str:
    if score is None: return "資料不足"
    if score >= 70: return "強"
    if score >= 50: return "中"
    return "弱"

def _overall_rating(s) -> str:
    if s >= 80: return "強勢"
    if s >= 65: return "偏多"
    if s >= 50: return "觀望"
    return "偏弱"

def analyze_technical_4d(df: pd.DataFrame, latest: pd.Series, current_price: float) -> dict:
    reasons, risks = [], []; score = 0
    ma5  = float(latest["MA5"])  if pd.notna(latest.get("MA5"))  else None
    ma20 = float(latest["MA20"]) if pd.notna(latest.get("MA20")) else None
    ma60 = float(latest["MA60"]) if pd.notna(latest.get("MA60")) else None
    if ma20 and current_price > ma20: score += 15; reasons.append(f"收盤價站上 MA20 {ma20:.0f}")
    elif ma20: risks.append(f"收盤價低於 MA20 {ma20:.0f}")
    if ma5 and ma20 and ma5 > ma20: score += 15; reasons.append("MA5 > MA20 短線多頭")
    if ma20 and ma60 and ma20 > ma60: score += 10; reasons.append("MA20 > MA60 長線向上")
    elif ma60: risks.append("MA20 < MA60 長線偏弱")
    rsi  = float(latest["RSI"])  if pd.notna(latest.get("RSI"))  else None
    macd = float(latest["MACD"]) if pd.notna(latest.get("MACD")) else None
    sig  = float(latest["Signal"]) if pd.notna(latest.get("Signal")) else None
    hist = float(latest["Hist"]) if pd.notna(latest.get("Hist")) else None
    if rsi:
        if 45 <= rsi <= 68: score += 20; reasons.append(f"RSI {rsi:.1f} 健康區間")
        elif rsi > 75: risks.append(f"RSI {rsi:.1f} 過熱")
        elif rsi < 35: score += 5; risks.append(f"RSI {rsi:.1f} 偏弱")
        else: score += 8
    if macd and sig and macd > sig: score += 15; reasons.append("MACD 金叉")
    elif macd and sig: risks.append("MACD 死叉")
    if hist and hist > 0: score += 5; reasons.append("MACD Histogram 正值")
    bb_up  = float(latest["BB_upper"]) if pd.notna(latest.get("BB_upper")) else None
    bb_lo  = float(latest["BB_lower"]) if pd.notna(latest.get("BB_lower")) else None
    bb_mid = float(latest["BB_mid"])   if pd.notna(latest.get("BB_mid"))   else None
    if bb_up and bb_lo and bb_mid:
        bw = round((bb_up - bb_lo) / bb_mid * 100, 1)
        if current_price > bb_mid: score += 10; reasons.append(f"股價在布林中軌上方（BB {bw}%）")
        else: risks.append(f"股價在布林中軌下方（BB {bw}%）")
        if current_price < bb_lo:  score += 10; reasons.append("觸及布林下軌，可能反彈")
        if current_price > bb_up * 0.99: risks.append("接近布林上軌，追高風險")
    score = max(0, min(100, score))
    bull_cnt = sum(1 for x in [(ma5 and ma20 and ma5>ma20),(ma20 and ma60 and ma20>ma60),(macd and sig and macd>sig)] if x)
    trend = "多頭" if bull_cnt >= 3 else ("空頭" if bull_cnt == 0 else "盤整")
    recent = df.tail(20)
    support    = round(float(recent["最低價"].min()),2) if "最低價" in recent.columns and not recent.empty else None
    resistance = round(float(recent["最高價"].max()),2) if "最高價" in recent.columns and not recent.empty else None
    atr = round(float(latest["ATR"]),2) if pd.notna(latest.get("ATR")) else None
    return {"score":score,"rating":_score_rating(score),"trend":trend,"support":support,"resistance":resistance,"atr":atr,
            "bb_upper":_f(bb_up),"bb_lower":_f(bb_lo),"bb_mid":_f(bb_mid),"rsi":_f(rsi),"macd":_f(macd,4),
            "reasons":reasons[:4],"risks":risks[:3]}

async def fetch_chip_data(stock_id: str) -> dict:
    today = datetime.today()
    for delta in range(7):
        dt = (today - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dt}&selectType=ALLBUT0999&response=json")
                if r.status_code != 200: continue
                rows = r.json().get("data",[])
                if not rows: continue
                row = next((x for x in rows if str(x[0]).strip() == stock_id), None)
                if not row: continue
                def _p(x):
                    try: return int(str(x).replace(",","").replace("─","0"))
                    except: return 0
                foreign = _p(row[4]) if len(row) > 4 else 0
                trust   = _p(row[10]) if len(row) > 10 else 0
                dealer  = _p(row[14]) if len(row) > 14 else 0
                return {"date":dt,"foreign_net_buy":foreign,"investment_trust_net_buy":trust,
                        "dealer_net_buy":dealer,"three_major_total":foreign+trust+dealer,"data_available":True}
        except: continue
    return {"date":None,"foreign_net_buy":None,"investment_trust_net_buy":None,
            "dealer_net_buy":None,"three_major_total":None,"data_available":False}

async def fetch_margin_data(stock_id: str) -> dict:
    today = datetime.today()
    for delta in range(7):
        dt = (today - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={dt}&selectType=ALL&response=json")
                if r.status_code != 200: continue
                rows = r.json().get("data",[])
                row = next((x for x in rows if str(x[0]).strip() == stock_id), None)
                if not row or len(row) < 14: continue
                def _p(x):
                    try: return int(str(x).replace(",",""))
                    except: return 0
                return {"date":dt,"margin_balance":_p(row[3]),"margin_change":_p(row[4]),
                        "short_balance":_p(row[9]),"short_change":_p(row[10]),"data_available":True}
        except: continue
    return {"date":None,"margin_balance":None,"margin_change":None,"short_balance":None,"short_change":None,"data_available":False}

def analyze_chip_4d(chip: dict, margin: dict) -> dict:
    reasons, risks = [], []; score = 50
    if not chip.get("data_available") and not margin.get("data_available"):
        return {"score":None,"rating":"資料不足","foreign_net_buy":None,"investment_trust_net_buy":None,
                "dealer_net_buy":None,"three_major_total":None,"margin_change":None,"short_change":None,
                "reasons":["籌碼資料暫時無法取得"],"risks":[]}
    foreign = chip.get("foreign_net_buy") or 0; trust = chip.get("investment_trust_net_buy") or 0
    dealer  = chip.get("dealer_net_buy") or 0;  total = chip.get("three_major_total") or 0
    if chip.get("data_available"):
        if foreign > 0: score += 15; reasons.append(f"外資買超 {foreign:,} 張")
        elif foreign < 0: score -= 15; risks.append(f"外資賣超 {abs(foreign):,} 張")
        if trust > 0: score += 10; reasons.append(f"投信買超 {trust:,} 張")
        elif trust < 0: score -= 5; risks.append(f"投信賣超 {abs(trust):,} 張")
        if dealer > 0: score += 5; reasons.append(f"自營商買超 {dealer:,} 張")
        if total > 0: reasons.append(f"三大法人合計買超 {total:,} 張")
        elif total < 0: risks.append(f"三大法人合計賣超 {abs(total):,} 張")
    mc = margin.get("margin_change") or 0; sc = margin.get("short_change") or 0
    if margin.get("data_available"):
        if mc < 0: score += 5; reasons.append(f"融資減少 {abs(mc):,} 張")
        elif mc > 0: score -= 5; risks.append(f"融資增加 {mc:,} 張")
        if sc > 0: score += 5; reasons.append(f"融券增加 {sc:,} 張")
    score = max(0, min(100, score))
    return {"score":score,"rating":_score_rating(score),"foreign_net_buy":chip.get("foreign_net_buy"),
            "investment_trust_net_buy":chip.get("investment_trust_net_buy"),"dealer_net_buy":chip.get("dealer_net_buy"),
            "three_major_total":chip.get("three_major_total"),"margin_change":margin.get("margin_change"),
            "short_change":margin.get("short_change"),"reasons":reasons[:4],"risks":risks[:3]}

async def fetch_fundamental_data(stock_id: str) -> dict:
    result = {"revenue_yoy":None,"revenue_mom":None,"revenue_trend":None,"eps":None,"roe":None,
              "gross_margin":None,"operating_margin":None,"per":None,"pbr":None,"data_available":False}
    ed = datetime.today(); sd = ed - timedelta(days=365)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            try:
                r = await client.get(FINMIND_BASE, params={"dataset":"TaiwanStockMonthRevenue","data_id":stock_id,
                    "start_date":(ed-timedelta(days=120)).strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                if r.status_code not in (402,403,429) and r.status_code == 200:
                    rows = r.json().get("data",[])
                    if len(rows) >= 2:
                        rows = sorted(rows, key=lambda x: x.get("date",""))
                        lr = _num(rows[-1].get("revenue")); pr = _num(rows[-2].get("revenue"))
                        yoy = _num(rows[-1].get("year_growth_rate") or rows[-1].get("yoy"))
                        if lr and pr: result["revenue_mom"] = round((lr-pr)/pr*100,1)
                        result["revenue_yoy"] = yoy; result["revenue_trend"] = [_num(r.get("revenue")) for r in rows[-3:]]
                        result["data_available"] = True
            except: pass
            for ds, key in [("TaiwanStockPER","per"),("TaiwanStockPBR","pbr")]:
                try:
                    r = await client.get(FINMIND_BASE, params={"dataset":ds,"data_id":stock_id,
                        "start_date":(ed-timedelta(days=30)).strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                    if r.status_code == 200:
                        rows = r.json().get("data",[])
                        if rows: result[key] = _num(rows[-1].get("PER" if ds=="TaiwanStockPER" else "PBR")); result["data_available"] = True
                except: pass
            try:
                r = await client.get(FINMIND_BASE, params={"dataset":"TaiwanStockFinancialStatements","data_id":stock_id,
                    "start_date":sd.strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                if r.status_code == 200:
                    rows = r.json().get("data",[])
                    for tag, key in [("EPS","eps"),("ROE","roe"),("毛利率","gross_margin"),("營業利益率","operating_margin")]:
                        hits = [x for x in rows if tag in str(x.get("type",""))]
                        if hits: result[key] = _num(hits[-1].get("value")); result["data_available"] = True
            except: pass
    except: pass
    return result

def analyze_fundamental_4d(fund: dict) -> dict:
    reasons, risks = [], []; score = 50
    if not fund.get("data_available"):
        return {"score":None,"rating":"資料不足","revenue_yoy":None,"revenue_mom":None,"eps":None,"roe":None,
                "gross_margin":None,"operating_margin":None,"per":None,"pbr":None,
                "reasons":["基本面資料暫時無法取得（FinMind 配額）"],"risks":[]}
    yoy = fund.get("revenue_yoy")
    if yoy is not None:
        if yoy >= 20: score += 20; reasons.append(f"月營收年成長 {yoy:.1f}%（強勁）")
        elif yoy >= 5: score += 10; reasons.append(f"月營收年成長 {yoy:.1f}%")
        elif yoy < 0: score -= 10; risks.append(f"月營收年衰退 {yoy:.1f}%")
    roe = fund.get("roe")
    if roe is not None:
        if roe >= 15: score += 15; reasons.append(f"ROE {roe:.1f}%（優質）")
        elif roe >= 8: score += 8; reasons.append(f"ROE {roe:.1f}%（尚可）")
        elif roe < 0: score -= 10; risks.append(f"ROE {roe:.1f}%（虧損）")
    gm = fund.get("gross_margin")
    if gm is not None:
        if gm >= 30: score += 10; reasons.append(f"毛利率 {gm:.1f}%（高護城河）")
        elif gm < 10: risks.append(f"毛利率偏低 {gm:.1f}%")
    eps = fund.get("eps")
    if eps is not None:
        if eps > 0: score += 5; reasons.append(f"EPS {eps:.2f}元（獲利中）")
        elif eps < 0: score -= 10; risks.append(f"EPS {eps:.2f}元（虧損）")
    per = fund.get("per")
    if per is not None:
        if 10 <= per <= 25: score += 5; reasons.append(f"本益比 {per:.1f}x（合理）")
        elif per > 40: risks.append(f"本益比 {per:.1f}x（偏高）")
    score = max(0, min(100, score))
    return {"score":score,"rating":_score_rating(score),"revenue_yoy":fund.get("revenue_yoy"),
            "revenue_mom":fund.get("revenue_mom"),"eps":fund.get("eps"),"roe":fund.get("roe"),
            "gross_margin":fund.get("gross_margin"),"operating_margin":fund.get("operating_margin"),
            "per":fund.get("per"),"pbr":fund.get("pbr"),"revenue_trend":fund.get("revenue_trend"),
            "reasons":reasons[:4],"risks":risks[:3]}

def analyze_news_4d(news: list) -> dict:
    if not news:
        return {"score":50,"rating":"中性","sentiment":"中性","bullish_count":0,"bearish_count":0,"neutral_count":0,
                "top_news":[],"risk_keywords":[],"reasons":["暫無相關新聞"],"risks":[]}
    bull = sum(1 for n in news if n.get("sentiment")=="利多"); bear = sum(1 for n in news if n.get("sentiment")=="利空")
    neu  = sum(1 for n in news if n.get("sentiment")=="中性")
    risk_kws = list(dict.fromkeys([kw for kw in RISK_KEYWORDS for n in news if kw in n.get("title","")]))[:5]
    score = 50; reasons, risks = [], []
    if bull > bear: score += min(30, bull*8); reasons.append(f"利多新聞 {bull} 則，情緒偏正面")
    elif bear > bull: score -= min(30, bear*8); risks.append(f"利空新聞 {bear} 則，情緒偏負面")
    else: reasons.append(f"新聞情緒中性（利多{bull}/利空{bear}/中性{neu}）")
    if risk_kws: score -= min(20, len(risk_kws)*5); risks.append(f"偵測到風險字詞：{', '.join(risk_kws[:3])}")
    score = max(0, min(100, score))
    sentiment = "利多" if bull > bear else ("利空" if bear > bull else "中性")
    top_news = [{"title":n["title"][:60],"sentiment":n["sentiment"],"link":n.get("link","")} for n in news[:5]]
    return {"score":score,"rating":_score_rating(score),"sentiment":sentiment,"bullish_count":bull,"bearish_count":bear,
            "neutral_count":neu,"top_news":top_news,"risk_keywords":risk_kws,"reasons":reasons[:3],"risks":risks[:3]}

def compute_overall_4d(fundamental, technical, chip, news) -> dict:
    """使用 weights.json 動態權重（V9 學習系統核心）"""
    w = load_ai_weights()
    weights = {"fundamental": w["fundamental"], "technical": w["technical"], "chip": w["chip"], "news": w["news"]}
    scores  = {"fundamental": fundamental.get("score"), "technical": technical.get("score"),
               "chip": chip.get("score"), "news": news.get("score")}
    valid = [(k, v, weights[k]) for k, v in scores.items() if v is not None]
    if not valid:
        return {"overall_score":None,"rating":"資料不足","summary":"各面向資料均不足，無法評估。","weights":weights,"scores":scores}
    total_w = sum(wd for _,_,wd in valid)
    overall_score = round(sum(v*wd for _,v,wd in valid) / total_w, 1)
    parts = []
    for k, v, _ in [("fundamental",fundamental,None),("technical",technical,None),("chip",chip,None),("news",news,None)]:
        label = {"fundamental":"基本面","technical":"技術面","chip":"籌碼面","news":"消息面"}[k]
        s = v.get("score")
        parts.append(f"{label}{'偏強' if s and s>=70 else ('普通' if s and s>=50 else ('偏弱' if s else '資料不足'))}")
    action_map = {"強勢":"整體偏多，可留意入場機會。","偏多":"技術與籌碼訊號偏正，建議觀察確認後再進場。",
                  "觀望":"各面向訊號分歧，建議觀望等待更明確訊號。","偏弱":"技術或基本面存在疑慮，建議保守。"}
    rating = _overall_rating(overall_score)
    summary = "，".join(parts) + "。" + action_map.get(rating,"")
    return {"overall_score":overall_score,"rating":rating,"summary":summary,"weights":weights,"scores":scores}

# ══════════════════════════════════════════════════════════════════════════════
# 建議入場價
# ══════════════════════════════════════════════════════════════════════════════
def compute_entry_price(row: pd.Series, current_price: float, signal: str) -> float | None:
    if signal == "AVOID": return None
    ma5  = float(row["MA5"])  if pd.notna(row.get("MA5"))  else None
    ma20 = float(row["MA20"]) if pd.notna(row.get("MA20")) else None
    if signal == "BUY":
        if ma5  and current_price > ma5:  return round(ma5,  2)
        if ma20 and current_price > ma20: return round(ma20, 2)
        return round(current_price * 1.01, 2)
    if ma20 and current_price > ma20: return round(ma20, 2)
    return round(current_price, 2)

# ══════════════════════════════════════════════════════════════════════════════
# AI 訊號（輕量版，供 stock / stock-lite / scan / alerts 使用）
# ══════════════════════════════════════════════════════════════════════════════
def compute_ai_signal_lite(row: pd.Series, winrate_info: dict, current_price: float, macro: dict | None = None) -> dict:
    try:
        def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
        rsi_val  = _g("RSI"); ma5_val  = _g("MA5"); ma20_val = _g("MA20"); ma60_val = _g("MA60")
        macd_val = _g("MACD"); sig_val = _g("Signal"); hist_val = _g("Hist")
        wr = winrate_info.get("winrate",0); trials = winrate_info.get("trials",0)
        score = 0
        if ma20_val and current_price > ma20_val: score += 10
        if ma5_val and ma20_val and ma5_val > ma20_val: score += 10
        if ma20_val and ma60_val and ma20_val > ma60_val: score += 10
        if macd_val and sig_val and macd_val > sig_val: score += 10
        if hist_val and hist_val > 0: score += 5
        if rsi_val:
            if 45 <= rsi_val <= 68: score += 10
            elif rsi_val > 75: score -= 10
            elif rsi_val < 35: score -= 5
        if trials >= 5:
            if wr >= 65: score += 20
            elif wr >= 55: score += 12
            elif wr >= 45: score += 6
        risk_penalty = 0
        if rsi_val and rsi_val > 75: risk_penalty -= 8
        if rsi_val and rsi_val < 35: risk_penalty -= 4
        if ma20_val and ma20_val > 0:
            pct = (current_price - ma20_val) / ma20_val * 100
            if pct > 12: risk_penalty -= 8
        if trials < 5: risk_penalty -= 5
        macro_penalty = 0; macro = macro or {}
        if macro.get("usd_twd") and macro["usd_twd"] > 32.0: macro_penalty -= 3
        if macro.get("dxy") and macro["dxy"] > 104: macro_penalty -= 3
        final_score = max(0, min(100, score + risk_penalty + macro_penalty))
        risk_level  = "HIGH" if (risk_penalty+macro_penalty)<=-15 else "MEDIUM" if (risk_penalty+macro_penalty)<=-8 else "LOW"
        if final_score >= 75:   signal = "BUY"
        elif final_score >= 55: signal = "WATCH"
        else:                   signal = "AVOID"
        if signal == "BUY":     target_price = round(current_price * 1.06, 2)
        elif signal == "WATCH": target_price = round(current_price * 1.03, 2)
        else:                   target_price = None
        stop_loss = round(ma20_val * 0.98, 2) if ma20_val else round(current_price * 0.95, 2)
        if target_price and stop_loss and current_price > stop_loss:
            rr = round((target_price - current_price) / (current_price - stop_loss), 2)
            risk_reward_ratio = rr if rr > 0 else None
        else: risk_reward_ratio = None
        if signal == "BUY" and (risk_reward_ratio is None or risk_reward_ratio < 1.5): signal = "WATCH"
        if signal == "BUY" and wr < 50 and trials >= 5: signal = "WATCH"
        entry_price = None
        if signal != "AVOID":
            if ma5_val and current_price > ma5_val: entry_price = round(ma5_val, 2)
            elif ma20_val and current_price > ma20_val: entry_price = round(ma20_val, 2)
            else: entry_price = round(current_price, 2) if signal == "WATCH" else round(current_price * 1.01, 2)
        holding_days = "5-10 天" if wr >= 65 else ("3-5 天" if wr >= 50 else "不建議持有")
        return {"signal":signal,"confidence":final_score,"entry_price":entry_price,"target_price":target_price,
                "stop_loss":stop_loss,"holding_days":holding_days,"risk_reward_ratio":risk_reward_ratio,
                "risk_model":{"risk_level":risk_level,"final_score":final_score,"base_score":score,
                              "risk_penalty":risk_penalty,"macro_penalty":macro_penalty,"a4_bonus":0,"risk_factors":[]},
                "entry_reason":[],"risk_reason":[],"score_breakdown":{"trend":min(30,max(0,score//3)),"momentum":0,"volume":0,"backtest":0,"news":0},
                "macro_context":{"usd_twd":macro.get("usd_twd"),"dxy":macro.get("dxy"),"note":macro.get("risk_note","")},
                "summary":"技術面分析完成，四面向分析請按需載入。",
                "disclaimer":"⚠️ 本工具僅供參考，非投資建議"}
    except Exception:
        return {"signal":"WATCH","confidence":0,"entry_price":None,"target_price":None,"stop_loss":None,
                "holding_days":"不建議持有","risk_reward_ratio":None,
                "risk_model":{"risk_level":"HIGH","final_score":0},"entry_reason":[],"risk_reason":[],
                "score_breakdown":{"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
                "macro_context":{},"summary":"資料不足","disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

# ══════════════════════════════════════════════════════════════════════════════
# LINE
# ══════════════════════════════════════════════════════════════════════════════
def _line_configured(): return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID and ENABLE_LINE_ALERTS)

def _check_line_config():
    if not LINE_CHANNEL_ACCESS_TOKEN: raise HTTPException(503, detail="LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
    if not LINE_TO_ID:                raise HTTPException(503, detail="LINE_TO_ID 尚未設定")
    if not ENABLE_LINE_ALERTS:        raise HTTPException(503, detail="ENABLE_LINE_ALERTS 未設為 true")

async def send_line_message(message: str) -> dict:
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(LINE_PUSH_URL, headers=headers, json={"to":LINE_TO_ID,"messages":[{"type":"text","text":message}]})
            if r.status_code == 200: return {"success":True,"message":"LINE 訊息發送成功"}
            return {"success":False,"message":f"LINE API 錯誤：{r.status_code}"}
    except Exception as e: return {"success":False,"message":f"發送失敗：{str(e)}"}

def _build_line_message(stock_id, stock_name, ai, price):
    display = f"{stock_name} ({stock_id})" if stock_name and stock_name != stock_id else stock_id
    return (f"📈 自選股 AI 買點\n股票：{display}\n訊號：{ai['signal']}\n信心：{ai['confidence']}/100\n"
            f"即時價：{price}  建議入場：{ai.get('entry_price') or '—'}\n"
            f"目標價：{ai.get('target_price')}  止蝕：{ai.get('stop_loss')}\n"
            f"風險報酬比：{ai.get('risk_reward_ratio')}x  建議持有：{ai.get('holding_days','—')}\n\n"
            f"{ai.get('disclaimer','⚠️ 本工具僅供參考，非投資建議')}")

# ══════════════════════════════════════════════════════════════════════════════
# 進階回測
# ══════════════════════════════════════════════════════════════════════════════
def advanced_backtest(df, holding_days=5, min_score=75):
    if df.empty: return {"total_trades":0,"wins":0,"losses":0,"winrate":0,"avg_return":0,"best_return":0,"worst_return":0,"max_drawdown":0,"profit_factor":0,"trades":[]}
    df = df.copy().reset_index(drop=True); df = compute_indicators(df)
    req = [c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df  = df.dropna(subset=req) if req else df
    trades, equity, peak, max_dd = [], 1.0, 1.0, 0.0
    for i, (_, row) in enumerate(df.iterrows()):
        if i + holding_days >= len(df): break
        sc  = technical_score(row)
        vi  = {"alert":False,"ratio":1.0,"latest_volume":0,"avg_volume_20d":0}
        wi  = {"winrate":0,"trials":0,"wins":0}
        cur = float(row["收盤價"])
        ai  = compute_ai_signal_lite(row, wi, cur)
        if ai["confidence"] < min_score: continue
        ep  = float(df.iloc[i+holding_days]["收盤價"]); rp = round((ep-cur)/cur*100,2)
        trades.append({"date":row["日期"].strftime("%Y-%m-%d"),"entry_price":cur,"exit_price":ep,
                       "return_pct":rp,"win":ep>cur,"confidence":ai["confidence"],"signal":ai["signal"]})
        equity *= (1+rp/100); peak = max(peak,equity); dd=(peak-equity)/peak*100; max_dd=max(max_dd,dd)
    total=len(trades); wins=sum(1 for t in trades if t["win"])
    rets=[t["return_pct"] for t in trades]
    gain=sum(r for r in rets if r>0); loss=abs(sum(r for r in rets if r<0))
    return {"total_trades":total,"wins":wins,"losses":total-wins,
            "winrate":round(wins/total*100,1) if total else 0,
            "avg_return":round(sum(rets)/total,2) if total else 0,
            "best_return":round(max(rets),2) if rets else 0,
            "worst_return":round(min(rets),2) if rets else 0,
            "max_drawdown":round(max_dd,2),"profit_factor":round(gain/loss,2) if loss else 0,
            "trades":list(reversed(trades))[:20]}

# ══════════════════════════════════════════════════════════════════════════════
# 核心分析：輕量版（V9 /api/stock 主路徑，速度 V7 等級）
# ══════════════════════════════════════════════════════════════════════════════
async def _analyze_stock_core(stock_id: str) -> dict:
    """
    只抓：即時報價 + 歷史股價 + 技術指標 + AI signal + chart_data
    不抓：四面向、新聞、基本面、籌碼、宏觀
    """
    stock_name = get_stock_name(stock_id)
    try:
        rt = await fetch_realtime_quote(stock_id)
        if rt and rt.get("stock_name"): stock_name = rt["stock_name"]

        price_df, data_source = await fetch_price_with_fallback(stock_id, lookback_days=400)

        if price_df.empty:
            rt_price = rt.get("price") if rt else None
            return {
                "stock_id": stock_id, "stock_name": stock_name, "last_date": "N/A",
                "data_source": "none", "data_warning": "歷史股價資料暫時無法取得，僅顯示即時報價。",
                "price": {"close": rt_price, "daily_close": None, "open": None, "high": None, "low": None,
                          "change": rt.get("change") if rt else None, "change_pct": rt.get("change_pct") if rt else None,
                          "mode": "realtime" if rt_price else "unavailable"},
                "indicators": {k: None for k in ["ma5","ma20","ma60","rsi","macd","signal","hist","bb_upper","bb_lower","bb_mid"]},
                "volume": {"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False},
                "score":   {"score":0,"max":5,"reasons":["❌ 無法評估（資料不足）"]},
                "backtest":{"trials":0,"wins":0,"winrate":0},
                "conclusion": "資料不足 ⚠️", "rsi_alert": None,
                "ai_signal": compute_ai_signal_lite(pd.Series(), {"winrate":0,"trials":0,"wins":0}, rt_price or 0),
                "realtime_quote": rt, "news": [], "chart_data": [], "analysis_4d": None,
            }

        price_df  = compute_indicators(price_df)
        latest    = price_df.iloc[-1]
        prev      = price_df.iloc[-2] if len(price_df) > 1 else latest
        change    = float(latest["收盤價"] - prev["收盤價"])
        chg_pct   = round(change / float(prev["收盤價"]) * 100, 2) if float(prev["收盤價"]) else 0
        cur_price = float(rt["price"]) if rt and rt.get("price") is not None else float(latest["收盤價"])

        score_info = technical_score(latest)
        winrate    = backtest_winrate(price_df)
        vol_info   = volume_analysis(price_df)
        conclusion = "短線偏多 📈" if score_info["score"]>=4 else ("短線偏弱 📉" if score_info["score"]<=2 else "觀望 ➡️")

        rsi_val   = float(latest["RSI"]) if "RSI" in latest.index and pd.notna(latest.get("RSI")) else None
        rsi_alert = None
        if rsi_val:
            if rsi_val > 70: rsi_alert = "⚠️ RSI 過熱（>70）"
            elif rsi_val < 30: rsi_alert = "⚠️ RSI 過冷（<30）"

        ai = compute_ai_signal_lite(latest, winrate, cur_price)
        record_ai_signal(stock_id, stock_name, ai, None, source="stock")

        chart_data = []
        for _, row in price_df.tail(60).iterrows():
            chart_data.append({"date":row["日期"].strftime("%Y-%m-%d"),
                "open":_f(row.get("開盤價")),"high":_f(row.get("最高價")),"low":_f(row.get("最低價")),
                "close":_f(row.get("收盤價")),"volume":int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
                "ma5":_f(row.get("MA5")),"ma20":_f(row.get("MA20")),"ma60":_f(row.get("MA60")),
                "rsi":_f(row.get("RSI")),"macd":_f(row.get("MACD"),4),"signal":_f(row.get("Signal"),4),"hist":_f(row.get("Hist"),4),
                "bb_upper":_f(row.get("BB_upper")),"bb_lower":_f(row.get("BB_lower"))})

        return {
            "stock_id": stock_id, "stock_name": stock_name,
            "last_date": latest["日期"].strftime("%Y-%m-%d"), "data_source": data_source,
            "price": {"close":_f(cur_price),"daily_close":_f(latest["收盤價"]),
                "open": _f(rt.get("open") if rt else latest.get("開盤價")),
                "high": _f(rt.get("high") if rt else latest.get("最高價")),
                "low":  _f(rt.get("low")  if rt else latest.get("最低價")),
                "change":   (_f(rt.get("change"),2) if rt and rt.get("change") is not None else round(change,2)),
                "change_pct":(_f(rt.get("change_pct"),2) if rt and rt.get("change_pct") is not None else chg_pct),
                "mode": "realtime" if rt and rt.get("price") is not None else "daily"},
            "indicators": {"ma5":_f(latest.get("MA5")),"ma20":_f(latest.get("MA20")),"ma60":_f(latest.get("MA60")),
                "rsi":_f(latest.get("RSI")),"macd":_f(latest.get("MACD"),4),"signal":_f(latest.get("Signal"),4),
                "hist":_f(latest.get("Hist"),4),"bb_upper":_f(latest.get("BB_upper")),
                "bb_lower":_f(latest.get("BB_lower")),"bb_mid":_f(latest.get("BB_mid"))},
            "volume": vol_info, "score": score_info, "backtest": winrate,
            "conclusion": conclusion, "rsi_alert": rsi_alert,
            "ai_signal": ai, "realtime_quote": rt, "news": [], "chart_data": chart_data, "analysis_4d": None,
        }
    except Exception as e:
        return {"stock_id":stock_id,"stock_name":stock_name,"error":str(e),"chart_data":[],"analysis_4d":None}

async def _analyze_stock_lite(stock_id: str) -> dict:
    """超輕量：TWSE MIS 即時 → 90天歷史 → AI signal，不抓四面向/新聞"""
    stock_name = get_stock_name(stock_id)
    fallback_ai = {"signal":"WATCH","confidence":0,"entry_price":None,"target_price":None,"stop_loss":None,
                   "holding_days":"不建議持有","risk_reward_ratio":None,
                   "risk_model":{"risk_level":"HIGH","final_score":0},"entry_reason":[],"risk_reason":[],
                   "score_breakdown":{"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
                   "macro_context":{},"summary":"資料不足","disclaimer":"⚠️ 本工具僅供參考，非投資建議"}
    try:
        rt = await fetch_realtime_quote(stock_id)
        if rt and rt.get("stock_name"): stock_name = rt["stock_name"]
        price   = rt["price"]     if rt and rt.get("price") is not None else None
        change  = rt["change"]    if rt and rt.get("change") is not None else None
        chg_pct = rt["change_pct"] if rt and rt.get("change_pct") is not None else None
        price_df, hist_src = await fetch_price_with_fallback(stock_id, lookback_days=90)
        if price is None and not price_df.empty:
            price = float(price_df.iloc[-1]["收盤價"])
            if len(price_df) >= 2:
                prev_c = float(price_df.iloc[-2]["收盤價"])
                change  = round(price - prev_c, 2)
                chg_pct = round(change / prev_c * 100, 2) if prev_c else None
        cur_price = price or 0.0
        ai = fallback_ai.copy()
        if not price_df.empty and cur_price > 0:
            price_df = compute_indicators(price_df)
            latest   = price_df.iloc[-1]
            wr_info  = backtest_winrate(price_df)
            ai       = compute_ai_signal_lite(latest, wr_info, cur_price)
        record_ai_signal(stock_id, stock_name, ai, None, source="stock-lite")
        return {"stock_id":stock_id,"stock_name":stock_name,"price":price,"change":change,"change_pct":chg_pct,
                "realtime_quote":rt,"ai_signal":ai,"data_source":hist_src if not price_df.empty else "TWSE MIS","lite":True}
    except Exception as e:
        return {"stock_id":stock_id,"stock_name":stock_name,"price":None,"change":None,"change_pct":None,
                "realtime_quote":None,"ai_signal":fallback_ai,"data_source":"error","lite":True,"error":str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# 啟動事件
# ══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    loaded = _load_master_from_file()
    if not loaded or _is_master_stale():
        asyncio.create_task(fetch_stock_master_list())

# ══════════════════════════════════════════════════════════════════════════════
# API 端點
# ══════════════════════════════════════════════════════════════════════════════

# ── 自選股（伺服器端備援，Firestore 為主） ───────────────────────────────────
@app.get("/api/watchlist")
async def api_get_watchlist():
    items = _read_watchlist(); return {"watchlist": items, "count": len(items)}

@app.post("/api/watchlist")
async def api_post_watchlist(body: WatchlistUpdateBody):
    items = _normalize_wl(body.watchlist); _write_watchlist(items)
    return {"watchlist": items, "count": len(items), "saved": True}

# ── 股票名稱查詢 ─────────────────────────────────────────────────────────────
@app.get("/api/stocks/master")
async def api_stocks_master():
    if not STOCK_MASTER: _load_master_from_file()
    return {"count": len(STOCK_MASTER), "updated_at": _master_updated_at, "stocks": STOCK_MASTER}

@app.get("/api/stocks/search")
async def api_stocks_search(q: str = Query("", min_length=1)):
    if not STOCK_MASTER: _load_master_from_file()
    q = q.strip(); results = []
    if q in STOCK_MASTER: results.append({"stock_id":q,"stock_name":STOCK_MASTER[q]["name"],"market":STOCK_MASTER[q].get("market","")})
    for sid, info in STOCK_MASTER.items():
        if sid == q: continue
        if sid.startswith(q): results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
        if len(results) >= 20: break
    if len(results) < 20:
        for sid, info in STOCK_MASTER.items():
            if sid == q or sid.startswith(q): continue
            if q in info["name"]: results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
            if len(results) >= 20: break
    return {"results": results[:20], "query": q}

# ── 主要查詢（V9 輕量穩定，不自動跑四面向） ──────────────────────────────────
@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id): raise HTTPException(400, detail="股票代號格式錯誤，請輸入 4~6 位數字")
    return await _analyze_stock_core(stock_id)

# ── 四面向分析（按需，獨立端點） ─────────────────────────────────────────────
@app.get("/api/analysis-4d/{stock_id}")
async def get_analysis_4d(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id): raise HTTPException(400, detail="股票代號格式錯誤")
    try:
        api_name_t = asyncio.create_task(_fetch_stock_name_from_api(stock_id))
        price_df, _ = await fetch_price_with_fallback(stock_id, lookback_days=400)
        api_name = await api_name_t
        stock_name = get_stock_name(stock_id, api_name)
        if price_df.empty:
            rt = await fetch_realtime_quote(stock_id)
            cur_price = rt["price"] if rt and rt.get("price") else 0
        else:
            price_df = compute_indicators(price_df)
            rt = await fetch_realtime_quote(stock_id)
            cur_price = float(rt["price"]) if rt and rt.get("price") else float(price_df.iloc[-1]["收盤價"])
            latest = price_df.iloc[-1]

        news, fund_raw, chip_raw, margin_raw = await asyncio.gather(
            fetch_news(stock_id, stock_name),
            fetch_fundamental_data(stock_id),
            fetch_chip_data(stock_id),
            fetch_margin_data(stock_id),
        )
        if price_df.empty:
            tech_4d = {"score":None,"rating":"資料不足","reasons":[],"risks":[]}
        else:
            tech_4d = analyze_technical_4d(price_df, latest, cur_price)
        fund_4d    = analyze_fundamental_4d(fund_raw)
        chip_4d    = analyze_chip_4d(chip_raw, margin_raw)
        news_4d    = analyze_news_4d(news)
        overall_4d = compute_overall_4d(fund_4d, tech_4d, chip_4d, news_4d)
        return {
            "stock_id": stock_id, "stock_name": stock_name,
            "analysis_4d": {"fundamental":fund_4d,"technical":tech_4d,"chip":chip_4d,"news":news_4d,"overall":overall_4d},
            "news": news,
        }
    except Exception as e:
        raise HTTPException(500, detail=f"四面向分析失敗：{str(e)}")

# ── 輕量 stock-lite ──────────────────────────────────────────────────────────
@app.get("/api/stock-lite/{stock_id}")
async def get_stock_lite(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id): raise HTTPException(400, detail="股票代號格式錯誤")
    return await _analyze_stock_lite(stock_id)

# ── 即時報價 ─────────────────────────────────────────────────────────────────
@app.get("/api/realtime/{stock_id}")
async def get_realtime(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id): raise HTTPException(400, detail="股票代號格式錯誤")
    quote = await fetch_realtime_quote(stock_id)
    if not quote: raise HTTPException(404, detail="找不到即時報價")
    return quote

# ── AI 選股掃描（輕量版） ────────────────────────────────────────────────────
@app.get("/api/scan/ai")
async def ai_scan(min_score: int = Query(75, ge=0, le=100), max_stocks: int = Query(40, ge=5, le=80)):
    t0 = time.time(); pool = list(dict.fromkeys(AI_SCAN_POOL))[:max_stocks]
    results, errors = [], []
    for stock_id in pool:
        try:
            r = await _analyze_stock_lite(stock_id)
            ai = r.get("ai_signal", {})
            if ai.get("confidence", 0) < min_score: continue
            results.append({"stock_id":stock_id,"stock_name":r["stock_name"],
                "signal":ai.get("signal","WATCH"),"confidence":ai.get("confidence",0),
                "risk_level":ai.get("risk_model",{}).get("risk_level","—"),
                "price":r.get("price"),"change_pct":r.get("change_pct"),
                "entry_price":ai.get("entry_price"),"target_price":ai.get("target_price"),
                "stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),
                "summary":ai.get("summary","")})
        except Exception as e: errors.append({"stock_id":stock_id,"error":str(e)})
    rank = {"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x: (rank.get(x["signal"],0), x["confidence"]), reverse=True)
    return {"scanned":len(pool),"found":len(results),"min_score":min_score,"results":results,
            "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1),"timestamp":datetime.now().isoformat()}

# ── LINE 通知 ─────────────────────────────────────────────────────────────────
@app.post("/api/alerts/test")
async def test_line():
    _check_line_config()
    result = await send_line_message("✅ 台股監測工具 V9 Stable - LINE 通知測試成功！")
    if not result["success"]: raise HTTPException(500, detail=result["message"])
    return result

@app.post("/api/alerts/check")
async def check_alerts(body: WatchlistBody):
    t0 = time.time(); line_ok = _line_configured(); results = []; now = datetime.now(); sent_msgs = []; errors = []
    stock_ids = body.watchlist or [item["stock_id"] for item in _read_watchlist()]
    for stock_id in stock_ids:
        if not re.match(r"^\d{4,6}$", stock_id): continue
        try:
            r = await _analyze_stock_lite(stock_id)
            ai = r.get("ai_signal",{}); stock_name = r.get("stock_name", stock_id)
            cur_price = r.get("price") or 0
            results.append({"stock_id":stock_id,"stock_name":stock_name,
                "signal":ai.get("signal","AVOID"),"confidence":ai.get("confidence",0),
                "summary":ai.get("summary",""),"entry_price":ai.get("entry_price"),
                "target_price":ai.get("target_price"),"stop_loss":ai.get("stop_loss"),
                "risk_reward_ratio":ai.get("risk_reward_ratio"),
                "risk_level":ai.get("risk_model",{}).get("risk_level","—")})
            rr = ai.get("risk_reward_ratio") or 0
            if line_ok and ai.get("signal") == "BUY" and ai.get("confidence",0) >= 75 and rr >= 1.5:
                ls = LAST_ALERTS.get(stock_id)
                if ls is None or (now - ls).total_seconds() >= ALERT_COOLDOWN_MINUTES * 60:
                    res = await send_line_message(_build_line_message(stock_id, stock_name, ai, cur_price))
                    if res["success"]: LAST_ALERTS[stock_id] = now; sent_msgs.append(stock_id)
        except Exception as e: errors.append({"stock_id":stock_id,"error":str(e)})
    rank = {"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x: (rank.get(x.get("signal",""),0), x.get("confidence",0)), reverse=True)
    return {"checked":len(stock_ids),"alerts":[r for r in results if r.get("signal")=="BUY"],
            "all_results":results,"sent_line":sent_msgs,"line_enabled":line_ok,
            "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1),"timestamp":now.isoformat()}

# ── 進階回測 ─────────────────────────────────────────────────────────────────
@app.get("/api/backtest/{stock_id}")
async def run_backtest(stock_id: str, lookback_days: int = 400, holding_days: int = 5, min_score: int = 75):
    if not re.match(r"^\d{4,6}$", stock_id): raise HTTPException(400, detail="股票代號格式錯誤")
    price_df, _ = await fetch_price_with_fallback(stock_id, lookback_days)
    api_name    = await _fetch_stock_name_from_api(stock_id)
    stock_name  = get_stock_name(stock_id, api_name)
    result      = advanced_backtest(price_df, holding_days=holding_days, min_score=min_score)
    return {"stock_id":stock_id,"stock_name":stock_name,
            "params":{"lookback_days":lookback_days,"holding_days":holding_days,"min_score":min_score},
            "result":{k:v for k,v in result.items() if k!="trades"},"trades":result["trades"]}

# ── AI 學習中心 ───────────────────────────────────────────────────────────────
@app.get("/api/learning/weights")
def api_learning_weights():
    history = load_signal_history()
    return {"weights": load_ai_weights(), "stats": _learning_stats(history), "recent": list(reversed(history))[:10]}

@app.get("/api/learning/history")
def api_learning_history(limit: int = Query(100, ge=1, le=500)):
    history = load_signal_history()
    return {"count": len(history), "signals": list(reversed(history))[:limit]}

@app.get("/api/learning/evaluate")
async def api_learning_evaluate():
    return await evaluate_signal_history()

@app.post("/api/learning/retrain")
def api_learning_retrain():
    return retrain_ai_weights()

# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status":"ok","version":"9.0-stable-firestore","time":datetime.now().isoformat(),
            "dev_mode":DEV_MODE,"line_configured":bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
            "line_enabled":ENABLE_LINE_ALERTS,"realtime_source":"TWSE MIS",
            "price_sources":"Yahoo Finance → TWSE Official → FinMind",
            "stock_master_count":len(STOCK_MASTER),"stock_master_updated":_master_updated_at,
            "http_timeout":HTTP_TIMEOUT,
            "features":["V9 stable core","Firestore watchlist","4D on-demand","AI learning","stock-lite","AI scan"]}
