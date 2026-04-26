"""
台股監測後端 - FastAPI
資料來源：FinMind API（免費額度）、TWSE Open API（免費）、Google News RSS
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import re
import asyncio

app = FastAPI(title="台股監測 API", version="2.0.0")

# ── CORS 設定（用環境變數管理，安全且彈性）────────────────────────────────────
# 本機開發時預設允許常見 local origins；
# 雲端部署時，設定環境變數 ALLOWED_ORIGINS（逗號分隔）來覆蓋。
#
# 範例：
#   本機執行：不需設定，使用下方預設值
#   Render 部署：在 Dashboard 設定環境變數
#     ALLOWED_ORIGINS=https://your-project.web.app,https://your-project.firebaseapp.com

_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8080,http://127.0.0.1:8080,"
    "http://localhost,http://127.0.0.1"
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# 開發模式：若環境變數 DEV_MODE=true，則允許所有來源（方便本機直接雙擊 HTML）
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
if DEV_MODE:
    ALLOWED_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=not DEV_MODE,   # allow_credentials 與 "*" 不相容
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# ── 常數 ──────────────────────────────────────────────────────────────────────
FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TIMEOUT = 25

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

# ── 工具函式 ──────────────────────────────────────────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def score_sentiment(text: str) -> str:
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    if bull > bear:
        return "利多"
    elif bear > bull:
        return "利空"
    return "中性"

# ── 股價資料（FinMind 免費 API）───────────────────────────────────────────────

async def fetch_twse_price(stock_id: str) -> pd.DataFrame:
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=400)   # 多抓一點，確保 MA60 有足夠資料

    params = {
        "dataset":    "TaiwanStockPrice",
        "data_id":    stock_id,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date":   end_date.strftime("%Y-%m-%d"),
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(FINMIND_BASE, params=params)
            r.raise_for_status()
            data = r.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="股價 API 逾時，請稍後再試")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"股價資料來源連線失敗：{e}")

    rows = data.get("data", [])
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"找不到股票代號 {stock_id} 的資料，請確認是否為上市股票（ETF 需用完整代號，例如 0050）",
        )

    raw = pd.DataFrame(rows)
    df = pd.DataFrame()
    df["日期"]   = pd.to_datetime(raw.get("date"),            errors="coerce")
    df["成交股數"] = pd.to_numeric(raw.get("Trading_Volume"),  errors="coerce")
    df["開盤價"]  = pd.to_numeric(raw.get("open"),            errors="coerce")
    df["最高價"]  = pd.to_numeric(raw.get("max"),             errors="coerce")
    df["最低價"]  = pd.to_numeric(raw.get("min"),             errors="coerce")
    df["收盤價"]  = pd.to_numeric(raw.get("close"),           errors="coerce")

    df = df.dropna(subset=["日期", "收盤價"]).sort_values("日期").reset_index(drop=True)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"股票 {stock_id} 無有效股價資料")
    return df

# ── 技術指標 ──────────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["收盤價"]
    df["MA5"]    = c.rolling(5).mean()
    df["MA20"]   = c.rolling(20).mean()
    df["MA60"]   = c.rolling(60).mean()
    df["RSI"]    = calc_rsi(c, 14)
    df["MACD"], df["Signal"], df["Hist"] = calc_macd(c)
    return df

# ── 技術面評分 ────────────────────────────────────────────────────────────────

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

# ── 回測勝率 ──────────────────────────────────────────────────────────────────

def backtest_winrate(df: pd.DataFrame) -> dict:
    df = df.dropna(subset=["MA5", "MA20", "MA60", "RSI", "MACD", "Signal"])
    if len(df) < 10:
        return {"trials": 0, "wins": 0, "winrate": 0}

    cond = (
        (df["收盤價"] > df["MA20"]) &
        (df["MA5"]   > df["MA20"]) &
        (df["RSI"]   > 50) &
        (df["MACD"]  > df["Signal"])
    )
    wins = trials = 0
    for idx in df[cond].index:
        pos = df.index.get_loc(idx)
        if pos + 5 < len(df):
            trials += 1
            if df.iloc[pos + 5]["收盤價"] > df.iloc[pos]["收盤價"]:
                wins += 1

    return {
        "trials":  trials,
        "wins":    wins,
        "winrate": round(wins / trials * 100, 1) if trials else 0,
    }

# ── 成交量分析 ────────────────────────────────────────────────────────────────

def volume_analysis(df: pd.DataFrame) -> dict:
    avg_vol    = df.tail(20)["成交股數"].mean()
    latest_vol = df.iloc[-1]["成交股數"]
    ratio      = round(float(latest_vol / avg_vol), 2) if avg_vol else 1.0
    return {
        "latest_volume": int(latest_vol) if pd.notna(latest_vol) else 0,
        "avg_volume_20d": int(avg_vol)   if pd.notna(avg_vol)    else 0,
        "ratio":  ratio,
        "alert":  ratio >= 1.5,
    }

# ── 新聞 RSS ──────────────────────────────────────────────────────────────────

async def fetch_news(stock_id: str, stock_name: str = "") -> list:
    query = stock_name if stock_name else stock_id
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
                if items:
                    break
            except Exception:
                continue

    seen, unique = set(), []
    for n in items:
        if n["title"] not in seen:
            seen.add(n["title"]); unique.append(n)
    return unique[:10]

# ── 股票名稱 ──────────────────────────────────────────────────────────────────

async def fetch_stock_name(stock_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r    = await client.get(TWSE_NAME_URL, params={"stockNo": stock_id})
            data = r.json()
            if isinstance(data, dict):
                for key in ["data", "msgArray"]:
                    arr = data.get(key)
                    if arr and isinstance(arr, list) and arr:
                        row = arr[0]
                        if isinstance(row, list) and len(row) > 1:
                            return row[1]
                        if isinstance(row, dict):
                            return row.get("公司名稱", row.get("Name", stock_id))
    except Exception:
        pass
    return stock_id

# ── 主要端點 ──────────────────────────────────────────────────────────────────

@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id: str):
    if not re.match(r"^\d{4,6}$", stock_id):
        raise HTTPException(status_code=400, detail="股票代號格式錯誤，請輸入 4~6 位數字")

    price_df, stock_name = await asyncio.gather(
        fetch_twse_price(stock_id),
        fetch_stock_name(stock_id),
    )

    price_df = compute_indicators(price_df)
    latest   = price_df.iloc[-1]
    prev     = price_df.iloc[-2] if len(price_df) > 1 else latest

    change     = float(latest["收盤價"] - prev["收盤價"])
    change_pct = round(change / float(prev["收盤價"]) * 100, 2) if prev["收盤價"] else 0

    score_info = technical_score(latest)
    winrate    = backtest_winrate(price_df)
    vol_info   = volume_analysis(price_df)

    s = score_info["score"]
    conclusion = "短線偏多 📈" if s >= 4 else ("短線偏弱 📉" if s <= 2 else "觀望 ➡️")

    rsi_val   = float(latest["RSI"]) if pd.notna(latest["RSI"]) else None
    rsi_alert = None
    if rsi_val:
        if rsi_val > 70:
            rsi_alert = "⚠️ RSI 過熱（>70），注意拉回風險"
        elif rsi_val < 30:
            rsi_alert = "⚠️ RSI 過冷（<30），可能出現反彈"

    def f(v, d=2):
        return round(float(v), d) if pd.notna(v) else None

    chart_data = [
        {
            "date":   row["日期"].strftime("%Y-%m-%d"),
            "open":   f(row["開盤價"]),
            "high":   f(row["最高價"]),
            "low":    f(row["最低價"]),
            "close":  f(row["收盤價"]),
            "volume": int(row["成交股數"]) if pd.notna(row["成交股數"]) else 0,
            "ma5":    f(row["MA5"]),
            "ma20":   f(row["MA20"]),
            "ma60":   f(row["MA60"]),
            "rsi":    f(row["RSI"]),
            "macd":   f(row["MACD"], 4),
            "signal": f(row["Signal"], 4),
            "hist":   f(row["Hist"],   4),
        }
        for _, row in price_df.tail(60).iterrows()
    ]

    news = await fetch_news(stock_id, stock_name)

    return {
        "stock_id":   stock_id,
        "stock_name": stock_name,
        "last_date":  latest["日期"].strftime("%Y-%m-%d"),
        "price": {
            "close":      f(latest["收盤價"]),
            "open":       f(latest["開盤價"]),
            "high":       f(latest["最高價"]),
            "low":        f(latest["最低價"]),
            "change":     round(change, 2),
            "change_pct": change_pct,
        },
        "indicators": {
            "ma5":    f(latest["MA5"]),
            "ma20":   f(latest["MA20"]),
            "ma60":   f(latest["MA60"]),
            "rsi":    f(latest["RSI"]),
            "macd":   f(latest["MACD"],   4),
            "signal": f(latest["Signal"], 4),
            "hist":   f(latest["Hist"],   4),
        },
        "volume":     vol_info,
        "score":      score_info,
        "backtest":   winrate,
        "conclusion": conclusion,
        "rsi_alert":  rsi_alert,
        "news":       news,
        "chart_data": chart_data,
    }


@app.get("/health")
def health():
    return {
        "status":   "ok",
        "time":     datetime.now().isoformat(),
        "dev_mode": DEV_MODE,
        "allowed_origins": ALLOWED_ORIGINS,
    }
