"""Rejeu des 6 écoles du carnet armé (A,B,C,D,R,X) sur l'historique long Binance Vision (1d, 2019-2026).
Mêmes règles que bot.py/engine.py; ici sans event_gate (on mesure la règle, pas le départ à plat). Frais 0,15 %."""
import gzip, csv, sys, json, numpy as np
from numpy.lib.stride_tricks import sliding_window_view
H=__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)),"..","history")+"/"
def load(s):
    d={}
    with gzip.open(H+f"{s}USDT_1d.csv.gz","rt") as f:
        for r in csv.DictReader(f): d[int(r["open_time_ms"])//86400000]=(float(r["high"]),float(r["low"]),float(r["close"]))
    return d
raw={k:load(k) for k in ["BTC","ETH","XRP","BNB","SOL"]}
days=sorted(set(raw["BTC"])&set(raw["ETH"]))  # base commune BTC/ETH
def arr(k,days):
    return {x:np.array([raw[k][d][i] if d in raw[k] else np.nan for d in days]) for x,i in zip("hlc",range(3))}
def ema(x,n):
    o=np.zeros(len(x));a=2/(n+1);o[0]=x[0]
    for i in range(1,len(x)):o[i]=a*x[i]+(1-a)*o[i-1]
    return o
def sma(x,n):
    o=np.full(len(x),np.nan)
    for i in range(n-1,len(x)):o[i]=x[i-n+1:i+1].mean()
    return o
def atr(h,l,c,n=14):
    tr=np.zeros(len(c));tr[0]=h[0]-l[0]
    for i in range(1,len(c)):tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    o=np.full(len(c),np.nan)
    for i in range(n-1,len(c)):o[i]=tr[i-n+1:i+1].mean()
    return o
def ret(c,k):
    o=np.full(len(c),np.nan);o[k:]=c[k:]/c[:-k]-1;return o
def rstd(x,n):
    o=np.full(len(x),np.nan)
    for i in range(n,len(x)):o[i]=x[i-n+1:i+1].std()
    return o
def dret(c):
    r=np.zeros(len(c));r[1:]=c[1:]/c[:-1]-1;return r
def vscale(c,tv=0.02):
    sd=rstd(dret(c),20);return np.where(np.isnan(sd)|(sd<=0),0.0,np.minimum(1.0,tv/np.where(sd>0,sd,1.0)))
def donch(h,l,c,chans=(20,30)):
    n=len(c);out=np.zeros(n)
    for L in chans:
        s=np.zeros(n)
        hi=sliding_window_view(h,L).max(axis=1)[:n-L];lo=sliding_window_view(l,L).min(axis=1)[:n-L]
        s[L:]=np.where(c[L:]>(hi+lo)/2,1.0,-1.0);out+=s
    return out/len(chans)
def sigA(h,l,c,start):
    e10,a14=ema(c,10),atr(h,l,c);sd=rstd(dret(c),30);r7=ret(c,7)
    n=len(c);out=np.zeros(n);side=0;hi=0;age=0;prev=False
    for i in range(n):
        ok=not(np.isnan(a14[i]) or np.isnan(sd[i]) or np.isnan(r7[i]))
        cond=bool(ok and c[i]>e10[i]+1.5*a14[i] and r7[i]>1.5*sd[i]*np.sqrt(7))
        if i>start:
            if side==1:
                age+=1;hi=max(hi,c[i])
                if c[i]<e10[i] or c[i]<hi-5*a14[i] or age>=30:side=0
            if side==0 and cond and not prev:side=1;hi=c[i];age=0
        out[i]=1.0 if(side==1 and i>start) else 0.0;prev=cond
    return out
def sigB(c):
    e10,s30=ema(c,10),sma(c,30);s=np.zeros(len(c))
    for i in range(7,len(c)):
        if np.isnan(s30[i]):continue
        s[i]=1.0 if(c[i]>s30[i] and c[i]>e10[i] and np.any(c[i-7:i]<e10[i-7:i])) else 0.0
    return s
def sigD(c):
    r7,r14,r28=ret(c,7),ret(c,14),ret(c,28)
    ok=~(np.isnan(r7)|np.isnan(r14)|np.isnan(r28));return np.where(ok&(r7>0)&(r14>0)&(r28>0),1.0,0.0)
def sigR(c,start):
    m,s=sma(c,20),rstd(c,20);n=len(c);out=np.zeros(n);side=0
    for i in range(start+1,n):
        if np.isnan(m[i]) or s[i]<=0:continue
        z=(c[i]-m[i])/s[i]
        if side==1 and z>0:side=0
        if side==0 and z<-2:side=1
        out[i]=1.0 if side else 0.0
    return out
def run(c,t,cap=100.0,fee=0.0015,thr=0.15,cb=-0.15,pause=168):
    n=len(c);eq=np.empty(n);eq[0]=cap;p,peak,wait,tr=0.0,cap,0,0
    for i in range(n-1):
        e=eq[i]
        if wait>0:wait-=1;tgt=0.0
        else:tgt=0.0 if np.isnan(t[i]) else t[i]
        if abs(tgt-p)>thr or np.sign(tgt)!=np.sign(p):
            e-=e*fee*abs(tgt-p)
            if p==0 and tgt!=0:tr+=1
            p=tgt
        e*=1+p*(c[i+1]/c[i]-1);eq[i+1]=e;peak=max(peak,e)
        if e/peak-1<=cb and wait==0 and p!=0:
            e-=e*fee*abs(p);eq[i+1]=e;p,wait,peak=0.0,pause,e
    return eq,tr
def mdd(e):return float((e/np.maximum.accumulate(e)-1).min())
def yr(d):return 1970+int(d*86400/31556952)  # approx
res=[];W={}
dsig={}
for k in ["BTC","ETH"]:
    a=arr(k,days);dsig[k]=donch(a["h"],a["l"],a["c"])
cons=(dsig["BTC"]+dsig["ETH"])/2
for k in ["BTC","ETH","XRP","BNB","SOL"]:
    kd=[d for d in days if d in raw[k]]
    ix=np.array([days.index(d) for d in kd]);a=arr(k,kd);h,l,c=a["h"],a["l"],a["c"]
    sc=vscale(c);w=1.0 if k in("BTC","ETH") else 0.5
    own=donch(h,l,c);sigC=np.maximum(w*own+(1-w)*cons[ix],0.0)
    r14={kk:ret(arr(kk,kd)["c"],14) for kk in ["BTC","ETH","XRP","BNB","SOL"] if all(d in raw[kk] for d in kd)}
    names=list(r14);M=np.array([r14[n] for n in names]).T
    X=np.zeros(len(c))
    for i in range(len(c)):
        if not np.isnan(M[i]).any():X[i]=1.0 if(names[int(np.argmax(M[i]))]==k and M[i].max()>0) else 0.0
    S={"A":sigA(h,l,c,60),"B":sigB(c),"C":sigC,"D":sigD(c),"R":sigR(c,60),"X":X}
    years=np.array([yr(d) for d in kd])
    hold_t=np.ones(len(c));hold_t[:60]=0
    for s,t in S.items():
        tgt=t*sc;eq,tr=run(c,tgt)
        res.append(dict(acc=f"{s}-{k}",first=str(np.datetime64(kd[60],"D")),total=eq[-1]/100-1,mdd=mdd(eq),trades=tr,
            hold=c[-1]/c[60]-1,exp=float(np.mean(tgt[60:]>0))))
        W[f"{s}-{k}"]=dict(eq=eq,years=years,tgt=tgt)
    # benchmark BTC vol-targeted 50 %
    if k=="BTC":
        tgt=np.where(np.arange(len(c))>=60,0.5*sc,0.0);eq,_=run(c,tgt)
        res.append(dict(acc="BENCH-BTC-50%vol",first=str(np.datetime64(kd[60],"D")),total=eq[-1]/100-1,mdd=mdd(eq),trades=0,hold=c[-1]/c[60]-1,exp=float(np.mean(tgt[60:]>0))))
        W["BENCH-BTC-50%vol"]=dict(eq=eq,years=years,tgt=tgt)
# par année
out=[]
for a,w in W.items():
    eq,y=w["eq"],w["years"];row=[a]
    for Y in range(2019,2027):
        m=np.where(y==Y)[0]
        row.append(f"{eq[m[-1]]/eq[max(m[0]-1,0)]-1:+.1%}" if len(m)>20 else "")
    out.append(row)
import csv as C
with open("rejeu-par-annee.csv","w",newline="") as f:
    wr=C.writer(f);wr.writerow(["compte"]+[str(y) for y in range(2019,2027)]);wr.writerows(out)
with open("rejeu-total.csv","w",newline="") as f:
    wr=C.DictWriter(f,fieldnames=list(res[0]));wr.writeheader()
    for r in res:wr.writerow({k:(f"{v:.4f}" if isinstance(v,float) else v) for k,v in r.items()})
for r in res:print(f"{r['acc']:18s} {r['first']} total {r['total']:+8.1%} mdd {r['mdd']:6.1%} entrées {r['trades']:3d} exposé {r['exp']:.0%} | achat-conservation {r['hold']:+9.1%}")
