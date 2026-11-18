#!/usr/bin/env python3
# sub_session.py — self-sustaining Subterra auth (Supabase refresh_token grant, no browser)
import json, base64, time, re, urllib.parse, os
from curl_cffi import requests
SESS='/tmp/sub_session.json'
CREDS='/tmp/sub_creds.json'
COOKIES='/tmp/sub_cookies.json'
API='https://api.subterra.run'

def load_session():
    if os.path.exists(SESS):
        return json.load(open(SESS))
    # bootstrap from cookies file
    cookies={x['name']:x['value'] for x in json.load(open(COOKIES))}
    parts=sorted([k for k in cookies if re.search(r'auth-token\.\d+$',k)])
    raw=urllib.parse.unquote(''.join(cookies[k] for k in parts))
    b64=raw[7:] if raw.startswith('base64-') else raw
    b64+='='*(-len(b64)%4)
    sess=json.loads(base64.b64decode(b64))
    save_session(sess); return sess

def save_session(s):
    json.dump(s,open(SESS,'w'))

def apikey():
    return json.load(open(CREDS))['apikey']

def access_token():
    return load_session().get('access_token','')

def refresh():
    s=load_session()
    r=requests.post(API+'/auth/v1/token?grant_type=refresh_token',
        json={'refresh_token':s['refresh_token']},impersonate='chrome',timeout=20,
        headers={'apikey':apikey(),'Content-Type':'application/json','Origin':'https://subterra.run','Referer':'https://subterra.run/'})
    if r.status_code==200:
        j=r.json()
        s['access_token']=j['access_token']
        if j.get('refresh_token'): s['refresh_token']=j['refresh_token']
        s['expires_at']=j.get('expires_at')
        save_session(s)
        return True
    return False

def auth_headers():
    return {'Authorization':'Bearer '+access_token(),'apikey':apikey(),
            'x-client-info':'supabase-ssr/0.12.5','Content-Type':'application/json',
            'Origin':'https://subterra.run','Referer':'https://subterra.run/'}

def cookie_header():
    # rebuild sb auth cookies from live session for same-origin /api/* routes
    s=load_session()
    val='base64-'+base64.b64encode(json.dumps(s,separators=(',',':')).encode()).decode()
    cookies={x['name']:x['value'] for x in json.load(open(COOKIES))}
    out={}
    for k,v in cookies.items():
        if 'auth-token' in k and re.search(r'auth-token(\.\d+)?$',k): continue
        out[k]=v
    # single-cookie form (SSR accepts chunked or single)
    out['sb-cgqgjpcmolxgbrfdtfkz-auth-token']=urllib.parse.quote(val,safe='')
    return out

if __name__=='__main__':
    print('token ok:',bool(access_token()),'refresh:',refresh())
