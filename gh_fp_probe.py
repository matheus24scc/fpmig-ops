#!/usr/bin/env python3
# gh_fp_probe.py — test FP OAuth + claim on GitHub Actions runner.
# Launches chromium, injects fp_session cookies from fpmig-state,
# tries clickClaims.online claim end-to-end, prints verdict.
import asyncio, json, sys
from playwright.async_api import async_playwright

STATE = 'ghstate/files/fp_cookies.json'

def load_cookies():
    d = json.load(open(STATE))
    out = []
    for c in d:
        ck = {'name': c['name'], 'value': c['value'],
              'domain': c.get('domain', '.faucetpay.io'),
              'path': c.get('path', '/')}
        if c.get('expires'): ck['expires'] = c['expires']
        ck['httpOnly'] = bool(c.get('httpOnly'))
        ck['secure'] = bool(c.get('secure'))
        ss = c.get('sameSite', 'Lax')
        ck['sameSite'] = ss if ss in ('Strict', 'Lax', 'None') else 'Lax'
        out.append(ck)
    return out

async def main():
    cks = load_cookies()
    print('cookies loaded:', len(cks), flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=['--no-sandbox'])
        ctx = await browser.new_context()
        await ctx.add_cookies(cks)
        pg = await ctx.new_page()
        # 1) verify FP session works in this browser
        await pg.goto('https://faucetpay.io/dashboard', wait_until='domcontentloaded', timeout=45000)
        await pg.wait_for_timeout(5000)
        body = await pg.evaluate('()=>document.body.innerText.slice(0,300)')
        print('FP dashboard:', 'LOGGED-IN' if 'gabrielgtx' in body else 'NOT-LOGGED-IN', flush=True)
        print(body[:200].replace('\n', ' | '), flush=True)
        me = await pg.evaluate("""async()=>{try{const r=await fetch('/app-api/session/me',{credentials:'include'});return r.status+'|'+(await r.text()).slice(0,200)}catch(e){return 'err|'+e}}""")
        print('session/me via page:', me, flush=True)
        ck = await ctx.cookies('https://faucetpay.io')
        print('ctx cookies now:', [c['name'] for c in ck], flush=True)
        # 2) clickClaims claim attempt
        try:
            await pg.goto('https://clickclaims.online', wait_until='domcontentloaded', timeout=90000)
        except Exception as e:
            print('goto err', repr(e)[:150], flush=True)
        await pg.wait_for_timeout(6000)
        try:
            info = await pg.evaluate("""()=>{
              const vis=e=>!!(e.offsetWidth||e.offsetHeight);
              const btns=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
                .map(e=>(e.innerText||e.value||'').trim().slice(0,50)).filter(Boolean).slice(0,12);
              return {url:location.href,btns,body:document.body.innerText.slice(0,400)};
            }""")
            print('clickClaims page:', json.dumps(info)[:800], flush=True)
        except Exception as e:
            print('page eval err', repr(e)[:200], flush=True)
            info = {}
        # OAuth: click "Sign in with FaucetPay" -> authorize -> back with session
        clicked = await pg.evaluate("""()=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const els=[...document.querySelectorAll('a,button')].filter(vis);
          const b=els.find(e=>/faucetpay/i.test(e.innerText||''));
          if(b){b.click();return (b.innerText||'').trim().slice(0,50)} return null;
        }""")
        print('oauth click:', clicked, flush=True)
        for i in range(30):
            await pg.wait_for_timeout(2500)
            u = pg.url
            print('nav', i, u[:110], flush=True)
            # done when back on clickclaims but past the auth/login interstitial
            if 'clickclaims' in u and '/auth/login' not in u:
                break
            # also check for popup pages doing the oauth
            for t in ctx.pages:
                if 'faucetpay.io' in t.url:
                    print('  fp tab:', t.url[:100], flush=True)
        await pg.wait_for_timeout(4000)
        info2 = await pg.evaluate("""()=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const btns=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
            .map(e=>(e.innerText||e.value||'').trim().slice(0,50)).filter(Boolean).slice(0,12);
          const forms=[...document.querySelectorAll('form')].filter(vis).length;
          return {url:location.href,btns,forms,body:document.body.innerText.slice(0,300)};
        }""")
        print('after oauth:', json.dumps(info2)[:800], flush=True)
        # try claim via fetch inside page (same trick as worker)
        res = await pg.evaluate("""async()=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const f=[...document.querySelectorAll('form')].find(x=>vis(x));
          if(!f) return 'noform';
          const fd=new FormData(f);
          // inject captcha tokens if solved
          for(const n of ['cf-turnstile-response','h-captcha-response','g-recaptcha-response','captcha_token','captcha']){
            const el=f.querySelector('[name="'+n+'"]'); if(el&&el.value) fd.set(n,el.value);
          }
          try{
            const resp=await fetch(f.action||location.pathname,{method:'POST',body:fd,credentials:'include'});
            return resp.status+'|'+(await resp.text()).slice(0,300);
          }catch(e){return 'fetcherr|'+e}
        }""")
        print('claim result:', res, flush=True)
        await browser.close()

asyncio.run(main())
