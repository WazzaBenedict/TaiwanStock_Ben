"""股癌兩條可檢驗說法的回測。成本=元大電子下單6折：買0.0855%，賣0.0855%+證交稅0.3%。
宇宙=今日成交值前200大（有倖存者偏誤，所以另列「同一宇宙等權買進持有」當對照）。"""
import pandas as pd, numpy as np, json, sys
u=json.load(open('data/universe.json')); FB=0.001425*0.6; FS=FB+0.003
px={}
for c in u+['0050']:
    d=pd.read_csv(f'data/{c}.csv',index_col=0,parse_dates=True); d=d[~d.index.duplicated()]
    f=d.adj/d.close; d['ao']=d.open*f; d['val']=d.close*d.volume; px[c]=d
cal=px['0050'].index
C=pd.DataFrame({c:px[c].adj for c in u}).reindex(cal); O=pd.DataFrame({c:px[c].ao for c in u}).reindex(cal)
R=pd.DataFrame({c:px[c].close for c in u}).reindex(cal); V=pd.DataFrame({c:px[c].val for c in u}).reindex(cal).rolling(20).mean()
Hh=pd.DataFrame({c:px[c].high for c in u}).reindex(cal)
def stats(eq):
    r=eq.pct_change().dropna(); y=len(r)/252
    return dict(cagr=round(((eq.iloc[-1]/eq.iloc[0])**(1/y)-1)*100,1),mdd=round((eq/eq.cummax()-1).min()*100,1),sharpe=round(r.mean()/r.std()*252**.5,2))
def sim(N=10,look=120,ndown=5,ma=None,start='2014-01-01'):
    hi=C.rolling(look).max(); newhigh=(C>=hi)&(V>=1e8)
    down=(R<R.shift(1)); dn=down.rolling(ndown).sum()==ndown
    below=(C<C.rolling(ma).mean()) if ma else None
    cash=1.0; pos={}; eq=[]; trades=[]; days=cal[cal>=start]
    for i,t in enumerate(days):
        k=cal.get_loc(t); y=cal[k-1]
        # 依昨日收盤訊號，今日開盤執行
        for c in list(pos):
            if dn.at[y,c] or (ma and below.at[y,c]):
                o=O.at[t,c]
                if np.isnan(o): continue
                sh,ep,ed=pos.pop(c); cash+=sh*o*(1-FS); trades.append((c,ed,t,o*(1-FS)/(ep*(1+FB))-1))
        free=N-len(pos)
        if free>0:
            cand=[c for c in u if newhigh.at[y,c] and c not in pos and not np.isnan(O.at[t,c]) and not dn.at[y,c]]
            cand.sort(key=lambda c:-V.at[y,c])
            tot=cash+sum(sh*C.at[y,c] for c,(sh,_,_) in pos.items())
            for c in cand[:free]:
                amt=min(tot/N,cash)
                if amt<=0: break
                o=O.at[t,c]; sh=amt/(o*(1+FB)); cash-=amt; pos[c]=(sh,o,t)
        eq.append(cash+sum(sh*(C.at[t,c] if not np.isnan(C.at[t,c]) else ep) for c,(sh,ep,_) in pos.items()))
    return pd.Series(eq,index=days),pd.DataFrame(trades,columns=['c','in','out','ret'])
b=px['0050'].adj
ew=(C.pct_change().fillna(0).where(C.notna().shift(1).fillna(False),0)); 
out={}
def rep(name,eq):
    out[name]={p:stats(eq[a:z]) for p,(a,z) in {'2014-2019':('2014','2019'),'2020-2026':('2020','2026'),'全期':('2014','2026')}.items()}
rep('0050買進持有',b['2014':])
ewr=C.pct_change().mean(axis=1).fillna(0); rep('同宇宙等權持有(偏誤對照)',(1+ewr['2014':]).cumprod())
for name,kw in {'創新高買+連5跌出':dict(),'創新高買+連5跌或破60日線出':dict(ma=60),'創新高買+連3跌出':dict(ndown=3),'60日新高+連5跌出':dict(look=60)}.items():
    eq,tr=sim(**kw); rep(name,eq); out[name]['交易']=dict(n=len(tr),win=round((tr.ret>0).mean()*100,1),avg=round(tr.ret.mean()*100,2),med=round(tr.ret.median()*100,2),hold=round((tr.out-tr['in']).dt.days.mean(),0))
# R2 漲停隔日
ev=[]
for c in u:
    d=px[c]; d=d['2015-07':]
    lu=(d.close/d.close.shift(1)>=1.095)&(d.close>=d.high*0.9999)&(d.val>=5e7)
    f=d.adj/d.close; ao=d.open*f
    for h,nm in [(1,'on'),]: pass
    e=pd.DataFrame({'on':ao.shift(-1)*(1-FS)/(d.adj*(1+FB))-1,'d1':d.adj.shift(-1)*(1-FS)/(d.adj*(1+FB))-1,'d5':d.adj.shift(-5)*(1-FS)/(d.adj*(1+FB))-1,'d20':d.adj.shift(-20)*(1-FS)/(d.adj*(1+FB))-1,
       'open_next_day':d.adj.shift(-1)*(1-FS)/(ao.shift(-1)*(1+FB))-1,
       'base5':d.adj.shift(-5)*(1-FS)/(d.adj*(1+FB))-1})
    ev.append(e[lu].assign(c=c)); 
ev=pd.concat(ev).dropna(); ev['y']=ev.index.year
allb=pd.concat([ (px[c].adj.shift(-5)*(1-FS)/(px[c].adj*(1+FB))-1)['2015-07':] for c in u]).dropna()
out['漲停收盤後(淨報酬%)']={'n':len(ev),'隔日開盤賣':round(ev.on.mean()*100,2),'隔日收盤賣':round(ev.d1.mean()*100,2),'隔日開盤才追、收盤賣':round(ev.open_next_day.mean()*100,2),'勝率_隔日開盤才追':round((ev.open_next_day>0).mean()*100,1),'5日後':round(ev.d5.mean()*100,2),'20日後':round(ev.d20.mean()*100,2),'任意日5日後(對照)':round(allb.mean()*100,2)}
out['漲停_分年_隔日開盤才追收盤賣']={int(y):[int(len(g)),round(g.open_next_day.mean()*100,2)] for y,g in ev.groupby('y')}
out['漲停_分年_收盤買隔日開盤賣']={int(y):round(g.on.mean()*100,2) for y,g in ev.groupby('y')}
json.dump(out,open('result.json','w'),ensure_ascii=False,indent=1); print(json.dumps(out,ensure_ascii=False,indent=1))
