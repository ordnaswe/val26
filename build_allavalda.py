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
import argparse, csv, json, os, re, unicodedata
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
    with open(path, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f, delimiter=delim))
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
ol.led{margin:4px 0 10px;padding-left:24px;font-family:system-ui;font-size:.92rem} ol.led li{padding:2px 0} ol.led a{text-decoration:none;color:var(--ink)} ol.led a:hover{color:var(--acc2)} .ers{color:var(--ink3);font-size:.82rem;margin-left:6px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:4px 0} .bar span{display:block;height:100%}
.crumb{font:.8rem system-ui;color:var(--ink3);margin:8px 0 0} .crumb a{color:var(--ink3);text-decoration:none} .crumb a:hover{color:var(--acc2)}
footer{padding-top:24px;margin-top:28px;border-top:1px solid var(--line);color:var(--ink3);font:.8rem system-ui}
.pv{color:var(--acc2)} .zoom{font:.8rem system-ui;color:var(--ink3);margin:6px 0 0}
@media(max-width:640px){.wrap{padding:0 12px 48px} h1{font-size:1.5rem} table{font-size:.84rem} th,td{padding:6px 5px}}
"""

def page(title, body, depth=0, crumb='', built=''):
    root = '../'*depth
    return f"""<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} – allavalda.se</title><meta name="description" content="{esc(title)} – alla folkvalda i Sverige efter valet 2026: riksdag, regionfullmäktige och kommunfullmäktige."><link rel="stylesheet" href="{root}style.css"></head>
<body><div class="wrap"><header class="top"><a class="brand" href="{root}">alla<span>valda</span>.se</a><nav class="main"><a href="{root}">Sök</a><a href="{root}parti/">Partier</a><a href="{root}statistik/">Statistik</a><a href="https://www.valutfall.se/">valutfall.se</a></nav></header>
{('<div class="crumb">'+crumb+'</div>') if crumb else ''}
{body}
<footer><p>Källa: Valmyndighetens fastställda resultat för valen den 13 september 2026 (valda ledamöter, ersättare, valgrund, personröster) och Valmyndighetens kandidatfil (folkbokföringskommun). Roller 2022–2026: Plenum. Kön och ålder ingår inte i Valmyndighetens öppna filer. {('Byggd '+esc(built)+'. ') if built else ''}<b>allavalda.se</b> är gjord av Influera Sveriges Sandro Wennberg med hjälp av AI (Anthropic). Valresultatet: <a href="https://www.valutfall.se/">valutfall.se</a>.</p></footer></div>
__SCRIPT__</body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='public/data.json'); ap.add_argument('--out', default='public_allavalda')
    ap.add_argument('--valda', default='data/valda.csv'); ap.add_argument('--ersattare', default='data/ersattare.csv')
    ap.add_argument('--personroster', default='data/personroster.csv'); ap.add_argument('--kandidaturer', default='data/kandidaturer.csv')
    ap.add_argument('--valkrets', default='data/valkrets.csv'); ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    a = ap.parse_args()
    d = json.load(open(a.data, encoding='utf-8'))
    komKod = d['komKod']; kod2kom = {v: k for k, v in komKod.items()}; lanKod = d['lanKod']; lanNamn = {v: k for k, v in lanKod.items()}
    COL = {p['id']: p['color'] for p in d['parties']}; PN = {p['id']: p['namn'] for p in d['parties']}
    built = (d.get('meta') or {}).get('built', '')
    def col(p): return COL.get(p, '#7a8390')
    def pf(p): return f'<span class="pf" style="background:{col(p)}">{esc(p)}</span>'
    valda = read_csv(a.valda)
    # säkerhetsnät om valda.csv har dubbletter (samma mandat på valområdes- och valkretsnivå)
    _seen = {}
    for r in valda:
        k = (r['valtyp'], r['valomrkod'], r.get('kandidatnummer') or r['namn'])
        if k not in _seen or (r.get('valkretskod') not in ('', r['valomrkod']) and _seen[k].get('valkretskod') in ('', _seen[k]['valomrkod'])): _seen[k] = r
    valda = list(_seen.values())
    if not valda: raise SystemExit('data/valda.csv saknas – kör valda.py först (Deploya live, slutliga).')
    ers = read_csv(a.ersattare); pers = read_csv(a.personroster)
    ers = list({(e['valtyp'], e['valomrkod'], e.get('ledamot_kandidatnummer'), e.get('kandidatnummer') or e['namn']): e for e in ers}.values())
    pers = list({(r['valtyp'], r['valomrkod'], r.get('kandidatnummer')): r for r in pers}.values())
    kand = {}; lists = defaultdict(list); knr_lists = defaultdict(list)
    for r in read_csv(a.kandidaturer, ';'):
        if r.get('GILTIG', 'J') != 'J': continue
        kand.setdefault((r.get('VALTYP'), r.get('KANDIDATNUMMER')), r)
        lk_ = (r['VALTYP'], r['VALOMRÅDESKOD'], r.get('VALKRETSKOD') or '', r['PARTIBETECKNING'])
        lists[lk_].append(r); knr_lists[(r['VALTYP'], r['VALOMRÅDESKOD'], r['KANDIDATNUMMER'])].append(lk_)
    for v in lists.values(): v.sort(key=lambda x: int(num(x.get('ORDNING')) or 0))
    vk2lan = {}; kom2vk = {}
    for r in read_csv(a.valkrets): kom2vk[r['kommunkod']] = r['valkretskod']; vk2lan.setdefault(r['valkretskod'], r['kommunkod'][:2])
    roles = defaultdict(list)
    for r in read_csv(a.nyckelpersoner):
        roles[(fold(r['namn']), r.get('parti_abbr'))].append(f"{r['organ']} ({r['roll']}), {r['omrade']}")

    # ---- normalisera ----
    for r in valda:
        r['vt'] = r['valtyp']; r['p'] = r['parti']; r['id'] = f"{r['vt']}-{r.get('kandidatnummer') or slugify(r['namn'])}"
        r['pr'] = num(r.get('personroster')); r['nr'] = int(num(r.get('invalsordning')) or 0)
        r['pv'] = 'person' in (r.get('valgrund') or '').lower(); r['kval'] = r.get('kvalificerad') == 'Ja'
        k = kand.get((r['vt'], r.get('kandidatnummer'))) or {}
        r['fbk'] = (k.get('FOLKBOKFÖRINGSKOMMUN') or '').strip(); r['fbk_kod'] = komKod.get(r['fbk'], '')
        r['listplats'] = (k.get('ORDNING') or '').strip()
        if r['vt'] == 'KF': r['kom'] = r['valomrkod']; r['lan'] = r['valomrkod'][:2]
        elif r['vt'] == 'RF': r['kom'] = r['fbk_kod']; r['lan'] = r['valomrkod']
        else: r['kom'] = r['fbk_kod']; r['lan'] = vk2lan.get(r.get('valkretskod'), r['fbk_kod'][:2])
        r['omr'] = r.get('valkretsnamn') if r['vt'] == 'RD' else r.get('valomrnamn')
        r['slug'] = slugify(r['namn'])
    ers_by = defaultdict(list)
    for e in ers: ers_by[(e['valtyp'], e['valomrkod'], e['parti'])].append(e)
    valda_knr_by = defaultdict(set); ers_knr_by = defaultdict(set)
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
        if r['pr'] is not None: extra.append(f"{fmtn(r['pr'])} personröster")
        if show_omr: extra.append(esc(r['omr'] or ''))
        return f'<li><a href="{person_link(r, depth)}">{esc(r["namn"])}</a> <span class="ers">{" · ".join(extra)}</span></li>'
    def party_lists(rows, depth, with_ers=None, show_omr=False):
        byp = defaultdict(list)
        for r in rows: byp[r['p']].append(r)
        order = sorted(byp, key=lambda p: (-len(byp[p]), p))
        html = ''
        for p in order:
            rs = sorted(byp[p], key=lambda r: (r['nr'] or 999, r['namn']))
            html += f'<h3>{pf(p)} {esc(PN.get(p, rs[0].get("partibeteckning") or p))} <span class="muted small">{len(rs)} mandat</span></h3><ol class="led">{"".join(led_item(r, depth, show_omr) for r in rs)}</ol>'
            if with_ers:
                e = sorted(with_ers.get(p, []), key=lambda x: (int(num(x.get('ersattarordning')) or 0), x['namn']))
                names = []; seen = set()
                for x in e:
                    if x['namn'] not in seen: seen.add(x['namn']); names.append(x['namn'])
                if names: html += f'<p class="small muted" style="margin:-4px 0 8px;font-family:system-ui">Ersättare: {esc(", ".join(names[:12]))}{" …" if len(names) > 12 else ""}</p>'
        return html
    def seatbar(rows):
        c = Counter(r['p'] for r in rows); tot = sum(c.values()) or 1
        ps = [p for p in PIDS if c[p]] + sorted([p for p in c if p not in PIDS], key=lambda p: -c[p])
        spans = ''.join('<span style="width:%.2f%%;background:%s" title="%s %d"></span>' % (100*c[p]/tot, col(p), esc(p), c[p]) for p in ps)
        lab = ' · '.join('%s %d' % (p, c[p]) for p in ps)
        return '<div class="bar">%s</div><p class="small muted" style="margin:2px 0 8px;font-family:system-ui">%s</p>' % (spans, lab)
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
q.addEventListener('input',async()=>{const v=fold(q.value.trim());if(v.length<2){hits.innerHTML='';return;}const I=await load();const r=I.filter(x=>x.f.includes(v)).slice(0,30);
 hits.innerHTML=r.map(x=>`<li><a href="${x.u}">${x.n}</a> <span class="m">${x.p} · ${x.v} · ${x.o}</span></li>`).join('')||'<li class="m">Inga träffar.</li>';});
</script>"""
    write('index.html', page('Alla folkvalda i Sverige', body, 0, '', built).replace('__SCRIPT__', script))
    # sökindex
    idx = [{'n': r['namn'], 'p': r['p'], 'v': VT[r['vt']], 'o': r['omr'] or '', 'u': f'person/{r["id"]}/', 'f': fold(r['namn'] + ' ' + (r['omr'] or '') + ' ' + r['p'] + ' ' + (r['fbk'] or ''))} for r in valda]
    for kk, nm in sorted(kod2kom.items(), key=lambda x: x[1]): idx.append({'n': nm, 'p': 'Kommun', 'v': 'Kommunfullmäktige', 'o': lanNamn.get(kk[:2], ''), 'u': f'kommun/{slugify(nm)}/', 'f': fold('kommun ' + nm)})
    with open(os.path.join(out, 'sok.json'), 'w', encoding='utf-8') as f: json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))

    # ---- län ----
    kom_rings = d.get('granser', {}).get('kommun') or {}
    for lk, lname in sorted(lanNamn.items()):
        rf = [r for r in valda if r['vt'] == 'RF' and r['valomrkod'] == lk]
        rd = [r for r in valda if r['vt'] == 'RD' and r['lan'] == lk]
        koms = sorted([(kk, nm) for nm, kk in komKod.items() if kk[:2] == lk], key=lambda x: x[1])
        items = [(kk, nm, kom_rings[kk]) for kk, nm in koms if kk in kom_rings]
        rname = 'Region Gotland' if lk == '09' else ('Västra Götalandsregionen' if lk == '14' else 'Region ' + lname.replace(' län', '').replace('s län', ''))
        body = f"""<h1>{esc(lname)}</h1><p class="lead">{len(rd)} riksdagsledamöter från länet, {len(rf)} ledamöter i {esc(rname)} och {len(koms)} kommuner.</p>
<div class="maprow"><div>{svg_map(items, lambda k: f'../../kommun/{slugify(kod2kom.get(k, k))}/', 2)}</div><div><h2 style="margin-top:0">Kommuner</h2><div class="chips">{''.join(f'<a class="chip" href="../../kommun/{slugify(nm)}/">{esc(nm)}</a>' for kk, nm in koms)}</div></div></div>
<h2>Riksdagsledamöter från {esc(lname)}</h2>{seatbar(rd) if rd else ''}{party_lists(rd, 2, show_omr=True) if rd else '<p class="muted">Inga.</p>'}
{('<h2>'+esc(rname)+'</h2>'+seatbar(rf)+party_lists(rf, 2, {p: [e for e in ers if e["valtyp"]=="RF" and e["valomrkod"]==lk and e["parti"]==p] for p in set(r["p"] for r in rf)})) if rf else ('<h2>Regionfullmäktige</h2><p class="muted">Gotland har inget regionval; regionfullmäktige är kommunfullmäktige.</p>' if lk=='09' else '')}"""
        write(f'lan/{lk}/index.html', page(lname, body, 2, f'<a href="../../">Sverige</a> › {esc(lname)}', built).replace('__SCRIPT__', ''))

    # ---- kommuner ----
    for nm, kk in sorted(komKod.items(), key=lambda x: x[1]):
        kf = [r for r in valda if r['vt'] == 'KF' and r['valomrkod'] == kk]
        rf = [r for r in valda if r['vt'] == 'RF' and r['kom'] == kk]
        rd = [r for r in valda if r['vt'] == 'RD' and r['kom'] == kk]
        slug = slugify(nm); lk = kk[:2]
        body = f"""<h1>{esc(nm)}</h1><p class="lead">{len(kf)} ledamöter i kommunfullmäktige, {sum(1 for r in kf if r['pv'])} av dem invalda på personröster. {len(rd)} riksdagsledamöter och {len(rf)} regionledamöter bor i kommunen.</p>
<p class="small sans"><a href="https://www.valutfall.se/kommun/{slug}/">Valresultatet i {esc(nm)} ner på valdistrikt – valutfall.se →</a></p>
<h2>Kommunfullmäktige 2026–2030</h2>{seatbar(kf) if kf else ''}{party_lists(kf, 2, {p: ers_by.get(('KF', kk, p), []) for p in set(r['p'] for r in kf)}) if kf else '<p class="muted">Inga valda i underlaget.</p>'}
{('<h2>Riksdagsledamöter som bor i '+esc(nm)+'</h2>'+party_lists(rd, 2, show_omr=True)) if rd else ''}
{('<h2>Regionledamöter som bor i '+esc(nm)+'</h2>'+party_lists(rf, 2)) if rf else ''}"""
        write(f'kommun/{slug}/index.html', page(nm, body, 2, f'<a href="../../">Sverige</a> › <a href="../../lan/{lk}/">{esc(lanNamn.get(lk, lk))}</a> › {esc(nm)}', built).replace('__SCRIPT__', ''))

    # ---- partier ----
    all_p = Counter(r['p'] for r in valda)
    body = f"""<h1>Partier</h1><p class="lead">Alla partier med minst ett mandat i något av de tre valen.</p><table><thead><tr><th>Parti</th><th class="r">Riksdag</th><th class="r">Region</th><th class="r">Kommun</th><th class="r">Totalt</th></tr></thead><tbody>{''.join(f'<tr><td><a href="{slugify(p)}/">{pf(p)} {esc(PN.get(p, p))}</a></td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="RD")}</td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="RF")}</td><td class="r">{sum(1 for r in valda if r["p"]==p and r["vt"]=="KF")}</td><td class="r">{c}</td></tr>' for p, c in all_p.most_common())}</tbody></table>"""
    write('parti/index.html', page('Partier', body, 1, '<a href="../">Sverige</a> › Partier', built).replace('__SCRIPT__', ''))
    for p, c in all_p.most_common():
        rows = [r for r in valda if r['p'] == p]; pvp = sum(1 for r in rows if r['pv'])
        sec = ''
        for vt in ('RD', 'RF', 'KF'):
            rs = [r for r in rows if r['vt'] == vt]
            if not rs: continue
            byo = defaultdict(list)
            for r in rs: byo[r['omr'] or ''].append(r)
            sec += f'<h2>{VT[vt]} <span class="muted small">{len(rs)} mandat</span></h2>' + ''.join(f'<h3>{esc(o)} <span class="muted small">{len(byo[o])}</span></h3><ol class="led">{"".join(led_item(r, 2) for r in sorted(byo[o], key=lambda r: (r["nr"] or 999, r["namn"])))}</ol>' for o in sorted(byo))
        body = f'<h1>{pf(p)} {esc(PN.get(p, rows[0].get("partibeteckning") or p))}</h1><p class="lead">{fmtn(c)} valda ledamöter, {pvp} ({round(100*pvp/c)} %) på personröster.</p>{sec}'
        write(f'parti/{slugify(p)}/index.html', page(PN.get(p, p), body, 2, f'<a href="../../">Sverige</a> › <a href="../">Partier</a> › {esc(PN.get(p, p))}', built).replace('__SCRIPT__', ''))

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
        ers_knr = {x.get('kandidatnummer') for x in e}
        ers_any = ers_knr_by.get((r['vt'], r['valomrkod'], r['p']), set())
        fakta = [('Vald till', f"{VT[r['vt']]}{(' – ' + esc(r['omr'])) if r['omr'] else ''}"), ('Parti', f"{pf(r['p'])} {esc(PN.get(r['p'], r.get('partibeteckning') or ''))}"),
                 ('Invald som nummer', f"{r['nr']} för partiet" + (f" (listplats {esc(r['listplats'])})" if r['listplats'] else '')), ('Valgrund', esc(r.get('valgrund') or '–'))]
        if r['pr'] is not None: fakta.append(('Personröster', fmtn(r['pr']) + (f" ({str(r.get('andel_personroster')).replace('.', ',')} % av partiets röster{', klarade personröstspärren' if r['kval'] else ''})" if r.get('andel_personroster') else '')))
        if r['fbk']: fakta.append(('Bor i', f'<a href="../../kommun/{slugify(r["fbk"])}/">{esc(r["fbk"])}</a>' if r['fbk_kod'] else esc(r['fbk'])))
        body = f"""<h1>{esc(r['namn'])}</h1><p class="lead">{pf(r['p'])} {esc(PN.get(r['p'], ''))} · {VT[r['vt']]}{(' · ' + esc(r['omr'])) if r['omr'] else ''}{' · <span class="pv">invald på personröster</span>' if r['pv'] else ''}</p>
<div class="card"><table><tbody>{''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in fakta)}</tbody></table></div>
{('<h2>Fler uppdrag efter valet</h2><ul class="led sans">' + ''.join(f'<li><a href="../../person/{x["id"]}/">{VT[x["vt"]]}{(" – " + esc(x["omr"])) if x["omr"] else ""}</a></li>' for x in others) + '</ul>') if others else ''}
{('<h2>Roller 2022–2026</h2><ul class="led sans">' + ''.join(f'<li>{esc(x)}</li>' for x in rl) + '</ul>') if rl else ''}
{('<h2>Hela listan' + (' – ' + esc(lkey[3]) if lkey else '') + (', ' + esc(full[0].get('VALKRETSNAMN') or '') if full and full[0].get('VALKRETSNAMN') and r['vt'] != 'KF' else '') + f' <span class="muted small">{len(full)} namn</span></h2><p class="small muted sans">Partiets valsedel i ordning. <b>Fet</b> = {esc(r["namn"])}. Markering: vald, ersättare för {esc(r["namn"].split()[0])}, ersättare för annan ledamot.</p><ol class="led">' + ''.join(f'<li{" style=\"font-weight:700\"" if c["KANDIDATNUMMER"] == r.get("kandidatnummer") else ""}>{esc(c["NAMN"])} <span class="ers">{"<span class=\"pv\">vald</span>" if c["KANDIDATNUMMER"] in valda_knr else ("ersättare för " + esc(r["namn"].split()[0]) if c["KANDIDATNUMMER"] in ers_knr else ("ersättare" if c["KANDIDATNUMMER"] in ers_any else ""))}{(" · " + esc(c["FOLKBOKFÖRINGSKOMMUN"])) if c.get("FOLKBOKFÖRINGSKOMMUN") and r["vt"] != "KF" else ""}</span></li>' for c in full) + '</ol>') if full else ''}
{('<h2>Ersättare för ' + esc(r['namn']) + '</h2><ol class="led">' + ''.join(f'<li>{esc(x["namn"])} <span class="ers">{esc(x.get("valgrund") or "")}</span></li>' for x in sorted(e, key=lambda x: int(num(x.get("ersattarordning")) or 0))) + '</ol>') if e else ''}
<p class="small sans"><a href="../../{'kommun/' + slugify(r['valomrnamn']) + '/' if r['vt']=='KF' else 'lan/' + r['lan'] + '/'}">Alla valda i {esc(r['valomrnamn'] if r['vt']=='KF' else lanNamn.get(r['lan'], ''))} →</a></p>"""
        crumb = f'<a href="../../">Sverige</a> › <a href="../../parti/{slugify(r["p"])}/">{esc(PN.get(r["p"], r["p"]))}</a> › {esc(r["namn"])}'
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
        prs = sorted([r for r in rs if r['pr'] is not None], key=lambda r: -r['pr'])[:10]
        sec += f'<h2>{VT[vt]} <span class="muted small">{fmtn(len(rs))} ledamöter</span></h2><div class="grid2"><div><h3>Mandat per parti</h3>{barchart([(pf(p)+" "+esc(PN.get(p,p)), v) for p, v in top], None, color=None)}</div><div><h3>Andel invalda på personröster</h3>{barchart([(pf(p), v) for p, v in sorted(pvs, key=lambda x: -x[1])], None, fmt=lambda v: f"{v} %")}</div></div>'
        if prs: sec += '<h3>Flest personröster</h3><table><thead><tr><th>Namn</th><th>Parti</th><th>Område</th><th class="r">Personröster</th></tr></thead><tbody>' + ''.join(f'<tr><td><a href="../person/{r["id"]}/">{esc(r["namn"])}</a></td><td>{pf(r["p"])}</td><td>{esc(r["omr"] or "")}</td><td class="r">{fmtn(r["pr"])}</td></tr>' for r in prs) + '</tbody></table>'
    rd = [r for r in valda if r['vt'] == 'RD']; fbk = Counter(r['fbk'] for r in rd if r['fbk'])
    missade = [r for r in pers if r.get('kvalificerad') == 'Ja' and r.get('invald') != 'Ja']
    sec += f'<h2>Var riksdagsledamöterna bor</h2><p class="lead">{len(fbk)} kommuner har minst en ledamot i riksdagen. {290-len(fbk)} kommuner har ingen.</p>{barchart(fbk.most_common(15), None)}'
    if missade: sec += f'<h2>Klarade personröstspärren men kom inte in</h2><p class="lead">{len(missade)} kandidater fick tillräckligt många personröster men partiet hade inte mandat nog. De tio med flest röster:</p><table><thead><tr><th>Namn</th><th>Parti</th><th>Val</th><th>Område</th><th class="r">Personröster</th></tr></thead><tbody>' + ''.join(f'<tr><td>{esc(r["namn"])}</td><td>{pf(r["parti"])}</td><td>{r["valtyp"]}</td><td>{esc(r.get("valomrnamn") or "")}</td><td class="r">{fmtn(num(r["personroster"]) or 0)}</td></tr>' for r in sorted(missade, key=lambda r: -(num(r["personroster"]) or 0))[:10]) + '</tbody></table>'
    body = f'<h1>Statistik om de valda</h1><p class="lead">Alla {fmtn(len(valda))} valda i de tre valen. Kön och ålder ingår inte i Valmyndighetens öppna filer och visas därför inte.</p>{sec}'
    write('statistik/index.html', page('Statistik', body, 1, '<a href="../">Sverige</a> › Statistik', built).replace('__SCRIPT__', ''))
    # robots/sitemap-light
    write('robots.txt', 'User-agent: *\nAllow: /\n')
    print(f'Skrev {out}: {len(valda)} personsidor, 290 kommuner, 21 län, {len(all_p)} partier.')

if __name__ == '__main__':
    main()
