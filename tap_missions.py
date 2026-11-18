#!/usr/bin/env python3
# tap_missions.py — TapSwap mission auto-completer.
# Flow per cycle: read state token+conf -> join TG channels from conf items
# (telethon) -> join_mission each conf mission -> submit all items ->
# wait for async verification -> finish_mission verified ones.
# Runs every ~20min. Rewards are shares (stat.reward tracks them).
import json, time, re, sys, asyncio
from curl_cffi import requests as creq

STATE='/tmp/tapswap_state.json'
API='https://api.tapswap.club'
APP='https://app.tapswap.club/'
LOG=open('/tmp/tap_missions.log','a',buffering=1)
def log(*a):
    s=' '.join(str(x) for x in a)
    print(time.strftime('%H:%M:%S'),s,flush=True)
    LOG.write(time.strftime('%H:%M:%S ')+s+'\n')

def load():
    return json.load(open(STATE))

def hdrs(tok):
    return {'Authorization':'Bearer '+tok,'X-App':'tapswap_server','X-Touch':'1','X-Cv':'664',
            'Content-Type':'application/json','Origin':APP.rstrip('/'),'Referer':APP}

def post(s,path,body,tok):
    try:
        r=s.post(API+path,json=body or {},headers=hdrs(tok),impersonate='chrome',timeout=20)
        try: return r.status_code,r.json()
        except Exception: return r.status_code,{}
    except Exception as e:
        return -1,{'err':str(e)[:120]}

def chan_names(conf):
    """Extract telegram channel usernames from mission items."""
    out=set()
    for m in conf.get('missions',[]):
        for it in m.get('items',[]):
            if it.get('type')!='tg': continue
            n=it.get('name') or it.get('link') or ''
            n=n.strip().lstrip('@')
            if n and 't.me' not in n and 'http' not in n: out.add(n)
            mm=re.search(r't\.me/(?:\+|joinchat/)?([A-Za-z0-9_]+)',n or '')
            if mm: out.add(mm.group(1))
    return out

def join_channels(names):
    async def go():
        from telethon import TelegramClient
        from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
        c=TelegramClient('/tmp/tg.session',2040,'b18441a1ff607e10a989891a5462e627')
        await c.connect()
        if not await c.is_user_authorized():
            log('TG session dead'); await c.disconnect(); return
        for n in names:
            try:
                e=await c.get_entity(n)
                await c(JoinChannelRequest(e))
                log('TG joined',n)
            except Exception as ex:
                msg=str(ex)
                if 'already' in msg.lower() or 'participant' in msg.lower():
                    pass
                else: log('TG join fail',n,msg[:80])
        await c.disconnect()
    try: asyncio.run(go())
    except Exception as e: log('TG err',str(e)[:100])

def account_missions(s,tok):
    """Get active/completed missions via a benign mission call response."""
    sc,j=post(s,'/api/missions/join_mission',{'id':'__noop__'},tok)
    return (j.get('account') or {}).get('missions',{})

def cycle():
    st=load(); tok=st.get('token'); conf=st.get('conf') or {}
    if not tok: log('no token'); return
    s=creq.Session(impersonate='chrome')
    # 1. join all tg channels from conf (idempotent)
    chans=chan_names(conf)
    if chans: join_channels(chans)
    # 2. join every conf mission (already_joined is fine)
    mids=[m['id'] for m in conf.get('missions',[])]
    for mid in mids:
        post(s,'/api/missions/join_mission',{'id':mid},tok)
    time.sleep(1)
    # 3. discover ACTIVE missions (includes dynamic ones not in conf)
    sc,j=post(s,'/api/missions/join_mission',{'id':'__noop__'},tok)
    active=((j.get('account') or {}).get('missions') or {}).get('active') or []
    # also submit conf mission items (covers missions joinable but not yet active)
    for m in conf.get('missions',[]):
        mid=m['id']; n=len(m.get('items',[]))
        for i in range(n):
            post(s,'/api/missions/finish_mission_item',{'id':mid,'itemIndex':i,'user_input':''},tok)
            time.sleep(0.15)
    # submit items for active dynamic missions too
    for m in active:
        mid=m['id']; items=m.get('items') or []
        for i in range(len(items)):
            post(s,'/api/missions/finish_mission_item',{'id':mid,'itemIndex':i,'user_input':''},tok)
            time.sleep(0.15)
    # 4. wait for async verification then finish all active
    time.sleep(75)
    done=[]
    targets=[m['id'] for m in active]+mids
    for mid in dict.fromkeys(targets):
        sc,j=post(s,'/api/missions/finish_mission',{'id':mid},tok)
        if sc==201:
            done.append(mid)
            p=(j.get('player') or {})
            log('MISSION DONE',mid,'shares=',p.get('shares'))
    if done: log('cycle complete, finished:',done)
    else: log('cycle complete, active=',[m['id'] for m in active],'pending verification')

if __name__=='__main__':
    log('=== tap_missions start ===')
    while True:
        try: cycle()
        except Exception as e: log('ERR',repr(e)[:150])
        time.sleep(1200)
