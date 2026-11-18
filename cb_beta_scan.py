#!/usr/bin/env python3
"""Beta-divergence mean-reversion scanner — relative-value edge.

Signal: an alt's 10d return underperforms BTC-USD's 10d return by >2.2 sigma
of its own 120d residual distribution, WHILE the alt still holds above its
50d MA (downtrend not broken — this is a beta laggard, not a dead coin).
Entry at signal close, exit after HOLD days or on convergence (residual
back to 0). Backtest gates identical to cb_edge_scan: winrate>=62%,
both halves>=55%, >=15 signals, liquidity>$200k/d.

Writes /tmp/cb_beta_proven.json — cb_monitor2 can merge like edge_proven.
Re-scans every 24h."""
import json,urllib.request,time,datetime,os,math
UA={'User-Agent':'Mozilla/5.0'}
OUT='/tmp/cb_beta_proven.json'
LOG=open('/tmp/cb_beta_scan.log','a',buffering=1)
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

LOOK=10      # return window days
RESID_WIN=120# sigma estimation window
Z_TH=2.2     # divergence threshold
HOLD=5       # hold days
def closes(c): return [x[4] for x in c if x[4]]

def scan_once():
    # BTC benchmark closes
    btc=candles('BTC-USD',86400,RESID_WIN+LOOK+10)
    if len(btc)<RESID_WIN+LOOK+5: log('btc candles short'); return
    bc=closes(btc)
    btc_ret=[bc[i]/bc[i-LOOK]-1 for i in range(LOOK,len(bc))]
    # residual per alt = alt_ret - btc_ret over same dates; sigma over window
    prods=get('https://api.exchange.coinbase.com/products') or []
    pairs=[p['id'] for p in prods if p['id'].endswith('-USD')
           and p['id']!='BTC-USD' and p.get('status')=='online' and not p.get('trading_disabled')]
    found={}
    for pair in pairs:
        c=candles(pair,86400,RESID_WIN+LOOK+15)
        if len(c)<RESID_WIN+LOOK+10: continue
        cl=closes(c)
        if len(cl)!=len(bc) or len(cl)<RESID_WIN+LOOK+5: continue
        rets=[cl[i]/cl[i-LOOK]-1 - (bc[i]/bc[i-LOOK]-1) for i in range(LOOK,len(cl))]
        # align: residuals for last RESID_WIN days
        res=rets[-RESID_WIN:]
        mu=sum(res)/len(res); sd=(sum((x-mu)**2 for x in res)/len(res))**0.5
        if sd<=0: continue
        z=(res[-1]-mu)/sd
        if z>-Z_TH: continue
        # trend filter: price above 50d MA
        ma50=sum(cl[-50:])/50
        if cl[-1]<ma50: continue
        # backtest: all historical z<-Z_TH signals, forward HOLD return
        ent=[]
        for j in range(len(rets)-RESID_WIN-1, len(rets)-HOLD-1):
            w=rets[max(0,j-RESID_WIN+1):j+1]
            if len(w)<60: continue
            m=sum(w)/len(w); s=(sum((x-m)**2 for x in w)/len(w))**0.5
            if s<=0: continue
            if (w[-1]-m)/s < -Z_TH:
                i0=LOOK+j  # close index of signal
                if i0+HOLD<len(cl):
                    ent.append((cl[i0+HOLD]/cl[i0]-1)*100)
        if len(ent)<15: continue
        w=sum(1 for x in ent if x>0)/len(ent)*100
        if w<62: continue
        h=len(ent)//2
        wo,wn=ent[:h],ent[h:]
        if not wo or not wn: continue
        wo_w=sum(1 for x in wo if x>0)/len(wo)*100
        wn_w=sum(1 for x in wn if x>0)/len(wn)*100
        if wo_w<55 or wn_w<55: continue
        # liquidity
        t=get(f'https://api.exchange.coinbase.com/products/{pair}/ticker')
        if not t or float(t['price'])*float(t['volume'])<200000: continue
        found[pair.split('-')[0]]={'z':round(z,2),'ret10':round((cl[-1]/cl[-LOOK]-1)*100,2),
                     'btc_ret10':round((bc[-1]/bc[-LOOK]-1)*100,2),
                     'winrate':round(w,1),'signals':len(ent),'hold':HOLD}
        log('FOUND',pair,json.dumps(found[pair]))
    for b in found.values(): b['beta']=True
    json.dump({'ts':time.time(),'patterns':found},open(OUT,'w'))
    log('scan done —',len(found),'qualified pairs')

if __name__=='__main__':
    log('=== cb_beta_scan start ===')
    while True:
        try: scan_once()
        except Exception as e:
            log('ERR',repr(e)[:200])
        time.sleep(86400)
