#!/usr/bin/env python3
# gh_fp_probe.py — test FP OAuth + claim on GitHub Actions runner.
# Launches chromium, injects fp_session cookies from fpmig-state,
# tries clickClaims.online claim end-to-end, prints verdict.
import asyncio, json, sys
from playwright.async_api import async_playwright

STATE = '/tmp/ghstate/files/fp_cookies.json'

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
        # 2) clickClaims claim attempt
        await pg.goto('https://clickclaims.online', wait_until='domcontentloaded', timeout=45000)
        await pg.wait_for_timeout(6000)
        info = await pg.evaluate("""()=>{
          const vis=e=>!!(e.offsetWidth||e.offsetHeight);
          const btns=[...document.querySelectorAll('button,input[type=submit],a.btn,[role=button]')].filter(vis)
            .map(e=>(e.innerText||e.value||'').trim().slice(0,50)).filter(Boolean).slice(0,12);
          return {url:location.href,btns,body:document.body.innerText.slice(0,400)};
        }""")
        print('clickClaims page:', json.dumps(info)[:800], flush=True)
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
