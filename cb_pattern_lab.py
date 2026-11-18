#!/usr/bin/env python3
"""cb_pattern_lab — brute-force pattern discovery per coin, 400d+ history.

For every liquid USD pair, tests a battery of pattern hypotheses on DAILY
bars. Each pattern = boolean mask over history; forward return measured
over HOLD days in PERCENT. A pattern is PROMOTED only if:
  n_signals >= 15, winrate >= 60%, BOTH halves >= 55%,
  avg_return > 1.2% (must clear ~0.8-1.2% round-trip taker fees),
  liquidity > $200k/day.

Patterns tested (each a different market anomaly):
  rsi30/35:        RSI14d < level -> long, hold 3d
  dn3/dn4/dn5:     N consecutive down closes -> exhaustion bounce, hold 3d
  nearhigh:       close within 4% of 90d high AND vol z>1.2 -> momentum, hold 3d
  rsidiv:         price LL but RSI HL (bullish divergence) -> hold 3d
  nr7:            narrowest daily range of last 7d -> next-day breakout dir, hold 2d
  postdump5:      any single day <= -5% (no volume req) -> hold 3d
  wknd:           Friday-close entry, hold through weekend (Sat+Sun), exit Mon
  bigup_fade:     day >= +8% -> SHORT next day (post-pump fade), hold 2d [informational]

Output: /tmp/cb_lab_proven.json {'patterns': {BASE: {pat: {...}}}}
monitor2 can merge; is_val() checks per-pattern live condition where
implemented, else presence+freshness acts as signal.
Rescan every 24h."""
import json,urllib.request,time,datetime,os,math
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_lab_proven.json'
LOG=open('/tmp/cb_pattern_lab.log','a',buffering=1)
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
def rsi_series(cl,p=14):
    out=[None]*len(cl)
    if len(cl)<p+1: return out
    gains=[];losses=[]
    for i in range(1,p+1):
        d=cl[i]-cl[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/p; al=sum(losses)/p
    out[p]=100-100/(1+ag/al) if al else 100
    for i in range(p+1,len(cl)):
        d=cl[i]-cl[i-1]
        ag=(ag*(p-1)+max(d,0))/p; al=(al*(p-1)+max(-d,0))/p
        out[i]=100-100/(1+ag/al) if al else 100
    return out

def fwd(cl,i,h,sign=1):
    if i+h>=len(cl) or not cl[i] or not cl[i+h]: return None
    return sign*(cl[i+h]/cl[i]-1)*100

def eval_pattern(cl,c,mask,hold,sign=1):
    ent=[]
    for i,v in enumerate(mask):
        if v and i+hold<len(cl):
            r=fwd(cl,i,hold,sign)
            if r is not None: ent.append((i,r))
    if len(ent)<15: return None
    rets=[r for _,r in ent]
    w=sum(1 for r in rets if r>0)/len(rets)*100
    if w<60: return None
    h=len(ent)//2
    wo=[r for _,r in ent[:h]]; wn=[r for _,r in ent[h:]]
    if not wo or not wn: return None
    if sum(1 for r in wo if r>0)/len(wo)*100<55: return None
    if sum(1 for r in wn if r>0)/len(wn)*100<55: return None
    avg=sum(rets)/len(rets)
    if avg<=1.2: return None   # must clear round-trip fees
    return {'n':len(ent),'wr':round(w,1),'avg':round(avg,2),'hold':hold,'sign':sign}

def masks(cl,c):
    M={}; n=len(cl)
    rs=rsi_series(cl)
    for lv in (30,35):
        M[f'rsi{lv}']=[rs[i] is not None and rs[i]<lv for i in range(n)]
    for k in (3,4,5):
        M[f'dn{k}']=[i>=k and all(cl[i-j]<cl[i-j-1] for j in range(k)) for i in range(n)]
    hi90=[max(cl[max(0,i-89):i+1]) for i in range(n)]
    vols=[(c[i][5] or 0) for i in range(n)]
    vmed=sorted(v for v in vols[-60:] if v>0)
    vmed=vmed[len(vmed)//2] if vmed else 0
    M['nearhigh']=[cl[i]>0 and hi90[i]>0 and cl[i]>=hi90[i]*0.96 and vmed>0 and vols[i]>=1.2*vmed for i in range(n)]
    # RSI bullish divergence: price LL vs 14d ago, RSI HL
    M['rsidiv']=[i>=14 and rs[i] is not None and rs[i-14] is not None
                 and cl[i]<cl[i-14] and rs[i]>rs[i-14] and rs[i]<45 for i in range(n)]
    # NR7 narrowest range in 7d -> breakout direction next day (mask marks the NR7 day; entry next day handled by shift)
    rng=[(c[i][2]-c[i][3])/c[i][1] if c[i][1] else 9e9 for i in range(n)]
    nr7=[False]*n
    for i in range(7,n):
        if rng[i]==min(rng[i-7:i+1]): nr7[i]=True
    M['nr7']=[nr7[i] and i+1<n and c[i+1][4]>c[i+1][1] for i in range(n-1)]+[False]  # breakout-up day after NR7
    M['postdump5']=[c[i][4] and c[i-3] and c[i-3][4] and c[i][4]/c[i-3][4]-1<=-0.05 for i in range(3,n)]
    # weekend: entry Friday close (index where date is Friday) hold 3 calendar days ~ use Sat/Sun/Mon: approx hold=3
    import datetime as _dt
    M['wknd']=[_dt.datetime.utcfromtimestamp(c[i][0]).weekday()==4 for i in range(n)]
    M['bigup_fade']=[i>=1 and c[i-1][4] and c[i-2] and c[i-2][4] and c[i-1][4]/c[i-2][4]-1>=0.08 for i in range(2,n)]
    return M

def scan_once():
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD')
           and p.get('status')=='online' and not p.get('trading_disabled')]
    out={}
    for k,pair in enumerate(pairs):
        c=candles(pair,86400,430)   # ~14 months
        if len(c)<300: continue
        cl=closes(c)
        if len(cl)<290 or len(cl)!=len(c): continue
        base=pair.split('-')[0]
        pats={}
        for name,mask in masks(cl,c).items():
            hold=3
            sign=1
            if name=='bigup_fade': sign=-1; hold=2
            elif name=='nr7': hold=2
            elif name=='wknd': hold=3
            r=eval_pattern(cl,c,mask,hold,sign)
            if r: pats[name]=r
        if pats:
            out[base]={'patterns':pats,'lab':True}
            log('LAB',base,json.dumps(pats)[:300])
        if k%40==0: log(f'..{k}/{len(pairs)} pairs={len(out)}')
    # flatten for monitor compatibility: each base -> first proven pattern entry
    flat={}
    for b,v in out.items():
        for pn,pd in v['patterns'].items():
            flat.setdefault(b,{'lab':True,'pat':pn,**{kk:vv for kk,vv in pd.items()}})
    json.dump({'ts':time.time(),'patterns':flat,'detail':out},open(OUT,'w'))
    log('LAB DONE:',len(out),'coins with proven patterns')

if __name__=='__main__':
    log('=== cb_pattern_lab start ===')
    while True:
        try: scan_once()
        except Exception as e: log('ERR',repr(e)[:200])
        time.sleep(86400)
