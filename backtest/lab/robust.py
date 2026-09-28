import common as C, engine as E, strategies as S, pandas as pd, numpy as np
pd.set_option('display.width',250)
BASE=dict(min_body=0.1,trend='ema20_50',min_risk=5,stop_atr=0.1,rr=10,be_at=2)
RISK=dict(risk_usd=150,flat_mod=955,max_trades=1)
def go(tf=5, risk=RISK, **kw):
    b,m=C.data(tf); p=dict(BASE); p.update(kw)
    return E.run(b,m,lambda: S.FirstCandle(**p),E.Risk(**risk))
def row(tr,**lab):
    i,o=C.split(tr); si,so=E.stats(i),E.stats(o)
    return dict(**lab,IS_n=si['n'],IS_PF=si['PF'],IS_R=si['avgR'],OOS_n=so['n'],OOS_PF=so['PF'],OOS_R=so['avgR'],net=E.stats(tr)['net$'],dd=E.stats(tr)['maxDD$'])
if __name__=='__main__':
    R=[]
    for mb in (0.05,0.075,0.1,0.125,0.15,0.2): R.append(row(go(min_body=mb),param='min_body',val=mb))
    for tn in ('none','ema9_21','ema20_50','ema200','vwap','ema20_50_200'): R.append(row(go(trend=tn),param='trend',val=tn))
    for sa in (0.08,0.09,0.1,0.11,0.12,0.13): R.append(row(go(stop_atr=sa),param='stop_atr',val=sa))
    for rr in (5,6,8,10,15,50): R.append(row(go(rr=rr),param='rr',val=rr))
    for be in (0,1.5,2,2.5,3): R.append(row(go(be_at=be),param='be_at',val=be))
    print(pd.DataFrame(R).to_string())
    tr=go()
    d=E.trades_df(tr)
    print('\nlong/short'); print(d.groupby('side').apply(lambda x: pd.Series(E.stats([t for t in tr if t.side==x.name]))).T.to_string())
    print('\nper year'); print(E.by_period(tr).to_string())
    print('\nhalf-years'); print(E.by_period(tr,'H').to_string())
    # slippage x2
    E.SLIP=0.5; tr2=go(); print('\nslippage 2 ticks:', E.stats(tr2)); E.SLIP=0.25
    # M3 chart variants
    for orb in (3,6,9): print('M3 orb',orb, row(go(tf=3,orb=orb),x=1))
    # Monte Carlo of trade order: DD distribution (in $ at 150 risk)
    p=np.array([t.pnl for t in tr]); rng=np.random.default_rng(1)
    dds=[];loss_streak=[]
    for _ in range(5000):
        x=rng.choice(p,len(p),replace=True); eq=np.concatenate([[0],x.cumsum()]); dds.append((np.maximum.accumulate(eq)-eq).max())
        s=0;mx=0
        for v in x:
            s=s+1 if v<0 else 0; mx=max(mx,s)
        loss_streak.append(mx)
    print('\nMC maxDD$ pct 50/90/95/99:',np.percentile(dds,[50,90,95,99]).round(), ' loss streak 50/95:',np.percentile(loss_streak,[50,95]))
    s=0;mx=0
    for v in p:
        s=s+1 if v<0 else 0; mx=max(mx,s)
    print('actual longest losing streak', mx)
