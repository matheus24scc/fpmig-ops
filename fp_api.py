#!/usr/bin/env python3
# fp_api.py — browser-free FaucetPay client (cookie session + curl_cffi)
# App-api surface discovered 2026-11-17: session/*, wallet/balances,
# faucet-list/*, ptc/*, offers/*, rp/*, games/availability, fx/rates.
import json, subprocess
from curl_cffi import requests
COOKIES='/tmp/fp_cookies.json'
B='https://faucetpay.io'
H={'accept':'application/json','content-type':'application/json',
   'Origin':'https://faucetpay.io','Referer':'https://faucetpay.io/dashboard'}

def _cookies():
    return {c['name']:c['value'] for c in json.load(open(COOKIES))}

def refresh_cookies():
    subprocess.run(['/tmp/pwenv/bin/python','/tmp/fp_cookie_sync.py'],timeout=60)

def api(method,path,body=None,tries=2):
    for i in range(tries):
        r=requests.request(method,B+path,impersonate='chrome',timeout=25,
                           cookies=_cookies(),headers=H,
                           json=body if body is not None else None)
        if r.status_code in (401,403) and i==0:
            refresh_cookies(); continue
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    return r.status_code, r.text

if __name__=='__main__':
    import sys
    sc,d=api(sys.argv[1] if len(sys.argv)>1 else 'GET',
             sys.argv[2] if len(sys.argv)>2 else '/app-api/wallet/balances',
             json.loads(sys.argv[3]) if len(sys.argv)>3 else None)
    print(sc, json.dumps(d)[:800])
