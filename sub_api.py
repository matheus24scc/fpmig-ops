#!/usr/bin/env python3
# Subterra API client — browser-free via curl_cffi (Cloudflare bypass) + self-refreshing supabase JWT
import json, time, os, sys
sys.path.insert(0,'/tmp')
from curl_cffi import requests
import sub_session
API='https://api.subterra.run/rest/v1/'

def _headers(extra=None):
    H={'Authorization':'Bearer '+sub_session.access_token(),'apikey':sub_session.apikey(),
       'x-client-info':'supabase-ssr/0.12.5','Content-Type':'application/json',
       'Origin':'https://subterra.run','Referer':'https://subterra.run/'}
    if extra: H.update(extra)
    return H

def _reauth():
    # refresh_token dead -> full Google SSO re-login via CDP browser
    import subprocess
    try:
        r=subprocess.run([sys.executable,'/tmp/sub_reauth.py'],capture_output=True,text=True,timeout=120)
        print('reauth:',(r.stdout+r.stderr).strip()[:200],flush=True)
        return r.returncode==0
    except Exception as e:
        print('reauth err',e,flush=True); return False

def _call(method,url,**kw):
    for i in range(3):
        r=requests.request(method,url,impersonate='chrome',timeout=25,**kw)
        if r.status_code in (401,403):
            if i==0 and sub_session.refresh():
                kw['headers']=_headers(kw.get('headers')); continue
            if i==1 and _reauth():
                kw['headers']=_headers(kw.get('headers')); continue
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    return r.status_code, r.text

def rpc(fn,params=None):
    return _call('POST',API+'rpc/'+fn,json=params or {},headers=_headers())

def table(path,params=None):
    return _call('GET',API+path,params=params or {},headers=_headers({'Accept':'application/json'}))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='rpc':
        print(rpc(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv)>3 else {}))
    elif len(sys.argv)>1 and sys.argv[1]=='get':
        print(table(sys.argv[2]))
    else:
        print('usage: sub_api.py rpc <fn> [json] | get <path>')
