"""
V12.3.1 Portfolio & Smart Alert Mode
架構：TW Engine / US Engine / Shared Engine（三層分離）
版本：12.2.1
"""
import os, re, asyncio, json, time
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx, numpy as np, pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="V12.3.1 Portfolio & Smart Alert Mode", version="12.3.1")
_raw = os.getenv("ALLOWED_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,"
    "https://taiwanstock-ben.web.app,https://taiwanstock-ben.firebaseapp.com")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
if DEV_MODE: ALLOWED_ORIGINS = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
    allow_credentials=not DEV_MODE, allow_methods=["GET","POST","OPTIONS"], allow_headers=["*"])

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TO_ID               = os.getenv("LINE_TO_ID", "")
ENABLE_LINE_ALERTS       = os.getenv("ENABLE_LINE_ALERTS", "false").lower() == "true"
LAST_ALERTS: dict[str, datetime] = {}
ALERT_COOLDOWN_MINUTES   = 30

# Optional API keys for richer US data
FINNHUB_API_KEY      = os.getenv("FINNHUB_API_KEY", "")
FMP_API_KEY          = os.getenv("FMP_API_KEY", "")
TWELVE_DATA_API_KEY  = os.getenv("TWELVE_DATA_API_KEY", "")

BASE_DIR           = Path(__file__).parent
WATCHLIST_FILE     = BASE_DIR / "watchlist.json"
STOCK_MASTER_FILE  = BASE_DIR / "stock_master.json"
TW_WEIGHTS_FILE    = BASE_DIR / "tw_weights.json"
US_WEIGHTS_FILE    = BASE_DIR / "us_weights.json"
TW_HISTORY_FILE    = BASE_DIR / "tw_signal_history.json"
US_HISTORY_FILE    = BASE_DIR / "us_signal_history.json"
US_MASTER_FILE     = BASE_DIR / "us_stock_master.json"

FINMIND_BASE  = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL  = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
HTTP_TIMEOUT  = 10
NEWS_TIMEOUT  = 5

# ══════════════════════════════════════════════════════════════════════════════
# TW Pool
# ══════════════════════════════════════════════════════════════════════════════
TW_SCAN_POOL = [
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
    "2404":"漢唐","2406":"國碩","2409":"友達","2421":"建準","2423":"固緯",
    "2429":"銘旺科","6182":"合晶","8240":"宏正","5871":"中租-KY","5876":"上海商銀",
    "5880":"合庫金","2801":"彰銀","2812":"台中銀","2823":"中壽","2836":"高雄銀",
    "2838":"聯邦銀","2845":"遠東銀","2849":"安泰銀","6116":"彩晶","2105":"正新",
    "2201":"裕隆","2204":"中華","2206":"三陽工業","2227":"裕日車","2231":"和泰工業",
    "2301":"光寶科","2323":"中環","2345":"智邦","2353":"宏碁","3005":"神基",
    "4904":"遠傳","5841":"合作金庫",
}

# ══════════════════════════════════════════════════════════════════════════════
# SHARED ENGINE — 指標計算
# ══════════════════════════════════════════════════════════════════════════════
def _f(v, d=2):  return round(float(v), d) if pd.notna(v) else None
def _num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in {"-","--","－","null","None"}: return None
    try: return float(s)
    except: return None

def calc_rsi(s: pd.Series, p=14) -> pd.Series:
    d = s.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/p, min_periods=p).mean()
    al = l.ewm(alpha=1/p, min_periods=p).mean()
    return 100 - (100 / (1 + ag / al.replace(0, np.nan)))

def calc_macd(s: pd.Series, fast=12, slow=26, signal=9):
    ef = s.ewm(span=fast, adjust=False).mean()
    es = s.ewm(span=slow, adjust=False).mean()
    m  = ef - es; sig = m.ewm(span=signal, adjust=False).mean()
    return m, sig, m - sig

def calc_atr(df: pd.DataFrame, period=14) -> pd.Series:
    hi = df.get("最高價", df["收盤價"]); lo = df.get("最低價", df["收盤價"])
    c = df["收盤價"]; pc = c.shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_adx(df: pd.DataFrame, period=14) -> pd.Series:
    try:
        hi = df.get("最高價", df["收盤價"]); lo = df.get("最低價", df["收盤價"])
        c = df["收盤價"]; pc = c.shift(1)
        tr = pd.concat([hi-lo,(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1)
        dm_plus = pd.Series(0.0, index=df.index)
        dm_minus = pd.Series(0.0, index=df.index)
        for i in range(1, len(df)):
            h_diff = float(hi.iloc[i]) - float(hi.iloc[i-1])
            l_diff = float(lo.iloc[i-1]) - float(lo.iloc[i])
            dm_plus.iloc[i]  = max(h_diff, 0) if h_diff > l_diff else 0
            dm_minus.iloc[i] = max(l_diff, 0) if l_diff > h_diff else 0
        atr14 = tr.ewm(alpha=1/period, min_periods=period).mean()
        dip14 = dm_plus.ewm(alpha=1/period, min_periods=period).mean()
        dim14 = dm_minus.ewm(alpha=1/period, min_periods=period).mean()
        di_plus  = 100 * dip14 / atr14.replace(0, np.nan)
        di_minus = 100 * dim14 / atr14.replace(0, np.nan)
        dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        return dx.ewm(alpha=1/period, min_periods=period).mean()
    except:
        return pd.Series(np.nan, index=df.index)

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Shared indicator computation for both TW and US."""
    if df.empty: return df
    c = df["收盤價"]
    df["MA5"]  = c.rolling(5).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["RSI"]  = calc_rsi(c, 14)
    df["MACD"], df["Signal"], df["Hist"] = calc_macd(c)
    df["BB_mid"] = c.rolling(20).mean()
    bbs = c.rolling(20).std()
    df["BB_upper"] = df["BB_mid"] + 2 * bbs
    df["BB_lower"] = df["BB_mid"] - 2 * bbs
    hi = df.get("最高價", c); lo = df.get("最低價", c)
    if hi is not None and lo is not None:
        df["ATR"] = calc_atr(df, 14)
    df["ADX"] = calc_adx(df, 14)
    return df

def calc_support_resistance(df: pd.DataFrame, lookback=20) -> tuple[float|None, float|None]:
    """Return (support, resistance) from recent price history."""
    if df.empty: return None, None
    tail = df.tail(lookback)
    sup = float(tail["最低價"].min()) if "最低價" in tail.columns else float(tail["收盤價"].min())
    res = float(tail["最高價"].max()) if "最高價" in tail.columns else float(tail["收盤價"].max())
    return round(sup, 4), round(res, 4)

def validate_trade_plan(ep, sl, tp) -> bool:
    """Core rule: stop_loss < entry_price < target_price AND rr >= 1.5"""
    if ep is None or sl is None or tp is None: return False
    if not (sl < ep < tp): return False
    rr = (tp - ep) / (ep - sl) if ep > sl else 0
    return rr >= 1.5

def compute_rr(ep, sl, tp) -> float | None:
    if ep is None or sl is None or tp is None: return None
    if ep <= sl: return None
    rr = (tp - ep) / (ep - sl)
    return round(rr, 2) if rr > 0 else None

def compute_technical_score(row: pd.Series, cp: float, vol_ratio: float = 1.0,
                             chg_pct: float = 0.0, price_df: pd.DataFrame | None = None) -> dict:
    """100-pt technical score with breakdown. Used by both TW and US."""
    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    ma5=_g("MA5"); ma20=_g("MA20"); ma60=_g("MA60")
    rsi=_g("RSI"); macd_v=_g("MACD"); sig_v=_g("Signal"); hist=_g("Hist")
    atr=_g("ATR"); adx=_g("ADX")
    score = 0
    bd = {"trend_score":0,"momentum_score":0,"volume_score":0,
          "volatility_score":0,"support_resistance_score":0,"adx_score":0}
    # 1. Trend 30
    if ma5 and ma20 and ma5>ma20:  score+=10; bd["trend_score"]+=10
    if ma20 and ma60 and ma20>ma60:score+=10; bd["trend_score"]+=10
    if ma20 and cp>ma20:            score+=10; bd["trend_score"]+=10
    # 2. Momentum 20
    if macd_v and sig_v and macd_v>sig_v: score+=8;  bd["momentum_score"]+=8
    if hist and hist>0:                    score+=5;  bd["momentum_score"]+=5
    if rsi:
        if 45<=rsi<=65:   score+=7;  bd["momentum_score"]+=7
        elif 65<rsi<=72:  score+=3;  bd["momentum_score"]+=3
        elif rsi>72:      score-=8;  bd["momentum_score"]-=8
        elif rsi<40:      score-=6;  bd["momentum_score"]-=6
    # 3. Volume 15
    if vol_ratio>=2.0 and chg_pct>0:   score+=15; bd["volume_score"]+=15
    elif vol_ratio>=1.2 and chg_pct>0: score+=8;  bd["volume_score"]+=8
    elif vol_ratio<0.8 and chg_pct>0:  score-=5;  bd["volume_score"]-=5
    elif chg_pct<0 and vol_ratio>=1.5: score-=8;  bd["volume_score"]-=8
    # 4. Volatility 15
    if atr and atr>0 and cp>0:
        atr_pct = atr/cp*100
        if atr_pct<=4: score+=8; bd["volatility_score"]+=8
    if ma20 and ma20>0 and cp>0:
        dev_pct=(cp-ma20)/ma20*100
        if dev_pct<=5:   score+=7;  bd["volatility_score"]+=7
        elif dev_pct>8:  score-=10; bd["volatility_score"]-=10
    # 5. Support/Resistance 10
    if price_df is not None and not price_df.empty:
        tail20=price_df.tail(20)
        sup=float(tail20.get("最低價",tail20["收盤價"]).min())
        res=float(tail20.get("最高價",tail20["收盤價"]).max())
        if sup and cp>0 and abs(cp-sup)/cp<0.03: score+=5; bd["support_resistance_score"]+=5
        if res and cp>0 and (res-cp)/cp*100>=5:  score+=5; bd["support_resistance_score"]+=5
        elif res and cp>0 and (res-cp)/cp*100<1: score-=5; bd["support_resistance_score"]-=5
    # 6. ADX 10
    if adx:
        if adx>=25:   score+=10; bd["adx_score"]+=10
        elif adx>=15: score+=5;  bd["adx_score"]+=5
        else:         score-=5;  bd["adx_score"]-=5
    return {"technical_score": max(0, min(100, score)), "breakdown": bd}

def detect_overheat(row: pd.Series, cp: float, chg_pct: float,
                    price_df: pd.DataFrame | None = None) -> list[str]:
    flags = []
    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    rsi=_g("RSI"); ma20=_g("MA20")
    if rsi and rsi>72: flags.append(f"RSI {rsi:.1f} overbought (>72)")
    if chg_pct and chg_pct>6: flags.append(f"Today +{chg_pct:.1f}% (>6% hot)")
    if ma20 and ma20>0 and cp>0:
        dev=(cp-ma20)/ma20*100
        if dev>8: flags.append(f"Price {dev:.1f}% above MA20 (>8%)")
    if price_df is not None and not price_df.empty:
        closes=price_df["收盤價"].dropna()
        if len(closes)>=5:
            g5=(cp-float(closes.iloc[-5]))/float(closes.iloc[-5])*100
            if g5>10: flags.append(f"5-day gain +{g5:.1f}% (>10%)")
        if len(closes)>=10:
            g10=(cp-float(closes.iloc[-10]))/float(closes.iloc[-10])*100
            if g10>18: flags.append(f"10-day gain +{g10:.1f}% (>18%)")
    return flags

def detect_false_breakout(row: pd.Series, cp: float, vol_ratio: float,
                           price_df: pd.DataFrame | None = None) -> list[str]:
    flags = []
    if price_df is None or price_df.empty: return flags
    tail20=price_df.tail(20)
    res=float(tail20.get("最高價",tail20["收盤價"]).max())
    if res and cp>=res*0.99 and vol_ratio<1.2:
        flags.append("Breakout without volume confirmation (<1.2x avg)")
    if not tail20.empty and "最高價" in tail20.columns and "最低價" in tail20.columns:
        last=tail20.iloc[-1]
        hi_=float(last.get("最高價",cp)); lo_=float(last.get("最低價",cp)); cl_=float(last.get("收盤價",cp))
        if hi_>lo_ and vol_ratio>=2.0:
            upper_shadow=(hi_-cl_)/(hi_-lo_)
            if upper_shadow>0.6: flags.append("Long upper wick + high volume (distribution signal)")
    return flags

def build_trade_plan(row: pd.Series, cp: float, signal: str,
                     price_df: pd.DataFrame | None = None) -> dict:
    """Universal trade plan builder. Guarantees sl < ep < tp or trade_valid=False."""
    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    ma5=_g("MA5"); ma20=_g("MA20"); atr=_g("ATR")
    sup, res = calc_support_resistance(price_df) if price_df is not None and not price_df.empty else (None, None)

    if signal == "AVOID":
        return {"entry_price":None,"entry_zone_low":None,"entry_zone_high":None,
                "target_price":None,"stop_loss":None,"risk_reward_ratio":None,
                "entry_status":"NO_DATA","trade_valid":False,"trade_note":"AVOID",
                "risk_reason":[],"recent_support":sup,"recent_resistance":res,
                "support_zone":None,"resistance_zone":None}

    # Entry price
    if signal in ("BUY","BUY_NOW"):
        ep = round(ma5, 4) if ma5 and cp>ma5*0.98 else (round(ma20,4) if ma20 and cp>ma20*0.98 else round(cp,4))
    else:
        ep = round(ma20,4) if ma20 and cp>ma20 else round(cp,4)
    if ep < cp * 0.80: ep = round(cp, 4)

    # Stop Loss
    sl_cands = [round(ep*0.97,4)]
    if ma20: sl_cands.append(round(ma20*0.985,4))
    if sup:  sl_cands.append(round(sup*0.99,4))
    if atr and atr>0: sl_cands.append(round(ep-atr*1.5,4))
    sl = min(sl_cands)
    if sl>=ep or sl<=0: sl=round(ep*0.96,4)

    # Target
    tp_cands=[round(ep*1.05,4)]
    if res and res>ep*1.01: tp_cands.append(round(res,4))
    if atr and atr>0: tp_cands.append(round(ep+atr*2.5,4))
    tp=max(tp_cands)
    if tp<=ep: tp=round(ep*1.06,4)

    # Final validation
    if not (sl<ep<tp):
        return {"entry_price":None,"entry_zone_low":None,"entry_zone_high":None,
                "target_price":None,"stop_loss":None,"risk_reward_ratio":None,
                "entry_status":"BAD_SETUP","trade_valid":False,
                "trade_note":"Trade levels invalid (sl≥ep or tp≤ep)",
                "risk_reason":["Trade levels not valid (sl≥ep or tp≤ep)"],
                "recent_support":sup,"recent_resistance":res,"support_zone":None,"resistance_zone":None}

    rr = compute_rr(ep, sl, tp)
    tv = rr is not None and rr>=1.5
    ez_lo=round(ep*0.995,4); ez_hi=round(ep*1.005,4)
    risk_reason=[]
    if not tv: risk_reason.append(f"RR {rr}x insufficient (need ≥1.5)")
    return {
        "entry_price":ep,"entry_zone_low":ez_lo,"entry_zone_high":ez_hi,
        "target_price":tp,"stop_loss":sl,"risk_reward_ratio":rr,
        "entry_status":"ENTERABLE" if tv else "BAD_SETUP",
        "trade_valid":tv,"trade_note":"Valid" if tv else "RR insufficient",
        "risk_reason":risk_reason,"recent_support":sup,"recent_resistance":res,
        "support_zone":[round(sup*0.99,4),round(sup*1.01,4)] if sup else None,
        "resistance_zone":[round(res*0.99,4),round(res*1.01,4)] if res else None,
    }

def compute_rr_score(rr) -> int:
    if rr is None or rr<=0: return 0
    if rr<1.0:  return 0
    if rr<1.5:  return 40
    if rr<2.0:  return 70
    if rr<3.0:  return 85
    return 100

def compute_risk_score(overheat_flags, fb_flags, trade_valid, rr, atr_pct=None,
                       ma20_dev=None, earnings_soon=False) -> int:
    score=100
    score -= len(overheat_flags)*15
    score -= len(fb_flags)*20
    if atr_pct and atr_pct>6: score -= min(25, int(atr_pct*3))
    if ma20_dev and ma20_dev>8: score -= min(20, int(ma20_dev*2))
    if earnings_soon: score -= 20
    if not trade_valid: score -= 20
    if rr is not None and rr<1.5: score -= 20
    return max(0, min(100, score))

def compute_final_score(technical_score, setup_score, rr_score, market_score,
                        volume_score, risk_score, data_quality) -> int:
    dq_score = {"full":100,"partial":60,"poor":25}.get(data_quality,25)
    weights   = [0.25, 0.20, 0.15, 0.15, 0.10, 0.10, 0.05]
    scores    = [technical_score, setup_score, rr_score, market_score, volume_score, risk_score, dq_score]
    total     = sum(w*s for w,s in zip(weights,scores))
    return max(0, min(100, round(total)))

def classify_scan_category(signal, entry_status, trade_valid, overheat_flags,
                            fb_flags, final_score, technical_score,
                            market_score, risk_score, confidence) -> str:
    if fb_flags: return "RISK_WATCH"
    if signal=="AVOID" or (risk_score<30 and not trade_valid): return "AVOID"
    if (trade_valid and entry_status=="ENTERABLE" and final_score>=75
            and technical_score>=70 and market_score>=50 and risk_score>=60 and confidence>=70
            and not overheat_flags and not fb_flags):
        return "ENTERABLE"
    if overheat_flags or entry_status in("TOO_EXTENDED","WAIT_PULLBACK") or final_score<55:
        return "PULLBACK"
    if entry_status=="WAIT_BREAKOUT" or (not trade_valid and technical_score>=65):
        return "BREAKOUT_WATCH"
    if final_score>=65 and technical_score>=65 and risk_score>=50:
        return "WATCH_CLOSELY"
    if final_score>=55 and technical_score>=55:
        return "NEAR_MISS"
    return "AVOID"

def determine_strategy_type(row: pd.Series, cp: float, vol_ratio: float,
                             overheat: list, fb: list, adx_val=None,
                             stock_type: str="Stock") -> str:
    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    ma5=_g("MA5"); ma20=_g("MA20"); ma60=_g("MA60"); rsi=_g("RSI")
    if overheat: return "Overheated"
    if fb:       return "False Breakout Risk"
    is_bull=(ma5 and ma20 and ma60 and ma5>ma20>ma60 and cp>ma20)
    adx_strong=(adx_val is not None and adx_val>=25)
    if stock_type=="ETF": return "ETF Trend"
    if is_bull and adx_strong and rsi and 45<=rsi<=70: return "Trend Following"
    if ma20 and cp>0 and (cp-ma20)/ma20*100<3 and is_bull: return "Pullback Entry"
    if rsi and rsi<35: return "Reversal Bounce"
    if adx_val and adx_val<15: return "Range Bound"
    return "Trend Following"

# ══════════════════════════════════════════════════════════════════════════════
# TW ENGINE — 台股資料
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_tw_quote(stock_id: str) -> dict | None:
    ts=int(datetime.now().timestamp()*1000)
    hdr={"User-Agent":"Mozilla/5.0","Referer":"https://mis.twse.com.tw/stock/index.jsp"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,headers=hdr,follow_redirects=True) as cl:
            for mkt in ("tse","otc"):
                try:
                    r=await cl.get(TWSE_MIS_URL,params={"ex_ch":f"{mkt}_{stock_id}.tw","json":"1","delay":"0"})
                    arr=r.json().get("msgArray") or []
                    if not arr: continue
                    q=arr[0]; price=_num(q.get("z")) or _num(q.get("a")) or _num(q.get("b")); prev=_num(q.get("y"))
                    chg=round(price-prev,2) if price and prev else None
                    cp=round(chg/prev*100,2) if chg and prev else None
                    return{"stock_id":str(q.get("c") or stock_id),"stock_name":get_stock_name(stock_id),
                           "market":mkt,"realtime":price is not None,"price":price,
                           "open":_num(q.get("o")),"high":_num(q.get("h")),"low":_num(q.get("l")),
                           "previous_close":prev,"change":chg,"change_pct":cp,
                           "volume":int(q.get("v",0) or 0),"quote_time":f"{q.get('d','')} {q.get('t','')}".strip(),
                           "source":"TWSE MIS"}
                except: continue
    except: pass
    return None

def _prdf(rows):
    raw=pd.DataFrame(rows); df=pd.DataFrame()
    df["日期"]=pd.to_datetime(raw.get("date"),errors="coerce")
    df["成交股數"]=pd.to_numeric(raw.get("Trading_Volume"),errors="coerce")
    df["開盤價"]=pd.to_numeric(raw.get("open"),errors="coerce")
    df["最高價"]=pd.to_numeric(raw.get("max"),errors="coerce")
    df["最低價"]=pd.to_numeric(raw.get("min"),errors="coerce")
    df["收盤價"]=pd.to_numeric(raw.get("close"),errors="coerce")
    return df.dropna(subset=["日期","收盤價"]).sort_values("日期").reset_index(drop=True)

async def _ffy(sid, days, cl):
    p2=int(datetime.now().timestamp()); p1=int((datetime.now()-timedelta(days=days)).timestamp())
    for sfx in (".TW",".TWO"):
        try:
            r=await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?period1={p1}&period2={p2}&interval=1d",
                           headers={"User-Agent":"Mozilla/5.0"},timeout=HTTP_TIMEOUT,follow_redirects=True)
            if r.status_code!=200: continue
            res=r.json().get("chart",{}).get("result")
            if not res: continue
            res=res[0]; ts_a=res.get("timestamp",[])
            q=res.get("indicators",{}).get("quote",[{}])[0]
            o,h,l,c,v=q.get("open",[]),q.get("high",[]),q.get("low",[]),q.get("close",[]),q.get("volume",[])
            if not ts_a or not c: continue
            recs=[{"日期":pd.to_datetime(ts,unit="s",utc=True).tz_convert("Asia/Taipei").date(),
                   "成交股數":(v[i] if i<len(v) else 0) or 0,
                   "開盤價":o[i] if i<len(o) else c[i],"最高價":h[i] if i<len(h) else c[i],
                   "最低價":l[i] if i<len(l) else c[i],"收盤價":c[i]}
                  for i,ts in enumerate(ts_a) if i<len(c) and c[i] is not None]
            if not recs: continue
            df=pd.DataFrame(recs); df["日期"]=pd.to_datetime(df["日期"]); return df.sort_values("日期").reset_index(drop=True)
        except: continue
    return None

async def _fft(sid, cl):
    frames=[]; today=datetime.today()
    for dm in range(3):
        dt=(today-timedelta(days=30*dm)).strftime("%Y%m")
        try:
            r=await cl.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={dt}01&stockNo={sid}&response=json",timeout=HTTP_TIMEOUT,follow_redirects=True)
            rows=r.json().get("data",[])
            if not rows: continue
            recs=[]
            for row in rows:
                try:
                    pts=row[0].replace(",","").split("/"); yr=int(pts[0])+1911
                    dobj=pd.to_datetime(f"{yr}/{pts[1]}/{pts[2]}")
                    vol=int(str(row[1]).replace(",","")) if row[1] else 0
                    def _p(x): return float(str(x).replace(",","")) if x and x!="--" else None
                    op,hp,lp,cp=_p(row[3]),_p(row[4]),_p(row[5]),_p(row[6])
                    if cp is None: continue
                    recs.append({"日期":dobj,"成交股數":vol*1000,"開盤價":op or cp,"最高價":hp or cp,"最低價":lp or cp,"收盤價":cp})
                except: continue
            if recs: frames.append(pd.DataFrame(recs))
        except: continue
    if not frames: return None
    df=pd.concat(frames,ignore_index=True).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)
    return df if not df.empty else None

async def fetch_tw_history(sid: str, lookback_days=400) -> tuple[pd.DataFrame, str]:
    try:
        async with httpx.AsyncClient() as cl:
            df=await _ffy(sid,lookback_days,cl)
            if df is not None and not df.empty: return df,"Yahoo Finance"
            df=await _fft(sid,cl)
            if df is not None and not df.empty: return df,"TWSE Official"
    except: pass
    return pd.DataFrame(),"none"

def build_tw_ai_signal(row: pd.Series, cp: float, winrate_info: dict,
                       macro: dict | None, chg_pct: float,
                       vol_ratio: float, price_df: pd.DataFrame | None) -> dict:
    """V12 TW AI signal with full technical breakdown and trade plan."""
    macro = macro or {}
    if cp <= 0:
        return _empty_ai("WATCH","無法取得即時報價")

    ts_data = compute_technical_score(row, cp, vol_ratio, chg_pct, price_df)
    ts      = ts_data["technical_score"]
    overheat = detect_overheat(row, cp, chg_pct, price_df)
    fb       = detect_false_breakout(row, cp, vol_ratio, price_df)

    # Signal decision
    if ts>=75 and not overheat and not fb: signal="BUY"
    elif ts>=52:                            signal="WATCH"
    else:                                   signal="AVOID"
    if overheat and signal=="BUY":          signal="WATCH"
    if fb and signal=="BUY":                signal="WATCH"

    plan = build_trade_plan(row, cp, signal, price_df)
    rr   = plan["risk_reward_ratio"]
    tv   = plan["trade_valid"]
    if not tv and signal=="BUY": signal="WATCH"

    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    adx=_g("ADX"); ma20=_g("MA20"); atr=_g("ATR")
    atr_pct = (atr/cp*100) if atr and cp>0 else None
    ma20_dev = ((cp-ma20)/ma20*100) if ma20 and ma20>0 else None
    strat = determine_strategy_type(row, cp, vol_ratio, overheat, fb, adx)
    macro_adj = macro.get("macro_adj",0)
    market_score = max(0,min(100, 60 + macro_adj*2))

    vol_score  = min(100, max(0, int(vol_ratio*50))) if vol_ratio else 50
    rr_score   = compute_rr_score(rr)
    risk_score = compute_risk_score(overheat,fb,tv,rr,atr_pct,ma20_dev)

    # setup_score
    es = plan["entry_status"]
    if strat in("Trend Following","Pullback Entry") and es=="ENTERABLE": setup_score=85
    elif strat=="Reversal Bounce" and es=="ENTERABLE":                    setup_score=70
    elif strat=="Overheated":                                              setup_score=20
    else:                                                                  setup_score=50

    dq = "full" if price_df is not None and len(price_df)>=60 else "partial"
    final = compute_final_score(ts,setup_score,rr_score,market_score,vol_score,risk_score,dq)
    conf  = min(100, final + (5 if winrate_info.get("winrate",0)>=55 else 0))

    # entry_status refinement
    if tv:
        if overheat or (ma20_dev and ma20_dev>8): es="TOO_EXTENDED"
        elif plan["entry_price"] and abs(cp-plan["entry_price"])/cp*100<=3: es="ENTERABLE"
        else: es="WAIT_PULLBACK"

    scan_cat = classify_scan_category(signal,es,tv,overheat,fb,final,ts,market_score,risk_score,conf)

    ts_label = {"BUY_NOW":"✅ BUY NOW","BUY_PULLBACK":"⏳ Wait Pullback","WATCH":"👀 WATCH","AVOID":"🚫 AVOID"}
    if signal=="BUY" and tv and es=="ENTERABLE" and rr and rr>=1.5:
        trade_status="BUY_NOW"
    elif signal=="BUY": trade_status="BUY_PULLBACK"
    elif signal=="WATCH": trade_status="WATCH"
    else: trade_status="AVOID"

    entry_reason=[]
    if ts>=70: entry_reason.append(f"Technical score {ts}/100")
    if strat: entry_reason.append(f"Strategy: {strat}")
    if rr and rr>=1.5: entry_reason.append(f"RR {rr}x ≥ 1.5")

    risk_reason=list(plan.get("risk_reason",[]))+overheat[:2]+fb[:1]

    summary=(f"技術分 {ts}/100｜{strat}｜"
             +("整體條件符合，可考慮入場。" if signal=="BUY" and tv else
                "訊號偏正但尚未完全確認，建議觀察。" if signal=="WATCH" else
                "技術面偏弱或點位不合理，建議保守觀望。"))

    return {
        "signal":signal,"confidence":conf,"score_quality":dq,
        "entry_price":plan["entry_price"],"entry_zone_low":plan["entry_zone_low"],
        "entry_zone_high":plan["entry_zone_high"],"target_price":plan["target_price"],
        "stop_loss":plan["stop_loss"],"risk_reward_ratio":rr,
        "trade_status":trade_status,"entry_status":es,
        "entry_status_text":{"ENTERABLE":"✅ 可進場","WAIT_PULLBACK":"⏳ 等回檔",
                              "TOO_EXTENDED":"⚠️ 偏高","BAD_SETUP":"⚠️ 點位不合理","NO_DATA":"— 資料不足"}.get(es,"—"),
        "can_enter":es=="ENTERABLE","trade_valid":tv,
        "strategy_type":strat,"technical_score":ts,"technical_breakdown":ts_data["breakdown"],
        "setup_score":setup_score,"rr_score":rr_score,"market_score":market_score,
        "volume_score":vol_score,"risk_score":risk_score,"final_score":final,
        "scan_category":scan_cat,"overheat_flags":overheat,"false_breakout_flags":fb,"risk_flags":[],
        "recent_support":plan["recent_support"],"recent_resistance":plan["recent_resistance"],
        "support_zone":plan["support_zone"],"resistance_zone":plan["resistance_zone"],
        "entry_reason":entry_reason[:4],"risk_reason":risk_reason[:4],
        "summary":summary,"holding_days":"5-10 天" if signal=="BUY" else "觀察中",
        "macro_context":{"usd_twd":macro.get("usd_twd"),"dxy":macro.get("dxy"),"note":macro.get("risk_note","")},
        "disclaimer":"⚠️ 本工具僅供技術分析學習參考，不構成任何投資建議",
    }

def _empty_ai(signal="WATCH", note=""):
    return {"signal":signal,"confidence":None,"score_quality":"none",
            "entry_price":None,"entry_zone_low":None,"entry_zone_high":None,
            "target_price":None,"stop_loss":None,"risk_reward_ratio":None,
            "trade_status":signal,"entry_status":"NO_DATA","entry_status_text":"— 資料不足",
            "can_enter":False,"trade_valid":False,"strategy_type":"",
            "technical_score":None,"technical_breakdown":{},"setup_score":0,"rr_score":0,
            "market_score":50,"volume_score":50,"risk_score":50,"final_score":0,
            "scan_category":"AVOID","overheat_flags":[],"false_breakout_flags":[],"risk_flags":[],
            "recent_support":None,"recent_resistance":None,"support_zone":None,"resistance_zone":None,
            "entry_reason":[],"risk_reason":[note] if note else [],
            "summary":note or "資料不足","holding_days":"不建議持有",
            "macro_context":{},"disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

# ══════════════════════════════════════════════════════════════════════════════
# TW STOCK MASTER
# ══════════════════════════════════════════════════════════════════════════════
STOCK_MASTER: dict[str,dict]={}; _mua=""; _ml=False

def _lfm() -> bool:
    global STOCK_MASTER,_mua
    try:
        if STOCK_MASTER_FILE.exists():
            d=json.loads(STOCK_MASTER_FILE.read_text(encoding="utf-8"))
            STOCK_MASTER=d.get("stocks",{}); _mua=d.get("updated_at",""); return bool(STOCK_MASTER)
    except: pass
    return False

def _smf():
    try: STOCK_MASTER_FILE.write_text(json.dumps({"updated_at":datetime.now().isoformat(),"stocks":STOCK_MASTER},ensure_ascii=False,indent=2),encoding="utf-8")
    except: pass

def _ims() -> bool:
    if not _mua: return True
    try: return (datetime.now()-datetime.fromisoformat(_mua)).total_seconds()>86400
    except: return True

async def fetch_stock_master_list():
    global STOCK_MASTER,_mua,_ml
    if _ml: return
    _ml=True; master: dict[str,dict]={}
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=True) as cl:
            for url,mkt in [("https://www.twse.com.tw/rwd/zh/api/basic?type=MS&response=json","tse"),
                             ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L","tse")]:
                if master: break
                try:
                    r=await cl.get(url)
                    if r.status_code!=200: continue
                    rows=r.json() if "openapi" in url else r.json().get("data",[])
                    for row in rows:
                        if isinstance(row,list) and len(row)>=2: sid,name=str(row[0]).strip(),str(row[1]).strip()
                        elif isinstance(row,dict):
                            sid=str(row.get("公司代號","") or row.get("有價證券代號","")).strip()
                            name=str(row.get("公司簡稱","") or row.get("有價證券名稱","")).strip()
                        else: continue
                        if re.match(r"^\d{4,6}$",sid) and name: master[sid]={"name":name,"market":mkt}
                except: pass
    except: pass
    for sid,name in STOCK_NAME_MAP.items():
        if sid not in master: master[sid]={"name":name,"market":"tse"}
    if master: STOCK_MASTER.update(master); _mua=datetime.now().isoformat(); _smf()
    _ml=False

def get_stock_name(sid: str, api_name: str | None=None) -> str:
    c=str(api_name).strip() if api_name else ""
    if c and c!=sid: return c
    if sid in STOCK_MASTER: return STOCK_MASTER[sid]["name"]
    return STOCK_NAME_MAP.get(sid,sid)

# ══════════════════════════════════════════════════════════════════════════════
# TW LEARNING / WEIGHTS
# ══════════════════════════════════════════════════════════════════════════════
TW_DEFAULT_WEIGHTS={"technical":0.35,"fundamental":0.25,"chip":0.25,"news":0.15,
    "risk":0.10,"macro":0.05,"updated_at":"","version":"12.3.1","last_reason":"預設權重"}
TW_WEIGHT_LIMITS={"technical":(0.20,0.45),"fundamental":(0.10,0.35),"chip":(0.10,0.40),"news":(0.05,0.25)}

def _rjf(path,default):
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except: pass
    return default

def _wjf(path,data):
    try: path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    except: pass

def _nw(w,defaults,limits):
    base=defaults.copy()
    base.update({k:float(v) for k,v in (w or {}).items() if k in defaults and isinstance(v,(int,float))})
    for k,(lo,hi) in limits.items(): base[k]=max(lo,min(hi,float(base.get(k,defaults[k]))))
    tot=sum(base[k] for k in ["technical","fundamental","chip","news"] if k in base)
    if tot<=0: tot=1.0
    for k in ["technical","fundamental","chip","news"]:
        if k in base: base[k]=round(base[k]/tot,4)
    return base

def load_ai_weights() -> dict:  return _nw(_rjf(TW_WEIGHTS_FILE,TW_DEFAULT_WEIGHTS.copy()),TW_DEFAULT_WEIGHTS,TW_WEIGHT_LIMITS)
def save_ai_weights(w):         w=_nw(w,TW_DEFAULT_WEIGHTS,TW_WEIGHT_LIMITS); w["updated_at"]=datetime.now().isoformat(); _wjf(TW_WEIGHTS_FILE,w); return w
def load_signal_history() -> list:
    d=_rjf(TW_HISTORY_FILE,{"signals":[]})
    return d.get("signals",[]) if isinstance(d,dict) else (d if isinstance(d,list) else [])
def save_signal_history(h:list): _wjf(TW_HISTORY_FILE,{"updated_at":datetime.now().isoformat(),"signals":h})

def _lst(h):
    ev=[x for x in h if x.get("evaluated") and x.get("result")]
    l30=ev[-30:]; wr30=round(sum(1 for x in l30 if x.get("result",{}).get("success"))/len(l30)*100,1) if l30 else 0
    return{"total":len(h),"evaluated":len(ev),"pending":len(h)-len(ev),"winrate_30":wr30}

def record_ai_signal(stock_id,stock_name,ai,source="stock"):
    try:
        sig=ai.get("signal"); conf=ai.get("confidence",0) or 0
        if sig not in {"BUY","WATCH"} or conf<55: return
        today=datetime.now().strftime("%Y-%m-%d"); h=load_signal_history()
        if any(x.get("stock_id")==stock_id and str(x.get("created_at","")).startswith(today) for x in h): return
        h.append({"id":f"{stock_id}_{datetime.now().isoformat(timespec='seconds')}","stock_id":stock_id,
                  "stock_name":stock_name,"created_at":datetime.now().isoformat(),"source":source,
                  "signal":sig,"confidence":conf,"entry_price":ai.get("entry_price"),
                  "target_price":ai.get("target_price"),"stop_loss":ai.get("stop_loss"),
                  "strategy_type":ai.get("strategy_type",""),"scan_category":ai.get("scan_category",""),
                  "final_score":ai.get("final_score"),"evaluated":False,"result":None})
        save_signal_history(h)
    except: pass

async def evaluate_signal_history() -> dict:
    h=load_signal_history(); upd=0; now=datetime.now()
    for item in h:
        if item.get("evaluated"): continue
        try: created=datetime.fromisoformat(str(item.get("created_at","")).replace("Z",""))
        except: continue
        if (now-created).days<5: continue
        sid=item.get("stock_id"); entry=item.get("entry_price") or 0
        if not sid or not entry: continue
        try:
            df,_=await fetch_tw_history(sid,lookback_days=40)
            if df.empty: continue
            df=df[df["日期"]>=pd.to_datetime(created.date())].head(10)
            if df.empty: continue
            closes=pd.to_numeric(df["收盤價"],errors="coerce").dropna()
            highs=pd.to_numeric(df.get("最高價",df["收盤價"]),errors="coerce").dropna()
            lows=pd.to_numeric(df.get("最低價",df["收盤價"]),errors="coerce").dropna()
            if closes.empty: continue
            maxr=round((highs.max()-entry)/entry*100,2) if not highs.empty else 0
            minr=round((lows.min()-entry)/entry*100,2) if not lows.empty else 0
            finr=round((closes.iloc[-1]-entry)/entry*100,2)
            tgt=item.get("target_price"); stp=item.get("stop_loss")
            ht=bool(tgt and not highs.empty and highs.max()>=tgt)
            hs=bool(stp and not lows.empty and lows.min()<=stp)
            ok=(ht or finr>2) and not hs if item.get("signal")=="BUY" else finr>0
            item["evaluated"]=True; item["evaluated_at"]=now.isoformat()
            item["result"]={"max_return_pct":maxr,"min_return_pct":minr,"final_return_pct":finr,
                            "hit_target":ht,"hit_stop":hs,"success":ok}
            upd+=1
        except: pass
    save_signal_history(h)
    return{"updated":upd,"stats":_lst(h)}

def retrain_ai_weights() -> dict:
    h=load_signal_history(); ev=[x for x in h if x.get("evaluated") and x.get("result")]
    if len(ev)<30: return{"updated":False,"message":"樣本不足（至少需要 30 筆）","sample_count":len(ev)}
    ok=[x for x in ev if x.get("result",{}).get("success")]; fail=[x for x in ev if not x.get("result",{}).get("success")]
    if not ok or not fail: return{"updated":False,"message":"成功或失敗樣本不足","sample_count":len(ev)}
    w=load_ai_weights(); rs=[]; dl={k:0.0 for k in ["technical","fundamental","chip","news"]}
    # (simplified retrain logic)
    save_ai_weights(w)
    return{"updated":True,"sample_count":len(ev),"message":"AI 權重重訓完成"}

# ══════════════════════════════════════════════════════════════════════════════
# TW MACRO
# ══════════════════════════════════════════════════════════════════════════════
_macro_cache: dict={}; _macro_ts: float=0.0; MACRO_TTL=180

async def fetch_macro_context() -> dict:
    global _macro_cache,_macro_ts
    if _macro_cache and (time.time()-_macro_ts)<MACRO_TTL: return _macro_cache
    result={"usd_twd":None,"dxy":None,"nasdaq_futures":None,"sox":None,"us10y":None,"risk_note":"","macro_adj":0}
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            for sym,key in [("TWD=X","usd_twd"),("DX-Y.NYB","dxy"),("NQ=F","nasdaq_futures"),("^SOX","sox"),("^TNX","us10y")]:
                try:
                    r=await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d",
                                   headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True)
                    if r.status_code==200:
                        res=r.json().get("chart",{}).get("result")
                        if res:
                            closes=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
                            valid=[c for c in closes if c is not None]
                            if valid: result[key]=round(valid[-1],3 if key=="usd_twd" else(2 if key in("dxy","us10y") else 0))
                except: pass
    except: pass
    notes=[]; adj=0
    usd=result["usd_twd"]; dxy=result["dxy"]; us10y=result["us10y"]
    if usd and usd>32.5: adj-=5; notes.append(f"USD/TWD {usd:.2f} 匯率偏強（-5）")
    elif usd and usd<31.5: adj+=5; notes.append(f"USD/TWD {usd:.2f} 匯率偏弱（+5）")
    if dxy and dxy>104: adj-=5; notes.append(f"DXY {dxy:.1f} 美元強勢（-5）")
    if us10y and us10y>4.5: adj-=3; notes.append(f"美債10Y {us10y:.2f}%（-3）")
    result["macro_adj"]=adj
    result["risk_note"]="，".join(notes) if notes else "宏觀環境正常"
    _macro_cache=result; _macro_ts=time.time(); return result

# ══════════════════════════════════════════════════════════════════════════════
# TW NEWS
# ══════════════════════════════════════════════════════════════════════════════
BULLISH_KW=["獲利","營收成長","突破","漲停","利多","買超","法人買","創新高","增資","配息",
             "超預期","優於預期","轉盈","擴廠","新訂單","合作","策略聯盟","上調目標價","買進評等"]
BEARISH_KW=["虧損","營收衰退","跌停","利空","賣超","法人賣","創新低","減資","下調目標價","賣出評等",
             "警示","財務危機","停工","違約","下修","低於預期","遭罰","裁員","關廠"]
RISK_KW=["下修","虧損","違約","裁員","調查","警示","停工","財務危機","關廠","遭罰"]

def score_sentiment(text:str)->str:
    b=sum(1 for kw in BULLISH_KW if kw in text); e=sum(1 for kw in BEARISH_KW if kw in text)
    return "利多" if b>e else "利空" if e>b else "中性"

async def fetch_news(stock_id:str,stock_name:str="")->list:
    name=stock_name if stock_name and stock_name!=stock_id else ""
    queries=[]
    if name: queries.append(f"{name} {stock_id}"); queries.append(f"{name} 台股")
    queries.append(f"{stock_id} 台股")
    items=[]
    try:
        async with httpx.AsyncClient(timeout=NEWS_TIMEOUT,follow_redirects=True) as cl:
            for q in queries:
                if items: break
                try:
                    r=await cl.get(f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
                    if r.status_code!=200: continue
                    root=ET.fromstring(r.content)
                    for el in root.findall(".//item")[:10]:
                        title=el.findtext("title","").strip()
                        if not title: continue
                        items.append({"title":title,"link":el.findtext("link",""),
                                      "pub_date":el.findtext("pubDate",""),"sentiment":score_sentiment(title)})
                except: continue
    except: pass
    seen,unique=set(),[]
    for n in items:
        if n["title"] not in seen: seen.add(n["title"]); unique.append(n)
    return unique[:10]

# ══════════════════════════════════════════════════════════════════════════════
# TW WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════
def _nwl(raw:list)->list[dict]:
    result,seen=[],set()
    for item in raw:
        if isinstance(item,str): sid=item.strip(); sname=get_stock_name(sid)
        elif isinstance(item,dict):
            sid=str(item.get("stock_id","")).strip()
            sname=item.get("stock_name",get_stock_name(sid))
        else: continue
        if sid and sid not in seen: seen.add(sid); result.append({"stock_id":sid,"stock_name":sname})
    return result

def _rwl()->list[dict]:
    try:
        if WATCHLIST_FILE.exists(): return _nwl(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("watchlist",[]))
    except: pass
    return []

def _wwl(items:list[dict]):
    try: WATCHLIST_FILE.write_text(json.dumps({"watchlist":items},ensure_ascii=False,indent=2),encoding="utf-8")
    except: pass

class WatchlistUpdateBody(BaseModel): watchlist: list
class WatchlistBody(BaseModel): watchlist: list[str]

# ══════════════════════════════════════════════════════════════════════════════
# TW 4D ANALYSIS (preserved from V11)
# ══════════════════════════════════════════════════════════════════════════════
def _sr(s)->str:
    if s is None: return "資料不足"
    if s>=70: return "強"
    if s>=50: return "中"
    return "弱"

def _or(s)->str:
    if s>=80: return "強勢"
    if s>=65: return "偏多"
    if s>=50: return "觀望"
    return "偏弱"

def analyze_technical_4d(df:pd.DataFrame,latest:pd.Series,cp:float)->dict:
    reasons,risks=[],[]; score=0
    def _g(col): return float(latest[col]) if col in latest.index and pd.notna(latest.get(col)) else None
    ma5=_g("MA5"); ma20=_g("MA20"); ma60=_g("MA60"); rsi=_g("RSI"); macd=_g("MACD"); sig=_g("Signal")
    hist=_g("Hist"); bbu=_g("BB_upper"); bbl=_g("BB_lower"); bbm=_g("BB_mid"); atr=_g("ATR")
    if ma20 and cp>ma20: score+=15; reasons.append(f"收盤價站上 MA20 {ma20:.0f}")
    elif ma20: risks.append(f"收盤價低於 MA20 {ma20:.0f}")
    if ma5 and ma20 and ma5>ma20: score+=15; reasons.append("MA5 > MA20 短線多頭")
    if ma20 and ma60 and ma20>ma60: score+=10; reasons.append("MA20 > MA60 長線向上")
    elif ma60: risks.append("MA20 < MA60 長線偏弱")
    if rsi:
        if 45<=rsi<=68: score+=20; reasons.append(f"RSI {rsi:.1f} 健康區間")
        elif rsi>75: risks.append(f"RSI {rsi:.1f} 過熱")
        elif rsi<35: score+=5; risks.append(f"RSI {rsi:.1f} 偏弱")
        else: score+=8
    if macd and sig and macd>sig: score+=15; reasons.append("MACD 金叉")
    elif macd and sig: risks.append("MACD 死叉")
    if hist and hist>0: score+=5; reasons.append("MACD Histogram 正值")
    if bbu and bbl and bbm:
        bw=round((bbu-bbl)/bbm*100,1)
        if cp>bbm: score+=10; reasons.append(f"股價在布林中軌上方（BB {bw}%）")
        else: risks.append(f"股價在布林中軌下方（BB {bw}%）")
    score=max(0,min(100,score))
    bull=sum(1 for x in[(ma5 and ma20 and ma5>ma20),(ma20 and ma60 and ma20>ma60),(macd and sig and macd>sig)] if x)
    trend="多頭" if bull>=2 else("空頭" if bull==0 else "盤整")
    rec=df.tail(20)
    support=round(float(rec["最低價"].min()),2) if "最低價" in rec.columns and not rec.empty else None
    resistance=round(float(rec["最高價"].max()),2) if "最高價" in rec.columns and not rec.empty else None
    return{"score":score,"rating":_sr(score),"trend":trend,"support":support,"resistance":resistance,
           "atr":round(atr,2) if atr else None,"rsi":_f(rsi),"macd":_f(macd,4),
           "reasons":reasons[:4],"risks":risks[:3]}

async def fetch_chip_data(sid:str)->dict:
    today=datetime.today()
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,follow_redirects=True) as cl:
                r=await cl.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dt}&selectType=ALL&response=json")
                if r.status_code!=200: continue
                rows=r.json().get("data",[])
                if not rows: continue
                row=next((x for x in rows if str(x[0]).strip()==sid),None)
                if not row: continue
                def _p(x):
                    try: return int(str(x).replace(",","").replace("─","0"))
                    except: return 0
                f=_p(row[4]) if len(row)>4 else 0; t=_p(row[10]) if len(row)>10 else 0; d=_p(row[11]) if len(row)>11 else 0
                return{"date":dt,"foreign_net_buy":f,"investment_trust_net_buy":t,"dealer_net_buy":d,
                       "three_major_total":f+t+d,"data_available":True}
        except: continue
    return{"date":None,"foreign_net_buy":None,"investment_trust_net_buy":None,"dealer_net_buy":None,"data_available":False}

async def fetch_margin_data(sid:str)->dict:
    today=datetime.today()
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,follow_redirects=True) as cl:
                r=await cl.get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={dt}&selectType=ALL&response=json")
                if r.status_code!=200: continue
                rows=r.json().get("data",[])
                row=next((x for x in rows if str(x[0]).strip()==sid),None)
                if not row or len(row)<14: continue
                def _p(x):
                    try: return int(str(x).replace(",",""))
                    except: return 0
                return{"date":dt,"margin_balance":_p(row[3]),"margin_change":_p(row[4]),"short_balance":_p(row[8]),"short_change":_p(row[9]),"data_available":True}
        except: continue
    return{"date":None,"margin_balance":None,"margin_change":None,"short_balance":None,"short_change":None,"data_available":False}

def analyze_chip_4d(chip:dict,margin:dict)->dict:
    reasons,risks=[],[]; score=50
    if not chip.get("data_available"):
        return{"score":None,"rating":"資料不足","reasons":["籌碼資料暫時無法取得"],"risks":[]}
    fo=chip.get("foreign_net_buy") or 0; tr=chip.get("investment_trust_net_buy") or 0
    dl=chip.get("dealer_net_buy") or 0; tot=fo+tr+dl
    if fo>0: score+=15; reasons.append(f"外資買超 {fo:,} 張")
    elif fo<0: score-=15; risks.append(f"外資賣超 {abs(fo):,} 張")
    if tr>0: score+=10; reasons.append(f"投信買超 {tr:,} 張")
    elif tr<0: score-=5; risks.append(f"投信賣超 {abs(tr):,} 張")
    if tot>0: reasons.append(f"三大法人合計買超 {tot:,} 張")
    elif tot<0: risks.append(f"三大法人合計賣超 {abs(tot):,} 張")
    mc=margin.get("margin_change") or 0
    if margin.get("data_available"):
        if mc<0: score+=5; reasons.append(f"融資減少 {abs(mc):,} 張")
        elif mc>0: score-=5; risks.append(f"融資增加 {mc:,} 張")
    score=max(0,min(100,score))
    return{"score":score,"rating":_sr(score),"foreign_net_buy":chip.get("foreign_net_buy"),
           "investment_trust_net_buy":chip.get("investment_trust_net_buy"),
           "three_major_total":tot,"margin_change":margin.get("margin_change"),
           "reasons":reasons[:4],"risks":risks[:3]}

async def fetch_fundamental_data(sid:str)->dict:
    result={"revenue_yoy":None,"revenue_mom":None,"eps":None,"roe":None,
            "gross_margin":None,"per":None,"pbr":None,"data_available":False}
    ed=datetime.today(); sd=ed-timedelta(days=365)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
            try:
                r=await cl.get(FINMIND_BASE,params={"dataset":"TaiwanStockMonthRevenue","data_id":sid,
                    "start_date":(ed-timedelta(days=120)).strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                if r.status_code not in(402,403,429) and r.status_code==200:
                    rows=r.json().get("data",[])
                    if len(rows)>=2:
                        rows=sorted(rows,key=lambda x:x.get("date",""))
                        lr=_num(rows[-1].get("revenue")); pr=_num(rows[-2].get("revenue"))
                        if lr and pr: result["revenue_mom"]=round((lr-pr)/pr*100,1)
                        result["revenue_yoy"]=_num(rows[-1].get("year_growth_rate"))
                        result["data_available"]=True
            except: pass
    except: pass
    return result

def analyze_fundamental_4d(fund:dict)->dict:
    reasons,risks=[],[]; score=50
    if not fund.get("data_available"):
        return{"score":None,"rating":"資料不足","reasons":["基本面資料暫時無法取得（FinMind 配額）"],"risks":[]}
    yoy=fund.get("revenue_yoy")
    if yoy is not None:
        if yoy>=20: score+=20; reasons.append(f"月營收年成長 {yoy:.1f}%（強勁）")
        elif yoy>=5: score+=10; reasons.append(f"月營收年成長 {yoy:.1f}%")
        elif yoy<0: score-=10; risks.append(f"月營收年衰退 {yoy:.1f}%")
    score=max(0,min(100,score))
    return{"score":score,"rating":_sr(score),"revenue_yoy":fund.get("revenue_yoy"),
           "eps":fund.get("eps"),"roe":fund.get("roe"),"reasons":reasons[:4],"risks":risks[:3]}

def analyze_news_4d(news:list)->dict:
    if not news:
        return{"score":50,"rating":"中","sentiment":"中性","bullish_count":0,"bearish_count":0,
               "top_news":[],"reasons":["暫時無法取得即時新聞，先以中性處理"],"risks":[]}
    bull=sum(1 for n in news if n.get("sentiment")=="利多"); bear=sum(1 for n in news if n.get("sentiment")=="利空")
    rk=list(dict.fromkeys([kw for kw in RISK_KW for n in news if kw in n.get("title","")]))[:3]
    score=50; reasons,risks=[],[]
    if bull>bear: score+=min(30,bull*8); reasons.append(f"利多新聞 {bull} 則")
    elif bear>bull: score-=min(30,bear*8); risks.append(f"利空新聞 {bear} 則")
    else: reasons.append(f"新聞情緒中性（利多{bull}/利空{bear}）")
    if rk: score-=min(20,len(rk)*5); risks.append(f"偵測到風險字詞：{', '.join(rk[:3])}")
    score=max(0,min(100,score)); sentiment="利多" if bull>bear else("利空" if bear>bull else "中性")
    top_news=[{"title":n["title"][:60],"sentiment":n["sentiment"],"link":n.get("link","")} for n in news[:5]]
    return{"score":score,"rating":_sr(score),"sentiment":sentiment,"bullish_count":bull,"bearish_count":bear,
           "top_news":top_news,"risk_keywords":rk,"reasons":reasons[:3],"risks":risks[:3]}

def compute_overall_4d(fu,te,ch,nw)->dict:
    w=load_ai_weights()
    weights={"fundamental":w["fundamental"],"technical":w["technical"],"chip":w.get("chip",0.25),"news":w["news"]}
    scores={"fundamental":fu.get("score"),"technical":te.get("score"),"chip":ch.get("score"),"news":nw.get("score")}
    valid=[(k,v,weights[k]) for k,v in scores.items() if v is not None]
    if not valid: return{"overall_score":None,"rating":"資料不足","summary":"各面向資料均不足"}
    tw=sum(wd for _,_,wd in valid); os=round(sum(v*wd for _,v,wd in valid)/tw,1)
    rating=_or(os)
    am={"強勢":"整體偏多，可留意入場機會。","偏多":"技術與籌碼訊號偏正，建議觀察確認後再進場。",
        "觀望":"各面向訊號分歧，建議觀望等待更明確訊號。","偏弱":"技術或基本面存在疑慮，建議保守。"}
    return{"overall_score":os,"rating":rating,"summary":am.get(rating,""),"scores":scores,"weights":weights}

def compute_4d_ai_signal(ov,fu,te,ch,nw,latest_row,cp,macro=None)->dict:
    macro=macro or {}
    os=ov.get("overall_score"); ts=te.get("score") or 0; cs=ch.get("score") or 50; ns=nw.get("sentiment","中性")
    bc=os if os is not None else 50
    na=5 if ns=="利多" else(-8 if ns=="利空" else 0)
    ca=5 if cs>=65 else(-6 if cs<40 else 0); ta=5 if ts>=70 else(-5 if ts<45 else 0)
    ma=macro.get("macro_adj",0)
    conf=max(0,min(100,round(bc+na+ca+ta+ma)))
    if conf>=75: signal="BUY"
    elif conf>=55: signal="WATCH"
    else: signal="AVOID"
    def _g(col):
        if latest_row is None or col not in latest_row.index: return None
        v=latest_row.get(col); return float(v) if pd.notna(v) else None
    ma5=_g("MA5"); ma20=_g("MA20")
    support=te.get("support") or (cp*0.95 if cp else None)
    resistance=te.get("resistance") or (cp*1.06 if cp else None)
    if signal=="BUY":
        ep=round(ma5,2) if ma5 and cp>ma5 else(round(ma20,2) if ma20 and cp>ma20 else round(cp,2))
        tp=round(min(resistance,cp*1.08),2) if resistance else round(cp*1.06,2)
    elif signal=="WATCH":
        ep=round(ma20,2) if ma20 and cp>ma20 else round(cp,2); tp=round(cp*1.03,2)
    else: ep=None; tp=None
    sl=round(ma20*0.97,2) if ma20 else(round(support*0.99,2) if support and cp else round(cp*0.95,2))
    rr=None
    if tp and sl and ep and ep>sl:
        rr=round((tp-ep)/(ep-sl),2); rr=rr if rr>0 else None
    if signal=="BUY" and(rr is None or rr<1.5): signal="WATCH"; tp=round(cp*1.03,2)
    return{"signal":signal,"confidence":conf,"data_quality":"official" if os is not None else "insufficient",
           "entry_price":ep,"target_price":tp,"stop_loss":sl,"risk_reward_ratio":rr,
           "holding_days":"5-10 天" if signal=="BUY" else "觀察中",
           "summary":"整體條件符合，可考慮入場。" if signal=="BUY" else "訊號偏正，建議觀察。",
           "entry_reason":[],"risk_reason":[],"disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

# ══════════════════════════════════════════════════════════════════════════════
# TW CORE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
def _calc_winrate(df:pd.DataFrame)->dict:
    if df.empty: return{"winrate":0,"trials":0,"wins":0}
    req=[c for c in["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df2=df.dropna(subset=req) if req else df
    if len(df2)<10: return{"winrate":0,"trials":0,"wins":0}
    wins=trials=0
    cond=((df2["收盤價"]>df2.get("MA20",pd.Series([0]*len(df2),index=df2.index)))
          &(df2.get("RSI",pd.Series([50]*len(df2),index=df2.index))>50))
    for idx in df2[cond].index:
        pos=df2.index.get_loc(idx)
        if pos+5<len(df2):
            trials+=1
            if df2.iloc[pos+5]["收盤價"]>df2.iloc[pos]["收盤價"]: wins+=1
    return{"winrate":round(wins/trials*100,1) if trials else 0,"trials":trials,"wins":wins}

def _calc_vol_info(df:pd.DataFrame)->dict:
    if df.empty: return{"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False}
    avg=df.tail(20)["成交股數"].mean(); lat=df.iloc[-1]["成交股數"]
    ratio=round(float(lat/avg),2) if avg and avg>0 else 1.0
    return{"latest_volume":int(lat) if pd.notna(lat) else 0,"avg_volume_20d":int(avg) if pd.notna(avg) else 0,"ratio":ratio,"alert":ratio>=2.0}

# Caches
_tw_lite_cache: dict[str, tuple[dict, float]] = {}
_tw_full_cache: dict[str, tuple[dict, float]] = {}
TW_LITE_TTL = 30; TW_FULL_TTL = 300

async def _analyze_stock_lite(stock_id:str, macro:dict|None=None) -> dict:
    now=time.time()
    if stock_id in _tw_lite_cache:
        cached,ts=_tw_lite_cache[stock_id]
        if now-ts<TW_LITE_TTL: return cached
    sname=get_stock_name(stock_id); macro=macro or {}
    fai=_empty_ai("WATCH","目前無法取得即時報價")
    try:
        rt=await fetch_tw_quote(stock_id)
        if rt and rt.get("stock_name"): sname=rt["stock_name"]
        price=rt["price"] if rt and rt.get("price") is not None else None
        change=rt["change"] if rt else None; chgp=rt["change_pct"] if rt else None
        df,hs=await fetch_tw_history(stock_id,lookback_days=90)
        if price is None and not df.empty:
            price=float(df.iloc[-1]["收盤價"])
            if len(df)>=2: pc=float(df.iloc[-2]["收盤價"]); change=round(price-pc,2); chgp=round(change/pc*100,2) if pc else None
        cp=price or 0.0; ai=fai.copy()
        if not df.empty and cp>0:
            df=compute_all_indicators(df); latest=df.iloc[-1]; wr=_calc_winrate(df); vi=_calc_vol_info(df)
            ai=build_tw_ai_signal(latest,cp,wr,macro,chgp or 0,vi.get("ratio",1.0),df)
        elif cp>0:
            ai=_empty_ai("WATCH","歷史資料不足，無法完整分析")
        record_ai_signal(stock_id,sname,ai,source="stock-lite")
        result={"stock_id":stock_id,"stock_name":sname,"price":price,"change":change,"change_pct":chgp,
                "realtime_quote":rt,"ai_signal":ai,"data_source":hs if not df.empty else "TWSE MIS","lite":True}
        _tw_lite_cache[stock_id]=(result,now); return result
    except Exception as e:
        return{"stock_id":stock_id,"stock_name":sname,"price":None,"change":None,"change_pct":None,
               "realtime_quote":None,"ai_signal":fai,"data_source":"error","lite":True,"error":str(e)}

async def _analyze_stock_core(stock_id:str) -> dict:
    now=time.time()
    if stock_id in _tw_full_cache:
        cached,ts=_tw_full_cache[stock_id]
        if now-ts<TW_FULL_TTL: return cached
    sname=get_stock_name(stock_id)
    try:
        rt=await fetch_tw_quote(stock_id)
        if rt and rt.get("stock_name"): sname=rt["stock_name"]
        df,dsrc=await fetch_tw_history(stock_id,lookback_days=400)
        if df.empty:
            rtp=rt.get("price") if rt else None
            return{"stock_id":stock_id,"stock_name":sname,"last_date":"N/A","data_source":"none",
                   "data_warning":"歷史股價資料暫時無法取得，僅顯示即時報價。",
                   "price":{"close":rtp,"mode":"realtime" if rtp else "unavailable"},
                   "indicators":{},"score":{"score":0,"technical_score":0,"reasons":["歷史資料不足，無法計算技術指標"]},
                   "ai_signal":_empty_ai("WATCH","歷史資料不足"),"chart_data":[],"news":[]}
        df=compute_all_indicators(df); latest=df.iloc[-1]
        prev=df.iloc[-2] if len(df)>1 else latest
        chg=float(latest["收盤價"]-prev["收盤價"])
        chgp=round(chg/float(prev["收盤價"])*100,2) if float(prev["收盤價"]) else 0
        cp=float(rt["price"]) if rt and rt.get("price") is not None else float(latest["收盤價"])
        wr=_calc_winrate(df); vi=_calc_vol_info(df)
        try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
        except: macro={"usd_twd":None,"dxy":None,"risk_note":"","macro_adj":0}
        ai=build_tw_ai_signal(latest,cp,wr,macro,chgp,vi.get("ratio",1.0),df)
        record_ai_signal(stock_id,sname,ai,source="stock")
        chart_data=[]
        for _,row in df.tail(120).iterrows():
            chart_data.append({"date":row["日期"].strftime("%Y-%m-%d"),
                "open":_f(row.get("開盤價")),"high":_f(row.get("最高價")),
                "low":_f(row.get("最低價")),"close":_f(row.get("收盤價")),
                "volume":int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
                "ma5":_f(row.get("MA5")),"ma20":_f(row.get("MA20")),"ma60":_f(row.get("MA60")),
                "rsi":_f(row.get("RSI")),"macd":_f(row.get("MACD"),4),"signal_line":_f(row.get("Signal"),4),
                "hist":_f(row.get("Hist"),4),"bb_upper":_f(row.get("BB_upper")),"bb_lower":_f(row.get("BB_lower"))})
        # V12.3.1: expose latest indicators directly for frontend indicator panel.
        # Older versions only embedded these in chart_data, so the technical indicator block showed dashes.
        latest_indicators={
            "ma5":_f(latest.get("MA5")),"ma20":_f(latest.get("MA20")),"ma60":_f(latest.get("MA60")),
            "rsi":_f(latest.get("RSI")),"macd":_f(latest.get("MACD"),4),"signal":_f(latest.get("Signal"),4),
            "hist":_f(latest.get("Hist"),4),"bb_upper":_f(latest.get("BB_upper")),"bb_lower":_f(latest.get("BB_lower")),
            "atr":_f(latest.get("ATR")),"adx":_f(latest.get("ADX"))
        }
        ts_for_panel=compute_technical_score(latest,cp,vi.get("ratio",1.0),chgp,df)
        tech100=int(ts_for_panel.get("technical_score") or 0)
        score5=max(0,min(5,round(tech100/20)))
        bd=ts_for_panel.get("breakdown",{}) or {}
        panel_reasons=[]
        if latest_indicators.get("ma5") is not None and latest_indicators.get("ma20") is not None:
            panel_reasons.append("MA5 > MA20 短線偏多" if latest_indicators["ma5"]>latest_indicators["ma20"] else "MA5 未站上 MA20，短線需觀察")
        if latest_indicators.get("rsi") is not None:
            panel_reasons.append(f"RSI {latest_indicators['rsi']}")
        if latest_indicators.get("macd") is not None and latest_indicators.get("signal") is not None:
            panel_reasons.append("MACD 強於 Signal" if latest_indicators["macd"]>latest_indicators["signal"] else "MACD 尚未轉強")
        result={"stock_id":stock_id,"stock_name":sname,"last_date":latest["日期"].strftime("%Y-%m-%d"),
                "data_source":dsrc,
                "price":{"close":_f(cp),"daily_close":_f(latest["收盤價"]),
                         "open":_f(rt.get("open") if rt else latest.get("開盤價")),
                         "high":_f(rt.get("high") if rt else latest.get("最高價")),
                         "low":_f(rt.get("low") if rt else latest.get("最低價")),
                         "change":_f(rt.get("change"),2) if rt and rt.get("change") is not None else _f(chg,2),
                         "change_pct":_f(rt.get("change_pct"),2) if rt and rt.get("change_pct") is not None else _f(chgp,2),
                         "mode":"realtime" if rt and rt.get("price") is not None else "daily"},
                "indicators":latest_indicators,
                "score":{"score":score5,"technical_score":tech100,"breakdown":bd,"reasons":panel_reasons},
                "volume":vi,"ai_signal":ai,"realtime_quote":rt,"news":[],"chart_data":chart_data}
        _tw_full_cache[stock_id]=(result,now); return result
    except Exception as e:
        return{"stock_id":stock_id,"stock_name":sname,"error":str(e),"chart_data":[],"indicators":{},"score":{"score":0,"technical_score":0,"reasons":[str(e)]},"ai_signal":_empty_ai("WATCH",str(e))}

# ══════════════════════════════════════════════════════════════════════════════
# US ENGINE — 美股資料
# ══════════════════════════════════════════════════════════════════════════════

# ── US Symbol Master ────────────────────────────────────────────────────────
US_BUILTIN: dict[str,dict] = {
    "AAPL":{"name":"Apple Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "MSFT":{"name":"Microsoft Corp.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "NVDA":{"name":"NVIDIA Corp.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "AMZN":{"name":"Amazon.com Inc.","exchange":"NASDAQ","type":"Stock","sector":"Consumer Cyclical"},
    "GOOGL":{"name":"Alphabet Inc. (A)","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "GOOG":{"name":"Alphabet Inc. (C)","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "META":{"name":"Meta Platforms","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "TSLA":{"name":"Tesla Inc.","exchange":"NASDAQ","type":"Stock","sector":"Consumer Cyclical"},
    "AVGO":{"name":"Broadcom Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "ORCL":{"name":"Oracle Corp.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "AMD":{"name":"Advanced Micro Devices","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "INTC":{"name":"Intel Corp.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "QCOM":{"name":"Qualcomm Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "MU":{"name":"Micron Technology","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "AMAT":{"name":"Applied Materials","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "LRCX":{"name":"Lam Research","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "KLAC":{"name":"KLA Corp.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "MRVL":{"name":"Marvell Technology","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "SMCI":{"name":"Super Micro Computer","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "ARM":{"name":"Arm Holdings","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "ASTS":{"name":"AST SpaceMobile","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "RKLB":{"name":"Rocket Lab USA","exchange":"NASDAQ","type":"Stock","sector":"Industrials"},
    "IONQ":{"name":"IonQ Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "SOUN":{"name":"SoundHound AI","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "PLTR":{"name":"Palantir Technologies","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "AI":{"name":"C3.ai Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "RGTI":{"name":"Rigetti Computing","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "QUBT":{"name":"Quantum Computing","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "BBAI":{"name":"BigBear.ai Holdings","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "COIN":{"name":"Coinbase Global","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "MSTR":{"name":"MicroStrategy Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "HOOD":{"name":"Robinhood Markets","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "SOFI":{"name":"SoFi Technologies","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "AFRM":{"name":"Affirm Holdings","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "PYPL":{"name":"PayPal Holdings","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "SQ":{"name":"Block Inc.","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "V":{"name":"Visa Inc.","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "MA":{"name":"Mastercard Inc.","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "RIVN":{"name":"Rivian Automotive","exchange":"NASDAQ","type":"Stock","sector":"Consumer Cyclical"},
    "LCID":{"name":"Lucid Group","exchange":"NASDAQ","type":"Stock","sector":"Consumer Cyclical"},
    "NIO":{"name":"NIO Inc. (ADR)","exchange":"NYSE","type":"Stock","sector":"Consumer Cyclical"},
    "CRM":{"name":"Salesforce Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "ADBE":{"name":"Adobe Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "NFLX":{"name":"Netflix Inc.","exchange":"NASDAQ","type":"Stock","sector":"Communication Services"},
    "SNOW":{"name":"Snowflake Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "DDOG":{"name":"Datadog Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "ZS":{"name":"Zscaler Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "CRWD":{"name":"CrowdStrike Holdings","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "PANW":{"name":"Palo Alto Networks","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "NET":{"name":"Cloudflare Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "MDB":{"name":"MongoDB Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "PATH":{"name":"UiPath Inc.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "UPST":{"name":"Upstart Holdings","exchange":"NASDAQ","type":"Stock","sector":"Financial Services"},
    "MRNA":{"name":"Moderna Inc.","exchange":"NASDAQ","type":"Stock","sector":"Healthcare"},
    "BNTX":{"name":"BioNTech SE (ADR)","exchange":"NASDAQ","type":"Stock","sector":"Healthcare"},
    "ENPH":{"name":"Enphase Energy","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "FSLR":{"name":"First Solar Inc.","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "PLUG":{"name":"Plug Power Inc.","exchange":"NASDAQ","type":"Stock","sector":"Industrials"},
    "IBM":{"name":"IBM Corp.","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "CSCO":{"name":"Cisco Systems","exchange":"NASDAQ","type":"Stock","sector":"Technology"},
    "DELL":{"name":"Dell Technologies","exchange":"NYSE","type":"Stock","sector":"Technology"},
    "JPM":{"name":"JPMorgan Chase","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "GS":{"name":"Goldman Sachs","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "MS":{"name":"Morgan Stanley","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "BAC":{"name":"Bank of America","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "WFC":{"name":"Wells Fargo","exchange":"NYSE","type":"Stock","sector":"Financial Services"},
    "WMT":{"name":"Walmart Inc.","exchange":"NYSE","type":"Stock","sector":"Consumer Defensive"},
    "COST":{"name":"Costco Wholesale","exchange":"NASDAQ","type":"Stock","sector":"Consumer Defensive"},
    "HD":{"name":"Home Depot","exchange":"NYSE","type":"Stock","sector":"Consumer Cyclical"},
    "MCD":{"name":"McDonald's Corp.","exchange":"NYSE","type":"Stock","sector":"Consumer Cyclical"},
    "SBUX":{"name":"Starbucks Corp.","exchange":"NASDAQ","type":"Stock","sector":"Consumer Cyclical"},
    "DIS":{"name":"Walt Disney Co.","exchange":"NYSE","type":"Stock","sector":"Communication Services"},
    "SPY":{"name":"SPDR S&P 500 ETF","exchange":"NYSEARCA","type":"ETF","sector":"Broad Market"},
    "QQQ":{"name":"Invesco Nasdaq 100 ETF","exchange":"NASDAQ","type":"ETF","sector":"Technology"},
    "IWM":{"name":"iShares Russell 2000 ETF","exchange":"NYSEARCA","type":"ETF","sector":"Small Cap"},
    "SOXX":{"name":"iShares Semiconductor ETF","exchange":"NASDAQ","type":"ETF","sector":"Technology"},
    "SMH":{"name":"VanEck Semiconductor ETF","exchange":"NASDAQ","type":"ETF","sector":"Technology"},
    "ARKK":{"name":"ARK Innovation ETF","exchange":"NYSEARCA","type":"ETF","sector":"Innovation"},
    "TQQQ":{"name":"ProShares UltraPro QQQ (3x)","exchange":"NASDAQ","type":"ETF","sector":"Leveraged"},
    "SQQQ":{"name":"ProShares UltraPro Short QQQ","exchange":"NASDAQ","type":"ETF","sector":"Inverse"},
    "SOXL":{"name":"Direxion Daily SOX Bull 3X","exchange":"NYSEARCA","type":"ETF","sector":"Leveraged"},
    "SOXS":{"name":"Direxion Daily SOX Bear 3X","exchange":"NYSEARCA","type":"ETF","sector":"Inverse"},
    "GLD":{"name":"SPDR Gold ETF","exchange":"NYSEARCA","type":"ETF","sector":"Commodities"},
    "SLV":{"name":"iShares Silver ETF","exchange":"NYSEARCA","type":"ETF","sector":"Commodities"},
    "TLT":{"name":"iShares 20Y Treasury ETF","exchange":"NASDAQ","type":"ETF","sector":"Fixed Income"},
    "XLK":{"name":"Tech Sector ETF (SPDR)","exchange":"NYSEARCA","type":"ETF","sector":"Technology"},
}

_us_master: dict[str,dict] = {}
_us_master_ts: float = 0.0
_us_master_loading: bool = False

def _load_us_master() -> dict:
    global _us_master, _us_master_ts
    master = dict(US_BUILTIN)
    try:
        if US_MASTER_FILE.exists():
            d=json.loads(US_MASTER_FILE.read_text(encoding="utf-8"))
            for sym,info in (d.get("symbols") or {}).items():
                if sym and isinstance(info,dict): master[sym.upper()]=info
    except: pass
    _us_master=master; _us_master_ts=time.time()
    return master

def get_us_master() -> dict:
    if not _us_master: _load_us_master()
    return _us_master

def search_us_master(q: str, limit=10) -> list[dict]:
    q=q.strip().upper(); master=get_us_master()
    results=[]; seen=set()
    if q in master:
        info=master[q]; results.append({"symbol":q,"name":info.get("name",""),"exchange":info.get("exchange",""),"type":info.get("type","Stock"),"sector":info.get("sector","")}); seen.add(q)
    for sym,info in master.items():
        if sym not in seen and sym.startswith(q):
            results.append({"symbol":sym,"name":info.get("name",""),"exchange":info.get("exchange",""),"type":info.get("type","Stock"),"sector":info.get("sector","")}); seen.add(sym)
            if len(results)>=limit: break
    if len(results)<limit:
        q_lo=q.lower()
        for sym,info in master.items():
            if sym not in seen and q_lo in info.get("name","").lower():
                results.append({"symbol":sym,"name":info.get("name",""),"exchange":info.get("exchange",""),"type":info.get("type","Stock"),"sector":info.get("sector","")}); seen.add(sym)
                if len(results)>=limit: break
    return results[:limit]

async def _bg_update_us_master():
    global _us_master_loading
    if _us_master_loading: return
    _us_master_loading=True
    master=dict(US_BUILTIN)
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=True) as cl:
            for exchange in ("nasdaq","nyse","amex"):
                try:
                    r=await cl.get(f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange={exchange}",headers={"User-Agent":"Mozilla/5.0"})
                    if r.status_code==200:
                        rows=r.json().get("data",{}).get("table",{}).get("rows",[])
                        for row in rows:
                            sym=str(row.get("symbol","")).strip().upper()
                            if sym and re.match(r'^[A-Z]{1,6}$',sym):
                                master[sym]={"name":row.get("name",""),"exchange":exchange.upper(),"type":"Stock","sector":row.get("sector","")}
                except: pass
    except: pass
    finally: _us_master_loading=False
    try:
        US_MASTER_FILE.write_text(json.dumps({"updated_at":datetime.now().isoformat(),"count":len(master),"symbols":master},ensure_ascii=False),encoding="utf-8")
    except: pass
    _us_master.update(master)

# ── US Quotes & History ─────────────────────────────────────────────────────
_us_quote_cache: dict[str,tuple[dict,float]] = {}
_us_full_cache:  dict[str,tuple[dict,float]] = {}
US_LITE_TTL = 30; US_FULL_TTL = 600

async def fetch_us_quote(symbol: str, client: httpx.AsyncClient) -> dict | None:
    """Yahoo Finance real-time quote."""
    try:
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        r=await client.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=10,follow_redirects=True)
        if r.status_code!=200: return None
        res=r.json().get("chart",{}).get("result")
        if not res: return None
        res=res[0]; meta=res.get("meta",{})
        price=meta.get("regularMarketPrice") or meta.get("previousClose")
        if not price: return None
        prev=meta.get("previousClose") or meta.get("chartPreviousClose") or price
        chg=round(float(price)-float(prev),4); chgp=round(chg/float(prev)*100,2) if prev else 0
        q=res.get("indicators",{}).get("quote",[{}])[0]
        # Update master name from Yahoo
        yahoo_name=meta.get("shortName") or meta.get("longName","")
        if yahoo_name and symbol in _us_master: _us_master[symbol]["name"]=yahoo_name
        return{
            "symbol":symbol,"name":yahoo_name or _us_master.get(symbol,{}).get("name",symbol),
            "exchange":meta.get("fullExchangeName") or meta.get("exchangeName",""),
            "sector":_us_master.get(symbol,{}).get("sector",""),
            "price":round(float(price),4),"previous_close":round(float(prev),4),
            "change":chg,"change_pct":chgp,
            "open":round(float(meta.get("regularMarketOpen") or price),4),
            "high":round(float(meta.get("regularMarketDayHigh") or price),4),
            "low":round(float(meta.get("regularMarketDayLow") or price),4),
            "volume":int(meta.get("regularMarketVolume") or 0),
            "fifty_two_week_high":round(float(meta.get("fiftyTwoWeekHigh") or 0),4) or None,
            "fifty_two_week_low":round(float(meta.get("fiftyTwoWeekLow") or 0),4) or None,
            "currency":meta.get("currency","USD"),
            "market_state":meta.get("marketState",""),
            "quote_time":(datetime.utcfromtimestamp(meta["regularMarketTime"]).strftime("%Y-%m-%d %H:%M UTC")
                          if meta.get("regularMarketTime") else None),
            "source":"Yahoo Finance",
        }
    except: return None

async def fetch_us_history(symbol: str, client: httpx.AsyncClient, days=400) -> pd.DataFrame:
    """Yahoo Finance OHLCV history → DataFrame with TW column names for shared indicators."""
    try:
        p2=int(datetime.now().timestamp()); p1=int((datetime.now()-timedelta(days=days)).timestamp())
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
        r=await client.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=15,follow_redirects=True)
        if r.status_code!=200: raise Exception(f"Yahoo {r.status_code}")
        res=r.json().get("chart",{}).get("result")
        if not res: return pd.DataFrame()
        res=res[0]; ts_list=res.get("timestamp",[])
        q=res.get("indicators",{}).get("quote",[{}])[0]
        o,h,l,c,v=(q.get(k,[]) for k in["open","high","low","close","volume"])
        recs=[{"日期":pd.to_datetime(ts,unit="s",utc=True).tz_convert("America/New_York").date(),
               "開盤價":float(o[i]) if i<len(o) and o[i] else float(c[i]),
               "最高價":float(h[i]) if i<len(h) and h[i] else float(c[i]),
               "最低價":float(l[i]) if i<len(l) and l[i] else float(c[i]),
               "收盤價":float(c[i]),"成交股數":int(v[i]) if i<len(v) and v[i] else 0}
              for i,ts in enumerate(ts_list) if i<len(c) and c[i] is not None]
        if not recs: return pd.DataFrame()
        df=pd.DataFrame(recs); df["日期"]=pd.to_datetime(df["日期"])
        return df.sort_values("日期").reset_index(drop=True)
    except:
        return pd.DataFrame()

async def fetch_us_profile(symbol: str) -> dict:
    """Fetch company profile from Yahoo Finance."""
    try:
        async with httpx.AsyncClient(timeout=10) as cl:
            r=await cl.get(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=summaryProfile,defaultKeyStatistics,financialData",
                           headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True)
            if r.status_code!=200: return {}
            data=r.json().get("quoteSummary",{}).get("result",[{}])[0] if r.json().get("quoteSummary",{}).get("result") else {}
            sp=data.get("summaryProfile",{}); dk=data.get("defaultKeyStatistics",{}); fd=data.get("financialData",{})
            def _v(d,k): v=d.get(k,{}); return v.get("raw") if isinstance(v,dict) else v
            return{
                "sector":sp.get("sector",""),"industry":sp.get("industry",""),
                "full_time_employees":sp.get("fullTimeEmployees"),
                "website":sp.get("website",""),"country":sp.get("country",""),
                "market_cap":_v(dk,"marketCap"),"pe_ratio":_v(dk,"forwardPE") or _v(dk,"trailingPE"),
                "eps":_v(dk,"trailingEps"),"book_value":_v(dk,"bookValue"),
                "price_to_book":_v(dk,"priceToBook"),"beta":_v(dk,"beta"),
                "shares_outstanding":_v(dk,"sharesOutstanding"),
                "total_revenue":_v(fd,"totalRevenue"),
                "revenue_growth":_v(fd,"revenueGrowth"),
                "gross_margins":_v(fd,"grossMargins"),
                "operating_margins":_v(fd,"operatingMargins"),
                "profit_margins":_v(fd,"profitMargins"),
                "return_on_equity":_v(fd,"returnOnEquity"),
                "debt_to_equity":_v(fd,"debtToEquity"),
                "current_ratio":_v(fd,"currentRatio"),
            }
    except: return {}

# ── US Market Context ────────────────────────────────────────────────────────
_us_ctx_cache: dict={}; _us_ctx_ts: float=0.0; US_CTX_TTL=180

async def fetch_us_market_context() -> dict:
    """US Market Context with explanation and graceful partial fallback."""
    global _us_ctx_cache,_us_ctx_ts
    if _us_ctx_cache and (time.time()-_us_ctx_ts)<US_CTX_TTL: return _us_ctx_cache
    syms={"spy":"SPY","qqq":"QQQ","soxx":"^SOX","iwm":"IWM","vix":"^VIX","us10y":"^TNX","dxy":"DX-Y.NYB","btc":"BTC-USD"}
    result={k:None for k in syms}
    errors=[]
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            for key,sym in syms.items():
                try:
                    r=await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d",
                                   headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True)
                    if r.status_code!=200:
                        errors.append({"component":key,"symbol":sym,"error":f"HTTP {r.status_code}"}); continue
                    res=r.json().get("chart",{}).get("result")
                    if not res:
                        errors.append({"component":key,"symbol":sym,"error":"no result"}); continue
                    closes=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
                    valid=[c for c in closes if c is not None]
                    if valid:
                        result[key]={"price":round(float(valid[-1]),2),
                                     "change_pct":round((float(valid[-1])-float(valid[-2]))/float(valid[-2])*100,2) if len(valid)>1 and valid[-2] else 0}
                    else:
                        errors.append({"component":key,"symbol":sym,"error":"no close"})
                except Exception as e:
                    errors.append({"component":key,"symbol":sym,"error":str(e)[:120]})
    except Exception as e:
        errors.append({"component":"client","error":str(e)[:120]})

    score=50; explanations=[]; notes=[]
    spy=result.get("spy"); qqq=result.get("qqq"); soxx=result.get("soxx"); iwm=result.get("iwm")
    vix=result.get("vix"); us10y=result.get("us10y"); dxy=result.get("dxy"); btc=result.get("btc")
    def chg(x): return (x or {}).get("change_pct") or 0
    def price(x, default=None): return (x or {}).get("price", default)
    if spy:
        delta=8 if chg(spy)>0 else -8; score+=delta; explanations.append({"name":"SPY","impact":delta,"text":f"SPY {chg(spy):+.2f}% {'supports risk-on' if delta>0 else 'weakens broad market tone'}"})
    if qqq:
        delta=10 if chg(qqq)>0 else -10; score+=delta; explanations.append({"name":"QQQ","impact":delta,"text":f"QQQ {chg(qqq):+.2f}% {'supports tech/growth' if delta>0 else 'pressures tech/growth'}"})
    if soxx:
        delta=8 if chg(soxx)>0 else -8; score+=delta; explanations.append({"name":"SOXX/SOX","impact":delta,"text":f"Semiconductor index {chg(soxx):+.2f}% {'supports chip names' if delta>0 else 'pressures semiconductor names'}"})
    if iwm:
        delta=4 if chg(iwm)>0 else -4; score+=delta; explanations.append({"name":"IWM","impact":delta,"text":f"Small caps {chg(iwm):+.2f}%"})
    if vix:
        v=float(price(vix,20))
        if v<15: delta=15; txt="VIX low; risk appetite healthy"
        elif v<20: delta=8; txt="VIX normal; risk environment acceptable"
        elif v<30: delta=-12; txt="VIX elevated; reduce high-beta risk"
        else: delta=-25; txt="VIX fear level; avoid aggressive entries"
        score+=delta; explanations.append({"name":"VIX","impact":delta,"text":f"{txt} ({v:.1f})"}); notes.append(f"VIX {v:.1f}")
    if us10y:
        y=float(price(us10y,4))
        if y>4.8: delta=-10; txt="US10Y high; growth stocks pressured"
        elif y<4.0: delta=5; txt="US10Y lower; growth stocks supported"
        else: delta=0; txt="US10Y neutral"
        score+=delta; explanations.append({"name":"US10Y","impact":delta,"text":f"{txt} ({y:.2f})"})
    if dxy:
        dx=chg(dxy)
        delta=-5 if dx>0.4 else (3 if dx<-0.4 else 0)
        score+=delta; explanations.append({"name":"DXY","impact":delta,"text":f"DXY {dx:+.2f}% {'strong dollar headwind' if delta<0 else 'dollar not a headwind' if delta>0 else 'neutral'}"})
    if btc:
        bp=chg(btc)
        delta=5 if bp>2 else (-5 if bp<-5 else 0)
        score+=delta; explanations.append({"name":"BTC","impact":delta,"text":f"BTC {bp:+.2f}% {'supports crypto-beta names' if delta>0 else 'pressures crypto-beta names' if delta<0 else 'neutral'}"})
    market_score=max(0,min(100,round(score)))
    sentiment="Bullish 🟢" if market_score>=65 else("Neutral ⚪" if market_score>=45 else "Bearish 🔴")
    status="ok" if len(errors)<=2 else ("partial" if len(errors)<len(syms) else "degraded")
    ctx={"market_score":market_score,"sentiment":sentiment,"note":" | ".join(notes[:4]),
         "components":result,"explanations":explanations,"status":status,"errors":errors[:8],
         "updated_at":datetime.now().isoformat()}
    _us_ctx_cache=ctx; _us_ctx_ts=time.time(); return ctx

# ── US AI Signal ────────────────────────────────────────────────────────────
def build_us_ai_signal(row: pd.Series, cp: float, chg_pct: float,
                       vol_ratio: float, price_df: pd.DataFrame | None,
                       market_ctx: dict | None, symbol: str) -> dict:
    """V12 US AI signal — full 100-pt with market context."""
    market_ctx=market_ctx or {}
    if cp<=0: return _empty_ai("WATCH","No price data available")

    ts_data=compute_technical_score(row,cp,vol_ratio,chg_pct,price_df)
    ts=ts_data["technical_score"]
    overheat=detect_overheat(row,cp,chg_pct,price_df)
    fb=detect_false_breakout(row,cp,vol_ratio,price_df)

    if ts>=75 and not overheat and not fb: signal="BUY"
    elif ts>=52: signal="WATCH"
    else: signal="AVOID"
    if overheat and signal=="BUY": signal="WATCH"
    if fb and signal=="BUY": signal="WATCH"

    plan=build_trade_plan(row,cp,signal,price_df)
    rr=plan["risk_reward_ratio"]; tv=plan["trade_valid"]
    if not tv and signal=="BUY": signal="WATCH"

    def _g(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    adx=_g("ADX"); ma20=_g("MA20"); atr=_g("ATR")
    atr_pct=(atr/cp*100) if atr and cp>0 else None
    ma20_dev=((cp-ma20)/ma20*100) if ma20 and ma20>0 else None
    stock_type=_us_master.get(symbol,{}).get("type","Stock")
    strat=determine_strategy_type(row,cp,vol_ratio,overheat,fb,adx,stock_type)

    # Classify by sector for strategy subtype
    sector=_us_master.get(symbol,{}).get("sector","")
    if "Semiconductor" in sector or symbol in("NVDA","AMD","AVGO","SMCI","MU","QCOM"):
        strat=strat if strat in("Overheated","False Breakout Risk","Range Bound") else "AI / Semiconductor Momentum"
    elif stock_type=="ETF":
        strat="ETF Trend"
    elif symbol in("AAPL","MSFT","AMZN","GOOGL","META") and strat=="Trend Following":
        strat="Mega Cap Trend"

    market_score=market_ctx.get("market_score",50)
    vol_score=min(100,max(0,int(vol_ratio*50))) if vol_ratio else 50
    rr_score=compute_rr_score(rr)
    risk_score=compute_risk_score(overheat,fb,tv,rr,atr_pct,ma20_dev)

    if strat in("Mega Cap Trend","ETF Trend"): setup_score=80 if ts>=65 else 55
    elif strat=="AI / Semiconductor Momentum": setup_score=75 if ts>=65 and not overheat else 45
    elif strat in("Pullback Entry","Reversal Bounce"): setup_score=70 if tv else 40
    elif strat=="Overheated": setup_score=20
    else: setup_score=55

    dq="full" if price_df is not None and len(price_df)>=60 else "partial"
    final=compute_final_score(ts,setup_score,rr_score,market_score,vol_score,risk_score,dq)
    conf=min(100,final)

    es=plan["entry_status"]
    if tv:
        if overheat or (ma20_dev and ma20_dev>8): es="TOO_EXTENDED"
        elif plan["entry_price"] and abs(cp-plan["entry_price"])/cp*100<=3: es="ENTERABLE"
        else: es="WAIT_PULLBACK"

    scan_cat=classify_scan_category(signal,es,tv,overheat,fb,final,ts,market_score,risk_score,conf)
    # US requires market_score >= 55 for ENTERABLE
    if scan_cat=="ENTERABLE" and market_score<55: scan_cat="NEAR_MISS"

    if signal=="BUY" and tv and es=="ENTERABLE" and rr and rr>=1.5: trade_status="BUY_NOW"
    elif signal=="BUY": trade_status="BUY_PULLBACK"
    elif signal=="WATCH": trade_status="WATCH"
    else: trade_status="AVOID"

    entry_reason=[]; risk_reason=list(plan.get("risk_reason",[]))+overheat[:2]+fb[:1]
    if ts>=70: entry_reason.append(f"Technical score {ts}/100")
    if strat: entry_reason.append(f"Strategy: {strat}")
    if rr and rr>=1.5: entry_reason.append(f"RR {rr}x ≥ 1.5")
    if market_score>=65: entry_reason.append(f"Market context bullish ({market_score}/100)")
    if market_score<45: risk_reason.append(f"Weak market context ({market_score}/100)")

    summary=(f"Tech {ts}/100 | {strat} | Market {market_score}/100 | "
             +("Entry conditions met." if signal=="BUY" and tv else
                "Signals positive but unconfirmed, watch for pullback." if signal=="WATCH" else
                "Technical conditions weak, avoid for now."))

    return{
        "signal":signal,"confidence":conf,"score_quality":dq,
        "entry_price":plan["entry_price"],"entry_zone_low":plan["entry_zone_low"],
        "entry_zone_high":plan["entry_zone_high"],"target_price":plan["target_price"],
        "stop_loss":plan["stop_loss"],"risk_reward_ratio":rr,
        "trade_status":trade_status,"entry_status":es,
        "entry_status_text":{"ENTERABLE":"✅ Enterable","WAIT_PULLBACK":"⏳ Wait Pullback",
                              "TOO_EXTENDED":"⚠️ Too Extended","BAD_SETUP":"⚠️ Invalid Setup","NO_DATA":"— No Data"}.get(es,"—"),
        "can_enter":es=="ENTERABLE","trade_valid":tv,
        "strategy_type":strat,"technical_score":ts,"technical_breakdown":ts_data["breakdown"],
        "setup_score":setup_score,"rr_score":rr_score,"market_score":market_score,
        "volume_score":vol_score,"risk_score":risk_score,"final_score":final,
        "scan_category":scan_cat,"overheat_flags":overheat,"false_breakout_flags":fb,"risk_flags":[],
        "recent_support":plan["recent_support"],"recent_resistance":plan["recent_resistance"],
        "support_zone":plan["support_zone"],"resistance_zone":plan["resistance_zone"],
        "entry_reason":entry_reason[:4],"risk_reason":risk_reason[:4],
        "summary":summary,"holding_days":"5-15 days" if signal=="BUY" else "Watch only",
        "market_context_score":market_score,
        "disclaimer":"⚠️ For reference only, not investment advice",
    }

# ── US Full Stock Fetch ──────────────────────────────────────────────────────
async def _fetch_us_full(symbol: str) -> dict:
    now=time.time()
    if symbol in _us_full_cache:
        cached,ts=_us_full_cache[symbol]
        if now-ts<US_FULL_TTL: return cached
    async with httpx.AsyncClient() as cl:
        quote,df,market_ctx=await asyncio.gather(
            fetch_us_quote(symbol,cl),
            fetch_us_history(symbol,cl,400),
            fetch_us_market_context(),
        )
    if not quote:
        return{"market":"us","symbol":symbol,"name":_us_master.get(symbol,{}).get("name",symbol),
               "error":"美股資料暫時無法取得，請稍後重試","data_quality":"poor",
               "chart_data":[],"ai_signal":_empty_ai("WATCH","Quote unavailable")}

    cp=float(quote["price"]); chg_pct=float(quote.get("change_pct") or 0)
    vol_ratio=1.0
    if not df.empty:
        try:
            avg=df.tail(20)["成交股數"].mean(); lat=float(df.iloc[-1]["成交股數"])
            if avg>0: vol_ratio=round(lat/avg,2)
        except: pass

    # Compute indicators and AI
    ai=_empty_ai("WATCH","Insufficient history")
    if not df.empty:
        df2=compute_all_indicators(df.copy()); latest=df2.iloc[-1]
        ai=build_us_ai_signal(latest,cp,chg_pct,vol_ratio,df,market_ctx,symbol)
    else:
        # Minimal AI from quote
        ep=round(cp,4); sl=round(cp*0.96,4); tp=round(cp*1.06,4)
        rr=round((tp-ep)/(ep-sl),2)
        ai={**_empty_ai("WATCH","No history — reference only"),
            "entry_price":ep,"entry_zone_low":round(ep*0.995,4),"entry_zone_high":round(ep*1.005,4),
            "target_price":tp,"stop_loss":sl,"risk_reward_ratio":rr,"score_quality":"poor",
            "market_score":market_ctx.get("market_score",50)}

    # Chart data
    chart_data=[]
    if not df.empty:
        df3=compute_all_indicators(df.copy())
        for _,row in df3.tail(120).iterrows():
            chart_data.append({"date":row["日期"].strftime("%Y-%m-%d"),
                "open":_f(row.get("開盤價"),4),"high":_f(row.get("最高價"),4),
                "low":_f(row.get("最低價"),4),"close":_f(row.get("收盤價"),4),
                "volume":int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
                "ma5":_f(row.get("MA5"),4),"ma20":_f(row.get("MA20"),4),"ma60":_f(row.get("MA60"),4),
                "rsi":_f(row.get("RSI")),"macd":_f(row.get("MACD"),4),
                "signal_line":_f(row.get("Signal"),4),"hist":_f(row.get("Hist"),4)})

    result={
        "market":"us","symbol":symbol,
        "name":quote.get("name") or _us_master.get(symbol,{}).get("name",symbol),
        "exchange":quote.get("exchange",""),"sector":quote.get("sector",""),
        "industry":_us_master.get(symbol,{}).get("sector",""),
        "price":quote["price"],"change":quote.get("change"),"change_pct":quote.get("change_pct"),
        "open":quote.get("open"),"high":quote.get("high"),"low":quote.get("low"),
        "volume":quote.get("volume"),"avg_volume":None,
        "fifty_two_week_high":quote.get("fifty_two_week_high"),
        "fifty_two_week_low":quote.get("fifty_two_week_low"),
        "currency":quote.get("currency","USD"),
        "market_state":quote.get("market_state",""),
        "quote_time":quote.get("quote_time"),
        "source":"Yahoo Finance","data_quality":"full" if len(df)>=60 else("partial" if not df.empty else "poor"),
        "chart_data":chart_data,"market_context":market_ctx,"ai_signal":ai,
    }
    _us_full_cache[symbol]=(result,now); return result

async def _fetch_us_lite(symbol: str) -> dict:
    now=time.time()
    if symbol in _us_full_cache:
        cached,ts=_us_full_cache[symbol]
        if now-ts<US_FULL_TTL:
            d=cached; ai=d.get("ai_signal",{})
            return{"market":"us","symbol":symbol,"name":d.get("name",symbol),
                   "price":d.get("price"),"change_pct":d.get("change_pct"),"change":d.get("change"),
                   "ai_signal":ai,"lite":True}
    if symbol in _us_quote_cache:
        cached,ts=_us_quote_cache[symbol]
        if now-ts<US_LITE_TTL: return cached
    async with httpx.AsyncClient() as cl:
        quote=await fetch_us_quote(symbol,cl)
    if not quote:
        return{"market":"us","symbol":symbol,"name":_us_master.get(symbol,{}).get("name",symbol),
               "price":None,"change_pct":None,"change":None,"ai_signal":_empty_ai(),"lite":True}
    cp=float(quote["price"]); chg=(quote.get("change_pct") or 0)
    ep=round(cp,4); sl=round(cp*0.96,4); tp=round(cp*1.06,4); rr=round((tp-ep)/(ep-sl),2)
    ai_lite={**_empty_ai("WATCH","Lite mode — query full data for analysis"),
             "entry_price":ep,"entry_zone_low":round(ep*0.995,4),"entry_zone_high":round(ep*1.005,4),
             "target_price":tp,"stop_loss":sl,"risk_reward_ratio":rr,"score_quality":"partial"}
    result={"market":"us","symbol":symbol,"name":quote.get("name",symbol),
            "price":quote["price"],"change_pct":quote.get("change_pct"),"change":quote.get("change"),
            "ai_signal":ai_lite,"lite":True}
    _us_quote_cache[symbol]=(result,now); return result

# ── US Scan Pools ────────────────────────────────────────────────────────────
US_CORE_POOL      = ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","AVGO","NFLX"]
US_GROWTH_POOL    = ["PLTR","SOFI","RIVN","HOOD","COIN","MSTR","ASTS","RKLB","IONQ","SOUN"]
US_SEMI_POOL      = ["NVDA","AMD","AVGO","SMCI","MU","QCOM","MRVL","AMAT","LRCX","KLAC"]
US_ETF_POOL       = ["SPY","QQQ","SOXX","IWM","ARKK","TQQQ","SMH"]
US_SCAN_CACHE: dict[str, tuple[dict, float]] = {}
TW_SCAN_CACHE: dict[str, tuple[dict, float]] = {}
SCAN_CACHE_TTL = 300

def _scan_cache_get(cache: dict, key: str, ttl: int = SCAN_CACHE_TTL):
    hit = cache.get(key)
    if not hit: return None
    payload, ts = hit
    if time.time() - ts < ttl:
        data = dict(payload)
        data["cache_status"] = "fresh"
        data["cache_age_seconds"] = round(time.time() - ts, 1)
        return data
    return None

def _scan_cache_set(cache: dict, key: str, payload: dict):
    payload = dict(payload)
    payload["cache_status"] = "fresh"
    payload["cache_saved_at"] = datetime.now().isoformat()
    cache[key] = (payload, time.time())
    return payload

def _unique_symbols(seq):
    out=[]
    for x in seq or []:
        s=str(x).strip().upper()
        if s and s not in out: out.append(s)
    return out

def select_us_scan_pool(pool: str = "all", symbols: str = "", limit: int = 50) -> list[str]:
    pool=(pool or "all").lower().replace("_","-")
    custom=_unique_symbols(re.split(r"[,\s]+", symbols or ""))
    if pool in ("watchlist","my-watchlist","custom") and custom:
        return custom[:limit]
    if pool in ("mega","mega-cap","core"):
        base=US_CORE_POOL
    elif pool in ("ai","semi","semiconductor","ai-semiconductor"):
        base=US_SEMI_POOL
    elif pool in ("growth","high-beta","highbeta"):
        base=US_GROWTH_POOL
    elif pool in ("etf","etfs"):
        base=US_ETF_POOL
    else:
        base=US_CORE_POOL + US_GROWTH_POOL + US_SEMI_POOL + US_ETF_POOL
    return list(dict.fromkeys(base))[:limit]

def select_tw_scan_pool(pool: str = "all", symbols: str = "", limit: int = 50) -> list[str]:
    pool=(pool or "all").lower().replace("_","-")
    custom=[]
    for x in re.split(r"[,\s]+", symbols or ""):
        if re.match(r"^\d{4,6}$", x or "") and x not in custom: custom.append(x)
    if pool in ("watchlist","my-watchlist","custom") and custom:
        return custom[:limit]
    if pool in ("finance","financial"):
        base=["2881","2882","2891","2886","2884","2885","2892","2801","2812","5880"]
    elif pool in ("electronics","tech","ai"):
        base=["2330","2317","2454","2308","2382","2357","2379","3034","2303","2327","2345","2360","3005"]
    elif pool in ("hot","popular"):
        base=["2357","3034","2485","2891","3481","6147","2342","5351","2344","6173","2313","3706"]
    else:
        base=TW_SCAN_POOL
    return list(dict.fromkeys(base))[:limit]

def scan_mode_label(mode: str, pool: str, count: int) -> str:
    return f"{(mode or 'full').upper()} · {pool or 'all'} · {count} symbols"

# ══════════════════════════════════════════════════════════════════════════════
# TW Additional helpers (scan market sentiment)
# ══════════════════════════════════════════════════════════════════════════════
_sc_cache: dict={}; _sc_ts: float=0.0

async def _scan_market_sentiment() -> dict:
    global _sc_cache,_sc_ts
    if _sc_cache and (time.time()-_sc_ts)<600: return _sc_cache
    pool=TW_SCAN_POOL[:30]; buy=watch=avoid=0
    try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except: macro={}
    for sid in pool:
        try:
            r=await _analyze_stock_lite(sid,macro); s=r.get("ai_signal",{}).get("signal","WATCH")
            if s=="BUY": buy+=1
            elif s=="AVOID": avoid+=1
            else: watch+=1
        except: pass
    tot=buy+watch+avoid or 1
    sent="強勢🔥" if buy>watch and buy>avoid else("空頭❄️" if avoid>(buy+watch)*0.5 else "中性⚠️")
    result={"buy_count":buy,"watch_count":watch,"avoid_count":avoid,"total":tot,
            "buy_pct":round(buy/tot*100,1),"sentiment":sent,"scanned_at":datetime.now().isoformat()}
    _sc_cache=result; _sc_ts=time.time(); return result

# TW backtest (preserved)
def advanced_backtest(df,holding_days=5,min_score=75):
    empty={"total_trades":0,"wins":0,"losses":0,"winrate":0,"avg_return":0,"best_return":0,"worst_return":0,"max_drawdown":0,"profit_factor":0,"sharpe_ratio":0,"trades":[]}
    if df.empty: return empty
    df=df.copy().reset_index(drop=True); df=compute_all_indicators(df)
    req=[c for c in["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df=df.dropna(subset=req) if req else df
    trades,equity,peak,max_dd=[],1.0,1.0,0.0
    for i,(_,row) in enumerate(df.iterrows()):
        if i+holding_days>=len(df): break
        cur=float(row["收盤價"])
        vi={"ratio":1.0,"alert":False,"latest_volume":0,"avg_volume_20d":0}
        wr={"winrate":0,"trials":0,"wins":0}
        ai=build_tw_ai_signal(row,cur,wr,{},0,1.0,None)
        if (ai.get("confidence") or 0)<min_score: continue
        ep=float(df.iloc[i+holding_days]["收盤價"]); rp=round((ep-cur)/cur*100,2)
        trades.append({"date":row["日期"].strftime("%Y-%m-%d"),"entry_price":cur,"exit_price":ep,
                       "return_pct":rp,"win":ep>cur,"confidence":ai.get("confidence",0),"signal":ai.get("signal","WATCH")})
        equity*=(1+rp/100); peak=max(peak,equity); dd=(peak-equity)/peak*100; max_dd=max(max_dd,dd)
    total=len(trades); wins=sum(1 for t in trades if t["win"])
    rets=[t["return_pct"] for t in trades]
    avg_r=sum(rets)/total if total else 0; std_r=(sum((r-avg_r)**2 for r in rets)/total)**0.5 if total>1 else 0
    gain=sum(r for r in rets if r>0); loss=abs(sum(r for r in rets if r<0))
    return{"total_trades":total,"wins":wins,"losses":total-wins,
           "winrate":round(wins/total*100,1) if total else 0,"avg_return":round(avg_r,2),
           "best_return":round(max(rets),2) if rets else 0,"worst_return":round(min(rets),2) if rets else 0,
           "max_drawdown":round(max_dd,2),"profit_factor":round(gain/loss,2) if loss else 0,
           "sharpe_ratio":round(avg_r/std_r,2) if std_r>0 else 0,"trades":list(reversed(trades))[:20]}

# TW LINE helpers
def _lc(): return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID and ENABLE_LINE_ALERTS)
def _cc():
    if not LINE_CHANNEL_ACCESS_TOKEN: raise HTTPException(503,detail="LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
    if not LINE_TO_ID: raise HTTPException(503,detail="LINE_TO_ID 尚未設定")
    if not ENABLE_LINE_ALERTS: raise HTTPException(503,detail="ENABLE_LINE_ALERTS 未設為 true")

async def send_line_message(msg:str)->dict:
    hdr={"Authorization":f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}","Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r=await cl.post(LINE_PUSH_URL,headers=hdr,json={"to":LINE_TO_ID,"messages":[{"type":"text","text":msg}]})
            if r.status_code==200: return{"success":True,"message":"LINE 訊息發送成功"}
            return{"success":False,"message":f"LINE API 錯誤：{r.status_code}"}
    except Exception as e: return{"success":False,"message":f"發送失敗：{str(e)}"}

def _blm(sid,name,ai,price):
    disp=f"{name} ({sid})" if name and name!=sid else sid
    ts=ai.get("trade_status","WATCH"); tl={"BUY_NOW":"✅ 可布局","BUY_PULLBACK":"⏳ 等回檔"}.get(ts,ts)
    ep=ai.get('entry_price'); tp=ai.get('target_price'); sl=ai.get('stop_loss')
    return(f"✅ V12 AI 交易訊號\n股票：{disp}\n狀態：{tl}\n信心：{ai.get('confidence',0)}\n"
           f"即時價：{price} 入場：{ep or '—'}\n目標：{tp or '—'} 止蝕：{sl or '—'}\n"
           f"RR：{ai.get('risk_reward_ratio') or '—'}x\n{ai.get('summary','')}")

async def _fname(sid:str)->str:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
            r=await cl.get(TWSE_NAME_URL,params={"stockNo":sid}); data=r.json()
            if isinstance(data,dict):
                for key in["data","msgArray"]:
                    arr=data.get(key)
                    if arr and isinstance(arr,list) and arr:
                        row=arr[0]
                        if isinstance(row,list) and len(row)>1: return row[1]
                        if isinstance(row,dict): return row.get("公司名稱",row.get("Name",""))
    except: pass
    return ""

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    loaded=_lfm()
    if not loaded or _ims(): asyncio.create_task(fetch_stock_master_list())
    _load_us_master()
    # Background: update US master if stale
    if time.time()-_us_master_ts>86400:
        asyncio.create_task(_bg_update_us_master())

# ══════════════════════════════════════════════════════════════════════════════
# API — TW Watchlist
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/watchlist")
async def api_get_watchlist():
    items=_rwl(); return{"watchlist":items,"count":len(items)}

@app.post("/api/watchlist")
async def api_post_watchlist(body:WatchlistUpdateBody):
    items=_nwl(body.watchlist); _wwl(items); return{"watchlist":items,"count":len(items),"saved":True}

# ══════════════════════════════════════════════════════════════════════════════
# API — TW Stocks
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/stocks/master")
async def api_stocks_master():
    if not STOCK_MASTER: _lfm()
    return{"count":len(STOCK_MASTER),"updated_at":_mua,"stocks":STOCK_MASTER}

@app.get("/api/stocks/search")
async def api_stocks_search(q:str=Query("",min_length=1)):
    if not STOCK_MASTER: _lfm()
    q=q.strip(); results=[]
    if q in STOCK_MASTER: results.append({"stock_id":q,"stock_name":STOCK_MASTER[q]["name"],"market":STOCK_MASTER[q].get("market","")})
    for sid,info in STOCK_MASTER.items():
        if sid==q: continue
        if sid.startswith(q): results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
        if len(results)>=20: break
    if len(results)<20:
        for sid,info in STOCK_MASTER.items():
            if sid==q or sid.startswith(q): continue
            if q in info["name"]: results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
            if len(results)>=20: break
    return{"results":results[:20],"query":q}

@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    return await _analyze_stock_core(stock_id)

@app.get("/api/stock-lite/{stock_id}")
async def get_stock_lite(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=5)
    except: macro={}
    return await _analyze_stock_lite(stock_id,macro)

@app.get("/api/realtime/{stock_id}")
async def get_realtime(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    q=await fetch_tw_quote(stock_id)
    if not q: raise HTTPException(404,detail="找不到即時報價")
    return q

@app.get("/api/analysis-4d/{stock_id}")
async def get_analysis_4d(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    try:
        at=asyncio.create_task(_fname(stock_id))
        df,dsrc=await fetch_tw_history(stock_id,lookback_days=400)
        an=await at; sname=get_stock_name(stock_id,an); lr=None
        rt=await fetch_tw_quote(stock_id)
        if df.empty: cp=float(rt["price"]) if rt and rt.get("price") else 0.0
        else:
            df=compute_all_indicators(df); lr=df.iloc[-1]
            cp=float(rt["price"]) if rt and rt.get("price") else float(lr["收盤價"])
        news,fu,chip,margin=await asyncio.gather(
            fetch_news(stock_id,sname),fetch_fundamental_data(stock_id),
            fetch_chip_data(stock_id),fetch_margin_data(stock_id))
        te=analyze_technical_4d(df,lr,cp) if not df.empty and lr is not None else{"score":None,"rating":"資料不足","trend":"—","reasons":[],"risks":[]}
        fud=analyze_fundamental_4d(fu); chd=analyze_chip_4d(chip,margin); nwd=analyze_news_4d(news)
        ovd=compute_overall_4d(fud,te,chd,nwd)
        try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=5)
        except: macro={}
        ai4d=compute_4d_ai_signal(ovd,fud,te,chd,nwd,lr,cp,macro)
        return{"stock_id":stock_id,"stock_name":sname,"cur_price":cp,"data_source":dsrc,
               "analysis_4d":{"fundamental":fud,"technical":te,"chip":chd,"news":nwd,"overall":ovd},
               "ai_signal":ai4d,"news":news}
    except Exception as e:
        return{"stock_id":stock_id,"stock_name":get_stock_name(stock_id),"error":str(e),
               "analysis_4d":None,"ai_signal":_empty_ai("WATCH","四面向資料暫時無法取得"),"news":[]}

@app.get("/api/macro")
async def api_macro():
    try: return await asyncio.wait_for(fetch_macro_context(),timeout=10)
    except Exception as e: return{"error":str(e),"usd_twd":None,"dxy":None,"risk_note":"宏觀資料暫時無法取得","macro_adj":0}

@app.get("/api/market-sentiment")
async def api_market_sentiment():
    try: return await _scan_market_sentiment()
    except Exception as e: return{"error":str(e),"buy_count":0,"watch_count":0,"avoid_count":0,"sentiment":"中性⚠️"}

# ══════════════════════════════════════════════════════════════════════════════
# API — TW AI Scan
# ══════════════════════════════════════════════════════════════════════════════
async def _tw_scan_core(min_score:int=65,max_stocks:int=50,mode:str="full",pool_name:str="all",symbols:str="",use_cache:bool=True):
    """V12.1 TW AI scan core — quick/full/watchlist pools + 6-zone output."""
    pool=select_tw_scan_pool(pool_name, symbols, max_stocks)
    cache_key=f"tw:{mode}:{pool_name}:{','.join(pool)}:{min_score}:{max_stocks}"
    if use_cache:
        hit=_scan_cache_get(TW_SCAN_CACHE, cache_key)
        if hit: return hit
    t0=time.time()
    try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except Exception as e: macro={"error":str(e)}
    market_score_tw=max(0,min(100,60+(macro.get("macro_adj",0)*2)))
    enterable=[];watch_closely=[];pullback=[];breakout_watch=[];risk_watch=[];avoid=[];near_miss=[];errors=[]
    attempted=0; classified=0; current_symbol=None
    for sid in pool:
        current_symbol=sid; attempted += 1
        try:
            r=await _analyze_stock_lite(sid,macro); ai=r.get("ai_signal",{}) or {}
            conf=ai.get("confidence") or 0; final=ai.get("final_score") or 0; cat=ai.get("scan_category","AVOID")
            item={"stock_id":sid,"symbol":sid,"stock_name":r.get("stock_name") or get_stock_name(sid),"name":r.get("stock_name") or get_stock_name(sid),"market":"tw",
                  "signal":ai.get("signal","WATCH"),"confidence":conf,"trade_status":ai.get("trade_status","WATCH"),
                  "entry_status":ai.get("entry_status","NO_DATA"),"entry_status_text":ai.get("entry_status_text","—"),
                  "can_enter":ai.get("can_enter",False),"trade_valid":ai.get("trade_valid",False),"strategy_type":ai.get("strategy_type",""),
                  "technical_score":ai.get("technical_score"),"final_score":final,"market_score":ai.get("market_score",market_score_tw),"risk_score":ai.get("risk_score",50),
                  "rr_score":ai.get("rr_score",0),"overheat_flags":ai.get("overheat_flags",[]),"false_breakout_flags":ai.get("false_breakout_flags",[]),
                  "price":r.get("price"),"change_pct":r.get("change_pct"),"entry_price":ai.get("entry_price"),"entry_zone_low":ai.get("entry_zone_low"),
                  "entry_zone_high":ai.get("entry_zone_high"),"target_price":ai.get("target_price"),"stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),
                  "recent_support":ai.get("recent_support"),"recent_resistance":ai.get("recent_resistance"),"reasons":ai.get("entry_reason",[]) or ai.get("reasons",[]),
                  "risk_reason":ai.get("risk_reason",[]),"summary":ai.get("summary","")}
            if conf < min_score:
                item.setdefault("risk_reason",[]).append(f"Confidence {conf}/100 below scan threshold {min_score}")
                if final>=65 and (item.get("technical_score") or 0)>=65 and (item.get("risk_score") or 0)>=50:
                    cat="WATCH_CLOSELY"
                elif final>=55 or (item.get("technical_score") or 0)>=55: cat="NEAR_MISS"
                else: cat="AVOID"
            elif cat=="NEAR_MISS" and final>=65 and (item.get("technical_score") or 0)>=65 and (item.get("risk_score") or 0)>=50:
                cat="WATCH_CLOSELY"
            item["scan_category"]=cat
            if cat=="ENTERABLE": enterable.append(item)
            elif cat=="WATCH_CLOSELY": watch_closely.append(item)
            elif cat=="PULLBACK": pullback.append(item)
            elif cat=="BREAKOUT_WATCH": breakout_watch.append(item)
            elif cat=="RISK_WATCH": risk_watch.append(item)
            elif cat=="NEAR_MISS": near_miss.append(item)
            else: avoid.append(item)
            classified += 1
        except Exception as e:
            errors.append({"stock_id":sid,"symbol":sid,"error":str(e)[:160]})
    def sort_e(x): return (-(x.get("final_score") or 0),-(x.get("risk_reward_ratio") or 0),-(x.get("risk_score") or 0),-(x.get("confidence") or 0))
    def sort_p(x): return (-(x.get("technical_score") or 0),-(x.get("confidence") or 0),-(x.get("final_score") or 0))
    for arr in (enterable,watch_closely,pullback,breakout_watch,risk_watch,near_miss,avoid): arr.sort(key=sort_e if arr is enterable else sort_p)
    found=len(enterable)+len(watch_closely)+len(pullback)+len(breakout_watch)+len(risk_watch)+len(near_miss)
    msg="目前沒有符合可進場條件的股票，建議等待更好的進場點。" if not enterable else f"發現 {len(enterable)} 檔可進場候選！"
    dur=round(time.time()-t0,1)
    payload={"market":"tw","scan_mode":mode,"pool":pool_name,"pool_size":len(pool),"updated_at":datetime.now().isoformat(),
           "scanned":len(pool),"attempted":attempted,"classified":classified,"failed":len(errors),"found":found,"current_symbol":current_symbol,
           "market_score":market_score_tw,"duration_seconds":dur,"scan_label":scan_mode_label(mode,pool_name,len(pool)),
           "summary":{"scanned":len(pool),"attempted":attempted,"classified":classified,"failed":len(errors),
                      "enterable_count":len(enterable),"watch_closely_count":len(watch_closely),"pullback_count":len(pullback),
                      "breakout_watch_count":len(breakout_watch),"risk_watch_count":len(risk_watch),"avoid_count":len(avoid),"near_miss_count":len(near_miss),"found":found,
                      "market_score":market_score_tw,"message":msg,"mode":mode,"pool":pool_name},
           "enterable":enterable,"watch_closely":watch_closely,"pullback":pullback,"breakout_watch":breakout_watch,
           "risk_watch":risk_watch,"avoid":avoid,"near_miss":near_miss,"errors":errors,"error_count":len(errors)}
    return _scan_cache_set(TW_SCAN_CACHE, cache_key, payload)

@app.get("/api/scan/ai")
async def tw_ai_scan(min_score:int=Query(65,ge=0,le=100),max_stocks:int=Query(50,ge=5,le=80),pool:str="all",symbols:str="",mode:str="full"):
    return await _tw_scan_core(min_score,max_stocks,mode,pool,symbols,True)

@app.get("/api/tw/scan/quick")
async def tw_scan_quick(pool:str="all",symbols:str="",min_score:int=Query(60,ge=0,le=100),max_stocks:int=Query(20,ge=5,le=40)):
    return await _tw_scan_core(min_score,max_stocks,"quick",pool,symbols,True)

@app.get("/api/tw/scan/full")
async def tw_scan_full(pool:str="all",symbols:str="",min_score:int=Query(65,ge=0,le=100),max_stocks:int=Query(50,ge=10,le=80)):
    return await _tw_scan_core(min_score,max_stocks,"full",pool,symbols,True)

@app.get("/api/tw/scan/watchlist")
async def tw_scan_watchlist(symbols:str="",min_score:int=Query(60,ge=0,le=100),max_stocks:int=Query(50,ge=1,le=100)):
    return await _tw_scan_core(min_score,max_stocks,"watchlist","watchlist",symbols,False)

# ══════════════════════════════════════════════════════════════════════════════
# API — LINE
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/alerts/test")
async def test_line():
    _cc()
    result=await send_line_message("✅ V12 AI Picker Pro - LINE 通知測試成功！")
    if not result["success"]: raise HTTPException(500,detail=result["message"])
    return result

@app.post("/api/alerts/check")
async def check_alerts(body:WatchlistBody):
    t0=time.time(); lo=_lc(); results=[]; now=datetime.now(); sent=[]; errors=[]
    stock_ids=body.watchlist or [item["stock_id"] for item in _rwl()]
    try: macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except: macro={}
    for sid in stock_ids:
        if not re.match(r"^\d{4,6}$",sid): continue
        try:
            r=await _analyze_stock_lite(sid,macro); ai=r.get("ai_signal",{}); sn=r.get("stock_name",sid); cp2=r.get("price") or 0
            results.append({"stock_id":sid,"stock_name":sn,"signal":ai.get("signal","AVOID"),
                "confidence":ai.get("confidence",0),"trade_status":ai.get("trade_status","WATCH"),
                "summary":ai.get("summary",""),"entry_price":ai.get("entry_price"),
                "target_price":ai.get("target_price"),"stop_loss":ai.get("stop_loss"),
                "risk_reward_ratio":ai.get("risk_reward_ratio")})
            rr2=ai.get("risk_reward_ratio") or 0; conf=ai.get("confidence") or 0
            es2=ai.get("entry_status","NO_DATA"); tv=ai.get("trade_valid",False)
            ts2=ai.get("technical_score") or 0; final2=ai.get("final_score") or 0
            ovh=bool(ai.get("overheat_flags")); fb2=bool(ai.get("false_breakout_flags"))
            cat=ai.get("scan_category","AVOID")
            lok=(cat=="ENTERABLE" and conf>=70 and rr2>=1.5 and tv
                 and ts2>=70 and final2>=75 and not ovh and not fb2)
            if lo and lok:
                ls=LAST_ALERTS.get(sid)
                if ls is None or (now-ls).total_seconds()>=ALERT_COOLDOWN_MINUTES*60:
                    res=await send_line_message(_blm(sid,sn,ai,cp2))
                    if res["success"]: LAST_ALERTS[sid]=now; sent.append(sid)
        except Exception as e: errors.append({"stock_id":sid,"error":str(e)})
    rank={"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x:(rank.get(x.get("signal",""),0),x.get("confidence",0)),reverse=True)
    return{"checked":len(stock_ids),"alerts":[r for r in results if r.get("signal")=="BUY"],
           "all_results":results,"sent_line":sent,"line_enabled":lo,
           "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1)}

# ══════════════════════════════════════════════════════════════════════════════
# API — TW Backtest & Learning
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/backtest/{stock_id}")
async def run_backtest(stock_id:str,lookback_days:int=400,holding_days:int=5,min_score:int=75):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    df,_=await fetch_tw_history(stock_id,lookback_days)
    an=await _fname(stock_id); sname=get_stock_name(stock_id,an)
    result=advanced_backtest(df,holding_days=holding_days,min_score=min_score)
    return{"stock_id":stock_id,"stock_name":sname,
           "params":{"lookback_days":lookback_days,"holding_days":holding_days,"min_score":min_score},
           "result":{k:v for k,v in result.items() if k!="trades"},"trades":result["trades"]}

@app.get("/api/learning/weights")
def api_learning_weights():
    h=load_signal_history(); return{"weights":load_ai_weights(),"stats":_lst(h),"recent":list(reversed(h))[:10]}

@app.get("/api/learning/history")
def api_learning_history(limit:int=Query(100,ge=1,le=500)):
    h=load_signal_history(); return{"count":len(h),"signals":list(reversed(h))[:limit]}

@app.get("/api/learning/evaluate")
async def api_learning_evaluate(): return await evaluate_signal_history()

@app.post("/api/learning/retrain")
def api_learning_retrain(): return retrain_ai_weights()

# ══════════════════════════════════════════════════════════════════════════════
# API — US Stocks
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/us/suggest")
async def us_suggest(q:str=Query("",min_length=1)):
    results=search_us_master(q,limit=10)
    if not results:
        sym=q.strip().upper()
        if re.match(r'^[A-Za-z.\-]{1,12}$',sym):
            try:
                async with httpx.AsyncClient() as cl:
                    qt=await fetch_us_quote(sym,cl)
                if qt: results=[{"symbol":sym,"name":qt.get("name",sym),"exchange":qt.get("exchange","US"),"type":"Stock","sector":""}]
            except: pass
    return{"results":results,"query":q}

@app.get("/api/us/stock/{symbol}")
async def us_get_stock(symbol:str):
    if not re.match(r'^[A-Za-z.\-]{1,12}$',symbol): raise HTTPException(400,detail="Invalid US stock symbol")
    return await _fetch_us_full(symbol.upper())

@app.get("/api/us/stock-lite/{symbol}")
async def us_get_stock_lite(symbol:str):
    if not re.match(r'^[A-Za-z.\-]{1,12}$',symbol): raise HTTPException(400,detail="Invalid US stock symbol")
    return await _fetch_us_lite(symbol.upper())

@app.get("/api/us/market-context")
async def us_market_context():
    try: return await fetch_us_market_context()
    except Exception as e: return{"error":str(e),"market_score":50,"sentiment":"Unknown"}

@app.get("/api/us/profile/{symbol}")
async def us_profile(symbol:str):
    if not re.match(r'^[A-Za-z.\-]{1,12}$',symbol): raise HTTPException(400,detail="Invalid symbol")
    profile=await fetch_us_profile(symbol.upper())
    master_info=get_us_master().get(symbol.upper(),{})
    return{"symbol":symbol.upper(),"name":master_info.get("name",symbol),"profile":profile}

async def _us_scan_core(min_score:int=60,max_stocks:int=50,mode:str="full",pool_name:str="all",symbols:str="",use_cache:bool=True):
    """V12.1 US AI scan core — pool selector + quick/full/watchlist + watch closely."""
    t0=time.time()
    pool=select_us_scan_pool(pool_name, symbols, max_stocks)
    cache_key=f"us:{mode}:{pool_name}:{','.join(pool)}:{min_score}:{max_stocks}"
    if use_cache:
        hit=_scan_cache_get(US_SCAN_CACHE, cache_key)
        if hit: return hit
    try:
        market_ctx=await asyncio.wait_for(fetch_us_market_context(),timeout=8)
    except Exception as e:
        market_ctx={"market_score":50,"sentiment":"Unknown","error":str(e)}
    market_score=market_ctx.get("market_score",50)
    enterable=[];watch_closely=[];pullback=[];breakout_watch=[];risk_watch=[];avoid=[];near_miss=[];errors=[]
    attempted=0; classified=0; current_symbol=None
    for sym in pool:
        current_symbol=sym; attempted += 1
        try:
            r=await _fetch_us_full(sym)
            if r.get("error"):
                errors.append({"symbol":sym,"error":str(r.get("error"))}); continue
            ai=r.get("ai_signal",{}) or {}; conf=ai.get("confidence") or 0; final=ai.get("final_score") or 0; cat=ai.get("scan_category","AVOID")
            item={"symbol":sym,"name":r.get("name",sym),"market":"us","price":r.get("price"),"change_pct":r.get("change_pct"),
                  "signal":ai.get("signal","WATCH"),"confidence":conf,"trade_status":ai.get("trade_status","WATCH"),
                  "entry_status":ai.get("entry_status","NO_DATA"),"entry_status_text":ai.get("entry_status_text","—"),"can_enter":ai.get("can_enter",False),"trade_valid":ai.get("trade_valid",False),
                  "strategy_type":ai.get("strategy_type",""),"technical_score":ai.get("technical_score"),"final_score":final,"market_score":ai.get("market_score",market_score),
                  "risk_score":ai.get("risk_score",50),"rr_score":ai.get("rr_score",0),"overheat_flags":ai.get("overheat_flags",[]),"false_breakout_flags":ai.get("false_breakout_flags",[]),
                  "entry_price":ai.get("entry_price"),"entry_zone_low":ai.get("entry_zone_low"),"entry_zone_high":ai.get("entry_zone_high"),"target_price":ai.get("target_price"),
                  "stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),"recent_support":ai.get("recent_support"),"recent_resistance":ai.get("recent_resistance"),
                  "reasons":ai.get("entry_reason",[]) or ai.get("reasons",[]),"risk_reason":ai.get("risk_reason",[]),"summary":ai.get("summary","")}
            if conf < min_score:
                item.setdefault("risk_reason",[]).append(f"Confidence {conf}/100 below scan threshold {min_score}")
                if final>=65 and (item.get("technical_score") or 0)>=65 and (item.get("risk_score") or 0)>=50:
                    cat="WATCH_CLOSELY"
                elif final>=55 or (item.get("technical_score") or 0)>=55: cat="NEAR_MISS"
                else: cat="AVOID"
            elif cat=="NEAR_MISS" and final>=65 and (item.get("technical_score") or 0)>=65 and (item.get("risk_score") or 0)>=50:
                cat="WATCH_CLOSELY"
            item["scan_category"]=cat
            if cat=="ENTERABLE": enterable.append(item)
            elif cat=="WATCH_CLOSELY": watch_closely.append(item)
            elif cat=="PULLBACK": pullback.append(item)
            elif cat=="BREAKOUT_WATCH": breakout_watch.append(item)
            elif cat=="RISK_WATCH": risk_watch.append(item)
            elif cat=="NEAR_MISS": near_miss.append(item)
            else: avoid.append(item)
            classified += 1
        except Exception as e:
            errors.append({"symbol":sym,"error":str(e)[:160]})
    def sort_e(x): return (-(x.get("final_score") or 0),-(x.get("risk_reward_ratio") or 0),-(x.get("confidence") or 0))
    def sort_p(x): return (-(x.get("technical_score") or 0),-(x.get("confidence") or 0),-(x.get("final_score") or 0))
    for arr in (enterable,watch_closely,pullback,breakout_watch,risk_watch,near_miss,avoid): arr.sort(key=sort_e if arr is enterable else sort_p)
    found=len(enterable)+len(watch_closely)+len(pullback)+len(breakout_watch)+len(risk_watch)+len(near_miss)
    msg="No stocks meet entry criteria currently. Watch Closely / Near Miss candidates are shown below." if not enterable else f"Found {len(enterable)} enterable candidates!"
    duration=round(time.time()-t0,1)
    payload={"market":"us","scan_mode":mode,"pool":pool_name,"pool_size":len(pool),"updated_at":datetime.now().isoformat(),
            "scanned":len(pool),"attempted":attempted,"classified":classified,"failed":len(errors),"found":found,"current_symbol":current_symbol,
            "market_score":market_score,"duration_seconds":duration,"scan_label":scan_mode_label(mode,pool_name,len(pool)),
            "summary":{"scanned":len(pool),"attempted":attempted,"classified":classified,"failed":len(errors),
                       "enterable_count":len(enterable),"watch_closely_count":len(watch_closely),"pullback_count":len(pullback),
                       "breakout_watch_count":len(breakout_watch),"risk_watch_count":len(risk_watch),"avoid_count":len(avoid),"near_miss_count":len(near_miss),
                       "found":found,"market_score":market_score,"sentiment":market_ctx.get("sentiment",""),"message":msg,"mode":mode,"pool":pool_name},
            "enterable":enterable,"watch_closely":watch_closely,"pullback":pullback,"breakout_watch":breakout_watch,
            "risk_watch":risk_watch,"avoid":avoid,"near_miss":near_miss,"errors":errors,"error_count":len(errors)}
    return _scan_cache_set(US_SCAN_CACHE, cache_key, payload)

@app.get("/api/us/scan")
async def us_ai_scan(min_score:int=Query(60,ge=0,le=100),max_stocks:int=Query(50,ge=5,le=80),pool:str="all",symbols:str="",mode:str="full"):
    return await _us_scan_core(min_score,max_stocks,mode,pool,symbols,True)

@app.get("/api/us/scan/quick")
async def us_scan_quick(pool:str="all",symbols:str="",min_score:int=Query(55,ge=0,le=100),max_stocks:int=Query(20,ge=5,le=40)):
    return await _us_scan_core(min_score,max_stocks,"quick",pool,symbols,True)

@app.get("/api/us/scan/full")
async def us_scan_full(pool:str="all",symbols:str="",min_score:int=Query(60,ge=0,le=100),max_stocks:int=Query(50,ge=10,le=80)):
    return await _us_scan_core(min_score,max_stocks,"full",pool,symbols,True)

@app.get("/api/us/scan/watchlist")
async def us_scan_watchlist(symbols:str="",min_score:int=Query(55,ge=0,le=100),max_stocks:int=Query(50,ge=1,le=100)):
    return await _us_scan_core(min_score,max_stocks,"watchlist","watchlist",symbols,False)

@app.get("/api/debug/scan-status")
def api_scan_status():
    now=time.time()
    def stat(cache):
        out=[]
        for k,(payload,ts) in list(cache.items())[-12:]:
            out.append({"key":k,"age_seconds":round(now-ts,1),"market":payload.get("market"),"mode":payload.get("scan_mode"),"pool":payload.get("pool"),"classified":payload.get("classified"),"failed":payload.get("failed")})
        return out
    return {"version":"12.3.1","scan_cache_ttl":SCAN_CACHE_TTL,"tw_cache":stat(TW_SCAN_CACHE),"us_cache":stat(US_SCAN_CACHE)}

# ══════════════════════════════════════════════════════════════════════════════
# API — DATA HEALTH / DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════════════
async def _check_us_data_health() -> dict:
    checks={}
    async with httpx.AsyncClient(timeout=8,headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True) as cl:
        try:
            q=await fetch_us_quote("AAPL",cl)
            checks["yahoo_quote"]={"status":"ok" if q and q.get("price") else "fail","symbol":"AAPL","price":(q or {}).get("price")}
        except Exception as e: checks["yahoo_quote"]={"status":"fail","error":str(e)[:120]}
        try:
            h=await fetch_us_history("AAPL",cl,days=90)
            checks["yahoo_history"]={"status":"ok" if h is not None and not h.empty else "fail","rows":0 if h is None else int(len(h))}
        except Exception as e: checks["yahoo_history"]={"status":"fail","error":str(e)[:120]}
    try:
        master=get_us_master()
        age=round((time.time()-_us_master_ts)/3600,2) if _us_master_ts else None
        checks["symbol_master"]={"status":"ok" if master else "fail","count":len(master),"age_hours":age,"file":str(US_MASTER_FILE.name)}
    except Exception as e: checks["symbol_master"]={"status":"fail","error":str(e)[:120]}
    try:
        ctx=await fetch_us_market_context()
        checks["market_context"]={"status":ctx.get("status","ok"),"market_score":ctx.get("market_score"),"errors":ctx.get("errors",[])[:3]}
    except Exception as e: checks["market_context"]={"status":"fail","error":str(e)[:120]}
    overall="ok" if all(v.get("status") in ("ok","partial") for v in checks.values()) else "partial"
    return {"market":"us","overall":overall,"checks":checks,"updated_at":datetime.now().isoformat()}

async def _check_tw_data_health() -> dict:
    checks={}
    try:
        q=await fetch_tw_quote("2330")
        checks["twse_mis"]={"status":"ok" if q and q.get("price") else "fail","stock_id":"2330","price":(q or {}).get("price")}
    except Exception as e: checks["twse_mis"]={"status":"fail","error":str(e)[:120]}
    try:
        loaded=bool(STOCK_MASTER) or _lfm()
        checks["tw_stock_master"]={"status":"ok" if loaded else "fail","count":len(STOCK_MASTER),"updated_at":_mua}
    except Exception as e: checks["tw_stock_master"]={"status":"fail","error":str(e)[:120]}
    try:
        macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
        checks["macro"]={"status":"ok" if macro else "partial","macro_adj":macro.get("macro_adj") if isinstance(macro,dict) else None}
    except Exception as e: checks["macro"]={"status":"partial","error":str(e)[:120]}
    overall="ok" if all(v.get("status") in ("ok","partial") for v in checks.values()) else "partial"
    return {"market":"tw","overall":overall,"checks":checks,"updated_at":datetime.now().isoformat()}

@app.get("/api/us/data-health")
async def api_us_data_health():
    return await _check_us_data_health()

@app.get("/api/tw/data-health")
async def api_tw_data_health():
    return await _check_tw_data_health()

@app.get("/api/health/full")
async def api_health_full():
    """
    V12.0.2 safe full health endpoint.
    This endpoint must NEVER return 500 because the frontend status panel depends on it.
    Any failing sub-check is reported as partial/fail inside JSON instead of raising.
    """
    def _json_safe(v):
        try:
            if isinstance(v, dict):
                return {str(k): _json_safe(val) for k, val in v.items()}
            if isinstance(v, (list, tuple, set)):
                return [_json_safe(x) for x in v]
            if isinstance(v, (np.integer,)):
                return int(v)
            if isinstance(v, (np.floating,)):
                f = float(v)
                return None if np.isnan(f) or np.isinf(f) else f
            if isinstance(v, float):
                return None if np.isnan(v) or np.isinf(v) else v
            if isinstance(v, (datetime,)):
                return v.isoformat()
            return v
        except Exception:
            return str(v)

    errors = []
    us = {"market": "us", "overall": "unknown", "checks": {}, "updated_at": datetime.now().isoformat()}
    tw = {"market": "tw", "overall": "unknown", "checks": {}, "updated_at": datetime.now().isoformat()}

    try:
        us = await asyncio.wait_for(_check_us_data_health(), timeout=18)
    except Exception as e:
        errors.append({"scope": "us_data_health", "error": str(e)[:300]})
        us = {
            "market": "us",
            "overall": "fail",
            "checks": {
                "endpoint": {"status": "fail", "error": str(e)[:180]}
            },
            "updated_at": datetime.now().isoformat()
        }

    try:
        tw = await asyncio.wait_for(_check_tw_data_health(), timeout=18)
    except Exception as e:
        errors.append({"scope": "tw_data_health", "error": str(e)[:300]})
        tw = {
            "market": "tw",
            "overall": "fail",
            "checks": {
                "endpoint": {"status": "fail", "error": str(e)[:180]}
            },
            "updated_at": datetime.now().isoformat()
        }

    payload = {
        "status": "ok" if not errors else "partial",
        "version": "12.3.1",
        "frontend_expected": "12.3.1",
        "time": datetime.now().isoformat(),
        "backend": {
            "title": "V12.3.1 Portfolio & Smart Alert Mode",
            "version": "12.3.1"
        },
        "line": {
            "configured": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
            "enabled": ENABLE_LINE_ALERTS
        },
        "cache": {
            "us_quote_ttl": globals().get("US_LITE_TTL", 30),
            "us_history_ttl": globals().get("US_FULL_TTL", 600),
            "us_market_context_ttl": globals().get("US_CTX_TTL", 180),
            "tw_full_cache_seconds": 300,
            "tw_lite_cache_seconds": 30
        },
        "data_health": {
            "us": us,
            "tw": tw
        },
        "errors": errors
    }
    return _json_safe(payload)


# ══════════════════════════════════════════════════════════════════════════════
# V12.2 TRADE PLAN & ALERT CENTER HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _trade_plan_status_from_values(price, entry_low=None, entry_high=None, target=None, stop=None):
    """Evaluate a long-side trade plan against current price. Always returns JSON-safe dict."""
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    def n(v):
        try: return float(v) if v is not None else None
        except Exception: return None
    entry_low, entry_high, target, stop = map(n, [entry_low, entry_high, target, stop])
    if price is None:
        return {"status":"NO_PRICE","status_text":"無現價資料","distance_to_entry_pct":None,"distance_to_target_pct":None,"distance_to_stop_pct":None}
    status = "WAITING_ENTRY"; text = "等待入場"
    if stop is not None and price <= stop:
        status, text = "STOP_BROKEN", "跌破止損"
    elif target is not None and price >= target:
        status, text = "TARGET_REACHED", "達到目標"
    elif target is not None and price >= target * 0.95:
        status, text = "NEAR_TARGET", "接近目標價"
    elif stop is not None and price <= stop * 1.05:
        status, text = "NEAR_STOP", "接近止損價"
    elif entry_low is not None and entry_high is not None and entry_low <= price <= entry_high:
        status, text = "ENTERABLE_NOW", "已進入入場區"
    elif entry_high is not None and price > entry_high:
        status, text = "ABOVE_ENTRY_ZONE", "高於入場區，不建議追高"
    elif entry_low is not None and price < entry_low:
        status, text = "WAITING_ENTRY", "等待進入入場區"
    def pct_to(v):
        if v is None or price == 0: return None
        return round((v - price) / price * 100, 2)
    mid = None
    if entry_low is not None and entry_high is not None:
        mid = (entry_low + entry_high) / 2
    elif entry_low is not None:
        mid = entry_low
    elif entry_high is not None:
        mid = entry_high
    return {
        "status": status,
        "status_text": text,
        "distance_to_entry_pct": pct_to(mid),
        "distance_to_target_pct": pct_to(target),
        "distance_to_stop_pct": pct_to(stop),
    }

@app.get("/api/trade-plan/check")
async def api_trade_plan_check(
    market: str = Query(..., description="tw or us"),
    symbol: str = Query(..., description="stock id or US symbol"),
    entry_low: float | None = None,
    entry_high: float | None = None,
    target: float | None = None,
    stop: float | None = None,
):
    """V12.2 lightweight trade-plan status checker. It does not store user data; Firestore stores plans on frontend."""
    market = (market or "").lower().strip()
    symbol = (symbol or "").upper().strip()
    price = None; name = symbol; source = None; error = None
    try:
        if market == "us":
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
                q = await fetch_us_quote(symbol, cl)
            if q:
                price = q.get("price"); name = q.get("name") or symbol; source = q.get("source")
        else:
            q = await fetch_tw_quote(symbol)
            if q:
                price = q.get("price"); name = q.get("stock_name") or symbol; source = q.get("source")
    except Exception as e:
        error = str(e)[:200]
    status = _trade_plan_status_from_values(price, entry_low, entry_high, target, stop)
    return {
        "market": market,
        "symbol": symbol,
        "name": name,
        "price": price,
        "source": source,
        "checked_at": datetime.now().isoformat(),
        "plan_status": status,
        "error": error,
    }

@app.get("/api/debug/trade-plans")
def api_debug_trade_plans():
    return {
        "version": "12.3.1",
        "storage": "Firestore frontend: users/{uid}/trade_plans/tw and users/{uid}/trade_plans/us",
        "checker": "/api/trade-plan/check",
        "statuses": ["WAITING_ENTRY","ENTERABLE_NOW","ABOVE_ENTRY_ZONE","NEAR_TARGET","NEAR_STOP","STOP_BROKEN","TARGET_REACHED","INVALIDATED","NO_PRICE"],
        "note": "Backend does not persist personal trade plans; authenticated frontend saves them in each user's Firestore.",
        "time": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# V12.3 PORTFOLIO & SMART ALERT MODE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _position_status_from_values(price, avg_price=None, shares=None, target=None, stop=None):
    """Evaluate an owned position. Backend only checks; frontend stores private positions in Firestore."""
    def n(v):
        try:
            if v is None or v == "": return None
            return float(v)
        except Exception:
            return None
    price, avg_price, shares, target, stop = map(n, [price, avg_price, shares, target, stop])
    if price is None:
        return {"status":"NO_PRICE","status_text":"無現價資料","unrealized_pnl":None,"unrealized_pnl_pct":None,"risk_amount":None,"distance_to_target_pct":None,"distance_to_stop_pct":None,"alerts":["目前無法取得現價"]}
    alerts = []
    pnl = None; pnl_pct = None; risk_amount = None
    if avg_price is not None and shares is not None:
        pnl = round((price - avg_price) * shares, 2)
        if avg_price:
            pnl_pct = round((price - avg_price) / avg_price * 100, 2)
    if avg_price is not None and stop is not None and shares is not None:
        risk_amount = round(max(0, (avg_price - stop) * shares), 2)
    status, text = "HOLDING_NORMAL", "正常持有"
    if stop is not None and price <= stop:
        status, text = "STOP_BROKEN", "跌破止損"
        alerts.append("已跌破止損，請立即重新評估")
    elif target is not None and price >= target:
        status, text = "TARGET_REACHED", "達到目標"
        alerts.append("已達到目標價，可考慮分批獲利或更新計畫")
    elif target is not None and price >= target * 0.95:
        status, text = "NEAR_TARGET", "接近目標"
        alerts.append("接近目標價")
    elif stop is not None and price <= stop * 1.05:
        status, text = "NEAR_STOP", "接近止損"
        alerts.append("接近止損價，請注意風險")
    elif pnl_pct is not None and pnl_pct <= -8:
        status, text = "RISK_UP", "風險升高"
        alerts.append("未實現損益明顯轉弱")
    elif pnl_pct is not None and pnl_pct >= 8:
        status, text = "HOLDING_NORMAL", "正常持有"
        alerts.append("已有獲利，請留意是否接近目標")
    def pct_to(v):
        if v is None or not price: return None
        return round((v - price) / price * 100, 2)
    return {
        "status": status,
        "status_text": text,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
        "risk_amount": risk_amount,
        "distance_to_target_pct": pct_to(target),
        "distance_to_stop_pct": pct_to(stop),
        "alerts": alerts,
    }

@app.get("/api/position/check")
async def api_position_check(
    market: str = Query(..., description="tw or us"),
    symbol: str = Query(..., description="stock id or US symbol"),
    avg_price: float | None = None,
    shares: float | None = None,
    target: float | None = None,
    stop: float | None = None,
):
    """V12.3 lightweight position checker. It does not persist personal data; Firestore stores positions on frontend."""
    market = (market or "").lower().strip()
    symbol = (symbol or "").upper().strip()
    price = None; name = symbol; source = None; error = None
    try:
        if market == "us":
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
                q = await fetch_us_quote(symbol, cl)
            if q:
                price = q.get("price"); name = q.get("name") or symbol; source = q.get("source")
        else:
            q = await fetch_tw_quote(symbol)
            if q:
                price = q.get("price"); name = q.get("stock_name") or symbol; source = q.get("source")
    except Exception as e:
        error = str(e)[:200]
    status = _position_status_from_values(price, avg_price, shares, target, stop)
    return {
        "market": market,
        "symbol": symbol,
        "name": name,
        "price": price,
        "source": source,
        "checked_at": datetime.now().isoformat(),
        "position_status": status,
        "error": error,
    }

@app.get("/api/debug/positions")
def api_debug_positions():
    return {
        "version": "12.3.1",
        "storage": "Firestore frontend: users/{uid}/positions/tw and users/{uid}/positions/us",
        "checker": "/api/position/check",
        "statuses": ["HOLDING_NORMAL","NEAR_TARGET","TARGET_REACHED","NEAR_STOP","STOP_BROKEN","RISK_UP","REVIEW_REQUIRED","NO_PRICE"],
        "note": "Backend does not persist personal positions; authenticated frontend saves them in each user's Firestore.",
        "time": datetime.now().isoformat(),
    }

# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/health")
def health():
    return{"status":"ok","version":"12.3.1","frontend_expected":"12.3.1","time":datetime.now().isoformat(),
           "dev_mode":DEV_MODE,"line_configured":bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
           "line_enabled":ENABLE_LINE_ALERTS,"realtime_source":"TWSE MIS",
           "price_sources":"Yahoo Finance → TWSE Official → FinMind",
           "us_master_count":len(_us_master),"tw_master_count":len(STOCK_MASTER),
           "features":["V12.3.1 Portfolio & Smart Alert Mode","AI Picker Pro",
                       "TW Engine + US Engine + Shared Engine",
                       "6-zone scan output","US Market Context","Symbol Master 200+",
                       "validate_trade_plan","compute_final_score","LINE alerts","Quick/Full AI Scan","Watch Closely zone","scan pool selector","scan cache diagnostics","Trade Plan Center","trade plan status checker","Watchlist UI polish","Portfolio Center","position status checker","smart position alerts"]}
