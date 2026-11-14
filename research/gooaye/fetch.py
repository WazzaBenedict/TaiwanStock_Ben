import requests, pandas as pd, json, os, time
H={'User-Agent':'Mozilla/5.0'}
r=requests.get('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL',timeout=30).json()
df=pd.DataFrame(r); df['TradeValue']=pd.to_numeric(df.TradeValue,errors='coerce')
df=df[df.Code.str.fullmatch(r'[1-9]\d{3}')]
u=df.sort_values('TradeValue',ascending=False).head(200).Code.tolist()
json.dump(u,open('data/universe.json','w'))
def yh(sym):
    r=requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',params={'range':'15y','interval':'1d'},headers=H,timeout=30).json()['chart']['result'][0]
    q=r['indicators']['quote'][0]
    d=pd.DataFrame({k:q[k] for k in ['open','high','low','close','volume']},index=pd.to_datetime(r['timestamp'],unit='s').tz_localize('UTC').tz_convert('Asia/Taipei').tz_localize(None).normalize())
    d['adj']=r['indicators']['adjclose'][0]['adjclose']; return d.dropna()
bad=[]
for c in u+['0050']:
    if os.path.exists(f'data/{c}.csv'): continue
    try: yh(c+'.TW').to_csv(f'data/{c}.csv')
    except Exception as e: bad.append(c); time.sleep(1)
print(len(u),'bad',bad)
