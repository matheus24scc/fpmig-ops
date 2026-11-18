import json,urllib.request,time,datetime,os,sys,uuid
sys.path.insert(0,'/tmp')
LOG=open('/tmp/cb_monitor.log','a',buffering=1)
SIG='/tmp/cb_signals.json'
POSF='/tmp/cb_positions.json'
BUY_USDC=1.20          # conservative size — only fires when USDC covers it
MAX_POS=2              # max concurrent auto positions
def log(*a):
    s=f"[{datetime.datetime.now().strftime('%m-%d %H:%M')}] "+' '.join(map(str,a))
    print(s,flush=True); LOG.write(s+'\n')
PAIRS="BTC ETH SOL XRP DOGE ADA AVAX LINK LTC BCH UNI AAVE ALGO SUI NEAR ATOM FIL APT ARB OP INJ TIA SEI WLD IMX TRX SHIB PEPE DOT POL ICP XLM HBAR VET EOS CRV MKR SNX COMP SUSHI ZRX BAT ENJ CHZ GRT LDO RNDR APE SAND MANA EGLD KAS QNT CELR ZEC".split()
UNIF='/tmp/cb_universe.json'
def universe():
    """ALL online USD products on Coinbase Exchange, pre-filtered by 24h
    USD volume > $200k (same threshold analyze() applies). Refreshed hourly."""
    try:
        u=json.load(open(UNIF))
        if time.time()-u.get('ts',0)<3600 and u.get('pairs'): return u['pairs']
    except Exception: pass
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(
            'https://api.exchange.coinbase.com/products',
            headers={'User-Agent':'Mozilla/5.0'}),timeout=20))
    except Exception as e:
        log('universe products err',str(e)[:80]); return PAIRS
    prods=[p['id'] for p in d if p.get('status')=='online'
           and p.get('quote_currency')=='USD'
           and '-' in p['id']]
    keep=set(PAIRS); n=0
    for pid in prods:
        base=pid.split('-')[0]
        if base in keep: continue
        try:
            t=json.load(urllib.request.urlopen(urllib.request.Request(
                f'https://api.exchange.coinbase.com/products/{pid}/ticker',
                headers={'User-Agent':'Mozilla/5.0'}),timeout=8))
            px=float(t.get('price') or 0); vol=float(t.get('volume') or 0)
            if px*vol>200000 or (base in PROVEN_HOOK and px*vol>20000): keep.add(base)
        except Exception: pass
        n+=1
        if n%50==0: time.sleep(0.3)
    out=sorted(keep)
    try: json.dump({'ts':time.time(),'pairs':out},open(UNIF,'w'))
    except Exception: pass
    log(f'universe: {len(out)} pairs ({len(prods)} products scanned)')
    return out
# coinbase -> hyperliquid name map (funding source)
HL_MAP={'SHIB':'kSHIB','PEPE':'kPEPE','POL':'MATIC','RNDR':'RENDER','BTC':'BTC','ETH':'ETH','SOL':'SOL','XRP':'XRP','DOGE':'DOGE','ADA':'ADA','AVAX':'AVAX','LINK':'LINK','LTC':'LTC','BCH':'BCH','UNI':'UNI','AAVE':'AAVE','ALGO':'ALGO','SUI':'SUI','NEAR':'NEAR','ATOM':'ATOM','FIL':'FIL','APT':'APT','ARB':'ARB','OP':'OP','INJ':'INJ','TIA':'TIA','SEI':'SEI','WLD':'WLD','IMX':'IMX','TRX':'TRX','DOT':'DOT','ICP':'ICP','XLM':'XLM','HBAR':'HBAR','VET':'VET','EOS':'EOS','CRV':'CRV','MKR':'MKR','SNX':'SNX','COMP':'COMP','SUSHI':'SUSHI','ZRX':'ZRX','BAT':'BAT','ENJ':'ENJ','CHZ':'CHZ','GRT':'GRT','LDO':'LDO','APE':'APE','SAND':'SAND','MANA':'MANA','EGLD':'EGLD','KAS':'KAS','QNT':'QNT','CELR':'CELR','ZEC':'ZEC'}
_fund_cache={'t':0,'d':{}}
def funding():
    if time.time()-_fund_cache['t']<240 and _fund_cache['d']: return _fund_cache['d']
    try:
        req=urllib.request.Request("https://api.hyperliquid.xyz/info",
            data=json.dumps({"type":"metaAndAssetCtxs"}).encode(),
            headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
        d=json.load(urllib.request.urlopen(req,timeout=20))
        m={}
        for u,c in zip(d[0]['universe'],d[1]):
            try: m[u['name']]=float(c.get('funding',0))*24*365*100  # %/yr
            except: pass
        _fund_cache['t']=time.time(); _fund_cache['d']=m
        return m
    except Exception as e:
        log("funding fetch err",str(e)[:80]); return _fund_cache['d']
def candles(prod,gran=3600,n=80):
    end=int(time.time()); start=end-gran*n
    url=f"https://api.exchange.coinbase.com/products/{prod}-USD/candles?granularity={gran}&start={start}&end={end}"
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    try:
        d=json.load(urllib.request.urlopen(req,timeout=15)); d.sort(key=lambda c:c[0]); return d
    except Exception: return None
def rsi(closes,p=14):
    if len(closes)<p+1: return None
    g=[];l=[]
    for i in range(1,len(closes)):
        ch=closes[i]-closes[i-1]; g.append(max(ch,0)); l.append(max(-ch,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 100.0 if al==0 else 100-100/(1+ag/al)
def analyze(pair,fund):
    c1=candles(pair,3600,100)
    if not c1 or len(c1)<50: return None
    closes=[x[4] for x in c1]; vols=[x[5] for x in c1]
    highs=[x[2] for x in c1]; lows=[x[1] for x in c1]
    r1=rsi(closes)
    if r1 is None: return None
    # --- 4H timeframe ---
    c4=candles(pair,14400,60)
    r4=None
    if c4 and len(c4)>=20:
        r4=rsi([x[4] for x in c4])
    # --- distance to 7d low (1h candles ~168h, we have 100 -> use available) ---
    lo7=min(lows); px=closes[-1]
    dist_low=(px/lo7-1)*100 if lo7 else 999
    # --- higher low: last3 lows >= min of prior 12 ---
    higher_low = min(lows[-3:]) >= min(lows[-15:-3])*0.999
    # --- reversal candle last 3h ---
    rev=False; why=''
    vavg=sum(vols[-40:-5])/35 if len(vols)>40 else 1
    for i in range(-3,0):
        o,h,l,cl,v=c1[i][3],c1[i][2],c1[i][1],c1[i][4],c1[i][5]
        body=(cl-o)/o*100; wick=(min(o,cl)-l)/l*100 if l else 0
        vr=v/vavg if vavg else 0
        if body>0.8 or (wick>1.5 and body>-0.5 and vr>1.5):
            rev=True; why=f"b{body:+.1f}% w{wick:.1f}% v{vr:.1f}x"; break
    # --- volume climax then dry-up: max vol last 15h was >2x avg, last 3h avg < 0.8x avg ---
    climax=False; dry=False
    if len(vols)>20:
        vbase=sum(vols[-45:-15])/30
        peak=max(vols[-15:])
        recent3=sum(vols[-3:])/3
        climax = peak > 2*vbase if vbase else False
        dry = recent3 < 0.9*vavg if vavg else False
    # --- stable last 3h ---
    stable3 = closes[-1] >= closes[-4]*0.985
    chg24=(closes[-1]/closes[-25]-1)*100 if len(closes)>25 else 0
    # --- liquidity filter: avg USD volume last 24h must clear minimum ---
    if len(vols)>=24:
        usd_vol=sum(v*closes[i] for i,v in enumerate(vols[-24:],start=len(vols)-24))/24
        if usd_vol<200000 and (usd_vol<20000 or pair.split('-')[0] not in PROVEN_HOOK): return None   # thin books — spread eats small trades (PROVEN_HOOK exempt >$20k/d)
    # --- funding for this coin (annualized %) ---
    hl=HL_MAP.get(pair); f=fund.get(hl) if hl else None
    # ===== SCORE (max 12) =====
    score=0; reasons=[]
    if r1<20: score+=2; reasons.append('rsi1h<20')
    elif r1<30: score+=1; reasons.append('rsi1h<30')
    if r4 is not None:
        if r4<30: score+=1; reasons.append('rsi4h<30')
        elif r4<40: score+=0.5; reasons.append('rsi4h<40')
    if dist_low<4: score+=2; reasons.append('near7dlow')
    elif dist_low<7: score+=1; reasons.append('nearlow')
    if higher_low: score+=2; reasons.append('higherlow')
    if rev: score+=2; reasons.append('reversal')
    if climax and dry: score+=1; reasons.append('climax+dry')
    if stable3: score+=1; reasons.append('stable3h')
    if f is not None:
        if f<0: score+=1; reasons.append(f'fund{f:+.0f}%')
        elif f>15: score-=1; reasons.append(f'fund{f:+.0f}%')
    # --- daily timeframe: THE validated pattern (RSI14d<30 -> 2d bounce, ~400d backtest)
    r_d=None; r_d_prev=None
    cd=candles(pair,86400,40)
    if cd and len(cd)>=20:
        dc=[x[4] for x in cd]
        r_d=rsi(dc)
        if len(dc)>=21: r_d_prev=rsi(dc[:-1])
    two_down_d = cd is not None and len(cd)>=20 and dc[-1]<dc[-2]<dc[-3]
    hook_d = r_d is not None and r_d_prev is not None and r_d>r_d_prev
    # capitulation-reclaim (edge family #2): last COMPLETED day dumped <=-7%
    # on >=2.5x median volume, and today's candle reclaims above that open
    capit_d=False
    if cd is not None and len(cd)>=23:
        cap=cd[-2]; today=cd[-1]
        if cap[3] and cap[4] and today[4]:
            ret=cap[4]/cd[-3][4]-1 if cd[-3][4] else 0
            vols=[x[5] or 0 for x in cd[-22:-2] if (x[5] or 0)>0]
            med=sorted(vols)[len(vols)//2] if vols else 0
            capit_d = ret<=-0.07 and med>0 and (cap[5] or 0)>=2.5*med and today[4]>cap[3]
    body1=(closes[-1]-c1[-1][3])/c1[-1][3]*100 if c1[-1][3] else 0
    return dict(pair=pair,rsi1=r1,rsi4=r4,rsi_d=r_d,r_d_prev=r_d_prev,two_down_d=two_down_d,hook_d=hook_d,capit_d=capit_d,dist_low=dist_low,higher_low=higher_low,
                rev=rev,why=why,climax=climax,dry=dry,stable3=stable3,chg24=chg24,
                px=px,funding=f,score=score,reasons=reasons,body1=body1)
def load_signals():
    try: return json.load(open(SIG))
    except Exception: return []
def save_signals(s):
    try: json.dump(s,open(SIG,'w'))
    except Exception: pass
def track_signals(cands):
    """Persist score>=7 candidates; measure outcome +2h/+24h vs entry price."""
    sigs=load_signals(); now=time.time(); changed=False
    # resolve old signals
    for s in sigs:
        age=now-s['ts']
        if s.get('px24') is None and age>86400:
            try:
                c=candles(s['pair'],3600,30)
                if c: s['px24']=c[-1][4]; s['ret24']=(s['px24']/s['px']-1)*100; changed=True
            except Exception: pass
        if s.get('px2h') is None and age>7200:
            try:
                c=candles(s['pair'],3600,6)
                if c: s['px2h']=c[-1][4]; s['ret2h']=(s['px2h']/s['px']-1)*100; changed=True
            except Exception: pass
    # add new
    for a in cands:
        if a['score']>=7 and not any(s['pair']==a['pair'] and now-s['ts']<3600 for s in sigs):
            sigs.append({'pair':a['pair'],'ts':now,'px':a['px'],'score':a['score'],
                         'reasons':a['reasons'],'funding':a['funding']})
            changed=True
    # prune >3 days
    sigs=[s for s in sigs if now-s['ts']<259200]
    if changed: save_signals(sigs)
    # report resolved stats
    done=[s for s in sigs if s.get('ret24') is not None]
    if done:
        wins=sum(1 for s in done if s['ret24']>0)
        avg=sum(s['ret24'] for s in done)/len(done)
        log(f"SIGNALS: {len(done)} resolved | winrate24h={wins}/{len(done)} ({wins/len(done)*100:.0f}%) avg24h={avg:+.2f}%")
        for s in done[-5:]:
            log(f"  {s['pair']} score={s['score']} ret24h={s['ret24']:+.1f}% ret2h={s.get('ret2h','?')}")
def btc_ok():
    c=candles('BTC',3600,60)
    if not c or len(c)<20: return False
    lows=[x[1] for x in c]; closes=[x[4] for x in c]
    return min(lows[-6:]) >= min(lows[-30:-6])*0.9995 and closes[-1]>=closes[-7]*0.99

def usdc_avail():
    try:
        from cb_api import api
        sc,j=api('GET','/accounts?limit=250')
        tot=0.0
        for a in j.get('accounts',[]):
            if a.get('currency')=='USDC':
                tot+=float(a['available_balance']['value'])
        return tot
    except Exception: return 0.0

def open_positions():
    try: return json.load(open(POSF))
    except Exception: return []

EXECF='/tmp/cb_executed.json'
ARMEDF='/tmp/cb_armed.json'
T2F='/tmp/cb_t2_seen.json'
T2_MIN_SEEN=6      # qualifying scans required (pattern must REPEAT, like ALGO's days)
T2_MIN_SPAN=20*3600 # and span at least ~20h — "caçar o padrão de vários dias"
PROVEN={'ALGO'}  # rsi_d<30 -> 2d: win75% n48 stable
# pair: (max daily RSI, needs 2 consecutive down daily closes)
PROVEN_PATTERNS={
 'ZEC':    {'rsi':25},                    # rsi<25->2d: win83% n18 old78/new89 avg+8.4%
 'LIGHTER':{'rsi':25},                    # rsi<25->2d: win80% n15 old71/new88 avg+4.4%
 'TON':    {'rsi':30,'two_down':True},    # rsi<30+2down->2d: win81% n16 old88/new75 avg+4.2%
}
PROVEN_HOOK=set()  # empty — ELSA ruled ineligible by user
_extra_cache={'t':0,'d':{}}
def proven_patterns():
    """hardcoded + auto-discovered (/tmp/cb_proven_extra.json, refreshed 24h)."""
    if time.time()-_extra_cache['t']<3600:
        return {**PROVEN_PATTERNS, **_extra_cache['d']}
    d={}
    try:
        j=json.load(open('/tmp/cb_proven_extra.json'))
        d=j.get('patterns') or {}
        try:
            e=json.load(open('/tmp/cb_edge_proven.json'))
            d.update(e.get('patterns') or {})
            try:
                b=json.load(open('/tmp/cb_beta_proven.json'))
                d.update(b.get('patterns') or {})
                q=json.load(open('/tmp/cb_squeeze_proven.json'))
                d.update(q.get('patterns') or {})
            except Exception: pass
        except Exception: pass
    except Exception: pass
    _extra_cache['t']=time.time(); _extra_cache['d']=d
    return {**PROVEN_PATTERNS, **d}
def is_val(a):
    """Validated >=75% daily patterns (winrate+stability+liquidity filtered)."""
    rd=a.get('rsi_d'); p=a['pair']
    if rd is None: return False
    if p in PROVEN: return rd<30                                   # ALGO: rsi30->2d win75%
    spec=proven_patterns().get(p)
    if not spec: return False
    if spec.get('capit'): return bool(a.get('capit_d'))
    if spec.get('beta'): return True   # presence in cb_beta_proven.json = live >2.2sigma divergence + trend + backtest gates
    if spec.get('squeeze'): return True  # presence in cb_squeeze_proven.json = live bandwidth squeeze + expansion + backtest gates
    if rd is None or rd>=spec.get('rsi',101): return False
    if spec.get('two_down'): return bool(a.get('two_down_d'))
    if spec.get('hook'): return bool(a.get('hook_d'))
    return True
def t2_record(pair,qualified):
    """Track how often/long a pair shows the ALGO-style pattern."""
    try: seen=json.load(open(T2F))
    except Exception: seen={}
    now=time.time()
    arr=[t for t in seen.get(pair,[]) if now-t<48*3600]
    if qualified and (not arr or now-arr[-1]>600): arr.append(now)
    if arr: seen[pair]=arr
    elif pair in seen: del seen[pair]
    try: json.dump(seen,open(T2F,'w'))
    except Exception: pass
    return arr
def t2_ready(pair):
    arr=t2_record(pair,False)
    return len(arr)>=T2_MIN_SEEN and (arr[-1]-arr[0])>=T2_MIN_SPAN
def executed_recently(pair,hrs=24):
    try:
        ex=json.load(open(EXECF))
    except Exception: ex={}
    ts=ex.get(pair,0)
    if time.time()-ts<hrs*3600: return True
    ex[pair]=time.time()
    try: json.dump(ex,open(EXECF,'w'))
    except Exception: pass
    return False

def load_armed():
    try: return json.load(open(ARMEDF))
    except Exception: return {}
def save_armed(a):
    try: json.dump(a,open(ARMEDF,'w'))
    except Exception: pass
def execute(pair,px):
    """Auto-buy ~$1.20 USDC on ENTRY signal; registers position for cb_pos_mgr."""
    if executed_recently(pair,hrs=12):
        log(f'EXECUTE {pair}: skip — already traded <12h ago'); return
    pos=open_positions()
    if len(pos)>=MAX_POS:
        log(f"EXECUTE {pair}: skip — {len(pos)} positions open (max {MAX_POS})"); return
    usdc=usdc_avail()
    if usdc<BUY_USDC+0.05:
        log(f"EXECUTE {pair}: skip — USDC {usdc:.2f} < {BUY_USDC}"); return
    # prefer USDC pair, fallback USD
    product=None
    for prod in (f'{pair}-USDC',f'{pair}-USD'):
        try:
            d=json.load(urllib.request.urlopen(urllib.request.Request(
                f'https://api.exchange.coinbase.com/products/{prod}',
                headers={'User-Agent':'Mozilla/5.0'}),timeout=10))
            if d.get('status')=='online' and d.get('quote_currency') in ('USDC','USD'):
                product=prod; quote=d['quote_currency']; break
        except Exception: pass
    if not product:
        log(f'EXECUTE {pair}: no online product'); return
    quote_ccy='USDC' if 'USDC' in product else 'USD'
    from cb_api import api
    body={"client_order_id":str(uuid.uuid4()),"product_id":product,"side":"BUY",
          "order_configuration":{"market_market_ioc":{"quote_size":f"{BUY_USDC:.2f}"}}}
    sc,j=api('POST','/orders',body)
    log(f'EXECUTE {pair} BUY {BUY_USDC} {quote_ccy} on {product}: {sc} {json.dumps(j)[:300]}')
    if sc not in (200,201): return
    # resolve filled base qty
    filled=j.get('filled_size') or (j.get('order') or {}).get('filled_size')
    fills=j.get('fills') or []
    qty=0.0
    if fills:
        try: qty=sum(float(f.get('size',0)) for f in fills)
        except Exception: pass
    if not qty:
        cur=pair
        try:
            sc2,acc=api('GET','/accounts?limit=250')
            for a in acc.get('accounts',[]):
                if a.get('currency')==cur:
                    qty=float(a['available_balance']['value'])+float((a.get('hold') or {}).get('value') or 0)
        except Exception: pass
    if qty<=0:
        log(f'EXECUTE {pair}: order ok but qty unresolved — check manually'); return
    pos.append({'pair':pair,'product':product,'currency':cur,'qty':qty,
                'entry_price':px,'entry_ts':time.time(),'quote_ccy':quote_ccy})
    json.dump(pos,open(POSF,'w'))
    log(f'POSITION OPEN {pair}: {qty:.6f} @ ~{px} ({BUY_USDC} {quote_ccy}) — mgr will babysit')
def main():
    log("monitor v2 start — strict mode (multi-TF + funding + structure)")
    alerted=set()
    while True:
        try:
            fund=funding()
            bok=btc_ok()
            log("BTC gate:", "OPEN" if bok else "CLOSED")
            cands=[]
            armed=load_armed()
            for pair in universe():
                if pair=='BTC': continue
                a=analyze(pair,fund)
                if not a:
                    armed[pair]=True  # couldn't evaluate -> treat as reset
                    continue
                # edge-trigger: signal OFF -> re-arm for next fresh signal
                if not is_val(a): armed[pair]=True
                time.sleep(0.12)
                # tier-1 candidate: oversold + score>=7 | tier-2 (ALGO-real):
                # RSI<38 + near 7d low + higher-low + reversal — no BTC gate
                t2 = a['rsi1']<38 and a['dist_low']<6 and a['higher_low'] and a['rev']
                # validated pattern = DAILY RSI<30 on proven coins (~400d, win>=62%)
                val = is_val(a)
                if (a['rsi1']<35 and a['score']>=7) or t2 or val or (a.get('rsi_d') or 100)<30:
                    cands.append(a)
            def _vsort(x):
                v = x.get('rsi_d') is not None and x['rsi_d']<30
                return (0 if v else 1, -x['score'])
            cands.sort(key=_vsort)
            for a in cands[:12]:
                t2q = a['rsi1']<38 and a['dist_low']<6 and a['higher_low'] and a['rev']
                seen_arr = t2_record(a['pair'], t2q)
                val = is_val(a)
                val_any = a.get('rsi_d') is not None and a['rsi_d']<30
                flag=''
                if val: flag='*** VALIDATED ***'
                elif val_any: flag='* rsiD<30(unproven) *'
                elif bok and a['score']>=9: flag='** strong(unvalidated) **'
                elif a['score']>=8: flag='** strong **'
                elif t2q and a['score']>=5:
                    flag=f'~ t2 {len(seen_arr)}/{T2_MIN_SEEN} ~'
                log(f"{flag:22} {a['pair']:6} px={a['px']:.6g} rsi1h={a['rsi1']:.0f} rsiD={a.get('rsi_d') and round(a['rsi_d'],1)} dLow={a['dist_low']:.1f}% f={a['funding'] if a['funding'] is not None else 'n/a'} score={a['score']} | {' '.join(a['reasons'])}")
                if flag=='*** VALIDATED ***' and a['pair'] not in alerted and armed.get(a['pair'],True):
                    alerted.add(a['pair']); armed[a['pair']]=False; save_armed(armed)
                    px=a['px']
                    hook = a['pair'] in PROVEN_HOOK
                    log(f">>> EXECUTE[VALIDATED]: {a['pair']} rsiD={a['rsi_d']:.1f}{' hook' if hook else ''} — daily RSI<30 pattern (win>=75% backtest)")
                    log(f">>> PLAN {a['pair']}: buy ~${BUY_USDC} | STOP {px*0.95:.6g} (-5%) | TP {px*1.03:.6g} (+3%) | time-stop 48h")
                    execute(a['pair'],px)
            # clear alert if conditions break (tier-2 uses its own criteria)
            for a in list(alerted):
                still=[x for x in cands if x['pair']==a and
                       ((x.get('rsi_d') is not None and x['rsi_d']<30) or x['score']>=8)]
                if not still: alerted.discard(a)
            save_armed(armed)
            track_signals(cands)
            log("scan done,",len(cands),"candidates")
        except Exception as e:
            log("scan err",str(e)[:100])
        time.sleep(300)
main()
