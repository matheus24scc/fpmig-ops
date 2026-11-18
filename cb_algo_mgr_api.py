#!/usr/bin/env python3
# cb_algo_mgr_api.py — browser-free ALGO position manager (pure API via cb_api.py)
# Pattern: RSI<30 oversold bounce, hold ~2 days. TP +3% / SL -5% / time 48h / RSI>=75.
import sys, json, time, urllib.request, uuid
sys.path.insert(0,'/tmp')
from cb_api import api
LOG='/tmp/cb_algo_mgr.log'
def log(m):
    line=f"[{time.strftime('%m-%d %H:%M')}] {m}"
    print(line,flush=True); open(LOG,'a').write(line+'\n')
ENTRY_TS=1794828700
ENTRY_PRICE=0.07907
HOLD_SECONDS=2*86400
STOP_PCT=-0.05
TAKE_PCT=0.03
STOP_OID="2bf63d8d-f2b3-4e57-8780-939fecdefc7f"

def price_now():
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request('https://api.exchange.coinbase.com/products/ALGO-USD/ticker',headers={'User-Agent':'Mozilla/5.0'}),timeout=10))
        return float(d['price'])
    except Exception: return 0.0
def candles(pair,n=40):
    end=int(time.time())
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.exchange.coinbase.com/products/{pair}/candles?granularity=86400&start={end-86400*n}&end={end}',headers={'User-Agent':'Mozilla/5.0'}),timeout=15))
        d.sort(key=lambda c:c[0]);return [x[4] for x in d]
    except Exception: return []
def rsi(cl,p=14):
    g=[];l=[]
    for j in range(1,len(cl)):
        ch=cl[j]-cl[j-1];g.append(max(ch,0));l.append(max(-ch,0))
    ag=sum(g[-p:])/p;al=sum(l[-p:])/p
    return 100-100/(1+ag/al) if al else 50
def get_algo_bal():
    sc,j=api('GET','/accounts?limit=250')
    try:
        tot=0.0
        for a in j.get('accounts',[]):
            if a.get('currency')=='ALGO':
                tot+=float(a['available_balance']['value'])+float((a.get('hold') or {}).get('value') or 0)
        return tot
    except Exception: return 0.0
def cancel_stop():
    sc,j=api('POST','/orders/batch_cancel',{"order_ids":[STOP_OID]})
    log(f'cancel stop: {sc} {json.dumps(j)[:200]}')
def sell(qty):
    body={"client_order_id":str(uuid.uuid4()),"product_id":"ALGO-USDC","side":"SELL",
          "order_configuration":{"market_market_ioc":{"base_size":f"{qty:.8f}"}}}
    sc,j=api('POST','/orders',body)
    log(f'SELL {qty:.4f}: {sc} {json.dumps(j)[:300]}')

def main():
    log('mgr-api start (browser-free)')
    zero_streak=0
    while True:
        try:
            bal=get_algo_bal()
            cl=candles('ALGO-USD')
            price=price_now() or (cl[-1] if cl else 0)
            r=rsi(cl) if cl else 50
            age=(time.time()-ENTRY_TS)/3600
            pnl=(price/ENTRY_PRICE-1)*100 if price else 0
            log(f'bal={bal:.4f} px={price} RSI={r:.1f} age={age:.1f}h pnl={pnl:+.2f}%')
            if bal<=0:
                zero_streak+=1
                if zero_streak>=3:
                    log('no ALGO x3 — closed, exit'); break
                time.sleep(300); continue
            zero_streak=0
            reason=None
            if pnl<=STOP_PCT*100: reason=f'STOP {pnl:.1f}%'
            elif pnl>=TAKE_PCT*100: reason=f'TP {pnl:.1f}%'
            elif age>=HOLD_SECONDS/3600: reason=f'HOLD48h age={age:.1f}h'
            elif r>=75: reason=f'RSI_OVERBOUGHT {r:.0f}'
            if reason:
                log(f'EXIT: {reason} — selling {bal:.4f}')
                cancel_stop(); time.sleep(4)
                sell(bal); time.sleep(5)
                if get_algo_bal()<0.01:
                    log('sell confirmed, done'); break
                log('sell partial? retry next cycle')
        except Exception as e:
            log(f'err {e}')
        time.sleep(60)
main()
