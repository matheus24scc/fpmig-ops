#!/usr/bin/env python3
"""Volatility-squeeze expansion scanner — Toby Crabel style, family #3.

Signal: Bollinger(20,2) bandwidth in the lowest 10% of its 120d range
(volatility compressed to nothing) AND last completed day shows range
expansion closing in the upper/lower quartile of its range (the squeeze
is resolving). Direction = that day's close-vs-open sign. Entry next open,
hold HOLD days.

Backtest gates identical: winrate>=62%, both halves>=55%, >=15 signals,
liquidity>$200k/d. Writes /tmp/cb_squeeze_proven.json; monitor2 merges it
like the other families (presence = live qualified signal).
Re-scans every 24h."""
import json,urllib.request,time,datetime,os
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_squeeze_proven.json'
LOG=open('/tmp/cb_squeeze_scan.log','a',buffering=1)
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

N=20; K=2.0; BW_WIN=120; PCT=10; HOLD=3
def closes(c): return [x[4] for x in c if x[4]]
def bandwidth(cl,i):
    w=cl[i-N+1:i+1]
    if len(w)<N: return None
    m=sum(w)/N; var=sum((x-m)**2 for x in w)/N
    sd=var**0.5
    if m==0: return None
    return (2*K*sd)/m*100

def scan_once():
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD')
           and p.get('status')=='online' and not p.get('trading_disabled')]
    found={}
    for k,pair in enumerate(pairs):
        c=candles(pair,86400,BW_WIN+30)
        if len(c)<BW_WIN+15: continue
        cl=closes(c)
        # bandwidth series for last BW_WIN days
        bws=[bandwidth(cl,i) for i in range(N-1,len(cl))]
        bws=[b for b in bws if b is not None]
        if len(bws)<BW_WIN-5: continue
        cur=bws[-1]; hist=sorted(bws[-BW_WIN:])
        pct=sum(1 for b in hist if b<=cur)/len(hist)*100
        if pct>PCT: continue
        # last completed day: range expansion + directional close
        d=c[-2]
        if not (d[2] and d[3] and d[4] and d[1]): continue
        rng=(d[2]-d[3])/d[1] if d[1] else 0
        prev_rng=(c[-3][2]-c[-3][3])/c[-3][1] if c[-3][1] else 0
        if rng<max(0.04,prev_rng*1.5): continue   # real expansion
        direction=1 if d[4]>d[1] else -1
        if direction==-1: continue  # spot is long-only
        # backtest historical squeeze-expansion signals
        ent=[]
        for i in range(N+BW_WIN-10, len(cl)-HOLD-1):
            w=cl[i-N+1:i+1]; m=sum(w)/N
            var=sum((x-m)**2 for x in w)/N; sd=var**0.5
            if m==0 or sd==0: continue
            bw=2*K*sd/m*100
            hh=cl[max(0,i-BW_WIN):i]
            if len(hh)<60: continue
            # pct rank of bw within trailing window
            hhs=[]
            for j in range(max(N-1,i-BW_WIN+1),i+1):
                ww=cl[j-N+1:j+1]; mm=sum(ww)/N
                vv=sum((x-mm)**2 for x in ww)/N
                if mm==0 or vv==0: continue
                hhs.append(2*K*(vv**0.5)/mm*100)
            if len(hhs)<60: continue
            if sum(1 for b in hhs if b<=bw)/len(hhs)*100>PCT: continue
            cd=c[i]
            if not(cd[1] and cd[2] and cd[3] and cd[4]): continue
            dr=(cd[2]-cd[3])/cd[1] if cd[1] else 0
            pr=(c[i-1][2]-c[i-1][3])/c[i-1][1] if c[i-1][1] else 0
            if dr<max(0.04,pr*1.5): continue
            if cd[4]<=cd[1]: continue  # long-only backtest
            ent.append((cl[i+HOLD]/cl[i]-1)*100)
        if len(ent)<15: continue
        w=sum(1 for x in ent if x>0)/len(ent)*100
        if w<62: continue
        h=len(ent)//2; wo,wn=ent[:h],ent[h:]
        if not wo or not wn: continue
        if sum(1 for x in wo if x>0)/len(wo)*100<55: continue
        if sum(1 for x in wn if x>0)/len(wn)*100<55: continue
        t=get(f'https://api.exchange.coinbase.com/products/{pair}/ticker')
        if not t or float(t['price'])*float(t['volume'])<200000: continue
        found[pair.split('-')[0]]={'direction':'long',
            'bw_pct':round(pct,1),'winrate':round(w,1),'signals':len(ent),'hold':HOLD,'squeeze':True}
        log('FOUND',pair,json.dumps(found[pair.split('-')[0]]))
        if k%60==0: log(f'..{k}/{len(pairs)} found={len(found)}')
    for b in found.values(): b['squeeze']=True
    json.dump({'ts':time.time(),'patterns':found},open(OUT,'w'))
    log('SCAN DONE:',len(found),'squeeze setups')

if __name__=='__main__':
    log('=== cb_squeeze_scan start ===')
    while True:
        try: scan_once()
        except Exception as e: log('ERR',repr(e)[:200])
        time.sleep(86400)
