#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_personvalet.py — bygger undersidan public/personvalet.html för valutfall.se.

Läser personlagrets utdata (data/invalda.csv + nyckelperson_status.csv), bevaknings-
listan (nyckelpersoner.csv) och partifärger/karta/meta ur public/data.json, och skriver
en SJÄLVSTÄNDIG HTML-sida med all data inbäddad. Auto-uppdaterar via status.json.

Layout: nationell översikt högst upp (nyckeltal + klickbar länskarta) och flikar
Region / Kommun / Riksdag / På vippen. Kartan styr: klick på ett län filtrerar den
aktiva fliken till länets region/kommuner. Klickbara personer (roll/listplats i modal).

Kör i loopen EFTER invalda.py:
  python3 build_personvalet.py --invalda data/invalda.csv --status nyckelperson_status.csv \
      --nyckelpersoner nyckelpersoner.csv --valkrets data/valkrets.csv \
      --data public/data.json --out public/personvalet.html
Endast standardbibliotek.
"""
import csv, json, re, argparse, unicodedata
from collections import defaultdict

def read_csv(path):
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []

def fold(s):
    s = re.sub(r'^\([^)]*\)\s*', '', str(s or '').strip())
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()

def parse_roll(nyckelroll):
    kat = ''
    m = re.search(r'\[([^\]]+)\]\s*$', nyckelroll or '')
    if m: kat = m.group(1); nyckelroll = nyckelroll[:m.start()].strip()
    omrade, organ = '', nyckelroll
    if ':' in (nyckelroll or ''): omrade, organ = nyckelroll.split(':', 1)
    return omrade.strip(), organ.strip(), kat.strip()

def build(inv_path, status_path, nyckel_path, valkrets_path, data_path, out_path):
    inv  = read_csv(inv_path)
    stat = read_csv(status_path)
    nyckel = read_csv(nyckel_path)
    d = json.load(open(data_path, encoding='utf-8'))
    parties = {p['id']: p for p in d.get('parties', [])}
    meta = d.get('meta', {})
    counted = total = None
    m = re.search(r'(\d+)\D+(\d+)', meta.get('status','') or '')
    if m: counted, total = int(m.group(1)), int(m.group(2))

    # roller per nyckelperson (namn_fold, parti) -> [ {organ,roll,omrade,kategori,sida,niva} ]
    roles_by = defaultdict(list)
    for r in nyckel:
        roles_by[(r.get('namn_fold',''), r.get('parti_abbr',''))].append(dict(
            omrade=r.get('omrade',''), organ=r.get('organ',''), roll=r.get('roll',''),
            kategori=r.get('roll_kategori',''), sida=r.get('sida',''), niva=r.get('niva','')))

    lanKod = d.get('lanKod', {}); lanNamn = {v:k for k,v in lanKod.items()}
    komKod = d.get('komKod', {})   # kommunnamn -> kommunkod (för län ur fbk på RD-nyckelpersoner)
    lanToVk = defaultdict(set)
    for r in read_csv(valkrets_path):
        kk = (r.get('kommunkod') or '').strip(); vknamn = (r.get('valkretsnamn') or '').strip()
        if len(kk) >= 2 and vknamn: lanToVk[kk[:2]].add(vknamn)
    lanToVk = {k: sorted(v) for k,v in lanToVk.items()}

    details = {}   # "Namn|PARTI" -> {vk,plats,valtyp,roller[]}
    def det_key(namn, parti): return f"{namn}|{parti}"
    def add_detail(namn, parti, vk, plats, valtyp):
        k = det_key(namn, parti)
        if k in details: return
        roller = roles_by.get((fold(namn), parti), [])
        details[k] = dict(vk=vk, plats=plats, valtyp=valtyp, roller=roller)

    def lan_of(r):
        return (r.get('valomrkod') or '')[:2]

    in_rd, in_rf, in_kf = [], [], []
    per_vk = defaultdict(list)
    for r in inv:
        vt = r['valtyp']
        if vt == 'RD' or r.get('nyckelperson') == 'Ja':
            add_detail(r['namn'], r['parti'], r['valkrets'], r.get('plats',''), vt)
        if vt == 'RD':
            per_vk[r['valkrets']].append(dict(namn=r['namn'], parti=r['parti'],
                plats=r.get('plats',''), nyckel=(r.get('nyckelperson')=='Ja')))
        if r.get('nyckelperson') == 'Ja':
            omr, organ, kat = parse_roll(r.get('nyckelroll',''))
            # län: RF/KF ur valomrkod; RD-nyckelperson ur folkbokföringskommun (fbk)
            lan = lan_of(r) if vt in ('RF','KF') else (komKod.get(r.get('fbk',''),'') or '')[:2]
            item = dict(namn=r['namn'], parti=r['parti'], valkrets=r['valkrets'], plats=r.get('plats',''),
                        omrade=omr, organ=organ, kategori=kat, sida=r.get('nyckelsida',''),
                        niva=r.get('nyckelniva',''), lan=lan)
            if vt=='RD': in_rd.append(item)
            elif vt=='RF': in_rf.append(item)
            elif vt=='KF': in_kf.append(item)

    risk = []
    for r in stat:
        if r.get('kandiderar')=='Ja' and (r.get('status') or '')=='på vippen':
            vk = (r.get('valkrets') or '')
            lan = vk[:2] if r.get('valtyp') in ('RF','KF') else ''
            risk.append(dict(namn=r.get('namn',''), parti=r.get('parti_abbr',''), omrade=r.get('omrade',''),
                organ=r.get('organ',''), roll=r.get('roll',''), kategori=r.get('roll_kategori',''),
                valtyp=r.get('valtyp',''), listplats=r.get('listplats',''), mandat=r.get('partiets_mandat',''),
                lan=lan, niva=r.get('niva','')))
            add_detail(r.get('namn',''), r.get('parti_abbr',''), vk, r.get('listplats',''), r.get('valtyp',''))
    risk.sort(key=lambda x:x['namn'])

    rd_total = sum(len(v) for v in per_vk.values())
    payload = dict(
        meta=dict(built=meta.get('built',''), status=meta.get('status',''), counted=counted, total=total,
                  source=meta.get('source_label','')),
        parties=[{'id':k,'namn':v.get('namn',k),'color':v.get('color','#888')} for k,v in parties.items()],
        in_rd=sorted(in_rd, key=lambda x:(x['omrade'], x['namn'])),
        in_rf=sorted(in_rf, key=lambda x:(x['omrade'], x['namn'])),
        in_kf=sorted(in_kf, key=lambda x:(x['omrade'], x['namn'])),
        risk=risk,
        per_vk={k:v for k,v in sorted(per_vk.items())},
        rd_total=rd_total,
        details=details,
        geo=dict(w=d.get('geoW',1000), h=d.get('geoH',2304), lan=d.get('granser',{}).get('lan',{}),
                 lanNamn=lanNamn, lanToVk=lanToVk),
    )
    html_out = PAGE.replace('/*__DATA__*/', json.dumps(payload, ensure_ascii=False))
    with open(out_path,'w',encoding='utf-8') as f: f.write(html_out)
    print(f"Skrev {out_path}: riksdag {rd_total} (varav {len(in_rd)} kommun-/regionprofiler), "
          f"region {len(in_rf)}, kommun {len(in_kf)}, på vippen {len(risk)}, "
          f"{len(details)} persondetaljer, {len(payload['geo']['lan'])} län på kartan.")

PAGE = r"""<!doctype html>
<html lang="sv"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personvalet – valutfall.se</title>
<style>
 :root{--paper:#f3f5f7;--surface:#fff;--surface2:#eaeef2;--ink:#161b22;--ink2:#4c5563;--ink3:#727c8a;
  --line:#dce1e7;--accent:#0e7c74;--accent2:#0b605a;--good:#2e7d5b;--warn:#8a6200;--crit:#b0313f;
  --good-s:#dcede4;--warn-s:#f3e7c9;--crit-s:#f3d9dc;--shadow:0 1px 2px rgba(16,22,30,.05),0 8px 22px -14px rgba(16,22,30,.22)}
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;
  --ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;--line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;
  --good:#54c08d;--warn:#d6a43c;--crit:#e27c88;--good-s:#12352a;--warn-s:#352a12;--crit-s:#3a1d22;--shadow:0 1px 2px rgba(0,0,0,.3),0 10px 28px -16px rgba(0,0,0,.6)}}
 :root[data-theme=dark]{--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;--ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;
  --line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--good:#54c08d;--warn:#d6a43c;--crit:#e27c88;--good-s:#12352a;--warn-s:#352a12;--crit-s:#3a1d22}
 *{box-sizing:border-box}
 body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
 .wrap{max-width:1000px;margin:0 auto;padding:0 18px 64px}
 a{color:var(--accent2)}
 header.top{padding:22px 0 14px}
 .row{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
 .eyebrow{font:600 .72rem/1 system-ui;letter-spacing:.14em;text-transform:uppercase;color:var(--accent2)}
 h1{margin:8px 0 4px;font-size:1.8rem;letter-spacing:-.01em}
 .sub{color:var(--ink2);margin:0;max-width:64ch;font-size:.95rem}
 .meta{margin-top:10px;font:.75rem/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink3);display:flex;gap:6px 16px;flex-wrap:wrap}
 .btn{background:var(--surface);color:var(--ink2);border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer;font:.74rem ui-monospace,monospace}
 .btn:hover{border-color:var(--accent);color:var(--accent2)}
 .banner{display:none;margin:12px 0 0;padding:10px 14px;border-radius:10px;background:var(--warn-s);color:var(--warn);font-size:.9rem;font-weight:600}
 .banner.show{display:block}
 .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:8px 0 18px}
 .tile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:13px 15px;box-shadow:var(--shadow)}
 .tile .n{font:700 1.7rem/1 system-ui;letter-spacing:-.02em}.tile .l{color:var(--ink2);font-size:.78rem;margin-top:4px}
 .tile.in .n{color:var(--accent2)}.tile.risk .n{color:var(--crit)}
 /* overview + karta */
 .maprow{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow)}
 .mapbox{flex:0 0 210px;max-width:44vw}
 svg.map{width:100%;height:auto;display:block}
 svg.map path{fill:var(--surface2);stroke:var(--paper);stroke-width:1.2;cursor:pointer;transition:fill .1s}
 svg.map path:hover{fill:var(--accent)}
 svg.map path.sel{fill:var(--accent);stroke:var(--accent2)}
 .mapside{flex:1;min-width:240px}
 .mapside h2{font-size:1.15rem;margin:0 0 6px;letter-spacing:-.01em}
 .mapside p{color:var(--ink2);margin:0 0 10px;font-size:.92rem}
 .quick{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
 .quick button{border:1px solid var(--line);background:var(--surface2);border-radius:999px;padding:6px 13px;cursor:pointer;font:inherit;font-size:.85rem;color:var(--ink)}
 .quick button:hover{border-color:var(--accent);color:var(--accent2)}
 /* flikar */
 .tabs{position:sticky;top:0;z-index:20;display:flex;gap:4px;flex-wrap:wrap;margin:22px 0 0;padding:8px 0;background:var(--paper);border-bottom:1px solid var(--line)}
 .tab{flex:1 1 auto;min-width:80px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:9px 12px;cursor:pointer;font:600 .9rem system-ui;color:var(--ink2)}
 .tab[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}
 .tab .c{font:.72rem ui-monospace,monospace;opacity:.8;margin-left:5px}
 .selbar{margin:12px 0 0;min-height:0}
 .selchip{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;border-radius:999px;padding:6px 8px 6px 14px;font-size:.85rem;font-weight:600}
 .selchip button{background:rgba(255,255,255,.25);border:none;color:#fff;width:22px;height:22px;border-radius:50%;cursor:pointer;font-size:1rem;line-height:1}
 .panel{padding:16px 0 8px}
 h2.ph{font-size:1.25rem;margin:6px 0 3px;letter-spacing:-.01em}.lead{color:var(--ink2);margin:0 0 14px;font-size:.9rem}
 .filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px;align-items:center}
 .chip{border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:5px 12px;cursor:pointer;font-size:.82rem;color:var(--ink2)}
 .chip[aria-pressed=true]{border-color:var(--accent);background:var(--accent);color:#fff}
 .chip:focus-visible,.person:focus-visible,.tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
 input.search{flex:1;min-width:160px;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:9px 12px;font:inherit}
 details{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:2px 14px}
 details summary{cursor:pointer;padding:11px 0;font-weight:600}
 details table{width:100%;border-collapse:collapse;font-size:.9rem;margin-bottom:8px}
 details td{padding:7px 8px;border-top:1px solid var(--line);cursor:pointer}
 details td.p{color:#fff;text-align:center;width:34px;font:.72rem ui-monospace,monospace}
 details td.ro{color:var(--ink2);font-size:.86rem}
 details tr:hover td{background:var(--surface2)}
 .keyrow td{background:var(--good-s)}.keyrow:hover td{background:var(--good-s)}
 .muted{color:var(--ink3)}.empty{color:var(--ink3);font-style:italic;padding:14px 2px}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
 .card{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--pc,#888);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow);cursor:pointer;text-align:left;width:100%;font:inherit;color:inherit}
 .card:hover{border-color:var(--accent)}
 .card .nm{font-weight:600}
 .card .rl{color:var(--ink2);font-size:.86rem;margin-top:4px}
 .card .where{color:var(--ink3);font-size:.8rem;margin-top:4px}
 .card .kb{display:inline-block;margin-top:7px;font:.66rem/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;border-radius:999px;background:var(--surface2);color:var(--ink2)}
 .risk-row{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid var(--line);align-items:baseline;flex-wrap:wrap;cursor:pointer}
 .pill{font:.68rem ui-monospace,monospace;text-transform:uppercase;letter-spacing:.05em;padding:3px 9px;border-radius:999px;background:var(--warn-s);color:var(--warn)}
 .pf{font:.72rem ui-monospace,monospace;color:#fff;border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:1px}
 /* modal */
 .overlay{position:fixed;inset:0;background:rgba(10,15,20,.55);display:none;align-items:center;justify-content:center;padding:18px;z-index:60}
 .overlay.show{display:flex}
 .modal{background:var(--surface);border:1px solid var(--line);border-radius:16px;max-width:460px;width:100%;padding:22px;box-shadow:0 20px 60px -20px rgba(0,0,0,.5)}
 .modal h3{margin:0 0 2px;font-size:1.3rem}
 .modal .close{float:right;border:none;background:none;font-size:1.4rem;cursor:pointer;color:var(--ink3);line-height:1}
 .modal .kv{color:var(--ink2);font-size:.9rem;margin:2px 0}
 .modal .roles{margin:14px 0 0;padding:0;list-style:none}
 .modal .roles li{padding:8px 0;border-top:1px solid var(--line)}
 .modal .roles .r-org{font-weight:600}.modal .roles .r-meta{color:var(--ink2);font-size:.84rem}
 .starnote{color:var(--ink3);font-size:.8rem;margin-top:8px}
 footer{padding-top:24px;margin-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:.8rem}
 @media(prefers-reduced-motion:reduce){*{transition:none!important}}
 @media(max-width:640px){.mapbox{flex:0 0 150px}.tabs{top:0}}
</style></head>
<body><div class="wrap">
<header class="top">
 <div class="row"><span class="eyebrow">valutfall.se · personvalet</span>
  <button class="btn" id="theme" type="button" aria-label="Byt tema">☾ / ☀</button></div>
 <h1>Personvalet</h1>
 <p class="sub">Vilka makthavare tar plats i riksdagen, regionfullmäktige och kommunfullmäktige – och vilka sittande ledare som är på väg ut. Klicka på ett län i kartan, eller välj en flik. Preliminärt, uppdateras löpande under valnatten.</p>
 <div class="meta" id="meta"></div>
 <div class="banner" id="banner">Nya siffror finns – sidan uppdateras…</div>
</header>

<section id="overview">
 <div class="tiles" id="tiles"></div>
 <div class="maprow">
   <div class="mapbox"><svg class="map" id="map" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Karta över Sveriges län"></svg></div>
   <div class="mapside" id="mapside"></div>
 </div>
</section>

<nav class="tabs" id="tabs" role="tablist">
 <button class="tab" role="tab" data-tab="region">Region</button>
 <button class="tab" role="tab" data-tab="kommun">Kommun</button>
 <button class="tab" role="tab" data-tab="riksdag">Riksdag</button>
 <button class="tab" role="tab" data-tab="vippen">På vippen</button>
</nav>
<div class="selbar" id="selbar"></div>

<section class="panel" id="p_region" role="tabpanel">
 <h2 class="ph">Regionmakt</h2>
 <p class="lead">Sittande region- och kommunledare samt tunga nämnders ordförande (vård, trafik) som tar plats i regionfullmäktige. Grupperat per region – klicka för roll och listplats.</p>
 <div class="filters" id="f_region"><input class="search" id="s_region" placeholder="Sök namn eller region…"></div>
 <div id="c_region"></div>
</section>
<section class="panel" id="p_kommun" role="tabpanel" hidden>
 <h2 class="ph">Kommunmakt</h2>
 <p class="lead">Sittande kommunledare (KSO/oppositionsråd) och nämndordförande (utbildning, omsorg/vård) som sannolikt blir invalda i kommunfullmäktige. Grupperat per kommun – klicka för roll och listplats.</p>
 <div class="filters" id="f_kommun"><input class="search" id="s_kommun" placeholder="Sök namn eller kommun…"></div>
 <div id="c_kommun"></div>
 <p class="starnote">Kommunmandat räknas ur områdesandelarna (inkl. lokala partier) och är preliminära. Lokala partiers listor matchas i mån av namnöverensstämmelse.</p>
</section>
<section class="panel" id="p_riksdag" role="tabpanel" hidden>
 <h2 class="ph">Kommun- och regionprofiler in i riksdagen</h2>
 <p class="lead">Sittande ledande lokal- och regionpolitiker (KSO/RSO, kommunal-/regionråd, tunga nämndordförande) som tar plats i riksdagen – preliminärt på listordning. Klicka för roll och listplats.</p>
 <div id="c_rd_makt"></div>
 <h2 class="ph" style="margin-top:28px">Alla invalda per riksvalkrets</h2>
 <p class="lead">Preliminärt invalda på listordning. Nyckelpersoner (de ovan) markerade med ★.</p>
 <div class="filters" id="f_riksdag"><input class="search" id="s_riksdag" placeholder="Sök namn eller valkrets…"></div>
 <div id="c_riksdag"></div>
</section>
<section class="panel" id="p_vippen" role="tabpanel" hidden>
 <h2 class="ph">På vippen</h2>
 <p class="lead">Nyckelpersoner som kandiderar och ligger nära sitt partis mandatstreck i sitt område.</p>
 <div id="c_vippen"></div>
</section>

<footer>
 <p id="src"></p>
 <p>Preliminärt – personröster (kryss) ingår inte och kan kasta om ordningen i slutresultatet. Underlag: Valmyndigheten + politikerdatabas. En del av <a href="/">valutfall.se</a> · Sandro Wennberg.</p>
</footer>
</div>

<div class="overlay" id="overlay"><div class="modal" id="modal"></div></div>

<script>
const DATA = /*__DATA__*/;
const PC = Object.fromEntries(DATA.parties.map(p=>[p.id,p.color]));
const PN = Object.fromEntries(DATA.parties.map(p=>[p.id,p.namn]));
const $ = s=>document.querySelector(s);
const esc = s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KATS=[['ledning','Ledning'],['vård','Vård (region)'],['omsorg/vård','Omsorg'],['utbildning','Utbildning'],['trafik','Trafik (region)']];
const pfSpan=p=>`<span class="pf" style="background:${PC[p]||'#888'}">${esc(p)}</span>`;
let selLan=null, activeTab='region';

(function(){const r=document.documentElement,b=$('#theme');
 const cur=()=>r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
 b.onclick=()=>r.setAttribute('data-theme',cur()==='dark'?'light':'dark');})();

// ---- nyckeltal ----
function head(){const m=DATA.meta;
 $('#meta').innerHTML=[m.status?esc(m.status):'',m.built?('Uppdaterad '+m.built.slice(11,16)):''].filter(Boolean).map(x=>`<span>${x}</span>`).join('');
 $('#src').textContent=m.source||'';
 const pct=(m.counted&&m.total)?Math.round(m.counted/m.total*100)+' %':'–';
 const t=[['in',DATA.rd_total,'invalda i riksdagen'],['in',DATA.in_rf.length,'nyckelpersoner i region'],
   ['in',DATA.in_kf.length,'nyckelpersoner i kommun'],['risk',DATA.risk.length,'på vippen'],['',pct,'av rösterna räknade']];
 $('#tiles').innerHTML=t.map(([c,n,l])=>`<div class="tile ${c}"><div class="n">${n}</div><div class="l">${esc(l)}</div></div>`).join('');}

// ---- modal ----
function openPerson(namn,parti){
 const det=DATA.details[namn+'|'+parti]||{};
 let roles='';
 if(det.roller&&det.roller.length){
   roles='<ul class="roles">'+det.roller.map(r=>`<li><div class="r-org">${esc(r.organ)}</div>
     <div class="r-meta">${esc(r.omrade)}${r.kategori?' · '+esc(r.kategori):''}${r.sida?' · '+esc(r.sida):''}</div></li>`).join('')+'</ul>';
 } else { roles='<p class="kv muted" style="margin-top:12px">Ingen registrerad nyckelroll (ordinarie invald).</p>'; }
 const vt=det.valtyp==='RF'?'Regionval':(det.valtyp==='KF'?'Kommunval':'Riksdagsval');
 $('#modal').innerHTML=`<button class="close" aria-label="Stäng" onclick="closeModal()">×</button>
   <h3>${esc(namn)} ${pfSpan(parti)}</h3>
   <div class="kv">${esc(PN[parti]||parti)}</div>
   <div class="kv">${vt}: ${esc(det.vk||'–')}${det.plats?` · listplats ${esc(det.plats)}`:''}</div>
   <div class="kv muted" style="margin-top:6px">Nuvarande uppdrag:</div>${roles}
   <p class="starnote">Roller ur politikerdatabasen (mandatperioden 2022–2026). Listplats preliminär.</p>`;
 $('#overlay').classList.add('show');
}
function closeModal(){$('#overlay').classList.remove('show');}
$('#overlay').addEventListener('click',e=>{if(e.target.id==='overlay')closeModal();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
document.addEventListener('click',e=>{const el=e.target.closest('[data-nm]');
 if(el&&el.dataset.nm){openPerson(el.dataset.nm, el.dataset.p||'');}});

// ---- grupperad renderare (region/kommun) ----
function chip(txt,onToggle,color){const c=document.createElement('button');c.className='chip';c.textContent=txt;c.setAttribute('aria-pressed','false');
 c.onclick=()=>{const v=c.getAttribute('aria-pressed')!=='true';c.setAttribute('aria-pressed',v);
   if(color){c.style.background=v?color:'';c.style.borderColor=v?color:''}onToggle(v);};return c;}
function renderGroups(items, cont, q, fParti, fKat){
 const f=items.filter(x=>(!selLan||x.lan===selLan)&&(!fParti.size||fParti.has(x.parti))&&(!fKat.size||fKat.has(x.kategori))&&
   (!q||(x.namn+' '+x.omrade).toLowerCase().includes(q)));
 if(!f.length){cont.innerHTML='<div class="empty">Inga träffar för valt filter.</div>';return;}
 const groups={};f.forEach(x=>{(groups[x.omrade]=groups[x.omrade]||[]).push(x);});
 const gk=Object.keys(groups).sort((a,b)=>a.localeCompare(b,'sv'));
 const openAll=!!(q||fParti.size||fKat.size||selLan)&&gk.length<=25;
 cont.innerHTML=gk.map(omr=>{const rows=groups[omr];
   const body=rows.map(x=>`<tr data-nm="${esc(x.namn)}" data-p="${esc(x.parti)}">
     <td class="p" style="background:${PC[x.parti]||'#888'}">${esc(x.parti)}</td>
     <td>${esc(x.namn)}</td><td class="ro">${esc(x.organ)}</td></tr>`).join('');
   return `<details${openAll?' open':''}><summary>${esc(omr)} <span class="muted" style="font-weight:400">· ${rows.length} nyckelperson${rows.length>1?'er':''}</span></summary><table>${body}</table></details>`;
 }).join('');
}
function panelFactory(kind, items){
 const cont=$('#c_'+kind), search=$('#s_'+kind), fbox=$('#f_'+kind);
 let fParti=new Set(), fKat=new Set();
 const render=()=>renderGroups(items, cont, (search.value||'').toLowerCase(), fParti, fKat);
 KATS.filter(([k])=>items.some(x=>x.kategori===k)).forEach(([k,l])=>fbox.insertBefore(chip(l,v=>{v?fKat.add(k):fKat.delete(k);render();}),search));
 [...new Set(items.map(x=>x.parti))].sort().forEach(p=>fbox.insertBefore(chip(p,v=>{v?fParti.add(p):fParti.delete(p);render();},PC[p]),search));
 search.addEventListener('input',render);
 return render;
}

// ---- riksdag: kommun-/regionprofiler in + per valkrets ----
function rdMaktCard(x){return `<button class="card person" style="--pc:${PC[x.parti]||'#888'}" data-nm="${esc(x.namn)}" data-p="${esc(x.parti)}">
   <div><span class="nm">${esc(x.namn)}</span>${pfSpan(x.parti)}</div>
   <div class="rl">${esc(x.organ)}</div>
   <div class="where">${esc(x.omrade)}${x.valkrets?` · valkrets ${esc(x.valkrets)}`:''}${x.plats?` (plats ${esc(x.plats)})`:''}</div>
   ${x.kategori?`<span class="kb">${esc(x.kategori)}</span>`:''}</button>`;}
function renderRDmakt(){const el=$('#c_rd_makt');
 let list=DATA.in_rd.filter(x=>!selLan||x.lan===selLan);
 if(!list.length){el.innerHTML=`<div class="empty">${DATA.rd_total?(selLan?'Inga kända kommun-/regionprofiler i valt län.':'Inga kända kommun-/regionprofiler bland de invalda.'):'Fylls när rösträkningen börjar på valnatten.'}</div>`;return;}
 el.innerHTML='<div class="cards">'+list.map(rdMaktCard).join('')+'</div>';}
function renderRiksdag(){renderRDmakt();const cont=$('#c_riksdag'),q=($('#s_riksdag').value||'').toLowerCase();
 let keys=Object.keys(DATA.per_vk);
 if(selLan){const allow=new Set(DATA.geo.lanToVk[selLan]||[]);keys=keys.filter(k=>allow.has(k));}
 let any=false;
 const parts=keys.map(k=>{let rows=DATA.per_vk[k];
   if(q)rows=rows.filter(r=>(r.namn+' '+k).toLowerCase().includes(q));
   if(!rows.length)return '';any=true;const nk=rows.filter(r=>r.nyckel).length;
   const body=rows.map(r=>`<tr class="${r.nyckel?'keyrow':''}" data-nm="${esc(r.namn)}" data-p="${esc(r.parti)}">
     <td class="p" style="background:${PC[r.parti]||'#888'}">${esc(r.parti)}</td><td>${esc(r.plats)}</td><td>${esc(r.namn)}${r.nyckel?' ★':''}</td></tr>`).join('');
   return `<details${(selLan||q)?' open':''}><summary>${esc(k)} <span class="muted" style="font-weight:400">· ${rows.length} mandat${nk?` · ${nk} nyckel`:''}</span></summary><table>${body}</table></details>`;}).filter(Boolean);
 cont.innerHTML=any?parts.join(''):`<div class="empty">${DATA.rd_total?'Inga träffar.':'Riksdagsmandaten fylls när rösträkningen börjar på valnatten.'}</div>`;}

// ---- vippen ----
function renderVippen(){const el=$('#c_vippen');
 let list=DATA.risk.filter(r=>!selLan||r.lan===selLan);
 if(!list.length){el.innerHTML=`<div class="empty">${selLan?'Ingen på vippen i valt län.':'Inga på vippen ännu.'}</div>`;return;}
 el.innerHTML=list.map(r=>`<div class="risk-row" data-nm="${esc(r.namn)}" data-p="${esc(r.parti)}">
   <div><span style="font-weight:600">${esc(r.namn)}</span> ${pfSpan(r.parti)} <span class="muted">— ${esc(r.omrade)}: ${esc(r.roll)} ${esc(r.organ)}</span></div>
   <div><span class="muted" style="font:.78rem ui-monospace,monospace">plats ${esc(r.listplats)} / ${esc(r.mandat)} (${esc(r.valtyp)})</span> <span class="pill">på vippen</span></div></div>`).join('');}

// ---- flikar ----
const RENDER={region:null,kommun:null,riksdag:renderRiksdag,vippen:renderVippen};
function counts(){return {region:DATA.in_rf.filter(x=>!selLan||x.lan===selLan).length,
  kommun:DATA.in_kf.filter(x=>!selLan||x.lan===selLan).length,
  riksdag:selLan?Object.entries(DATA.per_vk).filter(([k])=>(DATA.geo.lanToVk[selLan]||[]).includes(k)).reduce((a,[,v])=>a+v.length,0):DATA.rd_total,
  vippen:DATA.risk.filter(x=>!selLan||x.lan===selLan).length};}
function paintTabs(){const c=counts();document.querySelectorAll('.tab').forEach(t=>{const k=t.dataset.tab;
  t.setAttribute('aria-selected',k===activeTab);
  t.innerHTML=({region:'Region',kommun:'Kommun',riksdag:'Riksdag',vippen:'På vippen'})[k]+`<span class="c">${c[k]}</span>`;});}
function setTab(name){activeTab=name;
 ['region','kommun','riksdag','vippen'].forEach(k=>{$('#p_'+k).hidden=(k!==name);});
 paintTabs();RENDER[name]&&RENDER[name]();}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{setTab(t.dataset.tab);
  $('#tabs').scrollIntoView({behavior:'smooth',block:'start'});}));

// ---- karta ----
function ringsToPath(rings){return rings.map(r=>'M'+r.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L')+'Z').join('');}
function drawMap(){const g=DATA.geo,svg=$('#map');if(!g.lan||!Object.keys(g.lan).length){$('.maprow').style.display='none';return;}
 svg.setAttribute('viewBox',`0 0 ${g.w} ${g.h}`);
 svg.innerHTML=Object.entries(g.lan).map(([kod,rings])=>
   `<path d="${ringsToPath(rings)}" data-lan="${kod}"><title>${esc(g.lanNamn[kod]||kod)}</title></path>`).join('');
 svg.querySelectorAll('path').forEach(p=>p.addEventListener('click',()=>selectLan(p.getAttribute('data-lan'))));}
function selectLan(kod){selLan=(selLan===kod)?null:kod;
 $('#map').querySelectorAll('path').forEach(p=>p.classList.toggle('sel',p.getAttribute('data-lan')===selLan));
 paintTabs();mapside();selbar();RENDER[activeTab]&&RENDER[activeTab]();
 if(selLan){if(activeTab==='vippen')setTab('region');$('#tabs').scrollIntoView({behavior:'smooth',block:'start'});}}
function mapside(){const el=$('#mapside');const c=counts();
 if(!selLan){el.innerHTML=`<h2>Hela landet</h2>
   <p>Klicka på ett län för att se dess region och kommuner. Eller välj en flik nedan.</p>
   <div class="quick"><button data-go="region">${DATA.in_rf.length} i regionfullmäktige</button>
     <button data-go="kommun">${DATA.in_kf.length} i kommunfullmäktige</button>
     <button data-go="riksdag">${DATA.rd_total} i riksdagen</button></div>`;}
 else{const namn=DATA.geo.lanNamn[selLan]||selLan;
   const komm=[...new Set(DATA.in_kf.filter(x=>x.lan===selLan).map(x=>x.omrade))].length;
   el.innerHTML=`<h2>${esc(namn)}</h2>
     <p>${c.region} nyckelperson${c.region===1?'':'er'} i regionfullmäktige · ${c.kommun} i kommunfullmäktige (${komm} kommun${komm===1?'':'er'})${c.riksdag?` · ${c.riksdag} i riksdagen`:''}.</p>
     <div class="quick"><button data-go="region">Se region</button><button data-go="kommun">Se kommuner</button>
       ${c.riksdag?'<button data-go="riksdag">Riksdag</button>':''}
       <button data-clear="1">Visa hela landet</button></div>`;}
 el.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>{setTab(b.dataset.go);$('#tabs').scrollIntoView({behavior:'smooth',block:'start'});});
 const cl=el.querySelector('[data-clear]');if(cl)cl.onclick=()=>selectLan(selLan);}
function selbar(){const el=$('#selbar');
 if(!selLan){el.innerHTML='';return;}
 const namn=DATA.geo.lanNamn[selLan]||selLan;
 el.innerHTML=`<span class="selchip">Visar: ${esc(namn)} <button aria-label="Rensa" data-clear="1">×</button></span>`;
 el.querySelector('[data-clear]').onclick=()=>selectLan(selLan);}

// ---- init ----
head();drawMap();mapside();
RENDER.region=panelFactory('region', DATA.in_rf);
RENDER.kommun=panelFactory('kommun', DATA.in_kf);
$('#s_riksdag').addEventListener('input',renderRiksdag);
activeTab = DATA.in_rd.length? 'riksdag' : (DATA.in_rf.length? 'region' : 'kommun');
setTab(activeTab);
(function(){let base=DATA.meta.built;setInterval(async()=>{try{const r=await fetch('status.json?_='+Date.now(),{cache:'no-store'});
 const s=await r.json();if(s.built&&s.built!==base){$('#banner').classList.add('show');setTimeout(()=>location.reload(),1500);}}catch(e){}},45000);})();
</script>
</body></html>
"""

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--invalda', default='data/invalda.csv')
    ap.add_argument('--status', default='nyckelperson_status.csv')
    ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    ap.add_argument('--valkrets', default='data/valkrets.csv')
    ap.add_argument('--data', default='public/data.json')
    ap.add_argument('--out', default='public/personvalet.html')
    a = ap.parse_args()
    build(a.invalda, a.status, a.nyckelpersoner, a.valkrets, a.data, a.out)
