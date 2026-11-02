import numpy as np, pandas as pd
def synth_panel(n_stocks=300, start="2012-01-02", end="2016-12-30", seed=0):
    rng=np.random.default_rng(seed)
    idx=pd.bdate_range(start,end); T=len(idx)
    mkt=rng.normal(0.0004,0.01,T)
    r=mkt[:,None]*rng.uniform(0.5,1.5,n_stocks)+rng.normal(0,0.02,(T,n_stocks))
    close=pd.DataFrame(50*np.cumprod(1+r,axis=0),index=idx,columns=[str(1101+i) for i in range(n_stocks)])
    open_=close.shift(1)*(1+rng.normal(0,0.005,(T,n_stocks)));open_.iloc[0]=close.iloc[0]
    close.iloc[600:,0]=np.nan; open_.iloc[600:,0]=np.nan  # delisted
    val=pd.DataFrame(rng.uniform(5e7,2e9,(T,n_stocks)),index=idx,columns=close.columns)
    b=pd.Series(50*np.cumprod(1+mkt),index=idx); bo=b.shift(1).fillna(50)
    months=pd.date_range("2011-01-01",end,freq="MS")
    rev=pd.DataFrame(rng.lognormal(10,0.3,(len(months),n_stocks)),index=months,columns=close.columns)
    return {"close":close,"open":open_,"volume_value":val,"benchmark_close":b,"benchmark_open":bo,"revenue":rev}
