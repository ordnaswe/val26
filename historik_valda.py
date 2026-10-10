#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
historik_valda.py — ursprungligt valda ledamöter 2010, 2014, 2018 och 2022 (Valmyndigheten) i ett gemensamt
format -> data/valda_historik.csv.gz, samt Valmyndighetens fullständiga kandidatfil 2026 -> data/kandidaturer_2026_full.csv.gz.

Källor (Valmyndigheten, statistik och data):
  alla_ursprungliga_ledamoter_2010_RLK.xls, ursprungligt_valda_ledamoter_2014_RLK.xls, 2018_ursprungligt_valda.xls
    (namnen är gallrade av Valmyndigheten – bara aggregerad statistik går att göra)
  ledamoter_med_historik_2022-2026.csv (namn, kandidatnummer, personvald, ålder, kön, invals- och avgångsdatum)
  kandidaturer_inför_2026.csv (alla kandidaturer med ålder, kön, valsedelsuppgift, folkbokföringskommun)
Kräver xlrd för .xls (pip install xlrd). De färdiga .csv.gz committas, så skriptet behövs bara om källorna ändras.

    python3 historik_valda.py --x2010 … --x2014 … --x2018 … --c2022 … --k2026 …
"""
import argparse, csv, gzip

PFIX = {'FP': 'L'}
VT = {'R': 'RD', 'L': 'RF', 'K': 'KF', 'RD': 'RD', 'RF': 'RF', 'KF': 'KF'}
COLS = ['ar', 'valtyp', 'lankod', 'kommunkod', 'valkretskod', 'valkrets', 'parti', 'invalsordning', 'listplats', 'personvald', 'alder', 'kon',
        'namn', 'kandidatnummer', 'ursprunglig', 'avgang']

def i2(x, n):
    try: return str(int(float(x))).zfill(n)
    except Exception: return ''

def from_xls(path, ar):
    import xlrd
    sh = xlrd.open_workbook(path, ignore_workbook_corruption=True).sheet_by_index(0)
    h = [str(x).strip().lower() for x in sh.row_values(0)]
    for i in range(1, sh.nrows):
        r = dict(zip(h, sh.row_values(i)))
        vt = VT.get(str(r.get('valtyp')).strip())
        if not vt: continue
        lan = i2(r.get('länsnr', r.get('länsnummer')), 2); km = i2(r.get('kommunnr', r.get('kommunnummer')), 2)
        p = str(r.get('parti', r.get('partiförkortning', ''))).strip(); p = PFIX.get(p, p)
        yield dict(ar=ar, valtyp=vt, lankod=lan, kommunkod=(lan + km if vt == 'KF' and lan and km else ''),
                   valkretskod=i2(r.get('valkretsnr', r.get('valkretsnummer')), 2), valkrets=str(r.get('valkrets') or '').strip(),
                   parti=p, invalsordning=i2(r.get('invalsordning'), 1), listplats=i2(r.get('listplats'), 1),
                   personvald=1 if str(r.get('personvald')).strip().lower().startswith('person') else 0,
                   alder=i2(r.get('ålder', r.get('ålder valdag')), 1), kon=str(r.get('kön') or '').strip(),
                   namn='', kandidatnummer=i2(r.get('kandidatnr', r.get('kandnr')), 1), ursprunglig=1, avgang='')

def from_2022(path):
    raw = open(path, 'rb').read().decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    head = raw[1].split(';'); 
    for line in raw[2:]:
        if not line.strip(): continue
        r = dict(zip(head, line.split(';')))
        vt = r['Valtyp']; p = PFIX.get(r['Partiförkortning'], r['Partiförkortning'])
        lan = r['Länskod'].zfill(2) if r['Länskod'] else ''; km = r['Kommunkod']
        kod = (lan + km.zfill(2)) if (vt == 'KF' and km and len(km) <= 2) else km
        yield dict(ar=2022, valtyp=vt, lankod=lan, kommunkod=kod if vt == 'KF' else '', valkretskod=r['Valkretskod'], valkrets=r['Valkrets'],
                   parti=p or r['Partibeteckning'], invalsordning=r['Mandat (invalsordning)'], listplats='', personvald=1 if r['Personvald'] else 0,
                   alder=r['Ålder valdag'], kon=r['Kön'], namn=(r['Ledamot förnamn'] + ' ' + r['Ledamot efternamn']).strip(),
                   kandidatnummer=r['Kandidatnummer ledamot'], ursprunglig=0 if r['Invalsdatum'] else 1, avgang=(r['Avgångsdatum'] or '')[:10])

def main():
    ap = argparse.ArgumentParser()
    for k in ('x2010', 'x2014', 'x2018', 'c2022', 'k2026'): ap.add_argument('--' + k)
    ap.add_argument('--out', default='data/valda_historik.csv.gz'); ap.add_argument('--out-kand', default='data/kandidaturer_2026_full.csv.gz')
    a = ap.parse_args(); n = 0
    with gzip.open(a.out, 'wt', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
        for path, ar in ((a.x2010, 2010), (a.x2014, 2014), (a.x2018, 2018)):
            if path:
                for r in from_xls(path, ar): w.writerow(r); n += 1
        if a.c2022:
            for r in from_2022(a.c2022): w.writerow(r); n += 1
    print(f'Skrev {a.out}: {n} rader')
    if a.k2026:
        with open(a.k2026, encoding='utf-8-sig', newline='') as fi, gzip.open(a.out_kand, 'wt', newline='', encoding='utf-8') as fo:
            rd = csv.DictReader(fi, delimiter=';'); keep = ['VALTYP', 'VALOMRÅDESKOD', 'VALOMRÅDESNAMN', 'VALKRETSKOD', 'VALKRETSNAMN', 'PARTIBETECKNING', 'PARTIFÖRKORTNING',
                   'ORDNING', 'KANDIDATNUMMER', 'NAMN', 'ÅLDER_PÅ_VALDAGEN', 'KÖN', 'FOLKBOKFÖRINGSKOMMUN', 'VALSEDELSUPPGIFT', 'GILTIG']
            w = csv.DictWriter(fo, fieldnames=keep, delimiter=';'); w.writeheader(); m = 0
            for r in rd:
                w.writerow({k: (r.get(k) or '').strip() for k in keep}); m += 1
        print(f'Skrev {a.out_kand}: {m} rader')

if __name__ == '__main__':
    main()
