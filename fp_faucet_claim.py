#!/usr/bin/env python3
# fp_faucet_claim.py — FaucetPay external-faucet claim worker (browser CDP).
# FP API can't claim external faucets — each site has own auth/captcha.
# Strategy: visit top faucets, fill FP username/address, click claim,
# let Turnstile/hcaptcha auto-resolve in real browser, verify payout text.
# Targets are discovered from /tmp/fp_faucets_all.json ranked by weekly USD.
import asyncio, json, time, re, sys, random
sys.stdout=open('/tmp/fp_faucet_claim.log','a',buffering=1)
from playwright.async_api import async_playwright

FP_USER='gabrielgtx'
STATE='/tmp/fp_claim_state.json'
COOLDOWN=3300  # ~55min per faucet (hourly claims typical)

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s): json.dump(s,open(STATE,'w'))

CLAIM_JS=r"""()=>{
  const vis=e=>!!(e.offsetWidth||e.offsetHeight);
  const inputs=[...document.querySelectorAll('input')].filter(vis);
  const fp=inputs.find(i=>/faucetpay|fp[_-]?(user|addr|mail|name)|username|address|wallet|payee|user_?id/i.test((i.name||'')+' '+(i.id||'')+' '+(i.placeholder||'')));
  const claimBtns=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
    .filter(e=>/claim|faucet|collect|earn|get|harvest|open/i.test((e.innerText||e.value||'').trim())&&!/login|sign|register|ad|offer|ptc|short/i.test(e.innerText||''));
  return {hasFp:!!fp,fpName:fp?(fp.name||fp.id||''):null,btns:claimBtns.slice(0,6).map(b=>(b.innerText||b.value||'').trim().slice(0,40))};
}"""

def targets():
    faus=json.load(open('/tmp/fp_faucets_all.json'))
    faus.sort(key=lambda f:-(float(f.get('week_amount_paid_usd') or 0)))
    # top overall + ensure top hosted FaaS sites are covered (OAuth claim path)
    hosted=[f for f in faus if f.get('is_hosted')]
    hosted.sort(key=lambda f:-(float(f.get('week_amount_paid_usd') or 0)))
    nonhosted=[f for f in faus if not f.get('is_hosted')]
    nonhosted.sort(key=lambda f:-(float(f.get('week_amount_paid_usd') or 0)))
    ids={f['id'] for f in hosted[:60]}
    return hosted[:60]+[f for f in nonhosted[:25] if f['id'] not in ids]

async def _dismiss_overlays(pg):
    for sel in ['button:has-text("Accept")','button:has-text("Agree")','button:has-text("OK")','[class*=cc-] button','[id*=cookie] button']:
        try:
            for el in (await pg.query_selector_all(sel))[:3]:
                if await el.is_visible(): await el.click(timeout=800); await pg.wait_for_timeout(300)
        except Exception: pass
    try:
        await pg.evaluate("()=>{document.querySelectorAll('[class*=cc-],[id*=cookie],[class*=consent]').forEach(e=>e.remove())}")
    except Exception: pass

async def oauth_login(pg,base):
    # FaaS hosted sites: FP OAuth -> session cookie -> claim without fp field
    # flow: /auth/login -> click 'Sign in with FaucetPay' -> FP authorize -> Authorize -> callback
    try:
        await _dismiss_overlays(pg)
        await pg.goto(base.rstrip('/')+'/auth/login',wait_until='domcontentloaded',timeout=30000)
        await pg.wait_for_timeout(3500)
        await _dismiss_overlays(pg)
        # if already on authorize page or login shows provider button
        if 'faucetpay.io/oauth/authorize' not in pg.url:
            clicked=False
            for sel in ['a:has-text("Sign in with FaucetPay")','button:has-text("Sign in with FaucetPay")','a:has-text("FaucetPay")','button:has-text("FaucetPay")']:
                try:
                    for el in (await pg.query_selector_all(sel))[:2]:
                        if await el.is_visible():
                            await el.click(timeout=4000); clicked=True; break
                    if clicked: break
                except Exception: pass
            if not clicked:
                # fallback: direct provider URL
                await pg.goto(base.rstrip('/')+'/auth/login?provider=faucetpay',wait_until='domcontentloaded',timeout=30000)
            await pg.wait_for_timeout(5000)
        if 'faucetpay.io/oauth/authorize' in pg.url:
            el=await pg.query_selector('button:has-text("Authorize"),button[type=submit]')
            if el: await el.click(); await pg.wait_for_timeout(7000)
        # if we landed on site login page still, try provider link there too
        if 'faucetpay.io' not in pg.url and 'auth' in pg.url:
            for sel in ['a:has-text("FaucetPay")','button:has-text("FaucetPay")']:
                try:
                    el=await pg.query_selector(sel)
                    if el and await el.is_visible(): await el.click(timeout=4000); await pg.wait_for_timeout(5000); break
                except Exception: pass
            if 'faucetpay.io/oauth/authorize' in pg.url:
                el=await pg.query_selector('button:has-text("Authorize"),button[type=submit]')
                if el: await el.click(); await pg.wait_for_timeout(7000)
        return True
    except Exception as e:
        return 'oauth-err:'+str(e)[:80]

async def _try_hosted(pg,url,name):
    base=url.rstrip('/')
    await oauth_login(pg,base)
    await pg.goto(base,wait_until='domcontentloaded',timeout=30000)
    await pg.wait_for_timeout(3500)
    # FaaS claim console: CLAIM NOW button + turnstile
    body=await pg.evaluate("()=>document.body.innerText.slice(0,3000)")
    if 'busy, try again' in body.lower() or 'too many requests' in body.lower():
        return 'busy-ip-cd600',{'busy':True}
    info=await pg.evaluate("""()=>{
      const vis=e=>!!(e.offsetWidth||e.offsetHeight);
      const bs=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
        .filter(e=>/claim now|claim|collect/i.test((e.innerText||e.value||'').trim())&&!/login|sign|register|cancel/i.test(e.innerText||''));
      const paused=/paused|maintenance|come back/i.test(document.body.innerText.slice(0,2000));
      const body=document.body.innerText.slice(0,3000);
      const logged=(/sign out|logout/i.test(body)||/dashboard/i.test(body))&&!/sign in with/i.test(body);
      return {btns:bs.slice(0,5).map(b=>(b.innerText||'').trim().slice(0,40)),paused,logged};
    }""")
    if info.get('paused'): return 'paused',info
    if not info.get('logged'): return 'not-logged-in',info
    if not info.get('btns'): return 'nobtn',info
    # let turnstile/hcaptcha widgets auto-solve first (real browser = free solve)
    await pg.wait_for_timeout(5000)
    # submit claim FORM via fetch (page survives navigation); inject captcha token if present
    res=await pg.evaluate("""async()=>{
      const vis=e=>!!(e.offsetWidth||e.offsetHeight);
      const bs=[...document.querySelectorAll('button[type=submit],button,input[type=submit]')].filter(vis)
        .filter(e=>/claim/i.test((e.innerText||e.value||'').trim())&&!/login|sign|register|cancel/i.test(e.innerText||''));
      if(!bs.length)return 'nobtn';
      const f=bs[0].closest('form');
      if(!f)return 'noform';
      const fd=new FormData(f);
      // inject solved captcha tokens (turnstile/hcaptcha/recaptcha hidden fields)
      for(const n of ['cf-turnstile-response','h-captcha-response','g-recaptcha-response','captcha_token','captcha']){
        const el=document.querySelector(`[name="${n}"]`)||document.querySelector(`textarea[name="${n}"]`)||document.querySelector(`input[name="${n}"]`);
        if(el&&el.value) fd.set(n,el.value);
      }
      // also scan all inputs/textarea for token-looking values
      document.querySelectorAll('textarea,input[type=hidden]').forEach(el=>{
        if(el.name&&el.value&&el.value.length>50&&/token|captcha|turnstile|response/i.test(el.name)) fd.set(el.name,el.value);
      });
      try{
        const resp=await fetch(f.action||location.pathname,{method:'POST',body:fd,credentials:'include',redirect:'manual'});
        const t=await resp.text().catch(()=>'');
        return {st:resp.status,body:t.slice(0,250)};
      }catch(e){return {st:0,body:String(e).slice(0,150)};}
    }""")
    if isinstance(res,dict):
        st=res.get('st'); body=res.get('body','')
        # cooldown text: "every 1 minute" / "every 60 minutes"
        cd=3600
        m=re.search(r'every\s+(\d+)\s*(minute|hour|second)',await pg.evaluate("()=>document.body.innerText.slice(0,3000)"))
        if m:
            n=int(m.group(1)); cd=n*({'second':1,'minute':60,'hour':3600}[m.group(2)])
        if st==429: return 'ratelimit-cd'+str(cd),{'res':res}
        if st in (200,301,302):
            ok=bool(re.search(r'(success|paid|credited|balance|claimed)',body,re.I))
            return ('claimed!' if ok else 'submitted-200')+'|cd'+str(cd),{'res':res,'cd':cd}
        return 'submit-'+str(st),{'res':res}
    return res,info

async def try_claim(pg,url,name,hosted=False):
    if hosted:
        return await _try_hosted(pg,url,name)
    # try homepage then common claim subpaths if no fp field found
    for u in (url, url.rstrip('/')+'/faucet', url.rstrip('/')+'/claim', url.rstrip('/')+'/earn'):
        r=await _try_one(pg,u,name)
        if r[0] not in ('no-fp-field','nobtn','err'):
            return r
        if r[0]=='err': return r
    return r

async def _try_one(pg,url,name):
    try:
        await pg.goto(url,wait_until='domcontentloaded',timeout=30000)
        await pg.wait_for_timeout(3500)
        # close cookie/consent overlays
        for sel in ['button:has-text("Accept")','button:has-text("Agree")','button:has-text("OK")','[class*=cookie] button','[id*=cookie] button']:
            try:
                el=pg.locator(sel).first
                if await el.count() and await el.is_visible(): await el.click(timeout=800); await pg.wait_for_timeout(400)
            except Exception: pass
        info=await pg.evaluate(CLAIM_JS)
        if not info.get('hasFp'):
            return 'no-fp-field',info
        # fill FP field
        filled=await pg.evaluate("""(u)=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const inputs=[...document.querySelectorAll('input')].filter(vis);
          const fp=inputs.find(i=>/faucetpay|fp[_-]?(user|addr|mail|name)|username|address|wallet|payee|user_?id/i.test((i.name||'')+' '+(i.id||'')+' '+(i.placeholder||'')));
          if(!fp)return 'no';
          const st=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
          st.call(fp,u);fp.dispatchEvent(new Event('input',{bubbles:true}));fp.dispatchEvent(new Event('change',{bubbles:true}));
          return 'ok';}""",FP_USER)
        if filled!='ok': return 'fill-fail',info
        # click first plausible claim button
        clicked=await pg.evaluate("""()=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const bs=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
            .filter(e=>/claim|faucet|collect|earn|get|harvest|open/i.test((e.innerText||e.value||'').trim())&&!/login|sign|register|ad|offer|ptc|short|logout/i.test(e.innerText||''));
          if(!bs.length)return 'nobtn';
          bs[0].click();return 'clicked:'+((bs[0].innerText||bs[0].value||'').trim().slice(0,30));}""")
        if not str(clicked).startswith('clicked'): return clicked,info
        await pg.wait_for_timeout(6000)
        # check for success text / balance delta
        txt=await pg.evaluate("()=>document.body.innerText.slice(0,3000)")
        ok=bool(re.search(r'(claim(ed)?\s*(success|complete)|you (got|received|earned)|\+\s*[\d.]+\s*(BTC|DOGE|LTC|USDT|satoshi)|reward|paid out|congrat)',txt,re.I))
        # also look for turnstile iframe still pending
        ts=await pg.evaluate("()=>!!document.querySelector('iframe[src*=turnstile],iframe[src*=challenges]')")
        return ('claimed?' if ok else 'submitted')+('|turnstile' if ts else ''),{'info':info,'clicked':clicked,'txt':txt[-300:]}
    except Exception as e:
        return 'err:'+str(e)[:100],{}

async def main():
    st=load_state()
    async with async_playwright() as p:
        b=await p.chromium.connect_over_cdp('http://localhost:9222')
        ctx=b.contexts[0]
        pg=await ctx.new_page()
        try:
            while True:
                now=time.time()
                did=False
                todo=[]
                for f in targets():
                    fid=str(f['id']); url=f.get('faucet_url') or ''
                    if not url or 'http' not in url: continue
                    cd=st.get(fid,{}).get('cd') or COOLDOWN
                    if now-(st.get(fid,{}).get('ts',0))<cd: continue
                    todo.append((cd,f))
                todo.sort(key=lambda x:x[0])  # shortest cooldown first = max claims/hr
                for cd,f in todo:
                    fid=str(f['id']); url=f.get('faucet_url')
                    r,info=await try_claim(pg,url,f.get('faucet_name'),bool(f.get('is_hosted')))
                    cdet=3600
                    m2=re.search(r'cd(\d+)',str(r))
                    if m2: cdet=int(m2.group(1))
                    st[fid]={'ts':now,'result':r,'name':f.get('faucet_name'),'usd':f.get('week_amount_paid_usd'),'cd':cdet}
                    save_state(st)
                    print(time.strftime('%H:%M'),f.get('faucet_name','?')[:30],'->',r,str(info)[:150],flush=True)
                    did=True
                    await pg.wait_for_timeout(12000 if f.get('is_hosted') else 3000)
                if not did:
                    # all on cooldown — sleep till earliest
                    nxt=min((v.get('ts',0)+COOLDOWN for v in st.values()),default=now+600)
                    wait=max(60,min(1800,nxt-now))
                    print(time.strftime('%H:%M'),'all cooldown, sleep',int(wait),flush=True)
                    await asyncio.sleep(wait)
                await asyncio.sleep(5)
        finally:
            try: await pg.close()
            except Exception: pass
asyncio.run(main())
