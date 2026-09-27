import numpy as np, pandas as pd, common as C, engine as E
b,m=C.data(5)
lv=E.day_levels(b)
# daily ATR from RTH ranges
rows=[]
g=b[(b['mod']>=570)&(b['mod']<960)].groupby('date')
for d,x in g:
    if d not in lv or len(x)<70: continue
    L=lv[d]; o=x.o.iloc[0]
    def px(mm): 
        y=x[x['mod']<mm]; return y.c.iloc[-1] if len(y) else np.nan
    rows.append(dict(date=d,o=o,pdc=L['pdc'],pdh=L['pdh'],pdl=L['pdl'],onh=L['onh'],onl=L['onl'],
        c935=px(575),c945=px(585),c1000=px(600),c1030=px(630),c1100=px(660),c1200=px(720),c1555=x.c.iloc[-1],
        h=x.h.max(),l=x.l.min(),e20=x.ema20.iloc[0],e50=x.ema50.iloc[0],e200=x.ema200.iloc[0]))
D=pd.DataFrame(rows); D['rng']=D.h-D.l; D['atr']=D.rng.rolling(14).mean().shift()
D['gap']=(D.o-D.pdc)/D.atr
D['r5']=(D.c935-D.o)/D.atr; D['r15']=(D.c945-D.o)/D.atr; D['r30']=(D.c1000-D.o)/D.atr
D['fwd5_12']=(D.c1200-D.c935)/D.atr; D['fwd15_12']=(D.c1200-D.c945)/D.atr; D['fwd30_12']=(D.c1200-D.c1000)/D.atr
D['fwd30_c']=(D.c1555-D.c1000)/D.atr; D['fwd15_c']=(D.c1555-D.c945)/D.atr
D['onpos']=(D.o-D.onl)/(D.onh-D.onl)
D['trend']=np.sign(D.e20-D.e50)
D['yr']=pd.to_datetime(D.date).dt.year
D=D.dropna()
D.to_pickle('/tmp/claude-0/daily.pkl')
for yr,x in D.groupby('yr'):
    print(yr, len(x), 'corr r5->fwd5_12 %.3f r15->fwd15_12 %.3f r30->fwd30_12 %.3f r30->close %.3f gap->fwd15_12 %.3f gap->r15 %.3f trend->fwd15_12 %.3f' % (
      x.r5.corr(x.fwd5_12), x.r15.corr(x.fwd15_12), x.r30.corr(x.fwd30_12), x.r30.corr(x.fwd30_c), x.gap.corr(x.fwd15_12), x.gap.corr(x.r15), x.trend.corr(x.fwd15_12)))
