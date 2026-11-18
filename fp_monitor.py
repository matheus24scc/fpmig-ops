#!/usr/bin/env python3
# fp_monitor.py — FaucetPay surfaces watchdog: sponsored rain, offerwall gate,
# PTC gate, reward points, balances. Pure API via /tmp/fp_api.py.
import sys, time, json
sys.path.insert(0,'/tmp')
from fp_api import api
LOG='/tmp/fp_monitor.log'
def log(*a):
    s=' '.join(str(x) for x in a)
    print(s,flush=True)
    open(LOG,'a').write(time.strftime('%H:%M:%S ')+s+'\n')
state={}
def check():
    sc,d=api('POST','/app-api/rp/claim-daily-rp',{})
    if isinstance(d,dict) and d.get('ok'):
        log('RP DAILY claimed:',d.get('amount',d))
    sc,d=api('GET','/app-api/sponsored-rain/eligible-faucets')
    n=len((d.get('faucets') or [])) if isinstance(d,dict) else -1
    if state.get('rain')!=n: log('RAIN eligible faucets:',n); state['rain']=n
    sc,d=api('GET','/app-api/offers/can-use-offerwall')
    ok=d.get('offerwalls_allowed') if isinstance(d,dict) else None
    if state.get('wall')!=ok:
        log('OFFERWALL allowed:',ok,'strict:',d.get('strict_allowed'),'convert:',d.get('convert_allowed')); state['wall']=ok
    sc,d=api('GET','/app-api/rp/get-balance')
    rp=d.get('balance') if isinstance(d,dict) else None
    if state.get('rp')!=rp: log('RP balance:',rp); state['rp']=rp
    sc,d=api('POST','/app-api/ptc/create-session',{'ad_id':1})
    msg=str(d.get('message',''))[:80] if isinstance(d,dict) else str(d)[:80]
    gate='minimum of 25 payments' in msg
    if state.get('ptc_gate')!=gate: log('PTC gate:','LOCKED' if gate else 'OPEN','|',msg); state['ptc_gate']=gate
    # faucet payment history -> PTC gate progress (25 payments / 5 faucets)
    sc,d=api('POST','/app-api/wallet/faucet-transactions',{})
    txs=(d.get('transactions') or []) if isinstance(d,dict) else []
    faus=set(t.get('faucet_name') for t in txs)
    tot=sum(float(t.get('amount_bitcoin') or 0) for t in txs)
    prog=f'{len(txs)}p/{len(faus)}f'
    if state.get('faucet_tx')!=prog:
        log('FAUCET-TX:',prog,'total_btc~',round(tot,8),'| latest:',txs[0].get('faucet_name') if txs else '-')
        state['faucet_tx']=prog
    sc,d=api('GET','/app-api/wallet/balances')
    nz=[(b['coin'],b['balance']) for b in (d.get('balances') or []) if isinstance(b,dict) and b.get('balance')]
    if state.get('bal')!=nz: log('BALANCES:',json.dumps(nz)); state['bal']=nz
if __name__=='__main__':
    log('=== fp_monitor start ===')
    while True:
        try: check()
        except Exception as e: log('ERR',repr(e)[:120])
        time.sleep(600)
