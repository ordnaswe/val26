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
<footer><p>Källa: Valmyndighetens fastställda resultat för valen den 13 september 2026 (valda ledamöter, ersättare, valgrund, personröster) och Valmyndighetens kandidatfil (folkbokföringskommun). Ålder, kön och titel: Valmyndighetens kandidatfil 2026. Historik: Valmyndighetens filer över ursprungligt valda 2010–2022 (namnen gallrade av Valmyndigheten före 2022). Ny/omvald: matchning på namn, parti och ålder mot de valda 2022, en uppskattning. Roller 2022–2026: Plenum. {('Byggd '+esc(built)+'. ') if built else ''}<b>allavalda.se</b> är gjord av Influera Sveriges Sandro Wennberg med hjälp av AI (Anthropic). Valresultatet: <a href="https://www.valutfall.se/">valutfall.se</a>.</p></footer></div>
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
        try: r['jump'] = int(r['listplats']) - r['nr'] if r['listplats'] and r['nr'] else None
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
        for h in by_name.get(fold(r['namn']), []):
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
        for p in rd_by.get(fold(r['namn']), []):
            if r['alder'] and p.get('fodd') and (2026 - p['fodd']) not in (r['alder'], r['alder'] + 1): continue
            prof = rd_profile(p)
            if prof['perioder'] or prof['ersattare']: r['rdp'] = prof; break
        if r['vt'] == 'RD' and r['rdp'] is not None:
            r['status22'] = 'omvald' if 2022 in r['rdp']['perioder'] else ('återkommer' if r['rdp']['perioder'] else r.get('status22'))
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
        if r.get('status22') == 'ny': extra.append('ny')
        if r.get('alder'): extra.append(f"{r['alder']} år")
        if r.get('pr_tot') is not None: extra.append(f"{fmtn(r['pr_tot'])} personröster")
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
        hk = [h for h in hist if h['valtyp'] == 'KF' and h['kommunkod'] == kk and h['ursprunglig'] == '1']
        hrows = []
        for ar in ('2010', '2014', '2018', '2022'):
            hs = [h for h in hk if h['ar'] == ar]
            if hs: hrows.append((ar, len(hs), pct(sum(1 for h in hs if h['kon'] == 'K'), len(hs)), mean([h['alder_i'] for h in hs]), pct(sum(1 for h in hs if h['personvald'] == '1'), len(hs))))
        if kf: hrows.append(('2026', len(kf), pct(sum(1 for r in kf if r['kon'] == 'K'), sum(1 for r in kf if r['kon'])), mean([r['alder'] for r in kf]), pct(sum(1 for r in kf if r['pv']), len(kf))))
        avg22 = sum(1 for h in hk if h['ar'] == '2022' and h.get('avgang'))
        vet = sorted([r for r in kf if r.get('streak', 1) > 1], key=lambda r: (-r['streak'], r['namn']))[:15]
        nya = sum(1 for r in kf if r.get('status22') == 'ny')
        histhtml = ('<h2>Fullmäktige över tid</h2><table><thead><tr><th>Val</th><th class="r">Ledamöter</th><th class="r">Kvinnor %</th><th class="r">Medelålder</th><th class="r">Personvalda %</th></tr></thead><tbody>' +
                    ''.join(f'<tr><td>{ar}</td><td class="r">{n}</td><td class="r">{str(k).replace(".", ",") if k is not None else "–"}</td><td class="r">{str(m).replace(".", ",") if m is not None else "–"}</td><td class="r">{str(p).replace(".", ",") if p is not None else "–"}</td></tr>' for ar, n, k, m, p in hrows) +
                    f'</tbody></table><p class="small muted sans">{nya} av {len(kf)} ledamöter 2026 är nya jämfört med fullmäktige 2022 (uppskattning). {avg22} av ledamöterna som valdes 2022 lämnade sitt uppdrag under mandatperioden.</p>') if hrows else ''
        body = f"""<h1>{esc(nm)}</h1><p class="lead">{len(kf)} ledamöter i kommunfullmäktige, {sum(1 for r in kf if r['pv'])} av dem invalda på personröster. {len(rd)} riksdagsledamöter och {len(rf)} regionledamöter bor i kommunen.</p>
<p class="small sans"><a href="https://www.valutfall.se/kommun/{slug}/">Valresultatet i {esc(nm)} ner på valdistrikt – valutfall.se →</a></p>
<h2>Kommunfullmäktige 2026–2030</h2>{seatbar(kf) if kf else ''}{party_lists(kf, 2, {p: ers_by.get(('KF', kk, p), []) for p in set(r['p'] for r in kf)}) if kf else '<p class="muted">Inga valda i underlaget.</p>'}
{histhtml}
{('<h2>Längst i fullmäktige</h2><ol class="led">' + ''.join(f'<li><a href="../../person/{r["id"]}/">{esc(r["namn"])}</a> <span class="ers">{pf(r["p"])} · {r["streak"]} mandatperioder i rad, sedan {2026 - 4*(r["streak"]-1)}</span></li>' for r in vet) + '</ol>') if vet else ''}
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
        if r['fbk']: fakta.append(('Bor i', f'<a href="../../kommun/{slugify(r["fbk"])}/">{esc(r["fbk"])}</a>' if r['fbk_kod'] else esc(r['fbk'])))
        body = f"""<h1>{esc(r['namn'])}</h1><p class="lead">{pf(r['p'])} {esc(PN.get(r['p'], ''))} · {VT[r['vt']]}{(' · ' + esc(r['omr'])) if r['omr'] else ''}{' · <span class="pv">invald på personröster</span>' if r['pv'] else ''}</p>
<div class="card"><table><tbody>{''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in fakta)}</tbody></table></div>
{('<h2>Fler uppdrag efter valet</h2><ul class="led sans">' + ''.join(f'<li><a href="../../person/{x["id"]}/">{VT[x["vt"]]}{(" – " + esc(x["omr"])) if x["omr"] else ""}</a></li>' for x in others) + '</ul>') if others else ''}
{('<h2>Uppdrag sedan ' + named_years[0] + '</h2><p class="small muted sans">Ursprungligt valda enligt Valmyndigheten. ' + (f'Sitter sin {r["streak"]}:e mandatperiod i rad i ' + VTS[r["vt"]] + '. ' if r['streak'] > 1 else '') + 'Matchning på namn och ålder.</p><table><thead><tr><th>Val</th><th>Församling</th><th>Parti</th><th class="r">Invald som nr</th><th></th></tr></thead><tbody>' + f'<tr><td><b>2026</b></td><td>{VT[r["vt"]]}{(" – " + esc(r["omr"])) if r["omr"] else ""}</td><td>{pf(r["p"])}</td><td class="r">{r["nr"] or "–"}</td><td class="small muted">{"personvald" if r["pv"] else ""}</td></tr>' + ''.join(f'<tr><td>{h["ar"]}</td><td>{VT[h["valtyp"]]}{(" – " + esc(kod2kom.get(h["kommunkod"], ""))) if h["valtyp"]=="KF" else ((" – " + esc(lanNamn.get(h["lankod"], ""))) if h["valtyp"]=="RF" else ((" – " + esc(h["valkrets"])) if h.get("valkrets") else ""))}</td><td>{pf(h["parti"])}{" <span class=\"small muted\">partibyte</span>" if h["parti"] != r["p"] else ""}</td><td class="r">{esc(h["invalsordning"]) or "–"}</td><td class="small muted">{"personvald" if h["personvald"]=="1" else ""}{(", ersättare som gick in" if h.get("ursprunglig")=="0" else "")}{(", avgick " + esc(h["avgang"])) if h.get("avgang") else ""}</td></tr>' for h in r['tl']) + '</tbody></table>') if r.get('tl') else ''}
{('<h2>I riksdagen</h2><div class="card"><table><tbody>' + (f'<tr><th>Mandatperioder som ledamot</th><td>{len(r["rdp"]["perioder"]) + (1 if r["vt"]=="RD" else 0)} ' + ('(inklusive 2026–2030)' if r["vt"]=="RD" else '') + ' – ' + ', '.join(f'{y}–{y+4}' for y in r["rdp"]["perioder"]) + (', 2026–2030' if r["vt"]=="RD" else '') + '</td></tr>' if r['rdp']['perioder'] else '<tr><th>Riksdagen</th><td>Har tjänstgjort som ersättare</td></tr>') + (f'<tr><th>Första gången i kammaren</th><td>{r["rdp"]["forst"]}</td></tr>' if r['rdp']['forst'] else '') + ''.join(f'<tr><th>{esc(roll)}</th><td>{esc(org)} {fr}–{to or "nu"}</td></tr>' for org, roll, fr, to in r['rdp']['roller'][-8:]) + (f'<tr><th>Kommunala uppdrag (biografi)</th><td class="small">{esc(r["rdp"]["kommunalt"])}</td></tr>' if r['rdp']['kommunalt'] else '') + f'</tbody></table><p class="small muted sans">Källa: <a href="https://data.riksdagen.se/personlista/?iid={esc(r["rdp"]["id"])}&utformat=html">Riksdagens öppna data</a>.</p></div>') if r.get('rdp') else ''}
{('<h2>Roller 2022–2026</h2><ul class="led sans">' + ''.join(f'<li>{esc(x)}</li>' for x in rl) + '</ul>') if rl else ''}
{('<h2>Hela listan' + (' – ' + esc(lkey[3]) if lkey else '') + (', ' + esc(full[0].get('VALKRETSNAMN') or '') if full and full[0].get('VALKRETSNAMN') and r['vt'] != 'KF' else '') + f' <span class="muted small">{len(full)} namn</span></h2><p class="small muted sans">Partiets valsedel i ordning. <b>Fet</b> = {esc(r["namn"])}. Markering: vald, ersättare för {esc(r["namn"].split()[0])}, ersättare för annan ledamot.</p><ol class="led">' + ''.join(f'<li{" style=\"font-weight:700\"" if c["KANDIDATNUMMER"] == r.get("kandidatnummer") else ""}>{esc(c["NAMN"])} <span class="ers">{"<span class=\"pv\">vald</span>" if c["KANDIDATNUMMER"] in valda_knr else ("ersättare för " + esc(r["namn"].split()[0]) if c["KANDIDATNUMMER"] in ers_knr else ("ersättare" if c["KANDIDATNUMMER"] in ers_any else ""))}{(" · " + esc(c["FOLKBOKFÖRINGSKOMMUN"])) if c.get("FOLKBOKFÖRINGSKOMMUN") and r["vt"] != "KF" else ""}{(" · " + esc(c.get("ÅLDER_PÅ_VALDAGEN")) + " år") if (c.get("ÅLDER_PÅ_VALDAGEN") or "").strip() else ""}</span></li>' for c in full) + '</ol>') if full else ''}
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
        COLS = {'Riksdagen': '#1f5f8b', 'Regionfullmäktige': '#8a5a9e', 'Kommunfullmäktige': '#2e7d5b', 'Kandidater': '#b0313f'}
        for lab, s in series.items():
            pts = [(sx(i), sy(v)) for i, v in enumerate(s) if v is not None]
            if len(pts) < 2: continue
            c = COLS.get(lab, '#1f5f8b')
            out += f'<path d="{"".join(("M" if j==0 else "L")+f"{x:.1f},{y:.1f}" for j,(x,y) in enumerate(pts))}" fill="none" stroke="{c}" stroke-width="2.4"/>' + ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{c}"/>' for x, y in pts)
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
        agerows += f'<h3>{VT[vt]}: åldersgrupper</h3><div style="font-family:system-ui;font-size:.86rem">' + ''.join(f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0"><div style="width:60px">{lab}</div><div style="flex:1"><div style="height:10px;background:#b0313f;opacity:.55;width:{pct(kc[lab], sum(kc.values())) or 0}%;border-radius:4px"></div><div style="height:10px;background:var(--acc);width:{pct(vc[lab], sum(vc.values())) or 0}%;border-radius:4px;margin-top:2px"></div></div><div style="width:120px;text-align:right">{str(pct(kc[lab], sum(kc.values())) or 0).replace(".", ",")} % / {str(pct(vc[lab], sum(vc.values())) or 0).replace(".", ",")} %</div></div>' for lab, _, _ in AGEGRP) + '</div>'
    kmv += '</tbody></table><p class="small muted sans">Kandidater räknas en gång per val, även om de står på flera listor eller valsedlar. Röd stapel = kandidater, blå = valda.</p><div class="grid3">' + agerows + '</div>'
    # titlar
    vt_t = Counter(r['titel'].lower() for r in valda if r['titel'])
    k_t = Counter(titel(k.get('VALSEDELSUPPGIFT')).lower() for k in {(k['VALTYP'], k['KANDIDATNUMMER']): k for k in allkand if k.get('GILTIG', 'J') == 'J' and k.get('VALSEDELSUPPGIFT')}.values())
    nv, nk = sum(vt_t.values()) or 1, sum(k_t.values()) or 1
    trows = [(t, n, k_t.get(t, 0)) for t, n in vt_t.most_common(25)]
    kmv += '<h2>Vad de valda jobbar med</h2><p class="lead">Titeln de själva angett på valsedeln (fritext, tolkad som första ledet som inte är en ort). Index över 1 betyder att titeln är vanligare bland de valda än bland kandidaterna.</p><table><thead><tr><th>Titel</th><th class="r">Valda</th><th class="r">Andel valda</th><th class="r">Andel kandidater</th><th class="r">Index</th></tr></thead><tbody>' + ''.join(f'<tr><td>{esc(t[:1].upper()+t[1:])}</td><td class="r">{n}</td><td class="r">{str(pct(n, nv)).replace(".", ",")} %</td><td class="r">{str(pct(k, nk)).replace(".", ",")} %</td><td class="r"><b>{str(round((n/nv)/(k/nk), 2)).replace(".", ",") if k else "–"}</b></td></tr>' for t, n, k in trows) + '</tbody></table>'
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
    # listklättrare
    jumps = sorted([r for r in valda if r.get('jump') and r['jump'] > 0], key=lambda r: -r['jump'])[:15]
    if jumps: fn += '<h2>Största listklättrarna</h2><p class="lead">Kandidater som tack vare personröster blev valda långt före sin listplats.</p><table><thead><tr><th>Namn</th><th>Parti</th><th>Område</th><th class="r">Listplats → mandat</th></tr></thead><tbody>' + ''.join(f'<tr><td><a href="../person/{r["id"]}/">{esc(r["namn"])}</a></td><td>{pf(r["p"])}</td><td>{esc(r["omr"] or "")}</td><td class="r">{r["listplats"]} → {r["nr"]}</td></tr>' for r in jumps) + '</tbody></table>'
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
function km(m){{const v=Object.values(KM).map(x=>x[m]).filter(x=>x!=null);const lo=Math.min(...v),hi=Math.max(...v);document.querySelectorAll('#kmap path').forEach(p=>{{const x=KM[p.dataset.k];const t=x&&x[m]!=null?(x[m]-lo)/((hi-lo)||1):null;p.style.fill=t==null?'':`rgba(31,95,139,${{(0.12+0.88*t).toFixed(2)}})`;p.querySelector('title').textContent=x.n+': '+String(x[m]).replace('.',',');}});
 document.getElementById('kleg').textContent=LAB[m]+': ljus '+String(lo).replace('.',',')+' – mörk '+String(hi).replace('.',',')+'. Klicka på en kommun.';
 const s=Object.values(KM).filter(x=>x[m]!=null).sort((a,b)=>b[m]-a[m]);document.getElementById('ktop').innerHTML='<h3 style="margin-top:0">Högst</h3>'+s.slice(0,8).map(x=>`<div><a href="../kommun/${{x.s}}/">${{x.n}}</a> ${{String(x[m]).replace('.',',')}}</div>`).join('')+'<h3>Lägst</h3>'+s.slice(-8).reverse().map(x=>`<div><a href="../kommun/${{x.s}}/">${{x.n}}</a> ${{String(x[m]).replace('.',',')}}</div>`).join('');
 document.querySelectorAll('#km .chip').forEach(c=>c.style.borderColor=c.dataset.m===m?'var(--acc)':'');}}
document.querySelectorAll('#km .chip').forEach(c=>c.onclick=()=>km(c.dataset.m));km('kv');</script>'''
    else: karta = ''
    if len(named_years) > 1:
        tn = '<h2>Hur länge har de suttit?</h2><p class="lead">Antal mandatperioder i rad i samma församling, räknat bakåt till ' + named_years[0] + '. Matchning på namn och ålder.</p><table><thead><tr><th>Församling</th>' + ''.join(f'<th class="r">{k} {"period" if k==1 else "perioder"}</th>' for k in range(1, len(named_years)+2)) + '</tr></thead><tbody>'
        for vt in ('RD', 'RF', 'KF'):
            vs = [r for r in valda if r['vt'] == vt]; c = Counter(r.get('streak', 1) for r in vs)
            tn += f'<tr><td>{VT[vt]}</td>' + ''.join(f'<td class="r">{str(pct(c[k], len(vs))).replace(".", ",")} %</td>' for k in range(1, len(named_years)+2)) + '</tr>'
        tn += '</tbody></table>'
        fn = tn + fn
    rdv = [r for r in valda if r['vt'] == 'RD']
    if rdh and rdv:
        c = Counter(len((r.get('rdp') or {}).get('perioder', [])) for r in rdv)
        tr = '<h2>Erfarenhet i riksdagen</h2><p class="lead">Hur många mandatperioder de valda 2026 redan suttit i riksdagen, enligt Riksdagens öppna data (exakt, från 1994).</p><table><thead><tr><th>Parti</th><th class="r">Nya i riksdagen</th><th class="r">1 period</th><th class="r">2–3 perioder</th><th class="r">4+ perioder</th><th class="r">Snitt</th></tr></thead><tbody>'
        for p in PIDS + ['Alla']:
            vs = [r for r in rdv if p == 'Alla' or r['p'] == p]
            if not vs: continue
            n = [len((r.get('rdp') or {}).get('perioder', [])) for r in vs]
            tr += f'<tr><td>{pf(p) if p != "Alla" else "<b>Alla</b>"}</td><td class="r">{sum(1 for x in n if x == 0)}</td><td class="r">{sum(1 for x in n if x == 1)}</td><td class="r">{sum(1 for x in n if 2 <= x <= 3)}</td><td class="r">{sum(1 for x in n if x >= 4)}</td><td class="r">{str(round(sum(n)/len(n), 1)).replace(".", ",")}</td></tr>'
        tr += '</tbody></table>'
        ex = [r for r in valda if r['vt'] != 'RD' and r.get('rdp') and r['rdp']['perioder']]
        if ex: tr += f'<h3>Före detta riksdagsledamöter i region- och kommunfullmäktige ({len(ex)})</h3><ol class="led">' + ''.join(f'<li><a href="../person/{r["id"]}/">{esc(r["namn"])}</a> <span class="ers">{pf(r["p"])} · {VTS[r["vt"]]} {esc(r["omr"] or "")} · riksdagen {r["rdp"]["perioder"][0]}–{r["rdp"]["perioder"][-1]+4}</span></li>' for r in sorted(ex, key=lambda r: -len(r["rdp"]["perioder"]))[:40]) + '</ol>'
        fn = tr + fn
    sec = karta + utv + kmv + fn + sec
    body = f'<h1>Statistik om de valda</h1><p class="lead">Alla {fmtn(len(valda))} valda i de tre valen 2026: vilka de är, hur de skiljer sig från kandidaterna, hur många som är nya och hur det sett ut sedan 2010.</p>{sec}'
    write('statistik/index.html', page('Statistik', body, 1, '<a href="../">Sverige</a> › Statistik', built).replace('__SCRIPT__', ''))
    # robots/sitemap-light
    write('robots.txt', 'User-agent: *\nAllow: /\n')
    print(f'Skrev {out}: {len(valda)} personsidor, 290 kommuner, 21 län, {len(all_p)} partier.')

if __name__ == '__main__':
    main()
