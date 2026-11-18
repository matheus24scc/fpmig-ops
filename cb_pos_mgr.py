#!/usr/bin/env python3
# cb_pos_mgr.py — generic Coinbase position manager (any coin from cb_positions.json)
# Exit rules DERIVED from the 38 historical ALGO pattern occurrences
# (MFE med +4.14% / MAE med -2.58%): SL -5% | TP +3% | time-stop 48h | RSI14>=75
import sys, json, time, urllib.request, uuid, os
sys.path.insert(0,'/tmp')
from cb_api import api
LOG='/tmp/cb_pos_mgr.log'
POSF='/tmp/cb_positions.json'
SL_PCT=-0.05; TP_PCT=0.03; HOLD_S=172800; RSI_EXIT=75

def log(m):
    line=f"[{time.strftime('%m-%d %H:%M')}] {m}"
    print(line,flush=True); open(LOG,'a').write(line+'\n')

def load():
    try: return json.load(open(POSF))
    except Exception: return []
def save(ps):
    json.dump(ps,open(POSF,'w'))

def ticker(pair):
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(
            f'https://api.exchange.coinbase.com/products/{pair}/ticker',
            headers={'User-Agent':'Mozilla/5.0'}),timeout=10))
        return float(d['price'])
    except Exception: return 0.0

def candles(pair,n=40):
    end=int(time.time())
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(
            f'https://api.exchange.coinbase.com/products/{pair}-USD/candles?granularity=86400&start={end-86400*n}&end={end}',
            headers={'User-Agent':'Mozilla/5.0'}),timeout=15))
        d.sort(key=lambda c:c[0]); return [x[4] for x in d]
    except Exception: return []

def rsi(cl,p=14):
    if len(cl)<p+1: return 50
    g=[];l=[]
    for j in range(1,len(cl)):
        ch=cl[j]-cl[j-1]; g.append(max(ch,0)); l.append(max(-ch,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 100-100/(1+ag/al) if al else 50

def bal_of(cur):
    sc,j=api('GET','/accounts?limit=250')
    try:
        tot=0.0
        for a in j.get('accounts',[]):
            if a.get('currency')==cur:
                tot+=float(a['available_balance']['value'])+float((a.get('hold') or {}).get('value') or 0)
        return tot
    except Exception: return 0.0

def sell_all(pos):
    qty=bal_of(pos['currency'])
    if qty<=0: return True
    body={"client_order_id":str(uuid.uuid4()),"product_id":pos['product'],"side":"SELL",
          "order_configuration":{"market_market_ioc":{"base_size":f"{qty:.8f}"}}}
    sc,j=api('POST','/orders',body)
    log(f"SELL {pos['pair']} {qty:.6f} {pos['product']}: {sc} {json.dumps(j)[:200]}")
    time.sleep(4)
    return bal_of(pos['currency'])<max(qty*0.05,1e-8)

def main():
    log('pos_mgr start — generic positions')
    while True:
        try:
            ps=load()
            if not ps:
                log('idle — no open positions')
                time.sleep(120); continue
            changed=False
            for pos in list(ps):
                pair=pos['pair']; cur=pos['currency']; prod=pos['product']
                px=ticker(pair+'-USD') or pos['entry_price']
                age=(time.time()-pos['entry_ts'])/3600
                pnl=(px/pos['entry_price']-1)*100
                r=rsi(candles(pair))
                log(f"{pair} bal-check px={px} pnl={pnl:+.2f}% age={age:.1f}h rsi={r:.0f}")
                reason=None
                if pnl<=SL_PCT*100: reason=f'SL {pnl:.1f}%'
                elif pnl>=TP_PCT*100: reason=f'TP {pnl:.1f}%'
                elif age>=HOLD_S/3600: reason=f'TIME {age:.1f}h'
                elif r>=RSI_EXIT: reason=f'RSI_OVERBOUGHT {r:.0f}'
                if reason:
                    log(f'EXIT {pair}: {reason}')
                    if sell_all(pos):
                        ps.remove(pos); changed=True; log(f'{pair} closed')
                    else:
                        log(f'{pair} sell incomplete — retry next cycle')
            if changed: save(ps)
        except Exception as e:
            log('err '+repr(e)[:150])
        time.sleep(60)
main()
