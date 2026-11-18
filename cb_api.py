#!/usr/bin/env python3
# cb_api.py — browser-free Coinbase Advanced Trade client (cookie session + curl_cffi)
import json, subprocess, os, time
from curl_cffi import requests
COOKIES='/tmp/cb_cookies.json'
B='https://www.coinbase.com/api/v3/brokerage'
H={'cb-client':'CoinbaseWeb','cb-version':'2018-06-18','x-cb-platform':'web',
   'x-cb-is-logged-in':'true','x-cb-project-name':'consumer',
   'accept':'application/json','content-type':'application/json',
   'Origin':'https://www.coinbase.com','Referer':'https://www.coinbase.com/advanced-trade/spot/ALGO-USDC'}

def _cookies():
    return {c['name']:c['value'] for c in json.load(open(COOKIES))}

def refresh_cookies():
    # re-export session cookies from the live browser via CDP (needed only when they expire)
    subprocess.run(['/tmp/pwenv/bin/python','/tmp/cb_cookie_sync.py'],timeout=60)

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
    sc,d=api(sys.argv[1] if len(sys.argv)>1 else 'GET', sys.argv[2] if len(sys.argv)>2 else '/accounts?limit=5')
    print(sc, json.dumps(d)[:600])
