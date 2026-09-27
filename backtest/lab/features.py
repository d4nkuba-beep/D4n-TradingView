import numpy as np, pandas as pd, common as C, engine as E, strategies as S
def fc_features(tf=5, **kw):
    b,m=C.data(tf)
    cc=E.cached(b,m); lv=cc['levels']; a=cc['arr']
    tr=E.run(b,m,lambda: S.FirstCandle(**kw),E.Risk(flat_mod=kw.pop('flat',955) if 'flat' in kw else 955,max_trades=1))
    rows=[]
    bt=b.t.to_numpy(); bdate=b.date.to_numpy()
    for t in tr:
        L=lv[t.date]; d=L['datr']
        i=np.searchsorted(bt, int(t.entry_time.timestamp()) - 1)-1   # signal bar = bar before entry
        j0=i  # first candle (5m) index
        o,h,l,c=a['o'][j0],a['h'][j0],a['l'][j0],a['c'][j0]
        s=t.side
        rows.append(dict(date=t.date,yr=t.date.year,side=s,r=t.r,pnl=t.pnl,
            body=abs(c-o)/d, rng=(h-l)/d, clv=((c-l)-(h-c))/max(h-l,1e-9)*s,
            gap=(o-L['pdc'])/d*s, onpos=((o-L['onl'])/max(L['onh']-L['onl'],1e-9)-0.5)*s,
            above_pdh=float((c>L['pdh']) if s>0 else (c<L['pdl'])),
            trend=np.sign(a['ema20'][i]-a['ema50'][i])*s, t200=np.sign(c-a['ema200'][i])*s,
            rsi=(a['rsi'][i]-50)*s, datr=d, dow=pd.Timestamp(t.date).dayofweek,
            onrng=(L['onh']-L['onl'])/d))
    return pd.DataFrame(rows)
if __name__=='__main__':
    F=fc_features(stop='atr',stop_atr=0.1,rr=10,min_risk=5)
    F.to_pickle('/tmp/claude-0/fc.pkl')
    F['per']=np.where(F.yr<=2024,'IS','OOS')
    for col in ['body','rng','clv','gap','onpos','above_pdh','trend','t200','rsi','datr','dow','onrng']:
        q=F[col] if col in('above_pdh','trend','t200','dow') else pd.qcut(F[col],4,duplicates='drop')
        t=F.groupby([q,'per']).r.agg(['mean','count']).unstack()
        print('==',col); print(t.round(3).to_string())
