"""
台股監測後端 V8 - 四面向分析版
新增：四面向分析 analysis_4d（基本面/技術面/籌碼面/消息面/總分）
     布林通道、ATR、支撐壓力、籌碼面資料（TWSE 三大法人、融資融券）
     AI 訊號整合 analysis_4d 加減分
保留：全部 V7 功能（自選股同步、AI 選股、LINE 推播、全市場名稱、入場價）
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

app = FastAPI(title="台股監測 API V8", version="8.0.0")

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
DEV_MODE = os.getenv("DEV_MODE","false").lower()=="true"
if DEV_MODE: ALLOWED_ORIGINS=["*"]

app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS,
    allow_credentials=not DEV_MODE,allow_methods=["GET","POST","OPTIONS"],allow_headers=["*"])

# ── LINE ─────────────────────────────────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN","")
LINE_TO_ID                = os.getenv("LINE_TO_ID","")
ENABLE_LINE_ALERTS        = os.getenv("ENABLE_LINE_ALERTS","false").lower()=="true"
LAST_ALERTS: dict[str,datetime] = {}
ALERT_COOLDOWN_MINUTES = 30

# ── 路徑 ──────────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
WATCHLIST_FILE    = BASE_DIR/"watchlist.json"
STOCK_MASTER_FILE = BASE_DIR/"stock_master.json"

FINMIND_BASE  = "https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL = "https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL  = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
TIMEOUT = 25

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
STOCK_NAME_MAP: dict[str,str] = {
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
# 全市場股票主檔
# ══════════════════════════════════════════════════════════════════════════════
STOCK_MASTER: dict[str,dict] = {}
_master_updated_at = ""
_master_loading = False

def _load_master_from_file()->bool:
    global STOCK_MASTER,_master_updated_at
    try:
        if STOCK_MASTER_FILE.exists():
            d=json.loads(STOCK_MASTER_FILE.read_text(encoding="utf-8"))
            STOCK_MASTER=d.get("stocks",{})
            _master_updated_at=d.get("updated_at","")
            return bool(STOCK_MASTER)
    except: pass
    return False

def _save_master_to_file():
    try:
        STOCK_MASTER_FILE.write_text(
            json.dumps({"updated_at":datetime.now().isoformat(),"stocks":STOCK_MASTER},
                       ensure_ascii=False,indent=2),encoding="utf-8")
    except: pass

def _is_master_stale()->bool:
    if not _master_updated_at: return True
    try: return (datetime.now()-datetime.fromisoformat(_master_updated_at)).total_seconds()>86400
    except: return True

async def fetch_stock_master_list():
    global STOCK_MASTER,_master_updated_at,_master_loading
    if _master_loading: return
    _master_loading=True
    master:dict[str,dict]={}
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        for url,market in [
            ("https://www.twse.com.tw/rwd/zh/api/basic?type=MS&response=json","tse"),
            ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L","tse"),
        ]:
            if master: break
            try:
                r=await client.get(url)
                if r.status_code!=200: continue
                rows=r.json() if "openapi" in url else r.json().get("data",[])
                for row in rows:
                    if isinstance(row,list) and len(row)>=2:
                        sid,name=str(row[0]).strip(),str(row[1]).strip()
                    elif isinstance(row,dict):
                        sid=str(row.get("公司代號","")or row.get("有價證券代號","")).strip()
                        name=str(row.get("公司簡稱","")or row.get("有價證券名稱","")).strip()
                    else: continue
                    if re.match(r"^\d{4,6}$",sid) and name:
                        master[sid]={"name":name,"market":"tse"}
            except: pass
        for url in ["https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_information",
                    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]:
            try:
                r=await client.get(url)
                if r.status_code!=200: continue
                for row in r.json():
                    sid=str(row.get("SecuritiesCompanyCode","")or row.get("公司代號","")).strip()
                    name=str(row.get("CompanyName","")or row.get("公司簡稱","")).strip()
                    if re.match(r"^\d{4,6}$",sid) and name and sid not in master:
                        master[sid]={"name":name,"market":"otc"}
            except: pass
    for sid,name in STOCK_NAME_MAP.items():
        if sid not in master: master[sid]={"name":name,"market":"tse"}
    if master:
        STOCK_MASTER.update(master)
        _master_updated_at=datetime.now().isoformat()
        _save_master_to_file()
    _master_loading=False

def get_stock_name(stock_id:str,api_name:str|None=None)->str:
    cleaned=str(api_name).strip() if api_name else ""
    if cleaned and cleaned!=stock_id: return cleaned
    if stock_id in STOCK_MASTER: return STOCK_MASTER[stock_id]["name"]
    return STOCK_NAME_MAP.get(stock_id,stock_id)

# ══════════════════════════════════════════════════════════════════════════════
# 自選股
# ══════════════════════════════════════════════════════════════════════════════
def _normalize_wl(raw:list)->list[dict]:
    result,seen=[],set()
    for item in raw:
        if isinstance(item,str):
            sid=item.strip()
            if sid and sid not in seen: seen.add(sid); result.append({"stock_id":sid,"stock_name":get_stock_name(sid)})
        elif isinstance(item,dict):
            sid=str(item.get("stock_id","")).strip()
            if sid and sid not in seen:
                seen.add(sid); result.append({"stock_id":sid,"stock_name":item.get("stock_name") or get_stock_name(sid)})
    return result

def _read_watchlist()->list[dict]:
    try:
        if WATCHLIST_FILE.exists():
            return _normalize_wl(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("watchlist",[]))
    except: pass
    return []

def _write_watchlist(items:list[dict]):
    try: WATCHLIST_FILE.write_text(json.dumps({"watchlist":items},ensure_ascii=False,indent=2),encoding="utf-8")
    except: pass

class WatchlistUpdateBody(BaseModel): watchlist:list
class WatchlistBody(BaseModel): watchlist:list[str]

# ── 新聞關鍵字 ────────────────────────────────────────────────────────────────
BULLISH_KW=["獲利","營收成長","突破","漲停","利多","買超","法人買","創新高",
    "增資","配息","配股","股利","超預期","優於預期","轉盈","擴廠",
    "新訂單","拿下訂單","合作","策略聯盟","上調目標價","買進評等"]
BEARISH_KW=["虧損","營收衰退","跌停","利空","賣超","法人賣","創新低",
    "減資","下調目標價","賣出評等","警示","財務危機","停工",
    "違約","下修","低於預期","遭罰","裁員","關廠"]
RISK_KEYWORDS=["下修","虧損","違約","裁員","調查","警示","停工","財務危機","關廠","遭罰"]

def score_sentiment(text:str)->str:
    b=sum(1 for kw in BULLISH_KW if kw in text)
    e=sum(1 for kw in BEARISH_KW if kw in text)
    return "利多" if b>e else "利空" if e>b else "中性"

# ══════════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════════
def calc_rsi(s:pd.Series,p=14)->pd.Series:
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/p,min_periods=p).mean(); al=l.ewm(alpha=1/p,min_periods=p).mean()
    return 100-(100/(1+ag/al.replace(0,np.nan)))

def calc_macd(s:pd.Series,fast=12,slow=26,signal=9):
    ef=s.ewm(span=fast,adjust=False).mean(); es=s.ewm(span=slow,adjust=False).mean()
    m=ef-es; sig=m.ewm(span=signal,adjust=False).mean(); return m,sig,m-sig

def _f(v,d=2): return round(float(v),d) if pd.notna(v) else None
def _num(v):
    if v is None: return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).strip().replace(",","")
    if not s or s in {"-","--","－","null","None"}: return None
    if "_" in s:
        for p in s.split("_"):
            n=_num(p);
            if n is not None: return n
        return None
    try: return float(s)
    except: return None
def _int_num(v): n=_num(v); return int(n) if n is not None else 0
def _quote_time(d,t):
    d=(d or "").strip(); t=(t or "").strip()
    if len(d)==8 and d.isdigit(): return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t}".strip()
    return f"{d} {t}".strip() or None
def _make_empty_df(): return pd.DataFrame(columns=["日期","成交股數","開盤價","最高價","最低價","收盤價"])

# ══════════════════════════════════════════════════════════════════════════════
# 即時報價
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_realtime_quote(stock_id:str)->dict|None:
    ts=int(datetime.now().timestamp()*1000)
    headers={"User-Agent":"Mozilla/5.0","Referer":"https://mis.twse.com.tw/stock/index.jsp"}
    async with httpx.AsyncClient(timeout=10,headers=headers,follow_redirects=True) as client:
        for mkt in ("tse","otc"):
            try:
                r=await client.get(TWSE_MIS_URL,params={"ex_ch":f"{mkt}_{stock_id}.tw","json":"1","delay":"0","_":str(ts)})
                arr=r.json().get("msgArray") or []
                if not arr: continue
                q=arr[0]
                price=_num(q.get("z")) or _num(q.get("a")) or _num(q.get("b"))
                prev=_num(q.get("y"))
                change=round(price-prev,2) if price and prev else None
                chg_pct=round(change/prev*100,2) if change and prev else None
                return {"stock_id":str(q.get("c") or stock_id),"stock_name":get_stock_name(stock_id,q.get("n")),
                        "market":mkt,"realtime":price is not None,"price":price,
                        "open":_num(q.get("o")),"high":_num(q.get("h")),"low":_num(q.get("l")),
                        "previous_close":prev,"change":change,"change_pct":chg_pct,
                        "volume":_int_num(q.get("v")),"quote_time":_quote_time(q.get("d"),q.get("t")),
                        "source":"TWSE MIS","note":"盤中即時或延遲報價"}
            except: continue
    return None

# ══════════════════════════════════════════════════════════════════════════════
# 歷史股價：FinMind → Yahoo → TWSE
# ══════════════════════════════════════════════════════════════════════════════
def _parse_raw_to_df(rows):
    raw=pd.DataFrame(rows); df=pd.DataFrame()
    df["日期"]=pd.to_datetime(raw.get("date"),errors="coerce")
    df["成交股數"]=pd.to_numeric(raw.get("Trading_Volume"),errors="coerce")
    df["開盤價"]=pd.to_numeric(raw.get("open"),errors="coerce")
    df["最高價"]=pd.to_numeric(raw.get("max"),errors="coerce")
    df["最低價"]=pd.to_numeric(raw.get("min"),errors="coerce")
    df["收盤價"]=pd.to_numeric(raw.get("close"),errors="coerce")
    return df.dropna(subset=["日期","收盤價"]).sort_values("日期").reset_index(drop=True)

async def _fetch_from_finmind(stock_id,lookback_days,client):
    ed=datetime.today(); sd=ed-timedelta(days=lookback_days)
    try:
        r=await client.get(FINMIND_BASE,params={"dataset":"TaiwanStockPrice","data_id":stock_id,
            "start_date":sd.strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")},timeout=TIMEOUT)
        if r.status_code in (402,403,429): return None
        r.raise_for_status()
        rows=r.json().get("data",[])
        if not rows: return None
        df=_parse_raw_to_df(rows); return df if not df.empty else None
    except: return None

async def _fetch_from_yahoo(stock_id,lookback_days,client):
    p2=int(datetime.now().timestamp()); p1=int((datetime.now()-timedelta(days=lookback_days)).timestamp())
    for sfx in (".TW",".TWO"):
        try:
            r=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{sfx}?period1={p1}&period2={p2}&interval=1d&events=history",
                headers={"User-Agent":"Mozilla/5.0"},timeout=20,follow_redirects=True)
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
            df=pd.DataFrame(recs); df["日期"]=pd.to_datetime(df["日期"])
            return df.sort_values("日期").reset_index(drop=True)
        except: continue
    return None

async def _fetch_from_twse_official(stock_id,client):
    frames=[]; today=datetime.today()
    for dm in range(3):
        dt=today-timedelta(days=30*dm); ym=dt.strftime("%Y%m")
        try:
            r=await client.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}01&stockNo={stock_id}&response=json",timeout=15)
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

async def fetch_price_with_fallback(stock_id:str,lookback_days:int=400)->tuple[pd.DataFrame,str]:
    async with httpx.AsyncClient() as client:
        df=await _fetch_from_finmind(stock_id,lookback_days,client)
        if df is not None and not df.empty: return df,"FinMind"
        df=await _fetch_from_yahoo(stock_id,lookback_days,client)
        if df is not None and not df.empty: return df,"Yahoo Finance"
        df=await _fetch_from_twse_official(stock_id,client)
        if df is not None and not df.empty: return df,"TWSE Official"
    return _make_empty_df(),"none"

async def _fetch_stock_name_from_api(stock_id:str)->str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get(TWSE_NAME_URL,params={"stockNo":stock_id})
            data=r.json()
            if isinstance(data,dict):
                for key in ["data","msgArray"]:
                    arr=data.get(key)
                    if arr and isinstance(arr,list) and arr:
                        row=arr[0]
                        if isinstance(row,list) and len(row)>1: return row[1]
                        if isinstance(row,dict): return row.get("公司名稱",row.get("Name",""))
    except: pass
    return ""

# ══════════════════════════════════════════════════════════════════════════════
# 新聞
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_news(stock_id:str,stock_name:str="")->list:
    query=stock_name if stock_name and stock_name!=stock_id else stock_id
    items=[]
    async with httpx.AsyncClient(timeout=15) as client:
        for url in [f"https://news.google.com/rss/search?q={query}+台股&hl=zh-TW&gl=TW&ceid=TW:zh-TW",
                    f"https://news.google.com/rss/search?q={stock_id}&hl=zh-TW&gl=TW&ceid=TW:zh-TW"]:
            try:
                r=await client.get(url,follow_redirects=True)
                root=ET.fromstring(r.content)
                for el in root.findall(".//item")[:10]:
                    title=el.findtext("title","")
                    items.append({"title":title,"link":el.findtext("link",""),
                                  "pub_date":el.findtext("pubDate",""),"sentiment":score_sentiment(title)})
                if items: break
            except: continue
    seen,unique=set(),[]
    for n in items:
        if n["title"] not in seen: seen.add(n["title"]); unique.append(n)
    return unique[:10]

# ══════════════════════════════════════════════════════════════════════════════
# 宏觀資料
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_macro_context()->dict:
    result={"usd_twd":None,"dxy":None,"risk_note":""}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for sym,key in [("TWD=X","usd_twd"),("DX-Y.NYB","dxy")]:
                try:
                    r=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d",
                        headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True)
                    if r.status_code==200:
                        res=r.json().get("chart",{}).get("result")
                        if res:
                            closes=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
                            valid=[c for c in closes if c is not None]
                            if valid: result[key]=round(valid[-1],3 if key=="usd_twd" else 2)
                except: pass
    except: pass
    notes=[]
    usd,dxy=result["usd_twd"],result["dxy"]
    if usd and usd>32.0: notes.append(f"USD/TWD {usd}，匯率偏強")
    if dxy and dxy>104:  notes.append(f"DXY {dxy}，美元指數偏強")
    result["risk_note"]="，".join(notes) if notes else ("宏觀資料暫時無法取得" if not usd and not dxy else "宏觀環境無明顯壓力")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標計算
# ══════════════════════════════════════════════════════════════════════════════
def compute_indicators(df:pd.DataFrame)->pd.DataFrame:
    if df.empty: return df
    c=df["收盤價"]
    df["MA5"]=c.rolling(5).mean()
    df["MA20"]=c.rolling(20).mean()
    df["MA60"]=c.rolling(60).mean()
    df["RSI"]=calc_rsi(c,14)
    df["MACD"],df["Signal"],df["Hist"]=calc_macd(c)
    # 布林通道
    df["BB_mid"]=c.rolling(20).mean()
    bb_std=c.rolling(20).std()
    df["BB_upper"]=df["BB_mid"]+2*bb_std
    df["BB_lower"]=df["BB_mid"]-2*bb_std
    # ATR (14日)
    hi=df.get("最高價",c); lo=df.get("最低價",c)
    if hi is not None and lo is not None:
        prev_c=c.shift(1)
        tr=pd.concat([hi-lo,(hi-prev_c).abs(),(lo-prev_c).abs()],axis=1).max(axis=1)
        df["ATR"]=tr.rolling(14).mean()
    return df

def technical_score(row:pd.Series)->dict:
    score,reasons=0,[]
    if pd.notna(row.get("MA20")) and row["收盤價"]>row["MA20"]:
        score+=1; reasons.append("✅ 收盤價 > MA20（中線偏多）")
    else: reasons.append("❌ 收盤價 < MA20（中線偏弱）")
    if pd.notna(row.get("MA5")) and pd.notna(row.get("MA20")) and row["MA5"]>row["MA20"]:
        score+=1; reasons.append("✅ MA5 > MA20（均線多頭排列）")
    else: reasons.append("❌ MA5 < MA20（均線空頭排列）")
    if pd.notna(row.get("RSI")):
        if 40<=row["RSI"]<=70: score+=1; reasons.append(f"✅ RSI={row['RSI']:.1f}（健康區間）")
        elif row["RSI"]>70: reasons.append(f"⚠️ RSI={row['RSI']:.1f}（過熱）")
        else: reasons.append(f"❌ RSI={row['RSI']:.1f}（偏弱）")
    if pd.notna(row.get("MACD")) and pd.notna(row.get("Signal")) and row["MACD"]>row["Signal"]:
        score+=1; reasons.append("✅ MACD > Signal（動能偏多）")
    else: reasons.append("❌ MACD < Signal（動能偏空）")
    if pd.notna(row.get("MA20")) and pd.notna(row.get("MA60")) and row["MA20"]>row["MA60"]:
        score+=1; reasons.append("✅ MA20 > MA60（長線向上）")
    else: reasons.append("❌ MA20 < MA60（長線向下）")
    return {"score":score,"max":5,"reasons":reasons}

def backtest_winrate(df:pd.DataFrame)->dict:
    if df.empty: return {"trials":0,"wins":0,"winrate":0}
    req=[c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df2=df.dropna(subset=req) if req else df
    if len(df2)<10: return {"trials":0,"wins":0,"winrate":0}
    cond=((df2["收盤價"]>df2["MA20"])&(df2["MA5"]>df2["MA20"])&(df2["RSI"]>50)&(df2["MACD"]>df2["Signal"]))
    wins=trials=0
    for idx in df2[cond].index:
        pos=df2.index.get_loc(idx)
        if pos+5<len(df2):
            trials+=1
            if df2.iloc[pos+5]["收盤價"]>df2.iloc[pos]["收盤價"]: wins+=1
    return {"trials":trials,"wins":wins,"winrate":round(wins/trials*100,1) if trials else 0}

def volume_analysis(df:pd.DataFrame)->dict:
    if df.empty: return {"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False}
    avg_vol=df.tail(20)["成交股數"].mean()
    latest_vol=df.iloc[-1]["成交股數"]
    ratio=round(float(latest_vol/avg_vol),2) if avg_vol and avg_vol>0 else 1.0
    return {"latest_volume":int(latest_vol) if pd.notna(latest_vol) else 0,
            "avg_volume_20d":int(avg_vol) if pd.notna(avg_vol) else 0,"ratio":ratio,"alert":bool(ratio>=1.5)}

# ══════════════════════════════════════════════════════════════════════════════
# ★ 四面向分析系統 V8
# ══════════════════════════════════════════════════════════════════════════════

def _score_rating(score)->str:
    if score is None: return "資料不足"
    if score>=70: return "強"
    if score>=50: return "中"
    return "弱"

def _overall_rating(s)->str:
    if s>=80: return "強勢"
    if s>=65: return "偏多"
    if s>=50: return "觀望"
    return "偏弱"

# ── A. 技術面分析（4D） ────────────────────────────────────────────────────────
def analyze_technical_4d(df:pd.DataFrame,latest:pd.Series,current_price:float)->dict:
    """計算技術面評分 0-100 + 布林通道 + ATR + 支撐壓力 + 趨勢判斷"""
    reasons,risks=[],[]
    score=0

    # 均線評分（40分）
    ma5 =float(latest["MA5"])  if pd.notna(latest.get("MA5"))  else None
    ma20=float(latest["MA20"]) if pd.notna(latest.get("MA20")) else None
    ma60=float(latest["MA60"]) if pd.notna(latest.get("MA60")) else None
    if ma20 and current_price>ma20:
        score+=15; reasons.append(f"收盤價 {current_price:.0f} 站上 MA20 {ma20:.0f}")
    elif ma20:
        risks.append(f"收盤價低於 MA20 {ma20:.0f}")
    if ma5 and ma20 and ma5>ma20:
        score+=15; reasons.append("MA5 > MA20，短線多頭排列")
    if ma20 and ma60 and ma20>ma60:
        score+=10; reasons.append("MA20 > MA60，長線趨勢向上")
    elif ma60:
        risks.append("MA20 < MA60，長線趨勢偏弱")

    # RSI（20分）
    rsi=float(latest["RSI"]) if pd.notna(latest.get("RSI")) else None
    if rsi:
        if 45<=rsi<=68: score+=20; reasons.append(f"RSI {rsi:.1f} 健康區間 45~68")
        elif rsi>75:    risks.append(f"RSI {rsi:.1f} 過熱，注意追高風險")
        elif rsi<35:    score+=5; risks.append(f"RSI {rsi:.1f} 偏弱，可能反彈")
        else:           score+=8

    # MACD（20分）
    macd=float(latest["MACD"]) if pd.notna(latest.get("MACD")) else None
    sig =float(latest["Signal"]) if pd.notna(latest.get("Signal")) else None
    hist=float(latest["Hist"]) if pd.notna(latest.get("Hist")) else None
    if macd and sig and macd>sig:
        score+=15; reasons.append("MACD 金叉，動能偏多")
    elif macd and sig:
        risks.append("MACD 死叉，動能偏弱")
    if hist and hist>0:
        score+=5; reasons.append("MACD Histogram 正值")

    # 布林通道（20分）
    bb_up =float(latest["BB_upper"]) if pd.notna(latest.get("BB_upper")) else None
    bb_lo =float(latest["BB_lower"]) if pd.notna(latest.get("BB_lower")) else None
    bb_mid=float(latest["BB_mid"])   if pd.notna(latest.get("BB_mid"))   else None
    if bb_up and bb_lo and bb_mid:
        bw=round((bb_up-bb_lo)/bb_mid*100,1)
        if current_price>bb_mid:
            score+=10; reasons.append(f"股價在布林中軌上方（BB寬度 {bw}%）")
        else:
            risks.append(f"股價在布林中軌下方（BB寬度 {bw}%）")
        if current_price<bb_lo:
            score+=10; reasons.append("股價觸及布林下軌，可能反彈")
        if current_price>bb_up*0.99:
            risks.append("股價接近布林上軌，短線追高風險")

    score=max(0,min(100,score))

    # 趨勢判斷
    bull_cond=[(ma5 and ma20 and ma5>ma20),(ma20 and ma60 and ma20>ma60),(macd and sig and macd>sig)]
    bull_cnt=sum(1 for x in bull_cond if x)
    trend="多頭" if bull_cnt>=3 else ("空頭" if bull_cnt==0 else "盤整")

    # 支撐壓力（近20日高低點）
    recent=df.tail(20)
    support  =round(float(recent["最低價"].min()),2) if "最低價" in recent.columns and not recent.empty else None
    resistance=round(float(recent["最高價"].max()),2) if "最高價" in recent.columns and not recent.empty else None

    # ATR
    atr=round(float(latest["ATR"]),2) if pd.notna(latest.get("ATR")) else None

    return {
        "score":score,"rating":_score_rating(score),"trend":trend,
        "support":support,"resistance":resistance,"atr":atr,
        "bb_upper":_f(bb_up),"bb_lower":_f(bb_lo),"bb_mid":_f(bb_mid),
        "rsi":_f(rsi),"macd":_f(macd,4),"reasons":reasons[:4],"risks":risks[:3],
    }

# ── B. 籌碼面分析 ─────────────────────────────────────────────────────────────
async def fetch_chip_data(stock_id:str)->dict:
    """
    從 TWSE 官方抓三大法人 + 融資融券。
    任何失敗都回傳 None，不中斷主流程。
    """
    today=datetime.today()
    # 嘗試近 5 個交易日
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=12,follow_redirects=True) as client:
                # 三大法人
                r=await client.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dt}&selectType=ALLBUT0999&response=json")
                if r.status_code!=200: continue
                data=r.json(); rows=data.get("data",[])
                if not rows: continue
                # 找到目標股票（欄位0=代號）
                row=next((x for x in rows if str(x[0]).strip()==stock_id),None)
                if not row: continue
                def _p(x):
                    try: return int(str(x).replace(",","").replace("─","0"))
                    except: return 0
                foreign=_p(row[4]) if len(row)>4 else 0
                trust  =_p(row[10]) if len(row)>10 else 0
                dealer =_p(row[14]) if len(row)>14 else 0
                total  =foreign+trust+dealer
                return {"date":dt,"foreign_net_buy":foreign,"investment_trust_net_buy":trust,
                        "dealer_net_buy":dealer,"three_major_total":total,"data_available":True}
        except: continue
    return {"date":None,"foreign_net_buy":None,"investment_trust_net_buy":None,
            "dealer_net_buy":None,"three_major_total":None,"data_available":False}

async def fetch_margin_data(stock_id:str)->dict:
    """融資融券資料（TWSE 近期）"""
    today=datetime.today()
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=12,follow_redirects=True) as client:
                r=await client.get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={dt}&selectType=ALL&response=json")
                if r.status_code!=200: continue
                rows=r.json().get("data",[])
                row=next((x for x in rows if str(x[0]).strip()==stock_id),None)
                if not row or len(row)<14: continue
                def _p(x):
                    try: return int(str(x).replace(",",""))
                    except: return 0
                return {"date":dt,"margin_balance":_p(row[3]),"margin_change":_p(row[4]),
                        "short_balance":_p(row[9]),"short_change":_p(row[10]),"data_available":True}
        except: continue
    return {"date":None,"margin_balance":None,"margin_change":None,
            "short_balance":None,"short_change":None,"data_available":False}

def analyze_chip_4d(chip:dict,margin:dict)->dict:
    reasons,risks=[],[]
    score=50  # 中性起點

    if not chip.get("data_available") and not margin.get("data_available"):
        return {"score":None,"rating":"資料不足","foreign_net_buy":None,
                "investment_trust_net_buy":None,"dealer_net_buy":None,
                "three_major_total":None,"margin_change":None,"short_change":None,
                "reasons":["籌碼資料暫時無法取得"],"risks":[]}

    # 三大法人
    foreign=chip.get("foreign_net_buy") or 0
    trust  =chip.get("investment_trust_net_buy") or 0
    dealer =chip.get("dealer_net_buy") or 0
    total  =chip.get("three_major_total") or 0

    if chip.get("data_available"):
        if foreign>0: score+=15; reasons.append(f"外資買超 {foreign:,} 張")
        elif foreign<0: score-=15; risks.append(f"外資賣超 {abs(foreign):,} 張")
        if trust>0: score+=10; reasons.append(f"投信買超 {trust:,} 張")
        elif trust<0: score-=5; risks.append(f"投信賣超 {abs(trust):,} 張")
        if dealer>0: score+=5; reasons.append(f"自營商買超 {dealer:,} 張")
        if total>0: reasons.append(f"三大法人合計買超 {total:,} 張")
        elif total<0: risks.append(f"三大法人合計賣超 {abs(total):,} 張")

    # 融資融券
    mc=margin.get("margin_change") or 0
    sc=margin.get("short_change") or 0
    if margin.get("data_available"):
        if mc<0: score+=5; reasons.append(f"融資減少 {abs(mc):,} 張（去化壓力）")
        elif mc>0: score-=5; risks.append(f"融資增加 {mc:,} 張（追價風險）")
        if sc>0: score+=5; reasons.append(f"融券增加 {sc:,} 張（空方布局）")
        elif sc<0: score-=3; risks.append(f"融券減少 {abs(sc):,} 張（軋空回補）")

    score=max(0,min(100,score))
    return {"score":score,"rating":_score_rating(score),
            "foreign_net_buy":chip.get("foreign_net_buy"),
            "investment_trust_net_buy":chip.get("investment_trust_net_buy"),
            "dealer_net_buy":chip.get("dealer_net_buy"),
            "three_major_total":chip.get("three_major_total"),
            "margin_change":margin.get("margin_change"),
            "short_change":margin.get("short_change"),
            "reasons":reasons[:4],"risks":risks[:3]}

# ── C. 基本面分析 ─────────────────────────────────────────────────────────────
async def fetch_fundamental_data(stock_id:str)->dict:
    """
    從 FinMind 抓月營收、EPS 等資料。
    FinMind 失敗時回傳空資料，不中斷主流程。
    """
    result={"revenue_yoy":None,"revenue_mom":None,"revenue_trend":None,
            "eps":None,"roe":None,"gross_margin":None,"operating_margin":None,
            "per":None,"pbr":None,"dividend_yield":None,"data_available":False}
    end_date=datetime.today()
    start_date=end_date-timedelta(days=365)

    async with httpx.AsyncClient(timeout=20) as client:
        # 月營收
        try:
            r=await client.get(FINMIND_BASE,params={"dataset":"TaiwanStockMonthRevenue",
                "data_id":stock_id,"start_date":(end_date-timedelta(days=120)).strftime("%Y-%m-%d"),
                "end_date":end_date.strftime("%Y-%m-%d")},timeout=20)
            if r.status_code not in (402,403,429) and r.status_code==200:
                rows=r.json().get("data",[])
                if len(rows)>=2:
                    rows=sorted(rows,key=lambda x:x.get("date",""))
                    latest_rev=_num(rows[-1].get("revenue"))
                    prev_rev  =_num(rows[-2].get("revenue"))
                    yoy_rev   =_num(rows[-1].get("year_growth_rate") or rows[-1].get("yoy"))
                    if latest_rev and prev_rev:
                        result["revenue_mom"]=round((latest_rev-prev_rev)/prev_rev*100,1)
                    result["revenue_yoy"]=yoy_rev
                    result["revenue_trend"]=[_num(r.get("revenue")) for r in rows[-3:]]
                    result["data_available"]=True
        except: pass

        # 財務指標
        for ds,key in [("TaiwanStockPER","per"),("TaiwanStockPBR","pbr")]:
            try:
                r=await client.get(FINMIND_BASE,params={"dataset":ds,"data_id":stock_id,
                    "start_date":(end_date-timedelta(days=30)).strftime("%Y-%m-%d"),
                    "end_date":end_date.strftime("%Y-%m-%d")},timeout=15)
                if r.status_code==200:
                    rows=r.json().get("data",[])
                    if rows:
                        v=rows[-1].get("PER" if ds=="TaiwanStockPER" else "PBR")
                        result[key]=_num(v)
                        result["data_available"]=True
            except: pass

        # EPS / ROE / 毛利率（財務報表）
        try:
            r=await client.get(FINMIND_BASE,params={"dataset":"TaiwanStockFinancialStatements",
                "data_id":stock_id,"start_date":start_date.strftime("%Y-%m-%d"),
                "end_date":end_date.strftime("%Y-%m-%d")},timeout=20)
            if r.status_code==200:
                rows=r.json().get("data",[])
                eps_rows=[x for x in rows if "EPS" in str(x.get("type",""))]
                roe_rows=[x for x in rows if "ROE" in str(x.get("type",""))]
                gm_rows =[x for x in rows if "毛利率" in str(x.get("type",""))]
                om_rows =[x for x in rows if "營業利益率" in str(x.get("type",""))]
                if eps_rows: result["eps"]=_num(eps_rows[-1].get("value")); result["data_available"]=True
                if roe_rows: result["roe"]=_num(roe_rows[-1].get("value"))
                if gm_rows:  result["gross_margin"]=_num(gm_rows[-1].get("value"))
                if om_rows:  result["operating_margin"]=_num(om_rows[-1].get("value"))
        except: pass

        # 殖利率
        try:
            r=await client.get(FINMIND_BASE,params={"dataset":"TaiwanStockDividend",
                "data_id":stock_id,"start_date":(end_date-timedelta(days=400)).strftime("%Y-%m-%d"),
                "end_date":end_date.strftime("%Y-%m-%d")},timeout=15)
            if r.status_code==200:
                rows=r.json().get("data",[])
                if rows:
                    total_div=sum(_num(x.get("StockEarningsDistribution",0) or x.get("cash_dividends",0) or 0) for x in rows[-4:] if _num(x.get("cash_dividends",0) or 0))
                    result["dividend_yield"]=total_div
        except: pass

    return result

def analyze_fundamental_4d(fund:dict)->dict:
    reasons,risks=[],[]
    score=50  # 中性起點

    if not fund.get("data_available"):
        return {"score":None,"rating":"資料不足",
                "revenue_yoy":None,"revenue_mom":None,"eps":None,"roe":None,
                "gross_margin":None,"operating_margin":None,"per":None,"pbr":None,
                "reasons":["基本面資料暫時無法取得（FinMind 免費配額限制）"],"risks":[]}

    # 月營收 YoY
    yoy=fund.get("revenue_yoy")
    if yoy is not None:
        if yoy>=20:   score+=20; reasons.append(f"月營收年成長 {yoy:.1f}%（強勁）")
        elif yoy>=5:  score+=10; reasons.append(f"月營收年成長 {yoy:.1f}%")
        elif yoy<0:   score-=10; risks.append(f"月營收年衰退 {yoy:.1f}%")

    # ROE
    roe=fund.get("roe")
    if roe is not None:
        if roe>=15:  score+=15; reasons.append(f"ROE {roe:.1f}%（優質）")
        elif roe>=8: score+=8;  reasons.append(f"ROE {roe:.1f}%（尚可）")
        elif roe<0:  score-=10; risks.append(f"ROE {roe:.1f}%（虧損）")

    # 毛利率
    gm=fund.get("gross_margin")
    if gm is not None:
        if gm>=30:  score+=10; reasons.append(f"毛利率 {gm:.1f}%（高護城河）")
        elif gm<10: risks.append(f"毛利率偏低 {gm:.1f}%")

    # EPS
    eps=fund.get("eps")
    if eps is not None:
        if eps>0:  score+=5; reasons.append(f"EPS {eps:.2f}元（獲利中）")
        elif eps<0: score-=10; risks.append(f"EPS {eps:.2f}元（虧損）")

    # PER 估值
    per=fund.get("per")
    if per is not None:
        if 10<=per<=25: score+=5; reasons.append(f"本益比 {per:.1f}x（合理）")
        elif per>40:    risks.append(f"本益比 {per:.1f}x（偏高）")
        elif per<0:     risks.append(f"本益比為負（虧損中）")

    score=max(0,min(100,score))
    return {"score":score,"rating":_score_rating(score),
            "revenue_yoy":fund.get("revenue_yoy"),"revenue_mom":fund.get("revenue_mom"),
            "eps":fund.get("eps"),"roe":fund.get("roe"),
            "gross_margin":fund.get("gross_margin"),"operating_margin":fund.get("operating_margin"),
            "per":fund.get("per"),"pbr":fund.get("pbr"),
            "revenue_trend":fund.get("revenue_trend"),
            "reasons":reasons[:4],"risks":risks[:3]}

# ── D. 消息面分析 ─────────────────────────────────────────────────────────────
def analyze_news_4d(news:list)->dict:
    if not news:
        return {"score":50,"rating":"中性","sentiment":"中性",
                "bullish_count":0,"bearish_count":0,"neutral_count":0,
                "top_news":[],"risk_keywords":[],"reasons":["暫無相關新聞"],"risks":[]}

    bull=sum(1 for n in news if n.get("sentiment")=="利多")
    bear=sum(1 for n in news if n.get("sentiment")=="利空")
    neu =sum(1 for n in news if n.get("sentiment")=="中性")
    total=len(news)

    # 風險字詞偵測
    risk_kws=[kw for kw in RISK_KEYWORDS for n in news if kw in n.get("title","")]
    risk_kws=list(dict.fromkeys(risk_kws))[:5]

    score=50
    reasons,risks=[],[]
    if bull>bear:
        score+=min(30,bull*8); reasons.append(f"利多新聞 {bull} 則，情緒偏正面")
        if bull>=3: reasons.append("多則利多消息，市場關注度高")
    elif bear>bull:
        score-=min(30,bear*8); risks.append(f"利空新聞 {bear} 則，情緒偏負面")
    else:
        reasons.append(f"新聞情緒中性（利多{bull}/利空{bear}/中性{neu}）")

    if risk_kws:
        score-=min(20,len(risk_kws)*5)
        risks.append(f"偵測到風險字詞：{', '.join(risk_kws[:3])}")

    score=max(0,min(100,score))
    sentiment="利多" if bull>bear else ("利空" if bear>bull else "中性")
    top_news=[{"title":n["title"][:60],"sentiment":n["sentiment"],"link":n.get("link","")} for n in news[:5]]

    return {"score":score,"rating":_score_rating(score),"sentiment":sentiment,
            "bullish_count":bull,"bearish_count":bear,"neutral_count":neu,
            "top_news":top_news,"risk_keywords":risk_kws,
            "reasons":reasons[:3],"risks":risks[:3]}

# ── 總分 overall ──────────────────────────────────────────────────────────────
def compute_overall_4d(fundamental:dict,technical:dict,chip:dict,news:dict)->dict:
    # 加權：基本面25%、技術面35%、籌碼面25%、消息面15%
    weights={"fundamental":0.25,"technical":0.35,"chip":0.25,"news":0.15}
    scores={"fundamental":fundamental.get("score"),
            "technical":technical.get("score"),
            "chip":chip.get("score"),
            "news":news.get("score")}

    # 有效分項加權
    valid=[(k,v,weights[k]) for k,v in scores.items() if v is not None]
    if not valid:
        return {"overall_score":None,"rating":"資料不足","summary":"各面向資料均不足，無法評估。",
                "weights":weights,"scores":scores}

    total_w=sum(w for _,_,w in valid)
    weighted=sum(v*w for _,v,w in valid)
    overall_score=round(weighted/total_w,1)

    # 摘要
    parts=[]
    for k,v,_ in [("fundamental",fundamental,None),("technical",technical,None),
                   ("chip",chip,None),("news",news,None)]:
        label={"fundamental":"基本面","technical":"技術面","chip":"籌碼面","news":"消息面"}[k]
        s=v.get("score"); r=v.get("rating","資料不足")
        if s is None: parts.append(f"{label}資料不足")
        elif s>=70:   parts.append(f"{label}偏強")
        elif s>=50:   parts.append(f"{label}普通")
        else:         parts.append(f"{label}偏弱")

    action_map={"強勢":"整體偏多，可留意入場機會。","偏多":"技術與籌碼訊號偏正，建議觀察確認後再進場。",
                "觀望":"各面向訊號分歧，建議觀望等待更明確訊號。","偏弱":"技術或基本面存在疑慮，建議保守。"}
    rating=_overall_rating(overall_score)
    summary="，".join(parts)+"。"+action_map.get(rating,"")

    return {"overall_score":overall_score,"rating":rating,"summary":summary,
            "weights":weights,"scores":scores}

# ══════════════════════════════════════════════════════════════════════════════
# 建議入場價
# ══════════════════════════════════════════════════════════════════════════════
def compute_entry_price(row:pd.Series,current_price:float,signal:str)->float|None:
    if signal=="AVOID": return None
    ma5 =float(row["MA5"])  if pd.notna(row.get("MA5"))  else None
    ma20=float(row["MA20"]) if pd.notna(row.get("MA20")) else None
    if signal=="BUY":
        if ma5 and current_price>ma5:   return round(ma5,2)
        if ma20 and current_price>ma20: return round(ma20,2)
        return round(current_price*1.01,2)
    if ma20 and current_price>ma20: return round(ma20,2)
    return round(current_price,2)

# ══════════════════════════════════════════════════════════════════════════════
# ★ AI 策略評分引擎 V8（整合 analysis_4d）
# ══════════════════════════════════════════════════════════════════════════════
def compute_ai_signal(score_info:dict,row:pd.Series,vol_info:dict,winrate_info:dict,
                      news:list,current_price:float,macro:dict|None=None,
                      analysis_4d:dict|None=None)->dict:
    entry_reason:list[str]=[]
    risk_reason:list[str]=[]
    risk_factors:list[str]=[]

    def _get(col): return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None

    rsi_val=_get("RSI"); ma5_val=_get("MA5"); ma20_val=_get("MA20"); ma60_val=_get("MA60")
    macd_val=_get("MACD"); sig_val=_get("Signal"); hist_val=_get("Hist")

    # 趨勢 30
    trend=0
    if ma20_val and current_price>ma20_val: trend+=10; entry_reason.append("收盤價站上 MA20（+10）")
    if ma5_val and ma20_val and ma5_val>ma20_val: trend+=10; entry_reason.append("MA5 > MA20 均線多頭（+10）")
    if ma20_val and ma60_val and ma20_val>ma60_val: trend+=10; entry_reason.append("MA20 > MA60 長線向上（+10）")

    # 動能 25
    momentum=0
    if macd_val is not None and sig_val is not None and macd_val>sig_val:
        momentum+=10; entry_reason.append("MACD > Signal 動能偏多（+10）")
    if hist_val is not None and hist_val>0: momentum+=5; entry_reason.append("MACD Histogram > 0（+5）")
    if rsi_val is not None:
        if 45<=rsi_val<=68: momentum+=10; entry_reason.append(f"RSI={rsi_val:.1f} 健康區間（+10）")
        elif rsi_val>75:    momentum-=10; risk_reason.append(f"RSI={rsi_val:.1f} 過熱（-10）")
        elif rsi_val<35:    momentum-=5;  risk_reason.append(f"RSI={rsi_val:.1f} 偏弱（-5）")

    # 量能 15
    volume=0; ratio=vol_info.get("ratio",1.0)
    if ratio>=1.8 and rsi_val is not None and rsi_val>70:
        volume-=5; risk_reason.append(f"放量（{ratio}x）RSI 偏高（-5）")
    elif ratio>=1.2:
        volume+=8; entry_reason.append(f"成交量 {ratio}x 均量（+8）")
        if ma20_val and current_price>ma20_val: volume+=5; entry_reason.append("量增且站上 MA20（+5）")
        volume=min(volume,15)
    elif ma20_val and current_price>ma20_val: volume+=5; entry_reason.append("量能正常且站上 MA20（+5）")

    # 回測 20
    wr=winrate_info.get("winrate",0); trials=winrate_info.get("trials",0)
    backtest=0
    if trials>=5:
        if wr>=65:   backtest=20; entry_reason.append(f"回測勝率 {wr}%（+20）")
        elif wr>=55: backtest=12; entry_reason.append(f"回測勝率 {wr}%（+12）")
        elif wr>=45: backtest=6;  entry_reason.append(f"回測勝率 {wr}%（+6）")
        else:        risk_reason.append(f"回測勝率 {wr}%，不足 45%")

    # 新聞 10
    bull_n=sum(1 for n in news if n.get("sentiment")=="利多")
    bear_n=sum(1 for n in news if n.get("sentiment")=="利空")
    news_pts=6 if bull_n>bear_n else (-6 if bear_n>bull_n else 2)
    if bull_n>bear_n: entry_reason.append(f"新聞偏多（{bull_n}則，+6）")
    elif bear_n>bull_n: risk_reason.append(f"新聞偏空（{bear_n}則，-6）")

    base_score=max(0,min(100,trend+momentum+volume+backtest+news_pts))
    score_breakdown={"trend":max(0,min(30,trend)),"momentum":max(0,min(25,momentum)),
                     "volume":max(0,min(15,volume)),"backtest":max(0,min(20,backtest)),
                     "news":max(0,min(10,news_pts))}

    # 風險模型
    risk_penalty=0
    if rsi_val and rsi_val>75: risk_penalty-=10; risk_factors.append(f"RSI={rsi_val:.1f} 過熱（-10）")
    elif rsi_val and rsi_val<35: risk_penalty-=5; risk_factors.append(f"RSI={rsi_val:.1f} 偏弱（-5）")
    if ma20_val and ma20_val>0:
        pct=(current_price-ma20_val)/ma20_val*100
        if pct>12: risk_penalty-=8; risk_factors.append(f"股價距 MA20 +{pct:.1f}%（-8）")
    if ratio>=2.5 and vol_info.get("alert"): risk_penalty-=8; risk_factors.append(f"爆量（{ratio}x）（-8）")
    if trials>=5 and wr<45: risk_penalty-=10; risk_factors.append(f"歷史勝率 {wr}%（-10）")
    if trials<5: risk_penalty-=5; risk_factors.append("回測樣本不足（-5）")

    macro=macro or {}
    macro_penalty=0
    usd_twd=macro.get("usd_twd"); dxy=macro.get("dxy")
    if usd_twd and usd_twd>32.0: macro_penalty-=3; risk_factors.append(f"USD/TWD={usd_twd}（-3）")
    if dxy and dxy>104:           macro_penalty-=3; risk_factors.append(f"DXY={dxy}（-3）")

    # ★ 四面向加減分
    a4=analysis_4d or {}
    a4_bonus=0
    overall_4d=a4.get("overall",{})
    chip_4d=a4.get("chip",{})
    news_4d=a4.get("news",{})
    tech_4d=a4.get("technical",{})
    fund_4d=a4.get("fundamental",{})

    if overall_4d.get("overall_score") is not None:
        ov=overall_4d["overall_score"]
        if ov>=80: a4_bonus+=8; entry_reason.append(f"四面向總分 {ov} 分強勢（+8）")
        elif ov>=65: a4_bonus+=3; entry_reason.append(f"四面向總分 {ov} 分偏多（+3）")

    chip_score=chip_4d.get("score")
    if chip_score is not None and chip_score<40:
        a4_bonus-=8; risk_reason.append(f"籌碼面偏弱（{chip_score}分）（-8）")

    if news_4d.get("sentiment")=="利空":
        a4_bonus-=5; risk_reason.append("消息面偏負面（-5）")

    # 技術強但基本面弱 → 降為 WATCH
    tech_strong=tech_4d.get("score",50)>=70
    fund_weak  =fund_4d.get("score") is not None and fund_4d.get("score",50)<40

    total_penalty=risk_penalty+macro_penalty
    risk_level="HIGH" if total_penalty<=-15 else "MEDIUM" if total_penalty<=-8 else "LOW"
    final_score=max(0,min(100,base_score+risk_penalty+macro_penalty+a4_bonus))

    risk_model={"base_score":base_score,"risk_penalty":risk_penalty,"macro_penalty":macro_penalty,
                "a4_bonus":a4_bonus,"final_score":final_score,"risk_level":risk_level,"risk_factors":risk_factors}

    if final_score>=75:   signal="BUY"
    elif final_score>=55: signal="WATCH"
    else:                 signal="AVOID"

    if signal=="BUY": target_price=round(current_price*1.06,2)
    elif signal=="WATCH": target_price=round(current_price*1.03,2)
    else: target_price=None

    stop_loss=round(ma20_val*0.98,2) if ma20_val else round(current_price*0.95,2)
    if target_price and stop_loss and current_price>stop_loss:
        rr=round((target_price-current_price)/(current_price-stop_loss),2)
        risk_reward_ratio=rr if rr>0 else None
    else: risk_reward_ratio=None

    if signal=="BUY":
        if risk_reward_ratio is None or risk_reward_ratio<1.5:
            signal="WATCH"; risk_reason.append("風險報酬比不足（<1.5），暫不建議追價")
        elif wr<50 and trials>=5:
            signal="WATCH"; risk_reason.append("歷史勝率不足 50%，需保守觀察")
        # ★ 技術強但基本面弱降為 WATCH
        elif tech_strong and fund_weak:
            signal="WATCH"; risk_reason.append("技術面偏強但基本面偏弱，建議觀望")

    if wr>=65: holding_days="5-10 天"
    elif wr>=50: holding_days="3-5 天"
    else: holding_days="不建議持有"

    if signal=="BUY": summary="技術面與回測條件良好，風險可控，但仍需留意市場變化。"
    elif signal=="WATCH": summary="訊號尚未完全確認，或風險報酬比不足，建議觀望。"
    else: summary="條件不足，不建議進場。"

    entry_price=compute_entry_price(row,current_price,signal)
    macro_context={"usd_twd":usd_twd,"dxy":dxy,"note":macro.get("risk_note","")}

    return {"signal":signal,"confidence":final_score,"score_breakdown":score_breakdown,
            "risk_model":risk_model,"macro_context":macro_context,
            "entry_reason":entry_reason,"risk_reason":risk_reason,"summary":summary,
            "entry_price":entry_price,"target_price":target_price,"stop_loss":stop_loss,
            "holding_days":holding_days,"risk_reward_ratio":risk_reward_ratio,
            "disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

# ══════════════════════════════════════════════════════════════════════════════
# LINE
# ══════════════════════════════════════════════════════════════════════════════
def _line_configured(): return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID and ENABLE_LINE_ALERTS)
def _check_line_config():
    if not LINE_CHANNEL_ACCESS_TOKEN: raise HTTPException(503,detail="LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
    if not LINE_TO_ID: raise HTTPException(503,detail="LINE_TO_ID 尚未設定")
    if not ENABLE_LINE_ALERTS: raise HTTPException(503,detail="ENABLE_LINE_ALERTS 未設為 true")

async def send_line_message(message:str)->dict:
    headers={"Authorization":f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}","Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r=await client.post(LINE_PUSH_URL,headers=headers,json={"to":LINE_TO_ID,"messages":[{"type":"text","text":message}]})
            if r.status_code==200: return {"success":True,"message":"LINE 訊息發送成功"}
            return {"success":False,"message":f"LINE API 錯誤：{r.status_code}"}
    except Exception as e: return {"success":False,"message":f"發送失敗：{str(e)}"}

def _build_line_message(stock_id,stock_name,ai,price,overall=None):
    display=f"{stock_name} ({stock_id})" if stock_name and stock_name!=stock_id else stock_id
    reasons_text="\n".join(f"- {r.split('（')[0]}" for r in ai["entry_reason"][:4])
    rr=ai.get("risk_reward_ratio"); ep=ai.get("entry_price")
    ov_line=f"四面向總分：{overall:.0f}" if overall else ""
    return (f"📈 自選股 AI 買點\n股票：{display}\n訊號：{ai['signal']}\n信心：{ai['confidence']}/100\n"
            f"{ov_line}\n即時價：{price}  建議入場：{ep or '—'}\n"
            f"目標價：{ai['target_price']}  止蝕：{ai['stop_loss']}\n"
            f"風險報酬比：{rr}x  建議持有：{ai['holding_days']}\n\n"
            f"理由：\n{reasons_text}\n\n{ai['disclaimer']}")

# ══════════════════════════════════════════════════════════════════════════════
# 進階回測
# ══════════════════════════════════════════════════════════════════════════════
def advanced_backtest(df,holding_days=5,min_score=75):
    if df.empty: return {"total_trades":0,"wins":0,"losses":0,"winrate":0,"avg_return":0,"best_return":0,"worst_return":0,"max_drawdown":0,"profit_factor":0,"trades":[]}
    df=df.copy().reset_index(drop=True); df=compute_indicators(df)
    req=[c for c in ["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df=df.dropna(subset=req) if req else df
    trades,equity,peak,max_dd=[],1.0,1.0,0.0
    for i,(_,row) in enumerate(df.iterrows()):
        if i+holding_days>=len(df): break
        sc=technical_score(row)
        vi={"alert":False,"ratio":1.0,"latest_volume":0,"avg_volume_20d":0}
        wi={"winrate":0,"trials":0,"wins":0}
        cur=float(row["收盤價"])
        ai=compute_ai_signal(sc,row,vi,wi,[],cur)
        if ai["confidence"]<min_score: continue
        ep=float(df.iloc[i+holding_days]["收盤價"])
        rp=round((ep-cur)/cur*100,2)
        trades.append({"date":row["日期"].strftime("%Y-%m-%d"),"entry_price":cur,"exit_price":ep,
                       "return_pct":rp,"win":ep>cur,"confidence":ai["confidence"],"signal":ai["signal"]})
        equity*=(1+rp/100); peak=max(peak,equity); dd=(peak-equity)/peak*100; max_dd=max(max_dd,dd)
    total=len(trades); wins=sum(1 for t in trades if t["win"])
    rets=[t["return_pct"] for t in trades]
    gain=sum(r for r in rets if r>0); loss=abs(sum(r for r in rets if r<0))
    return {"total_trades":total,"wins":wins,"losses":total-wins,
            "winrate":round(wins/total*100,1) if total else 0,
            "avg_return":round(sum(rets)/total,2) if total else 0,
            "best_return":round(max(rets),2) if rets else 0,
            "worst_return":round(min(rets),2) if rets else 0,
            "max_drawdown":round(max_dd,2),
            "profit_factor":round(gain/loss,2) if loss else 0,
            "trades":list(reversed(trades))[:20]}

# ══════════════════════════════════════════════════════════════════════════════
# 核心分析函式（供 /api/stock 和 /api/scan/ai 共用）
# ══════════════════════════════════════════════════════════════════════════════
async def _analyze_stock(stock_id:str,macro:dict,lookback_days:int=400,with_4d:bool=True)->dict:
    api_name_t=asyncio.create_task(_fetch_stock_name_from_api(stock_id))
    price_df,data_source=await fetch_price_with_fallback(stock_id,lookback_days)
    api_name=await api_name_t
    stock_name=get_stock_name(stock_id,api_name)

    if price_df.empty:
        rt=await fetch_realtime_quote(stock_id)
        return {"stock_id":stock_id,"stock_name":stock_name,"error":"歷史資料不可用",
                "realtime_quote":rt,"data_source":"none"}

    price_df=compute_indicators(price_df)
    latest=price_df.iloc[-1]
    prev=price_df.iloc[-2] if len(price_df)>1 else latest
    change=float(latest["收盤價"]-prev["收盤價"])
    change_pct=round(change/float(prev["收盤價"])*100,2) if float(prev["收盤價"]) else 0

    score_info=technical_score(latest)
    winrate=backtest_winrate(price_df)
    vol_info=volume_analysis(price_df)
    conclusion="短線偏多 📈" if score_info["score"]>=4 else ("短線偏弱 📉" if score_info["score"]<=2 else "觀望 ➡️")

    rsi_val=float(latest["RSI"]) if "RSI" in latest.index and pd.notna(latest.get("RSI")) else None
    rsi_alert=None
    if rsi_val:
        if rsi_val>70: rsi_alert="⚠️ RSI 過熱（>70）"
        elif rsi_val<30: rsi_alert="⚠️ RSI 過冷（<30）"

    # 並行抓新聞+即時報價+四面向資料
    if with_4d:
        news,rt,fund_raw,chip_raw,margin_raw = await asyncio.gather(
            fetch_news(stock_id,stock_name),
            fetch_realtime_quote(stock_id),
            fetch_fundamental_data(stock_id),
            fetch_chip_data(stock_id),
            fetch_margin_data(stock_id),
        )
    else:
        news,rt = await asyncio.gather(fetch_news(stock_id,stock_name),fetch_realtime_quote(stock_id))
        fund_raw={"data_available":False}
        chip_raw={"data_available":False}
        margin_raw={"data_available":False}

    cur_price=float(rt["price"]) if rt and rt.get("price") is not None else float(latest["收盤價"])

    # 四面向分析
    tech_4d   = analyze_technical_4d(price_df,latest,cur_price)
    fund_4d   = analyze_fundamental_4d(fund_raw)
    chip_4d   = analyze_chip_4d(chip_raw,margin_raw)
    news_4d   = analyze_news_4d(news)
    overall_4d= compute_overall_4d(fund_4d,tech_4d,chip_4d,news_4d)

    analysis_4d={"fundamental":fund_4d,"technical":tech_4d,"chip":chip_4d,"news":news_4d,"overall":overall_4d}

    ai=compute_ai_signal(score_info,latest,vol_info,winrate,news,cur_price,macro,analysis_4d)

    chart_data=[]
    for _,row in price_df.tail(60).iterrows():
        chart_data.append({"date":row["日期"].strftime("%Y-%m-%d"),
            "open":_f(row.get("開盤價")),"high":_f(row.get("最高價")),
            "low":_f(row.get("最低價")),"close":_f(row.get("收盤價")),
            "volume":int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
            "ma5":_f(row.get("MA5")),"ma20":_f(row.get("MA20")),"ma60":_f(row.get("MA60")),
            "rsi":_f(row.get("RSI")),"macd":_f(row.get("MACD"),4),
            "signal":_f(row.get("Signal"),4),"hist":_f(row.get("Hist"),4),
            "bb_upper":_f(row.get("BB_upper")),"bb_lower":_f(row.get("BB_lower")),})

    return {
        "stock_id":stock_id,"stock_name":stock_name,
        "last_date":latest["日期"].strftime("%Y-%m-%d"),"data_source":data_source,
        "price":{"close":_f(cur_price),"daily_close":_f(latest["收盤價"]),
            "open":_f(rt.get("open") if rt else latest.get("開盤價")),
            "high":_f(rt.get("high") if rt else latest.get("最高價")),
            "low":_f(rt.get("low") if rt else latest.get("最低價")),
            "change":(_f(rt.get("change"),2) if rt and rt.get("change") is not None else round(change,2)),
            "change_pct":(_f(rt.get("change_pct"),2) if rt and rt.get("change_pct") is not None else change_pct),
            "mode":"realtime" if rt and rt.get("price") is not None else "daily"},
        "indicators":{"ma5":_f(latest.get("MA5")),"ma20":_f(latest.get("MA20")),
            "ma60":_f(latest.get("MA60")),"rsi":_f(latest.get("RSI")),
            "macd":_f(latest.get("MACD"),4),"signal":_f(latest.get("Signal"),4),
            "hist":_f(latest.get("Hist"),4),
            "bb_upper":_f(latest.get("BB_upper")),"bb_lower":_f(latest.get("BB_lower")),"bb_mid":_f(latest.get("BB_mid"))},
        "volume":vol_info,"score":score_info,"backtest":winrate,
        "conclusion":conclusion,"rsi_alert":rsi_alert,
        "ai_signal":ai,"realtime_quote":rt,"news":news,"chart_data":chart_data,
        "analysis_4d":analysis_4d,
    }

# ══════════════════════════════════════════════════════════════════════════════
# 啟動事件
# ══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    loaded=_load_master_from_file()
    if not loaded or _is_master_stale():
        asyncio.create_task(fetch_stock_master_list())

# ══════════════════════════════════════════════════════════════════════════════
# API 端點
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/watchlist")
async def api_get_watchlist():
    items=_read_watchlist(); return {"watchlist":items,"count":len(items)}

@app.post("/api/watchlist")
async def api_post_watchlist(body:WatchlistUpdateBody):
    items=_normalize_wl(body.watchlist); _write_watchlist(items)
    return {"watchlist":items,"count":len(items),"saved":True}

@app.get("/api/stocks/master")
async def api_stocks_master():
    if not STOCK_MASTER: _load_master_from_file()
    return {"count":len(STOCK_MASTER),"updated_at":_master_updated_at,"stocks":STOCK_MASTER}

@app.get("/api/stocks/search")
async def api_stocks_search(q:str=Query("",min_length=1)):
    if not STOCK_MASTER: _load_master_from_file()
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
    return {"results":results[:20],"query":q}

@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤，請輸入 4~6 位數字")
    macro=await fetch_macro_context()
    result=await _analyze_stock(stock_id,macro,with_4d=True)
    if "error" in result and "price" not in result:
        rt=result.get("realtime_quote"); rt_price=rt.get("price") if rt else None
        degraded_ai={"signal":"WATCH","confidence":0,
            "score_breakdown":{"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
            "risk_model":{"base_score":0,"risk_penalty":0,"macro_penalty":0,"a4_bonus":0,"final_score":0,"risk_level":"HIGH","risk_factors":["資料不足"]},
            "macro_context":{"usd_twd":macro.get("usd_twd"),"dxy":macro.get("dxy"),"note":macro.get("risk_note","")},
            "entry_reason":[],"risk_reason":["歷史資料暫時無法取得"],
            "summary":"歷史資料無法取得，請稍後再試。",
            "entry_price":None,"target_price":None,"stop_loss":None,"holding_days":"不建議持有",
            "risk_reward_ratio":None,"disclaimer":"⚠️ 本工具僅供參考，非投資建議"}
        degraded_4d={"fundamental":{"score":None,"rating":"資料不足","reasons":["資料暫時無法取得"],"risks":[]},"technical":{"score":None,"rating":"資料不足","reasons":[],"risks":[]},"chip":{"score":None,"rating":"資料不足","reasons":["資料暫時無法取得"],"risks":[]},"news":{"score":50,"rating":"中性","sentiment":"中性","bullish_count":0,"bearish_count":0,"neutral_count":0,"top_news":[],"risk_keywords":[],"reasons":[],"risks":[]},"overall":{"overall_score":None,"rating":"資料不足","summary":"資料不足，無法完整評估。","weights":{},"scores":{}}}
        return {"stock_id":stock_id,"stock_name":result.get("stock_name",stock_id),
            "last_date":"N/A","data_source":"none","data_warning":"歷史股價資料暫時無法取得。",
            "price":{"close":rt_price,"daily_close":None,"open":None,"high":None,"low":None,
                "change":rt.get("change") if rt else None,"change_pct":rt.get("change_pct") if rt else None,
                "mode":"realtime" if rt_price else "unavailable"},
            "indicators":{"ma5":None,"ma20":None,"ma60":None,"rsi":None,"macd":None,"signal":None,"hist":None,"bb_upper":None,"bb_lower":None,"bb_mid":None},
            "volume":{"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False},
            "score":{"score":0,"max":5,"reasons":["❌ 無法評估（資料不足）"]},
            "backtest":{"trials":0,"wins":0,"winrate":0},"conclusion":"資料不足 ⚠️","rsi_alert":None,
            "ai_signal":degraded_ai,"realtime_quote":rt,"news":[],"chart_data":[],"analysis_4d":degraded_4d}
    return result

@app.get("/api/realtime/{stock_id}")
async def get_realtime(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    quote=await fetch_realtime_quote(stock_id)
    if not quote: raise HTTPException(404,detail="找不到即時報價")
    return quote

@app.get("/api/scan/ai")
async def ai_scan(min_score:int=Query(80,ge=0,le=100),max_stocks:int=Query(50,ge=5,le=100)):
    t0=time.time(); macro=await fetch_macro_context()
    pool=list(dict.fromkeys(AI_SCAN_POOL))[:max_stocks]
    results,errors=[],[]
    for stock_id in pool:
        try:
            r=await _analyze_stock(stock_id,macro,lookback_days=200,with_4d=False)
            if "error" in r: errors.append({"stock_id":stock_id,"error":r["error"]}); continue
            ai=r.get("ai_signal",{}); p=r.get("price",{})
            if ai.get("confidence",0)<min_score: continue
            results.append({"stock_id":stock_id,"stock_name":r["stock_name"],
                "signal":ai.get("signal","AVOID"),"confidence":ai.get("confidence",0),
                "risk_level":ai.get("risk_model",{}).get("risk_level","—"),
                "price":p.get("close"),"change_pct":p.get("change_pct"),
                "entry_price":ai.get("entry_price"),"target_price":ai.get("target_price"),
                "stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),
                "summary":ai.get("summary","")})
        except Exception as e: errors.append({"stock_id":stock_id,"error":str(e)})
    rank={"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x:(rank.get(x["signal"],0),x["confidence"]),reverse=True)
    return {"scanned":len(pool),"found":len(results),"min_score":min_score,"results":results,
            "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1),"timestamp":datetime.now().isoformat()}

@app.post("/api/alerts/test")
async def test_line():
    _check_line_config()
    result=await send_line_message("✅ 台股監測工具 V8 - LINE 通知測試成功！\n你的 LINE Bot 設定正確，通知功能已啟用。")
    if not result["success"]: raise HTTPException(500,detail=result["message"])
    return result

@app.post("/api/alerts/check")
async def check_alerts(body:WatchlistBody):
    t0=time.time(); line_ok=_line_configured(); results=[]; now=datetime.now(); sent_msgs=[]; errors=[]
    stock_ids=body.watchlist or [item["stock_id"] for item in _read_watchlist()]
    macro=await fetch_macro_context()
    for stock_id in stock_ids:
        if not re.match(r"^\d{4,6}$",stock_id): continue
        try:
            r=await _analyze_stock(stock_id,macro,lookback_days=200,with_4d=False)
            if "error" in r and "price" not in r: errors.append({"stock_id":stock_id,"error":r["error"]}); continue
            ai=r.get("ai_signal",{}); p=r.get("price",{}); rt=r.get("realtime_quote",{})
            stock_name=r.get("stock_name",stock_id)
            cur_price=p.get("close") or (rt.get("price") if rt else None) or 0
            results.append({"stock_id":stock_id,"stock_name":stock_name,
                "signal":ai.get("signal","AVOID"),"confidence":ai.get("confidence",0),
                "summary":ai.get("summary",""),"entry_price":ai.get("entry_price"),
                "target_price":ai.get("target_price"),"stop_loss":ai.get("stop_loss"),
                "risk_reward_ratio":ai.get("risk_reward_ratio"),"risk_level":ai.get("risk_model",{}).get("risk_level","—")})
            rr=ai.get("risk_reward_ratio") or 0
            if line_ok and ai.get("signal")=="BUY" and ai.get("confidence",0)>=75 and rr>=1.5:
                ls=LAST_ALERTS.get(stock_id)
                if ls is None or (now-ls).total_seconds()>=ALERT_COOLDOWN_MINUTES*60:
                    ov=None
                    msg=_build_line_message(stock_id,stock_name,ai,cur_price,ov)
                    res=await send_line_message(msg)
                    if res["success"]: LAST_ALERTS[stock_id]=now; sent_msgs.append(stock_id)
        except Exception as e: errors.append({"stock_id":stock_id,"error":str(e)})
    rank={"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x:(rank.get(x.get("signal",""),0),x.get("confidence",0)),reverse=True)
    return {"checked":len(stock_ids),"alerts":[r for r in results if r.get("signal")=="BUY"],
            "all_results":results,"sent_line":sent_msgs,"line_enabled":line_ok,
            "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1),"timestamp":now.isoformat()}

@app.get("/api/backtest/{stock_id}")
async def run_backtest(stock_id:str,lookback_days:int=400,holding_days:int=5,min_score:int=75):
    if not re.match(r"^\d{4,6}$",stock_id): raise HTTPException(400,detail="股票代號格式錯誤")
    price_df,_=await fetch_price_with_fallback(stock_id,lookback_days)
    api_name=await _fetch_stock_name_from_api(stock_id)
    stock_name=get_stock_name(stock_id,api_name)
    result=advanced_backtest(price_df,holding_days=holding_days,min_score=min_score)
    return {"stock_id":stock_id,"stock_name":stock_name,
            "params":{"lookback_days":lookback_days,"holding_days":holding_days,"min_score":min_score},
            "result":{k:v for k,v in result.items() if k!="trades"},"trades":result["trades"]}

@app.get("/health")
def health():
    return {"status":"ok","version":"8.0.0","time":datetime.now().isoformat(),
            "dev_mode":DEV_MODE,"line_configured":bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
            "line_enabled":ENABLE_LINE_ALERTS,"realtime_source":"TWSE MIS",
            "price_sources":"FinMind → Yahoo Finance → TWSE Official",
            "stock_master_count":len(STOCK_MASTER),"stock_master_updated":_master_updated_at,
            "features":["4D analysis","chip data","fundamental data","bollinger bands","ATR"]}
