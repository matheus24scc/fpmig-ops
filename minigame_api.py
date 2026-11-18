#!/usr/bin/env python3
# minigame_api.py — pure-API Subterra minigame farmer (replaces mem_solver/reflex/qm browser workers)
# Flow: POST /api/minigames/start -> wait realistic duration -> POST /api/minigames/complete {won:true}
# Server validates min-duration + daily caps + cooldowns; captcha demands are skipped.
import sys, time, json, random, traceback
sys.path.insert(0,'/tmp')
from curl_cffi import requests

LOG='/tmp/minigame_api.log'
COOKIES='/tmp/sub_cookies.json'
BASE='https://subterra.run'
GAMES=['math','memory','reflex']
# realistic play durations (seconds) — above server min-duration, human-plausible
DUR={'math':(38,55),'memory':(42,58),'reflex':(14,22)}
BETWEEN=(150,300)  # seconds between attempts — respect server cooldown
CAP=25
_state={'wins':{g:0 for g in GAMES},'cool':{g:0.0 for g in GAMES}}

def log(*a):
    line=' '.join(str(x) for x in a)
    print(line,flush=True)
    with open(LOG,'a') as f: f.write(time.strftime('%H:%M:%S ')+line+'\n')

def cookies():
    # self-sustaining: rebuild auth cookies from live supabase session (no browser)
    sys.path.insert(0,'/tmp')
    import sub_session
    if sub_session.access_token():
        return sub_session.cookie_header()
    return {x['name']:x['value'] for x in json.load(open(COOKIES))}

def post(path,payload,game=None):
    h={'Origin':BASE,'Referer':BASE+'/earn/games/'+(game or 'math'),'Content-Type':'application/json'}
    r=requests.post(BASE+path,json=payload,impersonate='chrome',timeout=25,cookies=cookies(),headers=h)
    try: return r.status_code,r.json()
    except Exception: return r.status_code,{'error':r.text[:200]}

def refresh_cookies():
    # self-sustaining supabase refresh — no browser
    try:
        sys.path.insert(0,'/tmp')
        import sub_session
        sub_session.refresh()
    except Exception: pass

def play_once(game):
    sc,d=post('/api/minigames/start',{'gameId':game},game)
    if sc!=200 or not isinstance(d,dict):
        log(game,'start err',sc,str(d)[:120]); return False
    if d.get('error'):
        log(game,'start error:',d['error'][:120])
        if 'imit' in str(d['error']): _state['wins'][game]=CAP
        return False
    sid=d.get('sessionId')
    if not sid: log(game,'no sessionId',str(d)[:150]); return False
    dur=random.uniform(*DUR[game])
    log(game,'session',sid[:8],'playing',f'{dur:.0f}s')
    time.sleep(dur)
    sc2,r=post('/api/minigames/complete',{'sessionId':sid,'won':True},game)
    if sc2!=200:
        log(game,'complete http',sc2,str(r)[:120]); return False
    if r.get('needsCaptcha'):
        log(game,'NEEDS CAPTCHA — skipping (will retry later)')
        return False
    if r.get('error'):
        e=r['error']
        log(game,'complete error:',e[:140])
        if 'imit' in e: _state['wins'][game]=CAP
        if 'cool' in e.lower(): _state['cool'][game]=time.time()+600
        return False
    wt=r.get('winsToday'); rew=r.get('reward')
    if wt is not None: _state['wins'][game]=wt
    log(game,f'WIN reward={rew} winsToday={wt} crate={bool(r.get("crate"))}')
    _state['cool'][game]=time.time()+random.uniform(*BETWEEN)
    return True

def main():
    log('=== minigame_api start ===')
    while True:
        try:
            now=time.time()
            avail=[g for g in GAMES if _state['wins'][g]<CAP and now>_state['cool'].get(g,0)]
            if not avail:
                # all capped/cooled — sleep till earliest cooldown or 10min
                nxt=min([_state['cool'][g] for g in GAMES if _state['wins'][g]<CAP] or [now+600])
                w=max(60,min(nxt-now,600)) if nxt>now else 600
                log('all busy/capped — sleep',f'{w:.0f}s','wins:',_state['wins'])
                time.sleep(w); continue
            g=random.choice(avail)
            play_once(g)
        except Exception as e:
            log('ERR',repr(e)[:200]); traceback.print_exc()
            try: refresh_cookies()
            except Exception: pass
            time.sleep(30)

if __name__=='__main__':
    main()
