#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_analys.py — bygger undersidan public/analys.html för valutfall.se ("Eftervalsanalys, del 1").

Speglar Del 1 i eftervalsanalysen: valresultat och mandat med förändring mot 2022 (riket,
regioner, större städer), regeringsbildning (koalitionsräknare), regionala och kommunala
majoritetspussel med sittande styre, nyckelspelare, avvikelser i väljarbeteende,
demografi/geografi samt en sektorvy.

Kör (efter build.py, i loopen efter väljaranalysen):
  python3 build_analys.py --data public/data.json --out public/analys.html \
      --styre data/styre_kommun_2022.csv --folk data/folkmangd_2024.csv \
      --nyckelpersoner nyckelpersoner.csv [--slutligt data/slutligt.json]
Endast standardbibliotek.

Metod (visas på sidan):
  * Riksdagsmandat 2026 tas ur data.json (rdSeatsExact, räknat ur exakta röstetal av gor_mandat/build).
  * RF/KF-mandat räknas ur områdesandelarna i data.json med jämkade uddatalsmetoden (första
    deltal 1,2), spärr 3 % (RF) resp. 2 %/3 % (KF, en/flera valkretsar). Kommun/region behandlas
    som EN valkrets. 2022 räknas på samma sätt ur 2022-andelarna, så förändringen är jämförbar men
    approximativ. Personröster ingår inte.
  * Sittande styre 2022–2026 för kommuner: data/styre_kommun_2022.csv (Faktadriven). ÖP = lokalt
    parti (ospecificerat) -> styrets mandat visas som intervall (utan/med lokala partier).
  * Regioner: regionstyrelsens ordförande m.fl. ur nyckelpersoner.csv (Plenum); koalition visas
    inte eftersom verifierad källa saknas i repot.
"""
import csv, json, argparse, math, os
from collections import defaultdict

PIDS = ['V','S','MP','C','L','KD','M','SD']
RD_SEATS_2022 = {'S':107,'SD':73,'M':68,'V':24,'C':24,'KD':19,'MP':18,'L':16}   # Valmyndigheten, slutligt 2022
LEFT = ['S','V','MP','C']          # visas som "S+V+MP+C" (rödgröna + C)
RIGHT = ['M','KD','L','SD']        # visas som "M+KD+L+SD" (Tidöpartierna)

def num(x):
    try:
        v = float(str(x).replace(',', '.'))
        return None if math.isnan(v) else v
    except Exception:
        return None

def jamkad(votes, nseats, first=1.2):
    seats = {p: 0 for p in votes}
    for _ in range(int(nseats)):
        best, bq = None, -1.0
        for p, v in votes.items():
            div = first if seats[p] == 0 else (2*seats[p]+1)
            q = v/div
            if q > bq: bq, best = q, p
        if best is None: break
        seats[best] += 1
    return seats

def seats_from_shares(rows, total, thr):
    """rows: [{'p':..,'a':..}] eller {'p':a}. Alla partier >= spärr, 'Övriga' exkluderas."""
    if isinstance(rows, dict):
        votes = {p: a for p, a in rows.items() if p != 'Övriga' and a is not None and a >= thr}
    else:
        votes = {x['p']: x['a'] for x in rows if x.get('p') and x['p'] != 'Övriga' and (x.get('a') or 0) >= thr}
    if not votes or not total: return {}
    return jamkad(votes, total)

def wpearson(xs, ys, ws):
    sw = sum(ws)
    if sw <= 0 or len(xs) < 5: return None
    mx = sum(w*x for x, w in zip(xs, ws))/sw; my = sum(w*y for y, w in zip(ys, ws))/sw
    cov = sum(w*(x-mx)*(y-my) for x, y, w in zip(xs, ys, ws))/sw
    vx = sum(w*(x-mx)**2 for x, w in zip(xs, ws))/sw; vy = sum(w*(y-my)**2 for y, w in zip(ys, ws))/sw
    if vx <= 0 or vy <= 0: return None
    return cov/math.sqrt(vx*vy)

def read_csv(path):
    if not path or not os.path.exists(path): return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def alist(rows):
    """allresults-lista -> dict p->a"""
    return {x['p']: x['a'] for x in rows if x.get('p')}

def hist2022(h):
    """allhist-struktur {parti:{'2022':a}} -> dict p->a"""
    out = {}
    for p, ys in (h or {}).items():
        a = ys.get('2022')
        if a is not None: out[p] = a
    return out

def blocks(seats):
    l = sum(seats.get(p, 0) for p in LEFT); r = sum(seats.get(p, 0) for p in RIGHT)
    o = sum(v for p, v in seats.items() if p not in LEFT and p not in RIGHT)
    return {'L': l, 'R': r, 'O': o}

def top_parties(res2026, res2022, n=None):
    ps = sorted([p for p in res2026 if p != 'Övriga'], key=lambda p: -res2026[p])
    out = []
    for p in ps:
        a = res2026[p]; b = res2022.get(p)
        out.append({'p': p, 'a': a, 'b': b, 'chg': (None if b is None else round(a-b, 2))})
    return out[:n] if n else out

def build(a):
    d = json.load(open(a.data, encoding='utf-8'))
    parties = d['parties']; PN = {p['id']: p['namn'] for p in parties}
    komKod = d['komKod']; kod2kom = {v: k for k, v in komKod.items()}
    lanKod = d['lanKod']; lanNamn = {v: k for k, v in lanKod.items()}
    ar = d['allresults']; ah = d['allhist']
    seatsL = d['seats'].get('lan', {}); seatsK = d['seats'].get('kommun', {})
    valkretsar = d.get('valkretsar', {})
    final = {}
    if a.slutligt and os.path.exists(a.slutligt):
        final = json.load(open(a.slutligt, encoding='utf-8'))

    # ---------- är KF/RF live eller 2022-spegling? ----------
    def is_live(level, val):
        src = ar.get(level, {}); hist = ah.get('lan' if level == 'region' else level, {})
        diff = 0; n = 0
        for kod, vals in src.items():
            a = alist(vals.get(val, [])); b = hist2022(hist.get(kod, {}).get(val))
            if not a or not b: continue
            n += 1
            if any(abs(a.get(p, 0) - (b.get(p) or 0)) > 0.05 for p in a if p != 'Övriga'): diff += 1
        return n > 0 and diff > 0
    live = {'RD': is_live('riket', 'RD') or is_live('valkrets', 'RD'), 'RF': is_live('region', 'RF'), 'KF': is_live('kommun', 'KF')}
    if not live['RD']:
        # riket saknar hist per valkrets; jämför rikets RD direkt
        a0 = alist(ar['riket']['00'].get('RD', [])); b0 = hist2022(ah['riket']['00'].get('RD'))
        live['RD'] = any(abs(a0.get(p, 0) - (b0.get(p) or 0)) > 0.05 for p in a0 if p != 'Övriga')

    # ---------- RD 2026 per kommun/län ur valdistrikten (jämförbara distrikt, viktat med röstberättigade) ----------
    agg = {'kommun': defaultdict(lambda: defaultdict(float)), 'lan': defaultdict(lambda: defaultdict(float))}
    aggc = {'kommun': defaultdict(lambda: defaultdict(float)), 'lan': defaultdict(lambda: defaultdict(float))}
    aggw = {'kommun': defaultdict(float), 'lan': defaultdict(float)}
    for ds in d['districts']:
        w = ds.get('rost') or 0
        if w <= 0: continue
        sh = ds.get('shares') or {}; ch = ds.get('changes') or {}
        if not sh or not ch or all(abs(v) < 1e-9 for v in ch.values()): continue
        keys = {'kommun': komKod.get(ds.get('kommun', '')), 'lan': lanKod.get(ds.get('lan', ''))}
        for lvl, kod in keys.items():
            if not kod: continue
            aggw[lvl][kod] += w
            for p in PIDS:
                agg[lvl][kod][p] += (sh.get(p) or 0)*w; aggc[lvl][kod][p] += (ch.get(p) or 0)*w
    def rd_area(lvl, kod):
        W = aggw[lvl].get(kod, 0)
        if not W: return []
        return [{'p': p, 'a': round(agg[lvl][kod][p]/W, 2), 'b': round((agg[lvl][kod][p]-aggc[lvl][kod][p])/W, 2),
                 'chg': round(aggc[lvl][kod][p]/W, 2)} for p in sorted(PIDS, key=lambda p: -agg[lvl][kod][p])]

    # ---------- externa filer ----------
    styre = {r['kommunkod']: r for r in read_csv(a.styre)}
    folk = {r['kommunkod']: num(r['folkmangd']) for r in read_csv(a.folk)}
    np_rows = read_csv(a.nyckelpersoner)
    np_kom = defaultdict(list); np_reg = defaultdict(list)
    for r in np_rows:
        if r.get('roll_kategori') != 'ledning': continue
        item = {'namn': r['namn'], 'p': r.get('parti_abbr') or r.get('parti'), 'roll': r['roll'], 'organ': r['organ']}
        if r['niva'] == 'kommun':
            kk = komKod.get(r['omrade'])
            if kk: np_kom[kk].append(item)
        elif r['niva'] == 'region':
            np_reg[r['omrade']].append(item)
    def lan_to_region_name(lk):
        n = lanNamn.get(lk, '')
        if lk == '14': return 'Västra Götalandsregionen'
        base = n.replace(' län', '').replace('s län', '')
        # nyckelpersoner använder "Region X" utan genitiv-s för de flesta
        for cand in ['Region '+n.replace(' län',''), 'Region '+base]:
            if cand in np_reg: return cand
        # fallback: fuzzy på första ordet
        first = n.split()[0].rstrip('s')
        for k in np_reg:
            if first.lower() in k.lower(): return k
        return None

    cands = d.get('candidates', {})
    def listettor(valtyp, kod, ps, n=1):
        out = {}
        lists = cands.get(valtyp, {}).get(kod, {})
        for p in ps:
            names = []
            for nm in lists.get(p, []):
                if nm not in names: names.append(nm)
                if len(names) >= n: break
            if names: out[p] = names
        return out

    # ---------- RIKET (RD) ----------
    rd26 = alist(ar['riket']['00']['RD']); rd22 = hist2022(ah['riket']['00'].get('RD'))
    rd_seats = d.get('rdSeatsExact') or {}
    riket = {
        'res': top_parties(rd26, rd22), 'ovriga': rd26.get('Övriga'),
        'seats': rd_seats, 'seats2022': RD_SEATS_2022,
        'blocks': blocks(rd_seats), 'blocks2022': blocks(RD_SEATS_2022),
    }

    # ---------- VALKRETSAR (RD 2026 ur allresults; 2022 aggregerat ur distriktens serier) ----------
    vk_map = {v['namn']: k for k, v in d.get('riksvalkretsar', {}).items()}
    vk22 = defaultdict(lambda: defaultdict(float)); vk22w = defaultdict(float)
    for ds in d['districts']:
        e = ds.get('el', {}).get('RD') or {}
        ser = e.get('series') or ds.get('series') or {}; w = (e.get('w') or [0,0,0,0])
        w22 = w[2] or 0
        if not w22: continue
        vk = ds.get('vk')
        if not vk: continue
        vk22w[vk] += w22
        for p in PIDS:
            s = ser.get(p)
            if s and s[2] is not None: vk22[vk][p] += s[2]*w22
    valkretsar_out = []
    for name, rows in ar.get('valkrets', {}).items():
        if not rows.get('RD'): continue            # allresults.valkrets kan även innehålla RF/KF-valkretsar
        r26 = alist(rows.get('RD', [])); k = vk_map.get(name)
        r22 = {p: round(vk22[k][p]/vk22w[k], 2) for p in PIDS} if k and vk22w[k] else {}
        tp = top_parties(r26, r22)
        valkretsar_out.append({'namn': name, 'kod': k, 'fasta': d.get('riksvalkretsar', {}).get(k, {}).get('fasta'),
                               'res': tp, 'top': tp[0]['p'] if tp else None,
                               'top22': (max(r22, key=r22.get) if r22 else None)})
    valkretsar_out.sort(key=lambda x: x['namn'])

    # ---------- REGIONER (RF) ----------
    regioner = []
    for lk in sorted(seatsL):
        tot = seatsL[lk]
        r26 = alist(ar['region'].get(lk, {}).get('RF', [])); r22 = hist2022(ah['lan'].get(lk, {}).get('RF'))
        if not r26: continue
        s26 = seats_from_shares(r26, tot, 3.0); s22 = seats_from_shares(r22, tot, 3.0)
        rname = lan_to_region_name(lk)
        led = np_reg.get(rname, []) if rname else []
        regioner.append({
            'kod': lk, 'lan': lanNamn.get(lk, lk), 'namn': rname or ('Region ' + lanNamn.get(lk, lk).replace(' län', '')),
            'tot': tot, 'res': top_parties(r26, r22), 'seats': s26, 'seats22': s22,
            'blocks': blocks(s26), 'blocks22': blocks(s22),
            'ledning': [x for x in led if x['organ'] == 'Regionstyrelsen'],
            'listettor': listettor('RF', lk, [p for p in s26 if s26[p] > 0]),
            'rd': rd_area('lan', lk)[:4],
        })

    # ---------- KOMMUNER (KF) ----------
    kommuner = []
    for kk in sorted(seatsK):
        tot = seatsK[kk]
        r26 = alist(ar['kommun'].get(kk, {}).get('KF', [])); r22 = hist2022(ah['kommun'].get(kk, {}).get('KF'))
        if not r26: continue
        thr = 3.0 if valkretsar.get(kk, 1) > 1 else 2.0
        s26 = seats_from_shares(r26, tot, thr); s22 = seats_from_shares(r22, tot, thr)
        st = styre.get(kk, {})
        st_parts = [p for p in (st.get('partier') or '').split(',') if p]
        # styrets mandat 2026: riksdagspartierna säkert; ÖP = alla icke-riksdagspartier (max)
        sure = sum(s26.get(p, 0) for p in st_parts if p in PIDS)
        loc = sum(v for p, v in s26.items() if p not in PIDS)
        st_min = sure; st_max = sure + (loc if 'ÖP' in st_parts else 0)
        sure22 = sum(s22.get(p, 0) for p in st_parts if p in PIDS)
        loc22 = sum(v for p, v in s22.items() if p not in PIDS)
        st22_min = sure22; st22_max = sure22 + (loc22 if 'ÖP' in st_parts else 0)
        maj = tot//2 + 1
        status = None
        if st_parts:
            if st_min >= maj: status = 'majoritet'
            elif st_max >= maj: status = 'beror på lokalt parti'
            else: status = 'saknar majoritet'
        kommuner.append({
            'kod': kk, 'namn': kod2kom.get(kk, kk), 'lan': kk[:2], 'folk': folk.get(kk), 'tot': tot, 'maj': maj,
            'res': top_parties(r26, r22), 'seats': s26, 'seats22': s22, 'blocks': blocks(s26), 'blocks22': blocks(s22),
            'styre': {'partier': st_parts, 'kso': st.get('kso_parti'), 'majmin': st.get('majmin'), 'kat': st.get('kategori'),
                      'min': st_min, 'max': st_max, 'min22': st22_min, 'max22': st22_max, 'status': status} if st_parts else None,
            'ledning': [x for x in np_kom.get(kk, [])],
            'listettor': listettor('KF', kk, [p for p in s26 if s26[p] > 0 and p in PIDS]),
            'rd': rd_area('kommun', kk)[:3],
        })
    n_styre = sum(1 for k in kommuner if k['styre'])
    styre_stat = {'n': n_styre,
                  'majoritet': sum(1 for k in kommuner if k['styre'] and k['styre']['status'] == 'majoritet'),
                  'beror': sum(1 for k in kommuner if k['styre'] and k['styre']['status'] == 'beror på lokalt parti'),
                  'saknar': sum(1 for k in kommuner if k['styre'] and k['styre']['status'] == 'saknar majoritet')}
    # största parti-skiften KF
    skiften = []
    for k in kommuner:
        t26 = k['res'][0]['p'] if k['res'] else None
        r22 = hist2022(ah['kommun'].get(k['kod'], {}).get('KF'))
        t22 = max(r22, key=r22.get) if r22 else None
        if t26 and t22 and t26 != t22: skiften.append({'kod': k['kod'], 'namn': k['namn'], 'fran': t22, 'till': t26, 'folk': k['folk']})
    skiften.sort(key=lambda x: -(x['folk'] or 0))

    # ---------- AVVIKELSER ----------
    nat_chg = {r['p']: r['chg'] for r in riket['res'] if r['chg'] is not None}
    avv_kom = {p: [] for p in PIDS}
    for k in kommuner:
        for r in rd_area('kommun', k['kod']):
            p = r['p']
            if p in nat_chg:
                avv_kom[p].append({'kod': k['kod'], 'namn': k['namn'], 'a': r['a'], 'chg': r['chg'], 'rel': round(r['chg']-nat_chg[p], 2), 'folk': k['folk']})
    avvikelser = {}
    for p in PIDS:
        rows = sorted(avv_kom[p], key=lambda x: x['rel'])
        avvikelser[p] = {'ned': rows[:8], 'upp': rows[-8:][::-1]}
    # distrikt: största rörelser (viktade >= 500 röstberättigade)
    dist_sw = {p: [] for p in PIDS}
    for ds in d['districts']:
        if (ds.get('rost') or 0) < 500: continue
        ch = ds.get('changes') or {}
        for p in PIDS:
            c = ch.get(p)
            if c is None or abs(c) < 1e-9: continue
            dist_sw[p].append({'namn': ds['namn'], 'kommun': ds['kommun'], 'a': (ds.get('shares') or {}).get(p), 'chg': c})
    dist_out = {}
    for p in PIDS:
        rows = sorted(dist_sw[p], key=lambda x: x['chg'])
        dist_out[p] = {'ned': rows[:6], 'upp': rows[-6:][::-1]}
    # spridning: andel distrikt där partiet gick upp resp. ned
    spread = {}
    for p in PIDS:
        rows = dist_sw[p]
        if rows:
            up = sum(1 for r in rows if r['chg'] > 0); spread[p] = {'n': len(rows), 'upp': up, 'ned': len(rows)-up,
                'median': sorted(r['chg'] for r in rows)[len(rows)//2]}

    # ---------- DEMOGRAFI: samband nivå 2026 och förändring 2022->2026 per faktor ----------
    covKeys = d.get('covKeys', []); covMeta = d.get('cov', {})
    FAC_LAB = {'income': 'Inkomst', 'edu': 'Utbildning', 'foreign': 'Utländsk bakgrund', 'age': 'Ålder',
               'hyra': 'Hyresrätt', 'turnout': 'Valdeltagande', 'urban': 'Stad–land', 'syss': 'Sysselsättning'}
    demo = {'faktorer': [], 'niva': {}, 'chg': {}}
    for f in covKeys:
        xs = []; lvl = {p: [] for p in PIDS}; chg = {p: [] for p in PIDS}; ws = []
        for ds in d['districts']:
            x = ds.get(f); w = ds.get('rost') or 0
            if x is None or w <= 0: continue
            sh = ds.get('shares') or {}; ch = ds.get('changes') or {}
            if not sh: continue
            xs.append(x); ws.append(w)
            for p in PIDS:
                lvl[p].append(sh.get(p) or 0); chg[p].append(ch.get(p) or 0)
        if len(xs) < 50: continue
        lab = (covMeta.get(f) or {}).get('label') if isinstance(covMeta.get(f), dict) else None
        demo['faktorer'].append({'key': f, 'lab': lab or FAC_LAB.get(f, f), 'n': len(xs)})
        demo['niva'][f] = {p: (None if (c := wpearson(xs, lvl[p], ws)) is None else round(c, 2)) for p in PIDS}
        demo['chg'][f] = {p: (None if (c := wpearson(xs, chg[p], ws)) is None else round(c, 2)) for p in PIDS}

    # ---------- LÄN (RD-förändring per län, geografi) ----------
    lan_out = []
    for lk in sorted(lanKod.values()):
        tp = rd_area('lan', lk)
        if not tp: continue
        lan_out.append({'kod': lk, 'namn': lanNamn.get(lk, lk), 'res': tp, 'top': tp[0]['p'],
                        'top22': max(tp, key=lambda x: x['b'])['p']})

    payload = dict(
        meta=dict(built=d['meta'].get('built'), status=d['meta'].get('status'), live=d['meta'].get('live'), final=final, liveVal=live),
        parties=parties, PN=PN, PIDS=PIDS, LEFT=LEFT, RIGHT=RIGHT,
        riket=riket, valkretsar=valkretsar_out, lan=lan_out, regioner=regioner, kommuner=kommuner,
        styreStat=styre_stat, skiften=skiften, avvikelser=avvikelser, distrikt=dist_out, spread=spread, demo=demo,
        geo=dict(w=d.get('geoW', 1000), h=d.get('geoH', 2304), lan=d.get('granser', {}).get('lan', {}), lanNamn=lanNamn),
    )
    html = PAGE.replace('/*__DATA__*/', json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    with open(a.out, 'w', encoding='utf-8') as f: f.write(html)
    print(f"Skrev {a.out}: {len(kommuner)} kommuner ({n_styre} med styre), {len(regioner)} regioner, "
          f"{len(valkretsar_out)} valkretsar, {len(demo['faktorer'])} faktorer, {len(payload['geo']['lan'])} län på kartan. "
          f"Styre 2026: {styre_stat}. Live: {live}")

PAGE = r"""<!doctype html>
<html lang="sv"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eftervalsanalys – valutfall.se</title>
<style>
 :root{--paper:#f3f5f7;--surface:#fff;--surface2:#eaeef2;--ink:#161b22;--ink2:#4c5563;--ink3:#727c8a;
  --line:#dce1e7;--accent:#0e7c74;--accent2:#0b605a;--pos:#2e7d5b;--neg:#b0313f;--warn:#9a6a00;--warnbg:#f6ecd0;
  --shadow:0 1px 2px rgba(16,22,30,.05),0 8px 22px -14px rgba(16,22,30,.22)}
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;
  --ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;--line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88;--warn:#e2b75a;--warnbg:#2b2617;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 28px -16px rgba(0,0,0,.6)}}
 :root[data-theme=dark]{--paper:#0e1319;--surface:#161c24;--surface2:#1e2630;--ink:#e9ecf0;--ink2:#9ba5b2;--ink3:#79838f;
  --line:#28313c;--accent:#3db6ac;--accent2:#59c6bc;--pos:#54c08d;--neg:#e27c88;--warn:#e2b75a;--warnbg:#2b2617}
 *{box-sizing:border-box}
 body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
 .wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px}
 a{color:var(--accent2)}
 header.top{padding:22px 0 12px}
 .rowb{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
 .eyebrow{font:600 .72rem/1 system-ui;letter-spacing:.14em;text-transform:uppercase;color:var(--accent2)}
 h1{margin:8px 0 4px;font-size:1.8rem;letter-spacing:-.01em}
 h2{font-size:1.15rem;margin:22px 0 8px} h3{font-size:1rem;margin:16px 0 6px}
 .sub{color:var(--ink2);margin:0;max-width:68ch;font-size:.95rem}
 .meta{margin-top:10px;font:.75rem/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink3);display:flex;gap:6px 16px;flex-wrap:wrap}
 .btn{background:var(--surface);color:var(--ink2);border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer;font:.78rem system-ui}
 .btn:hover{border-color:var(--accent);color:var(--accent2)}
 .caveat{margin:12px 0 0;padding:10px 14px;border-radius:10px;background:var(--surface2);color:var(--ink2);font-size:.82rem}
 .warn{margin:12px 0 0;padding:10px 14px;border-radius:10px;background:var(--warnbg);color:var(--warn);font-size:.85rem;font-weight:600}
 .banner{display:none;margin:12px 0 0;padding:10px 14px;border-radius:10px;background:#f3e7c9;color:#8a6200;font-size:.9rem;font-weight:600}
 .banner.show{display:block}
 .tabs{display:flex;gap:4px;flex-wrap:wrap;margin:16px 0 0}
 .tab{flex:1 1 auto;min-width:100px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:9px 12px;cursor:pointer;font:600 .88rem system-ui;color:var(--ink2)}
 .tab[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}
 .panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);margin-top:10px}
 .lead{color:var(--ink2);font-size:.92rem;margin:0 0 10px}
 .note{color:var(--ink3);font-size:.78rem;margin-top:10px}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 14px}
 .kpi{background:var(--surface2);border-radius:10px;padding:10px 12px}
 .kpi .v{font-size:1.5rem;font-weight:700;line-height:1.1} .kpi .l{font-size:.78rem;color:var(--ink3)}
 .kpi .d{font-size:.8rem;color:var(--ink2)}
 table{width:100%;border-collapse:collapse;font-size:.88rem} th,td{padding:7px 8px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
 th{color:var(--ink3);font-weight:600;font-size:.78rem;border-top:none} td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
 tr.click{cursor:pointer} tr.click:hover td{background:var(--surface2)}
 .pf{font:.72rem ui-monospace,monospace;color:#fff;border-radius:5px;padding:1px 6px;white-space:nowrap}
 .pos{color:var(--pos)} .neg{color:var(--neg)} .muted{color:var(--ink3)}
 .bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--surface2);margin:6px 0}
 .bar span{display:block;height:100%}
 .seatbar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:8px 0;position:relative}
 .seatbar span{display:flex;align-items:center;justify-content:center;font:600 .7rem system-ui;color:#fff;overflow:hidden;white-space:nowrap}
 .seatbar .mid{position:absolute;left:50%;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
 .chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
 .chip{border:1.5px solid var(--line);background:var(--surface);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:.84rem;color:var(--ink2)}
 .chip.on{color:#fff;border-color:transparent} .chip:hover{border-color:var(--accent)}
 .chip.gov.on{box-shadow:0 0 0 2px var(--accent) inset}
 .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:6px 0 10px}
 .ctl{display:flex;flex-direction:column;gap:4px} .ctl label{font:.7rem/1 system-ui;letter-spacing:.03em;text-transform:uppercase;color:var(--ink3)}
 select,input[type=search]{border:1px solid var(--line);background:var(--surface2);color:var(--ink);border-radius:9px;padding:8px 10px;font:inherit}
 .seg{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--line);background:var(--surface2);border-radius:9px}
 .seg button{border:none;background:none;color:var(--ink2);border-radius:7px;padding:6px 12px;cursor:pointer;font:600 .85rem system-ui}
 .seg button[aria-pressed=true]{background:var(--accent);color:#fff}
 .status{display:inline-block;border-radius:6px;padding:2px 7px;font-size:.76rem;font-weight:600}
 .s-maj{background:rgba(46,125,91,.15);color:var(--pos)} .s-sak{background:rgba(176,49,63,.15);color:var(--neg)} .s-ber{background:var(--warnbg);color:var(--warn)} .s-na{background:var(--surface2);color:var(--ink3)}
 .detail{background:var(--surface2);border-radius:10px;padding:12px 14px;margin:8px 0 14px}
 .detail h3{margin-top:0}
 .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
 .maprow{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;margin-top:14px}
 .mapbox{flex:0 0 150px;max-width:38vw}
 svg.map{width:100%;height:auto;display:block} svg.map path{fill:var(--surface2);stroke:var(--paper);stroke-width:1.2;cursor:pointer}
 svg.map path:hover{fill:var(--accent)} svg.map path.sel{fill:var(--accent);stroke:var(--accent2)}
 .selchip{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;border-radius:999px;padding:5px 8px 5px 13px;font-size:.82rem;font-weight:600}
 .selchip button{background:rgba(255,255,255,.25);border:none;color:#fff;width:20px;height:20px;border-radius:50%;cursor:pointer}
 .explain{background:var(--surface2);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;padding:0 13px}
 .explain summary{cursor:pointer;padding:10px 0;font-weight:600;font-size:.85rem;color:var(--accent2)}
 .explain .body{padding:0 0 10px} .explain p{margin:0 0 8px;font-size:.86rem;color:var(--ink2)}
 .takeaway{background:var(--surface2);border-left:3px solid var(--accent);border-radius:8px;padding:10px 13px;margin:12px 0;font-size:.92rem}
 .tw{overflow-x:auto}
 .corr{display:inline-block;height:9px;border-radius:5px;vertical-align:middle}
 footer{padding-top:24px;margin-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:.8rem}
 @media(prefers-reduced-motion:reduce){*{transition:none!important}}
 @media(max-width:600px){.wrap{padding:0 12px 48px} h1{font-size:1.5rem} table{font-size:.82rem} th,td{padding:6px 5px}}
</style></head>
<body><div class="wrap">
<header class="top">
 <div class="rowb"><span class="eyebrow">valutfall.se · eftervalsanalys · del 1</span>
  <span><a class="btn" href="/" style="text-decoration:none">Resultat</a> <a class="btn" href="/valjaranalys.html" style="text-decoration:none">Väljaranalys</a> <button class="btn" id="theme" type="button" aria-label="Byt tema">☾ / ☀</button></span></div>
 <h1>Eftervalsanalys – valet 2026</h1>
 <p class="sub">Valresultat och mandat med förändring mot 2022, regeringsbildningens matematik, majoritetspussel i regioner och kommuner, nyckelspelare, avvikelser i väljarbeteendet och vad demografin säger. Underlag för del 1 i eftervalsanalysen.</p>
 <div class="meta" id="meta"></div>
 <div id="finalnote"></div>
 <div class="banner" id="banner">Nya siffror finns – sidan uppdateras…</div>
</header>

<div class="tabs" id="tabs" role="tablist">
 <button class="tab" role="tab" data-mode="riket">Riket</button>
 <button class="tab" role="tab" data-mode="regering">Regeringsbildning</button>
 <button class="tab" role="tab" data-mode="regioner">Regioner</button>
 <button class="tab" role="tab" data-mode="kommuner">Kommuner</button>
 <button class="tab" role="tab" data-mode="avvikelser">Avvikelser</button>
 <button class="tab" role="tab" data-mode="demografi">Demografi</button>
 <button class="tab" role="tab" data-mode="sektor">Sektorer</button>
</div>
<div class="panel" id="panel"></div>

<div class="maprow" id="maprow">
 <div class="mapbox"><svg class="map" id="map" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Karta över län"></svg></div>
 <div style="flex:1;min-width:220px" class="muted" id="maphelp"></div>
</div>

<footer>
 <p id="src"></p>
 <p>Underlag: Valmyndigheten (röster och mandat), SCB (distriktskovariater), Faktadriven (styre per kommun efter valet 2022, folkmängd 2024), Plenum via nyckelpersoner.csv (ordförande och vice i kommun- och regionstyrelser 2022–2026). Region- och kommunmandat räknas ur områdesandelarna med jämkade uddatalsmetoden och är approximativa; personröster ingår inte. En del av <a href="/">valutfall.se</a> · Sandro Wennberg.</p>
</footer>
</div>

<script>
const DATA = /*__DATA__*/;
const $=s=>document.querySelector(s); const PN=DATA.PN; const PIDS=DATA.PIDS;
const COL=Object.fromEntries(DATA.parties.map(p=>[p.id,p.color])); COL['ÖP']='#7a8390';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const col=p=>COL[p]||'#7a8390';
const pf=p=>`<span class="pf" style="background:${col(p)}">${esc(p)}</span>`;
const f1=v=>v==null?'–':(Math.round(v*10)/10).toFixed(1).replace('.',',');
const sg=v=>v==null?'<span class="muted">–</span>':`<span class="${v>0?'pos':v<0?'neg':'muted'}">${v>0?'+':''}${f1(v)}</span>`;
const sgi=v=>v==null?'–':`<span class="${v>0?'pos':v<0?'neg':'muted'}">${v>0?'+':''}${v}</span>`;
const fmt=n=>n==null?'–':Math.round(n).toLocaleString('sv-SE');
let mode='riket', selLan=null, openKod=null, kSort='folk', kFilter='stora', kQuery='', regOpen=null, avvP='S', demoView='chg';
const gov=new Set(), sup=new Set();

// ---------- tema ----------
(function(){const t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);
 $('#theme').onclick=()=>{const cur=document.documentElement.getAttribute('data-theme');const next=cur==='dark'?'light':(cur==='light'?'':'dark');
  if(next)document.documentElement.setAttribute('data-theme',next);else document.documentElement.removeAttribute('data-theme');localStorage.setItem('theme',next);};})();

function head(){const m=DATA.meta;const b=m.built?new Date(m.built):null;
 $('#meta').innerHTML=`<span>${esc(m.status||'')}</span>${b?`<span>byggd ${b.toLocaleString('sv-SE',{dateStyle:'short',timeStyle:'short'})}</span>`:''}`;
 const fin=m.final||{}; const vals=[['RD','Riksdag'],['RF','Region'],['KF','Kommun']];
 const lv=m.liveVal||{};
 const parts=vals.map(([k,l])=>lv[k]===false?`<b>${l}:</b> 2022-spegling (ingen 2026-data inläst)`:fin[k]?`<b>${l}:</b> slutligt (${esc(fin[k])})`:`<b>${l}:</b> preliminärt`);
 const missing=vals.filter(([k])=>lv[k]===false).map(([,l])=>l.toLowerCase()+'valet');
 $('#finalnote').innerHTML=`<div class="caveat">${parts.join(' · ')}. Tills alla tre valen är fastställda kan andelar och mandat ändras något. Region- och kommunmandat på den här sidan är beräknade ur andelarna, inte hämtade från Valmyndighetens mandatbeslut.</div>`+
  (missing.length?`<div class="warn">Resultaten för ${missing.join(' och ')} 2026 finns inte i underlaget än – flikarna Regioner och Kommuner visar 2022 års utfall som platshållare. Riksdagsvalet (även per län och kommun) är 2026.</div>`:'');
 $('#src').textContent=`Byggd ur data.json (${m.built||''}).`;}

function seatBar(seats,order,tot){const t=tot||Object.values(seats).reduce((a,b)=>a+b,0);
 const ps=[...order.filter(p=>seats[p]),...Object.keys(seats).filter(p=>!order.includes(p)&&seats[p]).sort((a,b)=>seats[b]-seats[a])];
 return `<div class="seatbar">${ps.map(p=>`<span style="width:${100*seats[p]/t}%;background:${col(p)}" title="${esc(PN[p]||p)} ${seats[p]}">${100*seats[p]/t>6?esc(p)+' '+seats[p]:''}</span>`).join('')}<div class="mid" title="Majoritetsgräns"></div></div>`;}
const ORDER=['V','S','MP','C','L','KD','M','SD'];

function resTable(res,ovriga,seats,seats22){
 const hasSeats=!!seats;
 return `<div class="tw"><table><thead><tr><th>Parti</th><th class="r">2026 %</th><th class="r">±2022</th>${hasSeats?'<th class="r">Mandat</th><th class="r">±</th>':''}</tr></thead><tbody>${
 res.map(r=>`<tr><td>${pf(r.p)} ${esc(PN[r.p]||r.p)}</td><td class="r">${f1(r.a)}</td><td class="r">${sg(r.chg)}</td>${hasSeats?`<td class="r">${seats[r.p]??0}</td><td class="r">${seats22?sgi((seats[r.p]||0)-(seats22[r.p]||0)):'–'}</td>`:''}</tr>`).join('')}
 ${ovriga!=null?`<tr><td class="muted">Övriga partier</td><td class="r muted">${f1(ovriga)}</td><td></td>${hasSeats?'<td></td><td></td>':''}</tr>`:''}</tbody></table></div>`;}

function blockLine(b,b22,tot){const maj=Math.floor(tot/2)+1;
 return `<p class="lead" style="margin-top:8px"><b>S+V+MP+C:</b> ${b.L} mandat ${b22?`(${sgi(b.L-b22.L)})`:''} · <b>M+KD+L+SD:</b> ${b.R} ${b22?`(${sgi(b.R-b22.R)})`:''}${b.O?` · <b>övriga/lokala:</b> ${b.O}`:''} · majoritet vid ${maj} av ${tot}.</p>`;}

// ---------- RIKET ----------
function renderRiket(){const r=DATA.riket;const tot=349;const b=r.blocks,b22=r.blocks2022;
 const vk=DATA.valkretsar;const lan=DATA.lan;
 const skift=lan.filter(l=>l.top&&l.top22&&l.top!==l.top22);
 $('#panel').innerHTML=`<h2 style="margin-top:0">Riksdagsvalet</h2>
 <div class="kpis">
  <div class="kpi"><div class="v">${b.L}–${b.R}</div><div class="l">S+V+MP+C mot M+KD+L+SD (mandat)</div><div class="d">2022: ${b22.L}–${b22.R}</div></div>
  <div class="kpi"><div class="v">${r.res[0]?pf(r.res[0].p):''} ${f1(r.res[0]?.a)} %</div><div class="l">Största parti</div><div class="d">${sg(r.res[0]?.chg)} procentenheter</div></div>
  <div class="kpi"><div class="v">${r.res.filter(x=>x.chg>0).length} av ${r.res.length}</div><div class="l">Riksdagspartier som ökade</div><div class="d">${r.res.filter(x=>x.chg>0).map(x=>x.p).join(', ')}</div></div>
 </div>
 ${seatBar(r.seats,ORDER,tot)}
 ${resTable(r.res,r.ovriga,r.seats,r.seats2022)}
 ${blockLine(b,b22,tot)}
 <div class="takeaway">${takeawayRiket(r)}</div>
 <h2>Län</h2><p class="lead">Riksdagsvalet per län, aggregerat ur jämförbara valdistrikt (viktat med röstberättigade). ${skift.length?`Största parti bytte i ${skift.length} län: ${skift.map(l=>esc(l.namn)+' ('+l.top22+'→'+l.top+')').join(', ')}.`:'Största parti är oförändrat i alla län.'} Klicka på ett län i kartan för att se kommunerna.</p>
 <div class="tw"><table><thead><tr><th>Län</th><th>Störst</th>${PIDS.map(p=>`<th class="r">${p}</th>`).join('')}</tr></thead><tbody>${
  lan.map(l=>{const m=Object.fromEntries(l.res.map(x=>[x.p,x]));return `<tr class="click" data-lan="${l.kod}"><td>${esc(l.namn)}</td><td>${pf(l.top)}</td>${PIDS.map(p=>`<td class="r">${f1(m[p]?.a)}<br><small>${sg(m[p]?.chg)}</small></td>`).join('')}</tr>`}).join('')}</tbody></table></div>
 <h2>Riksdagsvalkretsar</h2><p class="lead">Andel 2026 och förändring mot 2022 (2022 aggregerat ur valdistrikten).</p>
 <div class="tw"><table><thead><tr><th>Valkrets</th><th class="r">Fasta</th><th>Störst</th>${PIDS.map(p=>`<th class="r">${p}</th>`).join('')}</tr></thead><tbody>${
  vk.map(v=>{const m=Object.fromEntries(v.res.map(x=>[x.p,x]));return `<tr><td>${esc(v.namn)}</td><td class="r">${v.fasta??'–'}</td><td>${pf(v.top)}${v.top22&&v.top22!==v.top?` <small class="muted">(2022: ${v.top22})</small>`:''}</td>${PIDS.map(p=>`<td class="r">${f1(m[p]?.a)}<br><small>${sg(m[p]?.chg)}</small></td>`).join('')}</tr>`}).join('')}</tbody></table></div>
 <p class="note">Riksdagsmandaten är räknade ur exakta röstetal med Valmyndighetens metod (310 fasta + 39 utjämningsmandat, spärr 4 % nationellt eller 12 % i en valkrets). 2022 års mandat: Valmyndighetens slutliga resultat.</p>`;
 $('#panel').querySelectorAll('tr[data-lan]').forEach(tr=>tr.onclick=()=>{selectLan(tr.dataset.lan);setMode('kommuner');});}
function takeawayRiket(r){const up=r.res.filter(x=>x.chg>0).sort((a,b)=>b.chg-a.chg),dn=r.res.filter(x=>x.chg<0).sort((a,b)=>a.chg-b.chg);
 const s=[];if(up.length)s.push(`Störst ökning: ${up.slice(0,2).map(x=>PN[x.p]+' ('+sg(x.chg)+')').join(' och ')}.`);
 if(dn.length)s.push(`Störst tapp: ${dn.slice(0,2).map(x=>PN[x.p]+' ('+sg(x.chg)+')').join(' och ')}.`);
 const b=r.blocks;s.push(b.L>=175?`S+V+MP+C har egen majoritet i riksdagen (${b.L} mandat).`:b.R>=175?`M+KD+L+SD har egen majoritet i riksdagen (${b.R} mandat).`:`Ingen av sidorna når 175 mandat.`);return s.join(' ');}

// ---------- REGERINGSBILDNING ----------
function renderRegering(){const r=DATA.riket;const seats=r.seats;
 const g=[...gov].reduce((a,p)=>a+(seats[p]||0),0), s=[...sup].reduce((a,p)=>a+(seats[p]||0),0);
 const against=349-g-s; const tolerated=against<175;
 const chip=(p,set,cls)=>`<button class="chip ${cls} ${set.has(p)?'on':''}" data-p="${p}" data-set="${cls}" style="${set.has(p)?'background:'+col(p):''}">${esc(p)} ${seats[p]||0}</button>`;
 const presets=[['S+C+MP med V',['S','C','MP'],['V']],['S+V+MP+C',['S','V','MP','C'],[]],['M+KD+L med SD',['M','KD','L'],['SD']],['S+M',['S','M'],[]],['Rensa',[],[]]];
 $('#panel').innerHTML=`<h2 style="margin-top:0">Koalitionsräknare</h2>
 <details class="explain"><summary>Så fungerar räknaren</summary><div class="body"><p>Välj vilka partier som <b>bildar regering</b> och vilka som <b>släpper fram</b> den (stödpartier). En statsminister fälls i riksdagens omröstning bara om <b>minst 175</b> ledamöter röstar emot (negativ parlamentarism). Egen majoritet kräver 175 av 349 mandat.</p><p>Räknaren visar aritmetik, inte sannolikheter. Vilka konstellationer som är politiskt möjliga avgörs i förhandlingarna.</p></div></details>
 <p class="lead">Regering:</p><div class="chips">${ORDER.map(p=>chip(p,gov,'gov')).join('')}</div>
 <p class="lead">Släpper fram (stöd):</p><div class="chips">${ORDER.map(p=>chip(p,sup,'sup')).join('')}</div>
 <div class="chips" style="margin-top:10px">${presets.map((x,i)=>`<button class="btn" data-preset="${i}">${esc(x[0])}</button>`).join('')}</div>
 <div class="kpis" style="margin-top:14px">
  <div class="kpi"><div class="v">${g}</div><div class="l">Regeringens egna mandat</div><div class="d">${g>=175?'egen majoritet':g>0?'minoritet':'–'}</div></div>
  <div class="kpi"><div class="v">${g+s}</div><div class="l">Regering + stöd</div><div class="d">${g+s>=175?'majoritet i kammaren':'under 175'}</div></div>
  <div class="kpi"><div class="v">${against}</div><div class="l">Kan rösta emot</div><div class="d">${gov.size?(tolerated?'släpps fram (färre än 175 emot)':'fälls om alla övriga röstar emot'):'välj partier'}</div></div>
 </div>
 ${seatBar(seats,ORDER,349)}
 <div class="takeaway">${regeringText(g,s,against)}</div>
 <h3>Partiernas mandat</h3>${resTable(r.res,null,seats,r.seats2022)}
 <p class="note">Statsministeromröstningen regleras i regeringsformen 6 kap. 4 §: förslaget är förkastat om mer än hälften av ledamöterna röstar emot. Räknaren bygger på riksdagens mandatfördelning 2026 i data.json.</p>`;
 $('#panel').querySelectorAll('.chip').forEach(b=>b.onclick=()=>{const p=b.dataset.p;const set=b.dataset.set==='gov'?gov:sup;const other=b.dataset.set==='gov'?sup:gov;
  if(set.has(p))set.delete(p);else{set.add(p);other.delete(p);}renderRegering();});
 $('#panel').querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{const [,gp,sp]=presets[+b.dataset.preset];gov.clear();sup.clear();gp.forEach(p=>gov.add(p));sp.forEach(p=>sup.add(p));renderRegering();});}
function regeringText(g,s,against){if(!gov.size)return 'Välj partier ovan eller använd ett exempel. Exemplen är räkneexempel, inte bedömningar av vad som är troligt.';
 const gl=[...gov].join('+');const parts=[];
 parts.push(`${gl} har ${g} mandat${g>=175?' – egen majoritet.':' – en minoritetsregering.'}`);
 if(sup.size)parts.push(`Med stöd av ${[...sup].join('+')} når konstellationen ${g+s} mandat${g+s>=175?', majoritet i kammaren.':', fortfarande under 175.'}`);
 parts.push(against<175?`Övriga partier har ${against} mandat och kan inte fälla statsministern på egen hand.`:`Övriga partier har ${against} mandat och kan fälla statsministern om alla röstar emot.`);
 if(g<175)parts.push('En minoritetsregering utan stödavtal måste söka majoritet fråga för fråga i riksdagen, vilket flyttar tyngd till utskotten.');
 return parts.join(' ');}

// ---------- REGIONER ----------
function renderRegioner(){let rows=DATA.regioner;if(selLan)rows=rows.filter(r=>r.kod===selLan);
 const skift=DATA.regioner.filter(r=>{const t=r.res[0]?.p;const s22=r.seats22;const t22=Object.keys(s22).sort((a,b)=>s22[b]-s22[a])[0];return t&&t22&&t!==t22;});
 const flips=DATA.regioner.filter(r=>(r.blocks.L>r.blocks.R)!==(r.blocks22.L>r.blocks22.R));
 const base=DATA.meta.liveVal&&DATA.meta.liveVal.RF===false;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Regionerna – majoritetspussel</h2>${base?'<div class="warn" style="margin:0 0 12px">Regionvalet 2026 är inte inläst. Mandat och block nedan speglar 2022 och "förändringar" är därför noll. Riksdagsvalet i länet (i detaljvyn) är 2026.</div>':''}
 <details class="explain"><summary>Vad tabellen visar</summary><div class="body"><p>Mandat per region 2026 och 2022, beräknade ur regionvalets andelar med jämkade uddatalsmetoden (spärr 3 %). Regionen räknas som en valkrets, så enstaka mandat kan avvika från länsstyrelsens fördelning. <b>Ordf.</b> = regionstyrelsens ordförande 2022–2026 (Plenum). Klicka på en rad för detaljer, koalitionsräknare och listettor 2026.</p><p>Gotland har inget regionval; regionens fullmäktige väljs i kommunvalet och visas under Kommuner.</p></div></details>
 <div class="kpis">
  <div class="kpi"><div class="v">${flips.length}</div><div class="l">Regioner där blockövervikten bytte sida</div><div class="d">${flips.map(r=>esc(r.namn.replace('Region ',''))).join(', ')||'–'}</div></div>
  <div class="kpi"><div class="v">${DATA.regioner.filter(r=>r.blocks.L>Math.floor(r.tot/2)||r.blocks.R>Math.floor(r.tot/2)).length} av ${DATA.regioner.length}</div><div class="l">Regioner där en sida har egen majoritet</div><div class="d">övriga kräver blocköverskridande lösning eller lokala partier</div></div>
  <div class="kpi"><div class="v">${skift.length}</div><div class="l">Regioner med nytt största parti</div><div class="d">${skift.map(r=>esc(r.namn.replace('Region ',''))).join(', ')||'–'}</div></div>
 </div>
 <div class="tw"><table><thead><tr><th>Region</th><th>Störst</th><th class="r">S+V+MP+C</th><th class="r">M+KD+L+SD</th><th class="r">Övr.</th><th class="r">Maj.</th><th>Ordf. 2022–26</th></tr></thead><tbody>${
  rows.map(r=>{const o=r.ledning.find(x=>/^ordf/i.test(x.roll));const maj=Math.floor(r.tot/2)+1;
   return `<tr class="click" data-reg="${r.kod}"><td><b>${esc(r.namn)}</b></td><td>${pf(r.res[0]?.p)} ${f1(r.res[0]?.a)}</td>
   <td class="r">${r.blocks.L} <small>${sgi(r.blocks.L-r.blocks22.L)}</small></td><td class="r">${r.blocks.R} <small>${sgi(r.blocks.R-r.blocks22.R)}</small></td><td class="r">${r.blocks.O}</td><td class="r">${maj}/${r.tot}</td>
   <td>${o?esc(o.namn)+' '+pf(o.p):'<span class="muted">–</span>'}</td></tr>${regOpen===r.kod?`<tr><td colspan="7">${regionDetail(r)}</td></tr>`:''}`}).join('')}</tbody></table></div>
 <p class="note">Koalitioner i regionerna 2022–2026 visas inte eftersom en verifierad källa saknas i underlaget; ordförandeposten ger sittande styrets tyngdpunkt.</p>`;
 $('#panel').querySelectorAll('tr[data-reg]').forEach(tr=>tr.onclick=()=>{regOpen=regOpen===tr.dataset.reg?null:tr.dataset.reg;renderRegioner();});
 bindCoal();}
function coalCalc(id,seats,tot){const maj=Math.floor(tot/2)+1;const ps=Object.keys(seats).filter(p=>seats[p]>0).sort((a,b)=>(ORDER.indexOf(a)===-1?99:ORDER.indexOf(a))-(ORDER.indexOf(b)===-1?99:ORDER.indexOf(b)));
 return `<div class="coal" data-id="${id}" data-tot="${tot}"><p class="lead" style="margin:8px 0 4px">Räkna på en koalition (majoritet ${maj} av ${tot}):</p><div class="chips">${ps.map(p=>`<button class="chip" data-p="${esc(p)}" data-s="${seats[p]}">${esc(p)} ${seats[p]}</button>`).join('')}</div><div class="lead coalout">Välj partier.</div></div>`;}
function bindCoal(){$('#panel').querySelectorAll('.coal').forEach(box=>{const sel=new Set();const tot=+box.dataset.tot;const maj=Math.floor(tot/2)+1;
 box.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{const p=b.dataset.p;if(sel.has(p)){sel.delete(p);b.classList.remove('on');b.style.background='';}else{sel.add(p);b.classList.add('on');b.style.background=col(p);}
  const sum=[...box.querySelectorAll('.chip.on')].reduce((a,x)=>a+(+x.dataset.s),0);
  box.querySelector('.coalout').innerHTML=sel.size?`<b>${[...sel].join('+')}</b>: ${sum} mandat – ${sum>=maj?'<span class="pos">majoritet</span>':`<span class="neg">saknar ${maj-sum}</span>`}`:'Välj partier.';});});}
function ledningList(l){if(!l.length)return '<p class="muted">Inga uppgifter i personlagret.</p>';
 return `<ul style="margin:4px 0;padding-left:18px">${l.map(x=>`<li>${esc(x.namn)} ${pf(x.p)} <span class="muted">${esc(x.roll)}, ${esc(x.organ)}</span></li>`).join('')}</ul>`;}
function listettorList(le){const ps=Object.keys(le);if(!ps.length)return '<p class="muted">Inga listor i underlaget.</p>';
 return `<ul style="margin:4px 0;padding-left:18px">${ps.map(p=>`<li>${pf(p)} ${esc(le[p][0])}</li>`).join('')}</ul>`;}
function regionDetail(r){return `<div class="detail"><div class="grid2"><div><h3>Regionvalet ${esc(r.lan)}</h3>${seatBar(r.seats,ORDER,r.tot)}${resTable(r.res,null,r.seats,r.seats22)}${blockLine(r.blocks,r.blocks22,r.tot)}${coalCalc('r'+r.kod,r.seats,r.tot)}</div>
 <div><h3>Sittande ledning 2022–2026</h3>${ledningList(r.ledning)}<h3>Listettor 2026 (regionvalet)</h3>${listettorList(r.listettor)}<h3>Riksdagsvalet i länet 2026</h3><p class="note" style="margin:0 0 4px">Aggregerat ur jämförbara valdistrikt.</p><div class="tw"><table><tbody>${r.rd.map(x=>`<tr><td>${pf(x.p)}</td><td class="r">${f1(x.a)}</td><td class="r">${sg(x.chg)}</td></tr>`).join('')}</tbody></table></div></div></div></div>`;}

// ---------- KOMMUNER ----------
function statusTag(s){if(!s)return '<span class="status s-na">okänt styre</span>';const st=s.status;
 return st==='majoritet'?'<span class="status s-maj">behåller majoritet</span>':st==='saknar majoritet'?'<span class="status s-sak">saknar majoritet</span>':'<span class="status s-ber">beror på lokalt parti</span>';}
function renderKommuner(){let rows=DATA.kommuner.slice();const q=kQuery.trim().toLowerCase();
 if(selLan)rows=rows.filter(k=>k.lan===selLan);
 if(kFilter==='stora'&&!q&&!selLan)rows=rows.filter(k=>(k.folk||0)>=100000);
 if(kFilter==='saknar')rows=rows.filter(k=>k.styre&&k.styre.status!=='majoritet');
 if(q)rows=rows.filter(k=>k.namn.toLowerCase().includes(q));
 rows.sort((a,b)=>kSort==='folk'?(b.folk||0)-(a.folk||0):kSort==='namn'?a.namn.localeCompare(b.namn,'sv'):((a.styre?.min??999)-(a.maj))-((b.styre?.min??999)-(b.maj)));
 const ss=DATA.styreStat;const sk=DATA.skiften;
 const base=DATA.meta.liveVal&&DATA.meta.liveVal.KF===false;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Kommunerna – majoritetspussel</h2>${base?'<div class="warn" style="margin:0 0 12px">Kommunvalet 2026 är inte inläst. Mandat, block och "styrets mandat 2026" nedan speglar 2022 och förändringarna är noll. Riksdagsvalet i kommunen (i detaljvyn) är 2026.</div>':''}
 <details class="explain"><summary>Vad tabellen visar</summary><div class="body"><p>Mandat per kommun 2026 och 2022 räknade ur kommunvalets andelar (jämkade uddatalsmetoden, spärr 2 % eller 3 % vid flera valkretsar; kommunen räknas som en valkrets). <b>Styre 2022–26</b> = partierna i det sittande styret enligt Faktadriven. <b>Styrets mandat 2026</b> visar om samma partier skulle ha majoritet i det nya fullmäktige. ÖP = lokalt parti som inte kan identifieras i valresultatet; då visas ett intervall.</p><p>Att styret behåller majoriteten betyder inte att det fortsätter. Att det saknar majoritet betyder att något måste ändras.</p></div></details>
 <div class="kpis">
  <div class="kpi"><div class="v">${ss.saknar}</div><div class="l">Sittande styren som saknar majoritet ${base?'(2022-läge)':'efter valet'}</div><div class="d">av ${ss.n} kommuner med känt styre</div></div>
  <div class="kpi"><div class="v">${ss.majoritet}</div><div class="l">Styren ${base?'med majoritet (2022-läge)':'som behåller majoritet'}</div><div class="d">${ss.beror} beror på lokala partier</div></div>
  <div class="kpi"><div class="v">${sk.length}</div><div class="l">Kommuner med nytt största parti i KF</div><div class="d">${sk.slice(0,4).map(x=>esc(x.namn)+' ('+x.fran+'→'+x.till+')').join(', ')}${sk.length>4?' …':''}</div></div>
 </div>
 <div class="controls">
  <div class="ctl"><label>Urval</label><span class="seg" id="kf"><button data-f="stora" aria-pressed="${kFilter==='stora'}">Över 100 000 inv.</button><button data-f="alla" aria-pressed="${kFilter==='alla'}">Alla</button><button data-f="saknar" aria-pressed="${kFilter==='saknar'}">Styret saknar majoritet</button></span></div>
  <div class="ctl"><label>Sortera</label><select id="ksort"><option value="folk" ${kSort==='folk'?'selected':''}>Folkmängd</option><option value="namn" ${kSort==='namn'?'selected':''}>Namn</option><option value="marg" ${kSort==='marg'?'selected':''}>Styrets marginal</option></select></div>
  <div class="ctl"><label>Sök kommun</label><input type="search" id="kq" value="${esc(kQuery)}" placeholder="t.ex. Örebro"></div>
  <div class="ctl" id="selwrap"></div>
  <div class="ctl"><label>&nbsp;</label><button class="btn" id="kcsv">Ladda ner CSV</button></div>
 </div>
 <div class="tw"><table><thead><tr><th>Kommun</th><th class="r">Inv.</th><th>Störst KF</th><th class="r">S+V+MP+C</th><th class="r">M+KD+L+SD</th><th class="r">Övr.</th><th>Styre 2022–26</th><th class="r">Styrets mandat ${base?'(2022-spegling)':'2026'}</th><th>Läge</th></tr></thead><tbody>${
  rows.map(k=>{const s=k.styre;const sm=s?(s.min===s.max?`${s.min}`:`${s.min}–${s.max}`):'–';
   return `<tr class="click" data-kod="${k.kod}"><td><b>${esc(k.namn)}</b></td><td class="r">${fmt(k.folk)}</td><td>${pf(k.res[0]?.p)} ${f1(k.res[0]?.a)} <small>${sg(k.res[0]?.chg)}</small></td>
   <td class="r">${k.blocks.L} <small>${sgi(k.blocks.L-k.blocks22.L)}</small></td><td class="r">${k.blocks.R} <small>${sgi(k.blocks.R-k.blocks22.R)}</small></td><td class="r">${k.blocks.O}</td>
   <td>${s?s.partier.map(p=>pf(p)).join(' ')+(s.majmin?` <small class="muted">${esc(s.majmin.toLowerCase())}</small>`:''):'<span class="muted">–</span>'}</td><td class="r">${sm} <small class="muted">/ ${k.maj} av ${k.tot}</small></td><td>${statusTag(s)}</td></tr>${openKod===k.kod?`<tr><td colspan="9">${kommunDetail(k)}</td></tr>`:''}`}).join('')}
  ${rows.length?'':'<tr><td colspan="9" class="muted">Inga kommuner matchar.</td></tr>'}</tbody></table></div>
 <p class="note">${rows.length} kommuner visas. Folkmängd 2024 (SCB via Faktadriven). ÖP i styret = lokalt parti.</p>`;
 $('#panel').querySelectorAll('#kf button').forEach(b=>b.onclick=()=>{kFilter=b.dataset.f;renderKommuner();});
 $('#ksort').onchange=e=>{kSort=e.target.value;renderKommuner();};
 const kq=$('#kq');kq.oninput=e=>{kQuery=e.target.value;renderKommuner();const el=$('#kq');el.focus();el.setSelectionRange(el.value.length,el.value.length);};
 $('#kcsv').onclick=()=>downloadCSV(rows);
 $('#panel').querySelectorAll('tr[data-kod]').forEach(tr=>tr.onclick=()=>{openKod=openKod===tr.dataset.kod?null:tr.dataset.kod;renderKommuner();});
 updSel();bindCoal();}
function kommunDetail(k){const s=k.styre;
 return `<div class="detail"><div class="grid2"><div><h3>Kommunvalet ${esc(k.namn)}</h3>${seatBar(k.seats,ORDER,k.tot)}${resTable(k.res,null,k.seats,k.seats22)}${blockLine(k.blocks,k.blocks22,k.tot)}${coalCalc('k'+k.kod,k.seats,k.tot)}</div>
 <div>${s?`<h3>Sittande styre 2022–2026</h3><p class="lead">${s.partier.map(p=>pf(p)).join(' ')} – ${esc(s.majmin||'')}${s.kso?`, KSO från ${pf(s.kso)}`:''}. Samma partier: ${s.min22===s.max22?s.min22:s.min22+'–'+s.max22} mandat 2022 → ${s.min===s.max?s.min:s.min+'–'+s.max} mandat 2026 (majoritet ${k.maj}). ${statusTag(s)}</p>`:'<h3>Sittande styre</h3><p class="muted">Saknas i underlaget.</p>'}
 <h3>Ledande politiker 2022–2026</h3>${ledningList(k.ledning)}<h3>Listettor 2026 (kommunvalet)</h3>${listettorList(k.listettor)}
 <h3>Riksdagsvalet i kommunen 2026</h3><p class="note" style="margin:0 0 4px">Aggregerat ur kommunens jämförbara valdistrikt, viktat med röstberättigade.</p><div class="tw"><table><tbody>${k.rd.map(x=>`<tr><td>${pf(x.p)}</td><td class="r">${f1(x.a)}</td><td class="r">${sg(x.chg)}</td></tr>`).join('')}</tbody></table></div></div></div></div>`;}
function downloadCSV(rows){const h=['kommunkod','kommun','folkmangd','storst_kf','andel','forandring','S_V_MP_C','M_KD_L_SD','ovriga','styre_2022','styre_majmin','styre_mandat_min_2026','styre_mandat_max_2026','majoritet','mandat_totalt','lage'];
 const lines=[h.join(';')].concat(rows.map(k=>[k.kod,k.namn,k.folk??'',k.res[0]?.p??'',k.res[0]?.a??'',k.res[0]?.chg??'',k.blocks.L,k.blocks.R,k.blocks.O,k.styre?k.styre.partier.join('+'):'',k.styre?.majmin??'',k.styre?.min??'',k.styre?.max??'',k.maj,k.tot,k.styre?.status??''].map(v=>String(v).replace(/;/g,',')).join(';')));
 const blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='majoritetspussel_kommuner_2026.csv';a.click();}

// ---------- AVVIKELSER ----------
function renderAvvikelser(){const p=avvP;const A=DATA.avvikelser[p];const D=DATA.distrikt[p];const sp=DATA.spread[p];const nat=DATA.riket.res.find(x=>x.p===p);
 const row=x=>`<tr><td>${esc(x.namn)}</td><td class="r">${f1(x.a)}</td><td class="r">${sg(x.chg)}</td><td class="r"><b>${sg(x.rel)}</b></td></tr>`;
 const drow=x=>`<tr><td>${esc(x.namn)} <small class="muted">${esc(x.kommun)}</small></td><td class="r">${f1(x.a)}</td><td class="r">${sg(x.chg)}</td></tr>`;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Avvikelser i väljarbeteendet</h2>
 <details class="explain"><summary>Vad avvikelse betyder här</summary><div class="body"><p>Riksvalet 2026 mot 2022. <b>Avvikelse</b> = partiets förändring i kommunen minus partiets förändring i riket. Ett parti som backar 3 enheter nationellt men bara 1 i en kommun har en avvikelse på +2 där. Det pekar ut var partiet gått mot strömmen, vilket ofta hänger ihop med lokala kandidater, lokala frågor eller demografi.</p></div></details>
 <div class="chips">${ORDER.map(x=>`<button class="chip ${x===p?'on':''}" data-p="${x}" style="${x===p?'background:'+col(x):''}">${x}</button>`).join('')}</div>
 <div class="kpis"><div class="kpi"><div class="v">${sg(nat?.chg)}</div><div class="l">${esc(PN[p])} i riket</div><div class="d">${f1(nat?.a)} % 2026</div></div>
 ${sp?`<div class="kpi"><div class="v">${Math.round(100*sp.upp/sp.n)} %</div><div class="l">av valdistrikten där ${p} ökade</div><div class="d">medianförändring ${sg(sp.median)} (${sp.n} distrikt)</div></div>`:''}</div>
 <div class="grid2"><div><h3>Kommuner där ${p} gick bäst mot strömmen</h3><div class="tw"><table><thead><tr><th>Kommun</th><th class="r">2026 %</th><th class="r">±2022</th><th class="r">Avvik.</th></tr></thead><tbody>${A.upp.map(row).join('')}</tbody></table></div></div>
 <div><h3>Kommuner där ${p} gick sämst mot strömmen</h3><div class="tw"><table><thead><tr><th>Kommun</th><th class="r">2026 %</th><th class="r">±2022</th><th class="r">Avvik.</th></tr></thead><tbody>${A.ned.map(row).join('')}</tbody></table></div></div></div>
 <div class="grid2" style="margin-top:14px"><div><h3>Valdistrikt: största ökningar</h3><div class="tw"><table><thead><tr><th>Distrikt</th><th class="r">2026 %</th><th class="r">±2022</th></tr></thead><tbody>${D.upp.map(drow).join('')}</tbody></table></div></div>
 <div><h3>Valdistrikt: största tapp</h3><div class="tw"><table><thead><tr><th>Distrikt</th><th class="r">2026 %</th><th class="r">±2022</th></tr></thead><tbody>${D.ned.map(drow).join('')}</tbody></table></div></div></div>
 <p class="note">Valdistrikt med färre än 500 röstberättigade och distrikt som inte är jämförbara med 2022 (omritade eller nya) är uteslutna ur distriktslistorna.</p>`;
 $('#panel').querySelectorAll('.chip').forEach(b=>b.onclick=()=>{avvP=b.dataset.p;renderAvvikelser();});}

// ---------- DEMOGRAFI ----------
function corrCell(c){if(c==null)return '<td class="r muted">–</td>';const w=Math.min(60,Math.abs(c)*100);
 return `<td class="r"><span class="corr" style="width:${w}px;background:${c>0?'var(--pos)':'var(--neg)'}"></span> ${c>0?'+':''}${c.toFixed(2).replace('.',',')}</td>`;}
function renderDemografi(){const dm=DATA.demo;const T=demoView==='chg'?dm.chg:dm.niva;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Demografi och geografi</h2>
 <details class="explain"><summary>Så läser du tabellen</summary><div class="body"><p>Varje tal är en <b>korrelation</b> (−1 till +1) över landets valdistrikt, viktad efter antal röstberättigade. <b>Nivå 2026</b>: hänger partiets stöd ihop med faktorn? <b>Förändring 2022→2026</b>: hänger partiets <i>rörelse</i> ihop med faktorn – ökade partiet mest i höginkomstområden, i hyresrättsområden, bland äldre? Skala: 0 inget samband · 0,1 svagt · 0,3 tydligt · 0,5+ starkt.</p><p>Samband är inte orsakssamband, och områdessnitt säger inte hur enskilda personer röstat. Faktorerna är SCB:s senaste ögonblicksbild per valdistrikt. Fördjupning finns i <a href="/valjaranalys.html">Väljaranalysen</a>.</p></div></details>
 <div class="controls"><div class="ctl"><label>Visa</label><span class="seg" id="dv"><button data-v="chg" aria-pressed="${demoView==='chg'}">Förändring 2022→2026</button><button data-v="niva" aria-pressed="${demoView==='niva'}">Nivå 2026</button></span></div></div>
 <div class="tw"><table><thead><tr><th>Faktor</th>${PIDS.map(p=>`<th class="r">${p}</th>`).join('')}</tr></thead><tbody>${dm.faktorer.map(f=>`<tr><td><b>${esc(f.lab)}</b><br><small class="muted">${f.n} distrikt</small></td>${PIDS.map(p=>corrCell(T[f.key]?.[p])).join('')}</tr>`).join('')}</tbody></table></div>
 <div class="takeaway">${demoText(T,dm)}</div>
 <h3>Geografi</h3><p class="lead">Riksdagsvalets förändring per län finns under <a href="#" id="golan">Riket</a>, kommun för kommun under Kommuner, och de största lokala avvikelserna under Avvikelser.</p>`;
 $('#panel').querySelectorAll('#dv button').forEach(b=>b.onclick=()=>{demoView=b.dataset.v;renderDemografi();});
 $('#golan').onclick=e=>{e.preventDefault();setMode('riket');};}
function demoText(T,dm){const out=[];for(const p of PIDS){let best=null;for(const f of dm.faktorer){const c=T[f.key]?.[p];if(c!=null&&(best==null||Math.abs(c)>Math.abs(best.c)))best={c,lab:f.lab};}
 if(best&&Math.abs(best.c)>=0.2)out.push(`<b>${p}</b>: ${demoView==='chg'?(best.c>0?'ökade mest':'tappade mest'):(best.c>0?'starkast':'svagast')} där ${best.lab.toLowerCase()} är hög (${best.c>0?'+':''}${best.c.toFixed(2).replace('.',',')})`);}
 return out.length?out.join('. ')+'.':'Inga tydliga samband (alla under 0,2).';}

// ---------- SEKTORER ----------
const SEKTOR=[
 ['Finans','Riksdag och regering: skatte- och regelfrågor avgörs nationellt. Titta på riksdagens mandatbalans och koalitionsräknaren – en minoritetsregering flyttar tyngd till finans- och skatteutskotten.','riket'],
 ['Life science','Regionerna styr vården. Titta på regionerna där blockövervikten bytt sida och där ingen sida har egen majoritet – där avgörs styret i förhandling.','regioner'],
 ['Energi och infrastruktur','Tillstånd, nät och etableringar avgörs regionalt och kommunalt. Titta på kommunerna där styret saknar majoritet samt regionernas majoritetspussel.','kommuner'],
 ['Försvar och säkerhet','Statlig finansiering och nationella prioriteringar. Titta på riksdagens mandatbalans och vilken konstellation som kan bilda regering.','regering'],
 ['Industri och grön omställning','Nationell politik plus kommunala planbeslut. Titta på riket och på kommunerna med nya majoritetsförhållanden.','kommuner'],
 ['Bygg, fastighet och samhällsbyggnad','Kommunala planprocesser. Titta på de stora kommunerna: nytt största parti och styren som saknar majoritet.','kommuner'],
 ['Utbildning och välfärd','Nationell politik och kommunala beslut om skola och omsorg. Titta på riksdagen och på kommunernas majoritetspussel.','kommuner'],
];
function renderSektor(){const ss=DATA.styreStat;const flips=DATA.regioner.filter(r=>(r.blocks.L>r.blocks.R)!==(r.blocks22.L>r.blocks22.R));const b=DATA.riket.blocks;
 $('#panel').innerHTML=`<h2 style="margin-top:0">Sektorvy</h2><p class="lead">Var i materialet varje sektor bör titta först. Kundanpassad läsning görs i analysen – det här är vägvisare, inte bedömningar av partiernas positioner.</p>
 <div class="kpis"><div class="kpi"><div class="v">${b.L}–${b.R}</div><div class="l">Riksdagen: S+V+MP+C mot M+KD+L+SD</div></div><div class="kpi"><div class="v">${flips.length}</div><div class="l">Regioner med ny blockövervikt</div><div class="d">${flips.map(r=>esc(r.namn.replace('Region ',''))).join(', ')||'–'}</div></div><div class="kpi"><div class="v">${ss.saknar}</div><div class="l">Kommunstyren som saknar majoritet</div><div class="d">av ${ss.n}</div></div></div>
 <div class="tw"><table><thead><tr><th>Sektor</th><th>Var makten avgörs och vad att titta på</th><th></th></tr></thead><tbody>${SEKTOR.map(s=>`<tr><td><b>${esc(s[0])}</b></td><td>${esc(s[1])}</td><td><button class="btn" data-go="${s[2]}">Öppna</button></td></tr>`).join('')}</tbody></table></div>`;
 $('#panel').querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>setMode(b.dataset.go));}

// ---------- karta ----------
function ringsToPath(rings){return rings.map(r=>'M'+r.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L')+'Z').join('');}
function drawMap(){const g=DATA.geo,svg=$('#map');if(!g.lan||!Object.keys(g.lan).length){$('#maprow').style.display='none';return;}
 svg.setAttribute('viewBox',`0 0 ${g.w} ${g.h}`);
 svg.innerHTML=Object.entries(g.lan).map(([kod,rings])=>`<path d="${ringsToPath(rings)}" data-lan="${kod}"><title>${esc(g.lanNamn[kod]||kod)}</title></path>`).join('');
 svg.querySelectorAll('path').forEach(p=>p.addEventListener('click',()=>selectLan(p.getAttribute('data-lan'))));}
function selectLan(kod){selLan=(selLan===kod)?null:kod;
 $('#map').querySelectorAll('path').forEach(p=>p.classList.toggle('sel',p.getAttribute('data-lan')===selLan));
 if(mode!=='kommuner'&&mode!=='regioner'&&selLan)mode='kommuner';updMapHelp();render();}
function updSel(){const el=$('#selwrap');if(!el)return;if(!selLan){el.innerHTML='';return;}
 el.innerHTML=`<label>Län</label><span class="selchip">${esc(DATA.geo.lanNamn[selLan]||selLan)} <button aria-label="Rensa">×</button></span>`;
 el.querySelector('button').onclick=()=>selectLan(selLan);}
function updMapHelp(){$('#maphelp').innerHTML= selLan?`Visar <b>${esc(DATA.geo.lanNamn[selLan]||selLan)}</b> under Regioner och Kommuner. Klicka länet igen för hela landet.`:'Klicka på ett län för att filtrera Regioner och Kommuner.';}

// ---------- routing ----------
function setMode(m){mode=m;document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected',t.dataset.mode===m));$('#maprow').style.display=['riket','regioner','kommuner'].includes(m)&&DATA.geo.lan&&Object.keys(DATA.geo.lan).length?'':'none';render();
 try{history.replaceState(null,'','#'+m+(selLan?'&lan='+selLan:''));}catch(e){}}
function render(){({riket:renderRiket,regering:renderRegering,regioner:renderRegioner,kommuner:renderKommuner,avvikelser:renderAvvikelser,demografi:renderDemografi,sektor:renderSektor}[mode]||renderRiket)();}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setMode(t.dataset.mode));
head();drawMap();updMapHelp();
(function(){const h=location.hash.replace('#','');const parts=h.split('&');const m=parts[0];const l=(parts.find(x=>x.startsWith('lan='))||'').slice(4);
 if(l&&DATA.geo.lan[l]){selLan=l;$('#map').querySelectorAll('path').forEach(p=>p.classList.toggle('sel',p.getAttribute('data-lan')===l));updMapHelp();}
 setMode(['riket','regering','regioner','kommuner','avvikelser','demografi','sektor'].includes(m)?m:'riket');})();
(function(){let base=DATA.meta.built;setInterval(async()=>{try{const r=await fetch('status.json?_='+Date.now(),{cache:'no-store'});
 const s=await r.json();if(s.built&&s.built!==base){$('#banner').classList.add('show');setTimeout(()=>location.reload(),1500);}}catch(e){}},45000);})();
</script>
</body></html>
"""

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='public/data.json')
    ap.add_argument('--out', default='public/analys.html')
    ap.add_argument('--styre', default='data/styre_kommun_2022.csv')
    ap.add_argument('--folk', default='data/folkmangd_2024.csv')
    ap.add_argument('--nyckelpersoner', default='nyckelpersoner.csv')
    ap.add_argument('--slutligt', default='data/slutligt.json', help='JSON {"RD":"2026-09-19"} med fastställda val')
    build(ap.parse_args())
