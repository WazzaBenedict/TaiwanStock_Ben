"""
台股監測後端 V6
新增：FinMind 402/403/429 fallback（Yahoo Finance / TWSE 官方）、
     風險模型 risk_model、宏觀情境 macro_context（USD/TWD、DXY）、
     BUY 需同時滿足 RR>=1.5 且 winrate>=50、LINE 訊息格式升級
資料來源：FinMind → Yahoo Finance fallback → TWSE fallback
"""

import os, re, asyncio, json
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="台股監測 API", version="6.0.0")

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

# ── LINE ─────────────────────────────────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TO_ID                = os.getenv("LINE_TO_ID", "")
ENABLE_LINE_ALERTS        = os.getenv("ENABLE_LINE_ALERTS", "false").lower() == "true"

LAST_ALERTS: dict[str, datetime] = {}
ALERT_COOLDOWN_MINUTES = 30

# ── 常數 ──────────────────────────────────────────────────────────────────────
FINMIND_BASE  = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL  = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
TIMEOUT = 25

# ── 股票名稱字典 ───────────────────────────────────────────────────────────────
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
    "6669": "緯穎",    "3034": "聯詠",    "2449": "京元電子",
}

def get_stock_name(stock_id: str, api_name: str | None = None) -> str:
    cleaned = str(api_name).strip() if api_name else ""
    if cleaned and cleaned != stock_id:
        return cleaned
    return STOCK_NAME_MAP.get(stock_id, stock_id)

# ── 新聞關鍵字 ────────────────────────────────────────────────────────────────
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

class WatchlistBody(BaseModel):
    watchlist: list[str]

# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
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
    n = _num(v); return int(n) if n is not None else 0

def _quote_time(d, t):
    d = (d or '').strip(); t = (t or '').strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t}".strip()
    return f"{d} {t}".strip() or None

def _make_empty_df() -> pd.DataFrame:
    """回傳只有欄位的空 DataFrame，避免後續程式崩潰。"""
    return pd.DataFrame(columns=["日期","成交股數","開盤價","最高價","最低價","收盤價"])

# ══════════════════════════════════════════════════════════════════════════════
# 即時報價 TWSE MIS
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_realtime_quote(stock_id: str) -> dict | None:
    ts = int(datetime.now().timestamp() * 1000)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        for market in ("tse", "otc"):
            params = {"ex_ch": f"{market}_{stock_id}.tw", "json": "1", "delay": "0", "_": str(ts)}
            try:
                r    = await client.get(TWSE_MIS_URL, params=params)
                data = r.json()
                arr  = data.get("msgArray") or []
                if not arr: continue
                q       = arr[0]
                price   = _num(q.get("z")) or _num(q.get("a")) or _num(q.get("b"))
                prev    = _num(q.get("y"))
                open_   = _num(q.get("o"))
                high    = _num(q.get("h"))
                low     = _num(q.get("l"))
                change  = round(price - prev, 2) if price is not None and prev else None
                chg_pct = round(change / prev * 100, 2) if change is not None and prev else None
                return {
                    "stock_id":       str(q.get("c") or stock_id),
                    "stock_name":     get_stock_name(stock_id, q.get("n")),
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
                    "note":           "盤中即時或延遲報價",
                }
            except Exception:
                continue
    return None

# ══════════════════════════════════════════════════════════════════════════════
# ★ 歷史股價抓取：FinMind → Yahoo Finance → TWSE 官方（三層 fallback）
# ══════════════════════════════════════════════════════════════════════════════

def _parse_raw_to_df(rows: list[dict]) -> pd.DataFrame:
    """將 FinMind rows 轉換成標準 DataFrame。"""
    raw = pd.DataFrame(rows)
    df  = pd.DataFrame()
    df["日期"]   = pd.to_datetime(raw.get("date"),           errors="coerce")
    df["成交股數"] = pd.to_numeric(raw.get("Trading_Volume"), errors="coerce")
    df["開盤價"]  = pd.to_numeric(raw.get("open"),           errors="coerce")
    df["最高價"]  = pd.to_numeric(raw.get("max"),            errors="coerce")
    df["最低價"]  = pd.to_numeric(raw.get("min"),            errors="coerce")
    df["收盤價"]  = pd.to_numeric(raw.get("close"),          errors="coerce")
    return df.dropna(subset=["日期", "收盤價"]).sort_values("日期").reset_index(drop=True)


async def _fetch_from_finmind(stock_id: str, lookback_days: int, client: httpx.AsyncClient) -> pd.DataFrame | None:
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    params = {
        "dataset":    "TaiwanStockPrice",
        "data_id":    stock_id,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date":   end_date.strftime("%Y-%m-%d"),
    }
    try:
        r = await client.get(FINMIND_BASE, params=params, timeout=TIMEOUT)
        # 402 / 403 / 429 都視為配額超限，直接 fallback
        if r.status_code in (402, 403, 429):
            return None
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        if not rows:
            return None
        df = _parse_raw_to_df(rows)
        return df if not df.empty else None
    except Exception:
        return None


async def _fetch_from_yahoo(stock_id: str, lookback_days: int, client: httpx.AsyncClient) -> pd.DataFrame | None:
    """
    Yahoo Finance chart API（不需 API key）。
    台股代號加 .TW（上市）或 .TWO（上櫃），先試 .TW。
    """
    period2 = int(datetime.now().timestamp())
    period1 = int((datetime.now() - timedelta(days=lookback_days)).timestamp())
    for suffix in (".TW", ".TWO"):
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            f"?period1={period1}&period2={period2}&interval=1d&events=history"
        )
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = await client.get(url, headers=headers, timeout=20, follow_redirects=True)
            if r.status_code != 200:
                continue
            data   = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                continue
            res    = result[0]
            ts_arr = res.get("timestamp", [])
            q      = res.get("indicators", {}).get("quote", [{}])[0]
            opens  = q.get("open", [])
            highs  = q.get("high", [])
            lows   = q.get("low", [])
            closes = q.get("close", [])
            vols   = q.get("volume", [])
            if not ts_arr or not closes:
                continue
            records = []
            for i, ts in enumerate(ts_arr):
                c = closes[i] if i < len(closes) else None
                if c is None:
                    continue
                records.append({
                    "日期":   pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Taipei").date(),
                    "成交股數": (vols[i] if i < len(vols) else 0) or 0,
                    "開盤價":  opens[i]  if i < len(opens)  else c,
                    "最高價":  highs[i]  if i < len(highs)  else c,
                    "最低價":  lows[i]   if i < len(lows)   else c,
                    "收盤價":  c,
                })
            if not records:
                continue
            df = pd.DataFrame(records)
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期").reset_index(drop=True)
            return df
        except Exception:
            continue
    return None


async def _fetch_from_twse_official(stock_id: str, client: httpx.AsyncClient) -> pd.DataFrame | None:
    """
    TWSE 官方月資料 API。最多取最近 3 個月，約 60 筆。
    """
    frames = []
    today  = datetime.today()
    for delta_month in range(3):
        dt     = today - timedelta(days=30 * delta_month)
        ym     = dt.strftime("%Y%m")
        url    = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}01&stockNo={stock_id}&response=json"
        try:
            r    = await client.get(url, timeout=15)
            data = r.json()
            rows = data.get("data", [])
            if not rows:
                continue
            # TWSE 日期格式：民國年，例如 "113/04/01"
            records = []
            for row in rows:
                try:
                    parts   = row[0].replace(",", "").split("/")
                    year    = int(parts[0]) + 1911
                    date_s  = f"{year}/{parts[1]}/{parts[2]}"
                    dt_obj  = pd.to_datetime(date_s)
                    vol     = int(str(row[1]).replace(",", "")) if row[1] else 0
                    open_   = float(str(row[3]).replace(",", "")) if row[3] and row[3] != "--" else None
                    high    = float(str(row[4]).replace(",", "")) if row[4] and row[4] != "--" else None
                    low     = float(str(row[5]).replace(",", "")) if row[5] and row[5] != "--" else None
                    close   = float(str(row[6]).replace(",", "")) if row[6] and row[6] != "--" else None
                    if close is None:
                        continue
                    records.append({
                        "日期":   dt_obj,
                        "成交股數": vol * 1000,  # TWSE 單位是張，乘 1000 股
                        "開盤價":  open_ or close,
                        "最高價":  high  or close,
                        "最低價":  low   or close,
                        "收盤價":  close,
                    })
                except Exception:
                    continue
            if records:
                frames.append(pd.DataFrame(records))
        except Exception:
            continue
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)
    return df if not df.empty else None


async def fetch_price_with_fallback(stock_id: str, lookback_days: int = 400) -> tuple[pd.DataFrame, str]:
    """
    三層資料來源嘗試，回傳 (DataFrame, source_label)。
    若全部失敗，回傳空 DataFrame 讓上層以降級模式處理。
    """
    async with httpx.AsyncClient() as client:
        # 1. FinMind
        df = await _fetch_from_finmind(stock_id, lookback_days, client)
        if df is not None and not df.empty:
            return df, "FinMind"

        # 2. Yahoo Finance
        df = await _fetch_from_yahoo(stock_id, lookback_days, client)
        if df is not None and not df.empty:
            return df, "Yahoo Finance"

        # 3. TWSE 官方月資料
        df = await _fetch_from_twse_official(stock_id, client)
        if df is not None and not df.empty:
            return df, "TWSE Official"

    return _make_empty_df(), "none"

# ══════════════════════════════════════════════════════════════════════════════
# 股票名稱
# ══════════════════════════════════════════════════════════════════════════════

async def _fetch_stock_name_from_api(stock_id: str) -> str:
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

# ══════════════════════════════════════════════════════════════════════════════
# 新聞
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_news(stock_id: str, stock_name: str = "") -> list:
    query = stock_name if stock_name and stock_name != stock_id else stock_id
    urls  = [
        f"https://news.google.com/rss/search?q={query}+台股&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
        f"https://news.google.com/rss/search?q={stock_id}&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
    ]
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
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
# ★ 宏觀資料（USD/TWD、DXY）
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_macro_context() -> dict:
    """
    從 Yahoo Finance 抓 USD/TWD 和 DXY。
    任一失敗都不中斷，回傳 null。
    """
    result = {"usd_twd": None, "dxy": None, "risk_note": ""}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # USD/TWD
            try:
                r = await client.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/TWD=X?interval=1d&range=5d",
                    headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True
                )
                if r.status_code == 200:
                    data  = r.json()
                    res   = data.get("chart", {}).get("result")
                    if res:
                        closes = res[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                        valid  = [c for c in closes if c is not None]
                        if valid:
                            result["usd_twd"] = round(valid[-1], 3)
            except Exception:
                pass

            # DXY
            try:
                r = await client.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d",
                    headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True
                )
                if r.status_code == 200:
                    data  = r.json()
                    res   = data.get("chart", {}).get("result")
                    if res:
                        closes = res[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                        valid  = [c for c in closes if c is not None]
                        if valid:
                            result["dxy"] = round(valid[-1], 2)
            except Exception:
                pass
    except Exception:
        pass

    # 建立 note
    notes = []
    usd = result["usd_twd"]
    dxy = result["dxy"]
    if usd is not None and usd > 32.0:
        notes.append(f"美元/台幣 {usd}，匯率偏強，外資匯出壓力需留意")
    if dxy is not None and dxy > 104:
        notes.append(f"DXY {dxy}，美元指數偏強，新興市場資金面承壓")
    if usd is None and dxy is None:
        result["risk_note"] = "宏觀資料暫時無法取得"
    else:
        result["risk_note"] = "，".join(notes) if notes else "宏觀環境無明顯壓力"

    return result

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    c = df["收盤價"]
    df["MA5"]  = c.rolling(5).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["RSI"]  = calc_rsi(c, 14)
    df["MACD"], df["Signal"], df["Hist"] = calc_macd(c)
    return df

def technical_score(row: pd.Series) -> dict:
    score, reasons = 0, []
    if pd.notna(row.get("MA20")) and row["收盤價"] > row["MA20"]:
        score += 1; reasons.append("✅ 收盤價 > MA20（中線偏多）")
    else:
        reasons.append("❌ 收盤價 < MA20（中線偏弱）")
    if pd.notna(row.get("MA5")) and pd.notna(row.get("MA20")) and row["MA5"] > row["MA20"]:
        score += 1; reasons.append("✅ MA5 > MA20（均線多頭排列）")
    else:
        reasons.append("❌ MA5 < MA20（均線空頭排列）")
    if pd.notna(row.get("RSI")):
        if 40 <= row["RSI"] <= 70:
            score += 1; reasons.append(f"✅ RSI={row['RSI']:.1f}（健康區間 40~70）")
        elif row["RSI"] > 70:
            reasons.append(f"⚠️ RSI={row['RSI']:.1f}（過熱 >70）")
        else:
            reasons.append(f"❌ RSI={row['RSI']:.1f}（偏弱 <40）")
    if pd.notna(row.get("MACD")) and pd.notna(row.get("Signal")) and row["MACD"] > row["Signal"]:
        score += 1; reasons.append("✅ MACD > Signal（動能偏多）")
    else:
        reasons.append("❌ MACD < Signal（動能偏空）")
    if pd.notna(row.get("MA20")) and pd.notna(row.get("MA60")) and row["MA20"] > row["MA60"]:
        score += 1; reasons.append("✅ MA20 > MA60（長線趨勢向上）")
    else:
        reasons.append("❌ MA20 < MA60（長線趨勢向下）")
    return {"score": score, "max": 5, "reasons": reasons}

def backtest_winrate(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trials": 0, "wins": 0, "winrate": 0}
    req = [c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df2 = df.dropna(subset=req) if req else df
    if len(df2) < 10:
        return {"trials": 0, "wins": 0, "winrate": 0}
    cond = (
        (df2["收盤價"] > df2["MA20"]) & (df2["MA5"] > df2["MA20"]) &
        (df2["RSI"]   > 50)           & (df2["MACD"] > df2["Signal"])
    )
    wins = trials = 0
    for idx in df2[cond].index:
        pos = df2.index.get_loc(idx)
        if pos + 5 < len(df2):
            trials += 1
            if df2.iloc[pos + 5]["收盤價"] > df2.iloc[pos]["收盤價"]:
                wins += 1
    return {"trials": trials, "wins": wins, "winrate": round(wins / trials * 100, 1) if trials else 0}

def volume_analysis(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"latest_volume": 0, "avg_volume_20d": 0, "ratio": 1.0, "alert": False}
    avg_vol    = df.tail(20)["成交股數"].mean()
    latest_vol = df.iloc[-1]["成交股數"]
    ratio      = round(float(latest_vol / avg_vol), 2) if avg_vol and avg_vol > 0 else 1.0
    return {
        "latest_volume":  int(latest_vol) if pd.notna(latest_vol) else 0,
        "avg_volume_20d": int(avg_vol)    if pd.notna(avg_vol)    else 0,
        "ratio":          ratio,
        "alert":          bool(ratio >= 1.5),
    }

# ══════════════════════════════════════════════════════════════════════════════
# ★ V6 AI 策略評分引擎（加權 + 風險模型 + 宏觀）
# ══════════════════════════════════════════════════════════════════════════════

def compute_ai_signal(
    score_info:    dict,
    row:           pd.Series,
    vol_info:      dict,
    winrate_info:  dict,
    news:          list,
    current_price: float,
    macro:         dict | None = None,
) -> dict:
    entry_reason: list[str] = []
    risk_reason:  list[str] = []
    risk_factors: list[str] = []

    def _get(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None

    rsi_val  = _get("RSI")
    ma5_val  = _get("MA5")
    ma20_val = _get("MA20")
    ma60_val = _get("MA60")
    macd_val = _get("MACD")
    sig_val  = _get("Signal")
    hist_val = _get("Hist")

    # ══ 1. 趨勢 30 分 ═══════════════════════════════════════════════════════
    trend = 0
    if ma20_val and current_price > ma20_val:
        trend += 10; entry_reason.append("收盤價站上 MA20（+10）")
    if ma5_val and ma20_val and ma5_val > ma20_val:
        trend += 10; entry_reason.append("MA5 > MA20 均線多頭（+10）")
    if ma20_val and ma60_val and ma20_val > ma60_val:
        trend += 10; entry_reason.append("MA20 > MA60 長線向上（+10）")

    # ══ 2. 動能 25 分 ═══════════════════════════════════════════════════════
    momentum = 0
    if macd_val is not None and sig_val is not None and macd_val > sig_val:
        momentum += 10; entry_reason.append("MACD > Signal 動能偏多（+10）")
    if hist_val is not None and hist_val > 0:
        momentum += 5; entry_reason.append("MACD Histogram > 0（+5）")
    if rsi_val is not None:
        if 45 <= rsi_val <= 68:
            momentum += 10; entry_reason.append(f"RSI={rsi_val:.1f} 健康區間（+10）")
        elif rsi_val > 75:
            momentum -= 10; risk_reason.append(f"RSI={rsi_val:.1f} 過熱（-10）")
        elif rsi_val < 35:
            momentum -= 5;  risk_reason.append(f"RSI={rsi_val:.1f} 偏弱（-5）")

    # ══ 3. 量能 15 分 ═══════════════════════════════════════════════════════
    volume = 0
    ratio  = vol_info.get("ratio", 1.0)
    if ratio >= 1.8 and rsi_val is not None and rsi_val > 70:
        volume -= 5; risk_reason.append(f"放量（{ratio}x）但 RSI 偏高，短線過熱（-5）")
    elif ratio >= 1.2:
        volume += 8; entry_reason.append(f"成交量 {ratio}x 均量，動能增強（+8）")
        if ma20_val and current_price > ma20_val:
            volume += 5; entry_reason.append("量增且站上 MA20（+5）")
        volume = min(volume, 15)
    elif ma20_val and current_price > ma20_val:
        volume += 5; entry_reason.append("量能正常且站上 MA20（+5）")

    # ══ 4. 回測 20 分 ═══════════════════════════════════════════════════════
    wr     = winrate_info.get("winrate", 0)
    trials = winrate_info.get("trials", 0)
    backtest = 0
    if trials >= 5:
        if wr >= 65:
            backtest = 20; entry_reason.append(f"回測勝率 {wr}%（+20）")
        elif wr >= 55:
            backtest = 12; entry_reason.append(f"回測勝率 {wr}%（+12）")
        elif wr >= 45:
            backtest = 6;  entry_reason.append(f"回測勝率 {wr}%（+6）")
        else:
            risk_reason.append(f"回測勝率 {wr}%，不足 45%（+0）")

    # ══ 5. 新聞 10 分 ═══════════════════════════════════════════════════════
    bull_news = sum(1 for n in news if n.get("sentiment") == "利多")
    bear_news = sum(1 for n in news if n.get("sentiment") == "利空")
    news_pts  = 0
    if bull_news > bear_news:
        news_pts = 6; entry_reason.append(f"新聞偏多（利多 {bull_news} 則，+6）")
    elif bear_news > bull_news:
        news_pts = -6; risk_reason.append(f"近期新聞偏負面（利空 {bear_news} 則，-6）")
    else:
        news_pts = 2

    base_score = max(0, min(100, trend + momentum + volume + backtest + news_pts))

    score_breakdown = {
        "trend":    max(0, min(30, trend)),
        "momentum": max(0, min(25, momentum)),
        "volume":   max(0, min(15, volume)),
        "backtest": max(0, min(20, backtest)),
        "news":     max(0, min(10, news_pts)),
    }

    # ══ 風險模型 ════════════════════════════════════════════════════════════
    risk_penalty = 0

    if rsi_val is not None and rsi_val > 75:
        risk_penalty -= 10; risk_factors.append(f"RSI={rsi_val:.1f} 過熱（-10）")
    elif rsi_val is not None and rsi_val < 35:
        risk_penalty -= 5;  risk_factors.append(f"RSI={rsi_val:.1f} 偏弱（-5）")

    if ma20_val and ma20_val > 0:
        pct_above = (current_price - ma20_val) / ma20_val * 100
        if pct_above > 12:
            risk_penalty -= 8; risk_factors.append(f"股價距 MA20 +{pct_above:.1f}%，追高風險增加（-8）")

    if ratio >= 2.5:
        prev_row = row if "前日收盤" not in row else row
        # 用當日漲跌幅估算（若無前日收盤）
        change_today_pct = 0
        if "close" in winrate_info:
            pass  # 無法取得，跳過
        if vol_info.get("alert") and ratio >= 2.5:
            risk_penalty -= 8; risk_factors.append(f"爆量（{ratio}x），注意短線波動風險（-8）")

    if trials >= 5 and wr < 45:
        risk_penalty -= 10; risk_factors.append(f"歷史勝率 {wr}%，不足 45%（-10）")

    if trials < 5:
        risk_penalty -= 5; risk_factors.append("回測樣本不足（-5）")

    # 宏觀扣分
    macro = macro or {}
    macro_penalty = 0
    usd_twd = macro.get("usd_twd")
    dxy     = macro.get("dxy")
    if usd_twd is not None and usd_twd > 32.0:
        macro_penalty -= 3; risk_factors.append(f"USD/TWD={usd_twd} 匯率偏強（-3）")
    if dxy is not None and dxy > 104:
        macro_penalty -= 3; risk_factors.append(f"DXY={dxy} 美元指數偏強（-3）")

    # 風險等級
    total_penalty = risk_penalty + macro_penalty
    if total_penalty <= -15:
        risk_level = "HIGH"
    elif total_penalty <= -8:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    final_score = max(0, min(100, base_score + risk_penalty + macro_penalty))

    risk_model = {
        "base_score":    base_score,
        "risk_penalty":  risk_penalty,
        "macro_penalty": macro_penalty,
        "final_score":   final_score,
        "risk_level":    risk_level,
        "risk_factors":  risk_factors,
    }

    # ══ Signal（用 final_score）════════════════════════════════════════════
    if final_score >= 75:   signal = "BUY"
    elif final_score >= 55: signal = "WATCH"
    else:                   signal = "AVOID"

    # ── 目標價 / 止蝕 ────────────────────────────────────────────────────────
    if signal == "BUY":
        target_price = round(current_price * 1.06, 2)
    elif signal == "WATCH":
        target_price = round(current_price * 1.03, 2)
    else:
        target_price = None

    stop_loss = round(ma20_val * 0.98, 2) if ma20_val else round(current_price * 0.95, 2)

    if target_price and stop_loss and current_price > stop_loss:
        rr = round((target_price - current_price) / (current_price - stop_loss), 2)
        risk_reward_ratio = rr if rr > 0 else None
    else:
        risk_reward_ratio = None

    # BUY 降級條件
    if signal == "BUY":
        if risk_reward_ratio is None or risk_reward_ratio < 1.5:
            signal = "WATCH"
            risk_reason.append("風險報酬比不足（<1.5），暫不建議追價")
        elif wr < 50 and trials >= 5:
            signal = "WATCH"
            risk_reason.append("歷史勝率不足 50%，需保守觀察")

    if wr >= 65:     holding_days = "5-10 天"
    elif wr >= 50:   holding_days = "3-5 天"
    else:            holding_days = "不建議持有"

    if signal == "BUY":
        summary = "技術面與回測條件良好，風險可控，但仍需留意市場變化。"
    elif signal == "WATCH":
        summary = "訊號尚未完全確認，或風險報酬比不足，建議觀望。"
    else:
        summary = "條件不足，不建議進場。"

    macro_context = {
        "usd_twd": usd_twd,
        "dxy":     dxy,
        "note":    macro.get("risk_note", ""),
    }

    return {
        "signal":            signal,
        "confidence":        final_score,
        "score_breakdown":   score_breakdown,
        "risk_model":        risk_model,
        "macro_context":     macro_context,
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
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body    = {"to": LINE_TO_ID, "messages": [{"type": "text", "text": message}]}
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
    reasons_text = "\n".join(f"- {r.split('（')[0]}" for r in ai["entry_reason"][:4])
    rr = ai.get("risk_reward_ratio")
    mc = ai.get("macro_context", {})
    return (
        f"📈 自選股 AI 買點\n"
        f"股票：{display}\n"
        f"訊號：{ai['signal']}\n"
        f"信心：{ai['confidence']}/100\n"
        f"即時價：{price}\n"
        f"目標價：{ai['target_price']}\n"
        f"止蝕：{ai['stop_loss']}\n"
        f"風險報酬比：{rr}x\n"
        f"建議持有：{ai['holding_days']}\n\n"
        f"理由：\n{reasons_text}\n\n"
        f"{ai['disclaimer']}"
    )

# ══════════════════════════════════════════════════════════════════════════════
# 進階回測
# ══════════════════════════════════════════════════════════════════════════════

def advanced_backtest(df: pd.DataFrame, holding_days: int = 5, min_score: int = 75) -> dict:
    if df.empty:
        return {"total_trades":0,"wins":0,"losses":0,"winrate":0,"avg_return":0,"best_return":0,"worst_return":0,"max_drawdown":0,"profit_factor":0,"trades":[]}
    df = df.copy().reset_index(drop=True)
    df = compute_indicators(df)
    req = [c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df  = df.dropna(subset=req) if req else df
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

    # 並行：股名 + 股價 + 宏觀
    api_name_task  = asyncio.create_task(_fetch_stock_name_from_api(stock_id))
    macro_task     = asyncio.create_task(fetch_macro_context())

    price_df, data_source = await fetch_price_with_fallback(stock_id)
    api_name = await api_name_task
    macro    = await macro_task

    stock_name = get_stock_name(stock_id, api_name)

    # ── 降級模式：資料來源全部失敗 ──────────────────────────────────────────
    if price_df.empty:
        realtime_quote = await fetch_realtime_quote(stock_id)
        rt_price = realtime_quote.get("price") if realtime_quote else None
        degraded_ai = {
            "signal": "WATCH", "confidence": 0,
            "score_breakdown": {"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
            "risk_model": {"base_score":0,"risk_penalty":0,"macro_penalty":0,"final_score":0,"risk_level":"HIGH","risk_factors":["資料不足，無法評估"]},
            "macro_context": {"usd_twd": macro.get("usd_twd"), "dxy": macro.get("dxy"), "note": macro.get("risk_note","")},
            "entry_reason": [], "risk_reason": ["歷史股價資料暫時無法取得，評分不可靠"],
            "summary": "歷史資料無法取得，無法完整評估，請稍後再試。",
            "target_price": None, "stop_loss": None, "holding_days": "不建議持有",
            "risk_reward_ratio": None, "disclaimer": "⚠️ 本工具僅供參考，非投資建議",
        }
        price_obj = {
            "close":       rt_price,
            "daily_close": None, "open": None, "high": None, "low": None,
            "change":      realtime_quote.get("change")     if realtime_quote else None,
            "change_pct":  realtime_quote.get("change_pct") if realtime_quote else None,
            "mode":        "realtime" if rt_price else "unavailable",
        }
        return {
            "stock_id": stock_id, "stock_name": stock_name,
            "last_date": "N/A", "data_source": "none",
            "data_warning": "歷史股價資料暫時無法取得（FinMind/Yahoo/TWSE 均失敗），僅顯示即時報價。",
            "price": price_obj,
            "indicators": {"ma5":None,"ma20":None,"ma60":None,"rsi":None,"macd":None,"signal":None,"hist":None},
            "volume": {"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False},
            "score": {"score":0,"max":5,"reasons":["❌ 無法評估（資料不足）"]},
            "backtest": {"trials":0,"wins":0,"winrate":0},
            "conclusion": "資料不足 ⚠️",
            "rsi_alert": None,
            "ai_signal": degraded_ai,
            "realtime_quote": realtime_quote,
            "news": [],
            "chart_data": [],
        }

    price_df   = compute_indicators(price_df)
    latest     = price_df.iloc[-1]
    prev       = price_df.iloc[-2] if len(price_df) > 1 else latest
    change     = float(latest["收盤價"] - prev["收盤價"])
    change_pct = round(change / float(prev["收盤價"]) * 100, 2) if float(prev["收盤價"]) else 0

    score_info = technical_score(latest)
    winrate    = backtest_winrate(price_df)
    vol_info   = volume_analysis(price_df)
    s          = score_info["score"]
    conclusion = "短線偏多 📈" if s >= 4 else ("短線偏弱 📉" if s <= 2 else "觀望 ➡️")

    rsi_val   = float(latest["RSI"]) if "RSI" in latest.index and pd.notna(latest.get("RSI")) else None
    rsi_alert = None
    if rsi_val:
        if rsi_val > 70:   rsi_alert = "⚠️ RSI 過熱（>70），注意拉回風險"
        elif rsi_val < 30: rsi_alert = "⚠️ RSI 過冷（<30），可能出現反彈"

    news, realtime_quote = await asyncio.gather(
        fetch_news(stock_id, stock_name),
        fetch_realtime_quote(stock_id),
    )

    current_price = (
        float(realtime_quote["price"])
        if realtime_quote and realtime_quote.get("price") is not None
        else float(latest["收盤價"])
    )
    ai_signal = compute_ai_signal(score_info, latest, vol_info, winrate, news, current_price, macro)

    chart_data = []
    for _, row in price_df.tail(60).iterrows():
        chart_data.append({
            "date":   row["日期"].strftime("%Y-%m-%d"),
            "open":   _f(row.get("開盤價")),  "high": _f(row.get("最高價")),
            "low":    _f(row.get("最低價")),   "close": _f(row.get("收盤價")),
            "volume": int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
            "ma5":    _f(row.get("MA5")),   "ma20":   _f(row.get("MA20")),
            "ma60":   _f(row.get("MA60")),  "rsi":    _f(row.get("RSI")),
            "macd":   _f(row.get("MACD"),4), "signal": _f(row.get("Signal"),4),
            "hist":   _f(row.get("Hist"),4),
        })

    return {
        "stock_id":    stock_id,
        "stock_name":  stock_name,
        "last_date":   latest["日期"].strftime("%Y-%m-%d"),
        "data_source": data_source,
        "price": {
            "close":       _f(current_price),
            "daily_close": _f(latest["收盤價"]),
            "open":  _f(realtime_quote.get("open")  if realtime_quote else latest.get("開盤價")),
            "high":  _f(realtime_quote.get("high")  if realtime_quote else latest.get("最高價")),
            "low":   _f(realtime_quote.get("low")   if realtime_quote else latest.get("最低價")),
            "change":     (_f(realtime_quote.get("change"),2) if realtime_quote and realtime_quote.get("change") is not None else round(change,2)),
            "change_pct": (_f(realtime_quote.get("change_pct"),2) if realtime_quote and realtime_quote.get("change_pct") is not None else change_pct),
            "mode":       "realtime" if realtime_quote and realtime_quote.get("price") is not None else "daily",
        },
        "indicators": {
            "ma5":    _f(latest.get("MA5")),   "ma20": _f(latest.get("MA20")),
            "ma60":   _f(latest.get("MA60")),  "rsi":  _f(latest.get("RSI")),
            "macd":   _f(latest.get("MACD"),4), "signal": _f(latest.get("Signal"),4),
            "hist":   _f(latest.get("Hist"),4),
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
        raise HTTPException(status_code=404, detail="找不到即時報價")
    return quote


@app.post("/api/alerts/test")
async def test_line():
    _check_line_config()
    result = await send_line_message("✅ 台股監測工具 V6 - LINE 通知測試成功！\n你的 LINE Bot 設定正確，通知功能已啟用。")
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@app.post("/api/alerts/check")
async def check_alerts(body: WatchlistBody):
    """
    批量掃描自選股。LINE 未設定時仍回傳結果，不拋錯。
    """
    line_ok   = _line_configured()
    results   = []
    now       = datetime.now()
    sent_msgs = []

    # 宏觀資料只抓一次
    macro = await fetch_macro_context()

    for stock_id in body.watchlist:
        if not re.match(r"^\d{4,6}$", stock_id): continue
        try:
            api_name_coro = _fetch_stock_name_from_api(stock_id)
            price_task    = asyncio.create_task(fetch_price_with_fallback(stock_id, 200))
            api_name      = await api_name_coro
            stock_name    = get_stock_name(stock_id, api_name)

            price_df, _ = await price_task
            if price_df.empty:
                results.append({"stock_id": stock_id, "stock_name": stock_name, "error": "歷史資料暫時不可用"})
                continue

            price_df   = compute_indicators(price_df)
            latest     = price_df.iloc[-1]
            score_info = technical_score(latest)
            winrate    = backtest_winrate(price_df)
            vol_info   = volume_analysis(price_df)
            news       = await fetch_news(stock_id, stock_name)
            realtime   = await fetch_realtime_quote(stock_id)
            cur_price  = float(realtime["price"]) if realtime and realtime.get("price") is not None else float(latest["收盤價"])
            ai         = compute_ai_signal(score_info, latest, vol_info, winrate, news, cur_price, macro)

            results.append({
                "stock_id":          stock_id,
                "stock_name":        stock_name,
                "signal":            ai["signal"],
                "confidence":        ai["confidence"],
                "summary":           ai["summary"],
                "target_price":      ai["target_price"],
                "stop_loss":         ai["stop_loss"],
                "risk_reward_ratio": ai["risk_reward_ratio"],
                "risk_level":        ai["risk_model"]["risk_level"],
            })

            rr = ai.get("risk_reward_ratio") or 0
            if line_ok and ai["signal"] == "BUY" and ai["confidence"] >= 75 and rr >= 1.5:
                last_sent   = LAST_ALERTS.get(stock_id)
                cooldown_ok = last_sent is None or (now - last_sent).total_seconds() >= ALERT_COOLDOWN_MINUTES * 60
                if cooldown_ok:
                    msg    = _build_line_message(stock_id, stock_name, ai, cur_price)
                    result = await send_line_message(msg)
                    if result["success"]:
                        LAST_ALERTS[stock_id] = now
                        sent_msgs.append(stock_id)

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
    price_df, _  = await fetch_price_with_fallback(stock_id, lookback_days)
    api_name     = await _fetch_stock_name_from_api(stock_id)
    stock_name   = get_stock_name(stock_id, api_name)
    result       = advanced_backtest(price_df, holding_days=holding_days, min_score=min_score)
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
        "version":         "6.0.0",
        "time":            datetime.now().isoformat(),
        "dev_mode":        DEV_MODE,
        "line_configured": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
        "line_enabled":    ENABLE_LINE_ALERTS,
        "realtime_source": "TWSE MIS",
        "price_sources":   "FinMind → Yahoo Finance → TWSE Official",
        "stock_dict_size": len(STOCK_NAME_MAP),
    }
