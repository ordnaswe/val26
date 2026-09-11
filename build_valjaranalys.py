#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_valjaranalys.py — bygger undersidan public/valjaranalys.html för valutfall.se.

Analyserar HUR väljarna röstat kopplat till demografi/ekonomi/ålder/sysselsättning/boende,
inte bara geografi/parti. Två nivåer:
  * Valdistrikt (finast, ur data.json 'districts'): income, edu, foreign, age, hyra (+turnout live).
  * Kommun (Faktadriven/Kolada, data/kommun_kovariater.csv): sysselsättning, arbetslöshet,
    ekonomisk utsatthet, boende/brott/trygghet, integration/demografi.
Tre analysformer: Samband per faktor (scatter + korrelation), Så röstar grupperna (kvintiler),
Förändring över tid (2014→2022). Kartan filtrerar per län.

Kör (efter build.py, i loopen efter personvalet):
  python3 build_valjaranalys.py --data public/data.json --kommun data/kommun_kovariater.csv \
      --out public/valjaranalys.html
Endast standardbibliotek.

FÖRBEHÅLL som visas på sidan: korrelation ≠ kausalitet; ekologiskt felslut (områdessnitt säger
inte hur enskilda röstade); kovariater är en ögonblicksbild; förhandsvisning speglar 2022.
"""
import csv, json, argparse, math
from collections import defaultdict

PIDS = ['V','S','MP','C','L','KD','M','SD']

# Kommunfaktorer (kolumnordning i data/kommun_kovariater.csv efter kommunkod)
KOMF = [
    ('syssgrad',     'Sysselsättningsgrad 20–64', '%',      'Andel förvärvsarbetande 20–64 år.'),
    ('arbloshet',    'Arbetslöshet 20–64',        '%',      'Öppet arbetslösa + program (BAS).'),
    ('arbloshet_ung','Arbetslöshet 16–24',        '%',      'Ungdomsarbetslöshet, årsmedel.'),
    ('langtidsarbl', 'Långtidsarbetslösa 18–65',  '%',      'Andel av befolkningen.'),
    ('medianink',    'Medianinkomst 20–64',       'kr',     'Sammanräknad förvärvsinkomst, median.'),
    ('lag_ekstand',  'Låg ekonomisk standard',    '%',      'Invånare med låg ekonomisk standard.'),
    ('ekbistand',    'Ekonomiskt bistånd',        '%',      'Invånare som fått ekonomiskt bistånd.'),
    ('gini',         'Inkomstojämlikhet (Gini)',  'index',  'Gini för disponibel inkomst.'),
    ('hyresratt',    'Hyresrätter',               '%',      'Andel hyresrätter i beståndet.'),
    ('trangbodd',    'Trångboddhet',              '%',      'Trångboddhet i flerbostadshus (norm 2).'),
    ('brott',        'Anmälda brott',             '/100k',  'Anmälda brott per 100 000 invånare.'),
    ('tathet',       'Befolkningstäthet',         'inv/km²','Invånare per kvadratkilometer.'),
    ('tatortsgrad',  'Tätortsgrad',               '%',      'Andel invånare i tätort.'),
    ('utrikesfodda', 'Utrikes födda',             '%',      'Andel utrikes födda.'),
    ('medelalder',   'Medelålder',                'år',     'Medelålder i kommunen.'),
    ('ensamhushall', 'Ensamhushåll',              '%',      'Andel ensamhushåll.'),
    ('valdeltagande','Valdeltagande (RD)',        '%',      'Valdeltagande i senaste riksdagsval.'),
]

DIST_DESC = {
    'income':  'Medianinkomst i distriktet.',
    'edu':     'Andel med eftergymnasial utbildning.',
    'foreign': 'Andel med utländsk bakgrund.',
    'age':     'Medelålder i distriktet.',
    'hyra':    'Andel som bor i hyresrätt.',
    'turnout': 'Valdeltagande i distriktet.',
    'urban':   'Ort-typ enligt SCB:s DeSO-indelning: 0 = landsbygd, 1 = tätortsnära, 2 = stad. Högre = mer storstad.',
    'syss':    'Andel förvärvsarbetande 20–64 år i området (SCB, 2021). Högre = fler i arbete.',
}

def num(x):
    try:
        if x is None or x == '': return None
        return float(x)
    except: return None

def wpearson(xs, ys, ws):
    """Rost-viktad Pearson-korrelation. Returnerar (r, n) eller (None, n)."""
    sw = pts = 0.0; n = 0
    for x,y,w in zip(xs,ys,ws):
        if x is None or y is None or not w: continue
        sw += w; n += 1
    if n < 8 or sw <= 0: return None, n
    mx = sum(w*x for x,y,w in zip(xs,ys,ws) if x is not None and y is not None and w)/sw
    my = sum(w*y for x,y,w in zip(xs,ys,ws) if x is not None and y is not None and w)/sw
    sxx = syy = sxy = 0.0
    for x,y,w in zip(xs,ys,ws):
        if x is None or y is None or not w: continue
        dx=x-mx; dy=y-my; sxx+=w*dx*dx; syy+=w*dy*dy; sxy+=w*dx*dy
    if sxx<=0 or syy<=0: return None, n
    return sxy/math.sqrt(sxx*syy), n

def build(data_path, kommun_path, out_path):
    d = json.load(open(data_path, encoding='utf-8'))
    meta = d.get('meta', {})
    parties = {p['id']: p for p in d.get('parties', [])}
    cov = d.get('cov', {})
    covKeys = [k for k in d.get('covKeys', []) ]
    komKod = d.get('komKod', {})            # namn -> kod
    lanKod = d.get('lanKod', {}); lanNamn = {v:k for k,v in lanKod.items()}
    elyears = d.get('elyears', [2014,2018,2022,2026])

    # --- valdistriktsnivå ---
    DFAC = []   # (key, lab, unit, desc)  – hoppa turnout om helt tom
    for k in covKeys:
        c = cov.get(k, {})
        DFAC.append((k, c.get('lab', k), c.get('unit',''), DIST_DESC.get(k,'')))
    dist = []   # [lankod, komkod, rost] + [cov per DFAC] + [share per PID]
    tsacc = {k: {p: [ [0.0,0.0,0.0,0.0,0.0] for _ in range(len(elyears)) ] for p in PIDS} for k in covKeys}
    # tsacc[factor][party][yearidx] = [sw, sx, sy, sxx? ...] -> vi gör enkel ansats: samla listor
    ts_pairs = {k: {p: [ ([],[],[]) for _ in range(len(elyears)) ] for p in PIDS} for k in covKeys}
    for ds in d.get('districts', []):
        lan = ds.get('vk') and None  # vk är riksvalkrets, inte län; ta län ur lanKod via ds['lan']
        lankod = lanKod.get(ds.get('lan',''), '')
        komkod = komKod.get(ds.get('kommun',''), '')
        rost = num(ds.get('rost')) or 0.0
        covvals = [num(ds.get(k)) for k in covKeys]
        sh = ds.get('shares', {})
        shares = [num(sh.get(p)) for p in PIDS]
        row = [lankod, komkod, rost] + covvals + shares
        dist.append(row)
        # tidsserie: aktuell kovariat vs series[p][yearidx]
        ser = ds.get('series', {})
        for ki,k in enumerate(covKeys):
            xv = covvals[ki]
            if xv is None: continue
            for p in PIDS:
                arr = ser.get(p)
                if not arr: continue
                for yi in range(min(len(arr), len(elyears))):
                    yv = num(arr[yi])
                    if yv is None: continue
                    xs,ys,ws = ts_pairs[k][p][yi]
                    xs.append(xv); ys.append(yv); ws.append(rost)
    # precompute national tidsserie-korrelationer
    ts = {}
    for k in covKeys:
        ts[k] = {}
        for p in PIDS:
            rs = []
            for yi in range(len(elyears)):
                xs,ys,ws = ts_pairs[k][p][yi]
                r,_ = wpearson(xs,ys,ws)
                rs.append(None if r is None else round(r,3))
            ts[k][p] = rs

    # --- kommunnivå: aggregera RD-andelar rost-viktat ur distrikten ---
    komagg = defaultdict(lambda: {'rost':0.0, 'num':defaultdict(float)})
    # per-år (ur series) för kommun-tidsserie
    ny = len(elyears)
    komyear = defaultdict(lambda: {'w':[0.0]*ny, 'num':[defaultdict(float) for _ in range(ny)]})
    for ds in d.get('districts', []):
        kk = komKod.get(ds.get('kommun',''), '')
        if not kk: continue
        rost = num(ds.get('rost')) or 0.0
        komagg[kk]['rost'] += rost
        sh = ds.get('shares', {})
        for p in PIDS:
            v = num(sh.get(p))
            if v is not None: komagg[kk]['num'][p] += v*rost
        ser = ds.get('series', {})
        for p in PIDS:
            arr = ser.get(p)
            if not arr: continue
            for yi in range(min(len(arr), ny)):
                yv = num(arr[yi])
                if yv is None: continue
                komyear[kk]['num'][yi][p] += yv*rost
                komyear[kk]['w'][yi] += rost
    komshares = {}
    for kk,a in komagg.items():
        r = a['rost'] or 1.0
        komshares[kk] = {p: round(a['num'][p]/r, 2) for p in PIDS}
    # kommunandel per parti per år
    komyearshare = {}
    for kk,a in komyear.items():
        komyearshare[kk] = []
        for yi in range(ny):
            w = a['w'][yi]
            komyearshare[kk].append({p: (a['num'][yi][p]/w if w else None) for p in PIDS})

    # läs Faktadriven-kovariater
    komfac = {}
    try:
        with open(kommun_path, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                kk = (r.get('kommunkod') or '').strip()
                if len(kk) != 4: continue
                komfac[kk] = {key: num(r.get(key)) for key,_,_,_ in KOMF}
    except FileNotFoundError:
        pass
    kom = []
    kod2kom = {v:k for k,v in komKod.items()}
    for kk in sorted(set(list(komshares.keys()))):
        fac = komfac.get(kk)
        if not fac: continue
        kom.append(dict(kod=kk, namn=kod2kom.get(kk,kk), lan=kk[:2],
                        rost=round(komagg[kk]['rost']), fac=fac, sh=komshares[kk]))

    # kommun-tidsserie: aktuell kommun-kovariat vs kommunens andel per parti per val
    ts_kom = {}
    komkeys = [k for k,_,_,_ in KOMF]
    kklist = [k['kod'] for k in kom]
    for fk in komkeys:
        ts_kom[fk] = {}
        for p in PIDS:
            rs = []
            for yi in range(ny):
                xs, ys, ws = [], [], []
                for kk in kklist:
                    xv = komfac.get(kk,{}).get(fk)
                    yv = (komyearshare.get(kk,[{}]*ny)[yi] or {}).get(p) if kk in komyearshare else None
                    w = komagg[kk]['rost']
                    xs.append(xv); ys.append(yv); ws.append(w)
                r,_ = wpearson(xs, ys, ws)
                rs.append(None if r is None else round(r,3))
            ts_kom[fk][p] = rs

    counted = total = None
    import re
    m = re.search(r'(\d+)\D+(\d+)', meta.get('status','') or '')
    if m: counted, total = int(m.group(1)), int(m.group(2))

    payload = dict(
        meta=dict(built=meta.get('built',''), status=meta.get('status',''),
                  counted=counted, total=total, source=meta.get('source_label','')),
        parties=[{'id':k,'namn':v.get('namn',k),'color':v.get('color','#888')} for k,v in parties.items()],
        pids=PIDS, elyears=elyears,
        dfac=[{'key':k,'lab':l,'unit':u,'desc':desc} for k,l,u,desc in DFAC],
        komf=[{'key':k,'lab':l,'unit':u,'desc':desc} for k,l,u,desc in KOMF],
        dcols=['lan','kom','rost']+covKeys+PIDS,
        dist=dist,
        kom=kom,
        ts=ts,
        ts_kom=ts_kom,
        geo=dict(w=d.get('geoW',1000), h=d.get('geoH',2304),
                 lan=d.get('granser',{}).get('lan',{}), lanNamn=lanNamn),
    )
    html = PAGE.replace('/*__DATA__*/', json.dumps(payload, ensure_ascii=False))
    with open(out_path,'w',encoding='utf-8') as f: f.write(html)
    ndist = len(dist); nkom = len(kom)
    print(f"Skrev {out_path}: {ndist} distrikt, {len(DFAC)} distriktsfaktorer, "
          f"{nkom} kommuner, {len(KOMF)} kommunfaktorer, {len(payload['geo']['lan'])} län på kartan.")

PAGE = r"""<!doctype html>
<html lang="sv"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Väljaranalys – valutfall.se</title>
<style>
 :root{--paper:#f3f5f7;--surface:#fff;--surface2:#eaeef2;--ink:#161b22;--ink2:#4c5563;--ink3:#727c8a;
  --line:#dce1e7;--accent:#0e7c74;--accent2:#0b605a;--pos:#2e7d5b;--neg:#b0313f;
  --shadow:0 1px 2px rgba(16,22,30,.05),0 8px 22px -14px rgba(16,22,30,.22)}
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;
  --ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;--line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 28px -16px rgba(0,0,0,.6)}}
 :root[data-theme=dark]{--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;--ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;
  --line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88}
 *{box-sizing:border-box}
 body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
 .wrap{max-width:1000px;margin:0 auto;padding:0 18px 64px}
 a{color:var(--accent2)}
 header.top{padding:22px 0 12px}
 .rowb{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
 .eyebrow{font:600 .72rem/1 system-ui;letter-spacing:.14em;text-transform:uppercase;color:var(--accent2)}
 h1{margin:8px 0 4px;font-size:1.8rem;letter-spacing:-.01em}
 .sub{color:var(--ink2);margin:0;max-width:66ch;font-size:.95rem}
 .meta{margin-top:10px;font:.75rem/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink3);display:flex;gap:6px 16px;flex-wrap:wrap}
 .btn{background:var(--surface);color:var(--ink2);border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer;font:.74rem ui-monospace,monospace}
 .btn:hover{border-color:var(--accent);color:var(--accent2)}
 .caveat{margin:12px 0 0;padding:10px 14px;border-radius:10px;background:var(--surface2);color:var(--ink2);font-size:.82rem}
 .banner{display:none;margin:12px 0 0;padding:10px 14px;border-radius:10px;background:#f3e7c9;color:#8a6200;font-size:.9rem;font-weight:600}
 .banner.show{display:block}
 .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:18px 0 6px;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow)}
 .ctl{display:flex;flex-direction:column;gap:4px}
 .ctl label{font:.7rem/1 system-ui;letter-spacing:.03em;text-transform:uppercase;color:var(--ink3)}
 select,.seg{border:1px solid var(--line);background:var(--surface2);color:var(--ink);border-radius:9px;padding:8px 10px;font:inherit;cursor:pointer}
 .seg{display:inline-flex;gap:2px;padding:3px}
 .seg button{border:none;background:none;color:var(--ink2);border-radius:7px;padding:6px 12px;cursor:pointer;font:600 .85rem system-ui}
 .seg button[aria-pressed=true]{background:var(--accent);color:#fff}
 .facdesc{color:var(--ink3);font-size:.8rem;margin:2px 0 0}
 .tabs{display:flex;gap:4px;flex-wrap:wrap;margin:16px 0 0}
 .tab{flex:1 1 auto;min-width:110px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:9px 12px;cursor:pointer;font:600 .9rem system-ui;color:var(--ink2)}
 .tab[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}
 .panel{background:var(--surface);border:1px solid var(--line);border-top:none;border-radius:0 0 14px 14px;padding:16px;box-shadow:var(--shadow)}
 .maprow{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;margin-top:14px}
 .mapbox{flex:0 0 150px;max-width:38vw}
 svg.map{width:100%;height:auto;display:block}
 svg.map path{fill:var(--surface2);stroke:var(--paper);stroke-width:1.2;cursor:pointer}
 svg.map path:hover{fill:var(--accent)} svg.map path.sel{fill:var(--accent);stroke:var(--accent2)}
 .selchip{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;border-radius:999px;padding:5px 8px 5px 13px;font-size:.82rem;font-weight:600;margin-left:8px}
 .selchip button{background:rgba(255,255,255,.25);border:none;color:#fff;width:20px;height:20px;border-radius:50%;cursor:pointer}
 .chart{width:100%;overflow-x:auto}
 .corrtab{width:100%;border-collapse:collapse;font-size:.9rem;margin-top:6px}
 .corrtab th,.corrtab td{padding:7px 8px;border-top:1px solid var(--line);text-align:left}
 .corrtab td.r{text-align:right;font:.86rem ui-monospace,monospace}
 .bar{height:9px;border-radius:5px;display:inline-block;vertical-align:middle}
 .pf{font:.72rem ui-monospace,monospace;color:#fff;border-radius:5px;padding:1px 6px}
 .muted{color:var(--ink3)} .empty{color:var(--ink3);font-style:italic;padding:14px 2px}
 .lead{color:var(--ink2);font-size:.9rem;margin:0 0 10px}
 .note{color:var(--ink3);font-size:.78rem;margin-top:10px}
 .explain{background:var(--surface2);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;padding:0 13px}
 .explain summary{cursor:pointer;padding:10px 0;font-weight:600;font-size:.85rem;color:var(--accent2)}
 .explain .body{padding:0 0 10px}
 .explain p{margin:0 0 8px;font-size:.86rem;color:var(--ink2);line-height:1.55}
 .explain b{color:var(--ink)}
 .takeaway{background:var(--surface2);border-left:3px solid var(--accent);border-radius:8px;padding:10px 13px;margin:12px 0;font-size:.92rem}
 .scalekey{display:flex;gap:6px 14px;flex-wrap:wrap;font-size:.78rem;color:var(--ink3);margin:4px 0 0}
 .fc{border:1.5px solid var(--line);background:var(--surface);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:.82rem;color:var(--ink2)}
 .fc.on{background:var(--accent);border-color:var(--accent);color:#fff}
 .fc.off{opacity:.6;border-style:dashed}
 .fc:hover{border-color:var(--accent)}
 .scalekey span b{color:var(--ink2)}
 text{fill:var(--ink2)} .axis{stroke:var(--line)}
 footer{padding-top:24px;margin-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:.8rem}
 @media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head>
<body><div class="wrap">
<header class="top">
 <div class="rowb"><span class="eyebrow">valutfall.se · väljaranalys</span>
  <button class="btn" id="theme" type="button" aria-label="Byt tema">☾ / ☀</button></div>
 <h1>Väljaranalys</h1>
 <p class="sub">Hur hänger väljarnas röstning ihop med vilka de är – inkomst, utbildning, ålder, sysselsättning, boende? Välj en faktor och se sambandet med varje partis stöd, hur olika grupper röstar, och hur det ändrats över tid. Klicka på ett län för att zooma in.</p>
 <div class="meta" id="meta"></div>
 <div class="caveat">Samband är inte orsakssamband, och områdessnitt säger inte hur enskilda personer röstat (ekologiskt felslut). Kovariaterna är en ögonblicksbild (senaste tillgängliga år). Förhandsvisningen speglar valet 2022; på valnatten fylls valdistrikten med riktig data.</div>
 <div class="banner" id="banner">Nya siffror finns – sidan uppdateras…</div>
</header>

<div class="controls">
 <div class="ctl"><label>Nivå</label>
   <span class="seg" id="lvl"><button data-lvl="dist" aria-pressed="true">Valdistrikt</button><button data-lvl="kom" aria-pressed="false">Kommun</button></span></div>
 <div class="ctl"><label>Faktor</label><select id="factor"></select><div class="facdesc" id="facdesc"></div></div>
 <div class="ctl"><label>Parti</label><select id="party"></select></div>
 <div class="ctl" id="selwrap"></div>
</div>

<div class="tabs" id="tabs" role="tablist">
 <button class="tab" role="tab" data-mode="samband">Samband</button>
 <button class="tab" role="tab" data-mode="grupper">Så röstar grupperna</button>
 <button class="tab" role="tab" data-mode="tid">Förändring över tid</button>
 <button class="tab" role="tab" data-mode="multi">Flera faktorer</button>
 <button class="tab" role="tab" data-mode="profil">Partiprofil</button>
</div>
<div class="panel" id="panel"></div>

<div class="maprow">
 <div class="mapbox"><svg class="map" id="map" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Karta över län"></svg></div>
 <div style="flex:1;min-width:220px" class="muted" id="maphelp"></div>
</div>

<footer>
 <p id="src"></p>
 <p>Underlag: Valmyndigheten (röster per valdistrikt), SCB (distriktskovariater) och Kolada/Faktadriven (kommunmått). Metod: rost-viktad Pearson-korrelation och kvintiler. En del av <a href="/">valutfall.se</a> · Sandro Wennberg.</p>
</footer>
</div>

<script>
const DATA = /*__DATA__*/;
const PC = Object.fromEntries(DATA.parties.map(p=>[p.id,p.color]));
const PN = Object.fromEntries(DATA.parties.map(p=>[p.id,p.namn]));
const $ = s=>document.querySelector(s);
const esc = s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const CI = Object.fromEntries(DATA.dcols.map((c,i)=>[c,i]));   // kolumnindex i dist-rader
let level='dist', factorKey=DATA.dfac[0].key, party=DATA.pids[0], mode='samband', selLan=null, nbins=5, mvSel=null;

(function(){const r=document.documentElement,b=$('#theme');
 const cur=()=>r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
 b.onclick=()=>r.setAttribute('data-theme',cur()==='dark'?'light':'dark');})();

function head(){const m=DATA.meta;
 $('#meta').innerHTML=[m.status?esc(m.status):'',m.built?('Uppdaterad '+m.built.slice(11,16)):''].filter(Boolean).map(x=>`<span>${x}</span>`).join('');
 $('#src').textContent=m.source||'';}

// ---- faktorer & datahämtning ----
function facs(){return level==='dist'?DATA.dfac:DATA.komf;}
function facMeta(){return facs().find(f=>f.key===factorKey)||facs()[0];}
// returnerar {x:[...], sh:{pid:[...]}, w:[...]} filtrerat på selLan
function rows(){
 const out={x:[],w:[],sh:{}}; DATA.pids.forEach(p=>out.sh[p]=[]);
 if(level==='dist'){
   const fi=CI[factorKey];
   for(const r of DATA.dist){
     if(selLan && r[CI.lan]!==selLan) continue;
     out.x.push(r[fi]); out.w.push(r[CI.rost]||0);
     DATA.pids.forEach(p=>out.sh[p].push(r[CI[p]]));
   }
 } else {
   for(const k of DATA.kom){
     if(selLan && k.lan!==selLan) continue;
     out.x.push(k.fac[factorKey]); out.w.push(k.rost||0);
     DATA.pids.forEach(p=>out.sh[p].push(k.sh[p]));
   }
 }
 return out;
}
function wpearson(xs,ys,ws){let sw=0,n=0;
 for(let i=0;i<xs.length;i++){if(xs[i]==null||ys[i]==null||!ws[i])continue;sw+=ws[i];n++;}
 if(n<8||sw<=0)return{r:null,n};
 let mx=0,my=0;for(let i=0;i<xs.length;i++){if(xs[i]==null||ys[i]==null||!ws[i])continue;mx+=ws[i]*xs[i];my+=ws[i]*ys[i];}
 mx/=sw;my/=sw;let sxx=0,syy=0,sxy=0;
 for(let i=0;i<xs.length;i++){if(xs[i]==null||ys[i]==null||!ws[i])continue;const dx=xs[i]-mx,dy=ys[i]-my,w=ws[i];sxx+=w*dx*dx;syy+=w*dy*dy;sxy+=w*dx*dy;}
 if(sxx<=0||syy<=0)return{r:null,n};return{r:sxy/Math.sqrt(sxx*syy),n};
}
const rcol=r=>r==null?'var(--ink3)':(r>0?'var(--pos)':'var(--neg)');
const strength=r=>{r=Math.abs(r);return r<0.1?'inget':r<0.3?'svagt':r<0.5?'måttligt':r<0.7?'tydligt':'starkt';};
// klartext-styrka för lekmän
const styrkeOrd=r=>{const a=Math.abs(r);return a<0.1?'nästan inget':a<0.2?'svagt':a<0.35?'märkbart':a<0.5?'tydligt':'starkt';};
const omr=()=>level==='dist'?'valdistrikt':'kommuner';
// en mening om ett samband för en lekman
function plainCorr(p,r,facLabLc){const namn=PN[p]||p;
 if(Math.abs(r)<0.1) return `${namn} röstas ungefär lika oavsett ${facLabLc} – <b>nästan inget samband</b>.`;
 return r>0
   ? `${namn} är <b>starkare</b> i ${omr()} där ${facLabLc} är <b>hög</b>, och svagare där den är låg – <b>${styrkeOrd(r)} samband</b>.`
   : `${namn} är <b>starkare</b> i ${omr()} där ${facLabLc} är <b>låg</b>, och svagare där den är hög – <b>${styrkeOrd(r)} samband</b>.`;}
// hopfällbar förklaring per flik
function explain(kind){const facLc=facMeta().lab.toLowerCase();
 const scale=`<div class="scalekey"><span><b>0</b> inget</span><span><b>0,1</b> svagt</span><span><b>0,3</b> tydligt</span><span><b>0,5+</b> starkt</span></div>`;
 const P={
  samband:`<p>Varje stapel visar hur <b>${esc(facLc)}</b> och ett partis stöd följs åt över alla ${omr()} i landet, sammanfattat i ett tal mellan <b>−1 och +1</b> (kallas korrelation).</p>
    <p><b>0</b> = inget samband (faktorn säger ingenting om partiets stöd). Stapel <b>åt höger (+)</b> = partiet är starkare där faktorn är hög. Stapel <b>åt vänster (−)</b> = starkare där faktorn är låg. Ju längre stapel, desto tydligare mönster.</p>
    <p>Det beskriver hur <b>områden</b> skiljer sig åt – inte <b>varför</b>, och inte hur en enskild person röstar.</p>${scale}`,
  grupper:`<p>Vi radar upp alla ${omr()} efter <b>${esc(facLc)}</b>, från lägst till högst, och delar dem i lika stora grupper med ungefär lika många röster i varje. Stapeln visar hur stor andel som röstar på partiet i varje grupp.</p>
    <p>Skiljer sig staplarna mycket mellan lägsta och högsta gruppen hänger faktorn ihop med röstningen. Är de nästan lika spelar faktorn liten roll.</p>`,
  tid:`<p>Linjen visar sambandets styrka (−1 till +1) vid varje val. <b>Uppåt</b> = kopplingen har blivit mer positiv (partiet allt starkare där faktorn är hög). <b>Nedåt</b> = mer negativ. Nära mittlinjen = svagt samband.</p>`,
  profil:`<p><b>Väljarprofilen</b> sammanfattar i ord var partiet är starkt och svagt, utifrån sambanden ovan. <b>Rörelsen</b> visar för varje faktor om kopplingen stärkts (▲) eller försvagats (▼) sedan 2014.</p>
    <p>Kom ihåg: det handlar om skillnader mellan områden, inte om enskilda väljare.</p>`,
  multi:`<p>Här vägs flera faktorer in <b>samtidigt</b>. Vanliga samband överlappar – t.ex. hög inkomst och hög utbildning följs ofta åt. Den här vyn räknar ut varje faktors <b>egna</b> bidrag när de andra hålls konstanta.</p>
    <p><b>Enkelt samband</b> = faktorn ensam (samma som i Samband-fliken). <b>Eget bidrag</b> = vad faktorn tillför utöver de andra. Blir det egna bidraget mycket mindre än det enkla sambandet, så "förklaras faktorn bort" av de andra.</p>
    <p><b>Förklaringsgrad (R²)</b> säger hur stor del av skillnaderna mellan områden som faktorerna tillsammans fångar (0 % = inget, 100 % = allt). Staplarna är standardiserade så att de kan jämföras rakt av. Kryssa i/ur faktorer nedan.</p>`
 };
 return `<details class="explain"><summary>Vad betyder det här?</summary><div class="body">${P[kind]||''}</div></details>`;}

// ---- Samband: liggande diverging-stapel (alla partier) + scatter (valt parti) ----
function renderSamband(){const R=rows(),fm=facMeta();
 const corr=DATA.pids.map(p=>({p,...wpearson(R.x,R.sh[p],R.w)})).filter(o=>o.r!=null).sort((a,b)=>b.r-a.r);
 if(!corr.length){$('#panel').innerHTML='<div class="empty">För få områden för korrelation i valt urval.</div>';return;}
 const n=corr[0].n; const fl=fm.lab.toLowerCase();
 const top=corr[0], bot=corr[corr.length-1];
 const tolk=`<div class="takeaway">Så läser du det: ${plainCorr(top.p, top.r, fl)}`+
   (bot.r<-0.1&&bot.p!==top.p?` Tvärtom för ${plainCorr(bot.p, bot.r, fl).replace(/^[^ ]+ /,'')}`:'')+`</div>`;
 $('#panel').innerHTML=explain('samband')+`<p class="lead">Hur <b>${esc(fl)}</b> (${esc(fm.unit)}) hänger ihop med varje partis stöd${selLan?' i '+esc(DATA.geo.lanNamn[selLan]||selLan):''}. Staplar åt höger = partiet starkare där faktorn är hög, åt vänster = starkare där den är låg.</p>
   <div class="chart">${divergeBars(corr)}</div>
   ${tolk}
   <p class="lead" style="margin-top:16px">Punktdiagram: varje prick är ett ${level==='dist'?'valdistrikt':'kommun'} (större prick = fler röster). Lutar molnet uppåt åt höger följs hög ${esc(fl)} av högt stöd för ${esc(PN[party]||party)}; lutar det nedåt är det tvärtom.</p>
   <div class="chart" id="scatter"></div>
   <p class="note">Bygger på ${n} ${omr()} med data. Klicka ett län i kartan för att räkna om för just det länet.</p>`;
 drawScatter(R, party, fm);
}
function divergeBars(corr){
 const W=660, rowH=30, mT=24, mB=8, mL=150, mR=44, midW=W-mL-mR;
 const H=mT+mB+corr.length*rowH;
 const maxA=Math.max(...corr.map(o=>Math.abs(o.r)),0.3);
 const cx=mL+midW/2, half=midW/2;
 const sx=r=>cx+(r/maxA)*half;
 // rutnät/ticks
 const ticks=[-maxA,-maxA/2,0,maxA/2,maxA];
 const grid=ticks.map(t=>`<line x1="${sx(t).toFixed(1)}" y1="${mT-6}" x2="${sx(t).toFixed(1)}" y2="${H-mB}" stroke="var(--line)" ${t===0?'stroke-width="1.5"':'stroke-dasharray="2 3"'}/>
   <text x="${sx(t).toFixed(1)}" y="${mT-10}" font-size="10" text-anchor="middle">${t>0?'+':''}${t.toFixed(1)}</text>`).join('');
 const bars=corr.map((o,i)=>{const y=mT+i*rowH+rowH/2; const x=sx(o.r);
   const x0=Math.min(cx,x), w=Math.abs(x-cx);
   return `<text x="${mL-10}" y="${(y+4).toFixed(1)}" font-size="12" text-anchor="end">${esc(PN[o.p]||o.p)}</text>
     <rect x="${x0.toFixed(1)}" y="${(y-9).toFixed(1)}" width="${Math.max(w,1).toFixed(1)}" height="18" rx="3" fill="${PC[o.p]||'#888'}"/>
     <text x="${(o.r>=0?x+6:x-6).toFixed(1)}" y="${(y+4).toFixed(1)}" font-size="11" text-anchor="${o.r>=0?'start':'end'}" fill="var(--ink2)">${o.r>0?'+':''}${o.r.toFixed(2)}</text>`;}).join('');
 return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:680px">${grid}${bars}</svg>`;
}
function drawScatter(R, p, fm){
 const pts=[]; for(let i=0;i<R.x.length;i++){if(R.x[i]!=null&&R.sh[p][i]!=null&&R.w[i])pts.push([R.x[i],R.sh[p][i],R.w[i]]);}
 if(!pts.length){$('#scatter').innerHTML='<div class="empty">Ingen data.</div>';return;}
 const W=640,H=300,mL=44,mB=34,mT=10,mR=10;
 const xs=pts.map(a=>a[0]),ys=pts.map(a=>a[1]);
 const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=0,ymax=Math.max(...ys)*1.05||1;
 const sx=v=>mL+(v-xmin)/((xmax-xmin)||1)*(W-mL-mR), sy=v=>H-mB-(v-ymin)/((ymax-ymin)||1)*(H-mB-mT);
 // sampla för rendering om många
 let draw=pts; if(pts.length>1600){draw=[];const step=pts.length/1600;for(let i=0;i<pts.length;i+=step)draw.push(pts[Math.floor(i)]);}
 const rmax=Math.max(...draw.map(a=>a[2]));
 const dots=draw.map(a=>`<circle cx="${sx(a[0]).toFixed(1)}" cy="${sy(a[1]).toFixed(1)}" r="${(1.2+Math.sqrt(a[2]/rmax)*2.6).toFixed(1)}" fill="${PC[p]||'#888'}" fill-opacity="0.45"/>`).join('');
 const gx=[xmin,(xmin+xmax)/2,xmax].map(v=>`<text x="${sx(v).toFixed(1)}" y="${H-mB+16}" font-size="11" text-anchor="middle">${v>=1000?Math.round(v):(Math.round(v*10)/10)}</text>`).join('');
 const gy=[0,ymax/2,ymax].map(v=>`<text x="${mL-6}" y="${(sy(v)+4).toFixed(1)}" font-size="11" text-anchor="end">${Math.round(v)}</text>`).join('');
 $('#scatter').innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:660px">
   <line class="axis" x1="${mL}" y1="${H-mB}" x2="${W-mR}" y2="${H-mB}"/><line class="axis" x1="${mL}" y1="${mT}" x2="${mL}" y2="${H-mB}"/>
   ${dots}${gx}${gy}
   <text x="${(mL+W)/2}" y="${H-2}" font-size="11" text-anchor="middle">${esc(fm.lab)} (${esc(fm.unit)})</text>
   <text transform="rotate(-90 12 ${(H)/2})" x="12" y="${H/2}" font-size="11" text-anchor="middle">${esc(p)} %</text></svg>`;
}

// ---- Så röstar grupperna: kvantiler av faktorn -> viktad snittandel ----
function renderGrupper(){const R=rows(),fm=facMeta();
 const idx=[];for(let i=0;i<R.x.length;i++)if(R.x[i]!=null&&R.w[i])idx.push(i);
 const q=nbins;
 if(idx.length<q*2){$('#panel').innerHTML=ctlBins()+'<div class="empty">För få områden i valt urval för '+(q===5?'kvintiler':'deciler')+'.</div>';return;}
 idx.sort((a,b)=>R.x[a]-R.x[b]);
 const totw=idx.reduce((s,i)=>s+R.w[i],0);
 let acc=0,qi=1;const groups=[[]];
 for(const i of idx){groups[groups.length-1].push(i);acc+=R.w[i];
   if(qi<q && acc>=totw*qi/q){groups.push([]);qi++;}}
 const rowsq=groups.map((g,gi)=>{let sw=0,sy=0,xmin=Infinity,xmax=-Infinity;
   for(const i of g){sw+=R.w[i];sy+=R.w[i]*(R.sh[party][i]||0);xmin=Math.min(xmin,R.x[i]);xmax=Math.max(xmax,R.x[i]);}
   const lab=gi===0?'Lägst':(gi===groups.length-1?'Högst':(''+(gi+1)));
   return {lab,share:sw?sy/sw:0,xmin,xmax,n:g.length};});
 const mx=Math.max(...rowsq.map(r=>r.share),1);
 const bars=rowsq.map(r=>`<div style="display:flex;align-items:center;gap:10px;margin:6px 0">
   <div style="width:66px;font-size:.82rem" class="muted">${esc(r.lab)}</div>
   <div style="flex:1;background:var(--surface2);border-radius:6px;overflow:hidden"><div style="width:${Math.round(r.share/mx*100)}%;background:${PC[party]||'#888'};height:${q>7?15:20}px"></div></div>
   <div style="width:50px;text-align:right;font:.85rem ui-monospace,monospace">${r.share.toFixed(1)}%</div>
   <div style="width:130px;font-size:.72rem" class="muted">${fmtRange(r.xmin,r.xmax,fm)}</div></div>`).join('');
 const lo=rowsq[0], hi=rowsq[rowsq.length-1], diff=hi.share-lo.share, fl=fm.lab.toLowerCase();
 const rikt = Math.abs(diff)<1 ? `röstar ungefär lika (${lo.share.toFixed(0)}–${hi.share.toFixed(0)} %) oavsett ${esc(fl)} – faktorn spelar liten roll.`
   : `får <b>${hi.share.toFixed(1)} %</b> i ${omr()} med högst ${esc(fl)}, mot <b>${lo.share.toFixed(1)} %</b> där den är lägst – en skillnad på <b>${Math.abs(diff).toFixed(1)} procentenheter</b>, ${diff>0?'alltså mer stöd ju högre faktorn är':'alltså mindre stöd ju högre faktorn är'}.`;
 $('#panel').innerHTML=explain('grupper')+ctlBins()+`<p class="lead">${esc(PN[party]||party)}s stöd i ${omr()} grupperade efter ${esc(fl)} (${q===5?'kvintiler = 5 grupper':'deciler = 10 grupper'}, rost-viktat)${selLan?' i '+esc(DATA.geo.lanNamn[selLan]||selLan):''}.</p>
   <div class="takeaway">${esc(PN[party]||party)} ${rikt}</div>${bars}
   <p class="note">Varje grupp rymmer ~${Math.round(100/q)} % av rösterna, ordnade från lägst till högst på faktorn. Sista kolumnen visar faktorns spann i gruppen.</p>`;
 $('#panel').querySelectorAll('[data-bins]').forEach(b=>b.onclick=()=>{nbins=+b.dataset.bins;render();});
}
function ctlBins(){return `<div class="seg" style="margin:0 0 12px;border:1px solid var(--line);border-radius:9px;width:max-content">
   <button data-bins="5" aria-pressed="${nbins===5}">Kvintiler (5)</button>
   <button data-bins="10" aria-pressed="${nbins===10}">Deciler (10)</button></div>`;}
function fmtRange(a,b,fm){const f=v=>v>=1000?Math.round(v):(Math.round(v*10)/10);return `${f(a)}–${f(b)} ${esc(fm.unit)}`;}

// ---- Förändring över tid: nationell tidsserie-korrelation ----
function renderTid(){const fm=facMeta();
 const TS=(level==='dist'?DATA.ts:DATA.ts_kom)||{};
 const ts=TS[factorKey]||{}, yrs=DATA.elyears;
 const series=DATA.pids.map(p=>({p,vals:ts[p]||[]})).filter(o=>o.vals.some(v=>v!=null));
 if(!series.length){$('#panel').innerHTML='<div class="empty">Ingen tidsseriedata.</div>';return;}
 const W=660,H=320,mL=40,mB=40,mT=12,mR=90;
 const sx=i=>mL+i/((yrs.length-1)||1)*(W-mL-mR), sy=r=>mT+(1-(r+1)/2)*(H-mB-mT);
 const axis=`<line class="axis" x1="${mL}" y1="${sy(0)}" x2="${W-mR}" y2="${sy(0)}"/>`+
   [1,0.5,0,-0.5,-1].map(v=>`<text x="${mL-6}" y="${(sy(v)+4)}" font-size="10" text-anchor="end">${v>0?'+':''}${v}</text>`).join('')+
   yrs.map((y,i)=>`<text x="${sx(i)}" y="${H-mB+16}" font-size="11" text-anchor="middle">${y}</text>`).join('');
 const lines=series.map(o=>{const pts=o.vals.map((v,i)=>v==null?null:[sx(i),sy(v)]).filter(Boolean);
   if(pts.length<2)return '';
   const path=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join('');
   const last=pts[pts.length-1];
   return `<path d="${path}" fill="none" stroke="${PC[o.p]||'#888'}" stroke-width="2.2"/>
     ${pts.map(p=>`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${PC[o.p]||'#888'}"/>`).join('')}
     <text x="${(last[0]+6).toFixed(1)}" y="${(last[1]+4).toFixed(1)}" font-size="11" fill="${PC[o.p]||'#888'}">${esc(o.p)}</text>`;}).join('');
 $('#panel').innerHTML=explain('tid')+`<p class="lead">Hur sambandet mellan ${esc(fm.lab.toLowerCase())} och partiernas stöd ändrats över valen. Varje linje = ett parti. Uppåt = partiet har blivit relativt starkare där faktorn är hög; nedåt = svagare.</p>
   <div class="chart"><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:680px">${axis}${lines}</svg></div>
   <p class="note">Kovariaten är aktuell (senaste år) och jämförs mot varje års röstandel — visar hur väljarmönstret förskjutits, med reservation för att faktorns nivå också ändrats.</p>`;
}

// ---- Partiprofil: väljarpersona (aktuellt) + rörelse över tid för alla faktorer ----
function yearIdx(y){return DATA.elyears.indexOf(y);}
function renderProfil(){const F=facs();
 // korrelation för given faktornyckel (aktuellt urval) mot valt parti
 function corrFor(fkey){
   const xs=[],ys=[],ws=[];
   if(level==='dist'){const fi=CI[fkey];for(const r of DATA.dist){if(selLan&&r[CI.lan]!==selLan)continue;xs.push(r[fi]);ys.push(r[CI[party]]);ws.push(r[CI.rost]||0);}}
   else{for(const k of DATA.kom){if(selLan&&k.lan!==selLan)continue;xs.push(k.fac[fkey]);ys.push(k.sh[party]);ws.push(k.rost||0);}}
   return wpearson(xs,ys,ws).r;
 }
 const items=F.map(f=>({f,r:corrFor(f.key)})).filter(o=>o.r!=null).sort((a,b)=>b.r-a.r);
 if(!items.length){$('#panel').innerHTML='<div class="empty">För få områden i valt urval.</div>';return;}
 const strong=Math.max(...items.map(o=>Math.abs(o.r)));
 let pos=items.filter(o=>o.r>=0.12).slice(0,4), neg=items.filter(o=>o.r<=-0.12).slice(-4).reverse();
 if(!pos.length){pos=items.filter(o=>o.r>0).slice(0,2);}
 if(!neg.length){neg=items.filter(o=>o.r<0).slice(-2).reverse();}
 const lc=s=>String(s).replace(/\s*\([^)]*\)\s*$/,'').toLowerCase();
 const plats = selLan?esc(DATA.geo.lanNamn[selLan]||selLan):'hela landet';
 const weak = strong<0.15
   ? `är <b>${esc(PN[party]||party)}</b> brett spritt – inga starka geografiska samband, men svagt märks att partiet är något starkare i ${omr()} med `
   : `är <b>${esc(PN[party]||party)}</b> i genomsnitt starkare i ${omr()} med `;
 const persona = `<p style="font-size:1rem;line-height:1.6">I ${plats} `+weak+
   (pos.length?pos.map(o=>`högre ${esc(lc(o.f.lab))}`).join(', '):'inga särskilt utmärkande drag')+
   (neg.length?`, och svagare där det är högre ${neg.map(o=>esc(lc(o.f.lab))).join(', ')}`:'')+`.</p>`;
 // rörelse över tid: transponera ts/ts_kom -> per faktor för valt parti
 const TS=(level==='dist'?DATA.ts:DATA.ts_kom)||{};
 const i0=Math.max(0,yearIdx(2014)), i2=yearIdx(2022)>=0?yearIdx(2022):DATA.elyears.length-1;
 const mv=F.map(f=>{const arr=(TS[f.key]||{})[party]||[];const a=arr[i0],b=arr[i2];
   return {f,arr,a,b,d:(a!=null&&b!=null)?b-a:null};}).filter(o=>o.arr.some(v=>v!=null));
 // highlights: störst |förändring|
 const hi=mv.filter(o=>o.d!=null).sort((x,y)=>Math.abs(y.d)-Math.abs(x.d)).slice(0,3);
 const hitxt = hi.map(o=>{const dir=o.d>0?'stärkts':'försvagats';
   return `Mellan valen 2014 och 2022 har sambandet mellan ${esc(PN[party]||party)} och <b>${esc(lc(o.f.lab))}</b> ${dir} (styrka ${o.a>0?'+':''}${o.a.toFixed(2)} → ${o.b>0?'+':''}${o.b.toFixed(2)}).`;}).join(' ');
 const rows_mv = mv.slice().sort((x,y)=>(y.b??-9)-(x.b??-9)).map(o=>`<tr>
   <td>${esc(o.f.lab)}</td>
   <td>${sparkR(o.arr)}</td>
   <td class="r" style="color:${rcol(o.a)}">${o.a==null?'–':(o.a>0?'+':'')+o.a.toFixed(2)}</td>
   <td class="r" style="color:${rcol(o.b)}">${o.b==null?'–':(o.b>0?'+':'')+o.b.toFixed(2)}</td>
   <td>${o.d==null?'':(Math.abs(o.d)<0.03?'≈':(o.d>0?'▲':'▼'))+' '+(o.d>0?'+':'')+o.d.toFixed(2)}</td></tr>`).join('');
 $('#panel').innerHTML=explain('profil')+`<div style="background:var(--surface2);border-radius:12px;padding:14px 16px;margin-bottom:14px">
     <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span class="pf" style="background:${PC[party]||'#888'}">${esc(party)}</span><b>${esc(PN[party]||party)} – väljarprofil</b></div>${persona}</div>
   <p class="lead">Rörelse över tid: hur <b>sambandets styrka</b> mellan ${esc(PN[party]||party)} och varje faktor ändrats mellan valen (${level==='dist'?'valdistrikt':'kommuner'}, nationellt).</p>
   <div class="takeaway" style="font-size:.86rem">Siffrorna är <b>sambandets styrka</b> (ett tal −1 till +1), <b>inte</b> en andel. Kolumnen <b>2022</b> = hur starkt sambandet var vid valet 2022. <b>Förändring</b> = hur mycket starkare (▲) eller svagare (▼) sambandet blivit <b>från 2014 till 2022</b>. Exempel: går utländsk bakgrund från +0,10 till +0,30 har partiet blivit relativt starkare i områden med hög andel utländsk bakgrund – det säger inget om hur många procent av partiets väljare som har utländsk bakgrund. (2026 i minigrafen är en spegling av 2022 i förhandsläget.)</div>
   ${hitxt?`<p style="font-size:.92rem">${hitxt}</p>`:''}
   <div class="chart"><table class="corrtab"><thead><tr><th>Faktor</th><th>Utveckling<br><span class="muted" style="font-weight:400;font-size:.72rem">2014 → 2026</span></th><th class="r">Samband<br><span class="muted" style="font-weight:400;font-size:.72rem">2014</span></th><th class="r">Samband<br><span class="muted" style="font-weight:400;font-size:.72rem">2022</span></th><th>Förändring<br><span class="muted" style="font-weight:400;font-size:.72rem">2014→2022</span></th></tr></thead><tbody>${rows_mv}</tbody></table></div>
   <p class="note">Persona bygger på aktuella korrelationer (starkast ± faktorer), rörelsen på tidsserie-korrelationer. Korrelation ≠ kausalitet; områdessnitt säger inte hur enskilda röstade. Faktornivåerna är en ögonblicksbild och kan själva ha ändrats över tid.</p>`;
}
function sparkR(arr){const W=90,H=22,n=arr.length; if(n<2)return '';
 const sx=i=>2+i/(n-1)*(W-4), sy=r=>H/2-(r/1)*(H/2-2);
 const pts=arr.map((v,i)=>v==null?null:[sx(i),sy(v)]).filter(Boolean);
 if(pts.length<2)return '';
 const path=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join('');
 return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="vertical-align:middle"><line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="var(--line)"/><path d="${path}" fill="none" stroke="${PC[party]||'#888'}" stroke-width="1.8"/></svg>`;}

// ---- Flera faktorer: viktad multipel regression (standardiserade koefficienter) ----
function solveLin(A,b){const n=b.length,M=A.map((r,i)=>r.concat([b[i]]));
 for(let col=0;col<n;col++){let piv=col;for(let r=col+1;r<n;r++)if(Math.abs(M[r][col])>Math.abs(M[piv][col]))piv=r;
   if(Math.abs(M[piv][col])<1e-9)return null;[M[col],M[piv]]=[M[piv],M[col]];
   for(let r=0;r<n;r++){if(r===col)continue;const f=M[r][col]/M[col][col];for(let c=col;c<=n;c++)M[r][c]-=f*M[col][c];}}
 return M.map((r,i)=>r[n]/r[i]);}
function colVals(fk){ // faktorkolumn för aktivt urval
 if(level==='dist'){const fi=CI[fk];return DATA.dist.filter(r=>!selLan||r[CI.lan]===selLan);}
 return DATA.kom.filter(k=>!selLan||k.lan===selLan);}
function getVal(row,fk){return level==='dist'?row[CI[fk]]:row.fac[fk];}
function getShare(row){return level==='dist'?row[CI[party]]:row.sh[party];}
function getW(row){return level==='dist'?(row[CI.rost]||0):(row.rost||0);}
// Standard-urval: ett fåtal faktorer som inte överlappar för mycket (annars blir
// regressionen instabil när ~17 starkt korrelerade kommunfaktorer vägs in samtidigt).
const MVDEF_KOM=['syssgrad','medianink','utrikesfodda','medelalder','tathet','hyresratt','valdeltagande'];
function renderMulti(){const F=facs();
 // faktorer med data (uteslut helt tomma, t.ex. turnout i förhandsläge)
 const avail=F.filter(f=>colVals(f.key).some(r=>getVal(r,f.key)!=null));
 if(mvSel===null){
   const def=level==='kom'?MVDEF_KOM.filter(k=>avail.some(f=>f.key===k)):avail.map(f=>f.key);
   mvSel=new Set(def.length>=2?def:avail.map(f=>f.key));
 }
 const sel=avail.filter(f=>mvSel.has(f.key));
 const chips=`<div class="filters" style="margin:0 0 12px">`+avail.map(f=>{const on=mvSel.has(f.key);return `<button class="fc ${on?'on':'off'}" data-mv="${f.key}" aria-pressed="${on}">${on?'✓ ':'+ '}${esc(f.lab.replace(/\s*\([^)]*\)\s*$/,''))}</button>`;}).join('')+`</div>`;
 const head=explain('multi')+`<p class="lead">Vad hänger ihop med <b>${esc(PN[party]||party)}</b>s stöd när flera faktorer vägs in samtidigt (${level==='dist'?'valdistrikt':'kommuner'}${selLan?' i '+esc(DATA.geo.lanNamn[selLan]||selLan):''}). Kryssa faktorer:</p>${chips}`;
 function wire(){$('#panel').querySelectorAll('[data-mv]').forEach(b=>b.onclick=()=>{const k=b.dataset.mv;mvSel.has(k)?mvSel.delete(k):mvSel.add(k);renderMulti();});}
 if(sel.length<2){$('#panel').innerHTML=head+'<div class="empty">Välj minst två faktorer.</div>';wire();return;}
 // bygg rader med alla valda faktorer + andel + vikt
 const rowsD=colVals(sel[0].key);
 const X=[],Y=[],W=[];
 for(const r of rowsD){const xs=sel.map(f=>getVal(r,f.key)),y=getShare(r),w=getW(r);
   if(y==null||!w||xs.some(v=>v==null))continue; X.push(xs);Y.push(y);W.push(w);}
 const n=X.length,k=sel.length;
 if(n<k+8){$('#panel').innerHTML=head+`<div class="empty">För få områden (${n}) för ${k} faktorer i valt urval.</div>`;wire();return;}
 const sw=W.reduce((a,b)=>a+b,0);
 // standardisera varje faktor + y (viktat)
 const mean=col=>X.reduce((a,_,i)=>a+W[i]*X[i][col],0)/sw;
 const mx=sel.map((_,j)=>mean(j)), sx=sel.map((_,j)=>Math.sqrt(X.reduce((a,_,i)=>a+W[i]*(X[i][j]-mx[j])**2,0)/sw)||1);
 const my=Y.reduce((a,y,i)=>a+W[i]*y,0)/sw, sy=Math.sqrt(Y.reduce((a,y,i)=>a+W[i]*(y-my)**2,0)/sw)||1;
 const Xs=X.map(row=>row.map((v,j)=>(v-mx[j])/sx[j])), Ys=Y.map(y=>(y-my)/sy);
 // normalekvationer med intercept
 const p=k+1, A=Array.from({length:p},()=>new Array(p).fill(0)), bb=new Array(p).fill(0);
 for(let i=0;i<n;i++){const row=[1,...Xs[i]],wi=W[i];for(let a=0;a<p;a++){bb[a]+=wi*row[a]*Ys[i];for(let c=0;c<p;c++)A[a][c]+=wi*row[a]*row[c];}}
 const beta=solveLin(A,bb);
 if(!beta||beta.some(v=>!isFinite(v))){$('#panel').innerHTML=head+'<div class="empty">Kunde inte beräkna – faktorerna överlappar för mycket. Ta bort någon och försök igen.</div>';wire();return;}
 let sse=0,sst=0;for(let i=0;i<n;i++){let pred=beta[0];for(let j=0;j<k;j++)pred+=beta[1+j]*Xs[i][j];sse+=W[i]*(Ys[i]-pred)**2;sst+=W[i]*Ys[i]**2;}
 const r2=sst>0?Math.max(0,Math.min(1,1-sse/sst)):NaN;
 if(!isFinite(r2)){$('#panel').innerHTML=head+'<div class="empty">Kunde inte beräkna för valt urval. Prova andra faktorer.</div>';wire();return;}
 // enkelt samband (r) per faktor för jämförelse
 const simple={};sel.forEach((f,j)=>{const xs=X.map(r=>r[j]);simple[f.key]=wpearson(xs,Y,W).r;});
 const items=sel.map((f,j)=>({f,beta:beta[1+j],r:simple[f.key]})).sort((a,b)=>Math.abs(b.beta)-Math.abs(a.beta));
 const corrLike=items.map(o=>({p:o.f.key,r:o.beta,lab:o.f.lab}));
 // återanvänd diverging-stapel men märk med β
 const maxA=Math.max(...items.map(o=>Math.abs(o.beta)),0.2);
 const W2=660,rowH=30,mT=24,mB=8,mL=180,mR=52,midW=W2-mL-mR,H=mT+mB+items.length*rowH,cx=mL+midW/2,half=midW/2,sxf=v=>cx+(v/maxA)*half;
 const ticks=[-maxA,-maxA/2,0,maxA/2,maxA];
 const grid=ticks.map(t=>`<line x1="${sxf(t).toFixed(1)}" y1="${mT-6}" x2="${sxf(t).toFixed(1)}" y2="${H-mB}" stroke="var(--line)" ${t===0?'stroke-width="1.5"':'stroke-dasharray="2 3"'}/><text x="${sxf(t).toFixed(1)}" y="${mT-10}" font-size="10" text-anchor="middle">${t>0?'+':''}${t.toFixed(1)}</text>`).join('');
 const bars=items.map((o,i)=>{const y=mT+i*rowH+rowH/2,x=sxf(o.beta),x0=Math.min(cx,x),w=Math.abs(x-cx);
   return `<text x="${mL-10}" y="${(y+4).toFixed(1)}" font-size="12" text-anchor="end">${esc(o.f.lab.replace(/\s*\([^)]*\)\s*$/,''))}</text>
     <rect x="${x0.toFixed(1)}" y="${(y-9).toFixed(1)}" width="${Math.max(w,1).toFixed(1)}" height="18" rx="3" fill="var(--accent)"/>
     <text x="${(o.beta>=0?x+6:x-6).toFixed(1)}" y="${(y+4).toFixed(1)}" font-size="11" text-anchor="${o.beta>=0?'start':'end'}" fill="var(--ink2)">${o.beta>0?'+':''}${o.beta.toFixed(2)}</text>`;}).join('');
 const svg=`<svg viewBox="0 0 ${W2} ${H}" width="100%" style="max-width:680px">${grid}${bars}</svg>`;
 // tabell enkelt vs eget bidrag + "förklaras bort"
 const tab=`<table class="corrtab"><thead><tr><th>Faktor</th><th class="r">Enkelt samband</th><th class="r">Eget bidrag (β)</th><th></th></tr></thead><tbody>`+
   items.map(o=>{const bort=(Math.abs(o.r)>=0.15 && Math.abs(o.beta)<Math.abs(o.r)*0.45);
     return `<tr><td>${esc(o.f.lab.replace(/\s*\([^)]*\)\s*$/,''))}</td>
       <td class="r" style="color:${rcol(o.r)}">${o.r>0?'+':''}${o.r.toFixed(2)}</td>
       <td class="r" style="color:${rcol(o.beta)}">${o.beta>0?'+':''}${o.beta.toFixed(2)}</td>
       <td class="muted" style="font-size:.8rem">${bort?'förklaras till stor del bort av övriga':''}</td></tr>`;}).join('')+`</tbody></table>`;
 const topb=items[0];
 const summary=`<div class="takeaway">Tillsammans fångar faktorerna <b>${Math.round(r2*100)} %</b> av skillnaderna mellan ${omr()} i ${esc(PN[party]||party)}s stöd. Starkast oberoende koppling: <b>${esc(topb.f.lab.replace(/\s*\([^)]*\)\s*$/,'').toLowerCase())}</b> (β ${topb.beta>0?'+':''}${topb.beta.toFixed(2)}${topb.beta>0?', mer stöd där den är hög':', mindre stöd där den är hög'}).</div>`;
 $('#panel').innerHTML=head+summary+`<div class="chart">${svg}</div>${tab}
   <p class="note">Viktad multipel linjär regression på standardiserade faktorer (β i standardavvikelser, jämförbara). n = ${n} ${omr()}. Korrelation ≠ kausalitet; överlappande faktorer kan göra enskilda β instabila.</p>`;
 wire();
}

function render(){({samband:renderSamband,grupper:renderGrupper,tid:renderTid,multi:renderMulti,profil:renderProfil})[mode]();}

// ---- kontroller ----
function fillFactors(){const sel=$('#factor');sel.innerHTML=facs().map(f=>`<option value="${f.key}">${esc(f.lab)}</option>`).join('');
 if(!facs().some(f=>f.key===factorKey))factorKey=facs()[0].key; sel.value=factorKey; $('#facdesc').textContent=facMeta().desc||'';}
function fillParties(){const sel=$('#party');sel.innerHTML=DATA.pids.map(p=>`<option value="${p}">${esc(PN[p]||p)}</option>`).join('');sel.value=party;}
$('#factor').addEventListener('change',e=>{factorKey=e.target.value;$('#facdesc').textContent=facMeta().desc||'';render();});
$('#party').addEventListener('change',e=>{party=e.target.value;render();});
document.querySelectorAll('#lvl button').forEach(b=>b.addEventListener('click',()=>{
 level=b.dataset.lvl;document.querySelectorAll('#lvl button').forEach(x=>x.setAttribute('aria-pressed',x===b));
 mvSel=null;fillFactors();render();updMapHelp();}));
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{mode=t.dataset.mode;
 document.querySelectorAll('.tab').forEach(x=>x.setAttribute('aria-selected',x===t));render();}));

// ---- karta ----
function ringsToPath(rings){return rings.map(r=>'M'+r.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L')+'Z').join('');}
function drawMap(){const g=DATA.geo,svg=$('#map');if(!g.lan||!Object.keys(g.lan).length){$('.maprow').style.display='none';return;}
 svg.setAttribute('viewBox',`0 0 ${g.w} ${g.h}`);
 svg.innerHTML=Object.entries(g.lan).map(([kod,rings])=>`<path d="${ringsToPath(rings)}" data-lan="${kod}"><title>${esc(g.lanNamn[kod]||kod)}</title></path>`).join('');
 svg.querySelectorAll('path').forEach(p=>p.addEventListener('click',()=>selectLan(p.getAttribute('data-lan'))));}
function selectLan(kod){selLan=(selLan===kod)?null:kod;
 $('#map').querySelectorAll('path').forEach(p=>p.classList.toggle('sel',p.getAttribute('data-lan')===selLan));
 updSel();updMapHelp();render();}
function updSel(){const el=$('#selwrap');if(!selLan){el.innerHTML='';return;}
 el.innerHTML=`<label>Urval</label><span class="selchip">${esc(DATA.geo.lanNamn[selLan]||selLan)} <button aria-label="Rensa">×</button></span>`;
 el.querySelector('button').onclick=()=>selectLan(selLan);}
function updMapHelp(){$('#maphelp').innerHTML= selLan
   ? `Visar <b>${esc(DATA.geo.lanNamn[selLan]||selLan)}</b>. Klicka länet igen för hela landet.`
   : 'Klicka på ett län för att räkna om sambanden för just det länet. Annars visas hela landet.';}

// init
head();fillFactors();fillParties();drawMap();updMapHelp();
document.querySelector('.tab[data-mode=samband]').setAttribute('aria-selected','true');
render();
(function(){let base=DATA.meta.built;setInterval(async()=>{try{const r=await fetch('status.json?_='+Date.now(),{cache:'no-store'});
 const s=await r.json();if(s.built&&s.built!==base){$('#banner').classList.add('show');setTimeout(()=>location.reload(),1500);}}catch(e){}},45000);})();
</script>
</body></html>
"""

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='public/data.json')
    ap.add_argument('--kommun', default='data/kommun_kovariater.csv')
    ap.add_argument('--out', default='public/valjaranalys.html')
    a = ap.parse_args()
    build(a.data, a.kommun, a.out)
