#!/usr/bin/env python3
# tapswap_api.py — TapSwap 100% API: webview initData -> login -> chq challenge -> token
import asyncio, json, urllib.parse, subprocess, os, time
from telethon import TelegramClient
from telethon.tl import functions
from curl_cffi import requests

TG_API_ID=2040
TG_API_HASH='b18441a1ff607e10a989891a5462e627'
TG_SESSION='/tmp/tg.session'
BOT='tapswap_bot'
APP_URL='https://app.tapswap.ai/'
API='https://api.tapswap.club'
CHQ_MJS='/tmp/tapswap_bot/chq.mjs'
TOKEN_FILE='/tmp/tapswap_token.json'

def log(*a): print(f"[{time.strftime('%H:%M:%S')}]",*a,flush=True)

def hdrs(tok=None):
    h={'x-app':'tapswap_server','x-touch':'1','x-cv':'664','Content-Type':'application/json'}
    if tok: h['Authorization']=f'Bearer {tok}'
    return h

async def get_init_data():
    c=TelegramClient(TG_SESSION,TG_API_ID,TG_API_HASH)
    await c.connect()
    bot=await c.get_entity(BOT)
    r=await c(functions.messages.RequestWebViewRequest(
        peer=bot,bot=bot,platform='ios',url=APP_URL))
    frag=urllib.parse.urlparse(r.url).fragment
    raw=[p.split('=',1)[1] for p in frag.split('&') if p.startswith('tgWebAppData=')][0]
    return urllib.parse.unquote(raw)

def solve_chq(chq):
    ba=bytearray(len(chq)//2)
    for i in range(0,len(chq),2): ba[i//2]=int(chq[i:i+2],16)
    dec=bytes(b^157 for b in ba).decode('utf-8')
    out=subprocess.run(['node',CHQ_MJS,dec],capture_output=True,text=True,cwd='/tmp/tapswap_bot')
    lines=out.stdout.strip().split('\n')
    chr_key=int(lines[0].strip())
    cache_id=None
    for l in lines:
        if 'Cache-Id:' in l: cache_id=l.split(':',1)[1].strip()
    return chr_key,cache_id

async def login():
    init=await get_init_data()
    s=requests.Session(impersonate='chrome')
    r=s.post(API+'/api/account/login',json={'init_data':init,'referrer':''},headers=hdrs(),timeout=20)
    j=r.json()
    if r.status_code!=201 or 'chq' not in j:
        log('login unexpected:',r.status_code,str(j)[:200]); return None
    chq=j['chq']
    chr_key,cache_id=solve_chq(chq)
    log('chq solved chr=',chr_key,'cache=',cache_id)
    h=hdrs()
    if cache_id: h['Cache-Id']=cache_id
    r2=s.post(API+'/api/account/challenge',
        json={'init_data':init,'referrer':'','bot_key':'app_bot_0','chr':chr_key},headers=h,timeout=20)
    j2=r2.json()
    tok=j2.get('access_token')
    if not tok:
        log('challenge fail:',r2.status_code,str(j2)[:300]); return None
    json.dump({'token':tok,'ts':time.time()},open(TOKEN_FILE,'w'))
    log('TOKEN OK')
    return tok

def api(method,path,body=None,tok=None):
    if tok is None:
        try: tok=json.load(open(TOKEN_FILE))['token']
        except: return 0,{'error':'no_token'}
    r=requests.request(method,API+path,json=body,headers=hdrs(tok),impersonate='chrome',timeout=20)
    try: return r.status_code,r.json()
    except: return r.status_code,r.text

async def ensure_token():
    if os.path.exists(TOKEN_FILE):
        d=json.load(open(TOKEN_FILE))
        if time.time()-d.get('ts',0)<3500: return d['token']
    return await login()

if __name__=='__main__':
    tok=asyncio.run(ensure_token())
    if tok:
        sc,d=api('GET','/api/player',tok=tok)
        print('player:',sc,str(d)[:400])
