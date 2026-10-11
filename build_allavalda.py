#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_allavalda.py — allavalda.se: alla folkvalda i riksdag, regionfullmäktige och kommunfullmäktige 2026.

Statisk sajt ur samma data som valutfall.se:
  data/valda.csv, data/ersattare.csv, data/personroster.csv (valda.py ur Valmyndighetens slutliga filer)
  data/kandidaturer.csv (folkbokföringskommun, listplats), data/valkrets.csv (kommun -> riksvalkrets),
  public/data.json (kommun-/länskoder, partifärger, länskarta med kust, kommungränser), nyckelpersoner.csv (roller 2022–26).

Sidor (public_allavalda/):
  index.html                 sök, Sverigekarta (län), nyckeltal, partiingång
  lan/<kod>/index.html       kommunkarta, regionfullmäktige, riksdagsledamöter från länet
  kommun/<slug>/index.html   kommunfullmäktige per parti med ersättare, riksdags- och regionledamöter som bor i kommunen
  parti/<p>/index.html       partiets alla valda per val och område
  person/<id>/index.html     en sida per mandat (val + kandidatnummer), med övriga uppdrag för samma person
  statistik/index.html       diagram: valda per parti, personvalda, personröster, var riksdagsledamöterna bor
  sok.json                   sökindex (namn, parti, val, område, länk)

    python3 build_allavalda.py [--out public_allavalda]
Endast standardbibliotek. Kör efter valda.py.
"""
import argparse, csv, gzip, json, os, re, statistics, unicodedata
from collections import defaultdict, Counter

PIDS = ['V', 'S', 'MP', 'C', 'L', 'KD', 'M', 'SD']
VT = {'RD': 'Riksdagen', 'RF': 'Regionfullmäktige', 'KF': 'Kommunfullmäktige'}
VTS = {'RD': 'riksdagen', 'RF': 'regionfullmäktige', 'KF': 'kommunfullmäktige'}

def slugify(name):
    s = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s)).strip('-') or 'x'
def fold(s): return slugify(s)
def esc(s): return str(s if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
def read_csv(path, delim=','):
    if not os.path.exists(path): return []
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt', encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f, delimiter=delim))
AGEGRP = [('18–29', 18, 29), ('30–44', 30, 44), ('45–64', 45, 64), ('65+', 65, 200)]
def agegrp(a):
    for lab, lo, hi in AGEGRP:
        if a is not None and lo <= a <= hi: return lab
    return None
def pct(n, d): return round(100*n/d, 1) if d else None
def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 1) if xs else None
def fmtn(n): return f'{int(n):,}'.replace(',', '\u00a0')
def num(x):
    try: return float(str(x).replace(',', '.'))
    except Exception: return None

CSS = """
:root{--bg:#f7f6f2;--card:#fff;--ink:#1b1a17;--ink2:#5b5950;--ink3:#8a877c;--line:#e4e1d8;--acc:#1f5f8b;--acc2:#174a6d;--pos:#2e7d5b;--neg:#b0313f;--shadow:0 1px 2px rgba(0,0,0,.04),0 10px 24px -16px rgba(0,0,0,.25)}
@media(prefers-color-scheme:dark){:root{--bg:#121311;--card:#1b1d1a;--ink:#ecebe6;--ink2:#a8a69b;--ink3:#7f7d74;--line:#2c2f2a;--acc:#6fb0e0;--acc2:#8cc3ea;--pos:#54c08d;--neg:#e27c88}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Georgia,"Times New Roman",serif}
.wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px} a{color:var(--acc2)} .sans{font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
header.top{padding:20px 0 10px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.brand{font:700 1.25rem system-ui;letter-spacing:-.01em;text-decoration:none;color:var(--ink)} .brand span{color:var(--acc)}
nav.main a{font:600 .82rem system-ui;color:var(--ink2);text-decoration:none;margin-left:14px} nav.main a:hover{color:var(--acc2)}
h1{font-size:2rem;margin:12px 0 6px;line-height:1.15} h2{font-size:1.3rem;margin:26px 0 8px} h3{font-size:1.05rem;margin:18px 0 6px;font-family:system-ui}
.lead{color:var(--ink2);margin:0 0 10px;max-width:70ch} .muted{color:var(--ink3)} .small{font-size:.85rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow);margin:12px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0} .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px} .kpi .v{font:700 1.6rem system-ui;line-height:1.1} .kpi .l{font:.78rem system-ui;color:var(--ink3);margin-top:3px}
.pf{display:inline-block;font:700 .72rem ui-monospace,monospace;color:#fff;border-radius:5px;padding:2px 7px;white-space:nowrap;vertical-align:middle}
table{width:100%;border-collapse:collapse;font:.9rem system-ui} th,td{padding:7px 8px;border-top:1px solid var(--line);text-align:left;vertical-align:top} th{color:var(--ink3);font-weight:600;font-size:.76rem;border-top:none;text-transform:uppercase;letter-spacing:.04em} td.r,th.r{text-align:right}
.search{width:100%;max-width:560px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:12px;padding:13px 16px;font:1.05rem system-ui} .search:focus{outline:none;border-color:var(--acc)}
.hits{margin:8px 0 0;padding:0;list-style:none;max-width:560px} .hits li{padding:8px 10px;border-bottom:1px solid var(--line)} .hits a{text-decoration:none;color:var(--ink);font-family:system-ui} .hits .m{color:var(--ink3);font-size:.82rem}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0} .chip{border:1.5px solid var(--line);background:var(--card);border-radius:999px;padding:6px 12px;font:.85rem system-ui;color:var(--ink);text-decoration:none} .chip:hover{border-color:var(--acc)}
svg.map{width:100%;height:auto;display:block;background:var(--card);border:1px solid var(--line);border-radius:14px} svg.map path{fill:#d8dde3;stroke:#fff;stroke-width:1.2;cursor:pointer;transition:fill .1s} @media(prefers-color-scheme:dark){svg.map path{fill:#2f3a44;stroke:#1b1d1a}} svg.map path:hover{fill:var(--acc)} svg.map text{font:600 11px system-ui;fill:var(--ink2);pointer-events:none}
.maprow{display:grid;grid-template-columns:minmax(220px,1fr) minmax(260px,1.4fr);gap:18px;align-items:start} @media(max-width:700px){.maprow{grid-template-columns:1fr}}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px} .grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
ol.led{margin:4px 0 10px;padding-left:24px;font-family:system-ui;font-size:.92rem} ol.led li{padding:2px 0} ol.led a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;color:var(--ink)} ol.led a:hover{color:var(--acc2)} .ers{color:var(--ink3);font-size:.82rem;margin-left:6px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:4px 0} .bar span{display:block;height:100%}
.bar.seat{height:26px;border-radius:6px;margin:10px 0 0} .bar.seat span{border-right:2px solid var(--bg)} .bar.seat span:last-child{border-right:none}
.seatlab{display:flex;font:600 .74rem/1.15 system-ui;color:var(--ink2);margin:3px 0 0} .seatlab span{display:block;text-align:center;overflow:visible;white-space:nowrap}
.seatchips{display:flex;flex-wrap:wrap;gap:6px 12px;margin:8px 0 12px;font:.84rem system-ui;color:var(--ink2)} .seatchip{white-space:nowrap}
.crumb{font:.8rem system-ui;color:var(--ink3);margin:8px 0 0} .crumb a{color:var(--ink3);text-decoration:none} .crumb a:hover{color:var(--acc2)}
footer{padding-top:24px;margin-top:28px;border-top:1px solid var(--line);color:var(--ink3);font:.8rem system-ui}
.pv{color:var(--acc2)} .zoom{font:.8rem system-ui;color:var(--ink3);margin:6px 0 0}
header.top{position:relative} nav.main{display:flex;gap:2px;flex-wrap:wrap} nav.main a{margin-left:0;padding:6px 10px;border-radius:8px} nav.main a.cur{background:var(--acc);color:#fff}
details.mnav{display:none;position:relative} details.mnav summary{list-style:none;cursor:pointer;font:600 .9rem system-ui;border:1.5px solid var(--line);border-radius:10px;padding:7px 12px;background:var(--card)} details.mnav summary::-webkit-details-marker{display:none}
details.mnav[open] summary{border-color:var(--acc)} details.mnav .mlist{position:absolute;right:0;top:44px;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);min-width:220px;padding:6px}
details.mnav .mlist a{display:block;padding:10px 12px;border-radius:8px;font:600 .95rem system-ui;color:var(--ink);text-decoration:none} details.mnav .mlist a:hover,details.mnav .mlist a.cur{background:var(--bg);color:var(--acc2)}
@media(max-width:760px){nav.main{display:none} details.mnav{display:block}}
.subnav{position:sticky;top:0;z-index:10;background:var(--bg);display:flex;gap:6px;overflow-x:auto;white-space:nowrap;padding:8px 0;margin:4px 0 6px;border-bottom:1px solid var(--line);scrollbar-width:none;-webkit-overflow-scrolling:touch} .subnav::-webkit-scrollbar{display:none}
.subnav a{flex:0 0 auto;border:1.5px solid var(--line);background:var(--card);border-radius:999px;padding:6px 12px;font:600 .82rem system-ui;color:var(--ink2);text-decoration:none} .subnav a:hover{border-color:var(--acc);color:var(--acc2)} .subnav a.cur{background:var(--acc);border-color:var(--acc);color:#fff}
h2,h3{scroll-margin-top:60px}
[data-tip]{cursor:pointer} #tip{position:fixed;z-index:30;pointer-events:none;background:var(--ink);color:var(--bg);font:600 .82rem/1.35 system-ui;padding:7px 10px;border-radius:8px;max-width:260px;box-shadow:var(--shadow);display:none;white-space:pre-line}
@media(max-width:640px){
 table.rt,table.rt thead,table.rt tbody,table.rt tr,table.rt td{display:block;width:100%} table.rt{overflow:visible} table.rt thead{display:none}
 table.rt tr{border-top:1px solid var(--line);padding:6px 0} table.rt td{border:none;padding:2px 0;text-align:left!important;display:flex;justify-content:space-between;gap:10px}
 table.rt td::before{content:attr(data-label);color:var(--ink3);font:600 .72rem system-ui;text-transform:uppercase;letter-spacing:.04em;flex:0 0 auto;max-width:55%}
 table.rt td:first-child{font-weight:700} table.rt td:first-child::before{content:none}
}
.totop{position:fixed;right:14px;bottom:14px;z-index:15;border:1px solid var(--line);background:var(--card);border-radius:999px;width:44px;height:44px;display:none;align-items:center;justify-content:center;font:700 1.1rem system-ui;color:var(--ink2);text-decoration:none;box-shadow:var(--shadow)} .totop.on{display:flex}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0} .cards a.card{display:block;text-decoration:none;color:var(--ink);margin:0} .cards a.card:hover{border-color:var(--acc)} .cards a.card b{font:700 1.02rem system-ui;display:block;margin-bottom:4px} .cards a.card span{font:.86rem system-ui;color:var(--ink2)}
details.omr{border-top:1px solid var(--line)} details.omr summary{cursor:pointer;padding:9px 0;font:600 .95rem system-ui;list-style:none} details.omr summary::-webkit-details-marker{display:none} details.omr summary::before{content:'▸ ';color:var(--ink3)} details.omr[open] summary::before{content:'▾ '}
.filter{width:100%;max-width:420px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;padding:10px 14px;font:1rem system-ui;margin:6px 0 10px}
@media(max-width:640px){.wrap{padding:0 12px 48px} h1{font-size:1.5rem} table{font-size:.84rem;display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%} th,td{padding:6px 5px} .card table{display:table} .card{padding:12px}}
"""

MENU = [('', 'Sök'), ('karta/', 'Karta'), ('lan/', 'Län'), ('kommun/', 'Kommuner'), ('parti/', 'Partier'), ('statistik/', 'Statistik')]
def subnav(items, cur=None):
    """items: [(href, label)] – fastnar överst när man skrollar, scrollbar i sidled på mobil."""
    return '<nav class="subnav" aria-label="På sidan">' + ''.join(f'<a href="{h}"{" class=\"cur\"" if h == cur else ""}>{esc(l)}</a>' for h, l in items) + '</nav>'
def auto_subnav(body, after='</div>', short=None):
    """Ger alla <h2> utan id ett id och lägger en undermeny efter första förekomsten av `after`."""
    items = []
    def sub(m):
        txt = re.sub(r'<[^>]+>', '', m.group(1)).strip(); hid = slugify(txt)[:40]
        items.append(('#' + hid, (short or {}).get(txt.split(' ')[0], txt if len(txt) <= 22 else txt[:20] + '…')))
        return f'<h2 id="{hid}">{m.group(1)}</h2>'
    body = re.sub(r'<h2>(.*?)</h2>', sub, body)
    if len(items) < 2: return body
    i = body.find(after)
    return body[:i + len(after)] + subnav([('#top', 'Fakta')] + items) + body[i + len(after):] if i >= 0 else subnav(items) + body
def page(title, body, depth=0, crumb='', built='', section=None):
    root = '../'*depth
    def ml(cls):
        return ''.join(f'<a href="{root}{h}"{" class=\"cur\"" if section == h else ""}>{l}</a>' for h, l in MENU) + '<a href="https://www.valutfall.se/">valutfall.se ↗</a>'
    return f"""<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} – allavalda.se</title><meta name="description" content="{esc(title)} – alla folkvalda i Sverige efter valet 2026: riksdag, regionfullmäktige och kommunfullmäktige."><link rel="stylesheet" href="{root}style.css"></head>
<body><div class="wrap"><header class="top"><a class="brand" href="{root}">alla<span>valda</span>.se</a><nav class="main" aria-label="Huvudmeny">{ml('main')}</nav><details class="mnav"><summary aria-label="Meny">☰ Meny</summary><div class="mlist">{ml('m')}</div></details></header>
{('<div class="crumb">'+crumb+'</div>') if crumb else ''}
{body}
<footer><p>Källa: Valmyndighetens fastställda resultat för valen den 13 september 2026 (valda ledamöter, ersättare, valgrund, personröster) och Valmyndighetens kandidatfil (folkbokföringskommun). Ålder, kön och titel: Valmyndighetens kandidatfil 2026. Historik: Valmyndighetens filer över ursprungligt valda 2010–2022 (namnen gallrade av Valmyndigheten före 2022). Ny/omvald: matchning på namn, parti och ålder mot de valda 2022, en uppskattning. Roller 2022–2026: Plenum. {('Byggd '+esc(built)+'. ') if built else ''}<b>allavalda.se</b> är gjord av <a href="https://influera.se">Influera Sverige</a>s Sandro Wennberg med hjälp av AI (Anthropic). Valresultatet: <a href="https://www.valutfall.se/">valutfall.se</a>.</p></footer></div>
<a href="#" class="totop" id="totop" aria-label="Till toppen">↑</a>
<div id="tip" role="tooltip"></div>
<script>(function(){{var tip=document.getElementById('tip'),cur=null;function show(el,x,y){{tip.textContent=el.getAttribute('data-tip');tip.style.display='block';var w=tip.offsetWidth,h=tip.offsetHeight;tip.style.left=Math.max(6,Math.min(innerWidth-w-6,x-w/2))+'px';tip.style.top=Math.max(6,y-h-12)+'px';cur=el}}function hide(){{tip.style.display='none';cur=null}}
document.addEventListener('mouseover',function(e){{var el=e.target.closest&&e.target.closest('[data-tip]');if(el)show(el,e.clientX,e.clientY);else if(cur)hide()}});
document.addEventListener('mousemove',function(e){{if(cur){{var w=tip.offsetWidth,h=tip.offsetHeight;tip.style.left=Math.max(6,Math.min(innerWidth-w-6,e.clientX-w/2))+'px';tip.style.top=Math.max(6,e.clientY-h-12)+'px'}}}});
document.addEventListener('click',function(e){{var el=e.target.closest&&e.target.closest('[data-tip]');if(!el){{if(cur)hide();return}}var r=el.getBoundingClientRect(),inLink=el.closest('a');if(inLink){{if(!matchMedia('(hover:none)').matches||cur===el)return;e.preventDefault();show(el,e.clientX||r.left+r.width/2,e.clientY||r.top);return}}if(cur===el)hide();else show(el,e.clientX||r.left+r.width/2,e.clientY||r.top)}});
addEventListener('scroll',function(){{if(cur)hide()}},{{passive:true}});
document.querySelectorAll('table').forEach(function(t){{if(t.closest('.card'))return;var th=[].map.call(t.querySelectorAll('thead th'),function(x){{return x.textContent.trim()}});if(!th.length)return;t.classList.add('rt');t.querySelectorAll('tbody tr').forEach(function(tr){{[].forEach.call(tr.children,function(td,i){{if(th[i])td.setAttribute('data-label',th[i])}})}})}});}})();</script>
<script>(function(){{var t=document.getElementById('totop');addEventListener('scroll',function(){{t.classList.toggle('on',scrollY>900)}},{{passive:true}});document.querySelectorAll('details.mnav .mlist a').forEach(function(a){{a.addEventListener('click',function(){{a.closest('details').open=false}})}});document.addEventListener('click',function(e){{var d=document.querySelector('details.mnav[open]');if(d&&!d.contains(e.target))d.open=false}});}})();</script>
__SCRIPT__</body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='public/data.json'); ap.add_argument('--out', default='public_allavalda')
    ap.add_argument('--valda', default='data/valda.csv'); ap.add_argument('--ersattare', default='data/ersattare.csv')
    ap.add_argument('--personroster', default='data/personroster.csv'); ap.add_argument('--kandidaturer', default='data/kandidaturer.csv')
    ap.add_argument('--valkrets', default='data/valkrets.csv'); ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    ap.add_argument('--kandidaturer-full', default='data/kandidaturer_2026_full.csv.gz', help='Valmyndighetens fullständiga kandidatfil (ålder, kön, valsedelsuppgift)')
    ap.add_argument('--historik', default='data/valda_historik.csv.gz', help='ursprungligt valda 2010–2022 (historik_valda.py)')
    ap.add_argument('--riksdagen', default='data/riksdagen_historik.json.gz', help='Riksdagens öppna ledamotsdata (riksdag_historik.py)')
    a = ap.parse_args()
    d = DATA = json.load(open(a.data, encoding='utf-8'))
    komKod = d['komKod']; kod2kom = {v: k for k, v in komKod.items()}; lanKod = d['lanKod']; lanNamn = {v: k for k, v in lanKod.items()}
    COL = {p['id']: p['color'] for p in d['parties']}; PN = {p['id']: p['namn'] for p in d['parties']}
    built = (d.get('meta') or {}).get('built', '')
    def col(p): return COL.get(p, '#7a8390')
    def pf(p): return f'<span class="pf" style="background:{col(p)}">{esc(p)}</span>'
    valda = read_csv(a.valda)
    # säkerhetsnät om valda.csv har dubbletter (samma mandat på valområdes- och valkretsnivå)
    _seen = {}
    for r in valda:
        k = (r['valtyp'], r['valomrkod'], r.get('kandidatnummer') or (r['parti'] + '|' + fold(r['namn'])))
        if k not in _seen or (r.get('valkretskod') not in ('', r['valomrkod']) and _seen[k].get('valkretskod') in ('', _seen[k]['valomrkod'])): _seen[k] = r
    valda = list(_seen.values())
    if not valda: raise SystemExit('data/valda.csv saknas – kör valda.py först (Deploya live, slutliga).')
    ers = read_csv(a.ersattare); pers = read_csv(a.personroster)
    ers = list({(e['valtyp'], e['valomrkod'], e.get('ledamot_kandidatnummer'), e.get('kandidatnummer') or e['namn']): e for e in ers}.values())
    pers = list({(r['valtyp'], r['valomrkod'], r.get('kandidatnummer')): r for r in pers}.values())
    kand = {}; lists = defaultdict(list); knr_lists = defaultdict(list)
    # Kandidatfilen har en rad per valsedel: samma kandidat kan stå på flera valsedlar (LISTNUMMER) för samma parti och valkrets.
    # "Hela listan" = den längsta valsedeln (partiets huvudlista) som innehåller personen; dubbletter tas bort.
    kfile = a.kandidaturer_full if os.path.exists(a.kandidaturer_full) else a.kandidaturer
    allkand = read_csv(kfile, ';')
    for r in allkand:
        if r.get('GILTIG', 'J') != 'J': continue
        if not (r.get('ORDNING') or '').strip(): continue
        kand.setdefault((r.get('VALTYP'), r.get('KANDIDATNUMMER')), r)
        lk_ = (r['VALTYP'], r['VALOMRÅDESKOD'], r.get('VALKRETSKOD') or '', r['PARTIBETECKNING'], (r.get('LISTNUMMER') or '').strip())
        lists[lk_].append(r)
    for k_, v in list(lists.items()):
        seen_ = set(); u = []
        for x in sorted(v, key=lambda x: int(num(x.get('ORDNING')) or 0)):
            if x['KANDIDATNUMMER'] in seen_: continue
            seen_.add(x['KANDIDATNUMMER']); u.append(x)
        lists[k_] = u
    for k_, v in sorted(lists.items(), key=lambda kv: -len(kv[1])):   # längsta valsedeln först
        for x in v:
            kl = knr_lists[(k_[0], k_[1], x['KANDIDATNUMMER'])]
            if k_ not in kl: kl.append(k_)
    vk2lan = {}; kom2vk = {}
    for r in read_csv(a.valkrets): kom2vk[r['kommunkod']] = r['valkretskod']; vk2lan.setdefault(r['valkretskod'], r['kommunkod'][:2])
    roles = defaultdict(list)
    for r in read_csv(a.nyckelpersoner):
        roles[(fold(r['namn']), r.get('parti_abbr'))].append(f"{r['organ']} ({r['roll']}), {r['omrade']}")

    # ---- normalisera ----
    for r in valda:
        r['vt'] = r['valtyp']; r['p'] = r['parti']; r['id'] = f"{r['vt']}-{r.get('kandidatnummer') or slugify(r['namn'])}"
        r['pr'] = num(r.get('personroster')); r['nr'] = int(num(r.get('invalsordning')) or 0)
        r['pr_tot'] = num(r.get('personroster_totalt')) or r['pr']   # summa över alla valkretsar där kandidaten stod
        r['pv'] = 'person' in (r.get('valgrund') or '').lower(); r['kval'] = r.get('kvalificerad') == 'Ja'
        k = kand.get((r['vt'], r.get('kandidatnummer'))) or {}
        r['fbk'] = (k.get('FOLKBOKFÖRINGSKOMMUN') or '').strip(); r['fbk_kod'] = komKod.get(r['fbk'], '')
        r['listplats'] = (k.get('ORDNING') or '').strip()
        if r['vt'] == 'KF': r['kom'] = r['valomrkod']; r['lan'] = r['valomrkod'][:2]
        elif r['vt'] == 'RF': r['kom'] = r['fbk_kod']; r['lan'] = r['valomrkod']
        else: r['kom'] = r['fbk_kod']; r['lan'] = vk2lan.get(r.get('valkretskod'), r['fbk_kod'][:2])
        r['omr'] = r.get('valkretsnamn') if r['vt'] == 'RD' else r.get('valomrnamn')
        r['slug'] = slugify(r['namn'])
    # ---- ålder, kön, titel ur kandidatfilen ----
    ortnamn = {fold(n) for n in komKod} | {fold(n.replace(' län', '')) for n in lanKod} | {fold(n) for n in lanKod}
    def titel(s):
        for part in [p.strip() for p in re.split(r'[,;]', s or '') if p.strip()]:
            if re.fullmatch(r'\d+\s*(år)?', part): continue
            if fold(part) in ortnamn or fold(part).endswith('centrum'): continue
            return part[:1].upper() + part[1:]
        return ''
    for r in valda:
        k = kand.get((r['vt'], r.get('kandidatnummer'))) or {}
        r['alder'] = int(num(k.get('ÅLDER_PÅ_VALDAGEN')) or 0) or None; r['kon'] = (k.get('KÖN') or '').strip()
        r['titel'] = titel(k.get('VALSEDELSUPPGIFT'))
        r['fullnamn'] = r['namn']; r['visn'] = (k.get('NAMN') or '').strip() or r['namn']
        # listplats ur den valsedel där personen står bäst i sin valkrets (partier kan ha flera valsedlar med olika ordning)
        pl = [int(num(c.get('ORDNING')) or 0) for lk_ in knr_lists.get((r['vt'], r['valomrkod'], r.get('kandidatnummer') or ''), [])
              if lk_[2] in ((r.get('valkretskod') or ''), '') or r['vt'] == 'KF' for c in lists.get(lk_, []) if c['KANDIDATNUMMER'] == r.get('kandidatnummer')]
        pl = [x for x in pl if x]
        if pl: r['listplats'] = str(min(pl))
        try: r['jump'] = int(r['listplats']) - r['nr'] if r['listplats'] and r['nr'] and r['pv'] else None
        except Exception: r['jump'] = None
    # ---- historik 2010–2022 ----
    hist = read_csv(a.historik)
    for h in hist: h['alder_i'] = int(num(h.get('alder')) or 0) or None
    by_name = defaultdict(list)
    for h in hist:
        if h['namn']: by_name[fold(h['namn'])].append(h)
    named_years = sorted({h['ar'] for h in hist if h['namn']})
    def area_of(h): return h['kommunkod'] if h['valtyp'] == 'KF' else (h['lankod'] if h['valtyp'] == 'RF' else 'RD')
    for r in valda:
        # alla tidigare uppdrag: samma namn och ålder som stämmer (± 1 år) för respektive valår; parti får skilja (partibyte visas)
        tl = []
        for h in {id(x): x for x in by_name.get(fold(r['fullnamn']), []) + by_name.get(fold(r['visn']), [])}.values():
            if r['alder'] is not None and h['alder_i'] is not None and abs(h['alder_i'] - (r['alder'] - (2026 - int(h['ar'])))) > 1: continue
            tl.append(h)
        tl.sort(key=lambda h: (h['ar'], h['valtyp']), reverse=True)
        r['tl'] = tl
        # mandatperioder i rad i samma församling (inklusive 2026)
        own = r['valomrkod'] if r['vt'] in ('KF', 'RF') else 'RD'
        streak = 1
        for y in ('2022', '2018', '2014', '2010'):
            if y not in named_years: break
            if any(h['ar'] == y and h['valtyp'] == r['vt'] and area_of(h) == own for h in tl): streak += 1
            else: break
        r['streak'] = streak; r['first'] = min([int(h['ar']) for h in tl if h['valtyp'] == r['vt'] and area_of(h) == own] + [2026])
        cands = [h for h in tl if h['ar'] == '2022' and h['parti'] == r['p']]
        same = [h for h in cands if h['valtyp'] == r['vt'] and ((r['vt'] == 'KF' and h['kommunkod'] == r['valomrkod']) or (r['vt'] == 'RF' and h['lankod'] == r['valomrkod']) or r['vt'] == 'RD')]
        r['h22'] = cands; r['h22same'] = same[0] if same else None
        r['status22'] = 'omvald' if same else ('annan församling 2022' if cands else 'ny')
    # ---- riksdagens öppna data: exakt riksdagshistorik ----
    rdh = []
    if os.path.exists(a.riksdagen):
        with gzip.open(a.riksdagen, 'rt', encoding='utf-8') as f: rdh = json.load(f)
    rd_by = defaultdict(list)
    for p in rdh: rd_by[fold(p['namn'])].append(p)
    PERIODS = [(1994, '1994-10-03', '1998-10-05'), (1998, '1998-10-05', '2002-09-30'), (2002, '2002-09-30', '2006-10-02'), (2006, '2006-10-02', '2010-10-04'),
               (2010, '2010-10-04', '2014-09-29'), (2014, '2014-09-29', '2018-09-24'), (2018, '2018-09-24', '2022-09-26'), (2022, '2022-09-26', '2026-09-28')]
    ORGAN_NAMN = {'FiU': 'finansutskottet', 'SkU': 'skatteutskottet', 'JuU': 'justitieutskottet', 'KU': 'konstitutionsutskottet', 'CU': 'civilutskottet', 'UU': 'utrikesutskottet',
                  'FöU': 'försvarsutskottet', 'SoU': 'socialutskottet', 'SfU': 'socialförsäkringsutskottet', 'KrU': 'kulturutskottet', 'UbU': 'utbildningsutskottet',
                  'TU': 'trafikutskottet', 'MJU': 'miljö- och jordbruksutskottet', 'NU': 'näringsutskottet', 'AU': 'arbetsmarknadsutskottet', 'EUN': 'EU-nämnden'}
    def rd_profile(p):
        led = [k for k in p['kammare'] if 'ledamot' in (k[2] or '').lower()]
        ers_ = [k for k in p['kammare'] if 'ersättare' in (k[2] or '').lower()]
        per = []
        for y, s, e in PERIODS:
            if any((k[0] or '0000') < e and ((k[1] or '9999') > s) for k in led): per.append(y)
        roles = {}
        for ok, nm, roll, fr, to in p['organ']:
            if ok not in ORGAN_NAMN or (roll or '').lower() in ('suppleant', 'extra suppleant'): continue
            key = (ok, roll)
            r0 = roles.get(key, [fr, to]); roles[key] = [min(r0[0], fr or r0[0]), max(r0[1] or '', to or '')]
        return {'id': p['id'], 'perioder': per, 'ersattare': bool(ers_) and not led, 'forst': min([k[0][:4] for k in led] or ['']),
                'roller': sorted([(ORGAN_NAMN[k[0]], k[1], v[0][:4], (v[1] or '')[:4]) for k, v in roles.items()], key=lambda x: x[2]),
                'kommunalt': (p['bio'].get('Kommunala uppdrag') or '')[:600]}
    for r in valda:
        r['rdp'] = None
        for p in rd_by.get(fold(r['visn']), []) + rd_by.get(fold(r['fullnamn']), []):
            if r['alder'] and p.get('fodd') and (2026 - p['fodd']) not in (r['alder'], r['alder'] + 1): continue
            prof = rd_profile(p)
            if prof['perioder'] or prof['ersattare']: r['rdp'] = prof; break
        if r['vt'] == 'RD' and r['rdp'] is not None:
            r['status22'] = 'omvald' if 2022 in r['rdp']['perioder'] else ('återkommer' if r['rdp']['perioder'] else r.get('status22'))
    for r in valda: r['namn'] = r['visn']        # visa namnet som på valsedeln; fullständigt namn finns i r['fullnamn']
    ers_by = defaultdict(list)
    for e in ers: ers_by[(e['valtyp'], e['valomrkod'], e['parti'])].append(e)
    valda_knr_by = defaultdict(set); ers_knr_by = defaultdict(set); knr_id_by = defaultdict(dict)
    for r in valda: valda_knr_by[(r['vt'], r['valomrkod'], r['p'])].add(r.get('kandidatnummer'))
    for x in ers: ers_knr_by[(x['valtyp'], x['valomrkod'], x['parti'])].add(x.get('kandidatnummer'))
    by_person = defaultdict(list)     # samma person i flera val: namn + parti
    for r in valda: by_person[(fold(r['namn']), r['p'])].append(r)

    out = a.out; os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'style.css'), 'w', encoding='utf-8') as f: f.write(CSS)
    seen_ids = Counter()
    for r in valda:
        seen_ids[r['id']] += 1
        if seen_ids[r['id']] > 1: r['id'] = f"{r['id']}-{seen_ids[r['id']]}"
    def write(path, html):
        os.makedirs(os.path.dirname(os.path.join(out, path)) or out, exist_ok=True)
        with open(os.path.join(out, path), 'w', encoding='utf-8') as f: f.write(html)

    # ---- hjälpare ----
    def person_link(r, depth): return f'{"../"*depth}person/{r["id"]}/'
    def led_item(r, depth, show_omr=False):
        extra = []
        if r['pv']: extra.append('<span class="pv" title="Invald på personröster">personvald</span>')
        if r.get('status22') == 'ny': extra.append('ny')
        if r.get('alder'): extra.append(f"{r['alder']} år")
        if r.get('pr_tot') is not None: extra.append(f"{fmtn(r['pr_tot'])} personröster")
        if show_omr: extra.append(esc(r['omr'] or ''))
        return f'<li><a href="{person_link(r, depth)}">{esc(r["namn"])}</a> <span class="ers">{" · ".join(extra)}</span></li>'
    def party_lists(rows, depth, with_ers=None, show_omr=False, pref='p-'):
        byp = defaultdict(list)
        for r in rows: byp[r['p']].append(r)
        order = sorted(byp, key=lambda p: (-len(byp[p]), p))
        html = ''
        for p in order:
            rs = sorted(byp[p], key=lambda r: (r['nr'] or 999, r['namn']))
            html += f'<h3 id="{pref}{slugify(p)}">{pf(p)} {esc(PN.get(p, rs[0].get("partibeteckning") or p))} <span class="muted small">{len(rs)} mandat</span></h3><ol class="led">{"".join(led_item(r, depth, show_omr) for r in rs)}</ol>'
            if with_ers:
                e = sorted(with_ers.get(p, []), key=lambda x: (int(num(x.get('ersattarordning')) or 0), x['namn']))
                names = []; seen = set()
                for x in e:
                    if x['namn'] not in seen: seen.add(x['namn']); names.append(x['namn'])
                if names: html += f'<p class="small muted" style="margin:-4px 0 8px;font-family:system-ui">Ersättare: {esc(", ".join(names[:12]))}{" …" if len(names) > 12 else ""}</p>'
        return html
    def seatbar(rows):
        """Mandatstapel: partibeteckning och antal direkt under respektive färg, plus färgade etiketter för smala partier."""
        c = Counter(r['p'] for r in rows); tot = sum(c.values()) or 1
        ps = [p for p in PIDS if c[p]] + sorted([p for p in c if p not in PIDS], key=lambda p: -c[p])
        seg = ''.join('<span data-tip="%s: %d mandat (%s %%)" style="width:%.3f%%;background:%s"></span>' % (esc(PN.get(p, p)), c[p], str(round(100*c[p]/tot, 1)).replace('.', ','), 100*c[p]/tot, col(p)) for p in ps)
        def lab(p):
            w = 100*c[p]/tot; short = p if len(p) <= 4 else p[:3] + '…'
            inner = f'<b style="color:{col(p)}">{esc(short)}</b><br>{c[p]}' if w >= 6 else (f'{c[p]}' if w >= 3 else '')
            return f'<span style="width:{w:.3f}%">{inner}</span>'
        under = ''.join(lab(p) for p in ps)
        chips = ' '.join(f'<span class="seatchip"><span class="pf" style="background:{col(p)}">{esc(p)}</span> {c[p]}</span>' for p in ps)
        return f'<div class="bar seat">{seg}</div><div class="seatlab">{under}</div><div class="seatchips">{chips}</div>'
    def hbars(rows, unit='', mx=None, w_lab=150):
        """rows: [(etikett_html, värde, färg)] -> liggande staplar"""
        rows = [x for x in rows if x[1] is not None]
        if not rows: return ''
        mx = mx or max(v for _, v, _ in rows) or 1
        return '<div class="sans" style="font-size:.86rem;margin:6px 0 12px">' + ''.join(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><div style="width:{w_lab}px;flex:0 0 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{lab}</div>'
            f'<div data-tip="{esc(re.sub("<[^>]+>", " ", lab).strip())}: {str(v).replace(".", ",")}{unit}" style="flex:1;background:var(--line);border-radius:5px;overflow:hidden;min-width:60px"><div style="width:{max(0, min(100, 100*v/mx)):.1f}%;height:15px;background:{c or "var(--acc)"}"></div></div>'
            f'<div style="width:62px;text-align:right">{str(v).replace(".", ",")}{unit}</div></div>' for lab, v, c in rows) + '</div>'
    def stacked(rows, keys, colors, labels):
        """rows: [(etikett_html, {key: andel})] -> staplade 100 %-staplar med förklaring"""
        leg = '<div class="sans small muted" style="display:flex;gap:12px;flex-wrap:wrap;margin:4px 0">' + ''.join(f'<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{colors[k]};margin-right:4px"></span>{labels[k]}</span>' for k in keys) + '</div>'
        return leg + '<div class="sans" style="font-size:.86rem;margin:4px 0 12px">' + ''.join(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><div style="width:110px;flex:0 0 auto">{lab}</div><div style="flex:1;display:flex;height:16px;border-radius:5px;overflow:hidden;background:var(--line)">' +
            ''.join(f'<div data-tip="{esc(re.sub("<[^>]+>", " ", lab).strip())} – {labels[k]}: {str(round(d.get(k, 0), 1)).replace(".", ",")} %" style="width:{d.get(k, 0):.1f}%;background:{colors[k]}"></div>' for k in keys) + '</div></div>' for lab, d in rows) + '</div>'
    def people_charts(rs):
        """kön + åldersgrupper för en grupp valda"""
        if not rs: return ''
        nk = sum(1 for r in rs if r['kon'] == 'K'); nm = sum(1 for r in rs if r['kon'] == 'M'); ag = Counter(agegrp(r['alder']) for r in rs if r['alder']); na = sum(ag.values()) or 1
        return ('<div class="grid2"><div><h3>Kön</h3>' + stacked([('Kvinnor/män', {'K': 100*nk/max(1, nk+nm), 'M': 100*nm/max(1, nk+nm)})], ['K', 'M'], {'K': '#e07b39', 'M': '#1f5f8b'}, {'K': f'kvinnor {nk} ({str(round(100*nk/max(1, nk+nm), 1)).replace(".", ",")} %)', 'M': f'män {nm} ({str(round(100*nm/max(1, nk+nm), 1)).replace(".", ",")} %)'}) +
                '</div><div><h3>Åldersgrupper</h3>' + hbars([(lab, round(100*ag[lab]/na, 1), '#2e7d5b') for lab, _, _ in AGEGRP], ' %', mx=100, w_lab=60) + '</div></div>')
    # ---- valutfall.se-underlag: styre 2022–26, folkmängd, valdeltagande, resultat, nyckelpolitiker ----
    styreK = {r['kommunkod']: r for r in read_csv('data/styre_kommun_2022.csv')}
    styreR = {r['lankod']: r for r in read_csv('data/styre_region_2022.csv')}
    folk = {r['kommunkod']: int(num(r['folkmangd']) or 0) for r in read_csv('data/folkmangd_2024.csv')}
    vdel = {(r['valtyp'], r['niva'], r['kod']): num(r['valdeltagande_pct']) for r in read_csv('data/valdeltagande_2026.csv')}
    mand = defaultdict(dict)
    for r in read_csv('data/mandat_slutligt.csv'): mand[(r['valtyp'], r['kod'])][r['parti_abbr']] = (int(r['mandat2022'] or 0), int(r['mandat2026'] or 0))
    nyck = read_csv(a.nyckelpersoner)
    valda_by_name = defaultdict(list)
    for r in valda:
        valda_by_name[(fold(r['namn']), r['p'])].append(r); valda_by_name[(fold(r['fullnamn']), r['p'])].append(r)
    def styre_box(parts_s, majmin, ledare_parti, vt, kod, label_led, ovrigt=None, link_valutfall=''):
        parts = [p.strip() for p in (parts_s or '').split(',') if p.strip()]
        if not parts: return ''
        m = mand.get((vt, kod), {}); tot26 = sum(v[1] for v in m.values()); tot22 = sum(v[0] for v in m.values())
        s26 = sum(m.get(p, (0, 0))[1] for p in parts if p in m); s22 = sum(m.get(p, (0, 0))[0] for p in parts if p in m)
        loc = 'ÖP' in parts or bool(ovrigt)
        maj = tot26 // 2 + 1 if tot26 else None
        if maj is None: status = ''
        elif s26 >= maj: status = f'<span class="pv">behåller majoriteten</span> ({s26} av {tot26})'
        elif loc: status = f'har {s26} av {tot26} mandat utan det lokala partiet – majoriteten beror på det'
        else: status = f'<span style="color:var(--neg)">saknar majoritet</span> ({s26} av {tot26}, {maj - s26} för lite)'
        return (f'<tr><th>Styre 2022–2026</th><td>{" ".join(pf(p) for p in parts)} <span class="small muted">{esc((majmin or "").lower())}{(", " + label_led + " från " + esc(ledare_parti)) if ledare_parti else ""}{(", ÖP = " + esc(ovrigt)) if ovrigt else ""}</span></td></tr>'
                + (f'<tr><th>Styrets partier efter valet</th><td>{status}. Hade {s22} av {tot22} mandat 2022.</td></tr>' if status else ''))
    def ledning_rows(niva, omrade_names):
        fold_names = {fold(x) for x in omrade_names if x}
        rows = [x for x in nyck if x['niva'] == niva and fold(x['omrade']) in fold_names and x['roll_kategori'] == 'ledning' and 'styrelse' in x['organ'].lower()]
        order = lambda x: (0 if x['roll'].lower().startswith('ordf') else 1 if 'förste' in x['roll'].lower() or '1:e' in x['roll'] else 2, x['namn'])
        out = []
        for x in sorted(rows, key=order)[:6]:
            hit = valda_by_name.get((fold(x['namn']), x['parti_abbr']))
            nm = f'<a href="../../person/{hit[0]["id"]}/">{esc(x["namn"])}</a>' if hit else esc(x['namn'])
            out.append(f'{nm} {pf(x["parti_abbr"])} <span class="small muted">{esc(x["roll"].lower())} 2022–2026{(" · omvald 2026 till " + VTS[hit[0]["vt"]]) if hit else ""}</span>')
        return ('<tr><th>Ledning 2022–2026</th><td>' + '<br>'.join(out) + '</td></tr>') if out else ''
    def res_bars(vt, area, kod):
        rs = (DATA.get('allresults', {}).get(area, {}).get(kod, {}) or {}).get(vt, [])
        rs = [x for x in rs if x.get('p') and x['p'] != 'Övriga' and (x.get('a') or 0) >= 1][:10]
        return hbars([(pf(x['p']) + ' ' + esc(PN.get(x['p'], x['p'])), round(x['a'], 1), col(x['p'])) for x in rs], ' %', w_lab=170) if rs else ''
    # ---- Faktadriven (Kolada/SCB via faktadriven) ----
    FK = {r['kod']: {k: num(v) for k, v in r.items() if k != 'kod'} for r in read_csv('data/kommun_fakta.csv')}
    FM = {r['kol']: r for r in read_csv('data/kommun_fakta_meta.csv')}
    def fv(kod, k): return (FK.get(kod) or {}).get(k)
    def fmt(v, unit=''):
        if v is None: return '–'
        if abs(v) >= 1000: s = fmtn(round(v))
        else: s = (str(round(v, 1)) if abs(v - round(v)) > 1e-9 else str(int(round(v)))).replace('.', ',')
        return s + ({'%': ' %', 'år': ' år', 'kr': ' kr'}.get(unit, ''))
    def rank(kod, k):
        vals = sorted([(v.get(k), c) for c, v in FK.items() if len(c) == 4 and not c.startswith('00') and v.get(k) is not None], reverse=True)
        for i, (_, c) in enumerate(vals):
            if c == kod: return i + 1, len(vals)
        return None, len(vals)
    def fakta_rows(kod, grupper, kommun=True):
        out = ''
        for g in grupper:
            rows = ''
            for k, m in FM.items():
                if m['grupp'] != g: continue
                v = fv(kod, k)
                if v is None: continue
                rk, n = rank(kod, k) if kommun else (None, 0)
                riket = fv('0000', k)
                pos = f'<span class="small muted"> · plats {rk} av {n}</span>' if rk else ''
                tip = f"{m['namn']} ({m['ar']}): {fmt(v, m['enhet'])}" + (f"\nRiket: {fmt(riket, m['enhet'])}" if riket is not None else '') + (f"\nPlats {rk} av {n} kommuner (högst = 1)" if rk else '') + f"\nKälla: Kolada {m['kolada']} via Faktadriven"
                rows += f'<tr data-tip="{esc(tip)}"><th>{esc(m["namn"])}</th><td><b>{fmt(v, m["enhet"])}</b>{(" <span class=\"small muted\">riket " + fmt(riket, m["enhet"]) + "</span>") if riket is not None else ""}{pos}</td></tr>'
            if rows: out += f'<h3>{esc(g)}</h3><div class="card"><table><tbody>{rows}</tbody></table></div>'
        return out
    def pearson(xs, ys):
        pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if len(pts) < 8: return None
        n = len(pts); mx = sum(p[0] for p in pts)/n; my = sum(p[1] for p in pts)/n
        sxx = sum((p[0]-mx)**2 for p in pts); syy = sum((p[1]-my)**2 for p in pts); sxy = sum((p[0]-mx)*(p[1]-my) for p in pts)
        return sxy / (sxx*syy)**0.5 if sxx and syy else None
    def rtext(r):
        if r is None: return 'för få kommuner'
        a = abs(r); s = 'inget' if a < .1 else 'svagt' if a < .3 else 'tydligt' if a < .5 else 'starkt'
        return f'r = {str(round(r, 2)).replace(".", ",")} – {s} {"positivt" if r > 0 else "negativt"} samband' if a >= .1 else f'r = {str(round(r, 2)).replace(".", ",")} – inget tydligt samband'
    def scatter(pts, xl, yl, xu='', yu='', depth=2):
        """pts: [(x, y, namn, slug)] – en prick per kommun, länkad och med tooltip, plus regressionslinje"""
        pts = [p for p in pts if p[0] is not None and p[1] is not None]
        if len(pts) < 8: return ''
        W, H, L, B = 620, 340, 54, 40
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys); px = (x1-x0)*.04 or 1; py = (y1-y0)*.06 or 1
        x0 -= px; x1 += px; y0 -= py; y1 += py
        sx = lambda v: L + (v-x0)/(x1-x0)*(W-L-12); sy = lambda v: 10 + (1-(v-y0)/(y1-y0))*(H-B-10)
        g = ''.join(f'<line x1="{L}" x2="{W-12}" y1="{sy(y0+(y1-y0)*i/4):.1f}" y2="{sy(y0+(y1-y0)*i/4):.1f}" stroke="currentColor" opacity=".12"/><text x="{L-6}" y="{sy(y0+(y1-y0)*i/4)+4:.1f}" font-size="10" text-anchor="end" fill="currentColor" opacity=".6">{fmt(y0+(y1-y0)*i/4)}</text>' for i in range(5))
        g += ''.join(f'<text x="{sx(x0+(x1-x0)*i/4):.1f}" y="{H-B+16}" font-size="10" text-anchor="middle" fill="currentColor" opacity=".6">{fmt(x0+(x1-x0)*i/4)}</text>' for i in range(5))
        n = len(pts); mx = sum(xs)/n; my = sum(ys)/n; sxx = sum((x-mx)**2 for x in xs)
        if sxx:
            k = sum((x-mx)*(y-my) for x, y in zip(xs, ys))/sxx; m0 = my - k*mx
            g += f'<line x1="{sx(x0):.1f}" y1="{sy(m0+k*x0):.1f}" x2="{sx(x1):.1f}" y2="{sy(m0+k*x1):.1f}" stroke="var(--neg)" stroke-width="2" opacity=".7"/>'
        dots = ''.join(f'<a href="{"../"*depth}kommun/{sl}/"><circle data-tip="{esc(nm)}&#10;{esc(xl)}: {fmt(x, xu)}&#10;{esc(yl)}: {fmt(y, yu)}" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="var(--acc)" fill-opacity=".5" stroke="var(--acc)" stroke-width=".6"/></a>' for x, y, nm, sl in pts)
        lab = f'<text x="{(L+W)/2:.0f}" y="{H-4}" font-size="11" text-anchor="middle" fill="currentColor">{esc(xl)}</text><text x="12" y="{(H-B)/2:.0f}" font-size="11" text-anchor="middle" fill="currentColor" transform="rotate(-90 12 {(H-B)/2:.0f})">{esc(yl)}</text>'
        return f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:720px;font-family:system-ui;display:block">{g}{dots}{lab}</svg><p class="small muted sans" style="margin:2px 0 14px">{rtext(pearson(xs, ys))} · {n} kommuner · varje prick är en kommun, hovra eller tryck för siffror.</p>'
    def rings_path(rings): return ''.join('M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in r) + 'Z' for r in rings)
    def bbox(polys):
        pts = [pt for rings in polys for r in rings for pt in r]
        return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)
    def svg_map(items, link, depth, label=True):
        """items: [(kod, namn, rings)] i data.json-koordinater; zoomar till urvalet."""
        if not items: return ''
        x0, y0, x1, y1 = bbox([it[2] for it in items]); pad = max(x1-x0, y1-y0)*0.03
        vb = f'{x0-pad:.0f} {y0-pad:.0f} {x1-x0+2*pad:.0f} {y1-y0+2*pad:.0f}'
        paths = ''.join(f'<a href="{link(kod)}"><path d="{rings_path(rings)}"><title>{esc(namn)}</title></path></a>' for kod, namn, rings in items)
        return f'<svg class="map" viewBox="{vb}" preserveAspectRatio="xMidYMid meet" role="img">{paths}</svg><p class="zoom">Klicka på kartan för att gå ner en nivå.</p>'

    # ---- index: sök + Sverigekarta + nyckeltal ----
    n = Counter(r['vt'] for r in valda); pv = sum(1 for r in valda if r['pv'])
    lan_items = [(k, lanNamn.get(k, k), rings) for k, rings in (d.get('granser', {}).get('lan') or {}).items()]
    lan_items.sort(key=lambda x: x[1])
    body = f"""<h1>Alla folkvalda i Sverige</h1><p class="lead">Varje ledamot som valdes den 13 september 2026 till riksdagen, de 20 regionfullmäktige och de 290 kommunfullmäktige. Sök på namn, eller gå via län, kommun eller parti.</p>
<input class="search" id="q" type="search" placeholder="Sök namn, kommun eller parti …" autocomplete="off"><ul class="hits" id="hits"></ul>
<div class="kpis"><div class="kpi"><div class="v">{fmtn(len(valda))}</div><div class="l">valda ledamöter</div></div><div class="kpi"><div class="v">{n['RD']}</div><div class="l">i riksdagen</div></div><div class="kpi"><div class="v">{fmtn(n['RF'])}</div><div class="l">i regionfullmäktige</div></div><div class="kpi"><div class="v">{fmtn(n['KF'])}</div><div class="l">i kommunfullmäktige</div></div><div class="kpi"><div class="v">{round(100*pv/len(valda))} %</div><div class="l">invalda på personröster</div></div></div>
<div class="maprow"><div>{svg_map(lan_items, lambda k: f'lan/{k}/', 0)}</div><div><h2 style="margin-top:0">Län</h2><div class="chips">{''.join(f'<a class="chip" href="lan/{k}/">{esc(nm)}</a>' for k, nm, _ in lan_items)}</div><h2>Partier</h2><div class="chips">{''.join(f'<a class="chip" href="parti/{slugify(p)}/">{pf(p)} {esc(PN.get(p, p))}</a>' for p in PIDS)} <a class="chip" href="parti/">Alla partier, även lokala →</a></div><h2>Statistik</h2><p class="lead"><a href="statistik/">Diagram över de valda</a>: partier, personröster, var riksdagsledamöterna bor.</p></div></div>"""
    script = """<script>
let IDX=null;const q=document.getElementById('q'),hits=document.getElementById('hits');const fold=s=>s.normalize('NFKD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
async function load(){if(IDX)return IDX;IDX=await (await fetch('sok.json')).json();return IDX;}
q.addEventListener('input',async()=>{const v=fold(q.value.trim());if(v.length<2){hits.innerHTML='';return;}const I=await load();const ws=v.split(/[^a-z0-9]+/).filter(Boolean);const r=I.filter(x=>ws.every(w=>x.f.includes(w))).sort((a,b)=>((a.p==='Kommun'&&fold(a.n).startsWith(ws[0]))?-1:fold(a.n).startsWith(ws[0])?0:1)-((b.p==='Kommun'&&fold(b.n).startsWith(ws[0]))?-1:fold(b.n).startsWith(ws[0])?0:1)).slice(0,40);
 hits.innerHTML=r.map(x=>`<li><a href="${x.u}">${x.n}</a> <span class="m">${x.p} · ${x.v} · ${x.o}</span></li>`).join('')||'<li class="m">Inga träffar.</li>';});
</script>"""
    body = body.replace('<h2>Statistik</h2><p class="lead"><a href="statistik/">Diagram över de valda</a>: partier, personröster, var riksdagsledamöterna bor.</p>', '')
    body += f'''<h2>Utforska</h2><div class="cards"><a class="card" href="karta/"><b>Karta →</b><span>Kommunfullmäktige på kartan: kvinnor, ålder, nya och personvalda.</span></a><a class="card" href="lan/"><b>Län och regioner →</b><span>Karta, regionfullmäktige och riksdagsledamöter per län.</span></a><a class="card" href="kommun/"><b>Alla 290 kommuner →</b><span>Kommunfullmäktige med ersättare, styre, invånare och historik sedan 2010.</span></a><a class="card" href="parti/"><b>Partier →</b><span>Alla valda per parti i riksdag, region och kommun.</span></a><a class="card" href="statistik/"><b>Statistik →</b><span>Kön, ålder, yrken, förnyelse, personval och riksdagserfarenhet.</span></a></div>'''
    rdm = mand.get(('RD', '00'), {})
    if rdm:
        rv = sum(v for (vt, nv, k), v in [] ) if False else None
        rd_r = sum(num(r['roster']) or 0 for r in read_csv('data/valdeltagande_2026.csv') if r['valtyp'] == 'RD' and r['niva'] == 'kommun')
        rd_b = sum(num(r['rostberattigade']) or 0 for r in read_csv('data/valdeltagande_2026.csv') if r['valtyp'] == 'RD' and r['niva'] == 'kommun')
        body += ('<h2>Riksdagen 2026–2030</h2>' + hbars([(pf(p_) + ' ' + esc(PN.get(p_, p_)) + f' <span class="small muted">({"+" if v[1]-v[0] > 0 else ""}{v[1]-v[0]})</span>', v[1], col(p_)) for p_, v in sorted(rdm.items(), key=lambda x: -x[1][1]) if v[1]], ' mandat', w_lab=220) +
                 f'<p class="small muted sans">Mandat enligt Valmyndighetens fastställda fördelning, förändring mot 2022 inom parentes.{(" Valdeltagande i riksdagsvalet: " + str(round(100*rd_r/rd_b, 2)).replace(".", ",") + " %.") if rd_b else ""} Regeringsbildning och koalitioner: <a href="https://www.valutfall.se/partianalys.html#regering">valutfall.se ↗</a></p>')
    write('index.html', page('Alla folkvalda i Sverige', body, 0, '', built, section='').replace('__SCRIPT__', script))
    # sökindex
    idx = [{'n': r['namn'], 'p': r['p'], 'v': VT[r['vt']], 'o': r['omr'] or '', 'u': f'person/{r["id"]}/', 'f': ' '.join(sorted(set(fold(r['namn'] + ' ' + r['fullnamn'] + ' ' + (r['omr'] or '') + ' ' + r['p'] + ' ' + (r['fbk'] or '')).split('-'))))} for r in valda]
    for kk, nm in sorted(kod2kom.items(), key=lambda x: x[1]): idx.append({'n': nm, 'p': 'Kommun', 'v': 'Kommunfullmäktige', 'o': lanNamn.get(kk[:2], ''), 'u': f'kommun/{slugify(nm)}/', 'f': fold('kommun ' + nm)})
    with open(os.path.join(out, 'sok.json'), 'w', encoding='utf-8') as f: json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))

    # ---- län ----
    kom_rings = d.get('granser', {}).get('kommun') or {}
    for lk, lname in sorted(lanNamn.items()):
        rf = [r for r in valda if r['vt'] == 'RF' and r['valomrkod'] == lk]
        rd = [r for r in valda if r['vt'] == 'RD' and r['lan'] == lk]
        koms = sorted([(kk, nm) for nm, kk in komKod.items() if kk[:2] == lk], key=lambda x: x[1])
        items = [(kk, nm, kom_rings[kk]) for kk, nm in koms if kk in kom_rings]
        sr = styreR.get(lk, {})
        rname = sr.get('region') or ('Region Gotland' if lk == '09' else ('Västra Götalandsregionen' if lk == '14' else 'Region ' + lname.replace(' län', '').replace('s län', '')))
        inv = sum(folk.get(kk, 0) for kk, _ in koms)
        om = ('<div class="card"><table><tbody>' + (f'<tr><th>Invånare</th><td>{fmtn(inv)} <span class="small muted">(SCB 2024)</span></td></tr>' if inv else '') +
              (f'<tr><th>Valdeltagande</th><td>regionvalet {str(vdel.get(("RF", "region", lk))).replace(".", ",")} % · riksdagsvalet {str(vdel.get(("RD", "län", lk))).replace(".", ",")} %</td></tr>' if vdel.get(('RF', 'region', lk)) else '') +
              styre_box(sr.get('partier'), sr.get('majmin'), sr.get('rso_parti'), 'RF', lk, 'regionstyrelsens ordförande', sr.get('ovrigt_parti')) +
              ledning_rows('region', [rname, sr.get('region'), rname.replace('Södermanland', 'Sörmland')]) +
              f'<tr><th>Mer</th><td><a href="https://www.valutfall.se/partianalys.html#regioner">Majoritetspusslet i regionerna – valutfall.se ↗</a></td></tr></tbody></table></div>')
        rres = res_bars('RF', 'region', lk)
        lfakta = (f'<h3>Fakta om länet</h3><p class="small muted sans">Kolada och SCB via Faktadriven, jämfört med riket.</p>' + fakta_rows('00' + lk, ['Befolkning', 'Ekonomi och arbete', 'Demokrati'], kommun=False)) if FK.get('00' + lk) else ''
        sn = subnav([('#om', 'Om regionen'), ('#kommuner', 'Kommuner'), ('#riksdag', 'Riksdagsledamöter'), ('#region', esc(rname))] + [('#rf-' + slugify(p), p) for p in sorted(set(r['p'] for r in rf), key=lambda p: -sum(1 for r in rf if r['p'] == p))[:8]])
        body = f"""<h1>{esc(lname)}</h1><p class="lead">{len(rd)} riksdagsledamöter från länet, {len(rf)} ledamöter i {esc(rname)} och {len(koms)} kommuner.</p>{sn}<h2 id="om">Om {esc(rname)}</h2>{om}{('<h3>Regionvalet 2026</h3>' + rres) if rres else ''}{lfakta}
<div class="maprow"><div>{svg_map(items, lambda k: f'../../kommun/{slugify(kod2kom.get(k, k))}/', 2)}</div><div><h2 style="margin-top:0" id="kommuner">Kommuner</h2><div class="chips">{''.join(f'<a class="chip" href="../../kommun/{slugify(nm)}/">{esc(nm)}</a>' for kk, nm in koms)}</div></div></div>
<h2 id="riksdag">Riksdagsledamöter från {esc(lname)}</h2>{seatbar(rd) if rd else ''}{party_lists(rd, 2, show_omr=True) if rd else '<p class="muted">Inga.</p>'}
{('<h2 id="region">'+esc(rname)+'</h2>'+seatbar(rf)+people_charts(rf)+party_lists(rf, 2, pref='rf-', with_ers= {p: [e for e in ers if e["valtyp"]=="RF" and e["valomrkod"]==lk and e["parti"]==p] for p in set(r["p"] for r in rf)})) if rf else ('<h2>Regionfullmäktige</h2><p class="muted">Gotland har inget regionval; regionfullmäktige är kommunfullmäktige.</p>' if lk=='09' else '')}"""
        write(f'lan/{lk}/index.html', page(lname, body, 2, f'<a href="../../">Sverige</a> › <a href="../">Län</a> › {esc(lname)}', built, section='lan/').replace('__SCRIPT__', ''))

    # ---- kommuner ----
    for nm, kk in sorted(komKod.items(), key=lambda x: x[1]):
        kf = [r for r in valda if r['vt'] == 'KF' and r['valomrkod'] == kk]
        rf = [r for r in valda if r['vt'] == 'RF' and r['kom'] == kk]
        rd = [r for r in valda if r['vt'] == 'RD' and r['kom'] == kk]
        slug = slugify(nm); lk = kk[:2]
        hk = [h for h in hist if h['valtyp'] == 'KF' and h['kommunkod'] == kk and h['ursprunglig'] == '1']
        hrows = []
        for ar in ('2010', '2014', '2018', '2022'):
            hs = [h for h in hk if h['ar'] == ar]
            if hs: hrows.append((ar, len(hs), pct(sum(1 for h in hs if h['kon'] == 'K'), len(hs)), mean([h['alder_i'] for h in hs]), pct(sum(1 for h in hs if h['personvald'] == '1'), len(hs))))
        if kf: hrows.append(('2026', len(kf), pct(sum(1 for r in kf if r['kon'] == 'K'), sum(1 for r in kf if r['kon'])), mean([r['alder'] for r in kf]), pct(sum(1 for r in kf if r['pv']), len(kf))))
        avg22 = sum(1 for h in hk if h['ar'] == '2022' and h.get('avgang'))
        vet = sorted([r for r in kf if r.get('streak', 1) > 1], key=lambda r: (-r['streak'], r['namn']))[:15]
        nya = sum(1 for r in kf if r.get('status22') == 'ny')
        histhtml = ('<h2 id="historik">Fullmäktige över tid</h2><table><thead><tr><th>Val</th><th class="r">Ledamöter</th><th class="r">Kvinnor %</th><th class="r">Medelålder</th><th class="r">Personvalda %</th></tr></thead><tbody>' +
                    ''.join(f'<tr><td>{ar}</td><td class="r">{n}</td><td class="r">{str(k).replace(".", ",") if k is not None else "–"}</td><td class="r">{str(m).replace(".", ",") if m is not None else "–"}</td><td class="r">{str(p).replace(".", ",") if p is not None else "–"}</td></tr>' for ar, n, k, m, p in hrows) +
                    f'</tbody></table><p class="small muted sans">{nya} av {len(kf)} ledamöter 2026 är nya jämfört med fullmäktige 2022 (uppskattning). {avg22} av ledamöterna som valdes 2022 lämnade sitt uppdrag under mandatperioden.</p>') if hrows else ''
        sk = styreK.get(kk, {})
        om = ('<div class="card"><table><tbody>' + (f'<tr><th>Invånare</th><td>{fmtn(folk[kk])} <span class="small muted">(SCB 2024)</span></td></tr>' if folk.get(kk) else '') +
              f'<tr><th>Län</th><td><a href="../../lan/{lk}/">{esc(lanNamn.get(lk, lk))}</a></td></tr>' +
              (f'<tr><th>Valdeltagande</th><td>kommunvalet {str(vdel.get(("KF", "kommun", kk))).replace(".", ",")} % · riksdagsvalet {str(vdel.get(("RD", "kommun", kk))).replace(".", ",")} %</td></tr>' if vdel.get(('KF', 'kommun', kk)) else '') +
              styre_box(sk.get('partier'), sk.get('majmin'), sk.get('kso_parti'), 'KF', kk, 'kommunstyrelsens ordförande') +
              ledning_rows('kommun', [nm]) +
              f'<tr><th>Mer</th><td><a href="https://www.valutfall.se/kommun/{slug}/">Valresultatet ner på valdistrikt ↗</a> · <a href="https://www.valutfall.se/partianalys.html#kommuner&k={kk}">Majoritetspusslet ↗</a></td></tr></tbody></table></div>')
        kres = res_bars('KF', 'kommun', kk)
        # spegling: fullmäktige mot befolkningen
        sp = ''
        if kf:
            ma_kf = mean([r['alder'] for r in kf]); kv26 = pct(sum(1 for r in kf if r['kon'] == 'K'), sum(1 for r in kf if r['kon']))
            rows_sp = [('Medelålder', fmt(fv(kk, 'ma'), 'år') + ' i hela befolkningen (inklusive barn)', fmt(ma_kf, 'år') + ' i fullmäktige 2026'),
                       ('Kvinnor i fullmäktige', '2022–2026: ' + fmt(fv(kk, 'kkf'), '%'), f'2026: {fmt(kv26, "%")}'),
                       ('Utrikes födda', fmt(fv(kk, 'uf'), '%') + ' av befolkningen', fmt(fv(kk, 'ufkf'), '%') + ' i fullmäktige 2022–26')]
            sp = ('<h3>Speglar fullmäktige kommunen?</h3><div class="card"><table><tbody>' + ''.join(f'<tr><th>{a_}</th><td>{b_}<br><b>{c_}</b></td></tr>' for a_, b_, c_ in rows_sp) +
                  '</tbody></table><p class="small muted sans">Befolkning och fullmäktige 2022–26: Kolada via Faktadriven. Fullmäktige 2026: Valmyndighetens kandidatfil. Utrikes födda bland de valda 2026 finns inte i öppna data.</p></div>')
        # mandatperioden 2022–2026
        mp = []
        if fv(kk, 'al') is not None and fv(kk, 'al22') is not None: mp.append(('Arbetslöshet', f"{fmt(fv(kk, 'al22'), '%')} (2022) → {fmt(fv(kk, 'al'), '%')} (2024)", fv(kk, 'al') - fv(kk, 'al22'), ' procentenheter'))
        if fv(kk, 'p22') and fv(kk, 'p24'): mp.append(('Folkmängd', f"{fmtn(fv(kk, 'p22'))} → {fmtn(fv(kk, 'p24'))}", 100*(fv(kk, 'p24')/fv(kk, 'p22')-1), ' %'))
        if fv(kk, 'br') and fv(kk, 'br22'): mp.append(('Anmälda brott per 100 000 inv', f"{fmtn(fv(kk, 'br22'))} (2022) → {fmtn(fv(kk, 'br'))} (2025)", 100*(fv(kk, 'br')/fv(kk, 'br22')-1), ' %'))
        if fv(kk, 'res3') is not None: mp.append(('Kommunens resultat, snitt 2023–2025', f"{fmt(fv(kk, 'res3'), '%')} av skatter och generella statsbidrag", None, ''))
        mph = ('<h3>Under mandatperioden 2022–2026</h3><div class="card"><table><tbody>' + ''.join(f'<tr><th>{a_}</th><td>{b_}{(" <b>" + ("+" if d_ > 0 else "") + str(round(d_, 1)).replace(".", ",") + u_ + "</b>") if d_ is not None else ""}</td></tr>' for a_, b_, d_, u_ in mp) + '</tbody></table></div>') if mp else ''
        fakta = (f'<h2 id="fakta">Fakta om {esc(nm)}</h2><p class="small muted sans">Senaste värden från Kolada och SCB via Faktadriven, jämfört med riket och rangordnade bland 290 kommuner (plats 1 = högst värde). Hovra eller tryck på en rad för år och källa.</p>'
                 + sp + mph + fakta_rows(kk, ['Befolkning', 'Ekonomi och arbete', 'Kommunens ekonomi', 'Skola och trygghet', 'Demokrati']))
        # fullmäktige över tid som diagram
        if hrows:
            yrs = [x[0] for x in hrows]
            histhtml = ('<h2 id="historik">Fullmäktige över tid</h2><div class="grid2"><div><h3>Andel kvinnor, %</h3>' + hbars([(y, k, '#e07b39') for y, _, k, _, _ in hrows], ' %', mx=100, w_lab=50) +
                        '</div><div><h3>Medelålder</h3>' + hbars([(y, m, '#1f5f8b') for y, _, _, m, _ in hrows], ' år', mx=80, w_lab=50) + '</div></div><h3>Andel invalda på personröster, %</h3>' +
                        hbars([(y, p_, '#2e7d5b') for y, _, _, _, p_ in hrows], ' %', mx=max([x[4] or 0 for x in hrows] + [1]), w_lab=50) +
                        f'<p class="small muted sans">2010–2022: ursprungligt valda enligt Valmyndigheten. {nya} av {len(kf)} ledamöter 2026 är nya jämfört med fullmäktige 2022 (uppskattning). {avg22} av ledamöterna som valdes 2022 lämnade sitt uppdrag under mandatperioden.</p>')
        kps = sorted(set(r['p'] for r in kf), key=lambda p: -sum(1 for r in kf if r['p'] == p))
        sn = subnav([('#om', 'Om kommunen'), ('#fakta', 'Fakta'), ('#kf', 'Fullmäktige')] + [('#p-' + slugify(p), p) for p in kps] + ([('#historik', 'Över tid')] if hrows else [])  + ([('#rd', 'Riksdag')] if rd else []) + ([('#rf', 'Region')] if rf else []))
        body = f"""<h1>{esc(nm)}</h1>{sn}<p class="lead">{len(kf)} ledamöter i kommunfullmäktige, {sum(1 for r in kf if r['pv'])} av dem invalda på personröster. {len(rd)} riksdagsledamöter och {len(rf)} regionledamöter bor i kommunen.</p>
<h2 id="om">Om {esc(nm)}</h2>{om}{('<h3>Kommunvalet 2026</h3>' + kres) if kres else ''}
{fakta}
<h2 id="kf">Kommunfullmäktige 2026–2030</h2>{seatbar(kf) if kf else ''}{people_charts(kf)}{party_lists(kf, 2, {p: ers_by.get(('KF', kk, p), []) for p in set(r['p'] for r in kf)}) if kf else '<p class="muted">Inga valda i underlaget.</p>'}
{histhtml}
{('<h2 id="rd">Riksdagsledamöter som bor i '+esc(nm)+'</h2>'+party_lists(rd, 2, show_omr=True, pref='rd-')) if rd else ''}
{('<h2 id="rf">Regionledamöter som bor i '+esc(nm)+'</h2>'+party_lists(rf, 2, pref='rf-')) if rf else ''}"""
        write(f'kommun/{slug}/index.html', page(nm, body, 2, f'<a href="../../">Sverige</a> › <a href="../../lan/{lk}/">{esc(lanNamn.get(lk, lk))}</a> › {esc(nm)}', built, section='kommun/').replace('__SCRIPT__', ''))

    # ---- partier ----
    all_p = Counter(r['p'] for r in valda)
    body = f"""<h1>Partier</h1><p class="lead">Alla partier med minst ett mandat i något av de tre valen.</p><table><thead><tr><th>Parti</th><th class="r">Riksdag</th><th class="r">Region</th><th class="r">Kommun</th><th class="r">Totalt</th></tr></thead><tbody>{''.join(f'<tr><td><a href="{slugify(p)}/">{pf(p)} {esc(PN.get(p, p))}</a></td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="RD")}</td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="RF")}</td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="KF")}</td><td class="r">{c}</td></tr>' for p, c in all_p.most_common())}</tbody></table>"""
    write('parti/index.html', page('Partier', body, 1, '<a href="../">Sverige</a> › Partier', built, section='parti/').replace('__SCRIPT__', ''))
    for p, c in all_p.most_common():
        rows = [r for r in valda if r['p'] == p]; pvp = sum(1 for r in rows if r['pv'])
        sec = ''
        for vt in ('RD', 'RF', 'KF'):
            rs = [r for r in rows if r['vt'] == vt]
            if not rs: continue
            byo = defaultdict(list)
            for r in rs: byo[r['omr'] or ''].append(r)
            sec += f'<h2 id="{vt.lower()}">{VT[vt]} <span class="muted small">{len(rs)} mandat</span></h2>' + ('<input class="filter" type="search" placeholder="Filtrera område eller namn…" oninput="var v=this.value.toLowerCase();this.parentNode.querySelectorAll(\'details.omr[data-vt={vt}]\').forEach(function(d){{var m=!v||d.textContent.toLowerCase().indexOf(v)>=0;d.style.display=m?\'\':\'none\';if(v&&m)d.open=true}})">' if len(byo) > 12 else '') + ''.join(f'<details class="omr" data-vt="{vt}"{" open" if len(byo) <= 3 else ""}><summary>{esc(o)} <span class="muted small">{len(byo[o])}</span></summary><ol class="led">{"".join(led_item(r, 2) for r in sorted(byo[o], key=lambda r: (r["nr"] or 999, r["namn"])))}</ol></details>' for o in sorted(byo))
        sn = subnav([('#' + vt.lower(), f"{VT[vt]} ({sum(1 for r in rows if r['vt'] == vt)})") for vt in ('RD', 'RF', 'KF') if any(r['vt'] == vt for r in rows)] + [('../', 'Alla partier')])
        pm = mand.get(('RD', '00'), {}).get(p)
        pint = (f'<div class="card"><table><tbody><tr><th>Riksdagsmandat</th><td>{pm[1]} <span class="small muted">(2022: {pm[0]}, {"+" if pm[1]-pm[0] > 0 else ""}{pm[1]-pm[0]})</span></td></tr></tbody></table></div>' if pm else '')
        body = f'<h1>{pf(p)} {esc(PN.get(p, rows[0].get("partibeteckning") or p))}</h1><p class="lead">{fmtn(c)} valda ledamöter, {pvp} ({round(100*pvp/c)} %) på personröster. Tryck på ett område för att visa de valda.</p>{sn}{pint}{people_charts(rows)}{sec}'
        write(f'parti/{slugify(p)}/index.html', page(PN.get(p, p), body, 2, f'<a href="../../">Sverige</a> › <a href="../">Partier</a> › {esc(PN.get(p, p))}', built, section='parti/').replace('__SCRIPT__', ''))

    for r in valda: knr_id_by[(r['vt'], r['valomrkod'])][r.get('kandidatnummer')] = r['id']
    # ---- personer ----
    for r in valda:
        others = [x for x in by_person[(fold(r['namn']), r['p'])] if x is not r]
        rl = roles.get((fold(r['namn']), r['p']), [])
        e = [x for x in ers_by.get((r['vt'], r['valomrkod'], r['p']), []) if x.get('ledamot') == r['namn']]
        # hela partilistan där personen stod (valkretsen där hen blev vald om det finns flera)
        cand_keys = knr_lists.get((r['vt'], r['valomrkod'], r.get('kandidatnummer') or ''), [])
        lkey = next((k for k in cand_keys if k[2] == (r.get('valkretskod') or '')), cand_keys[0] if cand_keys else None)
        full = lists.get(lkey, []) if lkey else []
        valda_knr = valda_knr_by.get((r['vt'], r['valomrkod'], r['p']), set())
        knr2id = knr_id_by.get((r['vt'], r['valomrkod']), {})
        ers_knr = {x.get('kandidatnummer') for x in e}
        ers_any = ers_knr_by.get((r['vt'], r['valomrkod'], r['p']), set())
        geo_url = f"../../kommun/{slugify(r['valomrnamn'])}/" if r['vt'] == 'KF' else (f"../../lan/{r['lan']}/" if r.get('lan') else '')
        geo_a = (lambda t: f'<a href="{geo_url}">{t}</a>' if geo_url else t)
        party_a = f'<a href="../../parti/{slugify(r["p"])}/">{esc(PN.get(r["p"], r.get("partibeteckning") or r["p"]))}</a>'
        if r['fullnamn'] != r['namn']: pass
        fakta = [('Vald till', geo_a(f"{VT[r['vt']]}{(' – ' + esc(r['omr'])) if r['omr'] else ''}")), ('Parti', f"{pf(r['p'])} {party_a}"),
                 ('Invald som nummer', f"{r['nr']} för partiet" + (f" (listplats {esc(r['listplats'])})" if r['listplats'] else '')), ('Valgrund', esc(r.get('valgrund') or '–'))]
        if r['pr'] is not None:
            in_vk = f" i {esc(r['omr'])}" if (r['vt'] == 'RD' or (r['pr_tot'] or 0) > (r['pr'] or 0)) and r['omr'] else ''
            fakta.append(('Personröster', fmtn(r['pr']) + in_vk + (f" ({str(r.get('andel_personroster')).replace('.', ',')} % av partiets röster där{', klarade personröstspärren' if r['kval'] else ''})" if r.get('andel_personroster') else '')))
            if r['pr_tot'] and r['pr_tot'] > r['pr']:
                fakta.append(('Personröster totalt', fmtn(r['pr_tot']) + ' (summa i alla valkretsar där personen stod på listan)'))
        if r['alder']: fakta.insert(1, ('Ålder', f"{r['alder']} år på valdagen" + (f", {'kvinna' if r['kon']=='K' else 'man' if r['kon']=='M' else ''}" if r['kon'] else '')))
        if r['titel']: fakta.insert(2, ('På valsedeln', esc(r['titel'])))
        if r['jump'] and r['jump'] > 0: fakta.append(('Personvalets effekt', f"Stod på listplats {r['listplats']} men blev mandat nr {r['nr']} – {r['jump']} platser upp"))
        elif r['jump'] and r['jump'] < 0: fakta.append(('Personvalets effekt', f"Stod på listplats {r['listplats']}, blev mandat nr {r['nr']} – andra med personröster gick före"))
        h = r.get('h22same')
        if h:
            t = f"Omvald. Satt i {VTS[h['valtyp']]} 2022–2026 (invald som nr {esc(h['invalsordning'])}{', personvald' if h['personvald']=='1' else ''})"
            if h.get('avgang'): t += f", avgick {esc(h['avgang'])}"
            fakta.append(('Mandatperioden innan', t))
        elif r['h22']:
            x = r['h22'][0]; fakta.append(('Mandatperioden innan', f"Satt 2022–2026 i {VTS[x['valtyp']]}{(' – ' + esc(kod2kom.get(x['kommunkod'], ''))) if x['valtyp']=='KF' else ''}, nu vald till {VTS[r['vt']]}"))
        else: fakta.append(('Mandatperioden innan', 'Ny – fanns inte bland de valda 2022'))
        if r['fullnamn'] != r['namn']: fakta.insert(1, ('Fullständigt namn', esc(r['fullnamn'])))
        if r.get('lan') and r['vt'] != 'RF': fakta.append(('Län', f'<a href="../../lan/{r["lan"]}/">{esc(lanNamn.get(r["lan"], r["lan"]))}</a>'))
        if r['fbk']: fakta.append(('Bor i', f'<a href="../../kommun/{slugify(r["fbk"])}/">{esc(r["fbk"])}</a>' if r['fbk_kod'] else esc(r['fbk'])))
        body = f"""<h1>{esc(r['namn'])}</h1><p class="lead">{pf(r['p'])} {party_a} · {geo_a(VT[r['vt']] + ((' · ' + esc(r['omr'])) if r['omr'] else ''))}{' · <span class="pv">invald på personröster</span>' if r['pv'] else ''}</p>
<div class="card" id="top"><table><tbody>{''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in fakta)}</tbody></table></div>
{('<h2>Fler uppdrag efter valet</h2><ul class="led sans">' + ''.join(f'<li><a href="../../person/{x["id"]}/">{VT[x["vt"]]}{(" – " + esc(x["omr"])) if x["omr"] else ""}</a></li>' for x in others) + '</ul>') if others else ''}
{('<h2>Uppdrag sedan ' + named_years[0] + '</h2><p class="small muted sans">Ursprungligt valda enligt Valmyndigheten. ' + (f'Sitter sin {r["streak"]}:e mandatperiod i rad i ' + VTS[r["vt"]] + '. ' if r['streak'] > 1 else '') + 'Matchning på namn och ålder. Valmyndigheten har gallrat personuppgifterna för valen före 2022, så det går inte att följa enskilda personer längre bakåt.' + (' Riksdagsuppdrag längre bak finns under Riksdagen nedan.' if r.get('rdp') else '') + '</p><table><thead><tr><th>Val</th><th>Församling</th><th>Parti</th><th class="r">Invald som nr</th><th></th></tr></thead><tbody>' + f'<tr><td><b>2026</b></td><td>{geo_a(VT[r["vt"]] + ((" – " + esc(r["omr"])) if r["omr"] else ""))}</td><td>{pf(r["p"])}</td><td class="r">{r["nr"] or "–"}</td><td class="small muted">{"personvald" if r["pv"] else ""}</td></tr>' + ''.join(f'<tr><td>{h["ar"]}</td><td>{(f'<a href="../../kommun/{slugify(kod2kom.get(h["kommunkod"], ""))}/">' + VT[h["valtyp"]] + ' – ' + esc(kod2kom.get(h["kommunkod"], "")) + '</a>') if h["valtyp"]=="KF" and kod2kom.get(h["kommunkod"]) else ((f'<a href="../../lan/{h["lankod"]}/">' + VT[h["valtyp"]] + ' – ' + esc(lanNamn.get(h["lankod"], "")) + '</a>') if h["valtyp"]=="RF" and h.get("lankod") else (VT[h["valtyp"]] + ((" – " + esc(h["valkrets"])) if h.get("valkrets") else "")))}</td><td>{pf(h["parti"])}{" <span class=\"small muted\">partibyte</span>" if h["parti"] != r["p"] else ""}</td><td class="r">{esc(h["invalsordning"]) or "–"}</td><td class="small muted">{"personvald" if h["personvald"]=="1" else ""}{(", ersättare som gick in" if h.get("ursprunglig")=="0" else "")}{(", avgick " + esc(h["avgang"])) if h.get("avgang") else ""}</td></tr>' for h in r['tl']) + '</tbody></table>') if r.get('tl') else ''}
{('<h2>I riksdagen</h2><div class="card"><table><tbody>' + (f'<tr><th>Mandatperioder som ledamot</th><td>{len(r["rdp"]["perioder"]) + (1 if r["vt"]=="RD" else 0)} ' + ('(inklusive 2026–2030)' if r["vt"]=="RD" else '') + ' – ' + ', '.join(f'{y}–{y+4}' for y in r["rdp"]["perioder"]) + (', 2026–2030' if r["vt"]=="RD" else '') + '</td></tr>' if r['rdp']['perioder'] else '<tr><th>Riksdagen</th><td>Har tjänstgjort som ersättare</td></tr>') + (f'<tr><th>Första gången i kammaren</th><td>{r["rdp"]["forst"]}</td></tr>' if r['rdp']['forst'] else '') + ''.join(f'<tr><th>{esc(roll)}</th><td>{esc(org)} {fr}–{to or "nu"}</td></tr>' for org, roll, fr, to in r['rdp']['roller'][-8:]) + (f'<tr><th>Kommunala uppdrag (biografi)</th><td class="small">{esc(r["rdp"]["kommunalt"])}</td></tr>' if r['rdp']['kommunalt'] else '') + f'</tbody></table><p class="small muted sans">Källa: <a href="https://data.riksdagen.se/personlista/?iid={esc(r["rdp"]["id"])}&utformat=html">Riksdagens öppna data</a>.</p></div>') if r.get('rdp') else ''}
{('<h2>Roller 2022–2026</h2><p class="small muted sans">Uppdrag under förra mandatperioden enligt Plenum. Vilka som får nämnd- och styrelseuppdrag 2026–2030 avgörs när fullmäktige väljer dem efter valet.</p><ul class="led sans">' + ''.join(f'<li>{esc(x)}</li>' for x in rl) + '</ul>') if rl else ''}
{('<h2>Hela listan' + (' – ' + esc(lkey[3]) if lkey else '') + (', ' + esc(full[0].get('VALKRETSNAMN') or '') if full and full[0].get('VALKRETSNAMN') and r['vt'] != 'KF' else '') + f' <span class="muted small">{len(full)} namn</span></h2><p class="small muted sans">Partiets valsedel i ordning. <b>Fet</b> = {esc(r["namn"])}. Markering: vald, ersättare för {esc(r["namn"].split()[0])}, ersättare för annan ledamot.</p><ol class="led">' + ''.join(f'<li{" style=\"font-weight:700\"" if c["KANDIDATNUMMER"] == r.get("kandidatnummer") else ""}>{(f'<a href="../../person/{knr2id[c["KANDIDATNUMMER"]]}/">' + esc(c["NAMN"]) + '</a>') if c["KANDIDATNUMMER"] in knr2id else esc(c["NAMN"])} <span class="ers">{"<span class=\"pv\">vald</span>" if c["KANDIDATNUMMER"] in valda_knr else ("ersättare för " + esc(r["namn"].split()[0]) if c["KANDIDATNUMMER"] in ers_knr else ("ersättare" if c["KANDIDATNUMMER"] in ers_any else ""))}{(" · " + esc(c["FOLKBOKFÖRINGSKOMMUN"])) if c.get("FOLKBOKFÖRINGSKOMMUN") and r["vt"] != "KF" else ""}{(" · " + esc(c.get("ÅLDER_PÅ_VALDAGEN")) + " år") if (c.get("ÅLDER_PÅ_VALDAGEN") or "").strip() else ""}</span></li>' for c in full) + '</ol>') if full else ''}
{('<h2>Ersättare för ' + esc(r['namn']) + '</h2><ol class="led">' + ''.join(f'<li>{esc(x["namn"])} <span class="ers">{esc(x.get("valgrund") or "")}</span></li>' for x in sorted(e, key=lambda x: int(num(x.get("ersattarordning")) or 0))) + '</ol>') if e else ''}
<p class="small sans"><a href="../../{'kommun/' + slugify(r['valomrnamn']) + '/' if r['vt']=='KF' else 'lan/' + r['lan'] + '/'}">Alla valda i {esc(r['valomrnamn'] if r['vt']=='KF' else lanNamn.get(r['lan'], ''))} →</a></p>"""
        crumb = f'<a href="../../">Sverige</a> › ' + (f'<a href="../../lan/{r["lan"]}/">{esc(lanNamn.get(r["lan"], ""))}</a> › ' if r.get('lan') else '') + (f'<a href="../../kommun/{slugify(r["valomrnamn"])}/">{esc(r["valomrnamn"])}</a> › ' if r['vt'] == 'KF' else '') + f'<a href="../../parti/{slugify(r["p"])}/">{esc(r["p"])}</a> › {esc(r["namn"])}'
        body = auto_subnav(body, after='</p>', short={'Fler': 'Fler uppdrag', 'Uppdrag': 'Historik', 'I': 'Riksdagen', 'Hela': 'Hela listan', 'Ersättare': 'Ersättare', 'Roller': 'Roller 2022–26'})
        write(f'person/{r["id"]}/index.html', page(r['namn'], body, 2, crumb, built).replace('__SCRIPT__', ''))

    # ---- statistik ----
    def barchart(rows, key, fmt=lambda v: str(v), color=None, width=640):
        mx = max((v for _, v in rows), default=1) or 1
        return '<div style="font-family:system-ui;font-size:.86rem">' + ''.join(f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><div style="width:150px">{lab}</div><div style="flex:1;background:var(--line);border-radius:5px;overflow:hidden"><div style="width:{100*v/mx:.1f}%;height:16px;background:{(color(lab) if color else "var(--acc)")}"></div></div><div style="width:70px;text-align:right">{fmt(v)}</div></div>' for lab, v in rows) + '</div>'
    sec = ''
    for vt in ('RD', 'RF', 'KF'):
        rs = [r for r in valda if r['vt'] == vt]
        if not rs: continue
        c = Counter(r['p'] for r in rs); top = c.most_common(12)
        pvs = [(p, round(100*sum(1 for r in rs if r['p'] == p and r['pv'])/c[p])) for p, _ in top if c[p] >= 5]
        prs = sorted([r for r in rs if r.get('pr_tot') is not None], key=lambda r: -r['pr_tot'])[:10]
        sec += f'<h2>{VT[vt]} <span class="muted small">{fmtn(len(rs))} ledamöter</span></h2><div class="grid2"><div><h3>Mandat per parti</h3>{barchart([(pf(p)+" "+esc(PN.get(p,p)), v) for p, v in top], None, color=None)}</div><div><h3>Andel invalda på personröster</h3>{barchart([(pf(p), v) for p, v in sorted(pvs, key=lambda x: -x[1])], None, fmt=lambda v: f"{v} %")}</div></div>'
        if prs: sec += '<h3>Flest personröster</h3><table><thead><tr><th>Namn</th><th>Parti</th><th>Område</th><th class="r">Personröster</th></tr></thead><tbody>' + ''.join(f'<tr><td><a href="../person/{r["id"]}/">{esc(r["namn"])}</a></td><td>{pf(r["p"])}</td><td>{esc(r["omr"] or "")}</td><td class="r">{fmtn(r["pr_tot"])}</td></tr>' for r in prs) + '</tbody></table>'
    rd = [r for r in valda if r['vt'] == 'RD']; fbk = Counter(r['fbk'] for r in rd if r['fbk'])
    missade = [r for r in pers if r.get('kvalificerad') == 'Ja' and r.get('invald') != 'Ja']
    sec += f'<h2>Var riksdagsledamöterna bor</h2><p class="lead">{len(fbk)} kommuner har minst en ledamot i riksdagen. {290-len(fbk)} kommuner har ingen.</p>{barchart(fbk.most_common(15), None)}'
    if missade: sec += f'<h2>Klarade personröstspärren men kom inte in</h2><p class="lead">{len(missade)} kandidater fick tillräckligt många personröster men partiet hade inte mandat nog. De tio med flest röster:</p><table><thead><tr><th>Namn</th><th>Parti</th><th>Val</th><th>Område</th><th class="r">Personröster</th></tr></thead><tbody>' + ''.join(f'<tr><td>{esc(r["namn"])}</td><td>{pf(r["parti"])}</td><td>{r["valtyp"]}</td><td>{esc(r.get("valomrnamn") or "")}</td><td class="r">{fmtn(num(r["personroster"]) or 0)}</td></tr>' for r in sorted(missade, key=lambda r: -(num(r["personroster"]) or 0))[:10]) + '</tbody></table>'
    # ---------- utveckling 2010–2026 ----------
    def svgline(series, years, ymin=None, ymax=None, unit='', W=560, H=200):
        vals = [v for s in series.values() for v in s if v is not None]
        if not vals: return ''
        lo = ymin if ymin is not None else min(vals)*0.95; hi = ymax if ymax is not None else max(vals)*1.05
        sx = lambda i: 40 + i*(W-110)/max(1, len(years)-1); sy = lambda v: 10 + (1-(v-lo)/((hi-lo) or 1))*(H-40)
        out = ''.join(f'<text x="{sx(i):.0f}" y="{H-8}" font-size="11" text-anchor="middle" fill="currentColor" opacity=".6">{y}</text>' for i, y in enumerate(years))
        COLS = {'Riksdagen': '#1f5f8b', 'Regionfullmäktige': '#e07b39', 'Kommunfullmäktige': '#2e7d5b', 'Kandidater': '#b0313f'}
        for lab, s in series.items():
            pts = [(sx(i), sy(v)) for i, v in enumerate(s) if v is not None]
            if len(pts) < 2: continue
            c = COLS.get(lab, '#1f5f8b')
            out += f'<path d="{"".join(("M" if j==0 else "L")+f"{x:.1f},{y:.1f}" for j,(x,y) in enumerate(pts))}" fill="none" stroke="{c}" stroke-width="2.4"/>' + ''.join(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3" fill="{c}"/><circle data-tip="{esc(lab)} {years[i]}: {str(v).replace(".", ",")}{unit}" cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="11" fill="transparent"/>' for i, v in enumerate(s) if v is not None)
            out += f'<text x="{pts[-1][0]+6:.1f}" y="{pts[-1][1]+4:.1f}" font-size="11" fill="{c}">{esc(lab.replace("fullmäktige","f."))} {str(s[-1]).replace(".",",") if s[-1] is not None else ""}{unit}</text>'
        return f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:620px;font-family:system-ui">{out}</svg>'
    years = ['2010', '2014', '2018', '2022', '2026']
    def series(fn):
        out = {}
        for vt in ('RD', 'RF', 'KF'):
            s = []
            for ar in years:
                rows = [r for r in valda if r['vt'] == vt] if ar == '2026' else [h for h in hist if h['ar'] == ar and h['valtyp'] == vt and h['ursprunglig'] == '1']
                s.append(fn(rows, ar) if rows else None)
            out[VT[vt]] = s
        return out
    kv = series(lambda rs, ar: pct(sum(1 for r in rs if r['kon'] == 'K'), sum(1 for r in rs if r['kon'])))
    ma = series(lambda rs, ar: mean([r['alder'] if ar == '2026' else r['alder_i'] for r in rs]))
    pvs = series(lambda rs, ar: pct(sum(1 for r in rs if (r['pv'] if ar == '2026' else r['personvald'] == '1')), len(rs)))
    utv = f'<h2>Utvecklingen 2010–2026</h2><p class="lead">Ursprungligt valda ledamöter efter varje val. Namnen före 2022 är gallrade av Valmyndigheten, så historiken visar bara helheten.</p><div class="grid2"><div><h3>Andel kvinnor, %</h3>{svgline(kv, years)}</div><div><h3>Medelålder</h3>{svgline(ma, years)}</div></div><h3>Andel invalda på personröster, %</h3>{svgline(pvs, years)}'
    # parti-tabell KF
    pt = '<h3>Kommunfullmäktige per parti: andel kvinnor och medelålder</h3><table><thead><tr><th>Parti</th>' + ''.join(f'<th class="r">{y}</th>' for y in years) + '</tr></thead><tbody>'
    for p in PIDS:
        cells = []
        for ar in years:
            rs = [r for r in valda if r['vt'] == 'KF' and r['p'] == p] if ar == '2026' else [h for h in hist if h['ar'] == ar and h['valtyp'] == 'KF' and h['parti'] == p and h['ursprunglig'] == '1']
            if not rs: cells.append('<td class="r">–</td>'); continue
            k = pct(sum(1 for r in rs if r['kon'] == 'K'), sum(1 for r in rs if r['kon'])); m = mean([r['alder'] if ar == '2026' else r['alder_i'] for r in rs])
            cells.append(f'<td class="r">{str(k).replace(".", ",") if k is not None else "–"} % <span class="muted small">· {str(m).replace(".", ",") if m is not None else "–"} år</span></td>')
        pt += f'<tr><td>{pf(p)}</td>{"".join(cells)}</tr>'
    utv += pt + '</tbody></table>'
    # ---------- kandidater mot valda ----------
    kmv = '<h2>Kandidater mot valda 2026</h2><p class="lead">Alla giltiga kandidaturer jämförda med dem som valdes. Skillnaden visar vilka som "faller bort" på vägen från lista till fullmäktige.</p><table><thead><tr><th>Val</th><th class="r">Kandidater</th><th class="r">Valda</th><th class="r">Kvinnor kand. / valda</th><th class="r">Medelålder kand. / valda</th></tr></thead><tbody>'
    agerows = ''
    for vt in ('RD', 'RF', 'KF'):
        ks = list({k['KANDIDATNUMMER']: k for k in allkand if k.get('VALTYP') == vt and k.get('GILTIG', 'J') == 'J'}.values())
        vs = [r for r in valda if r['vt'] == vt]
        ka = [int(num(k.get('ÅLDER_PÅ_VALDAGEN')) or 0) or None for k in ks]
        kk_ = pct(sum(1 for k in ks if k.get('KÖN') == 'K'), sum(1 for k in ks if k.get('KÖN'))); vk = pct(sum(1 for r in vs if r['kon'] == 'K'), sum(1 for r in vs if r['kon']))
        kmv += f'<tr><td>{VT[vt]}</td><td class="r">{fmtn(len(ks))}</td><td class="r">{fmtn(len(vs))}</td><td class="r">{str(kk_).replace(".", ",") if kk_ is not None else "–"} % / {str(vk).replace(".", ",") if vk is not None else "–"} %</td><td class="r">{str(mean(ka)).replace(".", ",") if mean(ka) else "–"} / {str(mean([r["alder"] for r in vs])).replace(".", ",") if mean([r["alder"] for r in vs]) else "–"}</td></tr>'
        kc = Counter(agegrp(a) for a in ka if a); vc = Counter(agegrp(r['alder']) for r in vs if r['alder'])
        agerows += f'<h3>{VT[vt]}: åldersgrupper</h3><div style="font-family:system-ui;font-size:.86rem">' + ''.join(f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0"><div style="width:60px">{lab}</div><div style="flex:1" data-tip="{VT[vt]} {lab} år\nKandidater: {str(pct(kc[lab], sum(kc.values())) or 0).replace('.', ',')} % ({kc[lab]} st)\nValda: {str(pct(vc[lab], sum(vc.values())) or 0).replace('.', ',')} % ({vc[lab]} st)"><div style="height:10px;background:#b0313f;opacity:.55;width:{pct(kc[lab], sum(kc.values())) or 0}%;border-radius:4px"></div><div style="height:10px;background:var(--acc);width:{pct(vc[lab], sum(vc.values())) or 0}%;border-radius:4px;margin-top:2px"></div></div><div style="width:120px;text-align:right">{str(pct(kc[lab], sum(kc.values())) or 0).replace(".", ",")} % / {str(pct(vc[lab], sum(vc.values())) or 0).replace(".", ",")} %</div></div>' for lab, _, _ in AGEGRP) + '</div>'
    kmv += '</tbody></table><p class="small muted sans">Kandidater räknas en gång per val, även om de står på flera listor eller valsedlar. Röd stapel = kandidater, blå = valda.</p><div class="grid3">' + agerows + '</div>'
    # titlar
    vt_t = Counter(r['titel'].lower() for r in valda if r['titel'])
    k_t = Counter(titel(k.get('VALSEDELSUPPGIFT')).lower() for k in {(k['VALTYP'], k['KANDIDATNUMMER']): k for k in allkand if k.get('GILTIG', 'J') == 'J' and k.get('VALSEDELSUPPGIFT')}.values())
    nv, nk = sum(vt_t.values()) or 1, sum(k_t.values()) or 1
    trows = [(t, n, k_t.get(t, 0)) for t, n in vt_t.most_common(25)]
    yrk_chart = hbars([(esc(t[:1].upper() + t[1:]), n, None) for t, n, k in trows[:20]], '', w_lab=170)
    yrk = '<h2>Vad de valda jobbar med</h2><p class="lead">Titeln de själva angett på valsedeln (fritext, tolkad som första ledet som inte är en ort). Index över 1 betyder att titeln är vanligare bland de valda än bland kandidaterna.</p>' + yrk_chart + '<table><thead><tr><th>Titel</th><th class="r">Valda</th><th class="r">Andel valda</th><th class="r">Andel kandidater</th><th class="r">Index</th></tr></thead><tbody>' + ''.join(f'<tr><td>{esc(t[:1].upper()+t[1:])}</td><td class="r">{n}</td><td class="r">{str(pct(n, nv)).replace(".", ",")} %</td><td class="r">{str(pct(k, nk)).replace(".", ",")} %</td><td class="r"><b>{str(round((n/nv)/(k/nk), 2)).replace(".", ",") if k else "–"}</b></td></tr>' for t, n, k in trows) + '</tbody></table>'
    # ---------- förnyelse och avgångar ----------
    fn = '<h2>Förnyelse: nya och omvalda</h2><p class="lead">Andel av de valda 2026 som inte satt i samma församling efter valet 2022. Matchning på namn, parti och ålder (uppskattning: namnbyten och partibyten kan ge fel).</p><table><thead><tr><th>Parti</th>' + ''.join(f'<th class="r">{VT[v]}</th>' for v in ('RD', 'RF', 'KF')) + '</tr></thead><tbody>'
    for p in PIDS + ['Alla']:
        cells = ''
        for vt in ('RD', 'RF', 'KF'):
            vs = [r for r in valda if r['vt'] == vt and (p == 'Alla' or r['p'] == p)]
            nyv = sum(1 for r in vs if r.get('status22') != 'omvald')
            cells += f'<td class="r">{str(pct(nyv, len(vs))).replace(".", ",") if vs else "–"} %</td>'
        fn += f'<tr><td>{pf(p) if p != "Alla" else "<b>Alla partier</b>"}</td>{cells}</tr>'
    fn += '</tbody></table><h2>Avhopp under mandatperioden 2022–2026</h2><p class="lead">Andel av de ursprungligt valda 2022 som lämnade sitt uppdrag före valet 2026, enligt Valmyndighetens register.</p><table><thead><tr><th>Parti</th>' + ''.join(f'<th class="r">{VT[v]}</th>' for v in ('RD', 'RF', 'KF')) + '</tr></thead><tbody>'
    for p in PIDS + ['Alla']:
        cells = ''
        for vt in ('RD', 'RF', 'KF'):
            hs = [h for h in hist if h['ar'] == '2022' and h['valtyp'] == vt and h['ursprunglig'] == '1' and (p == 'Alla' or h['parti'] == p)]
            cells += f'<td class="r">{str(pct(sum(1 for h in hs if h.get("avgang")), len(hs))).replace(".", ",") if hs else "–"} %</td>'
        fn += f'<tr><td>{pf(p) if p != "Alla" else "<b>Alla partier</b>"}</td>{cells}</tr>'
    fn += '</tbody></table>'
    # diagram före tabellerna
    def ny_pct(vt, p): 
        vs = [r for r in valda if r['vt'] == vt and r['p'] == p]; return pct(sum(1 for r in vs if r.get('status22') != 'omvald'), len(vs)) if vs else None
    def avh_pct(vt, p):
        hs = [h for h in hist if h['ar'] == '2022' and h['valtyp'] == vt and h['ursprunglig'] == '1' and h['parti'] == p]; return pct(sum(1 for h in hs if h.get('avgang')), len(hs)) if hs else None
    ch_ny = '<div class="grid3">' + ''.join(f'<div><h3>{VT[vt]}: andel nya</h3>' + hbars([(pf(p), ny_pct(vt, p), col(p)) for p in PIDS], ' %', mx=100, w_lab=40) + '</div>' for vt in ('RD', 'RF', 'KF')) + '</div>'
    ch_av = '<div class="grid3">' + ''.join(f'<div><h3>{VT[vt]}: avhopp 2022–26</h3>' + hbars([(pf(p), avh_pct(vt, p), col(p)) for p in PIDS], ' %', mx=max([avh_pct(vt, q) or 0 for q in PIDS] + [1]), w_lab=40) + '</div>' for vt in ('RD', 'RF', 'KF')) + '</div>'
    fn = fn.replace('</p><table><thead><tr><th>Parti</th>', '</p>' + ch_ny + '<details class="omr"><summary>Visa tabell</summary><table><thead><tr><th>Parti</th>', 1)
    fn = fn.replace('</tbody></table><h2>Avhopp', '</tbody></table></details><h2>Avhopp', 1)
    fn = fn.replace('enligt Valmyndighetens register.</p><table>', 'enligt Valmyndighetens register.</p>' + ch_av + '<details class="omr"><summary>Visa tabell</summary><table>', 1)
    if fn.endswith('</tbody></table>'): fn += '</details>'
    # listklättrare
    jumps = sorted([r for r in valda if r.get('jump') and r['jump'] > 0], key=lambda r: -r['jump'])[:15]
    if jumps: fn += '<h2>Största listklättrarna</h2><p class="lead">Personvalda som blev valda långt före sin listplats. Listplatsen är den bästa plats personen hade på någon av partiets valsedlar i valkretsen.</p><table><thead><tr><th>Namn</th><th>Parti</th><th>Område</th><th class="r">Listplats → mandat</th></tr></thead><tbody>' + ''.join(f'<tr><td><a href="../person/{r["id"]}/">{esc(r["namn"])}</a></td><td>{pf(r["p"])}</td><td>{esc(r["omr"] or "")}</td><td class="r">{r["listplats"]} → {r["nr"]}</td></tr>' for r in jumps) + '</tbody></table>'
    # ---------- kommunkarta ----------
    kmet = {}
    for nm_, kk in komKod.items():
        vs = [r for r in valda if r['vt'] == 'KF' and r['valomrkod'] == kk]
        if not vs: continue
        kmet[kk] = {'n': nm_, 's': slugify(nm_), 'kv': pct(sum(1 for r in vs if r['kon'] == 'K'), sum(1 for r in vs if r['kon'])), 'ma': mean([r['alder'] for r in vs]),
                    'ny': pct(sum(1 for r in vs if r.get('status22') != 'omvald'), len(vs)), 'pv': pct(sum(1 for r in vs if r['pv']), len(vs))}
    krings = {k: v for k, v in (d.get('granser', {}).get('kommun') or {}).items() if k in kmet}
    if krings:
        x0, y0, x1, y1 = bbox(list(krings.values()))
        paths = ''.join(f'<a href="../kommun/{kmet[k]["s"]}/"><path data-k="{k}" d="{rings_path(rg)}"><title>{esc(kmet[k]["n"])}</title></path></a>' for k, rg in krings.items())
        karta = f'''<h2>Kommunfullmäktige på kartan</h2><div class="chips sans" id="km"><button class="chip" data-m="kv">Andel kvinnor</button><button class="chip" data-m="ma">Medelålder</button><button class="chip" data-m="ny">Andel nya</button><button class="chip" data-m="pv">Andel personvalda</button></div>
<div class="maprow"><div><svg class="map" id="kmap" viewBox="{x0:.0f} {y0:.0f} {x1-x0:.0f} {y1-y0:.0f}">{paths}</svg><p class="zoom" id="kleg"></p></div><div id="ktop" class="sans small"></div></div>
<script>const KM={json.dumps(kmet, ensure_ascii=False, separators=(",", ":"))};const LAB={{kv:'Andel kvinnor (%)',ma:'Medelålder (år)',ny:'Andel nya jämfört med 2022 (%)',pv:'Andel invalda på personröster (%)'}};
function km(m){{const v=Object.values(KM).map(x=>x[m]).filter(x=>x!=null);const lo=Math.min(...v),hi=Math.max(...v);document.querySelectorAll('#kmap path').forEach(p=>{{const x=KM[p.dataset.k];const t=x&&x[m]!=null?(x[m]-lo)/((hi-lo)||1):null;p.style.fill=t==null?'':`rgba(31,95,139,${{(0.12+0.88*t).toFixed(2)}})`;p.querySelector('title').textContent=x.n+': '+String(x[m]).replace('.',',');var f=v=>v==null?'–':String(v).replace('.',',');p.setAttribute('data-tip',x.n+'\\nKvinnor '+f(x.kv)+' %\\nMedelålder '+f(x.ma)+' år\\nNya '+f(x.ny)+' %\\nPersonvalda '+f(x.pv)+' %');}});
 document.getElementById('kleg').textContent=LAB[m]+': ljus '+String(lo).replace('.',',')+' – mörk '+String(hi).replace('.',',')+'. Klicka på en kommun.';
 const s=Object.values(KM).filter(x=>x[m]!=null).sort((a,b)=>b[m]-a[m]);document.getElementById('ktop').innerHTML='<h3 style="margin-top:0">Högst</h3>'+s.slice(0,8).map(x=>`<div><a href="../kommun/${{x.s}}/">${{x.n}}</a> ${{String(x[m]).replace('.',',')}}</div>`).join('')+'<h3>Lägst</h3>'+s.slice(-8).reverse().map(x=>`<div><a href="../kommun/${{x.s}}/">${{x.n}}</a> ${{String(x[m]).replace('.',',')}}</div>`).join('');
 document.querySelectorAll('#km .chip').forEach(c=>c.style.borderColor=c.dataset.m===m?'var(--acc)':'');}}
document.querySelectorAll('#km .chip').forEach(c=>c.onclick=()=>km(c.dataset.m));km('kv');</script>'''
    else: karta = ''
    if len(named_years) >= 3:   # bara meningsfullt när namnen räcker flera mandatperioder bakåt
        tn = '<h2>Hur länge har de suttit?</h2><p class="lead">Antal mandatperioder i rad i samma församling, räknat bakåt till ' + named_years[0] + '. Matchning på namn och ålder.</p><table><thead><tr><th>Församling</th>' + ''.join(f'<th class="r">{k} {"period" if k==1 else "perioder"}</th>' for k in range(1, len(named_years)+2)) + '</tr></thead><tbody>'
        for vt in ('RD', 'RF', 'KF'):
            vs = [r for r in valda if r['vt'] == vt]; c = Counter(r.get('streak', 1) for r in vs)
            tn += f'<tr><td>{VT[vt]}</td>' + ''.join(f'<td class="r">{str(pct(c[k], len(vs))).replace(".", ",")} %</td>' for k in range(1, len(named_years)+2)) + '</tr>'
        tn += '</tbody></table>'
        fn = tn + fn
    rdv = [r for r in valda if r['vt'] == 'RD']; rd_html = ''
    if rdh and rdv:
        c = Counter(len((r.get('rdp') or {}).get('perioder', [])) for r in rdv)
        tr = '<h2>Erfarenhet i riksdagen</h2><p class="lead">Hur många mandatperioder de valda 2026 redan suttit i riksdagen, enligt Riksdagens öppna data (exakt, från 1994).</p><table><thead><tr><th>Parti</th><th class="r">Nya i riksdagen</th><th class="r">1 period</th><th class="r">2–3 perioder</th><th class="r">4+ perioder</th><th class="r">Snitt</th></tr></thead><tbody>'
        for p in PIDS + ['Alla']:
            vs = [r for r in rdv if p == 'Alla' or r['p'] == p]
            if not vs: continue
            n = [len((r.get('rdp') or {}).get('perioder', [])) for r in vs]
            tr += f'<tr><td>{pf(p) if p != "Alla" else "<b>Alla</b>"}</td><td class="r">{sum(1 for x in n if x == 0)}</td><td class="r">{sum(1 for x in n if x == 1)}</td><td class="r">{sum(1 for x in n if 2 <= x <= 3)}</td><td class="r">{sum(1 for x in n if x >= 4)}</td><td class="r">{str(round(sum(n)/len(n), 1)).replace(".", ",")}</td></tr>'
        tr += '</tbody></table>'
        rows_st = []
        for p in PIDS + ['Alla']:
            vs = [r for r in rdv if p == 'Alla' or r['p'] == p]
            if not vs: continue
            n = [len((r.get('rdp') or {}).get('perioder', [])) for r in vs]
            rows_st.append((pf(p) if p != 'Alla' else '<b>Alla</b>', {'0': 100*sum(1 for x in n if x == 0)/len(n), '1': 100*sum(1 for x in n if x == 1)/len(n), '2': 100*sum(1 for x in n if 2 <= x <= 3)/len(n), '4': 100*sum(1 for x in n if x >= 4)/len(n)}))
        tr = tr.replace('<table>', stacked(rows_st, ['0', '1', '2', '4'], {'0': '#e0a83a', '1': '#8fb8d8', '2': '#1f5f8b', '4': '#173a55'}, {'0': 'nya', '1': '1 period', '2': '2–3 perioder', '4': '4+ perioder'}) + '<details class="omr"><summary>Visa tabell</summary><table>', 1).replace('</tbody></table>', '</tbody></table></details>', 1)
        ex = [r for r in valda if r['vt'] != 'RD' and r.get('rdp') and r['rdp']['perioder']]
        if ex: tr += f'<h3>Före detta riksdagsledamöter i region- och kommunfullmäktige ({len(ex)})</h3><ol class="led">' + ''.join(f'<li><a href="../person/{r["id"]}/">{esc(r["namn"])}</a> <span class="ers">{pf(r["p"])} · {VTS[r["vt"]]} {esc(r["omr"] or "")} · riksdagen {r["rdp"]["perioder"][0]}–{r["rdp"]["perioder"][-1]+4}</span></li>' for r in sorted(ex, key=lambda r: -len(r["rdp"]["perioder"]))[:40]) + '</ol>'
        rd_html = tr
    per_val = sec
    # ---------- korskörningar: valda/partier × Faktadriven ----------
    kd = {}
    for nm_, kk in komKod.items():
        vs = [r for r in valda if r['vt'] == 'KF' and r['valomrkod'] == kk]
        if not vs: continue
        m_ = mand.get(('KF', kk), {}); tot = sum(v[1] for v in m_.values()) or None
        sk = styreK.get(kk, {}); parts = [p for p in (sk.get('partier') or '').split(',') if p]
        st = None
        if parts and tot:
            s26 = sum(m_.get(p, (0, 0))[1] for p in parts if p in m_); maj = tot // 2 + 1
            st = 'behöll' if s26 >= maj else ('beror' if 'ÖP' in parts else 'förlorade')
        kd[kk] = dict(n=nm_, s=slugify(nm_), ma_kf=mean([r['alder'] for r in vs]), kv=pct(sum(1 for r in vs if r['kon'] == 'K'), sum(1 for r in vs if r['kon'])),
                      ny=pct(sum(1 for r in vs if r.get('status22') != 'omvald'), len(vs)), pv=pct(sum(1 for r in vs if r['pv']), len(vs)),
                      vd=vdel.get(('KF', 'kommun', kk)), st=st, share={p: 100*v[1]/tot for p, v in m_.items()} if tot else {})
    def P(fx, fy): return [(fx(k, v), fy(k, v), v['n'], v['s']) for k, v in kd.items()]
    ks = ''
    if kd and FK:
        ks += ('<h2>Speglar fullmäktige befolkningen?</h2><p class="lead">Medelåldern i kommunfullmäktige 2026 jämfört med medelåldern i hela befolkningen (inklusive barn, som inte kan väljas). Den röda linjen visar trenden: kommuner med äldre befolkning har också äldre fullmäktige.</p>'
               + scatter(P(lambda k, v: fv(k, 'ma'), lambda k, v: v['ma_kf']), 'Medelålder i befolkningen', 'Medelålder i fullmäktige 2026', 'år', 'år'))
        gap = sorted([(v['ma_kf'] - fv(k, 'ma'), v) for k, v in kd.items() if v['ma_kf'] and fv(k, 'ma')], key=lambda x: -x[0])
        if gap: ks += f'<p class="small sans">I genomsnitt är fullmäktige <b>{fmt(sum(g for g, _ in gap)/len(gap))} år äldre</b> än befolkningen. Störst skillnad: ' + ', '.join(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a> (+{fmt(g)})' for g, v in gap[:5]) + '. Minst: ' + ', '.join(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a> ({"+" if g > 0 else ""}{fmt(g)})' for g, v in gap[-3:]) + '.</p>'
        dk = sorted([(v['kv'] - fv(k, 'kkf'), v) for k, v in kd.items() if v['kv'] is not None and fv(k, 'kkf') is not None], key=lambda x: -x[0])
        if dk:
            ks += ('<h2>Fler eller färre kvinnor än förra mandatperioden</h2><p class="lead">Andel kvinnor i kommunfullmäktige 2026 jämfört med 2022–2026 (Kolada). Förändring i procentenheter.</p><div class="grid2"><div><h3>Störst ökning</h3>'
                   + hbars([(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a>', round(g, 1), '#e07b39') for g, v in dk[:10]], ' pe', w_lab=130) + '</div><div><h3>Störst minskning</h3>'
                   + hbars([(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a>', round(-g, 1), '#1f5f8b') for g, v in dk[-10:][::-1]], ' pe', w_lab=130) + '</div></div>'
                   + f'<p class="small muted sans">Andel kvinnor ökade i {sum(1 for g, _ in dk if g > 0)} kommuner och minskade i {sum(1 for g, _ in dk if g < 0)}.</p>')
        ks += ('<h2>Avhopp, hot och förnyelse</h2><p class="lead">Kommuner där många förtroendevalda hoppade av under 2018–2022 jämfört med hur stor andel av fullmäktige som är ny 2026.</p>'
               + scatter(P(lambda k, v: fv(k, 'avh'), lambda k, v: v['ny']), 'Hoppade av fullmäktige 2018–2022 (%)', 'Andel nya i fullmäktige 2026 (%)', '%', '%'))
        rh = [(fv('00' + lk_, 'hot'), lanNamn.get(lk_, lk_)) for lk_ in lanNamn if fv('00' + lk_, 'hot') is not None]
        if rh: ks += '<h3>Förtroendevalda utsatta för trakasserier, hot eller våld, per län (2024)</h3>' + hbars([(f'<a href="../../lan/{lk_}/">{esc(n_)}</a>', v_, '#b0313f') for (v_, n_), lk_ in sorted([((fv("00" + l_, "hot"), lanNamn.get(l_, l_)), l_) for l_ in lanNamn if fv("00" + l_, "hot") is not None], key=lambda x: -x[0][0])], ' %', mx=50, w_lab=170) + f'<p class="small muted sans">Riket: {fmt(fv("0000", "hot"), "%")}. Källa: Kolada N65900 (Politikernas trygghetsundersökning) via Faktadriven.</p>'
        ks += ('<h2>Valdeltagande och ekonomi</h2><p class="lead">Valdeltagandet i kommunvalet 2026 jämfört med kommunens medianinkomst och andelen invånare med ekonomiskt bistånd.</p><div class="grid2"><div>'
               + scatter(P(lambda k, v: fv(k, 'ink') and fv(k, 'ink')/1000, lambda k, v: v['vd']), 'Medianinkomst 20–64 år (tkr)', 'Valdeltagande kommunvalet 2026 (%)', '', '%') + '</div><div>'
               + scatter(P(lambda k, v: fv(k, 'eb'), lambda k, v: v['vd']), 'Invånare med ekonomiskt bistånd (%)', 'Valdeltagande kommunvalet 2026 (%)', '%', '%') + '</div></div>')
        dv = sorted([(v['vd'] - fv(k, 'vd'), v) for k, v in kd.items() if v['vd'] is not None and fv(k, 'vd') is not None], key=lambda x: -x[0])
        if dv: ks += f'<p class="small sans">Jämfört med kommunvalet 2022 ökade valdeltagandet mest i ' + ', '.join(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a> (+{fmt(g)})' for g, v in dv[:5]) + ' och minskade mest i ' + ', '.join(f'<a href="../../kommun/{v["s"]}/">{esc(v["n"])}</a> ({fmt(g)})' for g, v in dv[-5:][::-1]) + '. 2022 års valdeltagande är Koladas avrundade värde.</p>'
        # väljarnas dom över styret
        grp = {'behöll': [], 'förlorade': []}
        for k, v in kd.items():
            if v['st'] in grp: grp[v['st']].append(k)
        def gm(keys, f):
            xs = [f(k) for k in keys]; xs = [x for x in xs if x is not None]; return round(sum(xs)/len(xs), 2) if xs else None
        mets = [('Förändring arbetslöshet 2022–2024, procentenheter', lambda k: (fv(k, 'al') - fv(k, 'al22')) if fv(k, 'al') is not None and fv(k, 'al22') is not None else None),
                ('Befolkningsförändring 2022–2024, %', lambda k: 100*(fv(k, 'p24')/fv(k, 'p22')-1) if fv(k, 'p22') and fv(k, 'p24') else None),
                ('Förändring anmälda brott 2022–2025, %', lambda k: 100*(fv(k, 'br')/fv(k, 'br22')-1) if fv(k, 'br') and fv(k, 'br22') else None),
                ('Kommunens resultat, snitt 2023–2025, % av skatt och bidrag', lambda k: fv(k, 'res3')),
                ('Nettokostnadsavvikelse 2025, %', lambda k: fv(k, 'nka')),
                ('Skattesats 2026, %', lambda k: fv(k, 'sk'))]
        if grp['behöll'] and grp['förlorade']:
            ks += (f'<h2>Belönade väljarna styren i kommuner som gick bra?</h2><p class="lead">Kommuner där det sittande styret <b>behöll</b> majoriteten ({len(grp["behöll"])} st) jämfört med där styret <b>förlorade</b> den ({len(grp["förlorade"])} st), och hur kommunen utvecklades under mandatperioden. Medelvärden per grupp.</p><table><thead><tr><th>Mått</th><th class="r">Behöll</th><th class="r">Förlorade</th><th class="r">Skillnad</th></tr></thead><tbody>'
                   + ''.join(f'<tr><td>{esc(lab)}</td><td class="r">{fmt(gm(grp["behöll"], f))}</td><td class="r">{fmt(gm(grp["förlorade"], f))}</td><td class="r"><b>{fmt((gm(grp["behöll"], f) or 0) - (gm(grp["förlorade"], f) or 0))}</b></td></tr>' for lab, f in mets)
                   + '</tbody></table><p class="small muted sans">Styren med ett lokalt parti som avgör räknas inte. Skillnader mellan grupper visar samband, inte orsak: kommunernas storlek, läge och partifärg skiljer sig också. Styre 2022–2026: Faktadriven. Mandat 2026: Valmyndigheten.</p>')
        # partiernas styrka × kommunprofil
        ind = [('ink', 'Medianinkomst'), ('uf', 'Utrikes födda'), ('tg', 'Tätortsgrad'), ('ma', 'Medelålder'), ('al', 'Arbetslöshet'), ('eb', 'Ekonomiskt bistånd'), ('br', 'Anmälda brott'), ('mv', 'Meritvärde åk 9'), ('bf', 'Befolkningsförändring'), ('sk', 'Skattesats')]
        hm = '<h2>Partiernas styrka och kommunens profil</h2><p class="lead">Samband mellan partiernas andel av mandaten i kommunfullmäktige 2026 och kommunens nyckeltal, över alla kommuner. Blått = partiet är starkare där måttet är högt, orange = svagare. Hovra eller tryck för förklaring.</p><div style="overflow-x:auto"><table class="hm"><thead><tr><th></th>' + ''.join(f'<th class="r">{p}</th>' for p in PIDS) + '</tr></thead><tbody>'
        for k_, lab in ind:
            hm += f'<tr><td>{esc(lab)}</td>'
            for p in PIDS:
                r_ = pearson([fv(k, k_) for k in kd], [kd[k]['share'].get(p, 0) for k in kd])
                if r_ is None: hm += '<td>–</td>'; continue
                a_ = min(1, abs(r_)/0.7); bg = f'rgba(31,95,139,{a_:.2f})' if r_ > 0 else f'rgba(224,123,57,{a_:.2f})'
                hm += f'<td class="r" data-tip="{p} och {esc(lab.lower())}: r = {str(round(r_, 2)).replace(".", ",")}&#10;{esc(rtext(r_).split(" – ")[-1])}&#10;{len(kd)} kommuner" style="background:{bg};color:{"#fff" if a_ > .55 else "inherit"}">{str(round(r_, 2)).replace(".", ",")}</td>'
            hm += '</tr>'
        ks += hm + '</tbody></table></div><p class="small muted sans">Pearsons r. 0 = inget samband, ±0,3 tydligt, ±0,5 starkt. Samband är inte orsak.</p>'
        ks += ('<h2>Personval och kommunstorlek</h2><p class="lead">Andelen av fullmäktige som kom in på personröster jämfört med kommunens folkmängd.</p>'
               + scatter(P(lambda k, v: (fv(k, 'p24') and __import__('math').log10(fv(k, 'p24'))), lambda k, v: v['pv']), 'Folkmängd (log10: 4 = 10 000, 5 = 100 000)', 'Invalda på personröster 2026 (%)', '', '%'))
    STAT = [('korskorningar', 'Korskörningar', 'Fullmäktige mot befolkningen, hot och avhopp, valdeltagande och ekonomi, väljarnas dom över styren och partiernas profil.', ks),            ('utveckling', 'Utveckling 2010–2026', 'Kvinnor, medelålder och personvalda val för val sedan 2010.', utv),
            ('kandidater', 'Kandidater mot valda', 'Vilka som står på listorna jämfört med vilka som blir valda.', kmv),
            ('yrken', 'Yrken', 'Vad de valda jobbar med, jämfört med kandidaterna.', yrk),
            ('fornyelse', 'Förnyelse', 'Nya och omvalda, hur länge de suttit, avhopp och listklättrare.', fn),
            ('riksdagen', 'Riksdagen', 'Erfarenhet i riksdagen enligt Riksdagens öppna data.', rd_html),
            ('personval', 'Mandat och personval', 'Mandat per parti, flest personröster och var riksdagsledamöterna bor.', per_val)]
    STAT = [s for s in STAT if s[3]]
    def stat_nav(cur):
        return subnav([('../' if cur else './', 'Översikt')] + [(('../' if cur else '') + k + '/', t) for k, t, _, _ in STAT], ('../' if cur else '') + cur + '/' if cur else './')
    kv26 = pct(sum(1 for r in valda if r['kon'] == 'K'), sum(1 for r in valda if r['kon'])); ma26 = mean([r['alder'] for r in valda])
    ny26 = pct(sum(1 for r in valda if r.get('status22') != 'omvald'), len(valda)); pv26 = pct(sum(1 for r in valda if r['pv']), len(valda))
    nr = lambda v: str(v).replace('.', ',') if v is not None else '–'
    body = (f'<h1>Statistik om de valda</h1>{stat_nav(None)}<p class="lead">Alla {fmtn(len(valda))} valda i de tre valen 2026: vilka de är, hur de skiljer sig från kandidaterna, hur många som är nya och hur det sett ut sedan 2010. Välj ett område.</p>'
            f'<div class="kpis"><div class="kpi"><div class="v">{nr(kv26)} %</div><div class="l">kvinnor</div></div><div class="kpi"><div class="v">{nr(ma26)}</div><div class="l">medelålder</div></div><div class="kpi"><div class="v">{nr(ny26)} %</div><div class="l">nya sedan 2022</div></div><div class="kpi"><div class="v">{nr(pv26)} %</div><div class="l">invalda på personröster</div></div></div>'
            '<div class="cards"><a class="card" href="../karta/"><b>Karta →</b><span>Kommunfullmäktige på kartan, under Karta i menyn.</span></a>' + ''.join(f'<a class="card" href="{k}/"><b>{t} →</b><span>{d}</span></a>' for k, t, d, _ in STAT) + '</div>')
    write('statistik/index.html', page('Statistik', body, 1, '<a href="../">Sverige</a> › Statistik', built, section='statistik/').replace('__SCRIPT__', ''))
    # ---------- Karta: egen sida i huvudmenyn ----------
    if karta:
        kb = ('<h1>Karta</h1><p class="lead">Alla 290 kommunfullmäktige på kartan. Välj vad kartan ska visa. Hovra eller tryck på en kommun för alla siffror, klicka (eller tryck igen) för att se dess valda.</p>'
              + karta.replace('<h2>Kommunfullmäktige på kartan</h2>', '', 1) +
              '<p class="small muted sans">Andel nya = ledamöter som inte satt i samma fullmäktige efter valet 2022 (matchning på namn, parti och ålder). Källa: Valmyndigheten.</p>')
        write('karta/index.html', page('Karta', kb, 1, '<a href="../">Sverige</a> › Karta', built, section='karta/').replace('__SCRIPT__', ''))
    for k, t, d, html in STAT:
        html = html.replace('"../person/', '"../../person/').replace('"../kommun/', '"../../kommun/').replace('`../kommun/', '`../../kommun/')
        sb = f'<h1>{t}</h1>{stat_nav(k)}<p class="lead">{d}</p>{html}'
        write(f'statistik/{k}/index.html', page(t + ' – statistik', sb, 2, f'<a href="../../">Sverige</a> › <a href="../">Statistik</a> › {t}', built, section='statistik/').replace('__SCRIPT__', ''))

    # ---------- indexsidor för län och kommuner ----------
    lan_items2 = [(k, lanNamn.get(k, k), rings) for k, rings in (DATA.get('granser', {}).get('lan') or {}).items()]
    body = (f'<h1>Län och regioner</h1><p class="lead">Välj ett län för regionfullmäktige, riksdagsledamöter från länet och länets kommuner.</p>'
            f'<div class="maprow"><div>{svg_map(sorted(lan_items2, key=lambda x: x[1]), lambda k: f"{k}/", 1)}</div><div><div class="chips">' +
            ''.join(f'<a class="chip" href="{k}/">{esc(nm)} <span class="muted small">{sum(1 for r in valda if r["vt"]=="RF" and r["valomrkod"]==k)} + {sum(1 for r in valda if r["vt"]=="RD" and r["lan"]==k)}</span></a>' for k, nm, _ in sorted(lan_items2, key=lambda x: x[1])) +
            '</div><p class="small muted sans">Siffrorna: ledamöter i regionfullmäktige + riksdagsledamöter från länet.</p></div></div>')
    write('lan/index.html', page('Län och regioner', body, 1, '<a href="../">Sverige</a> › Län', built, section='lan/').replace('__SCRIPT__', ''))
    by_l = defaultdict(list)
    for nm_, kk in komKod.items(): by_l[kk[:2]].append((nm_, kk))
    body = ('<h1>Alla kommuner</h1><p class="lead">Kommunfullmäktige 2026–2030 i alla 290 kommuner. Sök eller välj län.</p>'
            '<input class="filter" type="search" id="kq" placeholder="Sök kommun…" oninput="var v=this.value.toLowerCase();document.querySelectorAll(\'#kl a\').forEach(function(a){a.style.display=!v||a.textContent.toLowerCase().indexOf(v)>=0?\'\':\'none\'});document.querySelectorAll(\'#kl h3\').forEach(function(h){var n=h.nextElementSibling;h.style.display=[].some.call(n.querySelectorAll(\'a\'),function(a){return a.style.display!==\'none\'})?\'\':\'none\'})">'
            + subnav([('#l' + lk, lanNamn.get(lk, lk).replace(' län', '')) for lk in sorted(by_l)]) + '<div id="kl">' +
            ''.join(f'<h3 id="l{lk}">{esc(lanNamn.get(lk, lk))}</h3><div class="chips">' + ''.join(f'<a class="chip" href="{slugify(nm_)}/">{esc(nm_)} <span class="muted small">{sum(1 for r in valda if r["vt"]=="KF" and r["valomrkod"]==kk)}</span></a>' for nm_, kk in sorted(v, key=lambda x: x[0])) + '</div>' for lk, v in sorted(by_l.items())) + '</div>')
    write('kommun/index.html', page('Alla kommuner', body, 1, '<a href="../">Sverige</a> › Kommuner', built, section='kommun/').replace('__SCRIPT__', ''))
    # robots/sitemap-light
    write('robots.txt', 'User-agent: *\nAllow: /\n')
    print(f'Skrev {out}: {len(valda)} personsidor, 290 kommuner, 21 län, {len(all_p)} partier.')

if __name__ == '__main__':
    main()
