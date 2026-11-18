#!/usr/bin/env python3
# sol_api.py — browser-free SolFarmer client (Bearer JWT + auto-refresh)
import json, time, os
from curl_cffi import requests
CREDS='/tmp/sol_creds.json'
B='https://solfarmer.io/api'
UID='98c28999-8158-4113-aa5c-0dc759cb0ea9'

def _load():
    return json.load(open(CREDS))

def _save(d):
    json.dump(d,open(CREDS,'w'))

def _refresh():
    c=_load()
    r=requests.post(B+'/auth/auth/refresh',json={'refreshToken':c['rt']},impersonate='chrome',timeout=20,
                    headers={'Content-Type':'application/json','Origin':'https://solfarmer.io'})
    j=r.json()
    print('refresh',r.status_code,str(j)[:150],flush=True)
    if r.status_code==200 and j.get('accessToken'):
        c['at']=j['accessToken']
        if j.get('refreshToken'): c['rt']=j['refreshToken']
        _save(c)
        return True
    return False

def headers():
    c=_load()
    return {'Authorization':'Bearer '+c['at'],'Content-Type':'application/json',
            'Origin':'https://solfarmer.io','Referer':'https://solfarmer.io/farm'}

def req(method,path,body=None,base='game',retry=True):
    # path like '/state' -> /api/game/state ; '/lucky-boxes/open' etc.
    # auth endpoints use base='auth' -> /api/auth/auth/...
    url=f'{B}/{base}{path}'
    for i in range(2):
        r=requests.request(method,url,json=body,impersonate='chrome',timeout=25,headers=headers())
        if r.status_code==401 and retry and i==0:
            if _refresh(): continue
        try: return r.status_code,r.json()
        except Exception: return r.status_code,r.text
    return r.status_code,r.text

def game(method,path,body=None): return req(method,path,body,'game')
def ledger(method,path,body=None): return req(method,path,body,'ledger')
def auth(method,path,body=None): return req(method,path,body,'auth')

if __name__=='__main__':
    import sys
    m,p=sys.argv[1],sys.argv[2]
    b=json.loads(sys.argv[3]) if len(sys.argv)>3 else None
    base=sys.argv[4] if len(sys.argv)>4 else 'game'
    print(req(m,p,b,base))
