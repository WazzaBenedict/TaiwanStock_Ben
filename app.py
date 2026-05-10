"""
台股監測後端 V10.2 Personal Trading System
新增：trade_status / Momentum Breakout / 多時間框架 / 宏觀 API / 市場情緒
保留：V9.2 全部功能（Firestore watchlist / AI 學習 / 四面向 / stock-lite）
"""
import os,re,asyncio,json,time
from datetime import datetime,timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx,numpy as np,pandas as pd
from fastapi import FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app=FastAPI(title="台股監測 API V10.2 Personal",version="10.2.0")
_raw=os.getenv("ALLOWED_ORIGINS","http://localhost:5500,http://127.0.0.1:5500,https://taiwanstock-ben.web.app,https://taiwanstock-ben.firebaseapp.com")
ALLOWED_ORIGINS=[o.strip() for o in _raw.split(",") if o.strip()]
DEV_MODE=os.getenv("DEV_MODE","false").lower()=="true"
if DEV_MODE:ALLOWED_ORIGINS=["*"]
app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS,allow_credentials=not DEV_MODE,allow_methods=["GET","POST","OPTIONS"],allow_headers=["*"])

LINE_CHANNEL_ACCESS_TOKEN=os.getenv("LINE_CHANNEL_ACCESS_TOKEN","")
LINE_TO_ID=os.getenv("LINE_TO_ID","")
ENABLE_LINE_ALERTS=os.getenv("ENABLE_LINE_ALERTS","false").lower()=="true"
LAST_ALERTS:dict[str,datetime]={}
ALERT_COOLDOWN_MINUTES=30

BASE_DIR=Path(__file__).parent
WATCHLIST_FILE=BASE_DIR/"watchlist.json"
STOCK_MASTER_FILE=BASE_DIR/"stock_master.json"
WEIGHTS_FILE=BASE_DIR/"weights.json"
SIGNAL_HISTORY_FILE=BASE_DIR/"signal_history.json"

FINMIND_BASE="https://api.finmindtrade.com/api/v4/data"
TWSE_NAME_URL="https://www.twse.com.tw/rwd/zh/api/basic"
TWSE_MIS_URL="https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
LINE_PUSH_URL="https://api.line.me/v2/bot/message/push"
HTTP_TIMEOUT=10
NEWS_TIMEOUT=5

AI_SCAN_POOL=[
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

STOCK_NAME_MAP:dict[str,str]={
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
# AI 學習系統
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_WEIGHTS={"technical":0.35,"fundamental":0.25,"chip":0.25,"news":0.15,
    "risk":0.10,"macro":0.05,"updated_at":"","version":"10.2.0","last_reason":"預設權重"}
WEIGHT_LIMITS={"technical":(0.20,0.45),"fundamental":(0.10,0.35),"chip":(0.10,0.40),"news":(0.05,0.25)}

def _rjf(path,default):
    try:
        if path.exists():return json.loads(path.read_text(encoding="utf-8"))
    except:pass
    return default

def _wjf(path,data):
    try:path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    except:pass

def _nw(w):
    base=DEFAULT_WEIGHTS.copy()
    base.update({k:float(v) for k,v in (w or {}).items() if k in DEFAULT_WEIGHTS and isinstance(v,(int,float))})
    for k,(lo,hi) in WEIGHT_LIMITS.items():base[k]=max(lo,min(hi,float(base.get(k,DEFAULT_WEIGHTS[k]))))
    tot=sum(base[k] for k in ["technical","fundamental","chip","news"])
    if tot<=0:tot=1.0
    for k in ["technical","fundamental","chip","news"]:base[k]=round(base[k]/tot,4)
    base["risk"]=float(base.get("risk",0.10));base["macro"]=float(base.get("macro",0.05))
    base["updated_at"]=base.get("updated_at") or ""
    return base

def load_ai_weights()->dict:return _nw(_rjf(WEIGHTS_FILE,DEFAULT_WEIGHTS.copy()))
def save_ai_weights(w):w=_nw(w);w["updated_at"]=datetime.now().isoformat();_wjf(WEIGHTS_FILE,w);return w
def load_signal_history()->list:
    d=_rjf(SIGNAL_HISTORY_FILE,{"signals":[]})
    if isinstance(d,list):return d
    return d.get("signals",[]) if isinstance(d,dict) else []
def save_signal_history(h:list):_wjf(SIGNAL_HISTORY_FILE,{"updated_at":datetime.now().isoformat(),"signals":h[-2000:]})

def record_ai_signal(stock_id,stock_name,ai,analysis_4d=None,source="stock"):
    try:
        sig=ai.get("signal");conf=ai.get("confidence",0) or 0
        if sig not in {"BUY","WATCH"} or conf<55:return
        today=datetime.now().strftime("%Y-%m-%d");h=load_signal_history()
        if any(x.get("stock_id")==stock_id and str(x.get("created_at","")).startswith(today) and x.get("signal")==sig for x in h):return
        a=analysis_4d or {}
        h.append({"id":f"{stock_id}_{datetime.now().isoformat(timespec='seconds')}","stock_id":stock_id,"stock_name":stock_name,
            "created_at":datetime.now().isoformat(),"source":source,"signal":sig,"confidence":conf,
            "entry_price":ai.get("entry_price"),"target_price":ai.get("target_price"),
            "stop_loss":ai.get("stop_loss"),"holding_days":ai.get("holding_days"),
            "scores":{k:a.get(k,{}).get("score") for k in ["technical","fundamental","chip","news"]},
            "weights_at_time":{k:load_ai_weights()[k] for k in ["technical","fundamental","chip","news"]},
            "evaluated":False,"result":None})
        save_signal_history(h)
    except:pass

def _lst(h):
    ev=[x for x in h if x.get("evaluated") and x.get("result")]
    l30=ev[-30:];wr30=round(sum(1 for x in l30 if x.get("result",{}).get("success"))/len(l30)*100,1) if l30 else 0
    return {"total":len(h),"evaluated":len(ev),"pending":len(h)-len(ev),"winrate_30":wr30}

async def evaluate_signal_history()->dict:
    h=load_signal_history();upd=0;errs=[];now=datetime.now()
    for item in h:
        if item.get("evaluated"):continue
        try:created=datetime.fromisoformat(str(item.get("created_at","")).replace("Z",""))
        except:continue
        if (now-created).days<5:continue
        sid=item.get("stock_id");entry=item.get("entry_price") or 0
        if not sid or not entry:continue
        try:
            df,_=await fetch_price_with_fallback(sid,lookback_days=40)
            if df.empty:continue
            df=df[df["日期"]>=pd.to_datetime(created.date())].head(10)
            if df.empty:continue
            closes=pd.to_numeric(df["收盤價"],errors="coerce").dropna()
            highs=pd.to_numeric(df.get("最高價",df["收盤價"]),errors="coerce").dropna()
            lows=pd.to_numeric(df.get("最低價",df["收盤價"]),errors="coerce").dropna()
            if closes.empty:continue
            maxr=round((highs.max()-entry)/entry*100,2) if not highs.empty else 0
            minr=round((lows.min()-entry)/entry*100,2) if not lows.empty else 0
            finr=round((closes.iloc[-1]-entry)/entry*100,2)
            tgt=item.get("target_price");stp=item.get("stop_loss")
            ht=bool(tgt and not highs.empty and highs.max()>=tgt)
            hs=bool(stp and not lows.empty and lows.min()<=stp)
            ok=(ht or finr>2) and not hs if item.get("signal")=="BUY" else finr>0
            item["evaluated"]=True;item["evaluated_at"]=now.isoformat()
            item["result"]={"max_return_pct":maxr,"min_return_pct":minr,"final_return_pct":finr,
                            "hit_target":ht,"hit_stop":hs,"success":ok}
            upd+=1
        except Exception as e:errs.append({"stock_id":sid,"error":str(e)})
    save_signal_history(h)
    return {"updated":upd,"errors":errs[:20],"stats":_lst(h)}

def retrain_ai_weights()->dict:
    h=load_signal_history();ev=[x for x in h if x.get("evaluated") and x.get("result")]
    if len(ev)<30:return{"updated":False,"message":"樣本不足，至少需要 30 筆已評估訊號","sample_count":len(ev),"weights":load_ai_weights()}
    ok=[x for x in ev if x.get("result",{}).get("success")];fail=[x for x in ev if not x.get("result",{}).get("success")]
    if not ok or not fail:return{"updated":False,"message":"成功或失敗樣本不足","sample_count":len(ev),"weights":load_ai_weights()}
    w=load_ai_weights();old={k:w[k] for k in["technical","fundamental","chip","news"]}
    dl={k:0.0 for k in old};rs=[]
    for k in old:
        sv=[x.get("scores",{}).get(k) for x in ok if x.get("scores",{}).get(k) is not None]
        fv=[x.get("scores",{}).get(k) for x in fail if x.get("scores",{}).get(k) is not None]
        if len(sv)<5 or len(fv)<5:continue
        diff=sum(sv)/len(sv)-sum(fv)/len(fv)
        if diff>=5:dl[k]=0.02;rs.append(f"{k} 成功高出 {diff:.1f}，+2%")
        elif diff<=-5:dl[k]=-0.02;rs.append(f"{k} 失敗偏高 {abs(diff):.1f}，-2%")
    if not any(dl.values()):return{"updated":False,"message":"沒有明顯調整訊號","sample_count":len(ev),"weights":w}
    for k,d in dl.items():
        lo,hi=WEIGHT_LIMITS[k];w[k]=max(lo,min(hi,w[k]+d))
    w["last_reason"]="；".join(rs);w=save_ai_weights(w)
    return{"updated":True,"sample_count":len(ev),"old_weights":old,"new_weights":{k:w[k] for k in old},"deltas":dl,"reasons":rs,"weights":w}

# ══════════════════════════════════════════════════════════════════════════════
# 股票主檔
# ══════════════════════════════════════════════════════════════════════════════
STOCK_MASTER:dict[str,dict]={};_mua="";_ml=False
def _lfm()->bool:
    global STOCK_MASTER,_mua
    try:
        if STOCK_MASTER_FILE.exists():
            d=json.loads(STOCK_MASTER_FILE.read_text(encoding="utf-8"))
            STOCK_MASTER=d.get("stocks",{});_mua=d.get("updated_at","");return bool(STOCK_MASTER)
    except:pass
    return False
def _smf():
    try:STOCK_MASTER_FILE.write_text(json.dumps({"updated_at":datetime.now().isoformat(),"stocks":STOCK_MASTER},ensure_ascii=False,indent=2),encoding="utf-8")
    except:pass
def _ims()->bool:
    if not _mua:return True
    try:return(datetime.now()-datetime.fromisoformat(_mua)).total_seconds()>86400
    except:return True
async def fetch_stock_master_list():
    global STOCK_MASTER,_mua,_ml
    if _ml:return
    _ml=True;master:dict[str,dict]={}
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=True) as cl:
            for url,mkt in [("https://www.twse.com.tw/rwd/zh/api/basic?type=MS&response=json","tse"),
                            ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L","tse")]:
                if master:break
                try:
                    r=await cl.get(url)
                    if r.status_code!=200:continue
                    rows=r.json() if "openapi" in url else r.json().get("data",[])
                    for row in rows:
                        if isinstance(row,list) and len(row)>=2:sid,name=str(row[0]).strip(),str(row[1]).strip()
                        elif isinstance(row,dict):
                            sid=str(row.get("公司代號","") or row.get("有價證券代號","")).strip()
                            name=str(row.get("公司簡稱","") or row.get("有價證券名稱","")).strip()
                        else:continue
                        if re.match(r"^\d{4,6}$",sid) and name:master[sid]={"name":name,"market":"tse"}
                except:pass
            for url in["https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_information",
                       "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]:
                try:
                    r=await cl.get(url)
                    if r.status_code!=200:continue
                    for row in r.json():
                        sid=str(row.get("SecuritiesCompanyCode","") or row.get("公司代號","")).strip()
                        name=str(row.get("CompanyName","") or row.get("公司簡稱","")).strip()
                        if re.match(r"^\d{4,6}$",sid) and name and sid not in master:master[sid]={"name":name,"market":"otc"}
                except:pass
    except:pass
    for sid,name in STOCK_NAME_MAP.items():
        if sid not in master:master[sid]={"name":name,"market":"tse"}
    if master:STOCK_MASTER.update(master);_mua=datetime.now().isoformat();_smf()
    _ml=False
def get_stock_name(sid:str,api_name:str|None=None)->str:
    c=str(api_name).strip() if api_name else ""
    if c and c!=sid:return c
    if sid in STOCK_MASTER:return STOCK_MASTER[sid]["name"]
    return STOCK_NAME_MAP.get(sid,sid)

# ══════════════════════════════════════════════════════════════════════════════
# 自選股
# ══════════════════════════════════════════════════════════════════════════════
def _nwl(raw:list)->list[dict]:
    result,seen=[],set()
    for item in raw:
        if isinstance(item,str):
            sid=item.strip()
            if sid and sid not in seen:seen.add(sid);result.append({"stock_id":sid,"stock_name":get_stock_name(sid)})
        elif isinstance(item,dict):
            sid=str(item.get("stock_id","")).strip()
            if sid and sid not in seen:
                seen.add(sid);result.append({"stock_id":sid,"stock_name":item.get("stock_name") or get_stock_name(sid)})
    return result
def _rwl()->list[dict]:
    try:
        if WATCHLIST_FILE.exists():return _nwl(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("watchlist",[]))
    except:pass
    return []
def _wwl(items:list[dict]):
    try:WATCHLIST_FILE.write_text(json.dumps({"watchlist":items},ensure_ascii=False,indent=2),encoding="utf-8")
    except:pass
class WatchlistUpdateBody(BaseModel):watchlist:list
class WatchlistBody(BaseModel):watchlist:list[str]

BULLISH_KW=["獲利","營收成長","突破","漲停","利多","買超","法人買","創新高","增資","配息","配股",
    "股利","超預期","優於預期","轉盈","擴廠","新訂單","拿下訂單","合作","策略聯盟","上調目標價","買進評等"]
BEARISH_KW=["虧損","營收衰退","跌停","利空","賣超","法人賣","創新低","減資","下調目標價","賣出評等",
    "警示","財務危機","停工","違約","下修","低於預期","遭罰","裁員","關廠"]
RISK_KW=["下修","虧損","違約","裁員","調查","警示","停工","財務危機","關廠","遭罰"]

def score_sentiment(text:str)->str:
    b=sum(1 for kw in BULLISH_KW if kw in text);e=sum(1 for kw in BEARISH_KW if kw in text)
    return "利多" if b>e else "利空" if e>b else "中性"

# ══════════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════════
def calc_rsi(s:pd.Series,p=14)->pd.Series:
    d=s.diff();g=d.clip(lower=0);l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/p,min_periods=p).mean();al=l.ewm(alpha=1/p,min_periods=p).mean()
    return 100-(100/(1+ag/al.replace(0,np.nan)))
def calc_macd(s:pd.Series,fast=12,slow=26,signal=9):
    ef=s.ewm(span=fast,adjust=False).mean();es=s.ewm(span=slow,adjust=False).mean()
    m=ef-es;sig=m.ewm(span=signal,adjust=False).mean();return m,sig,m-sig
def _f(v,d=2):return round(float(v),d) if pd.notna(v) else None
def _num(v):
    if v is None:return None
    if isinstance(v,(int,float)):return float(v)
    s=str(v).strip().replace(",","")
    if not s or s in{"-","--","－","null","None"}:return None
    try:return float(s)
    except:return None
def _in(v):n=_num(v);return int(n) if n is not None else 0
def _qt(d,t):
    d=(d or "").strip();t=(t or "").strip()
    if len(d)==8 and d.isdigit():return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t}".strip()
    return f"{d} {t}".strip() or None
def _mdf():return pd.DataFrame(columns=["日期","成交股數","開盤價","最高價","最低價","收盤價"])

# ══════════════════════════════════════════════════════════════════════════════
# 即時報價
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_realtime_quote(stock_id:str)->dict|None:
    ts=int(datetime.now().timestamp()*1000)
    hdr={"User-Agent":"Mozilla/5.0","Referer":"https://mis.twse.com.tw/stock/index.jsp"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,headers=hdr,follow_redirects=True) as cl:
            for mkt in("tse","otc"):
                try:
                    r=await cl.get(TWSE_MIS_URL,params={"ex_ch":f"{mkt}_{stock_id}.tw","json":"1","delay":"0","_":str(ts)})
                    arr=r.json().get("msgArray") or []
                    if not arr:continue
                    q=arr[0];price=_num(q.get("z")) or _num(q.get("a")) or _num(q.get("b"));prev=_num(q.get("y"))
                    chg=round(price-prev,2) if price and prev else None
                    cp=round(chg/prev*100,2) if chg and prev else None
                    return{"stock_id":str(q.get("c") or stock_id),"stock_name":get_stock_name(stock_id,q.get("n")),
                           "market":mkt,"realtime":price is not None,"price":price,
                           "open":_num(q.get("o")),"high":_num(q.get("h")),"low":_num(q.get("l")),
                           "previous_close":prev,"change":chg,"change_pct":cp,
                           "volume":_in(q.get("v")),"quote_time":_qt(q.get("d"),q.get("t")),
                           "source":"TWSE MIS","note":"盤中即時或延遲報價"}
                except:continue
    except:pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
# 歷史股價
# ══════════════════════════════════════════════════════════════════════════════
def _prdf(rows):
    raw=pd.DataFrame(rows);df=pd.DataFrame()
    df["日期"]=pd.to_datetime(raw.get("date"),errors="coerce")
    df["成交股數"]=pd.to_numeric(raw.get("Trading_Volume"),errors="coerce")
    df["開盤價"]=pd.to_numeric(raw.get("open"),errors="coerce")
    df["最高價"]=pd.to_numeric(raw.get("max"),errors="coerce")
    df["最低價"]=pd.to_numeric(raw.get("min"),errors="coerce")
    df["收盤價"]=pd.to_numeric(raw.get("close"),errors="coerce")
    return df.dropna(subset=["日期","收盤價"]).sort_values("日期").reset_index(drop=True)

async def _ffy(sid,days,cl):
    p2=int(datetime.now().timestamp());p1=int((datetime.now()-timedelta(days=days)).timestamp())
    for sfx in(".TW",".TWO"):
        try:
            r=await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?period1={p1}&period2={p2}&interval=1d&events=history",
                headers={"User-Agent":"Mozilla/5.0"},timeout=HTTP_TIMEOUT,follow_redirects=True)
            if r.status_code!=200:continue
            res=r.json().get("chart",{}).get("result")
            if not res:continue
            res=res[0];ts_a=res.get("timestamp",[])
            q=res.get("indicators",{}).get("quote",[{}])[0]
            o,h,l,c,v=q.get("open",[]),q.get("high",[]),q.get("low",[]),q.get("close",[]),q.get("volume",[])
            if not ts_a or not c:continue
            recs=[{"日期":pd.to_datetime(ts,unit="s",utc=True).tz_convert("Asia/Taipei").date(),
                   "成交股數":(v[i] if i<len(v) else 0) or 0,
                   "開盤價":o[i] if i<len(o) else c[i],"最高價":h[i] if i<len(h) else c[i],
                   "最低價":l[i] if i<len(l) else c[i],"收盤價":c[i]}
                  for i,ts in enumerate(ts_a) if i<len(c) and c[i] is not None]
            if not recs:continue
            df=pd.DataFrame(recs);df["日期"]=pd.to_datetime(df["日期"]);return df.sort_values("日期").reset_index(drop=True)
        except:continue
    return None

async def _fft(sid,cl):
    frames=[];today=datetime.today()
    for dm in range(3):
        dt=today-timedelta(days=30*dm);ym=dt.strftime("%Y%m")
        try:
            r=await cl.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}01&stockNo={sid}&response=json",timeout=HTTP_TIMEOUT)
            rows=r.json().get("data",[])
            if not rows:continue
            recs=[]
            for row in rows:
                try:
                    pts=row[0].replace(",","").split("/");yr=int(pts[0])+1911
                    dobj=pd.to_datetime(f"{yr}/{pts[1]}/{pts[2]}")
                    vol=int(str(row[1]).replace(",","")) if row[1] else 0
                    def _p(x):return float(str(x).replace(",","")) if x and x!="--" else None
                    op,hp,lp,cp=_p(row[3]),_p(row[4]),_p(row[5]),_p(row[6])
                    if cp is None:continue
                    recs.append({"日期":dobj,"成交股數":vol*1000,"開盤價":op or cp,"最高價":hp or cp,"最低價":lp or cp,"收盤價":cp})
                except:continue
            if recs:frames.append(pd.DataFrame(recs))
        except:continue
    if not frames:return None
    df=pd.concat(frames,ignore_index=True).drop_duplicates("日期").sort_values("日期").reset_index(drop=True)
    return df if not df.empty else None

async def _fff(sid,days,cl):
    ed=datetime.today();sd=ed-timedelta(days=days)
    try:
        r=await cl.get(FINMIND_BASE,params={"dataset":"TaiwanStockPrice","data_id":sid,
            "start_date":sd.strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")},timeout=HTTP_TIMEOUT)
        if r.status_code in(402,403,429):return None
        r.raise_for_status();rows=r.json().get("data",[])
        if not rows:return None
        df=_prdf(rows);return df if not df.empty else None
    except:return None

async def fetch_price_with_fallback(sid:str,lookback_days:int=400)->tuple[pd.DataFrame,str]:
    try:
        async with httpx.AsyncClient() as cl:
            df=await _ffy(sid,lookback_days,cl)
            if df is not None and not df.empty:return df,"Yahoo Finance"
            df=await _fft(sid,cl)
            if df is not None and not df.empty:return df,"TWSE Official"
            df=await _fff(sid,lookback_days,cl)
            if df is not None and not df.empty:return df,"FinMind"
    except:pass
    return _mdf(),"none"

async def _fname(sid:str)->str:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
            r=await cl.get(TWSE_NAME_URL,params={"stockNo":sid});data=r.json()
            if isinstance(data,dict):
                for key in["data","msgArray"]:
                    arr=data.get(key)
                    if arr and isinstance(arr,list) and arr:
                        row=arr[0]
                        if isinstance(row,list) and len(row)>1:return row[1]
                        if isinstance(row,dict):return row.get("公司名稱",row.get("Name",""))
    except:pass
    return ""

# ══════════════════════════════════════════════════════════════════════════════
# 宏觀資料（V10 新增 NASDAQ/SOX/US10Y）
# ══════════════════════════════════════════════════════════════════════════════
_macro_cache:dict={};_macro_ts:float=0.0;MACRO_TTL=300

async def fetch_macro_context()->dict:
    global _macro_cache,_macro_ts
    if _macro_cache and(time.time()-_macro_ts)<MACRO_TTL:return _macro_cache
    result={"usd_twd":None,"dxy":None,"nasdaq_futures":None,"sox":None,"us10y":None,"risk_note":"","macro_adj":0}
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            for sym,key in[("TWD=X","usd_twd"),("DX-Y.NYB","dxy"),("NQ=F","nasdaq_futures"),("^SOX","sox"),("^TNX","us10y")]:
                try:
                    r=await cl.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d",
                        headers={"User-Agent":"Mozilla/5.0"},follow_redirects=True)
                    if r.status_code==200:
                        res=r.json().get("chart",{}).get("result")
                        if res:
                            closes=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
                            valid=[c for c in closes if c is not None]
                            if valid:result[key]=round(valid[-1],3 if key=="usd_twd" else(2 if key in("dxy","us10y") else 0))
                except:pass
    except:pass
    notes=[];adj=0
    usd=result["usd_twd"];dxy=result["dxy"];us10y=result["us10y"]
    if usd and usd>32.5:adj-=5;notes.append(f"USD/TWD {usd}，匯率走強（-5）")
    elif usd and usd<31.5:adj+=5;notes.append(f"USD/TWD {usd}，匯率走弱（+5）")
    if dxy and dxy>104:adj-=5;notes.append(f"DXY {dxy}，美元強勢（-5）")
    elif dxy and dxy<100:adj+=5;notes.append(f"DXY {dxy}，美元弱勢（+5）")
    if us10y and us10y>4.5:adj-=3;notes.append(f"美債10Y {us10y}%，殖利率偏高（-3）")
    result["macro_adj"]=adj
    result["risk_note"]="，".join(notes) if notes else("宏觀資料暫時無法取得" if not usd and not dxy else "宏觀環境無明顯壓力")
    _macro_cache=result;_macro_ts=time.time();return result

# ══════════════════════════════════════════════════════════════════════════════
# 新聞
# ══════════════════════════════════════════════════════════════════════════════
async def fetch_news(stock_id:str,stock_name:str="")->list:
    name=stock_name if stock_name and stock_name!=stock_id else ""
    queries=[]
    if name:queries.append(f"{name} {stock_id}");queries.append(f"{name} 台股")
    queries.append(f"{stock_id} 台股")
    if name:queries.append(name)
    items=[]
    try:
        async with httpx.AsyncClient(timeout=NEWS_TIMEOUT,follow_redirects=True) as cl:
            for q in queries:
                if items:break
                try:
                    r=await cl.get(f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-TW")
                    if r.status_code!=200:continue
                    root=ET.fromstring(r.content)
                    for el in root.findall(".//item")[:10]:
                        title=el.findtext("title","").strip()
                        if not title:continue
                        items.append({"title":title,"link":el.findtext("link",""),
                                      "pub_date":el.findtext("pubDate",""),"sentiment":score_sentiment(title)})
                except:continue
    except:pass
    seen,unique=set(),[]
    for n in items:
        if n["title"] not in seen:seen.add(n["title"]);unique.append(n)
    return unique[:10]

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標
# ══════════════════════════════════════════════════════════════════════════════
def compute_indicators(df:pd.DataFrame)->pd.DataFrame:
    if df.empty:return df
    c=df["收盤價"]
    df["MA5"]=c.rolling(5).mean();df["MA20"]=c.rolling(20).mean();df["MA60"]=c.rolling(60).mean()
    df["RSI"]=calc_rsi(c,14);df["MACD"],df["Signal"],df["Hist"]=calc_macd(c)
    df["BB_mid"]=c.rolling(20).mean();bbs=c.rolling(20).std()
    df["BB_upper"]=df["BB_mid"]+2*bbs;df["BB_lower"]=df["BB_mid"]-2*bbs
    hi=df.get("最高價",c);lo=df.get("最低價",c)
    if hi is not None and lo is not None:
        pc=c.shift(1);tr=pd.concat([hi-lo,(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1)
        df["ATR"]=tr.rolling(14).mean()
    return df

def technical_score(row:pd.Series)->dict:
    score,reasons=0,[]
    if pd.notna(row.get("MA20")) and row["收盤價"]>row["MA20"]:score+=1;reasons.append("✅ 收盤價 > MA20")
    else:reasons.append("❌ 收盤價 < MA20")
    if pd.notna(row.get("MA5")) and pd.notna(row.get("MA20")) and row["MA5"]>row["MA20"]:score+=1;reasons.append("✅ MA5 > MA20")
    else:reasons.append("❌ MA5 < MA20")
    if pd.notna(row.get("RSI")):
        if 40<=row["RSI"]<=70:score+=1;reasons.append(f"✅ RSI={row['RSI']:.1f}")
        elif row["RSI"]>70:reasons.append(f"⚠️ RSI={row['RSI']:.1f}（過熱）")
        else:reasons.append(f"❌ RSI={row['RSI']:.1f}（偏弱）")
    if pd.notna(row.get("MACD")) and pd.notna(row.get("Signal")) and row["MACD"]>row["Signal"]:score+=1;reasons.append("✅ MACD > Signal")
    else:reasons.append("❌ MACD < Signal")
    if pd.notna(row.get("MA20")) and pd.notna(row.get("MA60")) and row["MA20"]>row["MA60"]:score+=1;reasons.append("✅ MA20 > MA60")
    else:reasons.append("❌ MA20 < MA60")
    return{"score":score,"max":5,"reasons":reasons}

def backtest_winrate(df:pd.DataFrame)->dict:
    if df.empty:return{"trials":0,"wins":0,"winrate":0}
    req=[c for c in["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df2=df.dropna(subset=req) if req else df
    if len(df2)<10:return{"trials":0,"wins":0,"winrate":0}
    cond=((df2["收盤價"]>df2["MA20"])&(df2["MA5"]>df2["MA20"])&(df2["RSI"]>50)&(df2["MACD"]>df2["Signal"]))
    wins=trials=0
    for idx in df2[cond].index:
        pos=df2.index.get_loc(idx)
        if pos+5<len(df2):
            trials+=1
            if df2.iloc[pos+5]["收盤價"]>df2.iloc[pos]["收盤價"]:wins+=1
    return{"trials":trials,"wins":wins,"winrate":round(wins/trials*100,1) if trials else 0}

def volume_analysis(df:pd.DataFrame)->dict:
    if df.empty:return{"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False}
    avg=df.tail(20)["成交股數"].mean();lat=df.iloc[-1]["成交股數"]
    ratio=round(float(lat/avg),2) if avg and avg>0 else 1.0
    return{"latest_volume":int(lat) if pd.notna(lat) else 0,"avg_volume_20d":int(avg) if pd.notna(avg) else 0,"ratio":ratio,"alert":bool(ratio>=1.5)}

# ══════════════════════════════════════════════════════════════════════════════
# 四面向分析
# ══════════════════════════════════════════════════════════════════════════════
def _sr(s)->str:
    if s is None:return "資料不足"
    if s>=70:return "強"
    if s>=50:return "中"
    return "弱"
def _or(s)->str:
    if s>=80:return "強勢"
    if s>=65:return "偏多"
    if s>=50:return "觀望"
    return "偏弱"

def analyze_technical_4d(df:pd.DataFrame,latest:pd.Series,cp:float)->dict:
    reasons,risks=[],[]; score=0
    def _g(col):return float(latest[col]) if pd.notna(latest.get(col)) else None
    ma5=_g("MA5");ma20=_g("MA20");ma60=_g("MA60");rsi=_g("RSI");macd=_g("MACD");sig=_g("Signal");hist=_g("Hist")
    bbu=_g("BB_upper");bbl=_g("BB_lower");bbm=_g("BB_mid");atr=_g("ATR")
    if ma20 and cp>ma20:score+=15;reasons.append(f"收盤價站上 MA20 {ma20:.0f}")
    elif ma20:risks.append(f"收盤價低於 MA20 {ma20:.0f}")
    if ma5 and ma20 and ma5>ma20:score+=15;reasons.append("MA5 > MA20 短線多頭")
    if ma20 and ma60 and ma20>ma60:score+=10;reasons.append("MA20 > MA60 長線向上")
    elif ma60:risks.append("MA20 < MA60 長線偏弱")
    if rsi:
        if 45<=rsi<=68:score+=20;reasons.append(f"RSI {rsi:.1f} 健康區間")
        elif rsi>75:risks.append(f"RSI {rsi:.1f} 過熱")
        elif rsi<35:score+=5;risks.append(f"RSI {rsi:.1f} 偏弱")
        else:score+=8
    if macd and sig and macd>sig:score+=15;reasons.append("MACD 金叉")
    elif macd and sig:risks.append("MACD 死叉")
    if hist and hist>0:score+=5;reasons.append("MACD Histogram 正值")
    if bbu and bbl and bbm:
        bw=round((bbu-bbl)/bbm*100,1)
        if cp>bbm:score+=10;reasons.append(f"股價在布林中軌上方（BB {bw}%）")
        else:risks.append(f"股價在布林中軌下方（BB {bw}%）")
        if cp<bbl:score+=10;reasons.append("觸及布林下軌，可能反彈")
        if cp>bbu*0.99:risks.append("接近布林上軌，追高風險")
    score=max(0,min(100,score))
    bull=sum(1 for x in[(ma5 and ma20 and ma5>ma20),(ma20 and ma60 and ma20>ma60),(macd and sig and macd>sig)] if x)
    trend="多頭" if bull>=3 else("空頭" if bull==0 else "盤整")
    rec=df.tail(20)
    support=round(float(rec["最低價"].min()),2) if "最低價" in rec.columns and not rec.empty else None
    resistance=round(float(rec["最高價"].max()),2) if "最高價" in rec.columns and not rec.empty else None
    return{"score":score,"rating":_sr(score),"trend":trend,"support":support,"resistance":resistance,
           "atr":round(atr,2) if atr else None,"bb_upper":_f(bbu),"bb_lower":_f(bbl),"bb_mid":_f(bbm),
           "rsi":_f(rsi),"macd":_f(macd,4),"reasons":reasons[:4],"risks":risks[:3]}

async def fetch_chip_data(sid:str)->dict:
    today=datetime.today()
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,follow_redirects=True) as cl:
                r=await cl.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dt}&selectType=ALLBUT0999&response=json")
                if r.status_code!=200:continue
                rows=r.json().get("data",[])
                if not rows:continue
                row=next((x for x in rows if str(x[0]).strip()==sid),None)
                if not row:continue
                def _p(x):
                    try:return int(str(x).replace(",","").replace("─","0"))
                    except:return 0
                f=_p(row[4]) if len(row)>4 else 0;t=_p(row[10]) if len(row)>10 else 0;d=_p(row[14]) if len(row)>14 else 0
                return{"date":dt,"foreign_net_buy":f,"investment_trust_net_buy":t,"dealer_net_buy":d,"three_major_total":f+t+d,"data_available":True}
        except:continue
    return{"date":None,"foreign_net_buy":None,"investment_trust_net_buy":None,"dealer_net_buy":None,"three_major_total":None,"data_available":False}

async def fetch_margin_data(sid:str)->dict:
    today=datetime.today()
    for delta in range(7):
        dt=(today-timedelta(days=delta)).strftime("%Y%m%d")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,follow_redirects=True) as cl:
                r=await cl.get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={dt}&selectType=ALL&response=json")
                if r.status_code!=200:continue
                rows=r.json().get("data",[])
                row=next((x for x in rows if str(x[0]).strip()==sid),None)
                if not row or len(row)<14:continue
                def _p(x):
                    try:return int(str(x).replace(",",""))
                    except:return 0
                return{"date":dt,"margin_balance":_p(row[3]),"margin_change":_p(row[4]),"short_balance":_p(row[9]),"short_change":_p(row[10]),"data_available":True}
        except:continue
    return{"date":None,"margin_balance":None,"margin_change":None,"short_balance":None,"short_change":None,"data_available":False}

def analyze_chip_4d(chip:dict,margin:dict)->dict:
    reasons,risks=[],[];score=50
    if not chip.get("data_available") and not margin.get("data_available"):
        return{"score":None,"rating":"資料不足","foreign_net_buy":None,"investment_trust_net_buy":None,
               "dealer_net_buy":None,"three_major_total":None,"margin_change":None,"short_change":None,
               "reasons":["籌碼資料暫時無法取得"],"risks":[]}
    fo=chip.get("foreign_net_buy") or 0;tr=chip.get("investment_trust_net_buy") or 0
    dl=chip.get("dealer_net_buy") or 0;tot=chip.get("three_major_total") or 0
    if chip.get("data_available"):
        if fo>0:score+=15;reasons.append(f"外資買超 {fo:,} 張")
        elif fo<0:score-=15;risks.append(f"外資賣超 {abs(fo):,} 張")
        if tr>0:score+=10;reasons.append(f"投信買超 {tr:,} 張")
        elif tr<0:score-=5;risks.append(f"投信賣超 {abs(tr):,} 張")
        if dl>0:score+=5;reasons.append(f"自營商買超 {dl:,} 張")
        if tot>0:reasons.append(f"三大法人合計買超 {tot:,} 張")
        elif tot<0:risks.append(f"三大法人合計賣超 {abs(tot):,} 張")
    mc=margin.get("margin_change") or 0;sc=margin.get("short_change") or 0
    if margin.get("data_available"):
        if mc<0:score+=5;reasons.append(f"融資減少 {abs(mc):,} 張")
        elif mc>0:score-=5;risks.append(f"融資增加 {mc:,} 張")
        if sc>0:score+=5;reasons.append(f"融券增加 {sc:,} 張")
    score=max(0,min(100,score))
    return{"score":score,"rating":_sr(score),"foreign_net_buy":chip.get("foreign_net_buy"),
           "investment_trust_net_buy":chip.get("investment_trust_net_buy"),"dealer_net_buy":chip.get("dealer_net_buy"),
           "three_major_total":chip.get("three_major_total"),"margin_change":margin.get("margin_change"),
           "short_change":margin.get("short_change"),"reasons":reasons[:4],"risks":risks[:3]}

async def fetch_fundamental_data(sid:str)->dict:
    result={"revenue_yoy":None,"revenue_mom":None,"revenue_trend":None,"eps":None,"roe":None,
            "gross_margin":None,"operating_margin":None,"per":None,"pbr":None,"data_available":False}
    ed=datetime.today();sd=ed-timedelta(days=365)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cl:
            try:
                r=await cl.get(FINMIND_BASE,params={"dataset":"TaiwanStockMonthRevenue","data_id":sid,
                    "start_date":(ed-timedelta(days=120)).strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                if r.status_code not in(402,403,429) and r.status_code==200:
                    rows=r.json().get("data",[])
                    if len(rows)>=2:
                        rows=sorted(rows,key=lambda x:x.get("date",""))
                        lr=_num(rows[-1].get("revenue"));pr=_num(rows[-2].get("revenue"))
                        yoy=_num(rows[-1].get("year_growth_rate") or rows[-1].get("yoy"))
                        if lr and pr:result["revenue_mom"]=round((lr-pr)/pr*100,1)
                        result["revenue_yoy"]=yoy;result["revenue_trend"]=[_num(r.get("revenue")) for r in rows[-3:]]
                        result["data_available"]=True
            except:pass
            for ds,key in[("TaiwanStockPER","per"),("TaiwanStockPBR","pbr")]:
                try:
                    r=await cl.get(FINMIND_BASE,params={"dataset":ds,"data_id":sid,
                        "start_date":(ed-timedelta(days=30)).strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                    if r.status_code==200:
                        rows=r.json().get("data",[])
                        if rows:result[key]=_num(rows[-1].get("PER" if ds=="TaiwanStockPER" else "PBR"));result["data_available"]=True
                except:pass
            try:
                r=await cl.get(FINMIND_BASE,params={"dataset":"TaiwanStockFinancialStatements","data_id":sid,
                    "start_date":sd.strftime("%Y-%m-%d"),"end_date":ed.strftime("%Y-%m-%d")})
                if r.status_code==200:
                    rows=r.json().get("data",[])
                    for tag,key in[("EPS","eps"),("ROE","roe"),("毛利率","gross_margin"),("營業利益率","operating_margin")]:
                        hits=[x for x in rows if tag in str(x.get("type",""))]
                        if hits:result[key]=_num(hits[-1].get("value"));result["data_available"]=True
            except:pass
    except:pass
    return result

def analyze_fundamental_4d(fund:dict)->dict:
    reasons,risks=[],[];score=50
    if not fund.get("data_available"):
        return{"score":None,"rating":"資料不足","revenue_yoy":None,"revenue_mom":None,"eps":None,"roe":None,
               "gross_margin":None,"operating_margin":None,"per":None,"pbr":None,
               "reasons":["基本面資料暫時無法取得（FinMind 配額）"],"risks":[]}
    yoy=fund.get("revenue_yoy")
    if yoy is not None:
        if yoy>=20:score+=20;reasons.append(f"月營收年成長 {yoy:.1f}%（強勁）")
        elif yoy>=5:score+=10;reasons.append(f"月營收年成長 {yoy:.1f}%")
        elif yoy<0:score-=10;risks.append(f"月營收年衰退 {yoy:.1f}%")
    roe=fund.get("roe")
    if roe is not None:
        if roe>=15:score+=15;reasons.append(f"ROE {roe:.1f}%（優質）")
        elif roe>=8:score+=8;reasons.append(f"ROE {roe:.1f}%（尚可）")
        elif roe<0:score-=10;risks.append(f"ROE {roe:.1f}%（虧損）")
    gm=fund.get("gross_margin")
    if gm is not None:
        if gm>=30:score+=10;reasons.append(f"毛利率 {gm:.1f}%（高護城河）")
        elif gm<10:risks.append(f"毛利率偏低 {gm:.1f}%")
    eps=fund.get("eps")
    if eps is not None:
        if eps>0:score+=5;reasons.append(f"EPS {eps:.2f}元")
        elif eps<0:score-=10;risks.append(f"EPS {eps:.2f}元（虧損）")
    per=fund.get("per")
    if per is not None:
        if 10<=per<=25:score+=5;reasons.append(f"本益比 {per:.1f}x（合理）")
        elif per>40:risks.append(f"本益比 {per:.1f}x（偏高）")
    score=max(0,min(100,score))
    return{"score":score,"rating":_sr(score),"revenue_yoy":fund.get("revenue_yoy"),"revenue_mom":fund.get("revenue_mom"),
           "eps":fund.get("eps"),"roe":fund.get("roe"),"gross_margin":fund.get("gross_margin"),
           "operating_margin":fund.get("operating_margin"),"per":fund.get("per"),"pbr":fund.get("pbr"),
           "revenue_trend":fund.get("revenue_trend"),"reasons":reasons[:4],"risks":risks[:3]}

def analyze_news_4d(news:list)->dict:
    if not news:
        return{"score":50,"rating":"中","sentiment":"中性","bullish_count":0,"bearish_count":0,"neutral_count":0,
               "top_news":[],"risk_keywords":[],"reasons":["暫時無法取得即時新聞，先以中性處理"],"risks":[]}
    bull=sum(1 for n in news if n.get("sentiment")=="利多");bear=sum(1 for n in news if n.get("sentiment")=="利空")
    neu=sum(1 for n in news if n.get("sentiment")=="中性")
    rk=list(dict.fromkeys([kw for kw in RISK_KW for n in news if kw in n.get("title","")]))[:5]
    score=50;reasons,risks=[],[]
    if bull>bear:score+=min(30,bull*8);reasons.append(f"利多新聞 {bull} 則")
    elif bear>bull:score-=min(30,bear*8);risks.append(f"利空新聞 {bear} 則")
    else:reasons.append(f"新聞情緒中性（利多{bull}/利空{bear}/中性{neu}）")
    if rk:score-=min(20,len(rk)*5);risks.append(f"偵測到風險字詞：{', '.join(rk[:3])}")
    score=max(0,min(100,score));sentiment="利多" if bull>bear else("利空" if bear>bull else "中性")
    top_news=[{"title":n["title"][:60],"sentiment":n["sentiment"],"link":n.get("link","")} for n in news[:5]]
    return{"score":score,"rating":_sr(score),"sentiment":sentiment,"bullish_count":bull,"bearish_count":bear,
           "neutral_count":neu,"top_news":top_news,"risk_keywords":rk,"reasons":reasons[:3],"risks":risks[:3]}

def compute_overall_4d(fu,te,ch,nw)->dict:
    w=load_ai_weights()
    weights={"fundamental":w["fundamental"],"technical":w["technical"],"chip":w["chip"],"news":w["news"]}
    scores={"fundamental":fu.get("score"),"technical":te.get("score"),"chip":ch.get("score"),"news":nw.get("score")}
    valid=[(k,v,weights[k]) for k,v in scores.items() if v is not None]
    if not valid:return{"overall_score":None,"rating":"資料不足","summary":"各面向資料均不足，無法評估。","weights":weights,"scores":scores}
    tw=sum(wd for _,_,wd in valid);os=round(sum(v*wd for _,v,wd in valid)/tw,1)
    parts=[]
    for k,v,_ in[("fundamental",fu,None),("technical",te,None),("chip",ch,None),("news",nw,None)]:
        label={"fundamental":"基本面","technical":"技術面","chip":"籌碼面","news":"消息面"}[k];s=v.get("score")
        parts.append(f"{label}{'偏強' if s and s>=70 else('普通' if s and s>=50 else('偏弱' if s else '資料不足'))}")
    am={"強勢":"整體偏多，可留意入場機會。","偏多":"技術與籌碼訊號偏正，建議觀察確認後再進場。",
        "觀望":"各面向訊號分歧，建議觀望等待更明確訊號。","偏弱":"技術或基本面存在疑慮，建議保守。"}
    rating=_or(os);summary="，".join(parts)+"。"+am.get(rating,"")
    return{"overall_score":os,"rating":rating,"summary":summary,"weights":weights,"scores":scores}

def compute_4d_ai_signal(ov,fu,te,ch,nw,latest_row,cp,macro=None)->dict:
    macro=macro or {}
    nav=len([s for s in[fu.get("score"),te.get("score"),ch.get("score"),nw.get("score")] if s is not None])
    dq="official" if nav>=3 else("estimated" if nav>=1 else "insufficient")
    os=ov.get("overall_score");ts=te.get("score") or 0;cs=ch.get("score") or 50;ns=nw.get("sentiment","中性")
    bc=os if os is not None else 50
    na=5 if ns=="利多" else(-8 if ns=="利空" else 0)
    ca=5 if cs>=65 else(-6 if cs<40 else 0)
    ta=5 if ts>=70 else(-5 if ts<45 else 0)
    ma=macro.get("macro_adj",0)
    conf=max(0,min(100,round(bc+na+ca+ta+ma)))
    can_buy=(dq=="official")
    if conf>=75 and can_buy:signal="BUY"
    elif conf>=55:signal="WATCH"
    else:signal="AVOID"
    def _g(col):
        if latest_row is None or col not in latest_row.index:return None
        v=latest_row.get(col);return float(v) if pd.notna(v) else None
    ma5=_g("MA5");ma20=_g("MA20")
    support=te.get("support") or(cp*0.95 if cp else None)
    resistance=te.get("resistance") or(cp*1.06 if cp else None)
    if signal=="BUY":
        ep=round(ma5,2) if ma5 and cp>ma5 else(round(ma20,2) if ma20 and cp>ma20 else round(cp*1.01,2))
        tp=round(min(resistance,cp*1.08),2) if resistance else round(cp*1.06,2)
    elif signal=="WATCH":
        ep=round(ma20,2) if ma20 and cp>ma20 else round(cp,2);tp=round(cp*1.03,2)
    else:ep=None;tp=None
    sl=round(ma20*0.97,2) if ma20 else(round(support*0.99,2) if support and cp else round(cp*0.95,2) if cp else None)
    if tp and sl and ep and ep>sl:
        rr=round((tp-ep)/(ep-sl),2);rr=rr if rr>0 else None
    else:rr=None
    if signal=="BUY" and(rr is None or rr<1.5):signal="WATCH"
    if signal=="WATCH" and rr is not None and rr<1.0:signal="AVOID"
    es="normal"
    if ep and cp and sl:
        dev=(cp-ep)/ep*100;dts=(cp-sl)/cp*100
        if dts<2:es="dangerous"
        elif dev>5:es="over_extended"
        elif -2<=dev<=2:es="good_entry"
    er,rr2=[],[]
    if ts>=65:er.append(f"技術面偏強（{ts:.0f}分）")
    if cs>=65:er.append(f"籌碼面偏強（{cs:.0f}分）")
    if ns=="利多":er.append("消息面偏多")
    if ts<45:rr2.append(f"技術面偏弱（{ts:.0f}分）")
    if cs<40:rr2.append(f"籌碼面偏弱（{cs:.0f}分）")
    if ns=="利空":rr2.append("消息面偏空")
    if dq!="official":rr2.append(f"資料品質：{dq}，訊號僅供參考")
    if es=="over_extended":rr2.append("已偏離建議入場價，不建議追高")
    if es=="dangerous":rr2.append("價格接近止蝕區，風險偏高")
    parts=[]
    for k,v,_ in[("技術面",te,None),("籌碼面",ch,None),("消息面",nw,None),("基本面",fu,None)]:
        s=v.get("score");parts.append(f"{k}{'偏強' if s and s>=70 else('普通' if s and s>=50 else('偏弱' if s else '資料不足'))}")
    act={"BUY":"整體條件符合，可考慮入場。","WATCH":"訊號偏正但尚未完全確認，建議觀察。","AVOID":"條件不足，建議保守觀望。"}
    summary="，".join(parts)+"。"+act.get(signal,"")
    hm={"BUY":"5-10 天","WATCH":"3-5 天","AVOID":"不建議持有"}
    return{"signal":signal,"confidence":conf,"data_quality":dq,"entry_status":es,
           "entry_price":ep,"target_price":tp,"stop_loss":sl,"risk_reward_ratio":rr,"holding_days":hm[signal],
           "summary":summary,"entry_reason":er[:4],"risk_reason":rr2[:4],"disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

# ══════════════════════════════════════════════════════════════════════════════
# ★ V10: trade_status 系統
# ══════════════════════════════════════════════════════════════════════════════
def compute_trade_status(ai:dict,cp:float,vol_info:dict|None=None)->str:
    sig=ai.get("signal","AVOID");conf=ai.get("confidence") or 0;rr=ai.get("risk_reward_ratio") or 0
    ep=ai.get("entry_price");quality=ai.get("score_quality","none")
    if sig=="AVOID" or conf<55:return "AVOID"
    dev=0.0
    if ep and ep>0 and cp>0:dev=(cp-ep)/ep*100
    if sig=="BUY":
        if dev>4:return "BUY_PULLBACK"
        if conf>=75 and rr>=1.5:return "BUY_NOW"
        return "WATCH"
    return "WATCH"

# ══════════════════════════════════════════════════════════════════════════════
# ★ V10.1: entry_status 可進場篩選系統
# ══════════════════════════════════════════════════════════════════════════════

ENTRY_STATUS_TEXT = {
    "ENTERABLE":    "可進場",
    "WAIT_PULLBACK":"等回檔",
    "TOO_EXTENDED": "已過熱",
    "BAD_RR":       "RR不足",
    "WEAK_SETUP":   "條件不足",
    "NO_DATA":      "資料不足",
}

def compute_entry_status(ai:dict, cp:float, chg_pct:float|None=None,
                         rsi:float|None=None, ma20:float|None=None,
                         price_df:pd.DataFrame|None=None) -> dict:
    """
    計算進場狀態 entry_status，回傳完整 entry_status_dict。
    用於 AI signal lite 與 scan/ai。
    """
    ep  = ai.get("entry_price")
    tp  = ai.get("target_price")
    sl  = ai.get("stop_loss")
    rr  = ai.get("risk_reward_ratio") or 0
    sig = ai.get("signal","WATCH")

    # 預設值
    distance_to_entry_pct = None
    upside_pct            = None
    downside_to_stop_pct  = None

    if ep and ep > 0 and cp > 0:
        distance_to_entry_pct = round((cp - ep) / ep * 100, 2)
    if tp and cp > 0:
        upside_pct = round((tp - cp) / cp * 100, 2)
    if sl and cp > 0:
        downside_to_stop_pct = round((cp - sl) / cp * 100, 2)

    reasons: list[str] = []

    # ── 無資料 ───────────────────────────────────────────────────────────────
    if sig == "AVOID" or ai.get("score_quality") == "none" or cp <= 0:
        return {"entry_status":"NO_DATA","entry_status_text":"資料不足",
                "can_enter":False,"distance_to_entry_pct":distance_to_entry_pct,
                "upside_pct":upside_pct,"downside_to_stop_pct":downside_to_stop_pct,
                "too_extended_reasons":reasons}

    # ── RR 不足 ──────────────────────────────────────────────────────────────
    if rr < 1.5:
        reasons.append(f"RR比 {rr}x 不足（需≥1.5）")
        return {"entry_status":"BAD_RR","entry_status_text":"RR不足",
                "can_enter":False,"distance_to_entry_pct":distance_to_entry_pct,
                "upside_pct":upside_pct,"downside_to_stop_pct":downside_to_stop_pct,
                "too_extended_reasons":reasons}

    # ── 上漲空間不足 ─────────────────────────────────────────────────────────
    if upside_pct is not None and upside_pct < 5:
        reasons.append(f"距目標價剩 {upside_pct:.1f}%，空間不足（需≥5%）")

    # ── RSI 過熱 ─────────────────────────────────────────────────────────────
    if rsi and rsi > 72:
        reasons.append(f"RSI {rsi:.1f} 過熱（需≤72）")

    # ── 今日漲幅過熱 ─────────────────────────────────────────────────────────
    if chg_pct and chg_pct > 5:
        reasons.append(f"今日漲幅 {chg_pct:.1f}% 過熱（需≤5%）")

    # ── 偏離 MA20 過多 ───────────────────────────────────────────────────────
    if ma20 and ma20 > 0 and cp > 0:
        pct_above_ma20 = (cp - ma20) / ma20 * 100
        if pct_above_ma20 > 8:
            reasons.append(f"現價高於 MA20 {pct_above_ma20:.1f}%（需≤8%）")

    # ── 近期漲幅 ─────────────────────────────────────────────────────────────
    if price_df is not None and not price_df.empty and cp > 0:
        closes = price_df["收盤價"].dropna()
        if len(closes) >= 5:
            gain5 = (cp - float(closes.iloc[-5])) / float(closes.iloc[-5]) * 100
            if gain5 > 12:
                reasons.append(f"近5日漲幅 {gain5:.1f}%，可能過熱（需≤12%）")
        if len(closes) >= 10:
            gain10 = (cp - float(closes.iloc[-10])) / float(closes.iloc[-10]) * 100
            if gain10 > 18:
                reasons.append(f"近10日漲幅 {gain10:.1f}%，可能過熱（需≤18%）")

    # ── 偏離建議入場價 ───────────────────────────────────────────────────────
    if distance_to_entry_pct is not None and distance_to_entry_pct > 3:
        reasons.append(f"現價高於建議入場價 {distance_to_entry_pct:.1f}%（需≤3%）")

    # ── 止蝕距離過遠 ─────────────────────────────────────────────────────────
    if downside_to_stop_pct is not None and downside_to_stop_pct > 6:
        reasons.append(f"止蝕距現價 {downside_to_stop_pct:.1f}%，風險偏大（需≤6%）")

    # ── 結論 ─────────────────────────────────────────────────────────────────
    if reasons:
        # 分類：是過熱、還是等回檔
        extended_kws = ["過熱","漲幅","MA20","近5日","近10日"]
        is_extended = any(any(kw in r for kw in extended_kws) for r in reasons)
        if is_extended:
            status = "TOO_EXTENDED" if (rsi and rsi > 72) or (chg_pct and chg_pct > 5) else "WAIT_PULLBACK"
        else:
            status = "WAIT_PULLBACK"
        return {"entry_status":status,"entry_status_text":ENTRY_STATUS_TEXT[status],
                "can_enter":False,"distance_to_entry_pct":distance_to_entry_pct,
                "upside_pct":upside_pct,"downside_to_stop_pct":downside_to_stop_pct,
                "too_extended_reasons":reasons}

    # ── 全部通過 → 可進場 ────────────────────────────────────────────────────
    if sig == "WATCH":
        return {"entry_status":"WEAK_SETUP","entry_status_text":"條件不足",
                "can_enter":False,"distance_to_entry_pct":distance_to_entry_pct,
                "upside_pct":upside_pct,"downside_to_stop_pct":downside_to_stop_pct,
                "too_extended_reasons":[]}

    return {"entry_status":"ENTERABLE","entry_status_text":"可進場",
            "can_enter":True,"distance_to_entry_pct":distance_to_entry_pct,
            "upside_pct":upside_pct,"downside_to_stop_pct":downside_to_stop_pct,
            "too_extended_reasons":[]}


def _enrich_ai_with_entry(ai:dict, cp:float, chg_pct:float|None=None,
                           rsi_val:float|None=None, ma20_val:float|None=None,
                           price_df:pd.DataFrame|None=None) -> dict:
    """將 entry_status 欄位注入 ai dict，不改變原有欄位。"""
    es = compute_entry_status(ai, cp, chg_pct, rsi_val, ma20_val, price_df)
    ai.update(es)
    return ai


# ★ V10: Momentum Breakout
def check_momentum_breakout(row:pd.Series,vol_info:dict)->bool:
    def _g(col):return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    ma5=_g("MA5");ma20=_g("MA20");macd=_g("MACD");sig=_g("Signal");hist=_g("Hist");rsi=_g("RSI")
    vr=vol_info.get("ratio",1.0) if vol_info else 1.0
    if not all([ma5,ma20,macd,sig,hist,rsi]):return False
    return(ma5>ma20 and macd>sig and hist>0 and 55<=rsi<=75 and vr>=2.0)

# ★ V10: 多時間框架
def compute_weekly_trend(df:pd.DataFrame)->str:
    try:
        d=df.copy();d["週"]=d["日期"].dt.to_period("W")
        wk=d.groupby("週")["收盤價"].last().reset_index()
        if len(wk)<21:return "資料不足"
        c=wk["收盤價"];m5=c.rolling(5).mean();m20=c.rolling(20).mean()
        l5=m5.iloc[-1];l20=m20.iloc[-1];lc=c.iloc[-1]
        if lc>l20 and l5>l20:return "多頭"
        if lc<l20 and l5<l20:return "空頭"
        return "盤整"
    except:return "資料不足"

def compute_multi_timeframe(df:pd.DataFrame,latest:pd.Series,cp:float)->dict:
    def _g(col):return float(latest[col]) if col in latest.index and pd.notna(latest.get(col)) else None
    ma5=_g("MA5");ma20=_g("MA20");rsi=_g("RSI");macd=_g("MACD");sig=_g("Signal")
    ds=0
    if ma20 and cp>ma20:ds+=25
    if ma5 and ma20 and ma5>ma20:ds+=25
    if rsi and 45<=rsi<=70:ds+=25
    if macd and sig and macd>sig:ds+=25
    dt="多" if ds>=75 else("空" if ds<=25 else "中性")
    wt=compute_weekly_trend(df);ws=100 if wt=="多頭" else(0 if wt=="空頭" else 50)
    ms=round(ds*0.6+ws*0.4)
    return{"daily_score":ds,"daily_trend":dt,"weekly_score":ws,"weekly_trend":wt,
           "multi_timeframe_score":ms,"overall":"多頭" if ms>=65 else("空頭" if ms<=35 else "盤整")}

# ══════════════════════════════════════════════════════════════════════════════
# AI 訊號三層評分（V9.2 保留 + V10 trade_status + momentum）
# ══════════════════════════════════════════════════════════════════════════════
def compute_ai_signal_lite(row:pd.Series,winrate_info:dict,cp:float,macro:dict|None=None,
                           price_df_len:int=0,realtime_quote:dict|None=None,
                           vol_info:dict|None=None,price_df:pd.DataFrame|None=None)->dict:
    macro=macro or {};rt=realtime_quote or {}
    def _g(col):return float(row[col]) if col in row.index and pd.notna(row.get(col)) else None
    def _mk(signal,conf,quality,status,note,ep,tp,sl,rr,ts,strat):
        return{"signal":signal,"confidence":conf,"score_status":status,"score_quality":quality,"score_note":note,
               "entry_price":ep,"target_price":tp,"stop_loss":sl,
               "holding_days":"不建議持有" if signal=="AVOID" else("5-10 天" if(conf or 0)>=75 else "3-5 天"),
               "risk_reward_ratio":rr,"trade_status":ts,"strategy_type":strat,
               "risk_model":{"risk_level":"LOW" if(conf or 0)>=75 else "MEDIUM" if(conf or 0)>=55 else "HIGH","final_score":conf},
               "entry_reason":[],"risk_reason":[],"score_breakdown":{"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
               "macro_context":{"usd_twd":macro.get("usd_twd"),"dxy":macro.get("dxy"),"note":macro.get("risk_note","")},
               "summary":"技術面分析完成，四面向分析請按需載入。","disclaimer":"⚠️ 本工具僅供參考，非投資建議"}

    if cp<=0:return _mk("WATCH",None,"none","無資料","目前無法取得即時報價",None,None,None,None,"WATCH","")

    ma5=_g("MA5");ma20=_g("MA20");ma60=_g("MA60")
    rsi=_g("RSI");macd=_g("MACD");sig=_g("Signal");hist=_g("Hist")
    wr=winrate_info.get("winrate",0)

    def _cp(signal):
        if signal=="BUY":tp=round(cp*1.06,2)
        elif signal=="WATCH":tp=round(cp*1.03,2)
        else:tp=None
        sl=round(ma20*0.98,2) if ma20 else round(cp*0.95,2)
        ep=None
        if signal!="AVOID":
            if ma5 and cp>ma5:ep=round(ma5,2)
            elif ma20 and cp>ma20:ep=round(ma20,2)
            else:ep=round(cp,2)
        if tp and sl and cp>sl:
            rr=round((tp-cp)/(cp-sl),2);rr=rr if rr>0 else None
        else:rr=None
        if signal=="BUY" and(rr is None or rr<1.5):signal="WATCH";tp=round(cp*1.03,2)
        return signal,ep,tp,sl,rr

    # ★ V10.1 Momentum Breakout + 風控
    if vol_info and check_momentum_breakout(row,vol_info):
        ep=round(ma5,2) if ma5 else round(cp,2)
        tp=round(cp*1.06,2);sl=round(ma20*0.97,2) if ma20 else round(cp*0.95,2)
        rr=round((tp-ep)/(ep-sl),2) if ep and sl and ep>sl else None
        conf=82
        # 風控：過熱時降為 BUY_PULLBACK
        chgp_val=float(rt.get("change_pct") or 0)
        ma20_pct=(cp-ma20)/ma20*100 if ma20 and ma20>0 else 0
        dist_entry=(cp-ep)/ep*100 if ep and ep>0 else 0
        upside=(tp-cp)/cp*100 if tp and cp>0 else 0
        mb_ok=(rsi is None or rsi<=72) and chgp_val<=5 and ma20_pct<=8 and (rr or 0)>=1.5 and upside>=5 and dist_entry<=3
        if mb_ok:
            ts="BUY_NOW"
        else:
            ts="BUY_PULLBACK"
        return _mk("BUY",conf,"full","正式分數","Momentum Breakout",ep,tp,sl,rr,ts,"Momentum Breakout")

    # Layer 1 正式分數
    full=all(v is not None for v in[ma20,ma60,rsi,macd,sig])
    if price_df_len>=60 and full:
        score=0
        if ma5 and ma20 and ma5>ma20:score+=20
        if ma20 and cp>ma20:score+=20
        if ma20 and ma60 and ma20>ma60:score+=20
        if rsi and 45<=rsi<=70:score+=15
        if macd and sig and macd>sig:score+=15
        if hist and hist>0:score+=10
        pen=0
        if rsi and rsi>78:pen-=10
        if rsi and rsi<30:pen-=5
        if ma20 and ma20>0 and(cp-ma20)/ma20*100>15:pen-=8
        final=max(0,min(100,score+pen+(macro.get("macro_adj",0))))
        if final>=75:s="BUY"
        elif final>=55:s="WATCH"
        else:s="AVOID"
        s,ep,tp,sl,rr=_cp(s)
        ts=compute_trade_status({"signal":s,"confidence":final,"risk_reward_ratio":rr,"entry_price":ep,"score_quality":"full"},cp,vol_info)
        return _mk(s,final,"full","正式分數","",ep,tp,sl,rr,ts,"")

    # Layer 2 估算分
    adj=0;chgp=rt.get("change_pct");prev=rt.get("previous_close")
    if chgp is not None:
        c2=float(chgp)
        if c2>3:adj+=8
        elif c2>1:adj+=5
        elif c2<-3:adj-=8
        elif c2<-1:adj-=5
    if prev and cp:
        if cp>float(prev):adj+=5
        elif cp<float(prev):adj-=5
    if ma20:
        if cp>ma20:adj+=10
        elif cp<ma20:adj-=10
    if rsi:
        if 45<=rsi<=70:adj+=10
        elif rsi>75:adj-=10
        elif rsi<35:adj-=8
    if macd is not None and sig is not None:
        if macd>sig:adj+=8
        elif macd<sig:adj-=8
    est=max(20,min(80,50+adj))
    s="WATCH" if est>=55 else "AVOID"
    s,ep,tp,sl,rr=_cp(s)
    ts=compute_trade_status({"signal":s,"confidence":est,"risk_reward_ratio":rr,"entry_price":ep,"score_quality":"partial"},cp,vol_info)
    return _mk(s,est,"partial","估算分","資料不足，先以即時價與可用技術資料估算",ep,tp,sl,rr,ts,"")

# ══════════════════════════════════════════════════════════════════════════════
# LINE
# ══════════════════════════════════════════════════════════════════════════════
def _lc():return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID and ENABLE_LINE_ALERTS)
def _cc():
    if not LINE_CHANNEL_ACCESS_TOKEN:raise HTTPException(503,detail="LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
    if not LINE_TO_ID:raise HTTPException(503,detail="LINE_TO_ID 尚未設定")
    if not ENABLE_LINE_ALERTS:raise HTTPException(503,detail="ENABLE_LINE_ALERTS 未設為 true")

async def send_line_message(msg:str)->dict:
    hdr={"Authorization":f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}","Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r=await cl.post(LINE_PUSH_URL,headers=hdr,json={"to":LINE_TO_ID,"messages":[{"type":"text","text":msg}]})
            if r.status_code==200:return{"success":True,"message":"LINE 訊息發送成功"}
            return{"success":False,"message":f"LINE API 錯誤：{r.status_code}"}
    except Exception as e:return{"success":False,"message":f"發送失敗：{str(e)}"}

def _blm(sid,name,ai,price):
    disp=f"{name} ({sid})" if name and name!=sid else sid
    ts=ai.get("trade_status","WATCH");tl={"BUY_NOW":"✅ 可布局","BUY_PULLBACK":"⏳ 等回檔"}.get(ts,"👀 觀察")
    return(f"📈 V10.2 AI 交易訊號\n股票：{disp}\n狀態：{tl}\n訊號：{ai['signal']}\n信心：{ai['confidence']}/100\n"
           f"即時價：{price}  入場：{ai.get('entry_price') or '—'}\n目標：{ai.get('target_price')}  止蝕：{ai.get('stop_loss')}\n"
           f"RR：{ai.get('risk_reward_ratio')}x  持有：{ai.get('holding_days','—')}\n{ai.get('disclaimer','⚠️ 非投資建議')}")

# ══════════════════════════════════════════════════════════════════════════════
# 進階回測（含 Sharpe Ratio）
# ══════════════════════════════════════════════════════════════════════════════
def advanced_backtest(df,holding_days=5,min_score=75):
    empty={"total_trades":0,"wins":0,"losses":0,"winrate":0,"avg_return":0,"best_return":0,"worst_return":0,"max_drawdown":0,"profit_factor":0,"sharpe_ratio":0,"trades":[]}
    if df.empty:return empty
    df=df.copy().reset_index(drop=True);df=compute_indicators(df)
    req=[c for c in["MA5","MA20","MA60","RSI","MACD","Signal"] if c in df.columns]
    df=df.dropna(subset=req) if req else df
    trades,equity,peak,max_dd=[],1.0,1.0,0.0
    for i,(_,row) in enumerate(df.iterrows()):
        if i+holding_days>=len(df):break
        vi={"alert":False,"ratio":1.0,"latest_volume":0,"avg_volume_20d":0}
        wi={"winrate":0,"trials":0,"wins":0};cur=float(row["收盤價"])
        ai=compute_ai_signal_lite(row,wi,cur,price_df_len=100)
        if(ai.get("confidence") or 0)<min_score:continue
        ep=float(df.iloc[i+holding_days]["收盤價"]);rp=round((ep-cur)/cur*100,2)
        trades.append({"date":row["日期"].strftime("%Y-%m-%d"),"entry_price":cur,"exit_price":ep,
                       "return_pct":rp,"win":ep>cur,"confidence":ai.get("confidence",0),"signal":ai.get("signal","")})
        equity*=(1+rp/100);peak=max(peak,equity);dd=(peak-equity)/peak*100;max_dd=max(max_dd,dd)
    total=len(trades);wins=sum(1 for t in trades if t["win"])
    rets=[t["return_pct"] for t in trades]
    gain=sum(r for r in rets if r>0);loss=abs(sum(r for r in rets if r<0))
    avg_r=sum(rets)/total if total else 0
    std_r=(sum((r-avg_r)**2 for r in rets)/total)**0.5 if total>1 else 0
    sharpe=round(avg_r/std_r,2) if std_r>0 else 0
    return{"total_trades":total,"wins":wins,"losses":total-wins,
           "winrate":round(wins/total*100,1) if total else 0,"avg_return":round(avg_r,2),
           "best_return":round(max(rets),2) if rets else 0,"worst_return":round(min(rets),2) if rets else 0,
           "max_drawdown":round(max_dd,2),"profit_factor":round(gain/loss,2) if loss else 0,
           "sharpe_ratio":sharpe,"trades":list(reversed(trades))[:20]}

# ══════════════════════════════════════════════════════════════════════════════
# 核心查詢（V10 輕量穩定）
# ══════════════════════════════════════════════════════════════════════════════
async def _analyze_stock_core(stock_id:str)->dict:
    sname=get_stock_name(stock_id)
    try:
        rt=await fetch_realtime_quote(stock_id)
        if rt and rt.get("stock_name"):sname=rt["stock_name"]
        df,dsrc=await fetch_price_with_fallback(stock_id,lookback_days=400)
        if df.empty:
            rtp=rt.get("price") if rt else None
            return{"stock_id":stock_id,"stock_name":sname,"last_date":"N/A","data_source":"none",
                   "data_warning":"歷史股價資料暫時無法取得，僅顯示即時報價。",
                   "price":{"close":rtp,"daily_close":None,"open":None,"high":None,"low":None,
                            "change":rt.get("change") if rt else None,"change_pct":rt.get("change_pct") if rt else None,
                            "mode":"realtime" if rtp else "unavailable"},
                   "indicators":{k:None for k in["ma5","ma20","ma60","rsi","macd","signal","hist","bb_upper","bb_lower","bb_mid"]},
                   "volume":{"latest_volume":0,"avg_volume_20d":0,"ratio":1.0,"alert":False},
                   "score":{"score":0,"max":5,"reasons":["❌ 無法評估（資料不足）"]},"backtest":{"trials":0,"wins":0,"winrate":0},
                   "conclusion":"資料不足 ⚠️","rsi_alert":None,
                   "ai_signal":compute_ai_signal_lite(pd.Series(),{"winrate":0,"trials":0,"wins":0},rtp or 0),
                   "multi_timeframe":None,"realtime_quote":rt,"news":[],"chart_data":[],"analysis_4d":None}
        df=compute_indicators(df);latest=df.iloc[-1];prev=df.iloc[-2] if len(df)>1 else latest
        chg=float(latest["收盤價"]-prev["收盤價"])
        chgp=round(chg/float(prev["收盤價"])*100,2) if float(prev["收盤價"]) else 0
        cp=float(rt["price"]) if rt and rt.get("price") is not None else float(latest["收盤價"])
        sc=technical_score(latest);wr=backtest_winrate(df);vi=volume_analysis(df)
        conc="短線偏多 📈" if sc["score"]>=4 else("短線偏弱 📉" if sc["score"]<=2 else "觀望 ➡️")
        rv=float(latest["RSI"]) if "RSI" in latest.index and pd.notna(latest.get("RSI")) else None
        ra="⚠️ RSI 過熱（>70）" if rv and rv>70 else("⚠️ RSI 過冷（<30）" if rv and rv<30 else None)
        try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
        except:macro={"usd_twd":None,"dxy":None,"risk_note":"","macro_adj":0}
        ai=compute_ai_signal_lite(latest,wr,cp,macro=macro,price_df_len=len(df),realtime_quote=rt,vol_info=vi,price_df=df)
        mtf=compute_multi_timeframe(df,latest,cp)
        # V10.1: enrich with entry_status
        rsi_cv=float(latest["RSI"]) if "RSI" in latest.index and pd.notna(latest.get("RSI")) else None
        ma20_cv=float(latest["MA20"]) if "MA20" in latest.index and pd.notna(latest.get("MA20")) else None
        chgp_cv=(_f(rt.get("change_pct"),2) if rt and rt.get("change_pct") is not None else chgp)
        ai=_enrich_ai_with_entry(ai,cp,chgp_cv,rsi_cv,ma20_cv,df)
        record_ai_signal(stock_id,sname,ai,None,source="stock")
        chart_data=[]
        for _,row in df.tail(60).iterrows():
            chart_data.append({"date":row["日期"].strftime("%Y-%m-%d"),
                "open":_f(row.get("開盤價")),"high":_f(row.get("最高價")),"low":_f(row.get("最低價")),
                "close":_f(row.get("收盤價")),"volume":int(row["成交股數"]) if pd.notna(row.get("成交股數")) else 0,
                "ma5":_f(row.get("MA5")),"ma20":_f(row.get("MA20")),"ma60":_f(row.get("MA60")),
                "rsi":_f(row.get("RSI")),"macd":_f(row.get("MACD"),4),"signal":_f(row.get("Signal"),4),"hist":_f(row.get("Hist"),4),
                "bb_upper":_f(row.get("BB_upper")),"bb_lower":_f(row.get("BB_lower"))})
        return{"stock_id":stock_id,"stock_name":sname,"last_date":latest["日期"].strftime("%Y-%m-%d"),"data_source":dsrc,
               "price":{"close":_f(cp),"daily_close":_f(latest["收盤價"]),
                   "open":_f(rt.get("open") if rt else latest.get("開盤價")),
                   "high":_f(rt.get("high") if rt else latest.get("最高價")),
                   "low":_f(rt.get("low") if rt else latest.get("最低價")),
                   "change":(_f(rt.get("change"),2) if rt and rt.get("change") is not None else round(chg,2)),
                   "change_pct":(_f(rt.get("change_pct"),2) if rt and rt.get("change_pct") is not None else chgp),
                   "mode":"realtime" if rt and rt.get("price") is not None else "daily"},
               "indicators":{"ma5":_f(latest.get("MA5")),"ma20":_f(latest.get("MA20")),"ma60":_f(latest.get("MA60")),
                   "rsi":_f(latest.get("RSI")),"macd":_f(latest.get("MACD"),4),"signal":_f(latest.get("Signal"),4),
                   "hist":_f(latest.get("Hist"),4),"bb_upper":_f(latest.get("BB_upper")),
                   "bb_lower":_f(latest.get("BB_lower")),"bb_mid":_f(latest.get("BB_mid"))},
               "volume":vi,"score":sc,"backtest":wr,"conclusion":conc,"rsi_alert":ra,
               "ai_signal":ai,"multi_timeframe":mtf,"realtime_quote":rt,"news":[],"chart_data":chart_data,"analysis_4d":None}
    except Exception as e:return{"stock_id":stock_id,"stock_name":sname,"error":str(e),"chart_data":[],"analysis_4d":None}

async def _analyze_stock_lite(stock_id:str,macro:dict|None=None)->dict:
    sname=get_stock_name(stock_id);macro=macro or {}
    fai={"signal":"WATCH","confidence":None,"score_status":"無資料","score_quality":"none",
         "score_note":"目前無法取得即時報價","entry_price":None,"target_price":None,"stop_loss":None,
         "holding_days":"不建議持有","risk_reward_ratio":None,"trade_status":"WATCH","strategy_type":"",
         "risk_model":{"risk_level":"MEDIUM","final_score":None},"entry_reason":[],"risk_reason":[],
         "score_breakdown":{"trend":0,"momentum":0,"volume":0,"backtest":0,"news":0},
         "macro_context":{},"summary":"資料不足","disclaimer":"⚠️ 本工具僅供參考，非投資建議"}
    try:
        rt=await fetch_realtime_quote(stock_id)
        if rt and rt.get("stock_name"):sname=rt["stock_name"]
        price=rt["price"] if rt and rt.get("price") is not None else None
        change=rt["change"] if rt and rt.get("change") is not None else None
        chgp=rt["change_pct"] if rt and rt.get("change_pct") is not None else None
        df,hs=await fetch_price_with_fallback(stock_id,lookback_days=90)
        if price is None and not df.empty:
            price=float(df.iloc[-1]["收盤價"])
            if len(df)>=2:
                pc=float(df.iloc[-2]["收盤價"]);change=round(price-pc,2)
                chgp=round(change/pc*100,2) if pc else None
        cp=price or 0.0;ai=fai.copy()
        if not df.empty and cp>0:
            df=compute_indicators(df);latest=df.iloc[-1];wri=backtest_winrate(df);vi=volume_analysis(df)
            ai=compute_ai_signal_lite(latest,wri,cp,macro=macro,price_df_len=len(df),realtime_quote=rt,vol_info=vi,price_df=df)
        elif cp>0:
            ai=compute_ai_signal_lite(pd.Series(),{"winrate":0,"trials":0,"wins":0},cp,macro=macro,price_df_len=0,realtime_quote=rt)
        # V10.1: enrich with entry_status
        rsi_v=None;ma20_v=None
        if not df.empty and len(df)>0:
            try:
                latest2=df.iloc[-1]
                rsi_v=float(latest2["RSI"]) if "RSI" in latest2.index and pd.notna(latest2.get("RSI")) else None
                ma20_v=float(latest2["MA20"]) if "MA20" in latest2.index and pd.notna(latest2.get("MA20")) else None
            except:pass
        ai=_enrich_ai_with_entry(ai,cp,chgp,rsi_v,ma20_v,df if not df.empty else None)
        record_ai_signal(stock_id,sname,ai,None,source="stock-lite")
        return{"stock_id":stock_id,"stock_name":sname,"price":price,"change":change,"change_pct":chgp,
               "realtime_quote":rt,"ai_signal":ai,"data_source":hs if not df.empty else "TWSE MIS","lite":True}
    except Exception as e:
        return{"stock_id":stock_id,"stock_name":sname,"price":None,"change":None,"change_pct":None,
               "realtime_quote":None,"ai_signal":fai,"data_source":"error","lite":True,"error":str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# 市場情緒掃描（快取 10 分鐘）
# ══════════════════════════════════════════════════════════════════════════════
_sc_cache:dict={};_sc_ts:float=0.0
async def _scan_market_sentiment()->dict:
    global _sc_cache,_sc_ts
    if _sc_cache and(time.time()-_sc_ts)<600:return _sc_cache
    pool=AI_SCAN_POOL[:30];buy=watch=avoid=0
    try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except:macro={}
    for sid in pool:
        try:
            r=await _analyze_stock_lite(sid,macro);s=r.get("ai_signal",{}).get("signal","WATCH")
            if s=="BUY":buy+=1
            elif s=="AVOID":avoid+=1
            else:watch+=1
        except:pass
    tot=buy+watch+avoid or 1
    sent="強勢🔥" if buy>watch and buy>avoid else("空頭❄️" if avoid>(buy+watch)*0.5 else "中性⚠️")
    result={"buy_count":buy,"watch_count":watch,"avoid_count":avoid,"total":tot,
            "buy_pct":round(buy/tot*100,1),"sentiment":sent,"scanned_at":datetime.now().isoformat()}
    _sc_cache=result;_sc_ts=time.time();return result

# ══════════════════════════════════════════════════════════════════════════════
# 啟動
# ══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    loaded=_lfm()
    if not loaded or _ims():asyncio.create_task(fetch_stock_master_list())

# ══════════════════════════════════════════════════════════════════════════════
# API 端點
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/watchlist")
async def api_get_watchlist():items=_rwl();return{"watchlist":items,"count":len(items)}

@app.post("/api/watchlist")
async def api_post_watchlist(body:WatchlistUpdateBody):
    items=_nwl(body.watchlist);_wwl(items);return{"watchlist":items,"count":len(items),"saved":True}

@app.get("/api/stocks/master")
async def api_stocks_master():
    if not STOCK_MASTER:_lfm()
    return{"count":len(STOCK_MASTER),"updated_at":_mua,"stocks":STOCK_MASTER}

@app.get("/api/stocks/search")
async def api_stocks_search(q:str=Query("",min_length=1)):
    if not STOCK_MASTER:_lfm()
    q=q.strip();results=[]
    if q in STOCK_MASTER:results.append({"stock_id":q,"stock_name":STOCK_MASTER[q]["name"],"market":STOCK_MASTER[q].get("market","")})
    for sid,info in STOCK_MASTER.items():
        if sid==q:continue
        if sid.startswith(q):results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
        if len(results)>=20:break
    if len(results)<20:
        for sid,info in STOCK_MASTER.items():
            if sid==q or sid.startswith(q):continue
            if q in info["name"]:results.append({"stock_id":sid,"stock_name":info["name"],"market":info.get("market","")})
            if len(results)>=20:break
    return{"results":results[:20],"query":q}

@app.get("/api/stock/{stock_id}")
async def get_stock(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id):raise HTTPException(400,detail="股票代號格式錯誤，請輸入 4~6 位數字")
    return await _analyze_stock_core(stock_id)

@app.get("/api/stock-lite/{stock_id}")
async def get_stock_lite(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id):raise HTTPException(400,detail="股票代號格式錯誤")
    try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=5)
    except:macro={}
    return await _analyze_stock_lite(stock_id,macro)

@app.get("/api/realtime/{stock_id}")
async def get_realtime(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id):raise HTTPException(400,detail="股票代號格式錯誤")
    q=await fetch_realtime_quote(stock_id)
    if not q:raise HTTPException(404,detail="找不到即時報價")
    return q

@app.get("/api/analysis-4d/{stock_id}")
async def get_analysis_4d(stock_id:str):
    if not re.match(r"^\d{4,6}$",stock_id):raise HTTPException(400,detail="股票代號格式錯誤")
    try:
        at=asyncio.create_task(_fname(stock_id))
        df,dsrc=await fetch_price_with_fallback(stock_id,lookback_days=400)
        an=await at;sname=get_stock_name(stock_id,an);lr=None
        rt=await fetch_realtime_quote(stock_id)
        if df.empty:cp=float(rt["price"]) if rt and rt.get("price") else 0.0
        else:
            df=compute_indicators(df);lr=df.iloc[-1]
            cp=float(rt["price"]) if rt and rt.get("price") else float(lr["收盤價"])
        news,fu,chip,margin=await asyncio.gather(
            fetch_news(stock_id,sname),fetch_fundamental_data(stock_id),fetch_chip_data(stock_id),fetch_margin_data(stock_id))
        te=analyze_technical_4d(df,lr,cp) if not df.empty and lr is not None else{"score":None,"rating":"資料不足","trend":"—","reasons":[],"risks":[],"support":None,"resistance":None,"atr":None}
        fud=analyze_fundamental_4d(fu);chd=analyze_chip_4d(chip,margin);nwd=analyze_news_4d(news)
        ovd=compute_overall_4d(fud,te,chd,nwd)
        try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=5)
        except:macro={}
        ai4d=compute_4d_ai_signal(ovd,fud,te,chd,nwd,lr,cp,macro)
        return{"stock_id":stock_id,"stock_name":sname,"cur_price":cp,"data_source":dsrc,
               "analysis_4d":{"fundamental":fud,"technical":te,"chip":chd,"news":nwd,"overall":ovd},
               "ai_signal":ai4d,"news":news}
    except Exception as e:
        return{"stock_id":stock_id,"stock_name":get_stock_name(stock_id),"error":str(e),"analysis_4d":None,
               "ai_signal":{"signal":"WATCH","confidence":None,"data_quality":"insufficient","entry_status":"normal",
                             "entry_price":None,"target_price":None,"stop_loss":None,"risk_reward_ratio":None,
                             "holding_days":"不建議持有","summary":"四面向資料暫時無法取得。",
                             "entry_reason":[],"risk_reason":["資料暫時無法取得"],"disclaimer":"⚠️ 本工具僅供參考，非投資建議"},"news":[]}

@app.get("/api/macro")
async def api_macro():
    try:return await asyncio.wait_for(fetch_macro_context(),timeout=10)
    except Exception as e:return{"error":str(e),"usd_twd":None,"dxy":None,"nasdaq_futures":None,"sox":None,"us10y":None,"risk_note":"宏觀資料暫時無法取得","macro_adj":0}

@app.get("/api/market-sentiment")
async def api_market_sentiment():
    try:return await _scan_market_sentiment()
    except Exception as e:return{"error":str(e),"buy_count":0,"watch_count":0,"avoid_count":0,"sentiment":"中性⚠️"}

@app.get("/api/scan/ai")
async def ai_scan(min_score:int=Query(70,ge=0,le=100),max_stocks:int=Query(40,ge=5,le=80)):
    """V10.1: AI 選股 + entry_filter，分 ENTERABLE / WAIT_PULLBACK 兩區。"""
    t0=time.time();pool=list(dict.fromkeys(AI_SCAN_POOL))[:max_stocks]
    try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except:macro={}
    enterable=[];pullback=[];errors=[]
    for sid in pool:
        try:
            r=await _analyze_stock_lite(sid,macro);ai=r.get("ai_signal",{})
            conf=ai.get("confidence") or 0
            if conf<min_score:continue
            es=ai.get("entry_status","NO_DATA")
            item={"stock_id":sid,"stock_name":r["stock_name"],
                "signal":ai.get("signal","WATCH"),"confidence":conf,
                "trade_status":ai.get("trade_status","WATCH"),
                "entry_status":es,"entry_status_text":ai.get("entry_status_text",ENTRY_STATUS_TEXT.get(es,"—")),
                "can_enter":ai.get("can_enter",False),
                "strategy_type":ai.get("strategy_type",""),
                "risk_level":ai.get("risk_model",{}).get("risk_level","—"),
                "price":r.get("price"),"change_pct":r.get("change_pct"),
                "entry_price":ai.get("entry_price"),"target_price":ai.get("target_price"),
                "stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),
                "distance_to_entry_pct":ai.get("distance_to_entry_pct"),
                "upside_pct":ai.get("upside_pct"),
                "score_quality":ai.get("score_quality","none"),
                "too_extended_reasons":ai.get("too_extended_reasons",[]),
                "summary":ai.get("summary","")}
            if es=="ENTERABLE":enterable.append(item)
            elif es in("WAIT_PULLBACK","TOO_EXTENDED"):pullback.append(item)
        except Exception as e:errors.append({"stock_id":sid,"error":str(e)})
    # 排序
    def sort_enter(x):
        rr=x.get("risk_reward_ratio") or 0
        dist=abs(x.get("distance_to_entry_pct") or 99)
        conf=x.get("confidence") or 0
        return (-rr,-dist,conf)  # RR高、距離近、信心高
    def sort_pullback(x):return (-(x.get("confidence") or 0))
    enterable.sort(key=sort_enter);pullback.sort(key=sort_pullback)
    return{"scanned":len(pool),"enterable_count":len(enterable),"pullback_count":len(pullback),
           "min_score":min_score,"enterable":enterable,"pullback":pullback,
           "errors":errors,"error_count":len(errors),
           "duration_seconds":round(time.time()-t0,1),"timestamp":datetime.now().isoformat()}

@app.post("/api/alerts/test")
async def test_line():
    _cc()
    result=await send_line_message("✅ 台股監測 V10.2 Personal - LINE 通知測試成功！")
    if not result["success"]:raise HTTPException(500,detail=result["message"])
    return result

@app.post("/api/alerts/check")
async def check_alerts(body:WatchlistBody):
    t0=time.time();lo=_lc();results=[];now=datetime.now();sent=[];errors=[]
    stock_ids=body.watchlist or [item["stock_id"] for item in _rwl()]
    try:macro=await asyncio.wait_for(fetch_macro_context(),timeout=6)
    except:macro={}
    for sid in stock_ids:
        if not re.match(r"^\d{4,6}$",sid):continue
        try:
            r=await _analyze_stock_lite(sid,macro);ai=r.get("ai_signal",{});sn=r.get("stock_name",sid);cp2=r.get("price") or 0
            results.append({"stock_id":sid,"stock_name":sn,"signal":ai.get("signal","AVOID"),
                "confidence":ai.get("confidence",0),"trade_status":ai.get("trade_status","WATCH"),
                "summary":ai.get("summary",""),"entry_price":ai.get("entry_price"),"target_price":ai.get("target_price"),
                "stop_loss":ai.get("stop_loss"),"risk_reward_ratio":ai.get("risk_reward_ratio"),
                "risk_level":ai.get("risk_model",{}).get("risk_level","—")})
            rr2=ai.get("risk_reward_ratio") or 0;conf=ai.get("confidence") or 0
            dq=ai.get("score_quality","none");ts=ai.get("trade_status","WATCH")
            es2=ai.get("entry_status","NO_DATA");up2=ai.get("upside_pct") or 0
            lok=(conf>=75 and rr2>=1.5 and dq=="full" and ai.get("signal")=="BUY"
                 and es2=="ENTERABLE" and up2>=5)
            if lo and lok:
                ls=LAST_ALERTS.get(sid)
                if ls is None or(now-ls).total_seconds()>=ALERT_COOLDOWN_MINUTES*60:
                    res=await send_line_message(_blm(sid,sn,ai,cp2))
                    if res["success"]:LAST_ALERTS[sid]=now;sent.append(sid)
        except Exception as e:errors.append({"stock_id":sid,"error":str(e)})
    rank={"BUY":3,"WATCH":2,"AVOID":1}
    results.sort(key=lambda x:(rank.get(x.get("signal",""),0),x.get("confidence",0)),reverse=True)
    return{"checked":len(stock_ids),"alerts":[r for r in results if r.get("signal")=="BUY"],
           "all_results":results,"sent_line":sent,"line_enabled":lo,
           "errors":errors,"error_count":len(errors),"duration_seconds":round(time.time()-t0,1),"timestamp":now.isoformat()}

@app.get("/api/backtest/{stock_id}")
async def run_backtest(stock_id:str,lookback_days:int=400,holding_days:int=5,min_score:int=75):
    if not re.match(r"^\d{4,6}$",stock_id):raise HTTPException(400,detail="股票代號格式錯誤")
    df,_=await fetch_price_with_fallback(stock_id,lookback_days)
    an=await _fname(stock_id);sname=get_stock_name(stock_id,an)
    result=advanced_backtest(df,holding_days=holding_days,min_score=min_score)
    return{"stock_id":stock_id,"stock_name":sname,
           "params":{"lookback_days":lookback_days,"holding_days":holding_days,"min_score":min_score},
           "result":{k:v for k,v in result.items() if k!="trades"},"trades":result["trades"]}

@app.get("/api/learning/weights")
def api_learning_weights():
    h=load_signal_history()
    return{"weights":load_ai_weights(),"stats":_lst(h),"recent":list(reversed(h))[:10]}

@app.get("/api/learning/history")
def api_learning_history(limit:int=Query(100,ge=1,le=500)):
    h=load_signal_history();return{"count":len(h),"signals":list(reversed(h))[:limit]}

@app.get("/api/learning/evaluate")
async def api_learning_evaluate():return await evaluate_signal_history()

@app.post("/api/learning/retrain")
def api_learning_retrain():return retrain_ai_weights()

@app.get("/health")
def health():
    return{"status":"ok","version":"10.2.0","time":datetime.now().isoformat(),
           "dev_mode":DEV_MODE,"line_configured":bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_TO_ID),
           "line_enabled":ENABLE_LINE_ALERTS,"realtime_source":"TWSE MIS",
           "price_sources":"Yahoo Finance → TWSE Official → FinMind",
           "stock_master_count":len(STOCK_MASTER),"stock_master_updated":_mua,
           "http_timeout":HTTP_TIMEOUT,
           "features":["V10.2 Personal Trading System","trade_status BUY_NOW/BUY_PULLBACK/WATCH/AVOID",
                       "Momentum Breakout","multi_timeframe","macro_api","market_sentiment",
                       "Firestore watchlist","4D on-demand","AI learning","stock-lite","sharpe_ratio"]}
