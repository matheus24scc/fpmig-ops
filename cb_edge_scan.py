#!/usr/bin/env python3
"""Capitulation-reclaim edge scanner — pattern family #2 (non-RSI).

Signal: a completed daily candle dumps <=-7% on >=2.5x median volume
(climax), and the NEXT day reclaims (close > capitulation-day open).
Entry at reclaim-day close, hold N days. This is the "selling climax +
absorption" pattern — distinct from RSI oversold, catches V-shaped
recoveries RSI misses.

Backtest filters (same rigor as cb_proven_scan):
  winrate >= 62%, both halves >= 55%, >=15 signals, liquidity >$200k/d.
Writes /tmp/cb_edge_proven.json — cb_monitor2 merges it and trades
'capit' specs via the capit_d flag computed in analyze().
Re-scans every 24h."""
import json,urllib.request,time,datetime,os
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_edge_proven.json'
LOG=open('/tmp/cb_edge_scan.log','a',buffering=1)
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

def liquidity_ok(pair):
    try:
        t=get(f'https://api.exchange.coinbase.com/products/{pair}-USD/ticker')
        return t and float(t['price'])*float(t['volume'])>200000
    except Exception: return False

DROP=-0.07      # capitulation day close-to-close return
VOLX=2.5        # volume multiple vs 20d median
HOLD=3          # hold days after reclaim entry

def scan_once():
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD') and p.get('status')=='online' and not p.get('trading_disabled')]
    found={}; meta={}
    for k,pair in enumerate(pairs):
        base=pair.split('-')[0]
        c=candles(pair,86400,400)
        if not c or len(c)<260: continue
        ent=[]
        for i in range(22,len(c)-HOLD-1):
            # capitulation day = i (completed), reclaim day = i+1
            cap=c[i]; rec=c[i+1]
            if not cap[3] or not cap[4] or not rec[3] or not rec[4]: continue
            ret=cap[4]/c[i-1][4]-1 if c[i-1][4] else 0
            if ret>DROP: continue
            vols=[x[5] or 0 for x in c[i-20:i]]
            vols=[v for v in vols if v>0]
            if not vols: continue
            med=sorted(vols)[len(vols)//2]
            if med<=0 or (cap[5] or 0)<VOLX*med: continue
            # reclaim confirmation: next day closes above capitulation open
            if rec[4]<=cap[3]: continue
            ent.append(i+1)   # entry index = reclaim day close
        if len(ent)<15: continue
        v=[(c[i+HOLD][4]/c[i][4]-1)*100 for i in ent]
        if not v: continue
        w=sum(1 for x in v if x>0)/len(v)*100
        if w<62: continue
        h=len(ent)//2
        wo=[(c[i+HOLD][4]/c[i][4]-1)*100 for i in ent[:h]]
        vn=[(c[i+HOLD][4]/c[i][4]-1)*100 for i in ent[h:]]
        wold=sum(1 for x in wo if x>0)/len(wo)*100 if wo else 0
        wnew=sum(1 for x in vn if x>0)/len(vn)*100 if vn else 0
        if wold<55 or wnew<55: continue
        if not liquidity_ok(pair): continue
        found[base]={'capit':True,'_w':round(w),'_n':len(ent)}
        meta[base]={'win':round(w),'n':len(ent),'drop':DROP,'volx':VOLX,'hold':HOLD}
        if k%60==0: log(f'..{k}/{len(pairs)} found={len(found)}')
    out={b:{k2:v2 for k2,v2 in sp.items() if not k2.startswith('_')} for b,sp in found.items()}
    json.dump({'patterns':out,'meta':meta,'ts':time.time()},open(OUT,'w'))
    log(f'SCAN DONE: {len(out)} capitulation-reclaim patterns',json.dumps(meta)[:500])

if __name__=='__main__':
    log('=== cb_edge_scan start ===')
    while True:
        try: scan_once()
        except Exception as e:
            log('ERR',repr(e)[:200])
        time.sleep(86400)