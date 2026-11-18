#!/usr/bin/env python3
# sub_api_autopilot.py — pure-API Subterra account daemon (no browser for account ops)
# Handles: quest claims, season pass claims, pickaxe equip/repair, trade monitoring,
# inventory management, pool check. Faucet/minigames/mine taps stay browser-side
# (captcha + client-side canvas).
import sys, time, json, traceback, os, re
sys.path.insert(0,'/tmp')
from sub_api import rpc, table

LOG='/tmp/sub_api_autopilot.log'
ME_ID='47217217-84c9-49cd-88bd-844c3a4556e2'
POLL=90
state={}

def log(*a):
    line=' '.join(str(x) for x in a)
    print(line,flush=True)
    with open(LOG,'a') as f: f.write(time.strftime('%H:%M:%S ')+line+'\n')

def jdump(d,n=300): return json.dumps(d)[:n] if not isinstance(d,str) else d[:n]

def my_profile():
    sc,d=table(f'profiles?id=eq.{ME_ID}&select=username,balance_native,balance_doge,balance_ltc,balance_sol,balance_trx,balance_xrp,level,xp,total_taps,daily_taps,streak_day,pool_id,pool2_id,pool_split,is_banned')
    return d[0] if isinstance(d,list) and d else None

def my_pickaxes():
    sc,d=table(f'pickaxes?select=id,catalog_id,power,durability_current,durability_max,is_broken,is_equipped,is_listed,repairs&owner_id=eq.{ME_ID}')
    return d if isinstance(d,list) else []

def claim_daily_quests():
    sc,d=rpc('daily_quests')
    if not isinstance(d,list): return
    for q in d:
        if q.get('claimed'): continue
        goal=q.get('goal_taps') or q.get('goal') or 0
        prog=q.get('progress') or 0
        if goal and prog<goal: continue
        sc2,r=rpc('claim_quest',{'p_quest_id':q['id']})
        log('quest',q['id'],'->',sc2,jdump(r,120))

def claim_pass():
    sc,d=rpc('season_pass_status')
    if not isinstance(d,dict): return
    me=d.get('me',{})
    # pass quests (daily+weekly cadence)
    for q in d.get('quests') or []:
        if q.get('claimed'): continue
        goal=q.get('goal') or 0; prog=q.get('progress')
        if prog is None: prog=goal  # some quests report null progress when complete?
        if goal and (prog or 0)<goal: continue
        sc2,r=rpc('claim_pass_quest',{'p_quest_id':q['id'],'p_with_subt':False})
        log('pass_quest',q['id'],'->',sc2,jdump(r,120))
    # free track level rewards (season ends soon — grab all reachable)
    mylvl=me.get('level',0)
    for l in d.get('levels') or []:
        if l['level']>mylvl or l.get('free_claimed'): continue
        sc2,r=rpc('claim_pass_rewards',{'p_level':l['level'],'p_track':'free'})
        log('pass_reward lvl',l['level'],'->',sc2,jdump(r,150))

_pick_cat={'t':0,'data':[]}
def _pickaxe_catalog():
    if time.time()-_pick_cat['t']<3600 and _pick_cat['data']: return _pick_cat['data']
    sc,d=table('pickaxe_catalog?select=id,name,power,durability_max,price_native,tier,is_purchasable&order=tier')
    _pick_cat['t']=time.time(); _pick_cat['data']=d or []
    return _pick_cat['data']

def manage_pickaxes(prof):
    picks=my_pickaxes()
    usable=[p for p in picks if not p['is_broken']]
    if not usable:
        # all broken = unrepairable (pickaxe_not_repairable) — buy cheapest
        # power>=2 pick so robot kills + tougher blocks unlock. Keep 550 reserve
        # so a mine recharge (1050) is never blocked by this purchase.
        bal0=prof.get('balance_native') or 0
        cat=_pickaxe_catalog()
        cand=[c for c in cat if c.get('is_purchasable') and (c.get('power') or 0)>=2 and (c.get('price_native') or 0)>0]
        cand.sort(key=lambda c:c.get('price_native') or 1e18)
        if cand and bal0-(cand[0].get('price_native') or 0)>=1100:
            b=cand[0]
            sc,r=rpc('buy_pickaxe',{'p_catalog_id':b['id']})
            log('BUY pickaxe (all-broken recovery)',b['id'],'pwr',b['power'],'dur',b['durability_max'],'price',b['price_native'],'->',sc,jdump(r,150))
        else:
            log('pickaxes: ALL BROKEN, bal',bal0,'— waiting to afford',cand[0]['id'] if cand else '?','price',cand[0].get('price_native') if cand else '?')
        return
    best=max(usable,key=lambda p:(p['power'],-p['durability_current']))
    eq=[p for p in usable if p['is_equipped']]
    # equip best if current equipped is worse or broken
    if not eq or (eq[0]['id']!=best['id'] and (eq[0]['power']<best['power'] or eq[0]['is_broken'])):
        sc,r=rpc('equip_pickaxe',{'p_pickaxe_id':best['id']})
        log('equip',best['catalog_id'],'pwr',best['power'],'->',sc,jdump(r,120))
    # repair if durability <30% and balance comfortable
    bal=prof.get('balance_native') or 0
    for p in usable:
        ratio=p['durability_current']/max(p['durability_max'],1)
        if ratio<0.3 and p['repairs']<3 and bal>150:
            sc,r=rpc('repair_pickaxe',{'p_pickaxe_id':p['id']})
            log('repair',p['catalog_id'],f'{p["durability_current"]}/{p["durability_max"]}','->',sc,jdump(r,150))
            break
    # auto-upgrade: buy cheapest pickaxe that beats current best, keep 80 SUBT reserve
    cat=_pickaxe_catalog()
    cur=(best['power'],best['durability_max'])
    best_buy=None
    for c in cat:
        if not c.get('is_purchasable'): continue
        price=c.get('price_native') or 0
        score=(c.get('power') or 0,c.get('durability_max') or 0)
        if score>cur and price>0 and bal-price>=80:
            if best_buy is None or price<best_buy.get('price_native',1e18):
                best_buy=c
    if best_buy:
        sc,r=rpc('buy_pickaxe',{'p_catalog_id':best_buy['id']})
        log('BUY pickaxe',best_buy['id'],'pwr',best_buy['power'],'dur',best_buy['durability_max'],'price',best_buy['price_native'],'->',sc,jdump(r,150))

def trade_watch(prof):
    sc,d=rpc('trade_my_offers')
    if isinstance(d,dict):
        act=d.get('active')
        if act:
            want=[w.get('name') for w in act.get('want',[])]
            give=[g.get('name') for g in act.get('give',[])]
            log('offer LIVE: give',give,'want',want,'id',str(act.get('id'))[:8])
        else:
            # no active offer — check if copper pickaxe arrived unbroken
            picks=my_pickaxes()
            copper=[p for p in picks if p['catalog_id']=='copper_pick' and not p['is_broken']]
            if copper and not state.get('copper_logged'):
                state['copper_logged']=True
                log('COPPER PICKAXE ARRIVED — equipped, mining at 2.3x')
            elif not copper:
                state['copper_logged']=False
                log('no active offer; copper_pick not in inventory')
    # market scan occasionally
    sc2,b=rpc('trade_offers_browse',{'p_kind':'pickaxe','p_catalog':None,'p_can_accept':True})
    if isinstance(b,list) and b:
        log('market pickaxe offers:',len(b),jdump(b[0],200))

_cat_cache={'t':0,'data':[]}
def miner_catalog():
    if time.time()-_cat_cache['t']<3600 and _cat_cache['data']: return _cat_cache['data']
    sc,d=table('miner_catalog?select=id,name,tier,hash_rate,recipe,craft_cost_native,fusion_fee_level2&order=hash_rate')
    if sc==200: _cat_cache['t']=time.time(); _cat_cache['data']=d
    return _cat_cache['data']

def craft_free_miners(prof,items):
    """Craft cost-0 SUBT miners when ore recipe is satisfied -> free hashrate for pools."""
    ores={o['catalog_id']:o['quantity'] for o in items.get('ores',[])}
    owned=sum(1 for m in my_miners() if not m.get('is_listed'))
    for m in miner_catalog():
        cost=m.get('craft_cost_native') or 0
        if cost>0: continue                      # only free crafts for now
        recipe=m.get('recipe') or {}
        if not recipe: continue                  # SUBT-only recipes skipped
        if all(ores.get(k,0)>=v for k,v in recipe.items()):
            sc,r=rpc('craft_miner',{'p_catalog_id':m['id']})
            log('CRAFT',m['id'],m['hash_rate'],'H/s ->',sc,jdump(r,150))
            if sc==200:
                owned+=1
                for k,v in recipe.items(): ores[k]=ores.get(k,0)-v

def craft_paid_miners(prof,items):
    """Buy SUBT-cost miners (empty ore recipe) when balance covers — hashrate engine."""
    ores={o['catalog_id']:o['quantity'] for o in items.get('ores',[])}
    bal=prof.get('balance_native') or 0
    for m in miner_catalog():  # sorted by hash_rate asc — cheapest first
        cost=m.get('craft_cost_native') or 0
        if cost<=0: continue
        recipe=m.get('recipe') or {}
        if not all(ores.get(k,0)>=v for k,v in recipe.items()): continue
        if bal-cost<150: continue                    # keep 150 SUBT reserve
        if m['id'] in state.get('uncraftable',()): continue   # SUBT-priced -> not_craftable
        sc,r=rpc('craft_miner',{'p_catalog_id':m['id']})
        log('BUY-MINER',m['id'],m['hash_rate'],'H/s cost',cost,'->',sc,jdump(r,150))
        if sc==200:
            bal-=cost
            for k,v in recipe.items(): ores[k]=ores.get(k,0)-v
        elif 'not_craftable' in str(r):
            state.setdefault('uncraftable',set()).add(m['id'])
        break                                          # one purchase per cycle

def my_miners():
    sc,d=table(f'miners?select=id,catalog_id,hash_rate,level,room_index,slot_index,is_listed,owner_id&owner_id=eq.{ME_ID}')
    return d if isinstance(d,list) else []

def assign_free_miners():
    """Every crafted miner MUST sit in a room slot to earn — assign any drifters."""
    mins=my_miners()
    placed={m['slot_index'] for m in mins if m.get('room_index')==1}
    free=sorted(set(range(10))-placed)          # 10 base slots in room 1
    changed=False
    for m in mins:
        if m.get('room_index') is None and not m.get('is_listed') and free:
            slot=free.pop(0)
            sc,r=rpc('assign_miner_slot',{'p_miner_id':m['id'],'p_room':1,'p_slot':slot})
            log('ASSIGN',m['catalog_id'],m['hash_rate'],'-> slot',slot,'->',sc,jdump(r,120))
            changed=True
    if changed: state['miners_dirty']=True
    return changed

def fuse_miners(prof):
    """Two identical same-level rigs -> one rig level+1 with 2.5x hashrate,
    freeing a slot. Always +EV when affordable; keeps one of each pair."""
    mins=[m for m in my_miners() if m.get('room_index')==1 and not m.get('is_listed')]
    bykey={}
    for m in mins: bykey.setdefault((m['catalog_id'],m['level']),[]).append(m)
    fees={m['id']:(m.get('fusion_fee_level2') or 0) for m in miner_catalog()}
    bal=prof.get('balance_native') or 0
    if time.time()<state.get('fuse_fail_until',0): return 0
    fused=0
    for (cat,lvl),group in bykey.items():
        fee=fees.get(cat) or 0
        # need fee + ore + healthy reserve; skip silently until affordable
        if len(group)<2 or bal < fee+300 or fused>=4: continue
        a,b=group[0],group[1]
        sc,r=rpc('fuse_miners',{'p_miner_a':a['id'],'p_miner_b':b['id']})
        log('FUSE',cat,'L'+str(lvl),'->',sc,jdump(r,150))
        if sc in (200,204):
            fused+=1; state['miners_dirty']=True
        else:
            msg=str(r)
            m_ore=re.search(r'insufficient_ore:\s*(\w+)',msg)
            if m_ore:
                buy_fusion_ore(m_ore.group(1),bal-fee-300)
                state['fuse_fail_until']=time.time()+120  # retry soon after buying
            elif 'insufficient_balance' in msg:
                state['fuse_fail_until']=time.time()+3600  # wait for SUBT accrual
            else:
                state['fuse_fail_until']=time.time()+600
            break
    return fused

def buy_fusion_ore(ore,max_spend):
    """Buy ~30 units of a fusion-blocking ore from cheapest NATIVE listings."""
    if max_spend<50: return 0
    sc,d=table(f"marketplace_listings?select=id,quantity,price_native,price_currency&status=eq.active&ore_id=eq.{ore}&price_currency=eq.NATIVE&order=price_native&limit=40")
    if not isinstance(d,list): return 0
    spent=0; bought=0
    for l in d:
        if bought>=30 or spent+l['price_native']>min(max_spend,400): break
        sc2,r=rpc('buy_marketplace_listing',{'p_listing_id':l['id'],'p_expected_price':l['price_native'],'p_expected_currency':l['price_currency']})
        if sc2==200: bought+=1; spent+=l['price_native'] or 0
        # stale/sold listing -> skip to next instead of aborting the batch
    if bought: log('BUY-ORE',ore,'x'+str(bought),'spent',spent)
    return bought

def manage_resonators(prof,items):
    """Craft cost-0 resonators when ore recipe is met, install into occupied slots."""
    sc,d=table('resonator_catalog?select=id,name,tier,recipe,craft_cost_native,bonus_pct&order=tier')
    if sc!=200 or not isinstance(d,list): return
    sc2,owned=table(f'resonators?select=id,catalog_id,level,room_index,slot_index&owner_id=eq.{ME_ID}')
    owned=owned if isinstance(owned,list) else []
    installed={(r.get('room_index'),r.get('slot_index')) for r in owned if r.get('room_index')}
    ores={o['catalog_id']:o['quantity'] for o in (items or {}).get('ores',[])}
    mins=[m for m in my_miners() if m.get('room_index')==1]
    for cat in d:
        if (cat.get('craft_cost_native') or 0)>0: continue
        if any(r.get('catalog_id')==cat['id'] for r in owned): continue  # one of each is enough for now
        recipe=cat.get('recipe') or {}
        if recipe and all(ores.get(k,0)>=v for k,v in recipe.items()):
            sc3,r=rpc('craft_resonator',{'p_catalog_id':cat['id']})
            log('CRAFT_RESO',cat['id'],'->',sc3,jdump(r,120))
            if sc3 in (200,204):
                for k,v in recipe.items(): ores[k]=ores.get(k,0)-v
                sc4,r2=table(f'resonators?select=id&owner_id=eq.{ME_ID}&catalog_id=eq.{cat["id"]}&order=crafted_at.desc&limit=1')
                rid=r2[0]['id'] if isinstance(r2,list) and r2 else None
                if rid:
                    # install into first miner slot lacking a resonator
                    for m in mins:
                        key=(1,m['slot_index'])
                        if key not in installed:
                            sc5,r3=rpc('install_resonator',{'p_resonator_id':rid,'p_room':1,'p_slot':m['slot_index']})
                            log('INSTALL_RESO',cat['id'],'slot',m['slot_index'],'->',sc5,jdump(r3,120))
                            installed.add(key)
                            break
                return

def open_crates(items):
    for c in (items or {}).get('crates') or []:
        cid=c.get('id')
        if not cid: continue
        sc,r=rpc('open_crate',{'p_crate_id':cid})
        log('OPEN_CRATE',cid[:8],'->',sc,jdump(r,200))

def claim_streak():
    sc,r=rpc('claim_daily_streak')
    if sc in (200,204): log('STREAK claim ->',sc,jdump(r,150))
    elif 'already' not in str(r).lower(): log('streak',sc,jdump(r,120))
    # weekly free rewards (faucet_6_days etc.) — cheap probe each cycle
    sc2,r2=rpc('claim_weekly_reward',{'p_reward_id':'faucet_6_days','p_week':None})
    if sc2 in (200,204): log('WEEKLY_REWARD ->',sc2,jdump(r2,200))

def ptc_worker():
    """Watch PTC ads via API: start_view -> wait duration -> claim_view.
    ~5 SUBT per ad per day; server enforces the timer."""
    done=state.setdefault('ptc_done',set())
    sc,d=rpc('ptc_available_ads')
    if not isinstance(d,list): return
    n=0
    for ad in d:
        aid=ad.get('id')
        if not aid or aid in done or n>=3: continue
        secs=int(ad.get('duration_seconds') or 5)+1
        sc1,r1=rpc('ptc_start_view',{'p_ad_id':aid})
        if sc1!=200:
            msg=str(r1)[:80]
            if 'already' in msg or 'own_ad' in msg: done.add(aid)
            continue
        time.sleep(min(secs,30))
        sc2,r2=rpc('ptc_claim_view',{'p_ad_id':aid})
        if sc2==200:
            rew=(r2 or {}).get('reward')
            log('PTC +%s SUBT (%s)'%(rew,ad.get('title','')[:30])); done.add(aid); n+=1
        else:
            msg=str(r2)[:80]
            if 'already' in msg or 'own_ad' in msg: done.add(aid)
            else: log('ptc claim err',sc2,msg)
    if n: state['ptc_dirty']=True

def foreman_sniper(items):
    """Sell surplus T1 ores to daily foreman orders for SUBT.
    Keeps a reserve for miner/resonator recipes; T2+ ores never sold."""
    today=time.strftime('%Y-%m-%d',time.gmtime())
    sc,d=table(f'foreman_orders?select=id,ore_id,unit_price,quantity,filled,per_player&day=eq.{today}')
    if not isinstance(d,list): return
    ores={o['catalog_id']:o['quantity'] for o in (items or {}).get('ores',[])}
    RESERVE={'coal':12,'copper':12,'sulfur':12,'tin':12}  # keep for T1 crafts
    for o in sorted(d,key=lambda x:-(x.get('unit_price') or 0)):
        oid=o.get('ore_id'); left=(o.get('quantity') or 0)-(o.get('filled') or 0)
        cap=o.get('per_player') or 999
        sell=min(left,cap,max(0,ores.get(oid,0)-RESERVE.get(oid,999)))
        if sell<=0 or oid not in RESERVE: continue
        sc2,r=rpc('foreman_sell',{'p_order_id':o['id'],'p_quantity':int(sell)})
        log('FOREMAN sell',sell,'x',oid,'@',o['unit_price'],'->',sc2,jdump(r,150))
        if sc2 in (200,204): ores[oid]=ores.get(oid,0)-int(sell)

def _inv_map(items):
    """catalog_id -> spendable qty for P2P trades. Reserves kept for ores,
    listed/placed items excluded, equipped pickaxe never spendable."""
    inv={}
    res=_ore_reserves()
    for o in items.get('ores',[]):
        oid=o.get('catalog_id'); q=o.get('quantity',0) or 0
        inv[oid]=max(0,q-(res.get(oid) or 0))
    sc,ls=table(f"marketplace_listings?select=ore_id,quantity&status=eq.active&item_type=eq.ore&seller_id=eq.{ME_ID}")
    if isinstance(ls,list):
        for l in ls:
            oid=l.get('ore_id')
            if oid in inv: inv[oid]=max(0,inv[oid]-(l.get('quantity') or 0))
    for k in ('bombs','crates','resonators'):
        for it in items.get(k) or []:
            cid=it.get('catalog_id')
            if cid: inv[cid]=inv.get(cid,0)+1
    for p in items.get('pickaxes') or []:
        cid=p.get('catalog_id')
        if cid and not p.get('equipped'): inv[cid]=inv.get(cid,0)+1
    placed=set(); listed_m=set()
    sc,ms=table(f"miners?select=id&owner_id=eq.{ME_ID}&room_index=not.is.null")
    if isinstance(ms,list): placed={m['id'] for m in ms}
    sc2,ml=table(f"marketplace_listings?select=miner_id&status=eq.active&item_type=eq.miner&seller_id=eq.{ME_ID}")
    if isinstance(ml,list): listed_m={l['miner_id'] for l in ml}
    for m in items.get('miners') or []:
        if m.get('id') in placed or m.get('id') in listed_m: continue
        cid=m.get('catalog_id')
        if cid: inv[cid]=inv.get(cid,0)+1
    return inv

_KIND_MAP={'ore':'ores','miner':'miners','pickaxe':'pickaxes','bomb':'bombs','crate':'crates','resonator':'resonators'}
def _want_fulfillable(want,inv):
    for w in want:
        kind=w.get('kind'); cid=w.get('catalog_id'); qty=w.get('quantity') or 1
        if kind not in _KIND_MAP or not cid: return False
        if inv.get(cid,0)<qty: return False
    return True

def market_sniper(prof,items):
    """Accept P2P trade offers with >=10% server-side value margin that we can
    fully fulfill from unlisted/unplaced inventory. One accept per cycle."""
    sc,d=rpc('trade_offers_browse',{})
    if not isinstance(d,list): return
    inv=_inv_map(items)
    for o in d:
        if o.get('status')!='active': continue
        gv=o.get('give_value') or 0; wv=o.get('want_value') or 0
        if wv<=0 or gv<wv*1.10: continue
        want=o.get('want') or []
        if not want or not _want_fulfillable(want,inv): continue
        sc2,r=rpc('accept_trade_offer',{'p_offer_id':o['id']})
        log('OFFER accept',o['id'][:8],'margin',int(gv-wv),
            'give',[(g.get('name'),g.get('quantity')) for g in o.get('give',[])],
            'want',[(w.get('name'),w.get('quantity')) for w in want],
            '->',sc2,jdump(r,150))
        return  # re-evaluate inventory next loop

_TOPUP=[('coal',10),('copper',10),('sulfur',10),('tin',10)]
def offer_creator(items):
    """Create a P2P trade offer when we have no active one. Bait priority:
    snowballs (seasonal demand) > T3+ ore surplus. Want: best hashrate miner
    (T1-T3) + T1 top-up ores, chosen via trade_quote so want_value ~= give_value.
    Never asks for T4/T5 or real-money items; one active offer at a time."""
    sc,d=rpc('trade_my_offers')
    if isinstance(d,dict) and d.get('active'):
        return  # one offer at a time
    cat=_ore_tiers(); res=_ore_reserves()
    bait=None
    for o in items.get('ores',[]):
        oid=o.get('catalog_id'); q=o.get('quantity',0) or 0
        if oid=='snowball' and q>=3:
            bait={'kind':'ore','catalog_id':'snowball','quantity':min(q,9)}; break
    if not bait:
        for o in items.get('ores',[]):
            oid=o.get('catalog_id'); q=o.get('quantity',0) or 0
            surplus=q-(res.get(oid) or 0)
            if (cat.get(oid) or {}).get('tier',0)>=3 and surplus>=2:
                bait={'kind':'ore','catalog_id':oid,'quantity':surplus}; break
    if not bait: return
    g=[bait]
    sc,q=rpc('trade_quote',{'p_give':g,'p_want':[{'kind':'ore','catalog_id':'coal','quantity':1}]})
    if sc!=200 or not isinstance(q,dict): return
    gv=q.get('give_value') or 0
    if gv<200: return  # not worth locking items for
    topup=[{'kind':'ore','catalog_id':x,'quantity':n} for x,n in _TOPUP]
    best=None
    tried=0
    for m in sorted(miner_catalog(),key=lambda m:-(m.get('hash_rate') or 0)):
        if (m.get('tier') or 0)>=4: continue
        tried+=1
        if tried>14: break
        want=[{'kind':'miner','catalog_id':m['id'],'quantity':1}]+topup
        sc2,q2=rpc('trade_quote',{'p_give':g,'p_want':want})
        if sc2!=200 or not isinstance(q2,dict): continue
        wv=q2.get('want_value') or 0
        if q2.get('balanced') and wv>=gv*0.9:
            best=want; break
    if not best:
        # fallback: T1 ores only, qty scaled to ~give value (10 value/ore)
        per=max(1,int(gv/40))
        best=[{'kind':'ore','catalog_id':x,'quantity':per} for x,_ in _TOPUP]
        sc2,q2=rpc('trade_quote',{'p_give':g,'p_want':best})
        if sc2!=200 or not isinstance(q2,dict) or (q2.get('want_value') or 0)<gv*0.8:
            return
    key='offer_day_'+time.strftime('%Y-%m-%d')
    if state.get(key)==bait['catalog_id']: return
    sc3,r=rpc('create_trade_offer',{'p_give':g,'p_want':best})
    log('OFFER create give',bait['catalog_id'],'x'+str(bait['quantity']),'want',
        [(w.get('catalog_id'),w.get('quantity')) for w in best],'->',sc3,jdump(r,150))
    if sc3==200: state[key]=bait['catalog_id']

def items_watch(prof=None):
    sc,d=rpc('trade_my_items')
    if not isinstance(d,dict): return d
    for k in ('ores','bombs','crates','pickaxes','resonators','miners'):
        d[k]=[x for x in (d.get(k) or []) if isinstance(x,dict)]
    miners=d.get('miners') or []
    broken_miners=[m for m in miners if m.get('broken') or m.get('is_broken')]
    if broken_miners: log('broken miners:',[m.get('name') for m in broken_miners])
    # resonators/crates/bombs counts for visibility
    log('inv: ores=%d miners=%d pickaxes=%d res=%d crates=%d bombs=%d'%(
        sum(o.get('quantity',0) for o in d.get('ores',[])),
        len(miners),len(d.get('pickaxes') or []),
        len(d.get('resonators') or []),len(d.get('crates') or []),len(d.get('bombs') or [])))
    return d

_ore_cat={'t':0,'data':{}}
def _ore_tiers():
    if time.time()-_ore_cat['t']<3600 and _ore_cat['data']: return _ore_cat['data']
    sc,d=table('ore_catalog?select=id,tier,min_sale_price,season_id')
    _ore_cat['t']=time.time()
    _ore_cat['data']={o['id']:o for o in (d or [])}
    return _ore_cat['data']

_ore_res={'t':0,'data':{}}
def _ore_reserves():
    """Max ore qty needed by any craft recipe (+coal buffer for fusion)."""
    if time.time()-_ore_res['t']<3600 and _ore_res['data']: return _ore_res['data']
    res={}
    for m in miner_catalog():
        for k,v in (m.get('recipe') or {}).items(): res[k]=max(res.get(k,0),v)
    sc,rd=table('resonator_catalog?select=recipe')
    for cat in (rd if isinstance(rd,list) else []):
        for k,v in (cat.get('recipe') or {}).items(): res[k]=max(res.get(k,0),v)
    res['coal']=res.get('coal',0)+15   # fusion consumes coal beyond craft recipes
    _ore_res['t']=time.time(); _ore_res['data']=res
    return res

def market_ore_seller(items):
    """Sell T3+ fully + T1/T2 surplus above craft reserves — pure SUBT at min_sale."""
    cat=_ore_tiers(); res=_ore_reserves()
    listed=state.setdefault('ore_listed',{})
    today=time.strftime('%Y-%m-%d')
    for o in items.get('ores',[]):
        oid=o.get('catalog_id'); qty=o.get('quantity',0)
        c=cat.get(oid) or {}
        if c.get('season_id') or qty<=0: continue
        tier=c.get('tier') or 0
        sell_qty=qty if tier>=3 else qty-(res.get(oid) or 0)
        if sell_qty<=0: continue
        key=oid+':'+str(tier)
        # re-list only if excess grew meaningfully since last listing
        if listed.get(key)==today and (listed.get(key+'_q') or 0)>=sell_qty: continue
        price=(c.get('min_sale_price') or 0)*sell_qty
        if price<=0: continue
        # alternate NATIVE/DOGE — DOGE sales feed the withdrawal balance directly.
        # price is SUBT-floor; crypto listings MUST be oracle-converted or they
        # are ~600x overpriced and never sell (bug fixed 2026-11-18).
        ccy='DOGE' if state.get('ore_ccy_idx',0)%2 else 'NATIVE'
        lprice=price
        if ccy!='NATIVE':
            rate=(_exchange_rates().get(ccy) or 0)
            if rate>0: lprice=round(price/rate,8)
            else: ccy='NATIVE'; lprice=price
        sc,r=rpc('list_marketplace_ore_lots',{'p_ore_id':oid,'p_lot_quantity':sell_qty,'p_lots':1,'p_price_native':lprice,'p_price_currency':ccy})
        log('LIST-ORE',oid,'x'+str(sell_qty),'@'+str(int(price)),'SUBT-equiv',ccy,'->',sc,str(r)[:120])
        if sc==200:
            state['ore_ccy_idx']=state.get('ore_ccy_idx',0)+1
            listed[key]=today; listed[key+'_q']=sell_qty

def listing_repricer():
    """Undercut stale ore listings: if a rival lists same ore+currency cheaper,
    cancel+relist ~3% below rival (floor = catalog min_sale*qty). Max 1 reprice
    per listing per 12h; skips when already competitive or no rival exists."""
    sc,d=table(f'marketplace_listings?select=id,ore_id,quantity,price_native,price_currency,created_at&seller_id=eq.{ME_ID}&status=eq.active&item_type=eq.ore')
    if not isinstance(d,list): return
    import datetime
    now=time.time()
    for l in d:
        try:
            age_h=(now-datetime.datetime.fromisoformat(str(l['created_at']).replace('Z','+00:00')).timestamp())/3600
        except Exception: continue
        if age_h<12: continue
        key='repr_'+l['id']
        if now-state.get(key,0)<43200: continue
        oid=l.get('ore_id'); ccy=l.get('price_currency') or 'NATIVE'
        if not oid: continue
        sc2,r=table(f"marketplace_listings?select=price_native&status=eq.active&item_type=eq.ore&ore_id=eq.{oid}&price_currency=eq.{ccy}&seller_id=neq.{ME_ID}&order=price_native.asc&limit=1")
        if not (isinstance(r,list) and r): continue
        rival=r[0].get('price_native') or 0
        ours=l.get('price_native') or 0
        if rival<=0 or ours<=rival*1.08: continue
        cat=_ore_tiers().get(oid) or {}
        floor=(cat.get('min_sale_price') or 0)*(l.get('quantity') or 1)
        newp=max(floor,rival*0.97)
        if newp>=ours*0.92 or newp<=0: continue
        sc3,c=rpc('cancel_marketplace_listing',{'p_listing_id':l['id']})
        if sc3!=200:
            log('REPRICE cancel fail',str(l['id'])[:8],sc3,str(c)[:100]); continue
        sc4,rr=rpc('list_marketplace_ore_lots',{'p_ore_id':oid,'p_lot_quantity':l.get('quantity'),'p_lots':1,'p_price_native':newp,'p_price_currency':ccy})
        log('REPRICE',oid,'x'+str(l.get('quantity')),'@'+str(int(ours)),'->@'+str(int(newp)),ccy,'->',sc4,str(rr)[:100])
        state[key]=now


def race_sprint(items):
    """Race day: dump sellable ore into NATIVE listings at min_sale so SUBT
    lands fast -> fuels mine3d_recharge -> more race swings. Skips ores that
    already have an active NATIVE listing (no double-listing)."""
    cat=_ore_tiers(); res=_ore_reserves()
    sc,d=table(f'marketplace_listings?select=ore_id&status=eq.active&item_type=eq.ore&price_currency=eq.NATIVE&seller_id=eq.{ME_ID}')
    have={l.get('ore_id') for l in d} if isinstance(d,list) else set()
    for o in items.get('ores',[]):
        oid=o.get('catalog_id'); qty=o.get('quantity',0)
        c=cat.get(oid) or {}
        if c.get('season_id') or qty<=0 or oid in have: continue
        tier=c.get('tier') or 0
        sell_qty=qty if tier>=3 else qty-(res.get(oid) or 0)
        if sell_qty<=0: continue
        price=(c.get('min_sale_price') or 0)*sell_qty
        if price<=0: continue
        sc,r=rpc('list_marketplace_ore_lots',{'p_ore_id':oid,'p_lot_quantity':sell_qty,'p_lots':1,'p_price_native':price,'p_price_currency':'NATIVE'})
        log('RACE-SPRINT',oid,'x'+str(sell_qty),'@'+str(int(price)),'NATIVE ->',sc,str(r)[:100])


def fix_crypto_listings():
    """Cancel+relist our crypto-priced ore listings that are >2x the oracle-
    equivalent SUBT floor. Legacy listings priced 'min_sale SUBT but labeled
    DOGE' sit ~600x too high and never sell — this converts dead listings
    into real DOGE sales (direct FP fuel)."""
    rates=_exchange_rates(); cat=_ore_tiers()
    sc,d=table(f'marketplace_listings?select=id,ore_id,quantity,price_native,price_currency,created_at&seller_id=eq.{ME_ID}&status=eq.active&item_type=eq.ore&price_currency=neq.NATIVE')
    if not isinstance(d,list): return
    import datetime
    now=time.time()
    for l in d:
        ccy=l.get('price_currency'); rate=rates.get(ccy) or 0
        oid=l.get('ore_id'); qty=l.get('quantity') or 1
        c=cat.get(oid) or {}
        floor=(c.get('min_sale_price') or 0)*qty
        if rate<=0 or floor<=0: continue
        fair=floor/rate
        ours=l.get('price_native') or 0
        if ours<=fair*2.5: continue   # within tolerance — leave it
        # stale listing guard: don't churn listings <10min old
        try:
            age=(now-datetime.datetime.fromisoformat(str(l['created_at']).replace('Z','+00:00')).timestamp())/60
            if age<10: continue
        except Exception: pass
        sc3,rr=rpc('cancel_marketplace_listing',{'p_listing_id':l['id']})
        if sc3!=200:
            log('FX-LIST cancel fail',str(l['id'])[:8],sc3,str(rr)[:100]); continue
        sc4,r2=rpc('list_marketplace_ore_lots',{'p_ore_id':oid,'p_lot_quantity':qty,'p_lots':1,'p_price_native':round(fair,8),'p_price_currency':ccy})
        log('FX-LIST',oid,'x'+str(qty),ccy,'@'+str(ours),'->@'+str(round(fair,6)),sc4,str(r2)[:100])

def ore_flip_sniper(prof):
    """Buy NATIVE ore listings priced <=55% of catalog min_sale*qty.
    Bought ore lands in inventory -> market_ore_seller relists at min_sale
    automatically = pure spread. One buy/cycle, <=120 SUBT, 60 reserve."""
    bal=prof.get('balance_native') or 0
    if bal<160: return
    cat=_ore_tiers()
    sc,d=table(f"marketplace_listings?select=id,ore_id,quantity,price_native,price_currency,seller_id&status=eq.active&item_type=eq.ore&price_currency=eq.NATIVE&seller_id=neq.{ME_ID}&order=price_native.asc&limit=60")
    if not isinstance(d,list): return
    best=None; bestdisc=0
    for l in d:
        c=cat.get(l.get('ore_id')) or {}
        floor=(c.get('min_sale_price') or 0)*(l.get('quantity') or 1)
        price=l.get('price_native') or 0
        if floor<=0 or price<=0 or price>bal-60 or price>120: continue
        disc=1-price/floor
        if disc>bestdisc: bestdisc=disc; best=l
    if best and bestdisc>=0.45:
        fl=(cat.get(best.get('ore_id')) or {}).get('min_sale_price') or 0
        sc3,r=rpc('buy_marketplace_listing',{'p_listing_id':best['id'],'p_expected_price':best['price_native'],'p_expected_currency':'NATIVE'})
        log('ORE-FLIP',best.get('ore_id'),'x'+str(best.get('quantity')),'@'+str(best.get('price_native')),'floor~'+str(int(fl*best.get('quantity',1))),'->',sc3,jdump(r,140))

def _exchange_rates():
    """Public oracle: SUBT per 1 unit of each crypto (rate_to_native)."""
    sc,d=table('exchange_rates?select=currency,rate_to_native')
    if not isinstance(d,list): return {}
    return {r['currency']:(r.get('rate_to_native') or 0) for r in d}

_CC_BAL={'DOGE':'balance_doge','LTC':'balance_ltc','SOL':'balance_sol','TRX':'balance_trx','XRP':'balance_xrp'}

def cross_currency_sniper(prof):
    """Buy ore listings priced in crypto when crypto_price*rate_to_native <= 55%
    of catalog min_sale*qty - seller underpriced vs NATIVE floor.
    Spends crypto balances, ore relists via market_ore_seller = portfolio rotation."""
    rates=_exchange_rates()
    if not rates: return
    cat=_ore_tiers()
    best=None; best_disc=0; best_subt=0
    for cc,balkey in _CC_BAL.items():
        rate=rates.get(cc) or 0
        cbal=prof.get(balkey) or 0
        if rate<=0 or cbal<=0: continue
        sc,d=table(f"marketplace_listings?select=id,ore_id,quantity,price_native,price_currency,seller_id&status=eq.active&item_type=eq.ore&price_currency=eq.{cc}&seller_id=neq.{ME_ID}&order=price_native.asc&limit=30")
        if not isinstance(d,list): continue
        for l in d:
            price=l.get('price_native') or 0
            if price<=0 or price>cbal: continue
            subt_eq=price*rate
            floor=((cat.get(l.get('ore_id')) or {}).get('min_sale_price') or 0)*(l.get('quantity') or 1)
            if floor<=0: continue
            disc=1-subt_eq/floor
            if disc>best_disc:
                best_disc=disc; best=l; best_subt=subt_eq
    if best and best_disc>=0.45:
        cc=best.get('price_currency')
        sc3,r=rpc('buy_marketplace_listing',{'p_listing_id':best['id'],'p_expected_price':best['price_native'],'p_expected_currency':cc})
        log('XCCY',cc,best.get('ore_id'),'x'+str(best.get('quantity')),'@'+str(best.get('price_native')),
            'subt_eq~'+str(int(best_subt)),'disc~'+str(int(best_disc*100))+'%','->',sc3,jdump(r,140))

def miner_market_sniper(prof):
    """Buy underpriced miner listings on the open market. EV rule: only T3+
    (we craft/fuse T1-T2 cheaper ourselves) and only when price <= 50% of the
    miner's craft_cost_native — i.e. someone dumping below material cost.
    Keeps a 400 SUBT reserve; max 25k SUBT per purchase; NATIVE only."""
    bal=prof.get('balance_native') or 0
    if bal<600: return
    sc,d=table(f"marketplace_listings?select=id,miner_id,price_native,price_currency,created_at&status=eq.active&item_type=eq.miner&seller_id=neq.{ME_ID}&order=price_native.asc&limit=15")
    if not isinstance(d,list): return
    cat={m['id']:m for m in miner_catalog()}
    for l in d:
        if (l.get('price_currency') or 'NATIVE')!='NATIVE': continue
        price=l.get('price_native') or 0
        mid=l.get('miner_id')
        if not mid or price<=0: continue
        sc2,m=table(f"miners?select=catalog_id,hash_rate,level&id=eq.{mid}")
        if not (isinstance(m,list) and m): continue
        m=m[0]; cm=cat.get(m.get('catalog_id')) or {}
        tier=cm.get('tier') or 0
        cost=cm.get('craft_cost_native') or 0
        hr=m.get('hash_rate') or cm.get('hash_rate') or 0
        if tier<3 or cost<=0: continue
        if price>cost*0.5 or price>bal-400 or price>25000: continue
        sc3,r=rpc('buy_marketplace_listing',{'p_listing_id':l['id'],'p_expected_price':price,'p_expected_currency':'NATIVE'})
        log('MINER-BUY',cm.get('name'),hr,'H/s @',int(price),'(craft',int(cost),') ->',sc3,jdump(r,150))
        return  # one purchase per cycle, re-check balance next loop

def race_watch():
    """Dig race standings — prize is real SUBT (rank2 today = 1000)."""
    sc,d=rpc('mine_race_board',{})
    if not isinstance(d,dict): return
    me=d.get('me') or {}
    rank=me.get('rank')
    if rank and rank<=10:
        top=(d.get('top') or [])
        mine=[t for t in top if t.get('me')]
        prize=(mine[0].get('prize') if mine else None)
        lead=top[0] if top else {}
        log('RACE rank',rank,'/',len(top),'prize',prize,
            'swings',me.get('swings'),'leader',lead.get('swings'),'@',lead.get('username'))

def main():
    log('=== sub_api_autopilot start ===')
    last_items=0
    while True:
        try:
            prof=my_profile()
            if not prof:
                state['auth_fails']=state.get('auth_fails',0)+1
                log('profile fetch failed — creds may need refresh (x%d)'%state['auth_fails'])
                if state['auth_fails']>=5 and not state.get('reauth_running'):
                    state['reauth_running']=True
                    log('auto-reauth: launching sub_reauth.py via CDP browser')
                    import subprocess
                    try:
                        r=subprocess.run(['/tmp/pwenv/bin/python','/tmp/sub_reauth.py'],
                                         capture_output=True,text=True,timeout=180)
                        log('reauth result:',(r.stdout+r.stderr).strip()[:300])
                    except Exception as e:
                        log('reauth err',repr(e)[:150])
                    state['reauth_running']=False; state['auth_fails']=0
                time.sleep(30); continue
            state['auth_fails']=0
            if prof.get('is_banned'): log('BANNED — stopping'); break
            log('bal',prof.get('balance_native'),'lvl',prof.get('level'),'taps',prof.get('daily_taps'),'streak',prof.get('streak_day'))
            claim_daily_quests()
            claim_pass()
            claim_streak()
            ptc_worker()
            manage_pickaxes(prof)
            trade_watch(prof)
            items=items_watch(prof)
            if items:
                craft_free_miners(prof,items)
                craft_paid_miners(prof,items)
                # opportunistic mine boost (extra hits/yield) when flush
                if prof.get('balance_native',0)>800 and state.get('boost_day')!=time.strftime('%Y-%m-%d'):
                    sc,r=rpc('buy_mine_boost',{})
                    if sc==200: state['boost_day']=time.strftime('%Y-%m-%d'); log('BOOST bought ->',jdump(r,120))
                    elif 'insufficient' not in str(r).lower(): log('BOOST err',sc,str(r)[:100])
                market_ore_seller(items)
                race_sprint(items)
                fix_crypto_listings()
                market_sniper(prof,items)
                offer_creator(items)
                manage_resonators(prof,items)
                open_crates(items)
                foreman_sniper(items)
            listing_repricer()
            race_watch()
            miner_market_sniper(prof)
            ore_flip_sniper(prof)
            cross_currency_sniper(prof)
            assign_free_miners()
            fuse_miners(prof)
            # crypto pool balances — first real-money rail
            cb={k:prof.get(k) for k in ('balance_doge','balance_ltc','balance_sol','balance_trx','balance_xrp')}
            cb={k:v for k,v in cb.items() if v}
            if cb: log('CRYPTO',json.dumps(cb))
            # auto-withdraw: DOGE pool -> Coinbase deposit addr when >= ~$0.02 (~0.34 DOGE)
            try:
                # withdraw needs local browser (CDP) — GH runner has none;
                # local doge_watch.py handles it via heartbeat balance
                if not os.path.exists('/tmp/pwenv/bin/python'):
                    doge=0.0
                else:
                    doge=float(prof.get('balance_doge') or 0)
                marker='/tmp/sub_doge_withdrawn.flag'
                stale=(not os.path.exists(marker)) or (time.time()-os.path.getmtime(marker)>7200)
                if doge>=0.36 and stale:
                    amt=max(0.34,round(doge-0.005,6))
                    log('DOGE threshold hit',doge,'— FP withdraw',amt,'-> gabrielgtx')
                    import subprocess
                    r=subprocess.run(['/tmp/pwenv/bin/python','/tmp/sub_wd_fp.py','DOGE',str(amt),'gabrielgtx'],
                                     capture_output=True,text=True,timeout=180)
                    out=(r.stdout+r.stderr).strip()
                    log('withdraw result:',out[:400])
                    if 'Withdrawal sent' in out or 'Sent' in out:
                        open(marker,'w').write(str(doge))
                    else:
                        log('withdraw NOT confirmed — will retry next cycle')
            except Exception as e:
                log('withdraw check err',repr(e)[:120])
            last_items=time.time()
        except Exception as e:
            log('ERR',repr(e)[:200]); traceback.print_exc()
        # turbo window 00:00-00:10 UTC — foreman orders renew ~00:01 and
        # sell out in minutes; poll fast to snipe them
        mins=time.gmtime().tm_hour*60+time.gmtime().tm_min
        sleep_s=12 if mins<10 else POLL
        time.sleep(sleep_s)

if __name__=='__main__':
    main()
