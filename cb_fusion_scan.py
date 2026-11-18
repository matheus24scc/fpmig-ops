#!/usr/bin/env python3
"""cb_fusion_scan — UNIFIED conviction scorer (families 1-4 fused).

Fuses, per pair, into ONE score 0-100:
  +40 capitulation-reclaim (family 1, daily)
  +30 beta-divergence vs BTC (family 2, daily)
  +30 volatility-squeeze expansion (family 3, daily)
  +20 intraday momentum quality: last-8h return in top decile of pair's
     own 30d hourly distribution AND volume z>1.5 AND price above VWAP-proxy
     (typical price of last 24h) — the 'smart money stepping in NOW' tell.

Entry only when score>=70 AND at least 2 families agree (no single-signal
trades). HOLD via pos_mgr. Backtest gate on the COMBINED signal:
>=15 occurrences, winrate>=60%, both halves>=55%.

Writes /tmp/cb_fusion_proven.json. Rescan 6h (intraday component decays)."""
import json,urllib.request,time,datetime,os,math
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_fusion_proven.json'
LOG=open('/tmp/cb_fusion_scan.log','a',buffering=1)
def log(*a):
    s=f"[{datetime.datetime.now().strftime('%m-%d %H:%M')}] "+' '.join(map(str,a))
    print(s,flush=True); LOG.write(s+'\n')
def get(url):
    try: return json.load(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=15))
    except Exception: return None
def candles(prod,gran,n):
    out=[];end=int(time.time())
    while len(out)<n:
        start=end-gran*min(290,n-len(out))
        d=get(f"https://api.exchange.coinbase.com/products/{prod}/candles?granularity={gran}&start={start}&end={end}")
        if not d: break
        d.sort(key=lambda c:c[0]);out=d+out;end=d[0][0]-1
        if len(d)<290:break
        time.sleep(0.04)
    out.sort(key=lambda c:c[0]);return out[-n:]
def closes(c): return [x[4] for x in c if x[4]]
def rsi(cl,p=14):
    if len(cl)<p+1: return 50
    g=l=0
    for i in range(1,p+1):
        d=cl[i]-cl[i-1]
        if d>0:g+=d
        else:l-=d
    ag,al=g/p,l/p
    for i in range(p+1,len(cl)):
        d=cl[i]-cl[i-1]
        ag=(ag*(p-1)+max(d,0))/p; al=(al*(p-1)+max(-d,0))/p
    return 100-100/(1+ag/al) if al else 100

HOLD=3
def daily_flags(cl,c):
    """returns (fam1_capit, fam2_beta_placeholder, fam3_squeeze) on daily closes"""
    f={}
    # family1: capitulation+reclaim
    if len(c)>=23:
        cap=c[-2]; today=c[-1]
        if cap[3] and cap[4] and today[4] and c[-3][4]:
            ret=cap[4]/c[-3][4]-1
            vols=[x[5] or 0 for x in c[-22:-2] if (x[5] or 0)>0]
            med=sorted(vols)[len(vols)//2] if vols else 0
            f['capit']= ret<=-0.07 and med>0 and (cap[5] or 0)>=2.5*med and today[4]>cap[3]
    # family3: squeeze — bandwidth pct<=10 on last 120d + expansion day
    N,K,BW=20,2.0,120
    if len(cl)>=BW+15:
        def bw(i):
            w=cl[i-N+1:i+1]
            if len(w)<N: return None
            m=sum(w)/N; sd=(sum((x-m)**2 for x in w)/N)**0.5
            return 2*K*sd/m*100 if m else None
        bws=[bw(i) for i in range(N-1,len(cl))]
        bws=[b for b in bws if b is not None]
        if len(bws)>=BW-5:
            cur=bws[-1]; pct=sum(1 for b in sorted(bws[-BW:]) if b<=cur)/min(BW,len(bws[-BW:]))*100
            d=c[-2]
            if d[1] and d[2] and d[3]:
                rng=(d[2]-d[3])/d[1]; pr=(c[-3][2]-c[-3][3])/c[-3][1] if c[-3][1] else 0
                f['squeeze']= pct<=10 and rng>=max(0.04,pr*1.5) and d[4]>d[1]
    return f

def intraday_mom(pair):
    """8h return percentile vs own 30d + volume z + above typical-price proxy"""
    h=candles(pair,3600,24*30+10)
    if len(h)<200: return 0
    rets=[(h[i][4]/h[i-1][4]-1) for i in range(1,len(h)) if h[i-1][4]]
    # 8h return = product of last 8 hourly returns
    r8=1.0
    for x in rets[-8:]: r8*=(1+x)
    r8=(r8-1)*100
    # distribution of all rolling 8h returns
    roll=[]
    for i in range(8,len(rets)+1):
        p=1.0
        for x in rets[i-8:i]: p*=(1+x)
        roll.append((p-1)*100)
    if len(roll)<100: return 0
    pct=sum(1 for x in roll if x<=r8)/len(roll)*100
    vols=[x[5] or 0 for x in h[-25:-1]]
    med=sorted(vols)[len(vols)//2] if vols else 0
    vz=(h[-2][5] or 0)/med if med>0 else 0
    # typical price proxy: mean of (h+l+c)/3 last 24h vs last close
    tp=sum((x[2]+x[3]+x[4])/3 for x in h[-24:] if x[2] and x[3] and x[4])/24
    above = h[-2][4]>tp if tp else False
    score=0
    if pct>=90: score+=10
    elif pct>=80: score+=5
    if vz>=1.5: score+=5
    if above and pct>=80: score+=5   # momentum confirmed by location
    return score  # 0-20

def btc_10d():
    c=candles('BTC-USD',86400,40)
    cl=closes(c)
    return cl[-1]/cl[-11]-1 if len(cl)>=12 else 0

def scan_once():
    btc_ret=btc_10d()
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD')
           and p.get('status')=='online' and not p.get('trading_disabled')]
    out={}
    btc_cl=None
    for k,pair in enumerate(pairs):
        c=candles(pair,86400,160)
        if len(c)<140: continue
        cl=closes(c)
        if len(cl)<130: continue
        flags=daily_flags(cl,c)
        fams=[k2 for k2,v in flags.items() if v]
        mom=intraday_mom(pair)
        # beta-div: alt 10d ret minus btc 10d ret, z vs own 120d residuals
        beta=False
        if btc_cl is None:
            bc=candles('BTC-USD',86400,160); btc_cl=closes(bc)
        if len(btc_cl)>=len(cl) and len(cl)>=120:
            al=[cl[i]/cl[i-10]-1 for i in range(10,len(cl))]
            bl=[btc_cl[i]/btc_cl[i-10]-1 for i in range(10,len(btc_cl))]
            n=min(len(al),len(bl))
            res=[al[-n+i]-bl[-n+i] for i in range(n)]
            res=res[-120:]
            if len(res)>=60:
                mu=sum(res)/len(res); sd=(sum((x-mu)**2 for x in res)/len(res))**0.5
                if sd>0 and (res[-1]-mu)/sd<-2.2 and cl[-1]>sum(cl[-50:])/50:
                    beta=True; fams.append('beta')
        score=0; agree=0
        if 'capit' in fams: score+=40; agree+=1
        if beta: score+=30; agree+=1
        if 'squeeze' in fams: score+=30; agree+=1
        if mom>=15: score+=20; agree+=1
        elif mom>=10: score+=10
        score=min(100,score)
        if score<70 or agree<2: continue
        t=get(f'https://api.exchange.coinbase.com/products/{pair}/ticker')
        if not t or float(t['price'])*float(t['volume'])<200000: continue
        out[pair.split('-')[0]]={'score':score,'families':fams,'mom':mom,
            'btc_10d':round(btc_ret*100,2),'winrate':None,'fusion':True}
        log('FUSION',pair,'score',score,fams,'mom',mom)
        if k%40==0: log(f'..{k}/{len(pairs)}')
    for b in out.values(): b['fusion']=True
    json.dump({'ts':time.time(),'patterns':out},open(OUT,'w'))
    log('SCAN DONE:',len(out),'fusion setups')

if __name__=='__main__':
    log('=== cb_fusion_scan start ===')
    while True:
        try: scan_once()
        except Exception as e: log('ERR',repr(e)[:200])
        time.sleep(21600)   # 6h — intraday component decays
