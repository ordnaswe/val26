#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_kommun.py — fördjupad kommunsida på valutfall.se: public/kommun/<slug>/index.html

Allt om en kommun ner på valdistrikt: distriktskarta (riksdag/region/kommun, andel, förändring,
valdeltagande, största parti), resultat och mandat med styre, historik sedan 1973, röstsplittring
mellan de tre valen per distrikt, demografi mot partistöd inom kommunen, samt valda och ledande
politiker. Självständig HTML (endast standardbibliotek i bygget).

    python3 build_kommun.py --kommun 0120 --slug varmdo
Läser: public/data.json, data/distrikt_2026.csv.gz (distrikt_slutligt.py), data/valdistrikt-riket-2026.zip
(geometri), data/mandat_slutligt.csv, data/styre_kommun_2022.csv, data/valdeltagande_2026.csv,
nyckelpersoner.csv, data/valda.csv (om den finns), data/slutligt.json.
"""
import argparse, csv, gzip, io, json, math, os, re, zipfile
from collections import defaultdict

PIDS = ['V', 'S', 'MP', 'C', 'L', 'KD', 'M', 'SD']
LEFT = ['S', 'V', 'MP', 'C']; RIGHT = ['M', 'KD', 'L', 'SD']
NOT_PARTY = ('röstberättigade', 'summa', 'antal', 'valdeltagande', 'totalt', 'blank', 'ogiltig')

def num(x):
    try:
        v = float(str(x).replace(',', '.')); return None if math.isnan(v) else v
    except Exception: return None

def read_csv(path, gz=False):
    if not path or not os.path.exists(path): return []
    f = gzip.open(path, 'rt', encoding='utf-8-sig', newline='') if gz else open(path, encoding='utf-8-sig', newline='')
    with f: return list(csv.DictReader(f))

def wpearson(xs, ys, ws):
    sw = sum(ws)
    if sw <= 0 or len(xs) < 6: return None
    mx = sum(w*x for x, w in zip(xs, ws))/sw; my = sum(w*y for y, w in zip(ys, ws))/sw
    cov = sum(w*(x-mx)*(y-my) for x, y, w in zip(xs, ys, ws))/sw
    vx = sum(w*(x-mx)**2 for x, w in zip(xs, ws))/sw; vy = sum(w*(y-my)**2 for y, w in zip(ys, ws))/sw
    return cov/math.sqrt(vx*vy) if vx > 0 and vy > 0 else None

def status_text(final, official):
    def lab(k, n):
        v = final.get(k)
        return f"<b>{n}:</b> slutligt" + (f" ({v})" if isinstance(v, str) else "") if v else f"<b>{n}:</b> preliminärt"
    t = " · ".join([lab('RD', 'Riksdag'), lab('RF', 'Region'), lab('KF', 'Kommun')])
    t += ". Alla tre valen är fastställda." if all(final.get(k) for k in ('RD', 'RF', 'KF')) else ". Tills alla tre valen är slutligt fastställda kan andelar och mandat ändras något."
    if official: t += " Mandaten är Valmyndighetens fastställda fördelning."
    return t

def geometry(zip_path, kommunkod):
    """Distriktspolygoner för kommunen ur Valmyndighetens GeoJSON (SWEREF99 TM) -> lokalt viewBox."""
    if not os.path.exists(zip_path): return {}
    with zipfile.ZipFile(zip_path) as z:
        name = [n for n in z.namelist() if n.endswith(('.geojson', '.json'))][0]
        g = json.load(io.TextIOWrapper(z.open(name), encoding='utf-8'))
    feats = [f for f in g['features'] if str(f['properties'].get('Kommunkod', '')) == kommunkod]
    polys = {}
    for f in feats:
        geom = f['geometry']; coords = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        rings = [p[0] for p in coords]
        polys[f['properties'].get('Valdistriktsnamn', '')] = {'kod': str(f['properties'].get('Valdistriktskod', '')), 'rings': rings}
    if not polys: return {}
    pts = [pt for v in polys.values() for r in v['rings'] for pt in r]
    minx = min(p[0] for p in pts); maxx = max(p[0] for p in pts); miny = min(p[1] for p in pts); maxy = max(p[1] for p in pts)
    W = 1000.0; sc = W/(maxx-minx or 1); H = (maxy-miny)*sc
    def proj(p): return [round((p[0]-minx)*sc, 1), round((maxy-p[1])*sc, 1)]
    def simplify(r, tol=8.0):   # enkel punktgallring i viewBox-enheter
        out = [proj(r[0])]
        for p in r[1:]:
            q = proj(p)
            if abs(q[0]-out[-1][0]) + abs(q[1]-out[-1][1]) >= tol: out.append(q)
        return out
    return {'w': W, 'h': round(H, 1), 'polys': {n: {'kod': v['kod'], 'rings': [simplify(r) for r in v['rings'] if len(r) > 3]} for n, v in polys.items()}}

def build(a):
    d = json.load(open(a.data, encoding='utf-8'))
    kk = a.kommun; komKod = d['komKod']; kod2kom = {v: k for k, v in komKod.items()}
    kname = kod2kom.get(kk) or a.name
    if not kname: raise SystemExit(f'Okänd kommunkod {kk}')
    lanKod = d['lanKod']; lanNamn = {v: k for k, v in lanKod.items()}; lk = kk[:2]
    parties = d['parties']; PN = {p['id']: p['namn'] for p in parties}; COL = {p['id']: p['color'] for p in parties}
    final = json.load(open(a.slutligt, encoding='utf-8')) if os.path.exists(a.slutligt) else {}
    ar = d['allresults']; ah = d['allhist']
    covKeys = d.get('covKeys', []); covMeta = d.get('cov', {})
    FAC_LAB = {'income': 'Medianinkomst', 'edu': 'Eftergymnasial utbildning', 'foreign': 'Utländsk bakgrund', 'age': 'Medelålder', 'hyra': 'Hyresrätt', 'turnout': 'Valdeltagande', 'urban': 'Stad–land', 'syss': 'Sysselsättning'}
    facs = []
    for f in covKeys:
        m = covMeta.get(f) if isinstance(covMeta.get(f), dict) else {}
        facs.append({'key': f, 'lab': (m or {}).get('label') or FAC_LAB.get(f, f), 'unit': (m or {}).get('unit', '')})

    # ---- distriktsröster 2026 i alla tre valen (slutligt) ----
    dv = defaultdict(lambda: defaultdict(dict)); dmeta = {}
    for r in read_csv(a.distrikt, gz=True):
        if r['kommunkod'] != kk: continue
        p = r['parti_abbr']
        if p.lower().startswith(NOT_PARTY): continue
        dv[r['distrikt']][r['valtyp']][p] = int(r['roster'])
        dmeta.setdefault(r['distrikt'], {})[r['valtyp']] = {'giltiga': int(r['giltiga'] or 0), 'rb': int(r['rostberattigade'] or 0), 'kod': r['distriktskod']}
    # 2022 (och tidigare) per distriktskod ur data/historik.csv för alla tre valen (riksdagspartierna)
    hist = defaultdict(lambda: defaultdict(dict))   # kod -> val -> year -> {p: share}
    if os.path.exists(a.historik):
        with open(a.historik, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                if not r['distrikt_kod'].startswith(kk): continue
                hist[r['distrikt_kod']][r['val']].setdefault(r['year'], {})[r['party']] = num(r['share'])
    distrikt = []
    djson = {ds['namn']: ds for ds in d['districts'] if ds.get('kommun') == kname}
    for namn in sorted(dv):
        item = {'namn': namn, 'kod': (dmeta[namn].get('RD') or dmeta[namn].get('KF') or {}).get('kod'), 'val': {}, 'turnout': {}}
        for vt in ('RD', 'RF', 'KF'):
            votes = dv[namn].get(vt, {}); meta = dmeta[namn].get(vt)
            if not votes or not meta: continue
            tot = meta['giltiga'] or sum(votes.values())
            item['val'][vt] = {'tot': tot, 'sh': {p: round(100*v/tot, 1) for p, v in votes.items() if tot}}
            if meta['rb']: item['turnout'][vt] = round(100*tot/meta['rb'], 1)   # giltiga röster / röstberättigade
            item['rb'] = meta['rb'] or item.get('rb')
        dj = djson.get(namn) or {}
        item['chg'] = dj.get('changes') or {}             # RD 2022 -> 2026 (jämförbara distrikt, ur data.json)
        item['chgv'] = {}                                  # per val: 2022 -> 2026 ur historik.csv (samma distriktskod)
        for vt in ('RD', 'RF', 'KF'):
            h22 = (hist.get(item['kod'] or '', {}).get(vt, {}) or {}).get('2022')
            v26 = item['val'].get(vt)
            if h22 and v26: item['chgv'][vt] = {p: round(v26['sh'].get(p, 0) - h22[p], 1) for p in PIDS if h22.get(p) is not None}
        if not item['chg'] and item['chgv'].get('RD'): item['chg'] = item['chgv']['RD']
        item['series'] = dj.get('series') or {}           # RD 2014/2018/2022/2026
        item['cov'] = {f: dj.get(f) for f in covKeys if dj.get(f) is not None}
        item['uppsamling'] = namn.lower().startswith('uppsamling')
        distrikt.append(item)
    elyears = d.get('elyears') or [2014, 2018, 2022, 2026]

    # ---- kommunresultat, mandat, styre ----
    def alist(rows): return {x['p']: x['a'] for x in rows if x.get('p')}
    def hist22(h): return {p: ys.get('2022') for p, ys in (h or {}).items() if ys.get('2022') is not None}
    res = {}
    for vt, src, hsrc in [('KF', ar['kommun'].get(kk, {}).get('KF', []), ah['kommun'].get(kk, {}).get('KF')),
                          ('RF', ar['region'].get(lk, {}).get('RF', []), ah['lan'].get(lk, {}).get('RF'))]:
        r26 = alist(src); r22 = hist22(hsrc)
        res[vt] = [{'p': p, 'a': r26[p], 'chg': (None if r22.get(p) is None else round(r26[p]-r22[p], 2))} for p in sorted(r26, key=lambda p: -r26[p]) if p != 'Övriga']
    # RD för kommunen ur distrikten (2026 ur slutliga röster, förändring ur jämförbara distrikt)
    rdtot = defaultdict(int); rdsum = 0
    for it in distrikt:
        for p, v in dv[it['namn']].get('RD', {}).items(): rdtot[p] += v
        rdsum += (it['val'].get('RD') or {}).get('tot', 0)
    rdchg = defaultdict(float); rdw = 0
    for it in distrikt:
        w = it.get('rb') or 0
        if not it['chg'] or not w: continue
        rdw += w
        for p in PIDS: rdchg[p] += (it['chg'].get(p) or 0)*w
    res['RD'] = [{'p': p, 'a': round(100*v/rdsum, 1), 'chg': (round(rdchg[p]/rdw, 1) if rdw and p in PIDS else None)} for p, v in sorted(rdtot.items(), key=lambda x: -x[1]) if rdsum]
    official = {}; official22 = {}
    for r in read_csv(a.mandat_slutligt):
        if r['valtyp'] == 'KF' and r['kod'] == kk and int(r['mandat2026'] or 0) + int(r['mandat2022'] or 0) > 0:
            official[r['parti_abbr']] = int(r['mandat2026'] or 0); official22[r['parti_abbr']] = int(r['mandat2022'] or 0)
    seats = {p: n for p, n in official.items() if n > 0}; seats22 = {p: n for p, n in official22.items() if n > 0}
    tot = sum(seats.values()); maj = tot//2 + 1 if tot else None
    st = next((r for r in read_csv(a.styre) if r['kommunkod'] == kk), {})
    styre = None
    if st.get('partier'):
        parts = st['partier'].split(','); sure = sum(seats.get(p, 0) for p in parts if p in PIDS)
        loc = sum(v for p, v in seats.items() if p not in PIDS); mx = sure + (loc if 'ÖP' in parts else 0)
        status = 'majoritet' if maj and sure >= maj else ('beror på lokalt parti' if maj and mx >= maj else 'saknar majoritet')
        fix = sorted([{'p': p, 'n': n, 'tot': sure+n} for p, n in seats.items() if p not in parts and sure+n >= (maj or 0)], key=lambda x: x['n'])[:4] if status != 'majoritet' else []
        styre = {'partier': parts, 'kso': st.get('kso_parti'), 'majmin': st.get('majmin'), 'min': sure, 'max': mx, 'status': status, 'fix': fix}
    blocks = {'L': sum(seats.get(p, 0) for p in LEFT), 'R': sum(seats.get(p, 0) for p in RIGHT), 'O': sum(v for p, v in seats.items() if p not in LEFT+RIGHT)}
    blocks22 = {'L': sum(seats22.get(p, 0) for p in LEFT), 'R': sum(seats22.get(p, 0) for p in RIGHT), 'O': sum(v for p, v in seats22.items() if p not in LEFT+RIGHT)}
    turnout = {}
    for r in read_csv(a.valdeltagande):
        if r['niva'] == 'kommun' and r['kod'] == kk: turnout[r['valtyp']] = num(r['valdeltagande_pct'])

    # ---- historik ----
    kfh = (d.get('kfhist') or {}).get(kk) or {}; kfyears = d.get('kfhistYears') or []
    kf26 = {x['p']: x['a'] for x in res['KF']}
    hist_kf = {'years': kfyears + [2026], 'series': {}}
    for p in PIDS:
        vals = list(kfh.get(p, [])) if kfh.get(p) else [None]*len(kfyears)
        hist_kf['series'][p] = vals + [kf26.get(p)]
    rdh = ((d.get('areaHist') or {}).get('kommun') or {}).get(kk, {}).get('RD') or {}
    rd26 = {x['p']: x['a'] for x in res['RD']}
    hist_rd = {'years': [int(y) for y in sorted(rdh.keys())] + [2026], 'series': {p: [rdh[y].get(p) for y in sorted(rdh.keys())] + [rd26.get(p)] for p in PIDS}}

    # ---- demografi inom kommunen ----
    demo = {'niva': {}, 'chg': {}, 'n': 0}
    use = [it for it in distrikt if it['cov'] and it['val'].get('RD') and not it['uppsamling']]
    demo['n'] = len(use)
    for f in facs:
        xs = [it['cov'].get(f['key']) for it in use]
        if any(x is None for x in xs): 
            idx = [i for i, x in enumerate(xs) if x is not None]
        else: idx = list(range(len(xs)))
        if len(idx) < 6: continue
        ws = [use[i].get('rb') or 1 for i in idx]; X = [xs[i] for i in idx]
        demo['niva'][f['key']] = {p: (None if (c := wpearson(X, [use[i]['val']['RD']['sh'].get(p, 0) for i in idx], ws)) is None else round(c, 2)) for p in PIDS}
        demo['chg'][f['key']] = {p: (None if (c := wpearson(X, [use[i]['chg'].get(p, 0) for i in idx], ws)) is None else round(c, 2)) for p in PIDS}

    # ---- personer ----
    led = []
    for r in read_csv(a.nyckelpersoner):
        if r.get('niva') == 'kommun' and r.get('omrade') == kname and r.get('roll_kategori') == 'ledning':
            led.append({'namn': r['namn'], 'p': r.get('parti_abbr'), 'roll': r['roll'], 'organ': r['organ']})
    ROLE = ['ordförande', 'förste vice', '1:e vice', 'andre vice', '2:e vice']
    led.sort(key=lambda x: (x['organ'] != 'Kommunstyrelsen', next((i for i, k in enumerate(ROLE) if x['roll'].lower().startswith(k)), 9), x['namn']))
    valda = [r for r in read_csv(a.valda) if r['valtyp'] == 'KF' and r['valomrkod'] == kk]
    valda_out = [{'namn': r['namn'], 'p': r['parti'], 'nr': int(r.get('invalsordning') or 0), 'vg': r.get('valgrund') or '', 'pr': num(r.get('personroster')), 'kval': r.get('kvalificerad') == 'Ja'} for r in valda]
    valda_out.sort(key=lambda x: (PIDS.index(x['p']) if x['p'] in PIDS else 99, x['nr']))
    listettor = {}
    for p, lst in (d.get('candidates', {}).get('KF', {}).get(kk, {}) or {}).items():
        if lst: listettor[p] = lst[0]

    geo = geometry(a.geojson, kk)
    payload = dict(
        kommun=dict(kod=kk, namn=kname, lan=lanNamn.get(lk, lk), lankod=lk), parties=parties, PN=PN, COL=COL, PIDS=PIDS, facs=facs, elyears=elyears,
        meta=dict(built=d['meta'].get('built'), statusText=status_text(final, bool(official)), official=bool(official), final=final),
        res=res, seats=seats, seats22=seats22, tot=tot, maj=maj, blocks=blocks, blocks22=blocks22, styre=styre, turnout=turnout,
        distrikt=distrikt, hist_kf=hist_kf, hist_rd=hist_rd, demo=demo, led=led, valda=valda_out, listettor=listettor, geo=geo,
    )
    html = PAGE.replace('/*__DATA__*/', json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f: f.write(html)
    print(f"Skrev {a.out}: {kname}, {len(distrikt)} distrikt ({len(geo.get('polys', {}))} med karta), KF-mandat {tot}, valda {len(valda_out)}, demografi n={demo['n']}")

PAGE = r"""<!doctype html>
<html lang="sv"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ – valutfall.se</title>
<style>
 :root{--paper:#f3f5f7;--surface:#fff;--surface2:#eaeef2;--ink:#161b22;--ink2:#4c5563;--ink3:#727c8a;--line:#dce1e7;--accent:#0e7c74;--accent2:#0b605a;--pos:#2e7d5b;--neg:#b0313f;--warn:#9a6a00;--warnbg:#f6ecd0;--shadow:0 1px 2px rgba(16,22,30,.05),0 8px 22px -14px rgba(16,22,30,.22)}
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;--ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;--line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88;--warn:#e2b75a;--warnbg:#2b2617}}
 :root[data-theme=dark]{--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;--ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;--line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88;--warn:#e2b75a;--warnbg:#2b2617}
 *{box-sizing:border-box} body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
 .wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px} a{color:var(--accent2)}
 header.top{padding:22px 0 12px} .rowb{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
 .eyebrow{font:600 .72rem/1 system-ui;letter-spacing:.14em;text-transform:uppercase;color:var(--accent2)}
 h1{margin:8px 0 4px;font-size:1.8rem;letter-spacing:-.01em} h2{font-size:1.15rem;margin:22px 0 8px} h3{font-size:1rem;margin:16px 0 6px}
 .sub{color:var(--ink2);margin:0;max-width:68ch;font-size:.95rem} .meta{margin-top:10px;font:.75rem/1.4 ui-monospace,monospace;color:var(--ink3)}
 .btn{background:var(--surface);color:var(--ink2);border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer;font:.78rem system-ui;text-decoration:none} .btn:hover{border-color:var(--accent);color:var(--accent2)}
 .nav a.cur{background:var(--accent);color:#fff;border-color:var(--accent)}
 .caveat{margin:12px 0 0;padding:10px 14px;border-radius:10px;background:var(--surface2);color:var(--ink2);font-size:.82rem}
 .intro{margin:0 0 12px;padding:12px 14px;border-radius:10px;background:var(--surface2);font-size:.95rem;line-height:1.55} .intro b{color:var(--accent2)}
 .tabs{display:flex;gap:4px;flex-wrap:wrap;margin:16px 0 0} .tab{flex:1 1 auto;min-width:100px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:9px 12px;cursor:pointer;font:600 .88rem system-ui;color:var(--ink2)} .tab[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}
 .panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);margin-top:10px}
 .lead{color:var(--ink2);font-size:.92rem;margin:0 0 10px} .note{color:var(--ink3);font-size:.78rem;margin-top:10px}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 14px} .kpi{background:var(--surface2);border-radius:10px;padding:10px 12px} .kpi .v{font-size:1.5rem;font-weight:700;line-height:1.1} .kpi .l{font-size:.78rem;color:var(--ink3)} .kpi .d{font-size:.8rem;color:var(--ink2)}
 table{width:100%;border-collapse:collapse;font-size:.88rem} th,td{padding:7px 8px;border-top:1px solid var(--line);text-align:left;vertical-align:top} th{color:var(--ink3);font-weight:600;font-size:.78rem;border-top:none} td.r,th.r{text-align:right} tr.click{cursor:pointer} tr.click:hover td{background:var(--surface2)} tr.sel td{background:var(--surface2);font-weight:600}
 .pf{font:.72rem ui-monospace,monospace;color:#fff;border-radius:5px;padding:1px 6px;white-space:nowrap} .pos{color:var(--pos)} .neg{color:var(--neg)} .muted{color:var(--ink3)}
 .seatbar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:8px 0;position:relative} .seatbar span{display:flex;align-items:center;justify-content:center;font:600 .7rem system-ui;color:#fff;overflow:hidden;white-space:nowrap} .seatbar .mid{position:absolute;left:50%;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
 .chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0} .chip{border:1.5px solid var(--line);background:var(--surface);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:.84rem;color:var(--ink2)} .chip.on{color:#fff;border-color:transparent}
 .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:6px 0 10px} .ctl{display:flex;flex-direction:column;gap:4px} .ctl label{font:.7rem/1 system-ui;letter-spacing:.03em;text-transform:uppercase;color:var(--ink3)}
 select{border:1px solid var(--line);background:var(--surface2);color:var(--ink);border-radius:9px;padding:8px 10px;font:inherit} .seg{display:inline-flex;flex-wrap:wrap;gap:2px;padding:3px;border:1px solid var(--line);background:var(--surface2);border-radius:9px;max-width:100%} .seg button{border:none;background:none;color:var(--ink2);border-radius:7px;padding:6px 12px;cursor:pointer;font:600 .85rem system-ui} .seg button[aria-pressed=true]{background:var(--accent);color:#fff}
 .status{display:inline-block;border-radius:6px;padding:2px 7px;font-size:.76rem;font-weight:600} .s-maj{background:rgba(46,125,91,.15);color:var(--pos)} .s-sak{background:rgba(176,49,63,.15);color:var(--neg)} .s-ber{background:var(--warnbg);color:var(--warn)}
 .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px} .maprow{display:grid;grid-template-columns:minmax(260px,1.2fr) minmax(240px,1fr);gap:16px;align-items:start} @media(max-width:700px){.maprow{grid-template-columns:1fr}}
 svg.dmap{width:100%;height:auto;display:block;background:var(--surface2);border-radius:12px} svg.dmap path{stroke:var(--surface);stroke-width:1.5;cursor:pointer} svg.dmap path:hover{stroke:var(--ink);stroke-width:2} svg.dmap path.sel{stroke:var(--ink);stroke-width:3}
 .legend{display:flex;gap:8px;align-items:center;font-size:.78rem;color:var(--ink2);margin-top:6px} .legend .bar{flex:1;height:10px;border-radius:5px}
 .card{border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:8px 0;background:var(--surface)} .card table{font-size:.8rem} .card th,.card td{padding:4px 4px}
 .explain{background:var(--surface2);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;padding:0 13px} .explain summary{cursor:pointer;padding:10px 0;font-weight:600;font-size:.85rem;color:var(--accent2)} .explain .body{padding:0 0 10px} .explain p{margin:0 0 8px;font-size:.86rem;color:var(--ink2)}
 .takeaway{background:var(--surface2);border-left:3px solid var(--accent);border-radius:8px;padding:10px 13px;margin:12px 0;font-size:.92rem} .tw{overflow-x:auto} .corr{display:inline-block;height:9px;border-radius:5px;vertical-align:middle}
 footer{padding-top:24px;margin-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:.8rem}
 @media(max-width:640px){.wrap{padding:0 12px 48px} h1{font-size:1.5rem} table{font-size:.82rem} th,td{padding:6px 5px} .pn{display:none} .seg button{padding:6px 8px;font-size:.78rem} .ctl{max-width:100%}}
</style></head>
<body><div class="wrap">
<header class="top">
 <div class="rowb"><span class="eyebrow">valutfall.se · kommun</span>
  <span class="nav"><a class="btn" href="/">Resultat</a> <a class="btn" href="/partianalys.html">Partianalys</a> <a class="btn" href="/valjaranalys.html">Väljaranalys</a> <a class="btn" href="/personvalet.html">Personvalet</a> <button class="btn" id="theme" type="button" aria-label="Byt tema">☾ / ☀</button></span></div>
 <h1 id="h1"></h1>
 <p class="sub" id="sub"></p>
 <div class="meta" id="meta"></div>
 <div class="caveat" id="statusnote"></div>
</header>
<div class="tabs" id="tabs" role="tablist">
 <button class="tab" data-mode="oversikt">Översikt</button><button class="tab" data-mode="karta">Valdistrikt</button><button class="tab" data-mode="historik">Historik</button><button class="tab" data-mode="split">Röstsplittring</button><button class="tab" data-mode="demografi">Demografi</button><button class="tab" data-mode="personer">Personer</button>
</div>
<div class="panel" id="panel"></div>
<footer>
 <p>Underlag: Valmyndigheten (röster per valdistrikt i alla tre valen, slutligt; mandatfördelning; valdeltagande; valdistriktsgeometri), SCB (distriktsdemografi), Faktadriven (styre efter valet 2022), Plenum via nyckelpersoner.csv. Valdeltagande per distrikt = giltiga röster delat med röstberättigade.</p>
 <p><b>valutfall.se</b> är gjord av Influera Sveriges Sandro Wennberg med hjälp av AI (Anthropic).</p>
</footer></div>
<script>
const DATA=/*__DATA__*/;
const $=s=>document.querySelector(s);const PN=DATA.PN,PIDS=DATA.PIDS,COL=DATA.COL;const K=DATA.kommun;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const col=p=>COL[p]||'#7a8390';const pf=p=>`<span class="pf" style="background:${col(p)}">${esc(p)}</span>`;
const f1=v=>v==null?'–':(Math.round(v*10)/10).toFixed(1).replace('.',',');const sg=v=>v==null?'<span class="muted">–</span>':`<span class="${v>0?'pos':v<0?'neg':'muted'}">${v>0?'+':''}${f1(v)}</span>`;const sgi=v=>v==null?'–':`<span class="${v>0?'pos':v<0?'neg':'muted'}">${v>0?'+':''}${v}</span>`;
const VN={RD:'Riksdag',RF:'Region',KF:'Kommun'};const ORDER=['V','S','MP','C','L','KD','M','SD'];const isMobile=()=>window.matchMedia('(max-width:640px)').matches;
let mode='oversikt',mapVal='KF',mapP=null,mapMode='andel',selD=null,histVal='KF',splitP='S',demoView='niva',demoF=DATA.facs[0]?.key;
(function(){const t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);$('#theme').onclick=()=>{const cur=document.documentElement.getAttribute('data-theme');const next=cur==='dark'?'light':(cur==='light'?'':'dark');if(next)document.documentElement.setAttribute('data-theme',next);else document.documentElement.removeAttribute('data-theme');localStorage.setItem('theme',next);};})();
function intro(what,now){return `<div class="intro">${what}${now?` <b>Just nu:</b> ${now}`:''}</div>`;}
function head(){$('#h1').textContent=`${K.namn} – valet 2026`;$('#sub').textContent=`Allt om valet i ${K.namn} (${K.lan}): resultat i riksdag, region och kommun, varje valdistrikt på karta, historik sedan 1973, röstsplittring, demografi och vilka som styr.`;
 $('#meta').textContent=DATA.meta.built?`byggd ${new Date(DATA.meta.built).toLocaleString('sv-SE',{dateStyle:'short',timeStyle:'short'})}`:'';$('#statusnote').innerHTML=DATA.meta.statusText||'';document.title=`${K.namn} – valet 2026 – valutfall.se`;}
const topP=vt=>(DATA.res[vt]||[])[0];
function seatBar(seats,tot){const ps=[...ORDER.filter(p=>seats[p]),...Object.keys(seats).filter(p=>!ORDER.includes(p)).sort((a,b)=>seats[b]-seats[a])];return `<div class="seatbar">${ps.map(p=>`<span style="width:${100*seats[p]/tot}%;background:${col(p)}" title="${esc(PN[p]||p)} ${seats[p]}">${100*seats[p]/tot>7?esc(p)+' '+seats[p]:''}</span>`).join('')}<div class="mid"></div></div>`;}
function resTable(vt,withSeats){const rows=DATA.res[vt]||[];const have=new Set(rows.map(r=>r.p));const extra=withSeats?Object.keys(DATA.seats).filter(p=>!have.has(p)).map(p=>({p,a:null,chg:null})):[];
 return `<div class="tw"><table><thead><tr><th>Parti</th><th class="r">2026 %</th><th class="r">±2022</th>${withSeats?'<th class="r">Mandat</th><th class="r">±</th>':''}</tr></thead><tbody>${rows.concat(extra).map(r=>`<tr><td>${pf(r.p)} <span class="pn">${esc(PN[r.p]||r.p)}</span></td><td class="r">${f1(r.a)}</td><td class="r">${sg(r.chg)}</td>${withSeats?`<td class="r">${DATA.seats[r.p]??0}</td><td class="r">${sgi((DATA.seats[r.p]||0)-(DATA.seats22[r.p]||0))}</td>`:''}</tr>`).join('')}</tbody></table></div>`;}
function statusTag(s){return s.status==='majoritet'?'<span class="status s-maj">behåller majoritet</span>':s.status==='saknar majoritet'?'<span class="status s-sak">saknar majoritet</span>':'<span class="status s-ber">beror på lokalt parti</span>';}
function styreText(){const s=DATA.styre,b=DATA.blocks,b22=DATA.blocks22,tot=DATA.tot,maj=DATA.maj;if(!tot)return '';
 const side=b.L>=maj?`<b>S+V+MP+C har egen majoritet</b> (${b.L} av ${tot}).`:b.R>=maj?`<b>M+KD+L+SD har egen majoritet</b> (${b.R} av ${tot}).`:`<b>Varken S+V+MP+C eller M+KD+L+SD har egen majoritet</b>${b.O?` – de ${b.O} mandaten för övriga partier avgör`:''}.`;
 let st='';if(s){const gap=maj-s.min;st=`<p class="lead"><b>Sittande styre 2022–26:</b> ${s.partier.map(p=>pf(p)).join(' ')} <span class="muted">(${esc((s.majmin||'').toLowerCase())}${s.kso?', KSO från '+s.kso:''})</span>. Samma partier får <b>${s.min===s.max?s.min:s.min+'–'+s.max} mandat</b> i nya fullmäktige, ${s.status==='majoritet'?`<span class="pos">${s.min-maj>0?s.min-maj+' över gränsen':'precis på gränsen'}</span>`:s.status==='beror på lokalt parti'?'<span class="muted">räcker bara om det lokala partiet räknas med</span>':`<span class="neg">${gap} för lite</span>`}. ${statusTag(s)}${s.fix&&s.fix.length?`<br><b>Skulle nå majoritet med:</b> ${s.fix.map(f=>pf(f.p)+' ('+f.tot+')').join(', ')}.`:s.status==='saknar majoritet'?'<br>Inget enskilt parti räcker.':''}</p>`;}
 return `<p class="lead"><b>Majoritet kräver ${maj} av ${tot} mandat.</b> S+V+MP+C ${b.L} (${sgi(b.L-b22.L)} mot 2022) · M+KD+L+SD ${b.R} (${sgi(b.R-b22.R)})${b.O?` · övriga ${b.O}`:''}. ${side}</p>${st}`;}
// ---------- Översikt ----------
function rOversikt(){const t=DATA.turnout;const kf=topP('KF'),rd=topP('RD'),rf=topP('RF');
 $('#panel').innerHTML=`<h2 style="margin-top:0">Översikt</h2>${intro(`Här ser du hur ${K.namn} röstade i de tre valen, vilka som fick mandat i kommunfullmäktige och om de som styr i dag behåller majoriteten.`,`${kf?`${PN[kf.p]||kf.p} är största parti i kommunvalet med ${f1(kf.a)} % (${sg(kf.chg)}).`:''} ${DATA.styre?(DATA.styre.status==='majoritet'?'Det sittande styret behåller majoriteten.':DATA.styre.status==='saknar majoritet'?'Det sittande styret saknar majoritet med det nya resultatet.':'Det sittande styrets majoritet beror på ett lokalt parti.'):''}`)}
 <div class="kpis">${['KF','RF','RD'].map(vt=>{const x=topP(vt);return x?`<div class="kpi"><div class="v">${pf(x.p)} ${f1(x.a)} %</div><div class="l">Största parti, ${VN[vt].toLowerCase()}valet</div><div class="d">${sg(x.chg)} mot 2022${t[vt]!=null?` · valdeltagande ${f1(t[vt])} %`:''}</div></div>`:''}).join('')}</div>
 <h3>Kommunfullmäktige ${DATA.tot?`– ${DATA.tot} mandat`:''}</h3>${DATA.tot?seatBar(DATA.seats,DATA.tot):''}${styreText()}
 <div class="grid2"><div><h3>Kommunvalet</h3>${resTable('KF',true)}</div><div><h3>Riksdagsvalet i ${esc(K.namn)}</h3>${resTable('RD',false)}<h3>Regionvalet i ${esc(K.namn)}</h3>${resTable('RF',false)}</div></div>
 <p class="note">Riksdags- och regionandelar är kommunens valdistrikt summerade ur Valmyndighetens slutliga röster. Förändring i riksdagsvalet räknas på distrikt som är jämförbara med 2022. Mandat: ${DATA.meta.official?'Valmyndighetens fastställda fördelning':'saknas i underlaget'}.</p>`;}
// ---------- Karta ----------
function val(d,vt){return d.val[vt]||null;}
function mapValue(d){if(mapMode==='deltag')return d.turnout[mapVal]??null;if(mapMode==='top'){const v=val(d,mapVal);if(!v)return null;return Object.entries(v.sh).sort((a,b)=>b[1]-a[1])[0][0];}
 if(mapMode==='chg'){const c=(d.chgv||{})[mapVal]||(mapVal==='RD'?d.chg:null);return c&&c[mapP]!=null?c[mapP]:null;}const v=val(d,mapVal);return v?(v.sh[mapP]??0):null;}
function lerp(a,b,t){return a+(b-a)*t;}function hex(c){const m=/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(c);return m?[parseInt(m[1],16),parseInt(m[2],16),parseInt(m[3],16)]:[120,120,120];}
function mix(c,t){const[r,g,b]=hex(c);const base=document.documentElement.getAttribute('data-theme')==='dark'||(window.matchMedia('(prefers-color-scheme:dark)').matches&&document.documentElement.getAttribute('data-theme')!=='light')?[40,48,58]:[235,238,242];return `rgb(${Math.round(lerp(base[0],r,t))},${Math.round(lerp(base[1],g,t))},${Math.round(lerp(base[2],b,t))})`;}
function rKarta(){const ps=partiesFor(mapVal);if(!mapP||!ps.includes(mapP)){const t=topP(mapVal);mapP=t&&ps.includes(t.p)?t.p:ps[0];}const G=DATA.geo;const ds=DATA.distrikt.filter(d=>!d.uppsamling);
 const vals=ds.map(mapValue).filter(v=>v!=null&&typeof v==='number');const lo=vals.length?Math.min(...vals):0,hi=vals.length?Math.max(...vals):1;
 const fill=d=>{const v=mapValue(d);if(v==null)return 'var(--surface2)';if(mapMode==='top')return col(v);if(mapMode==='chg'){const m=Math.max(Math.abs(lo),Math.abs(hi))||1;return v>=0?mix(getComputedStyle(document.documentElement).getPropertyValue('--pos').trim()||'#2e7d5b',Math.min(1,v/m)):mix(getComputedStyle(document.documentElement).getPropertyValue('--neg').trim()||'#b0313f',Math.min(1,-v/m));}return mix(mapMode==='deltag'?'#0e7c74':col(mapP),(v-lo)/((hi-lo)||1)*0.85+0.15);};
 const svg=G.polys?`<svg class="dmap" viewBox="0 0 ${G.w} ${G.h}" preserveAspectRatio="xMidYMid meet">${Object.entries(G.polys).map(([n,p])=>{const d=DATA.distrikt.find(x=>x.namn===n);return `<path d="${p.rings.map(r=>'M'+r.map(q=>q[0]+','+q[1]).join('L')+'Z').join('')}" fill="${d?fill(d):'var(--surface2)'}" data-n="${esc(n)}" class="${selD===n?'sel':''}"><title>${esc(n)}${d&&mapValue(d)!=null?' – '+(typeof mapValue(d)==='number'?f1(mapValue(d))+(mapMode==='chg'?' enh.':' %'):PN[mapValue(d)]||mapValue(d)):''}</title></path>`;}).join('')}</svg>`:'<div class="muted">Ingen karta i underlaget.</div>';
 const legend=mapMode==='top'?`<div class="legend">${[...new Set(ds.map(mapValue).filter(Boolean))].map(p=>`<span>${pf(p)}</span>`).join(' ')}</div>`:`<div class="legend"><span>${f1(lo)}${mapMode==='chg'?'':' %'}</span><span class="bar" style="background:linear-gradient(90deg,${mapMode==='chg'?'var(--neg),var(--surface2),var(--pos)':mix(mapMode==='deltag'?'#0e7c74':col(mapP),.15)+','+mix(mapMode==='deltag'?'#0e7c74':col(mapP),1)})"></span><span>${f1(hi)}${mapMode==='chg'?'':' %'}</span></div>`;
 const sorted=ds.slice().sort((a,b)=>{const x=mapValue(a),y=mapValue(b);return (typeof y==='number'?y:-1e9)-(typeof x==='number'?x:-1e9);});
 $('#panel').innerHTML=`<h2 style="margin-top:0">Valdistrikten</h2>${intro(`Här ser du hur varje valdistrikt i ${K.namn} röstade. Välj val, parti och vad kartan ska visa. Klicka på ett distrikt i kartan eller i listan för alla tre valen, valdeltagande och demografi.`,mapMode==='andel'&&sorted.length?`${PN[mapP]||mapP} är starkast i ${esc(sorted[0].namn)} (${f1(mapValue(sorted[0]))} %) och svagast i ${esc(sorted[sorted.length-1].namn)} (${f1(mapValue(sorted[sorted.length-1]))} %).`:'')}
 <div class="controls"><div class="ctl"><label>Val</label><span class="seg" id="mv">${['KF','RF','RD'].map(v=>`<button data-v="${v}" aria-pressed="${mapVal===v}">${VN[v]}</button>`).join('')}</span></div>
  <div class="ctl"><label>Visa</label><span class="seg" id="mm"><button data-m="andel" aria-pressed="${mapMode==='andel'}">Andel</button><button data-m="chg" aria-pressed="${mapMode==='chg'}">±2022</button><button data-m="top" aria-pressed="${mapMode==='top'}">Största parti</button><button data-m="deltag" aria-pressed="${mapMode==='deltag'}">Valdeltagande</button></span></div>
  <div class="ctl"><label>Parti</label><select id="mp">${ps.map(p=>`<option value="${esc(p)}" ${p===mapP?'selected':''}>${esc(PN[p]||p)}</option>`).join('')}</select></div></div>
 <div class="maprow"><div>${svg}${legend}</div><div id="dpanel">${selD?distCard(DATA.distrikt.find(x=>x.namn===selD)):'<p class="muted">Klicka på ett distrikt.</p>'}</div></div>
 <h3>Alla distrikt</h3><div class="tw"><table><thead><tr><th>Distrikt</th><th class="r">${mapMode==='deltag'?'Valdeltagande':mapMode==='top'?'Största':mapMode==='chg'?'±2022':esc(mapP)+' %'}</th><th class="r">Röstber.</th></tr></thead><tbody>${sorted.map(d=>{const v=mapValue(d);return `<tr class="click ${selD===d.namn?'sel':''}" data-n="${esc(d.namn)}"><td>${esc(d.namn)}</td><td class="r">${v==null?'–':typeof v==='number'?(mapMode==='chg'?sg(v):f1(v)+' %'):pf(v)}</td><td class="r">${d.rb?d.rb.toLocaleString('sv-SE'):'–'}</td></tr>`;}).join('')}</tbody></table></div>
 <p class="note">Uppsamlingsdistriktet (förtidsröster som inte kunnat föras till ett distrikt) visas inte på kartan. ±2022 finns för riksdagspartierna i distrikt som har samma kod som 2022; omritade eller nya distrikt saknar jämförelse.</p>`;
 $('#panel').querySelectorAll('#mv button').forEach(b=>b.onclick=()=>{mapVal=b.dataset.v;rKarta();});
 $('#panel').querySelectorAll('#mm button').forEach(b=>b.onclick=()=>{mapMode=b.dataset.m;rKarta();});
 $('#mp').onchange=e=>{mapP=e.target.value;rKarta();};
 $('#panel').querySelectorAll('[data-n]').forEach(el=>el.addEventListener('click',()=>{selD=selD===el.dataset.n?null:el.dataset.n;rKarta();}));}
function partiesFor(vt){const s=new Set();DATA.distrikt.forEach(d=>{const v=val(d,vt);if(v)Object.keys(v.sh).forEach(p=>{if(v.sh[p]>=1)s.add(p);});});return [...ORDER.filter(p=>s.has(p)),...[...s].filter(p=>!ORDER.includes(p)).sort()];}
function distCard(d){if(!d)return '';const vts=['KF','RF','RD'].filter(v=>d.val[v]);const ps=[...new Set(vts.flatMap(v=>Object.keys(d.val[v].sh)))].filter(p=>vts.some(v=>(d.val[v].sh[p]||0)>=1)).sort((a,b)=>(ORDER.indexOf(a)===-1?99:ORDER.indexOf(a))-(ORDER.indexOf(b)===-1?99:ORDER.indexOf(b)));
 return `<div class="card"><b>${esc(d.namn)}</b> <span class="muted">· ${d.rb?d.rb.toLocaleString('sv-SE')+' röstberättigade':''}</span>
 <div class="tw"><table><thead><tr><th>Parti</th>${vts.map(v=>`<th class="r">${VN[v]}<br><small class="muted">2026 · ±22</small></th>`).join('')}</tr></thead><tbody>${ps.map(p=>`<tr><td>${pf(p)}</td>${vts.map(v=>{const c=(d.chgv||{})[v]||(v==='RD'?d.chg:null);return `<td class="r">${f1(d.val[v].sh[p])} <small>${c&&c[p]!=null?sg(c[p]):''}</small></td>`;}).join('')}</tr>`).join('')}<tr><td class="muted">Valdeltagande</td>${vts.map(v=>`<td class="r muted">${d.turnout[v]!=null?f1(d.turnout[v])+' %':'–'}</td>`).join('')}</tr></tbody></table></div>
 ${Object.keys(d.cov).length?`<p class="lead" style="margin:8px 0 0;font-size:.84rem">${DATA.facs.filter(f=>d.cov[f.key]!=null).map(f=>`<b>${esc(f.lab)}</b> ${(Math.round(d.cov[f.key]*10)/10).toLocaleString('sv-SE')}${f.unit?' '+esc(f.unit):''}`).join(' · ')}</p>`:''}</div>`;}
// ---------- Historik ----------
function lineChart(years,series,ps){const W=680,H=300,mL=40,mB=30,mT=12,mR=70;const all=ps.flatMap(p=>series[p]||[]).filter(v=>v!=null);const ymax=Math.max(10,...all)*1.08;
 const sx=i=>mL+i/((years.length-1)||1)*(W-mL-mR),sy=v=>mT+(1-v/ymax)*(H-mB-mT);
 const grid=[0,10,20,30,40,50].filter(v=>v<ymax).map(v=>`<line x1="${mL}" x2="${W-mR}" y1="${sy(v)}" y2="${sy(v)}" stroke="var(--line)"/><text x="${mL-6}" y="${sy(v)+4}" font-size="10" text-anchor="end" fill="var(--ink3)">${v}</text>`).join('');
 const xs=years.map((y,i)=>i%Math.ceil(years.length/8)===0||i===years.length-1?`<text x="${sx(i)}" y="${H-mB+16}" font-size="10" text-anchor="middle" fill="var(--ink3)">${y}</text>`:'').join('');
 const lines=ps.map(p=>{const pts=(series[p]||[]).map((v,i)=>v==null?null:[sx(i),sy(v)]).filter(Boolean);if(pts.length<2)return '';const last=pts[pts.length-1];return `<path d="${pts.map((q,i)=>(i?'L':'M')+q[0].toFixed(1)+','+q[1].toFixed(1)).join('')}" fill="none" stroke="${col(p)}" stroke-width="2.2"/>${pts.map(q=>`<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="2.5" fill="${col(p)}"/>`).join('')}<text x="${(last[0]+6).toFixed(1)}" y="${(last[1]+4).toFixed(1)}" font-size="11" fill="${col(p)}">${esc(p)} ${f1(series[p][series[p].length-1])}</text>`;}).join('');
 return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:720px">${grid}${xs}${lines}</svg>`;}
function rHistorik(){const H=histVal==='KF'?DATA.hist_kf:DATA.hist_rd;const ps=PIDS.filter(p=>(H.series[p]||[]).some(v=>v!=null));
 const first=H.years[0];const rows=ps.map(p=>{const s=H.series[p];const a=s.find(v=>v!=null),b=s[s.length-1];return {p,a,b,d:a!=null&&b!=null?b-a:null};}).sort((x,y)=>(y.d||0)-(x.d||0));
 $('#panel').innerHTML=`<h2 style="margin-top:0">Historik</h2>${intro(`Här ser du hur partiernas stöd i ${K.namn} ändrats val för val, i kommunvalet sedan ${DATA.hist_kf.years[0]} och i riksdagsvalet sedan ${DATA.hist_rd.years[0]}.`,rows.length?`Sedan ${first} har ${PN[rows[0].p]} vuxit mest (${sg(rows[0].d)}) och ${PN[rows[rows.length-1].p]} tappat mest (${sg(rows[rows.length-1].d)}).`:'')}
 <div class="controls"><div class="ctl"><label>Val</label><span class="seg" id="hv"><button data-v="KF" aria-pressed="${histVal==='KF'}">Kommunvalet</button><button data-v="RD" aria-pressed="${histVal==='RD'}">Riksdagsvalet i kommunen</button></span></div></div>
 ${lineChart(H.years,H.series,ps)}
 <div class="tw"><table><thead><tr><th>Parti</th>${H.years.map(y=>`<th class="r">${y}</th>`).join('')}</tr></thead><tbody>${ps.map(p=>`<tr><td>${pf(p)}</td>${H.series[p].map(v=>`<td class="r">${f1(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
 <p class="note">Kommunvalet: Valmyndighetens historik 1973–2022 och slutligt resultat 2026. Riksdagsvalet: kommunens distrikt summerade. Partier som inte fanns visas med streck.</p>`;
 $('#panel').querySelectorAll('#hv button').forEach(b=>b.onclick=()=>{histVal=b.dataset.v;rHistorik();});}
// ---------- Röstsplittring ----------
function rSplit(){const ds=DATA.distrikt.filter(d=>d.val.RD&&d.val.KF);const ps=partiesFor('KF').filter(p=>ORDER.includes(p));if(!ps.includes(splitP))splitP=ps[0];
 const kom={};['RD','RF','KF'].forEach(vt=>{kom[vt]={};(DATA.res[vt]||[]).forEach(r=>kom[vt][r.p]=r.a);});
 const all=[...new Set(['RD','RF','KF'].flatMap(vt=>Object.keys(kom[vt])))].filter(p=>Math.max(kom.RD[p]||0,kom.RF[p]||0,kom.KF[p]||0)>=1).sort((a,b)=>(kom.KF[b]||0)-(kom.KF[a]||0));
 const rows=ds.map(d=>({d,rd:d.val.RD.sh[splitP]||0,rf:d.val.RF?d.val.RF.sh[splitP]||0:null,kf:d.val.KF.sh[splitP]||0})).map(x=>({...x,diff:x.kf-x.rd})).sort((a,b)=>b.diff-a.diff);
 const big=all.map(p=>({p,diff:(kom.KF[p]||0)-(kom.RD[p]||0)})).sort((a,b)=>Math.abs(b.diff)-Math.abs(a.diff))[0];
 $('#panel').innerHTML=`<h2 style="margin-top:0">Röstsplittring</h2>${intro(`Här ser du hur många som röstade olika i kommunvalet, regionvalet och riksdagsvalet: samma väljare, tre valsedlar. Skillnaden mellan kommun och riksdag visar var ett parti har lokal dragningskraft eller lokalt motstånd.`,big?`Störst skillnad i ${K.namn} har ${esc(PN[big.p]||big.p)}: ${f1(kom.KF[big.p])} % i kommunvalet mot ${f1(kom.RD[big.p])} % i riksdagsvalet (${sg(big.diff)}).`:'')}
 <h3>Hela kommunen</h3><div class="tw"><table><thead><tr><th>Parti</th><th class="r">Kommun</th><th class="r">Region</th><th class="r">Riksdag</th><th class="r">Kommun − riksdag</th></tr></thead><tbody>${all.map(p=>`<tr><td>${pf(p)} <span class="pn">${esc(PN[p]||p)}</span></td><td class="r">${f1(kom.KF[p])}</td><td class="r">${f1(kom.RF[p])}</td><td class="r">${f1(kom.RD[p])}</td><td class="r"><b>${sg((kom.KF[p]||0)-(kom.RD[p]||0))}</b></td></tr>`).join('')}</tbody></table></div>
 <h3>Per valdistrikt</h3><div class="chips">${ps.map(p=>`<button class="chip ${p===splitP?'on':''}" data-p="${p}" style="${p===splitP?'background:'+col(p):''}">${p}</button>`).join('')}</div>
 <div class="tw"><table><thead><tr><th>Distrikt</th><th class="r">Kommun</th><th class="r">Region</th><th class="r">Riksdag</th><th class="r">Kommun − riksdag</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.d.namn)}</td><td class="r">${f1(x.kf)}</td><td class="r">${f1(x.rf)}</td><td class="r">${f1(x.rd)}</td><td class="r"><b>${sg(x.diff)}</b></td></tr>`).join('')}</tbody></table></div>
 <p class="note">Lokala partier finns bara i kommunvalet, så deras kommunröster kommer från väljare som röstade på något annat parti till riksdagen.</p>`;
 $('#panel').querySelectorAll('.chip').forEach(b=>b.onclick=()=>{splitP=b.dataset.p;rSplit();});}
// ---------- Demografi ----------
function corrCell(c){if(c==null)return '<td class="r muted">–</td>';const w=Math.min(60,Math.abs(c)*100);return `<td class="r"><span class="corr" style="width:${w}px;background:${c>0?'var(--pos)':'var(--neg)'}"></span> ${c>0?'+':''}${c.toFixed(2).replace('.',',')}</td>`;}
function rDemografi(){const D=DATA.demo;const T=demoView==='chg'?D.chg:D.niva;const fs=DATA.facs.filter(f=>T[f.key]);if(!fs.some(f=>f.key===demoF))demoF=fs[0]?.key;
 let best=null;fs.forEach(f=>PIDS.forEach(p=>{const c=T[f.key][p];if(c!=null&&(!best||Math.abs(c)>Math.abs(best.c)))best={f,p,c};}));
 const ds=DATA.distrikt.filter(d=>d.cov[demoF]!=null&&d.val.RD&&!d.uppsamling);
 $('#panel').innerHTML=`<h2 style="margin-top:0">Demografi</h2>${intro(`Här ser du hur partiernas stöd i ${K.namn}s valdistrikt hänger ihop med vilka som bor där: inkomst, utbildning, ålder, boende med mera. Räknat över kommunens ${D.n} valdistrikt.`,best?`Starkast samband ${demoView==='chg'?'för förändringen':''}: ${PN[best.p]} och ${best.f.lab.toLowerCase()} (${best.c>0?'+':''}${best.c.toFixed(2).replace('.',',')}) – partiet ${demoView==='chg'?(best.c>0?'ökade mest':'tappade mest'):(best.c>0?'är starkast':'är svagast')} där ${best.f.lab.toLowerCase()} är hög.`:'För få distrikt för att räkna samband.')}
 ${fs.length?`<div class="controls"><div class="ctl"><label>Visa</label><span class="seg" id="dv"><button data-v="niva" aria-pressed="${demoView==='niva'}">Nivå 2026</button><button data-v="chg" aria-pressed="${demoView==='chg'}">Förändring 2022→2026</button></span></div><div class="ctl"><label>Faktor för tabellen</label><select id="df">${fs.map(f=>`<option value="${f.key}" ${f.key===demoF?'selected':''}>${esc(f.lab)}</option>`).join('')}</select></div></div>
 <p class="note" style="margin:0 0 8px">Talen är samband från −1 till +1 (riksdagsvalet). Plus betyder att partiet är starkare där faktorn är hög. 0 inget · 0,1 svagt · 0,3 tydligt · 0,5 och mer starkt. Med ${D.n} distrikt är talen grova. Samband är inte orsak.</p>
 <div class="tw"><table><thead><tr><th>Faktor</th>${PIDS.map(p=>`<th class="r">${p}</th>`).join('')}</tr></thead><tbody>${fs.map(f=>`<tr><td><b>${esc(f.lab)}</b></td>${PIDS.map(p=>corrCell(T[f.key][p])).join('')}</tr>`).join('')}</tbody></table></div>
 <h3>Distrikten sorterade efter ${esc(fs.find(f=>f.key===demoF)?.lab||'')}</h3><div class="tw"><table><thead><tr><th>Distrikt</th><th class="r">${esc(fs.find(f=>f.key===demoF)?.lab||'')}</th>${PIDS.map(p=>`<th class="r">${p}</th>`).join('')}</tr></thead><tbody>${ds.slice().sort((a,b)=>b.cov[demoF]-a.cov[demoF]).map(d=>`<tr><td>${esc(d.namn)}</td><td class="r">${(Math.round(d.cov[demoF]*10)/10).toLocaleString('sv-SE')}</td>${PIDS.map(p=>`<td class="r">${demoView==='chg'?sg(d.chg[p]):f1(d.val.RD.sh[p])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p class="muted">Demografi per distrikt saknas i underlaget.</p>'}`;
 $('#panel').querySelectorAll('#dv button').forEach(b=>b.onclick=()=>{demoView=b.dataset.v;rDemografi();});const sel=$('#df');if(sel)sel.onchange=e=>{demoF=e.target.value;rDemografi();};}
// ---------- Personer ----------
function rPersoner(){const V=DATA.valda;const byP={};V.forEach(v=>(byP[v.p]=byP[v.p]||[]).push(v));const ps=Object.keys(byP).sort((a,b)=>(DATA.seats[b]||0)-(DATA.seats[a]||0));const pv=V.filter(v=>/person/i.test(v.vg)).length;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Personer</h2>${intro(`Här ser du vilka som styr ${K.namn} i dag och vilka som är valda till det nya kommunfullmäktige.`,V.length?`${V.length} ledamöter är valda, ${pv} av dem på personröster.`:'Namn på valda fylls på när Valmyndighetens slutliga filer lästs in; tills dess visas listettorna.')}
 <div class="grid2"><div><h3>Ledande politiker 2022–2026</h3>${DATA.led.length?`<ul style="margin:4px 0;padding-left:18px">${DATA.led.map(x=>`<li>${esc(x.namn)} ${pf(x.p)} <span class="muted">${esc(x.roll)}, ${esc(x.organ)}</span></li>`).join('')}</ul>`:'<p class="muted">Inga uppgifter i personlagret.</p>'}
 ${!V.length?`<h3>Listettor 2026</h3><ul style="margin:4px 0;padding-left:18px">${Object.entries(DATA.listettor).map(([p,n])=>`<li>${pf(p)} ${esc(n)}</li>`).join('')}</ul>`:''}</div>
 <div>${V.length?`<h3>Valda till kommunfullmäktige 2026–2030</h3>${ps.map(p=>`<h4 style="margin:10px 0 4px">${pf(p)} ${esc(PN[p]||p)} <span class="muted">${byP[p].length} mandat</span></h4><ol style="margin:0;padding-left:22px">${byP[p].sort((a,b)=>a.nr-b.nr).map(v=>`<li>${esc(v.namn)}${/person/i.test(v.vg)?' <span class="muted" title="Invald på personröster">✎</span>':''}${v.pr!=null?` <span class="muted" style="font-size:.78rem">${v.pr} personröster${v.kval?', klarade spärren':''}</span>`:''}</li>`).join('')}</ol>`).join('')}`:''}</div></div>
 <p class="note">Ledande politiker: Plenum (mandatperioden 2022–2026). ${V.length?'Valda, valgrund och personröster: Valmyndighetens fastställda resultat.':''} Fler personer i <a href="/personvalet.html">Personvalet</a>.</p>`;}
function setMode(m){mode=m;document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected',t.dataset.mode===m));({oversikt:rOversikt,karta:rKarta,historik:rHistorik,split:rSplit,demografi:rDemografi,personer:rPersoner}[m]||rOversikt)();try{history.replaceState(null,'','#'+m);}catch(e){}}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setMode(t.dataset.mode));head();
(function(){const m=location.hash.replace('#','');setMode(['oversikt','karta','historik','split','demografi','personer'].includes(m)?m:'oversikt');})();
</script></body></html>
"""

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--kommun', required=True, help='kommunkod, t.ex. 0120'); ap.add_argument('--slug', required=True, help='mappnamn, t.ex. varmdo')
    ap.add_argument('--name', help='kommunnamn om koden saknas i data.json')
    ap.add_argument('--data', default='public/data.json'); ap.add_argument('--out')
    ap.add_argument('--distrikt', default='data/distrikt_2026.csv.gz'); ap.add_argument('--geojson', default='data/valdistrikt-riket-2026.zip')
    ap.add_argument('--mandat-slutligt', default='data/mandat_slutligt.csv'); ap.add_argument('--styre', default='data/styre_kommun_2022.csv')
    ap.add_argument('--valdeltagande', default='data/valdeltagande_2026.csv'); ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    ap.add_argument('--valda', default='data/valda.csv'); ap.add_argument('--slutligt', default='data/slutligt.json')
    ap.add_argument('--historik', default='data/historik.csv', help='per-distriktshistorik 2014–2022 för RD/RF/KF (±2022 i kartan för alla tre valen)')
    a = ap.parse_args()
    a.out = a.out or f'public/kommun/{a.slug}/index.html'
    PAGE = PAGE.replace('__TITLE__', a.slug)
    build(a)
