"""
台股監測後端 V5
新增：股票名稱字典、加權 AI 評分引擎（score_breakdown）、
     /api/alerts/check 改為 LINE 未設定時回傳結果而非拋錯
資料來源：FinMind API（免費）、TWSE Open API（免費）、Google News RSS
"""

import os
import re
import asyncio
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="台股監測 API", version="5.0.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8080,http://127.0.0.1:8080,"
    "http://localhost,http://127.0.0.1,"
    "https://taiwanstock-ben.web.app,https://taiwanstock-ben.firebaseapp.com"
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
if DEV_MODE:
    ALLOWED_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=not DEV_MODE,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── LINE 設定（環境變數，絕不寫死）───────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TO_ID                = os.getenv("LINE_TO_ID", "")
ENABLE_LINE_ALERTS        = os.getenv("ENABLE_LINE_ALERTS", "false").lower() == "true"

# ── 重複通知防護 ────────────────────────────────────────────────────────────────
LAST_ALERTS: dict[str, datetime] = {}
ALERT_COOLDOWN_MINUTES = 30

# ── 常數 ──────────────────────────────────────────────────────────────────────
FINMIND_BASE  = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL  = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
TIMEOUT = 25

# ── ★ 股票名稱字典（API 抓不到時的 fallback）────────────────────────────────
STOCK_NAME_MAP: dict[str, str] = {
    "2330": "台積電",  "2454": "聯發科",  "2317": "鴻海",
    "2308": "台達電",  "2412": "中華電",  "2357": "華碩",
    "1314": "中石化",  "2327": "國巨",    "8422": "可寧衛",
    "2881": "富邦金",  "2882": "國泰金",  "2891": "中信金",
    "2303": "聯電",    "2603": "長榮",    "3008": "大立光",
    "2382": "廣達",    "2379": "瑞昱",    "3034": "聯詠",
    "3661": "世芯-KY", "3231": "緯創",    "2356": "英業達",
    "4938": "和碩",    "1216": "統一",    "1301": "台塑",
    "1303": "南亞",    "2002": "中鋼",    "2207": "和泰車",
    "0050": "元大台灣50", "0056": "元大高股息",
    "2886": "兆豐金",  "2884": "玉山金",  "2885": "元大金",
    "2892": "第一金",  "2883": "開發金",  "2888": "新光金",
    "2609": "陽明",    "2615": "萬海",    "2618": "長榮航",
    "6505": "台塑化",  "1326": "台化",    "1402": "遠東新",
    "2395": "研華",    "2408": "南亞科",  "3711": "日月光投控",
    "2337": "旺宏",    "2344": "華邦電",  "2376": "技嘉",
}


def get_stock_name(stock_id: str, api_name: str | None = None) -> str:
    """
    優先使用 API 回傳名稱；若為空或等於股票代號，改用字典；
    字典也沒有，則直接回傳代號。
    """
    cleaned = str(api_name).strip() if api_name else ""
    if cleaned and cleaned != stock_id:
        return cleaned
    return STOCK_NAME_MAP.get(stock_id, stock_id)


# ── 關鍵字 ────────────────────────────────────────────────────────────────────
BULLISH_KEYWORDS = [
    "獲利", "營收成長", "突破", "漲停", "利多", "買超", "法人買", "創新高",
    "增資", "配息", "配股", "股利", "超預期", "優於預期", "轉盈", "擴廠",
    "新訂單", "拿下訂單", "合作", "策略聯盟", "上調目標價", "買進評等",
]
BEARISH_KEYWORDS = [
    "虧損", "營收衰退", "跌停", "利空", "賣超", "法人賣", "創新低",
    "減資", "下調目標價", "賣出評等", "警示", "財務危機", "停工",
    "違約", "下修", "低於預期", "遭罰", "裁員", "關廠",
]

# ── Pydantic ───────────────────────────────────────────────────────────────────
class WatchlistBody(BaseModel):
    watchlist: list[str]

# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast    = series.ewm(span=fast, adjust=False).mean()
    ema_slow    = series.ewm(span=slow, adjust=False).mean()
    macd        = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def score_sentiment(text: str) -> str:
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    if bull > bear: return "利多"
    if bear > bull: return "利空"
    return "中性"


def _f(v, d=2):
    return round(float(v), d) if pd.notna(v) else None

# ══════════════════════════════════════════════════════════════════════════════
# TWSE MIS 即時報價
# ══════════════════════════════════════════════════════════════════════════════

def _num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(',', '')
    if not s or s in {'-', '--', '－', 'null', 'None'}: return None
    if '_' in s:
        for part in s.split('_'):
            n = _num(part)
            if n is not None: return n
        return None
    try: return float(s)
    except: return None

def _int_num(v):
    n = _num(v)
    return int(n) if n is not None else 0

def _quote_time(d, t):
    d = (d or '').strip(); t = (t or '').strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t}".strip()
    return f"{d} {t}".strip() or None

async def fetch_realtime_quote(stock_id: str) -> dict | None:
    ts      = int(datetime.now().timestamp() * 1000)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        for market in ("tse", "otc"):
            params = {"ex_ch": f"{market}_{stock_id}.tw", "json": "1", "delay": "0", "_": str(ts)}
            try:
                r    = await client.get(TWSE_MIS_URL, params=params)
                data = r.json()
                arr  = data.get("msgArray") or []
                if not arr: continue
                q        = arr[0]
                price    = _num(q.get("z")) or _num(q.get("a")) or _num(q.get("b"))
                prev     = _num(q.get("y"))
                open_    = _num(q.get("o"))
                high     = _num(q.get("h"))
                low      = _num(q.get("l"))
                change   = round(price - prev, 2) if price is not None and prev else None
                chg_pct  = round(change / prev * 100, 2) if change is not None and prev else None
                rt_name  = get_stock_name(stock_id, q.get("n"))
                return {
                    "stock_id":       str(q.get("c") or stock_id),
                    "stock_name":     rt_name,
                    "market":         market,
                    "realtime":       price is not None,
                    "price":          price,
                    "open":           open_,
                    "high":           high,
                    "low":            low,
                    "previous_close": prev,
                    "change":         change,
                    "change_pct":     chg_pct,
                    "volume":         _int_num(q.get("v")),
                    "quote_time":     _quote_time(q.get("d"), q.get("t")),
                    "source":         "TWSE MIS",
                    "note":           "盤中即時或延遲報價；若休市則可能顯示最後可用資料。",
                }
            except Exception:
                continue
    return None

# ══════════════════════════════════════════════════════════════════════════════
# 資料抓取
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_twse_price(stock_id: str, lookback_days: int = 400) -> pd.DataFrame:
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    params = {
        "dataset":    "TaiwanStockPrice",
        "data_id":    stock_id,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date":   end_date.strftime("%Y-%m-%d"),
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r    = await client.get(FINMIND_BASE, params=params)
            r.raise_for_status()
            data = r.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="股價 API 逾時，請稍後再試")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"股價資料來源連線失敗：{e}")

    rows = data.get("data", [])
    if not rows:
        raise HTTPException(status_code=404, detail=f"找不到股票代號 {stock_id} 的資料，請確認是否為上市股票")

    raw = pd.DataFrame(rows)
    df  = pd.DataFrame()
    df["日期"]   = pd.to_datetime(raw.get("date"),           errors="coerce")
    df["成交股數"] = pd.to_numeric(raw.get("Trading_Volume"), errors="coerce")
    df["開盤價"]  = pd.to_numeric(raw.get("open"),           errors="coerce")
    df["最高價"]  = pd.to_numeric(raw.get("max"),            errors="coerce")
    df["最低價"]  = pd.to_numeric(raw.get("min"),            errors="coerce")
    df["收盤價"]  = pd.to_numeric(raw.get("close"),          errors="coerce")
    df = df.dropna(subset=["日期", "收盤價"]).sort_values("日期").reset_index(drop=True)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"股票 {stock_id} 無有效股價資料")
    return df


async def _fetch_stock_name_from_api(stock_id: str) -> str:
    """從 TWSE 網頁 API 抓股票名稱（原 fetch_stock_name，改為私有）。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r    = await client.get(TWSE_NAME_URL, params={"stockNo": stock_id})
            data = r.json()
            if isinstance(data, dict):
                for key in ["data", "msgArray"]:
                    arr = data.get(key)
                    if arr and isinstance(arr, list) and arr:
                        row = arr[0]
                        if isinstance(row, list) and len(row) > 1:  return row[1]
                        if isinstance(row, dict):
                            return row.get("公司名稱", row.get("Name", ""))
    except Exception:
        pass
    return ""

async def fetch_stock_name(stock_id: str) -> str:
    """公開函式：先查 API，再用字典 fallback。"""
    api_name = await _fetch_stock_name_from_api(stock_id)
    return get_stock_name(stock_id, api_name)


async def fetch_news(stock_id: str, stock_name: str = "") -> list:
    # 避免用代號當查詢詞（若名稱等於代號）
    query = stock_name if stock_name and stock_name != stock_id else stock_id
    urls  = [
        f"https://news.google.com/rss/search?q={query}+台股&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
        f"https://news.google.com/rss/search?q={stock_id}&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
    ]
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for url in urls:
            try:
                r    = await client.get(url, follow_redirects=True)
                root = ET.fromstring(r.content)
                for el in root.findall(".//item")[:8]:
                    title = el.findtext("title", "")
                    items.append({
                        "title":     title,
                        "link":      el.findtext("link", ""),
                        "pub_date":  el.findtext("pubDate", ""),
                        "sentiment": score_sentiment(title),
                    })
                if items: break
            except Exception:
                continue
    seen, unique = set(), []
    for n in items:
        if n["title"] not in seen:
            seen.add(n["title"]); unique.append(n)
    return unique[:10]

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["收盤價"]
    df["MA5"]  = c.rolling(5).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["RSI"]  = calc_rsi(c, 14)
    df["MACD"], df["Signal"], df["Hist"] = calc_macd(c)
    return df


def technical_score(row: pd.Series) -> dict:
    score, reasons = 0, []
    if pd.notna(row["MA20"]) and row["收盤價"] > row["MA20"]:
        score += 1; reasons.append("✅ 收盤價 > MA20（中線偏多）")
    else:
        reasons.append("❌ 收盤價 < MA20（中線偏弱）")
    if pd.notna(row["MA5"]) and pd.notna(row["MA20"]) and row["MA5"] > row["MA20"]:
        score += 1; reasons.append("✅ MA5 > MA20（均線多頭排列）")
    else:
        reasons.append("❌ MA5 < MA20（均線空頭排列）")
    if pd.notna(row["RSI"]):
        if 40 <= row["RSI"] <= 70:
            score += 1; reasons.append(f"✅ RSI={row['RSI']:.1f}（健康區間 40~70）")
        elif row["RSI"] > 70:
            reasons.append(f"⚠️ RSI={row['RSI']:.1f}（過熱 >70）")
        else:
            reasons.append(f"❌ RSI={row['RSI']:.1f}（偏弱 <40）")
    if pd.notna(row["MACD"]) and pd.notna(row["Signal"]) and row["MACD"] > row["Signal"]:
        score += 1; reasons.append("✅ MACD > Signal（動能偏多）")
    else:
        reasons.append("❌ MACD < Signal（動能偏空）")
    if pd.notna(row["MA20"]) and pd.notna(row["MA60"]) and row["MA20"] > row["MA60"]:
        score += 1; reasons.append("✅ MA20 > MA60（長線趨勢向上）")
    else:
        reasons.append("❌ MA20 < MA60（長線趨勢向下）")
    return {"score": score, "max": 5, "reasons": reasons}


def backtest_winrate(df: pd.DataFrame) -> dict:
    df = df.dropna(subset=["MA5", "MA20", "MA60", "RSI", "MACD", "Signal"])
    if len(df) < 10:
        return {"trials": 0, "wins": 0, "winrate": 0}
    cond = (
        (df["收盤價"] > df["MA20"]) & (df["MA5"] > df["MA20"]) &
        (df["RSI"]   > 50)          & (df["MACD"] > df["Signal"])
    )
    wins = trials = 0
    for idx in df[cond].index:
        pos = df.index.get_loc(idx)
        if pos + 5 < len(df):
            trials += 1
            if df.iloc[pos + 5]["收盤價"] > df.iloc[pos]["收盤價"]:
                wins += 1
    return {"trials": trials, "wins": wins, "winrate": round(wins / trials * 100, 1) if trials else 0}


def volume_analysis(df: pd.DataFrame) -> dict:
    avg_vol    = df.tail(20)["成交股數"].mean()
    latest_vol = df.iloc[-1]["成交股數"]
    ratio      = round(float(latest_vol / avg_vol), 2) if avg_vol else 1.0
    return {
        "latest_volume":  int(latest_vol) if pd.notna(latest_vol) else 0,
        "avg_volume_20d": int(avg_vol)    if pd.notna(avg_vol)    else 0,
        "ratio":          ratio,
        "alert":          bool(ratio >= 1.5),
    }

# ══════════════════════════════════════════════════════════════════════════════
# ★ 加權 AI 策略評分引擎 V5（滿分 100，分五維度）
# ══════════════════════════════════════════════════════════════════════════════

def compute_ai_signal(
    score_info:   dict,
    row:          pd.Series,
    vol_info:     dict,
    winrate_info: dict,
    news:         list,
    current_price: float,
) -> dict:
    """
    加權評分：趨勢 30 + 動能 25 + 量能 15 + 回測 20 + 新聞 10 = 100
    """
    entry_reason: list[str] = []
    risk_reason:  list[str] = []

    # ── 取值 ─────────────────────────────────────────────────────────────────
    rsi_val  = float(row["RSI"])    if pd.notna(row["RSI"])    else None
    ma5_val  = float(row["MA5"])    if pd.notna(row["MA5"])    else None
    ma20_val = float(row["MA20"])   if pd.notna(row["MA20"])   else None
    ma60_val = float(row["MA60"])   if pd.notna(row["MA60"])   else None
    macd_val = float(row["MACD"])   if pd.notna(row["MACD"])   else None
    sig_val  = float(row["Signal"]) if pd.notna(row["Signal"]) else None
    hist_val = float(row["Hist"])   if pd.notna(row["Hist"])   else None

    # ══ 1. 趨勢 Trend：30 分 ════════════════════════════════════════════════
    trend = 0
    if ma20_val and current_price > ma20_val:
        trend += 10; entry_reason.append("收盤價站上 MA20（+10）")
    if ma5_val and ma20_val and ma5_val > ma20_val:
        trend += 10; entry_reason.append("MA5 > MA20 均線多頭（+10）")
    if ma20_val and ma60_val and ma20_val > ma60_val:
        trend += 10; entry_reason.append("MA20 > MA60 長線向上（+10）")

    # ══ 2. 動能 Momentum：25 分 ════════════════════════════════════════════
    momentum = 0
    if macd_val is not None and sig_val is not None and macd_val > sig_val:
        momentum += 10; entry_reason.append("MACD > Signal 動能偏多（+10）")
    if hist_val is not None and hist_val > 0:
        momentum += 5; entry_reason.append("MACD Histogram > 0（+5）")
    if rsi_val is not None:
        if 45 <= rsi_val <= 68:
            momentum += 10; entry_reason.append(f"RSI={rsi_val:.1f} 健康區間（+10）")
        elif rsi_val > 75:
            momentum -= 10; risk_reason.append(f"RSI={rsi_val:.1f} 過熱，追高風險增加（-10）")
        elif rsi_val < 35:
            momentum -= 5;  risk_reason.append(f"RSI={rsi_val:.1f} 偏弱（-5）")

    # ══ 3. 量能 Volume：15 分 ══════════════════════════════════════════════
    volume = 0
    ratio  = vol_info.get("ratio", 1.0)
    if ratio >= 1.8 and rsi_val is not None and rsi_val > 70:
        volume -= 5; risk_reason.append(f"放量（{ratio}x）但 RSI 偏高，可能短線過熱（-5）")
    elif ratio >= 1.2:
        volume += 8; entry_reason.append(f"成交量 {ratio}x 均量，主力動能增強（+8）")
        if ma20_val and current_price > ma20_val:
            volume += 5; entry_reason.append("量增且站上 MA20（+5）")
        volume = min(volume, 15)   # 本維度上限 15
    elif ma20_val and current_price > ma20_val:
        volume += 5; entry_reason.append("量能正常且價格站上 MA20（+5）")

    # ══ 4. 回測 Backtest：20 分 ════════════════════════════════════════════
    wr      = winrate_info.get("winrate", 0)
    trials  = winrate_info.get("trials", 0)
    backtest = 0
    if trials >= 5:
        if wr >= 65:
            backtest = 20; entry_reason.append(f"歷史回測勝率 {wr}%（+20）")
        elif wr >= 55:
            backtest = 12; entry_reason.append(f"歷史回測勝率 {wr}%（+12）")
        elif wr >= 45:
            backtest = 6;  entry_reason.append(f"歷史回測勝率 {wr}%（+6）")
        else:
            risk_reason.append(f"歷史回測勝率 {wr}%，不足 45%（+0）")

    # ══ 5. 新聞 News：10 分 ══════════════════════════════════════════════════
    bull_news = sum(1 for n in news if n.get("sentiment") == "利多")
    bear_news = sum(1 for n in news if n.get("sentiment") == "利空")
    news_pts  = 0
    if bull_news > bear_news:
        news_pts = 6; entry_reason.append(f"新聞偏多（利多 {bull_news} 則，+6）")
    elif bear_news > bull_news:
        news_pts = -6; risk_reason.append(f"近期新聞偏負面（利空 {bear_news} 則，-6）")
    else:
        news_pts = 2   # 中性 +2

    # ── 加總，限制 0~100 ─────────────────────────────────────────────────────
    raw_pts = trend + momentum + volume + backtest + news_pts
    pts     = max(0, min(100, raw_pts))

    score_breakdown = {
        "trend":    max(0, min(30, trend)),
        "momentum": max(0, min(25, momentum)),
        "volume":   max(0, min(15, volume)),
        "backtest": max(0, min(20, backtest)),
        "news":     max(0, min(10, news_pts)),
    }

    # ── 訊號 ────────────────────────────────────────────────────────────────
    if pts >= 75:   signal = "BUY"
    elif pts >= 55: signal = "WATCH"
    else:           signal = "AVOID"

    # ── 目標價 / 止蝕 ────────────────────────────────────────────────────────
    if signal == "BUY":
        target_price = round(current_price * 1.06, 2)
    elif signal == "WATCH":
        target_price = round(current_price * 1.03, 2)
    else:
        target_price = None

    stop_loss = round(ma20_val * 0.98, 2) if ma20_val else round(current_price * 0.95, 2)

    # 風險報酬比
    if target_price and stop_loss and current_price > stop_loss:
        rr  = round((target_price - current_price) / (current_price - stop_loss), 2)
        risk_reward_ratio = rr if rr > 0 else None
    else:
        risk_reward_ratio = None

    # ── 持有天數建議 ─────────────────────────────────────────────────────────
    if wr >= 65:     holding_days = "5-10 天"
    elif wr >= 50:   holding_days = "3-5 天"
    else:            holding_days = "不建議持有"

    # ── 摘要 ────────────────────────────────────────────────────────────────
    if signal == "BUY":
        summary = "技術面與回測條件良好，但仍需留意風險。"
    elif signal == "WATCH":
        summary = "訊號尚未完全確認，建議觀望。"
    else:
        summary = "條件不足，不建議進場。"

    return {
        "signal":            signal,
        "confidence":        pts,
        "score_breakdown":   score_breakdown,
        "entry_reason":      entry_reason,
        "risk_reason":       risk_reason,
        "summary":           summary,
        "target_price":      target_price,
        "stop_loss":         stop_loss,
        "holding_days":      holding_days,
        "risk_reward_ratio": risk_reward_ratio,
        "disclaimer":        "⚠️ 本工具僅供參考，非投資建議",
    }

# ══════════════════════════════════════════════════════════════════════════════
# LINE
# ══════════════════════════════════════════════════════════════════════════════

def _line_configured() -> bool:
    return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID and ENABLE_LINE_ALERTS)

def _check_line_config():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
    if not LINE_TO_ID:
        raise HTTPException(status_code=503, detail="LINE_TO_ID 尚未設定")
    if not ENABLE_LINE_ALERTS:
        raise HTTPException(status_code=503, detail="ENABLE_LINE_ALERTS 未設為 true")

async def send_line_message(message: str) -> dict:
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    body = {"to": LINE_TO_ID, "messages": [{"type": "text", "text": message}]}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(LINE_PUSH_URL, headers=headers, json=body)
            if r.status_code == 200:
                return {"success": True, "message": "LINE 訊息發送成功"}
            return {"success": False, "message": f"LINE API 錯誤：{r.status_code} - {r.text}"}
    except Exception as e:
        return {"success": False, "message": f"發送失敗：{str(e)}"}

def _build_line_message(stock_id: str, stock_name: str, ai: dict, price: float) -> str:
    display = f"{stock_name} ({stock_id})" if stock_name and stock_name != stock_id else stock_id
    reasons_text = "\n".join(f"- {r}" for r in ai["entry_reason"][:5])
    bd = ai.get("score_breakdown", {})
    return (
        f"📈 台股買點提醒\n"
        f"股票：{display}\n"
        f"訊號：{ai['signal']}  信心：{ai['confidence']}/100\n"
        f"價格：{price}  目標：{ai['target_price']}  止蝕：{ai['stop_loss']}\n"
        f"建議持有：{ai['holding_days']}  RR：{ai['risk_reward_ratio']}x\n"
        f"評分：趨勢{bd.get('trend',0)} 動能{bd.get('momentum',0)} 量能{bd.get('volume',0)} 回測{bd.get('backtest',0)} 新聞{bd.get('news',0)}\n"
        f"理由：\n{reasons_text}\n"
        f"{ai['disclaimer']}"
    )

# ══════════════════════════════════════════════════════════════════════════════
# 進階回測
# ══════════════════════════════════════════════════════════════════════════════

def advanced_backtest(df: pd.DataFrame, holding_days: int = 5, min_score: int = 75) -> dict:
    df = df.copy().reset_index(drop=True)
    df = compute_indicators(df)
    df = df.dropna(subset=["MA5", "MA20", "MA60", "RSI", "MACD", "Signal"])
    trades, equity, peak, max_dd = [], 1.0, 1.0, 0.0
    for i, (_, row) in enumerate(df.iterrows()):
        if i + holding_days >= len(df): break
        sc_info  = technical_score(row)
        vol_info = {"alert": False, "ratio": 1.0, "latest_volume": 0, "avg_volume_20d": 0}
        wr_info  = {"winrate": 0, "trials": 0, "wins": 0}
        cur      = float(row["收盤價"])
        ai       = compute_ai_signal(sc_info, row, vol_info, wr_info, [], cur)
        if ai["confidence"] < min_score: continue
        exit_p  = float(df.iloc[i + holding_days]["收盤價"])
        ret_pct = round((exit_p - cur) / cur * 100, 2)
        trades.append({
            "date":        row["日期"].strftime("%Y-%m-%d"),
            "entry_price": cur, "exit_price": exit_p,
            "return_pct":  ret_pct, "win": exit_p > cur,
            "confidence":  ai["confidence"], "signal": ai["signal"],
        })
        equity *= (1 + ret_pct / 100)
        peak    = max(peak, equity)
        dd      = (peak - equity) / peak * 100
        max_dd  = max(max_dd, dd)
    total = len(trades); wins = sum(1 for t in trades if t["win"])
    rets  = [t["return_pct"] for t in trades]
    gain  = sum(r for r in rets if r > 0)
    loss  = abs(sum(r for r in rets if r < 0))
    return {
        "total_trades":  total, "wins": wins, "losses": total - wins,
        "winrate":       round(wins / total * 100, 1) if total else 0,
        "avg_return":    round(sum(rets) / total, 2)  if total else 0,
        "best_return":   round(max(rets), 2)           if rets  else 0,
        "worst_return":  round(min(rets), 2)           if rets  else 0,
        "max_drawdown":  round(max_dd, 2),
        "profit_factor": round(gain / loss, 2)         if loss  else 0,
        "trades":        list(reversed(trades))[:20],
    }

# ══════════════════════════════════════════════════════════════════════════════
# 主要端點
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id):
        raise HTTPException(status_code=400, detail="股票代號格式錯誤，請輸入 4~6 位數字")

    price_df, api_name = await asyncio.gather(
        fetch_twse_price(stock_id),
        _fetch_stock_name_from_api(stock_id),
    )
    # 用 get_stock_name 確保名稱正確（API + 字典 fallback）
    stock_name = get_stock_name(stock_id, api_name)

    price_df   = compute_indicators(price_df)
    latest     = price_df.iloc[-1]
    prev       = price_df.iloc[-2] if len(price_df) > 1 else latest
    change     = float(latest["收盤價"] - prev["收盤價"])
    change_pct = round(change / float(prev["收盤價"]) * 100, 2) if prev["收盤價"] else 0

    score_info = technical_score(latest)
    winrate    = backtest_winrate(price_df)
    vol_info   = volume_analysis(price_df)

    s          = score_info["score"]
    conclusion = "短線偏多 📈" if s >= 4 else ("短線偏弱 📉" if s <= 2 else "觀望 ➡️")

    rsi_val   = float(latest["RSI"]) if pd.notna(latest["RSI"]) else None
    rsi_alert = None
    if rsi_val:
        if rsi_val > 70:  rsi_alert = "⚠️ RSI 過熱（>70），注意拉回風險"
        elif rsi_val < 30: rsi_alert = "⚠️ RSI 過冷（<30），可能出現反彈"

    news           = await fetch_news(stock_id, stock_name)
    realtime_quote = await fetch_realtime_quote(stock_id)

    current_price = (
        float(realtime_quote["price"])
        if realtime_quote and realtime_quote.get("price") is not None
        else float(latest["收盤價"])
    )
    ai_signal = compute_ai_signal(score_info, latest, vol_info, winrate, news, current_price)

    chart_data = [
        {
            "date":   row["日期"].strftime("%Y-%m-%d"),
            "open":   _f(row["開盤價"]), "high": _f(row["最高價"]),
            "low":    _f(row["最低價"]),  "close": _f(row["收盤價"]),
            "volume": int(row["成交股數"]) if pd.notna(row["成交股數"]) else 0,
            "ma5":    _f(row["MA5"]),  "ma20":   _f(row["MA20"]),
            "ma60":   _f(row["MA60"]), "rsi":    _f(row["RSI"]),
            "macd":   _f(row["MACD"], 4), "signal": _f(row["Signal"], 4),
            "hist":   _f(row["Hist"], 4),
        }
        for _, row in price_df.tail(60).iterrows()
    ]

    return {
        "stock_id":   stock_id,
        "stock_name": stock_name,
        "last_date":  latest["日期"].strftime("%Y-%m-%d"),
        "price": {
            "close":       _f(current_price),
            "daily_close": _f(latest["收盤價"]),
            "open":  _f(realtime_quote.get("open")  if realtime_quote else latest["開盤價"]),
            "high":  _f(realtime_quote.get("high")  if realtime_quote else latest["最高價"]),
            "low":   _f(realtime_quote.get("low")   if realtime_quote else latest["最低價"]),
            "change":     _f(realtime_quote.get("change"), 2) if realtime_quote and realtime_quote.get("change") is not None else round(change, 2),
            "change_pct": _f(realtime_quote.get("change_pct"), 2) if realtime_quote and realtime_quote.get("change_pct") is not None else change_pct,
            "mode":       "realtime" if realtime_quote and realtime_quote.get("price") is not None else "daily",
        },
        "indicators": {
            "ma5":    _f(latest["MA5"]),  "ma20": _f(latest["MA20"]),
            "ma60":   _f(latest["MA60"]), "rsi":  _f(latest["RSI"]),
            "macd":   _f(latest["MACD"], 4), "signal": _f(latest["Signal"], 4),
            "hist":   _f(latest["Hist"], 4),
        },
        "volume":    vol_info,
        "score":     score_info,
        "backtest":  winrate,
        "conclusion": conclusion,
        "rsi_alert": rsi_alert,
        "ai_signal": ai_signal,
        "realtime_quote": realtime_quote,
        "news":      news,
        "chart_data": chart_data,
    }


@app.get("/api/realtime/{stock_id}")
async def get_realtime(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id):
        raise HTTPException(status_code=400, detail="股票代號格式錯誤，請輸入 4~6 位數字")
    quote = await fetch_realtime_quote(stock_id)
    if not quote:
        raise HTTPException(status_code=404, detail="找不到即時報價；可能為休市、資料源暫時不可用或股票代號錯誤")
    return quote


@app.post("/api/alerts/test")
async def test_line():
    _check_line_config()
    result = await send_line_message(
        "✅ 台股監測工具 V5 - LINE 通知測試成功！\n你的 LINE Bot 設定正確，通知功能已啟用。"
    )
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@app.post("/api/alerts/check")
async def check_alerts(body: WatchlistBody):
    """
    批量檢查自選股 BUY 訊號，符合條件發送 LINE 通知。
    ★ LINE 未設定時：仍回傳掃描結果，不拋 HTTP 錯誤。
    """
    line_ok   = _line_configured()
    results   = []
    now       = datetime.now()
    sent_msgs = []

    for stock_id in body.watchlist:
        if not re.match(r"^\d{4,6}$", stock_id): continue
        try:
            price_df, api_name = await asyncio.gather(
                fetch_twse_price(stock_id),
                _fetch_stock_name_from_api(stock_id),
            )
            stock_name = get_stock_name(stock_id, api_name)
            price_df   = compute_indicators(price_df)
            latest     = price_df.iloc[-1]
            score_info = technical_score(latest)
            winrate    = backtest_winrate(price_df)
            vol_info   = volume_analysis(price_df)
            news       = await fetch_news(stock_id, stock_name)
            realtime   = await fetch_realtime_quote(stock_id)
            cur_price  = float(realtime["price"]) if realtime and realtime.get("price") is not None else float(latest["收盤價"])
            ai         = compute_ai_signal(score_info, latest, vol_info, winrate, news, cur_price)

            results.append({
                "stock_id":   stock_id,
                "stock_name": stock_name,
                "signal":     ai["signal"],
                "confidence": ai["confidence"],
                "summary":    ai["summary"],
                "target_price":      ai["target_price"],
                "stop_loss":         ai["stop_loss"],
                "risk_reward_ratio": ai["risk_reward_ratio"],
            })

            rr = ai.get("risk_reward_ratio") or 0
            if line_ok and ai["signal"] == "BUY" and ai["confidence"] >= 75 and rr >= 1.5:
                last_sent = LAST_ALERTS.get(stock_id)
                cooldown_ok = (
                    last_sent is None or
                    (now - last_sent).total_seconds() >= ALERT_COOLDOWN_MINUTES * 60
                )
                if cooldown_ok:
                    msg    = _build_line_message(stock_id, stock_name, ai, cur_price)
                    result = await send_line_message(msg)
                    if result["success"]:
                        LAST_ALERTS[stock_id] = now
                        sent_msgs.append(stock_id)

        except HTTPException as e:
            results.append({"stock_id": stock_id, "error": e.detail})
        except Exception as e:
            results.append({"stock_id": stock_id, "error": str(e)})

    alerts = [r for r in results if r.get("signal") == "BUY"]
    return {
        "checked":      len(body.watchlist),
        "alerts":       alerts,
        "all_results":  results,
        "sent_line":    sent_msgs,
        "line_enabled": line_ok,
        "timestamp":    now.isoformat(),
    }


@app.get("/api/backtest/{stock_id}")
async def run_backtest(
    stock_id: str, lookback_days: int = 400,
    holding_days: int = 5, min_score: int = 75,
):
    if not re.match(r"^\d{4,6}$", stock_id):
        raise HTTPException(status_code=400, detail="股票代號格式錯誤")
    price_df, api_name = await asyncio.gather(
        fetch_twse_price(stock_id, lookback_days=lookback_days),
        _fetch_stock_name_from_api(stock_id),
    )
    stock_name = get_stock_name(stock_id, api_name)
    result     = advanced_backtest(price_df, holding_days=holding_days, min_score=min_score)
    return {
        "stock_id": stock_id, "stock_name": stock_name,
        "params":   {"lookback_days": lookback_days, "holding_days": holding_days, "min_score": min_score},
        "result":   {k: v for k, v in result.items() if k != "trades"},
        "trades":   result["trades"],
    }


@app.get("/health")
def health():
    return {
        "status":          "ok",
        "version":         "5.0.0",
        "time":            datetime.now().isoformat(),
        "dev_mode":        DEV_MODE,
        "line_configured": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
        "line_enabled":    ENABLE_LINE_ALERTS,
        "realtime_source": "TWSE MIS",
        "stock_dict_size": len(STOCK_NAME_MAP),
    }
