#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
riksdag_aktivitet.py — vad riksdagsledamöterna gjorde under mandatperioden 2022–2026, ur Riksdagens öppna data (CC0).

Hämtar Riksdagens färdiga dataset:
  votering-<rm>.csv.zip   en rad per ledamot och votering (rost: Ja/Nej/Avstår/Frånvarande)
  anforande-<rm>.json.zip en fil per anförande i kammaren
för riksmötena 2022/23–2025/26 och räknar per ledamot (intressent_id). Skriver data/riksdagen_aktivitet.json.gz:
  {intressent_id: {"vot": antal voteringar, "fr": frånvarande, "ja":…, "nej":…, "avst":…, "anf": antal anföranden}}

    python3 riksdag_aktivitet.py [--rm 202223 202324 202425 202526]
Endast standardbibliotek. Körs av "Deploya allavalda.se" före build_allavalda.py; fel i ett dataset hoppas över.
"""
import argparse, csv, gzip, io, json, sys, urllib.request, zipfile
from collections import defaultdict

BASE = 'https://data.riksdagen.se/dataset'

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'allavalda.se (Influera Sverige AB)'})
    with urllib.request.urlopen(req, timeout=600) as r: return r.read()

def walk(o, hit):
    if isinstance(o, dict):
        if 'intressent_id' in o: hit(o)
        for v in o.values(): walk(v, hit)
    elif isinstance(o, list):
        for v in o: walk(v, hit)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--rm', nargs='*', default=['202223', '202324', '202425', '202526'])
    ap.add_argument('--out', default='data/riksdagen_aktivitet.json.gz'); a = ap.parse_args()
    S = defaultdict(lambda: defaultdict(int))
    for rm in a.rm:
        url = f'{BASE}/votering/votering-{rm}.csv.zip'
        try:
            z = zipfile.ZipFile(io.BytesIO(fetch(url))); n = 0
            for name in z.namelist():
                if not name.lower().endswith('.csv'): continue
                raw = z.read(name)
                for enc in ('utf-8-sig', 'cp1252'):
                    try: txt = raw.decode(enc); break
                    except UnicodeDecodeError: continue
                for r in csv.DictReader(io.StringIO(txt)):
                    r = {k.strip().lower(): (v or '').strip() for k, v in r.items() if k}
                    iid, rost = r.get('intressent_id'), r.get('rost', '').lower()
                    if not iid or not rost: continue
                    s = S[iid]; s['vot'] += 1; n += 1
                    if rost.startswith('fr'): s['fr'] += 1
                    elif rost == 'ja': s['ja'] += 1
                    elif rost == 'nej': s['nej'] += 1
                    elif rost.startswith('av'): s['avst'] += 1
            print(f'votering {rm}: {n} ledamotsröster', file=sys.stderr)
        except Exception as e:
            print(f'votering {rm}: FEL {e} ({url})', file=sys.stderr)
        url = f'{BASE}/anforande/anforande-{rm}.json.zip'
        try:
            z = zipfile.ZipFile(io.BytesIO(fetch(url))); n = 0
            for name in z.namelist():
                if not name.lower().endswith('.json'): continue
                try: o = json.loads(z.read(name).decode('utf-8-sig'))
                except Exception: continue
                seen = set()
                def hit(d):
                    iid = (d.get('intressent_id') or '').strip()
                    if iid and iid not in seen: seen.add(iid)
                walk(o, hit)
                for iid in seen: S[iid]['anf'] += 1; n += 1
            print(f'anförande {rm}: {n} anföranden', file=sys.stderr)
        except Exception as e:
            print(f'anförande {rm}: FEL {e} ({url})', file=sys.stderr)
    with gzip.open(a.out, 'wt', encoding='utf-8') as f: json.dump({k: dict(v) for k, v in S.items()}, f, separators=(',', ':'))
    print(f'Skrev {a.out}: {len(S)} ledamöter', file=sys.stderr)

if __name__ == '__main__':
    main()
