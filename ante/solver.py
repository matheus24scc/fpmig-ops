#!/usr/bin/env python3
# ante_solver.py — plays Ante normal rounds via API, decodes hints, logs all
import json,urllib.request,time,os,sys,random
BASE='https://pay.ante.games'
W=json.load(open('/tmp/ante/wallet.json'))
ADDR=W['address']
LOG=open('/tmp/ante/solver.log','a',buffering=1)
HINTLOG=open('/tmp/ante/hints.jsonl','a',buffering=1)
def log(*a):
    s=f"[{time.strftime('%H:%M:%S')}] "+' '.join(map(str,a));print(s,flush=True);LOG.write(s+'\n')
def api(path,body=None,method=None):
    data=json.dumps(body).encode() if body is not None else None
    r=urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'})
    try: return json.load(urllib.request.urlopen(r,timeout=15))
    except urllib.error.HTTPError as e:
        try: return {'HTTP':e.code,'body':json.loads(e.read()[:500])}
        except Exception: return {'HTTP':e.code}
    except Exception as e: return {'ERR':str(e)[:100]}

# ---- hint decode map: hint_text -> predicate(residue 0-99). FILL AS LEARNED ----
def is_prime(n):
    if n<2: return False
    for i in range(2,int(n**0.5)+1):
        if n%i==0: return False
    return True
def pred_ge30(r): return r>=30
def pred_mod3_2(r): return r%3==2
def pred_notprime(r): return not is_prime(r)
def pred_digitsum_10_13(r): return 10<=sum(int(d) for d in str(r))<=13
def pred_ge75(r): return r>=75
def pred_even(r): return r%2==0
def pred_lastdigit_le4(r): return r%10<=4
# --- batch decode of collected metaphors (all predicates on residue 0-99) ---
def pred_lastdigit_even(r): return r%10%2==0
def pred_mod4_2(r): return r%4==2
def pred_tens_odd(r): return (r//10)%2==1
def pred_units_ge5(r): return r%10>=5
def pred_lt60(r): return r<60
def pred_mod4_1(r): return r%4==1
def pred_tens_even(r): return (r//10)%2==0
def pred_tens_gt_units(r): return (r//10)>(r%10)
def pred_odd(r): return r%2==1
def pred_lt80(r): return r<80
def pred_ge20(r): return r>=20
def pred_mod7_5(r): return r%7==5
def pred_ge60(r): return r>=60
def pred_mod7_0(r): return r%7==0
def pred_mod4_3(r): return r%4==3
def pred_ge25(r): return r>=25
def pred_prime(r): return is_prime(r)
def pred_mod6_5(r): return r%6==5
def pred_units_le4b(r): return r%10<=4
def pred_lt50(r): return r<50
def pred_mod6_4(r): return r%6==4
def pred_digitsum_lt6(r): return sum(int(d) for d in str(r))<6
def pred_lt70(r): return r<70
def pred_units_gt_tens(r): return (r%10)>(r//10)
def pred_mod7_4(r): return r%7==4
def pred_mod11_6(r): return r%11==6
def pred_ge70(r): return r>=70
def pred_ge50(r): return r>=50
def pred_digitsum_gt13(r): return sum(int(d) for d in str(r))>13
def pred_mod5_3(r): return r%5==3
def pred_mod3_0(r): return r%3==0
def pred_mod3_1(r): return r%3==1
def pred_mod4_0(r): return r%4==0
def pred_mod5_1(r): return r%5==1
def pred_mod5_2(r): return r%5==2
def pred_mod6_1(r): return r%6==1
def pred_mod6_2(r): return r%6==2
def pred_mod9_0(r): return r%9==0
def pred_mod11_9(r): return r%11==9
def pred_ge40(r): return r>=40
def pred_ge80(r): return r>=80
def pred_lt25(r): return r<25
def pred_lt40(r): return r<40
def pred_digitsum_6_9(r):
    s=sum(int(d) for d in str(r)); return 6<=s<=9
HINT_MAP={
 'Not before the thirtieth plinth does the causeway hold it.':pred_ge30,
 'Ranked in threes, a pair of stones lingers past the last full row.':pred_mod3_2,
 'It does not belong to the primes; the masons find it divisible, or simply too slight to qualify.':pred_notprime,
 "Its keystone's digits, added together, land between ten and thirteen inclusive.":pred_digitsum_10_13,
 'It stands at the three-quarter post of the hundred-stone road or beyond.':pred_ge75,
 'Every block in its count finds a partner across the aisle.':pred_even,
 'The closing figure of its inscription stays within the first five numerals, four at most.':pred_lastdigit_le4,
 'Three shy of another seven, four stones cluster at the ramp.':pred_mod7_4,
 'The closing figure on its plaque splits in two without remainder.':pred_lastdigit_even,
 'The four-wide terrace closes with two stones stranded at its lip.':pred_mod4_2,
 'The tens numeral on its plaque is an odd figure.':pred_tens_odd,
 'Its final digit belongs to the high shelf: five and upward.':pred_units_ge5,
 'A pilgrim reaches it before the sixtieth arch overhead.':pred_lt60,
 'Coursed in fours, one lone stone crowns the unfinished corner.':pred_mod4_1,
 'It stands before the sixtieth column of the long arcade.':pred_lt60,
 'The first numeral of its two-figure inscription is even.':pred_tens_even,
 'The tens figure of its inscription looks down upon the units.':pred_tens_gt_units,
 'One stone always waits unmatched when its count is set out in pairs.':pred_odd,
 'Its stones pair off into twin files with none left standing alone.':pred_even,
 "The esplanade's first eight tens contain it, short of eighty.":pred_lt80,
 'Its number is twenty at the least, the first score already behind.':pred_ge20,
 'Two short of one more seven, five stones line the corridor.':pred_mod7_5,
 'Its column stands at the sixtieth of the arcade or past it.':pred_ge60,
 'Its tally roofs the seven-vaulted crypt with no block to spare.':pred_mod7_0,
 'Four wagons take their share and three blocks are left in the yard.':pred_mod4_3,
 'Its marker lies no earlier than the twenty-fifth of the hundred.':pred_ge25,
 'Its stones refuse every equal ranking deeper than single file.':pred_prime,
 'Six masons take equal lots and five blocks stay in the yard.':pred_mod6_5,
 'Its number reaches thirty or climbs beyond it.':pred_ge30,
 'The tens numeral on its plaque is an even figure.':pred_tens_even,
 'Its final digit belongs to the low shelf: nothing above four.':pred_lastdigit_le4,
 "Its pillar rises before the hall's midpoint is crossed.":pred_lt50,
 'Ranked in sixes, four stones remain when the last course sets.':pred_mod6_4,
 "Added together, the pair of digits on its keystone stay under six.":pred_digitsum_lt6,
 'It lies before the seventieth stone of the processional way.':pred_lt70,
 "After the four-wide rows are laid, one stone remains for the mason's sill.":pred_mod4_1,
 'On its plaque the last numeral overtops the first.':pred_units_gt_tens,
 'The last numeral on its plaque is large, five or greater.':pred_units_ge5,
 'No mason can lay its count in even rows of any width but one.':pred_odd,
 "The road's final quarter claims it, the seventy-fifth stone included.":pred_ge75,
 'The masons split its load into two equal carts, nothing remaining.':pred_even,
 'On its plaque the first numeral overtops the last.':pred_tens_gt_units,
 'Eleven buttresses share evenly and six blocks remain at the winch.':pred_mod11_6,
 'The processional way holds it no sooner than the seventieth.':pred_ge70,
 'The steward finds it in the latter half of the hundred, the halfway stone included.':pred_ge50,
 "Its plaque's two figures make a heavy sum, past thirteen combined.":pred_digitsum_gt13,
 'The herald calls its name before the seventieth step.':pred_lt70,
 'Coursed in fours, two stones outlast the final full row.':pred_mod4_2,
 'Its stone lies at the thirtieth marker of the causeway or farther on.':pred_ge30,
 'It is one of the unbreakable tallies, divisible by itself and one alone.':pred_prime,
 'Coursed in fours, three stones huddle past the last complete rank.':pred_mod4_3,
 'The five-arched gallery closes with a trio left before the steps.':pred_mod5_3,
 'Laid in ranks of three, the last rank stands complete, the corner bare.':pred_mod3_0,
 "Its decades outnumber its final digit, the leading figure the larger.":pred_tens_gt_units,
 'Three porters share its load exactly, none carrying more than another.':pred_mod3_0,
 'Split its load between two carts and a single block rides the seam.':pred_even,
 'A courier passes it before the eightieth lamp is lit.':pred_lt80,
 "Added together, the digits on its keystone overtop thirteen.":pred_digitsum_gt13,
 'After the triad columns are filled, one stone waits on the threshold.':pred_mod3_1,
 'Counted in fives, a single stone remains beside the plinth.':pred_mod5_1,
 'Divided among four wagons, every wagon bears an equal share.':pred_mod4_0,
 'Five porters share the load and a pair is left at the quarry mouth.':pred_mod5_2,
 'Five porters take equal shares and one block stays for the apprentice.':pred_mod5_1,
 'Four-square courses take its whole count, the top course complete.':pred_mod4_0,
 'It belongs to the near half of the hundred-pillar hall.':pred_lt50,
 'Its final digit outnumbers its decades, the closing figure the larger.':pred_units_gt_tens,
 "Its number is forty at the least; the walker's count has passed two-score.":pred_ge40,
 'Its number is seventy at the least, the seventieth stone reached or passed.':pred_ge70,
 'Its number reaches sixty or stands beyond it.':pred_ge60,
 "Its pillar rises only after the hall's midpoint is crossed, or upon it.":pred_ge50,
 "Its plaque's two figures make a slight sum, less than six between them.":pred_digitsum_lt6,
 'Its plinth stands at the eightieth of the esplanade or past it.':pred_ge80,
 'Its stone lies at the seventieth of the way or farther along.':pred_ge70,
 'Its tally refuses twin files — the last stone stands alone in the aisle.':pred_odd,
 'Nine-stone courses absorb its count wholly, the grid left even.':pred_mod9_0,
 'No earlier than pillar twenty does the colonnade reveal it.':pred_ge20,
 'One stone shy of closing another hexagon, five wait at the sill.':pred_mod6_5,
 'Ranked in elevens, nine stones outlast the last full circuit.':pred_mod11_9,
 "Ranked in sixes, one stone remains for the keystone's shim.":pred_mod6_1,
 "Ranked in threes, a single stone is left at the courtyard's edge.":pred_mod3_1,
 'Six masons divide the pile and two blocks remain at the well.':pred_mod6_2,
 'Summed, the pair of figures on its plaque reach six or more, yet never pass nine.':pred_digitsum_6_9,
 "The arcade's first six tens hold it, short of sixty.":pred_lt60,
 'The closing figure of its inscription starts at five or climbs higher.':pred_units_ge5,
 'The closing figure on its plaque leaves one over when halved.':pred_odd,
 'The final numeral of its inscription is an odd figure.':pred_odd,
 'The first of its two carved digits pairs off cleanly, even by nature.':pred_tens_even,
 'The first of its two carved digits refuses pairing, odd by nature.':pred_tens_odd,
 'The last numeral on its plaque is small, no greater than four.':pred_units_le4b,
 'The list of numbers divisible only by themselves and one passes it by.':pred_notprime,
 'The opening quarter of the gallery ends before its plinth appears.':pred_lt25,
 'The road\'s final quarter begins only after its place has passed.':pred_ge75,
 'The steward counts it among the first half of the hundred.':pred_lt50,
 "The terrace's first four tens contain it, shy of forty.":pred_lt40,
 'The triple colonnade claims every one of its stones, corner swept clean.':pred_mod3_0,
 'The two numerals on its plaque total at least ten and at most thirteen.':pred_digitsum_10_13,
 'The units figure of its inscription rises above the tens.':pred_units_gt_tens,
 'Three porters split the load and two blocks are left on the ramp.':pred_mod3_2,
 'Two shy of a final six, four stones gather beneath the arch.':pred_mod6_4,
 "Its keystone's digits, added together, land between six and nine inclusive.":pred_digitsum_6_9,
 'The arcade grants it no place earlier than the sixtieth.':pred_ge60,
 'Its plinth stands at the twentieth marker or somewhere beyond.':pred_ge20,
 'Four wagons share the load and a single block rides atop the last.':pred_mod4_1,
 'Some rank wider than one and narrower than itself lays its count in even rows — or it is too small to be prime at all.':pred_notprime,
 'The two numerals carved on its plaque total more than thirteen.':pred_digitsum_gt13,
}
KNOWN_HINTS=set(HINT_MAP)

def decode_residues(hints):
    """residues 0-99 satisfying ALL known hint predicates"""
    out=[]
    for r in range(100):
        ok=True
        for h in hints:
            p=HINT_MAP.get(h)
            if p and not p(r): ok=False;break
        if ok: out.append(r)
    return out

def candidates(hints,field,per_cp):
    """guessable blocks are 0-99 (server enforces) consistent w/ decoded residues"""
    res=decode_residues(hints)
    if not res: res=list(range(100))
    return [r for r in res if r<100]

def play_round():
    st=api('/round/state')
    if not st or st.get('status')!='ACTIVE':
        log('no active round',st and st.get('status')); return False
    field=st.get('blocksPerCheckpoint',119); ncps=st.get('totalCheckpoints',10)
    pot=st.get('pot'); mult=st.get('rewardMultiplier',1); rich=st.get('isRichVein')
    log(f'ROUND field={field} cps={ncps} pot={pot} mult={mult} rich={rich} t={st.get("secondsRemaining")}s')
    s=api('/session/create',{'solana_wallet':ADDR,'model':'swe-2-flash','provider':'cognition','user_agent':'devin-solver/1.0'})
    if 'sessionId' not in s:
        log('session fail',s); return False
    sid=s['sessionId']; log('session',sid[:13])
    for cp in range(ncps):
        hints=[]; tried=set(); last_n=-1
        # phase A: burn guesses to unlock hints while spreading coverage
        while True:
            # build guess list: decoded candidates first, then unexplored spread
            cands=[b for b in candidates(hints,field,cp) if b not in tried]
            if cands:
                # prefer blocks in mid/high field (hints usually constrain low residues anyway)
                guess=cands[0]
            else:
                guess=next((b for b in range(min(field,100)) if b not in tried),None)
            if guess is None: break
            tried.add(guess)
            r=api(f'/block/{cp}/{guess}',{'sessionId':sid})
            if r.get('HTTP')==429:
                tried.discard(guess); time.sleep(1.2); continue
            if 'result' not in r:
                log('guess err',cp,guess,str(r)[:120])
                if 'session' in str(r).lower() or r.get('HTTP') in (400,401,403,404,410):
                    log('session dead — abort round'); return False
                time.sleep(2); continue
            for h in (r.get('hints') or []):
                if h not in KNOWN_HINTS:
                    KNOWN_HINTS.add(h); HINTLOG.write(json.dumps({'hint':h,'cp':cp,'round':st.get('roundId')})+'\n'); HINTLOG.flush()
                    log('NEW HINT:',h)
            res=r.get('result')
            if res=='CORRECT':
                log(f'cp{cp} CLEAR in {len(tried)} tries'); break
            if res=='WIN':
                log(f'*** WIN cp{cp} ***',json.dumps(r)[:300]); return True
            if r.get('nextCheckpoint') and r['nextCheckpoint']!=cp:
                log(f'cp{cp} advanced->',r['nextCheckpoint']); break
            time.sleep(1.05)  # rate limit 1/s
        else:
            pass
        if cp>=ncps-1: break
    return False

def main():
    log('=== ante solver start === addr',ADDR)
    while True:
        try:
            if play_round():
                log('round won — checking balance'); time.sleep(10)
        except Exception as e:
            log('ERR',repr(e)[:200])
        time.sleep(15)
if __name__=='__main__': main()
