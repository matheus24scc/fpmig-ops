#!/usr/bin/env python3
# sol_api_loop.py — browser-free SolFarmer daemon: settle mining, daily chest, quests, balance
import sys, time, json, random, string, traceback, os
sys.path.insert(0,'/tmp')
from sol_api import game, ledger, UID
LOG='/tmp/sol_api.log'
SETTLE_EVERY=1200   # 20min — matches mining accrual cadence
POLL=60

def log(*a):
    line=' '.join(str(x) for x in a)
    print(line,flush=True)
    with open(LOG,'a') as f: f.write(time.strftime('%H:%M:%S ')+line+'\n')

def idem():
    return 'sol-'+''.join(random.choices(string.ascii_lowercase+string.digits,k=24))

def headers_extra():
    from sol_api import headers
    h=headers(); h['idempotency-key']=idem(); return h

def settle():
    # POST needs idempotency-key — use raw request via sol_api.req won't add it; do manual
    from curl_cffi import requests
    from sol_api import headers as H
    h=H(); h['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/mining/settle',json={'userId':UID},
                    impersonate='chrome',timeout=25,headers=h)
    try: return r.status_code,r.json()
    except Exception: return r.status_code,r.text

def balance():
    sc,d=ledger('GET',f'/balance/{UID}')
    if not isinstance(d,dict):
        log('bal err',sc,str(d)[:200]); return {}
    return d

def try_chest():
    from curl_cffi import requests
    from sol_api import headers as H
    h=H(); h['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/lucky-boxes/open',json={'box_id':'daily-free-box'},
                    impersonate='chrome',timeout=25,headers=h)
    try: return r.status_code,r.json()
    except Exception: return r.status_code,r.text

def claim_quests():
    # find claimable quests — story quests endpoint
    sc,d=game('GET','/quests/story')
    if not isinstance(d,(dict,list)): return
    qs=d.get('quests') if isinstance(d,dict) else d
    if not isinstance(qs,list): return
    for q in qs:
        if q.get('claimed') or q.get('status')=='claimed': continue
        if q.get('claimable') or q.get('completed') or q.get('progress',0)>=q.get('goal',1):
            qid=q.get('id') or q.get('quest_id')
            if not qid: continue
            from curl_cffi import requests
            from sol_api import headers as H
            h=H(); h['idempotency-key']=idem()
            r=requests.post('https://solfarmer.io/api/game/quests/claim',json={'quest_id':qid},
                            impersonate='chrome',timeout=25,headers=h)
            log('quest claim',qid,r.status_code,r.text[:150])
    # character quests (daily SOL/XP rewards) — separate list at /quests
    sc,d=game('GET','/quests')
    qs=d.get('quests') if isinstance(d,dict) else None
    if isinstance(qs,list):
        for q in qs:
            if q.get('claimed') or not q.get('completed'): continue
            qid=q.get('id') or q.get('quest_id')
            if not qid: continue
            from curl_cffi import requests
            from sol_api import headers as H
            h=H(); h['idempotency-key']=idem()
            r=requests.post('https://solfarmer.io/api/game/quests/claim',json={'quest_id':qid},
                            impersonate='chrome',timeout=25,headers=h)
            log('char quest claim',qid,r.status_code,r.text[:150])

def claim_streak():
    """Daily login streak — +0.0001 SOL/day, streak grows the reward."""
    from sol_api import headers as H
    from curl_cffi import requests as cr
    h=headers_extra()
    r=cr.post('https://solfarmer.io/api/game/quests/streak/claim',json={},
              impersonate='chrome',timeout=25,headers=h)
    if r.status_code==200:
        try:
            d=r.json(); log('STREAK',d.get('streakDays'),'days +',int(d.get('rewardLamports',0))/1e9,'SOL')
        except Exception: log('streak ok')
    else:
        log('streak',r.status_code,r.text[:120])

def buy_miners():
    """Auto-buy best hashrate/SOL miner when balance covers it, then place in free slot.
    All shop miners share ~100k H/SOL — pick biggest that fits power+slots+balance."""
    from curl_cffi import requests
    from sol_api import headers as H
    sc,shop=game('GET','/shop/miners')
    if not isinstance(shop,dict): return
    lvl=game('GET','/state')[1].get('gameState',{}).get('level',0)
    st=game('GET','/state')[1]
    room=[r for r in st.get('rooms',[]) if r.get('room_id')=='room-1']
    if not room: return
    room=room[0]
    placed=[m for m in st.get('miners',[]) if m.get('room_id')=='room-1']
    free_slots=int(room.get('max_slots',12))-len(placed)
    power_used=sum(int(m.get('power',0)) for m in placed)
    power_free=int(room.get('max_power',2000))-power_used
    b=balance(); spend=float(b.get('balance_sol') or 0)+float(b.get('ssol') or 0)
    inv_ids={i['miner_id']:i['id'] for i in game('GET','/miners/inventory')[1].get('inventory',[])}
    cands=[]
    for m in shop.get('miners',[]):
        if m.get('locked') or m.get('unlock_level',99)>lvl: continue
        c=float(m['cost']); pw=int(m.get('power',0)); h=float(m['hashrate'])
        if c<=spend and pw<=power_free and free_slots>0:
            cands.append((h,c,m['miner_id'],pw))
    if not cands: return
    cands.sort(reverse=True)  # max hashrate first (same H/SOL ratio)
    h,c,mid,pw=cands[0]
    hhdr=H(); hhdr['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/shop/miners/purchase',json={'miner_id':mid},
                    impersonate='chrome',timeout=25,headers=hhdr)
    try: d=r.json()
    except Exception: d=r.text[:150]
    if r.status_code!=200 or not (isinstance(d,dict) and d.get('success')):
        log('buy fail',mid,r.status_code,str(d)[:150]); return
    log(f'BOUGHT {mid} {h:.0f}H cost {c} SOL')
    # place it
    time.sleep(1)
    inv=game('GET','/miners/inventory')[1].get('inventory',[])
    mine=[i for i in inv if i['miner_id']==mid]
    if not mine: log('bought but not in inv?',mid); return
    free_slot=next((i for i in range(int(room.get('max_slots',12))) if i not in {m.get('slot_index') for m in placed}),None)
    if free_slot is None: log('no free slot for',mid); return
    hhdr=H(); hhdr['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/miners/place',
                    json={'miner_id':mine[0]['id'],'room_id':'room-1','slot_index':free_slot},
                    impersonate='chrome',timeout=25,headers=hhdr)
    log('place',mid,'slot',free_slot,r.status_code,r.text[:150])

def claim_milestones():
    """Claim level-gated milestone rewards (SOL lamports) — e.g. lvl15 = 0.005 SOL."""
    sc,d=game('GET','/progression/milestones')
    if not isinstance(d,dict): return
    for m in d.get('milestones',[]):
        if m.get('claimed') or m.get('unlocked') is False: continue
        # only attempt if level reached
        lvl=int((game('GET','/state')[1].get('gameState',{}) or {}).get('level',0))
        if m.get('level',99)>lvl: continue
        from curl_cffi import requests
        from sol_api import headers as H
        h=H(); h['idempotency-key']=idem()
        r=requests.post('https://solfarmer.io/api/game/quests/milestones/claim',
                        json={'milestone_id':m['milestone_id']},
                        impersonate='chrome',timeout=20,headers=h)
        try: dd=r.json()
        except Exception: dd=r.text[:100]
        log('MILESTONE',m['milestone_id'],'->',r.status_code,str(dd)[:140])

def auto_convert():
    """SOL->sSOL at 1:1, min 0.001 SOL per tx.
    Whenever liquid SOL reaches the minimum, convert the MAXIMUM
    (whole balance) — sSOL is the upgrade currency (miners/merges)."""
    b=balance()
    lam=int(b.get('balance_lamports') or 0)
    if lam<1_000_000: return  # below 0.001 SOL minimum
    from curl_cffi import requests
    from sol_api import headers as H
    h=H(); h['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/wallet/convert',
                    json={'amount_lamports':str(lam)},
                    impersonate='chrome',timeout=20,headers=h)
    try: d=r.json()
    except Exception: d=r.text[:120]
    log('CONVERT',lam,'lamports SOL->sSOL ->',r.status_code,str(d)[:140])

def merge_duplicates():
    """Merge same-type miner pairs (lowest level first = cheapest SSOL fee).
    Verified: POST /miners/merge {miner1_id,miner2_id} -> higher level + bonus."""
    sc,st=game('GET','/state')
    if not isinstance(st,dict): return
    ms=[m for m in st.get('miners',[]) if m.get('room_id')=='room-1']
    by={}
    for m in ms: by.setdefault((m.get('miner_id'),int(m.get('level',1))),[]).append(m)
    pairs=[]
    for (mid,lvl),grp in by.items():
        if len(grp)>=2:
            pairs.append((lvl,grp[0]['id'],grp[1]['id'],mid))
    if not pairs: return
    pairs.sort()  # cheapest (lowest level) first
    bad=state.setdefault('merge_bad',{}) if False else None
    import json as _j,os as _o
    BF='/tmp/sol_merge_bad.json'
    try: bad=_j.load(open(BF))
    except Exception: bad={}
    now=time.time()
    bad={k:v for k,v in bad.items() if v>now}
    pairs=[p for p in pairs if bad.get(p[1]+'|'+p[2],0)<=now]
    if not pairs:
        _j.dump(bad,open(BF,'w')); return
    lvl,a,b,mid=pairs[0]
    from curl_cffi import requests
    from sol_api import headers as H
    h=H(); h['idempotency-key']=idem()
    r=requests.post('https://solfarmer.io/api/game/miners/merge',
                    json={'miner1_id':a,'miner2_id':b},
                    impersonate='chrome',timeout=25,headers=h)
    try: d=r.json()
    except Exception: d=r.text[:150]
    log('MERGE',mid,'lvl',lvl,'->',r.status_code,str(d)[:160])
    if r.status_code==422 and 'same level' in str(d).lower():
        bad[a+'|'+b]=now+86400; _j.dump(bad,open(BF,'w'))

CB_SOL_ADDR='9LwhNSzLtDBh7zDywSzqiNGF4QkEjt22oGEUB69xVmL1'

SOL_WITHDRAW_FLAG='/tmp/sol_withdrawn.flag'
MIN_WITHDRAW_LAMPORTS=100_000_000  # 0.1 SOL — server-enforced minimum

def maybe_withdraw(b):
    """Auto-withdraw to Coinbase once game SOL >= 0.1 SOL min.
    Flow discovered in JS bundle: POST /wallet/withdraw then /confirm."""
    if os.path.exists(SOL_WITHDRAW_FLAG): return
    sol=float(b.get('balance_sol') or 0)
    if sol < 0.1: return
    from sol_api import headers as H
    from curl_cffi import requests as cr
    lamports=str(int(sol*0.98*1e9))  # keep 2% buffer for fees/rounding
    h=headers_extra()
    r=cr.post('https://solfarmer.io/api/game/wallet/withdraw',
              json={'amount_lamports':lamports,'destination_address':CB_SOL_ADDR},
              impersonate='chrome',timeout=30,headers=h)
    log('withdraw req',r.status_code,r.text[:300])
    if r.status_code not in (200,201): return
    try: payload=r.json()
    except Exception: return
    # second step: confirm with returned payload/params
    r2=cr.post('https://solfarmer.io/api/game/wallet/withdraw/confirm',
               json=payload, impersonate='chrome',timeout=30,headers=headers_extra())
    log('withdraw confirm',r2.status_code,r2.text[:300])
    if r2.status_code in (200,201):
        open(SOL_WITHDRAW_FLAG,'w').write(str(sol))
        log('WITHDRAWN -> Coinbase', sol, 'SOL')

def main():
    log('=== sol_api_loop start ===')
    last_settle=0; last_quest=0; last_buy=0; last_mg=0; last_merge=0
    while True:
        try:
            b=balance()
            log('bal',b.get('balance_sol'),'SOL ssol',b.get('ssol'))
            try: maybe_withdraw(b)
            except Exception as e: log('withdraw err',repr(e)[:150])
            now=time.time()
            if now-last_settle>SETTLE_EVERY:
                sc,d=settle()
                if isinstance(d,dict) and d.get('success'):
                    s=d.get('settlement',{})
                    log('SETTLE +',s.get('earnings_sol_display'),'SOL')
                else:
                    log('settle',sc,str(d)[:150])
                last_settle=now
                # chest right after settle (daily, self-limiting)
                sc2,d2=try_chest()
                log('chest',sc2,str(d2)[:200])
            if now-last_quest>3600:
                claim_quests(); claim_streak(); last_quest=now
            if now-last_quest>3600:
                try: claim_milestones()
                except Exception as e: log('ms err',repr(e)[:120])
            try: auto_convert()
            except Exception as e: log('conv err',repr(e)[:120])
            if now-last_merge>600:
                try: merge_duplicates()
                except Exception as e: log('merge err',repr(e)[:150])
                last_merge=now
            if now-last_buy>600:
                try: buy_miners()
                except Exception as e: log('buy err',repr(e)[:150])
                last_buy=now
            # daily minigame farm (crypto_sweeper only — verified), throttled 10min
            mg_done='/tmp/sol_mg_done.json'
            try:
                if now-last_mg>600:
                    import subprocess
                    st=json.load(open(mg_done)) if os.path.exists(mg_done) else {}
                    if st.get('date')!=time.strftime('%Y-%m-%d') or 'crypto_sweeper' not in (st.get('games') or {}):
                        subprocess.run(['/tmp/pwenv/bin/python','/tmp/sol_minigame_farm.py'],timeout=120)
                    last_mg=now
            except Exception as e: log('mg err',repr(e)[:100])
        except Exception as e:
            log('ERR',repr(e)[:200]); traceback.print_exc()
        time.sleep(POLL)

if __name__=='__main__':
    main()
