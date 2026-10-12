#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnos_personroster.py — felsöker hur personröster ligger lagrade i Valmyndighetens slutliga riksdagsfil.
Skriver till loggen: filerna i zippen, och för ett parti (standard SD) var i JSON-strukturen personrösterna
finns och vilka summor de olika sätten att räkna ger. Ändrar inga filer.

    python3 diagnos_personroster.py [--zips .cache/zips] [--parti SD] [--namn Åkesson]
"""
import argparse, glob, io, json, os, zipfile

def walk(o, path, hit):
    if isinstance(o, dict):
        hit(o, path)
        for k, v in o.items(): walk(v, path + [k], hit)
    elif isinstance(o, list):
        for i, v in enumerate(o): walk(v, path + [f'[{i}]'], hit)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--zips', default='.cache/zips'); ap.add_argument('--parti', default='SD'); ap.add_argument('--namn', default='Åkesson')
    a = ap.parse_args()
    files = [f for f in glob.glob(os.path.join(a.zips, '*.zip')) if '_RD' in os.path.basename(f) and ('s_' in os.path.basename(f) or 'slutlig' in f)]
    print('RD-zippar:', [os.path.basename(f) for f in files])
    for zp in files:
        z = zipfile.ZipFile(zp)
        print('\n==', os.path.basename(zp), '->', z.namelist())
        for n in z.namelist():
            if not n.endswith('.json'): continue
            root = json.load(io.TextIOWrapper(z.open(n), encoding='utf-8'))
            print(f'\n--- {n}: toppnycklar {list(root)[:12]}')
            sums = {}; shown = 0; namn_hits = []
            def hit(d, path):
                nonlocal shown
                p = (d.get('partiforkortning') or d.get('partiForkortning') or '')
                if p == a.parti and ('antalRoster' in d or 'listRoster' in d or 'summeradePersonroster' in d):
                    key = '/'.join(x for x in path if not x.startswith('['))
                    if shown < 3:
                        print(f'  {a.parti}-objekt vid {key}: nycklar {list(d)}')
                        for k, v in d.items():
                            if isinstance(v, list) and v: print(f'     {k}: {len(v)} st, första: {json.dumps(v[0], ensure_ascii=False)[:300]}')
                        shown += 1
                    for k, v in d.items():
                        if isinstance(v, list):
                            tot = 0
                            def h2(dd, pp):
                                nonlocal tot
                                if 'antalPersonroster' in dd: tot += dd.get('antalPersonroster') or 0
                            walk(v, [], h2)
                            sums[(key, k)] = sums.get((key, k), 0) + tot
                nm = d.get('namn') or ''
                if a.namn and a.namn in str(nm) and 'antalPersonroster' in d and len(namn_hits) < 40:
                    namn_hits.append(('/'.join(x for x in path if not x.startswith('[')), d.get('antalPersonroster')))
            walk(root, [], hit)
            print(f'  Summa antalPersonroster för {a.parti} per plats i strukturen:')
            for (key, k), t in sorted(sums.items()): print(f'     {key} . {k}: {t}')
            print(f'  {a.namn} – antalPersonroster per plats (högst 40):')
            for pth, v in namn_hits: print(f'     {pth}: {v}')

if __name__ == '__main__':
    main()
