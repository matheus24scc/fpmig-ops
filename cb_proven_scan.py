#!/usr/bin/env python3
"""Auto-expanding pattern discovery: scans ALL Coinbase USD products,
backtests daily-RSI variants, applies the 3 user filters
(winrate>=75%, stable old/new halves, liquidity>$200k/d),
and writes /tmp/cb_proven_extra.json which cb_monitor2 merges
into PROVEN_PATTERNS. Re-scans every 24h."""
import json,urllib.request,time,datetime,os
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_proven_extra.json'
LOG=open('/tmp/cb_proven_scan.log','a',buffering=1)
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
def rsi(cl,p=14):
    g=[];l=[]
    for j in range(1,len(cl)):
        ch=cl[j]-cl[j-1];g.append(max(ch,0));l.append(max(-ch,0))
    if len(g)<p: return None
    ag=sum(g[-p:])/p;al=sum(l[-p:])/p
    return 100-100/(1+ag/al) if al else 100

# variants worth auto-promoting: (name, rsi_threshold, two_down, hold_days, hook)
VARIANTS=[('rsi30',30,False,2,False),('rsi25',25,False,2,False),('rsi20',20,False,2,False),
          ('rsi35',35,False,2,False),('rsi30_2down',30,True,2,False),('rsi30_3d',30,False,3,False),
          ('rsi30_hook',30,False,2,True),('rsi25_hook',25,False,2,True),
          ('rsi30_4d',30,False,4,False),('rsi25_3d',25,False,3,False)]
BASE_OK={'ALGO','ZEC','LIGHTER','TON'}  # already proven — skip re-adding

def liquidity_ok(pair):
    try:
        t=get(f'https://api.exchange.coinbase.com/products/{pair}-USD/ticker')
        return t and float(t['price'])*float(t['volume'])>200000
    except Exception: return False

def scan_once():
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD') and p.get('status')=='online' and not p.get('trading_disabled')]
    found={}
    for k,pair in enumerate(pairs):
        base=pair.split('-')[0]
        if base in BASE_OK: continue
        c=candles(pair,86400,400)
        if not c or len(c)<260: continue
        cl=[x[4] for x in c];n=len(cl)
        rs=[None]*n
        for i in range(15,n): rs[i]=rsi(cl[:i+1])
        for name,th,two_down,hold,hook in VARIANTS:
            ent=[]
            for i in range(21,n-hold-1):
                if rs[i] is None or rs[i]>=th: continue
                if two_down and not (i>=2 and cl[i]<cl[i-1]<cl[i-2]): continue
                if hook and not (rs[i-1] is not None and rs[i]>rs[i-1]): continue
                ent.append(i)
            if len(ent)<15: continue
            v=[(cl[i+hold]/cl[i]-1)*100 for i in ent]
            w=sum(1 for x in v if x>0)/len(v)*100
            if w<75: continue
            # stability: both halves must win >=60%
            h=len(ent)//2
            wo=[(cl[i+hold]/cl[i]-1)*100 for i in ent[:h]]
            vn_=[(cl[i+hold]/cl[i]-1)*100 for i in ent[h:]]
            wold=sum(1 for x in wo if x>0)/len(wo)*100 if wo else 0
            wnew=sum(1 for x in vn_ if x>0)/len(vn_)*100 if vn_ else 0
            if wold<60 or wnew<60: continue
            if not liquidity_ok(pair): continue
            spec={'rsi':th}
            if two_down: spec['two_down']=True
            if hook: spec['hook']=True
            # keep best variant per coin (highest winrate)
            cur=found.get(base)
            if not cur or w>(cur.get('_w',0)):
                spec['_w']=round(w); spec['_n']=len(ent); spec['_hold']=hold; spec['_variant']=name
                found[base]=spec
        if k%60==0: log(f'..{k}/{len(pairs)} found={len(found)}')
    # write clean json (strip _ fields into meta)
    out={}
    meta={}
    for b,sp in found.items():
        meta[b]={'win':sp.pop('_w'),'n':sp.pop('_n'),'hold':sp.pop('_hold'),'variant':sp.pop('_variant')}
        out[b]=sp
    json.dump({'patterns':out,'meta':meta,'ts':time.time()},open(OUT,'w'))
    log(f'SCAN DONE: {len(out)} new proven patterns',json.dumps(meta)[:400])
    return out

while True:
    try: scan_once()
    except Exception as e: log('scan err',repr(e)[:200])
    # re-scan every 6h (daily candles update once/day, but new
    # listings/janelas deserve fresher discovery); heartbeat hourly
    for _ in range(6):
        time.sleep(3600); log('alive — next scan soon')
