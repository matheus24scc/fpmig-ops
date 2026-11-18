#!/usr/bin/env python3
# mine_api.py — pure-API Subterra miner (replaces mine_v6.py browser worker)
# Digs frontier cells via mine3d_dig RPC every ~31s (hand cooldown), tracks loot.
import sys, time, json, random, traceback
from collections import deque
sys.path.insert(0,'/tmp')
from sub_api import rpc, table

LOG='/tmp/mine_api.log'
SIZE=280; LAYERS=4
DIG_CD=17.0

def log(*a):
    line=' '.join(str(x) for x in a)
    print(line,flush=True)
    with open(LOG,'a') as f: f.write(time.strftime('%H:%M:%S ')+line+'\n')

def idx(l,r,c): return (l*SIZE+r)*SIZE+c
def wh(i):
    c=i%SIZE; n=(i-c)//SIZE; r=n%SIZE; l=(n-r)//SIZE
    return l,r,c

def build_revealed(d):
    rev=set()
    for t in range(0,len(d['open'])-1,2):
        s,cnt=d['open'][t],d['open'][t+1]
        for n in range(s,s+cnt):
            r,cl=divmod(n,SIZE)
            for l in range(LAYERS): rev.add(idx(l,r,cl))
    for t in range(0,len(d['dug'])-1,2):
        s,cnt=d['dug'][t],d['dug'][t+1]
        for n in range(s,s+cnt): rev.add(n)
    return rev

def frontier(rev):
    # ALL unrevealed cells adjacent to ANY revealed cell — no sampling,
    # so no ore pocket is ever stranded behind an unsampled cell
    out=set()
    for cell in rev:
        l0,r0,c0=wh(cell)
        for dl,dr,dc in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            nl,nr,nc=l0+dl,r0+dr,c0+dc
            if 0<=nl<LAYERS and 0<=nr<SIZE and 0<=nc<SIZE:
                ni=idx(nl,nr,nc)
                if ni not in rev: out.add(ni)
    return list(out)

ME_ID='47217217-84c9-49cd-88bd-844c3a4556e2'
_eq_pick={'t':0,'id':None}
def equipped_pickaxe():
    # refresh every 5min — pickaxe may break/be swapped by autopilot
    if time.time()-_eq_pick['t']<300: return _eq_pick['id']
    try:
        sc,d=table(f'pickaxes?select=id&owner_id=eq.{ME_ID}&is_equipped=eq.true&limit=1')
        _eq_pick['id']=(d[0]['id'] if isinstance(d,list) and d else None)
    except Exception: pass
    _eq_pick['t']=time.time()
    return _eq_pick['id']

def main():
    log('=== mine_api start (pure API) ===')
    rev=None; session=None; last_state=0; hits_used=0; haul={}; robots=[]; recharged=False; rech_price=1000
    ore_cells=deque(maxlen=12); collected_try=set(); dig_count=0
    while True:
        try:
            # refresh state every 5min or on session change/error
            need_state = rev is None or time.time()-last_state>300
            if need_state:
                sc,d=rpc('mine3d_state')
                if sc!=200 or not isinstance(d,dict) or 'session' not in d:
                    log('state err',sc,str(d)[:150]); time.sleep(20); continue
                session=d['session']['id']
                rev=build_revealed(d)
                hits_used=d.get('hits_used',0); hits_max=(d.get('hits_max') or 15)+(d.get('boost_hits') or 0)
                haul=d.get('haul') or {}
                last_state=time.time()
                pk=equipped_pickaxe()
                robots=[r for r in (d.get('robots') or []) if r.get('hp',0)>0]
                coins=[c for c in (d.get('coins') or [])]
                log(f'state: session={session[:8]} revealed={len(rev)} hits={hits_used}/{hits_max} haul_ore={haul.get("ore")} pick={str(pk)[:8]} robots={len(robots)} coins={len(coins)}')
                for cn in coins:
                    try:
                        ci2=cn.get('i')
                        if ci2 is None: continue
                        cl,cr,cc=wh(ci2)
                        for xs,zs in ((cc,cr),(cr,cc)):
                            scp,rc=rpc('mine3d_pick_coin',{'p_id':cn['id'],'p_x':xs,'p_z':zs})
                            if scp==200:
                                log('COIN!',cn.get('c'),cn.get('a'),'picked'); break
                            msg=str(rc)[:80]
                            if 'coin_gone' in msg: break
                        else:
                            log('coin err',cn.get('id'),msg[:80])
                    except Exception as e: log('coin exc',repr(e)[:80])
                recharged=False
                rech_price=d.get('recharge_price') or 1000
                log(f'recharges_left={d.get("recharges_left")} hand_cd={d.get("hand_cooldown")}')
            # --- robot hunt: they carry crypto (TRX/DOGE/SOL...) — kill for the payload
            if robots:
                rb=robots[0]
                rpk = equipped_pickaxe() if hits_used < hits_max else None
                sc,rh=rpc('mine3d_hit_robot',{'p_robot_id':rb['id'],'p_pickaxe_id':rpk,'p_x':rb.get('c',0),'p_z':rb.get('r',0)})
                if sc==200 and isinstance(rh,dict):
                    if 'hits_used' in rh: hits_used=rh['hits_used']
                    if 'hits_max' in rh: hits_max=rh['hits_max']
                    if rh.get('dead'):
                        log('ROBOT KILLED',rb.get('cur'),rb.get('amt'),'share=',rh.get('my_share'))
                        robots.pop(0)
                    else:
                        rb['hp']=rh.get('hp',rb.get('hp',0))
                        log(f'robot hit hp={rb["hp"]}/{rb.get("max")} dmg={rh.get("damage")} cur={rb.get("cur")} amt={rb.get("amt")}')
                    # respect hand cooldown from response if present
                    hfa=rh.get('hand_free_at'); now=rh.get('now')
                    if hfa and now:
                        time.sleep(max(2,min((hfa-now)/1000+1.5,60)))
                    else:
                        time.sleep(15)
                    continue
                else:
                    msg=(rh.get('message') if isinstance(rh,dict) else str(rh))[:100]
                    log('robot err',sc,msg)
                    if 'robot_gone' in str(msg): robots.pop(0)
                    elif 'pickaxe_not_equipped' in str(msg):
                        _eq_pick['t']=0  # autopilot swapping picks — refresh cache, keep hunting
                        time.sleep(8)
                    elif 'cooling' in str(msg) or 'hand' in str(msg): time.sleep(15)
                    else: robots=[]; time.sleep(5)
                    continue
            # --- recharge hits when exhausted and SUBT covers it (1000 + reserve)
            if hits_used>=hits_max and not recharged:
                try:
                    scp,prof=table(f'profiles?id=eq.{ME_ID}&select=balance_native&limit=1')
                    bal=(prof[0].get('balance_native') if isinstance(prof,list) and prof else 0) or 0
                    price=rech_price
                    if bal>=price+50:
                        scr,rr=rpc('mine3d_recharge',{'p_session_id':session})
                        log('RECHARGE',scr,str(rr)[:150])
                        if scr==200:
                            recharged=True; rev=None  # force state refresh for new hits
                    else:
                        log(f'hits exhausted ({hits_used}/{hits_max}) bal={bal} < recharge {price}+50 — bare hand mode')
                except Exception as e: log('recharge err',repr(e)[:100])
                recharged=True  # don't spam profile rpc every cycle
            cands=frontier(rev)
            if not cands:
                log('no frontier — full refresh'); rev=None; time.sleep(10); continue
            # score a random sample: prefer cells near recent ore strikes
            # (veins cluster) and cells that reveal the most new blocks
            sample=random.sample(cands,min(48,len(cands)))
            best=None; bs=-1e9
            for cand in sample:
                l2,r2,c2=wh(cand)
                exp=0
                for dl,dr,dc in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                    nl,nr,nc=l2+dl,r2+dr,c2+dc
                    if 0<=nl<LAYERS and 0<=nr<SIZE and 0<=nc<SIZE and idx(nl,nr,nc) not in rev: exp+=1
                s=exp*2.0
                if ore_cells:
                    dmin=min(abs(l2-ol)+abs(r2-orr)+abs(c2-oc) for ol,orr,oc in ore_cells)
                    if dmin<=4: s+=15
                    elif dmin<=8: s+=8
                s+=random.random()
                if s>bs: bs=s; best=cand
            ci=best
            l,r,c=wh(ci)
            pk = equipped_pickaxe() if hits_used < hits_max else None  # hits exhausted -> bare hand still digs
            sc,res=rpc('mine3d_dig',{'p_session_id':session,'p_layer':l,'p_row':r,'p_col':c,'p_pickaxe_id':pk})
            if (sc!=200 or not isinstance(res,dict)) and 'mine_hit_limit' in str(res):
                # pickaxe hits exhausted — bare hand still digs (free, slower)
                sc,res=rpc('mine3d_dig',{'p_session_id':session,'p_layer':l,'p_row':r,'p_col':c,'p_pickaxe_id':None})
            if sc!=200 or not isinstance(res,dict):
                msg=res.get('message') if isinstance(res,dict) else str(res)[:120]
                log('dig err',sc,msg)
                if 'grid_expired' in str(msg) or 'session' in str(msg).lower():
                    rev=None; session=None
                elif 'cooling' in str(msg):
                    # fetch fresh state for accurate hand_free_at, sleep until free
                    try:
                        scs,ds=rpc('mine3d_state')
                        if isinstance(ds,dict) and ds.get('hand_free_at') and ds.get('now'):
                            wait=(ds['hand_free_at']-ds['now'])/1000+2
                            if wait>0: time.sleep(min(wait,60))
                            else: time.sleep(8)
                        else: time.sleep(15)
                    except Exception: time.sleep(15)
                elif 'already' in str(msg).lower() or 'revealed' in str(msg).lower():
                    rev.add(ci)  # stale frontier entry — mark and move on
                    time.sleep(2)
                else:
                    rev=None  # resync revealed set
                    time.sleep(3)
                continue
            # success: the dug cell AND returned blocks are now revealed —
            # marking the target prevents re-digging the same cell forever
            rev.add(ci)
            for b in res.get('blocks') or []: rev.add(b)
            ore=res.get('ore') or []
            if ore:
                ore_cells.append((l,r,c))
                log('ORE!',json.dumps(ore)[:200],'at',l,r,c)
            dig_count+=1
            # sweep: loot can sit on revealed-but-undug cells — try collecting
            # a few random ones every 12 digs (cheap RPC, errors ignored)
            if dig_count%12==0 and rev:
                pool=[x for x in random.sample(list(rev),min(400,len(rev))) if x not in collected_try][:4]
                for t in pool:
                    collected_try.add(t)
                    tl,tr,tc=wh(t)
                    sct,ct=rpc('mine3d_collect',{'p_session_id':session,'p_layer':tl,'p_row':tr,'p_col':tc})
                    if sct==200 and isinstance(ct,dict) and ct:
                        log('SWEEP COLLECT',json.dumps(ct)[:200],'at',tl,tr,tc)
                if len(collected_try)>20000: collected_try.clear()
            ev=res.get('event_drop')
            if ev: log('EVENT',json.dumps(ev)[:200])
            if 'hits_used' in res: hits_used=res['hits_used']
            if 'hits_max' in res: hits_max=res['hits_max']
            log(f'dug ({l},{r},{c}) blocks={len(res.get("blocks") or [])} hits={hits_used}/{hits_max}')
            # collect items lying on the dug cell (ore/pickaxe/lootbox drops
            # do NOT auto-bank — they must be picked up via mine3d_collect)
            sc2,col=rpc('mine3d_collect',{'p_session_id':session,'p_layer':l,'p_row':r,'p_col':c})
            if sc2==200 and isinstance(col,dict) and col:
                log('COLLECTED',json.dumps(col)[:250])
            elif sc2!=200:
                msg=(col.get('message') if isinstance(col,dict) else str(col))[:80]
                if not any(x in str(msg) for x in ('nothing_to_collect','already_collected','cell_not_revealed')):
                    log('collect err',sc2,msg)
            # sleep until hand is free if server tells us, else fixed cooldown
            hfa=res.get('hand_free_at'); now=res.get('now')
            if hfa and now:
                wait=(hfa-now)/1000+1.5
                time.sleep(max(2,min(wait,90)))
            else:
                time.sleep(DIG_CD)
        except Exception as e:
            log('ERR',repr(e)[:200]); traceback.print_exc(); time.sleep(15)

if __name__=='__main__':
    main()
