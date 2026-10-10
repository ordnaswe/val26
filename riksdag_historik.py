#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
riksdag_historik.py — riksdagsledamöternas historik ur Riksdagens öppna data (data.riksdagen.se, CC0).

Hämtar personlistan för samtliga nuvarande och tidigare ledamöter (från omkring 1990) med deras uppdrag
och biografi, och skriver en kompakt fil:  data/riksdagen_historik.json.gz
  [{ "id": intressent_id, "namn": "Förnamn Efternamn", "fodd": 1979, "kon": "man", "parti": "SD",
     "kammare": [[from, tom, roll, status], ...],              # kammaruppdrag (ledamot/ersättare)
     "organ":   [[organ_kod, organnamn, roll, from, tom], ...], # utskott, EU-nämnden m.m.
     "bio":     {"Kommunala uppdrag": "...", ...} }]           # biografiska uppgifter (fritext)

    python3 riksdag_historik.py                 # hämtar från data.riksdagen.se
    python3 riksdag_historik.py --src fil.json  # använder en redan nedladdad personlista (utformat=json)
Endast standardbibliotek. Körs av workflowet "Deploya allavalda.se" före build_allavalda.py.
"""
import argparse, gzip, json, sys, urllib.request

URL = ("https://data.riksdagen.se/personlista/?iid=&fnamn=&enamn=&f_ar=&kn=&parti=&valkrets="
       "&rdlstatus=samtliga&org=&utformat=json&sort=sorteringsnamn&sortorder=asc&termlista=")

def as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def text(x):
    if x is None: return ''
    if isinstance(x, list): return ' '.join(text(i) for i in x if i)
    if isinstance(x, dict): return text(x.get('uppgift') or x.get('#text') or '')
    return str(x).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src'); ap.add_argument('--out', default='data/riksdagen_historik.json.gz')
    a = ap.parse_args()
    if a.src:
        raw = json.load(open(a.src, encoding='utf-8'))
    else:
        print('Hämtar personlistan från data.riksdagen.se …', file=sys.stderr)
        req = urllib.request.Request(URL, headers={'User-Agent': 'allavalda.se (Influera Sverige AB)'})
        with urllib.request.urlopen(req, timeout=300) as r: raw = json.loads(r.read().decode('utf-8'))
    persons = as_list((raw.get('personlista') or {}).get('person'))
    out = []
    for p in persons:
        upp = as_list((p.get('personuppdrag') or {}).get('uppdrag'))
        kam, org = [], []
        for u in upp:
            ok = (u.get('organ_kod') or '').strip(); roll = (u.get('roll_kod') or '').strip()
            fr = (u.get('from') or '')[:10]; to = (u.get('tom') or '')[:10]
            if ok.lower() == 'kam' or (u.get('typ') or '') == 'kammaruppdrag':
                kam.append([fr, to, roll, (u.get('status') or '').strip()])
            elif (u.get('typ') or '') == 'uppdrag' and ok:
                org.append([ok, text(u.get('uppgift')), roll, fr, to])
        bio = {}
        for g in as_list((p.get('personuppgift') or {}).get('uppgift')):
            if (g.get('typ') or '') == 'biografi':
                k = (g.get('kod') or '').strip(); t = text(g.get('uppgift'))
                if k and t: bio[k] = (bio.get(k, '') + ' ' + t).strip()
        if not kam: continue
        try: fodd = int(p.get('fodd_ar') or 0) or None
        except Exception: fodd = None
        out.append({'id': p.get('intressent_id'), 'namn': f"{(p.get('tilltalsnamn') or '').strip()} {(p.get('efternamn') or '').strip()}".strip(),
                    'fodd': fodd, 'kon': p.get('kon'), 'parti': p.get('parti'), 'valkrets': p.get('valkrets'),
                    'kammare': sorted(kam), 'organ': sorted(org, key=lambda x: x[3]), 'bio': bio})
    with gzip.open(a.out, 'wt', encoding='utf-8') as f: json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f'Skrev {a.out}: {len(out)} personer med kammaruppdrag', file=sys.stderr)

if __name__ == '__main__':
    main()
