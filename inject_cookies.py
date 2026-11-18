#!/usr/bin/env python3
# inject_cookies.py — seed FP session cookies into the CDP browser on GH runner.
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
    print('injecting', len(cks), 'cookies', flush=True)
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = b.contexts[0]
        await ctx.add_cookies(cks)
        # warm FP session once so oauth authorize is instant
        pg = await ctx.new_page()
        try:
            await pg.goto('https://faucetpay.io/dashboard', wait_until='domcontentloaded', timeout=45000)
            await pg.wait_for_timeout(4000)
        except Exception as e:
            print('warm warn', repr(e)[:120], flush=True)
        me = await pg.evaluate("""async()=>{try{const r=await fetch('/app-api/session/me',{credentials:'include'});return r.status}catch(e){return 'err'}}""")
        print('session check:', me, flush=True)
        await pg.close()

asyncio.run(main())
