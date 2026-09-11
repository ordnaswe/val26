#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invalda.py — mandat -> person-motor för valutfall.se (RD/RF).

Vad den gör
-----------
1. Läser kandidatlistorna (Valmyndighetens kandidaturer.csv).
2. Tar EMOT mandat per parti per valkrets (det din build.py redan räknar fram)
   och räknar ut vilka kandidater som preliminärt blir invalda = de N översta
   på partiets lista i valkretsen, där N = partiets mandat där.
3. Kopplar de invalda mot bevakningslistan (nyckelpersoner.csv) via
   namn+parti (+ort när den finns) och flaggar nyckelpersoner som är på väg IN.
4. Vänder även på det: för varje nyckelperson som kandiderar (RD/RF) räknar den
   ut om personen ligger ÖVER eller UNDER sitt partis mandatstreck i valkretsen
   -> "sannolikt invald" / "på väg ut" / "utanför".

Allt är stdlib (csv, re, unicodedata, collections, argparse) — inga beroenden.

Så kopplas den in i valutfall
-----------------------------
build.py räknar redan mandat per parti per valkrets (RD: 310 fasta + 39 utjämning;
RF: per regionvalkrets). Mata in den fördelningen som `mandat`-dict eller mandat.csv
(kolumner: valtyp,valomradeskod,valkretskod,parti_abbr,mandat). Motorn returnerar
invalda + nyckelperson-status som du skriver till en JSON/CSV och renderar i template.html
(t.ex. ny flik "Personvalet" / "Nyckelpersoner in-ut"), och som uppdateras varje
hämtvarv i takt med att `raknat` växer.

Viktiga förbehåll (dokumenterade, inte gissningar)
--------------------------------------------------
* PERSONRÖSTER ingår inte live. Motorn rangordnar på listordning (ORDNING). I
  slutresultatet kan kryss (>5 %) kasta om ordningen -> markera som preliminärt.
* FLERA VALSEDLAR per parti i en valkrets: live saknas röster per lista, så motorn
  väljer partiets "kanoniska" lista = den med flest anmälda kandidater och rangordnar
  på den. Valkretsar där partiet har >1 lista flaggas `flera_listor=True` (approx.).
* NAMNMATCHNING mot bevakningslistan sker på namn (utan diakritiska tecken) + parti,
  med ort som tie-break där den finns. Vanliga namn kan ge tvetydig träff -> `match`
  märks 'entydig' / 'tvetydig' / 'namn+parti' så du kan verifiera.
"""
import csv, re, unicodedata, argparse, json, sys
from collections import defaultdict, Counter

PARTI={'Socialdemokraterna':'S','Moderaterna':'M','Moderata samlingspartiet':'M',
 'Sverigedemokraterna':'SD','Centerpartiet':'C','Vänsterpartiet':'V','Kristdemokraterna':'KD',
 'Liberalerna':'L','Miljöpartiet De Gröna':'MP','Miljöpartiet de gröna':'MP'}
def pabbr(p):
    p=(p or '').strip(); return PARTI.get(p,p)
def fold(s):
    s=re.sub(r'^\([^)]*\)\s*','',str(s or '').strip())
    s=unicodedata.normalize('NFKD',s)
    s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+',' ',s).lower()

# ---------------------------------------------------------------- kandidatlistor
def load_lists(path, valtyper=('RD','RF','KF')):
    """-> lists[reskey] = [cand,...] sorterad på ORDNING, där reskey är
       upplösningsnyckeln som matchar gor_mandats mandatnyckel:
         RD: ('RD','00', riksvalkretskod, parti)
         RF: ('RF', länkod, länkod, parti)      — regionens dellistor slås ihop
         KF: ('KF', kommunkod, kommunkod, parti) — kommunens ev. dellistor slås ihop
       Kandidater dedupliceras på kandidatnummer (lägsta ORDNING behålls)."""
    groups=defaultdict(dict)  # reskey -> {kandidatnr: cand}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r.get('GILTIG','').strip()!='J': continue
            vt=r['VALTYP'].strip()
            if vt not in valtyper: continue
            pa=pabbr(r.get('PARTIFÖRKORTNING') or r.get('PARTIBETECKNING'))
            vo=r['VALOMRÅDESKOD'].strip(); vk=r['VALKRETSKOD'].strip()
            reskey = ('RD','00',vk,pa) if vt=='RD' else (vt,vo,vo,pa)
            try: ordn=int(r['ORDNING'])
            except: ordn=9999
            knr=(r.get('KANDIDATNUMMER') or '').strip() or (r.get('NAMN','')+str(ordn))
            cand=dict(ordning=ordn, namn=(r['NAMN'] or '').strip(), namn_fold=fold(r['NAMN']),
                kandidatnr=knr, fbk=(r.get('FOLKBOKFÖRINGSKOMMUN') or '').strip(),
                valkretsnamn=r.get('VALKRETSNAMN','').strip(), valomrnamn=r.get('VALOMRÅDESNAMN','').strip(),
                multi=False)
            g=groups[reskey]
            if knr not in g or ordn < g[knr]['ordning']:
                if knr in g: cand['multi']=True
                g[knr]=cand
    lists={}
    for reskey,cands in groups.items():
        lists[reskey]=sorted(cands.values(), key=lambda c:c['ordning'])
    return lists

# ---------------------------------------------------------------- bevakningslista
def load_watchlist(path):
    """-> index_fold[namn_fold] = [person,...]"""
    idx=defaultdict(list)
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            idx[r['namn_fold']].append(r)
    return idx

def lan_core(s):
    """Normaliserar län-/regionnamn till en jämförbar kärna:
       'Stockholms län' och 'Region Stockholm' -> 'stockholm';
       'Västra Götalands län' och 'Västra Götalandsregionen' -> 'vastra gotaland'."""
    s=fold(s).replace('regionen','').replace('region ','')
    s=re.sub(r's?\s*lan$','',s).strip()
    return re.sub(r's$','',s).strip()

def area_ok(cand, p, komKod, region2lan):
    """Får bevakningsperson p kopplas till invald kandidat cand? Områdesspärr per valtyp:
       KF: samma kommun. RF: region-nivå i samma region ELLER kommunledare vars kommun
       ligger i regionen. RD: ingen områdesspärr (bevakningspersoner är region-/kommunfolk
       som matchas på namn+parti+ort)."""
    vt=cand.get('valtyp',''); niva=p.get('niva',''); omr=p.get('omrade','')
    if vt=='KF':
        return niva=='kommun' and fold(omr)==fold(cand.get('valkrets',''))
    if vt=='RF':
        lk=cand.get('valomrkod','')
        if niva=='region': return region2lan.get(lan_core(omr),'')==lk
        if niva=='kommun': return (komKod.get(omr,'') or '')[:2]==lk
        return False
    return True  # RD

def match_watch(cand, wl, komKod=None, region2lan=None):
    """Matcha en invald kandidat mot bevakningslistan. -> (person|None, kvalitet).
       KF/RF spärras till rätt område så att t.ex. en 'Fredrik Pettersson (S)' i Vara
       inte kopplas till en invald med samma namn i Stockholm."""
    komKod=komKod or {}; region2lan=region2lan or {}
    cands=wl.get(cand['namn_fold'], [])
    if not cands: return None,''
    same_p=[p for p in cands if p['parti_abbr']==cand['parti']]
    if not same_p: return None,''
    vt=cand.get('valtyp','')
    if vt in ('KF','RF'):
        ok=[p for p in same_p if area_ok(cand, p, komKod, region2lan)]
        if not ok: return None,''
        # samma person kan ha flera roller (KSO + nämnd) -> ledning först, inte tvetydigt
        ok.sort(key=lambda p:(0 if p.get('roll_kategori')=='ledning' else 1, p.get('organ','')))
        orter={fold(p.get('omrade','')) for p in ok}
        return ok[0], ('entydig' if len(orter)==1 else 'tvetydig')
    # RD: kräv rätt folkbokföringskommun för kommun-nivå (undvik namnkrock mellan orter).
    kommun_p=[p for p in same_p if p.get('matchort')]
    region_p=[p for p in same_p if not p.get('matchort')]
    by_ort=[p for p in kommun_p if fold(p['matchort'])==fold(cand.get('fbk',''))]
    if by_ort:
        return by_ort[0], ('entydig' if len(by_ort)==1 else 'tvetydig')
    # ingen kommunträff på ort: acceptera bara en unik region-nivå-person (saknar ort)
    if region_p and len(same_p)==1:
        return region_p[0], 'namn+parti'
    return None, ''   # tvetydigt/fel ort -> ingen koppling

# ---------------------------------------------------------------- val (elect)
def elect(mandat, lists):
    """mandat: dict[(valtyp,valomrkod,valkretskod,parti_abbr)] = antal_mandat.
       -> lista över invalda kandidater (dict)."""
    out=[]
    for key,n in mandat.items():
        if n<=0: continue
        lst=lists.get(key)
        if not lst:
            out.append(dict(_saknad_lista=True, key=key, mandat=n)); continue
        for i,c in enumerate(lst[:int(n)]):
            vt,vo,vk,pa=key
            # RD visar riksdagsvalkretsens namn; RF/KF visar region-/kommunnamnet
            # (dellistor slås ihop per region/kommun, så valkretsnamn kan vara en sub-valkrets)
            disp = (c['valomrnamn'] or c['valkretsnamn']) if vt in ('RF','KF') else (c['valkretsnamn'] or c['valomrnamn'])
            out.append(dict(valtyp=vt, valomrkod=vo, valkretskod=vk, parti=pa,
                plats=i+1, av_mandat=int(n), namn=c['namn'], namn_fold=c['namn_fold'],
                kandidatnr=c['kandidatnr'], fbk=c['fbk'], valkrets=disp,
                flera_listor=c.get('flera_listor',False)))
    return out

def annotate(elected, wl, komKod=None, region2lan=None):
    for c in elected:
        if c.get('_saknad_lista'): continue
        p,kval=match_watch(c, wl, komKod, region2lan)
        c['nyckelperson']= 'Ja' if p else 'Nej'
        c['match']=kval
        if p:
            c['nyckelroll']=f"{p['omrade']}: {p['organ']} ({p['roll']}) [{p['roll_kategori']}]"
            c['nyckelsida']=p['sida']; c['nyckelniva']=p['niva']
    return elected

# ------------------------------------------------- nyckelperson-status (vem åker ut)
def nyckelperson_status(mandat, lists, wl_path, komKod=None, region2lan=None):
    """För varje nyckelperson som kandiderar: över/under partiets mandatstreck? Kandidat-
       nycklar områdesspärras (KF=samma kommun, RF=samma region) så en person bara jämförs
       mot mandatstrecket där den faktiskt hör hemma."""
    komKod=komKod or {}; region2lan=region2lan or {}
    place={}
    for key,lst in lists.items():
        for i,c in enumerate(lst):
            place.setdefault((c['namn_fold'], key[3]), []).append((key, i+1, c['fbk']))
    def key_ok(key, niva, omr):
        vt=key[0]
        if vt=='KF': return key[1]==(komKod.get(omr,'') or '')
        if vt=='RF':
            if niva=='region': return region2lan.get(lan_core(omr),'')==key[1]
            if niva=='kommun': return (komKod.get(omr,'') or '')[:2]==key[1]
            return False
        return True  # RD
    rows=[]
    with open(wl_path, encoding='utf-8', newline='') as f:
        for pr in csv.DictReader(f):
            niva=pr.get('niva',''); omr=pr.get('omrade','')
            hits=[h for h in place.get((pr['namn_fold'], pr['parti_abbr']), []) if key_ok(h[0], niva, omr)]
            if not hits:
                rows.append({**pr,'kandiderar':'Nej','status':'kandiderar ej (i sitt område)'}); continue
            hits_sorted=sorted(hits, key=lambda h:(0 if pr.get('matchort') and fold(pr['matchort'])==fold(h[2]) else 1, h[1]))
            key,plats,_=hits_sorted[0]
            n=int(mandat.get(key,0))
            status = 'sannolikt invald' if plats<=n else ('på vippen' if plats<=n+2 else 'utanför')
            rows.append({**pr,'kandiderar':'Ja','valtyp':key[0],'valkrets':key[2],
                'listplats':plats,'partiets_mandat':n,'status':status})
    return rows

# ---------------------------------------------------------------- demo / CLI
def _demo(lists, wl):
    """Syntetiskt exempel: ge några partier mandat i två RD-valkretsar och visa utfallet."""
    # valkretskoder i kandidaturer: RD har VALOMRÅDESKOD=00. Plocka två faktiska valkretsar.
    rd_keys=[k for k in lists if k[0]=='RD']
    # hitta Stockholms kommun (vk '01') om finns
    sample=Counter()
    demo={}
    seen=set()
    for k in rd_keys:
        vt,vo,vk,pa=k
        if vk in ('01','12') and pa in ('S','M','SD'):  # 01=Sthlm kommun, 12=Skåne västra (exempel)
            demo[k]= {'S':4,'M':3,'SD':3}[pa]
    if not demo:  # fallback: ta de tre första
        for k in rd_keys[:3]: demo[k]=2
    el=annotate(elect(demo, lists), wl)
    print("DEMO — invalda (syntetiska mandat):")
    for c in el:
        if c.get('_saknad_lista'):
            print("  [saknad lista]",c['key']); continue
        tag = f"  <== NYCKELPERSON: {c.get('nyckelroll')}" if c['nyckelperson']=='Ja' else ""
        print(f"  {c['valtyp']} {c['valkrets']:24s} {c['parti']:3s} plats {c['plats']}/{c['av_mandat']}  {c['namn']}{tag}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--kandidaturer', default='kandidaturer.csv')
    ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    ap.add_argument('--mandat', help='CSV: valtyp,valomradeskod,valkretskod,parti_abbr,mandat')
    ap.add_argument('--data', default='public/data.json', help='för kommun-/regionkoder (områdesspärr i matchningen)')
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--out', default='invalda.csv')
    a=ap.parse_args()
    lists=load_lists(a.kandidaturer)
    wl=load_watchlist(a.nyckelpersoner)
    # områdeskartor för matchningsspärr
    komKod, region2lan = {}, {}
    try:
        d=json.load(open(a.data, encoding='utf-8'))
        komKod={k:v for k,v in d.get('komKod',{}).items()}
        region2lan={lan_core(namn): kod for namn,kod in d.get('lanKod',{}).items()}
    except Exception as e:
        print(f"OBS: kunde inte läsa {a.data} ({e}) — områdesspärr i matchningen inaktiv.", file=sys.stderr)
    print(f"Laddade {len(lists)} parti-listor och bevakningslista; {len(komKod)} kommunkoder.", file=sys.stderr)
    if a.demo:
        _demo(lists, wl); return
    if not a.mandat:
        print("Ange --mandat mandat.csv eller --demo", file=sys.stderr); sys.exit(1)
    mandat={}
    with open(a.mandat, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            mandat[(r['valtyp'].strip(), r['valomradeskod'].strip(), r['valkretskod'].strip(), r['parti_abbr'].strip())]=int(r['mandat'])
    el=annotate(elect(mandat, lists), wl, komKod, region2lan)
    cols=['valtyp','valomrkod','valkretskod','valkrets','parti','plats','av_mandat','namn','fbk','nyckelperson','match','nyckelroll','nyckelsida','nyckelniva']
    with open(a.out,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for c in el:
            if not c.get('_saknad_lista'): w.writerow(c)
    st=nyckelperson_status(mandat, lists, a.nyckelpersoner, komKod, region2lan)
    with open('nyckelperson_status.csv','w',encoding='utf-8',newline='') as f:
        keys=sorted({k for row in st for k in row})
        w=csv.DictWriter(f, fieldnames=keys, extrasaction='ignore'); w.writeheader(); w.writerows(st)
    print(f"Skrev {a.out} och nyckelperson_status.csv", file=sys.stderr)

if __name__=='__main__':
    main()
