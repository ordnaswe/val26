#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valda.py — valda ledamöter, ersättare och personröster ur Valmyndighetens SLUTLIGA mandatfördelningsfiler.

Läser Val_2026_slutlig_<kod>_<RD|RF|KF>.zip (de som hamta.py laddar ner till .cache/zips/ med
--pattern "s/…") och plockar ur *_mandatfordelning_*.json (fältbeskrivning: val.se, "Slutlig
mandatfördelning", slut-mandatfordelning.md):
  valomrade.valda.partiLedamoterLista[].ledamoter[]        -> valda (med ersattareList[])
  valomrade.valkretsLista[].valda…                           -> samma för valkretsindelade områden
  valomrade.kvalificeradeForPersonvalLista[] (+ per valkrets) -> klarat personröstspärren, andel
  valomrade.rostfordelning…partiRoster[].summeradePersonroster[] -> personröster för alla kandidater

Skriver:
  data/valda.csv       en rad per vald ledamot
  data/ersattare.csv   en rad per ersättare (kopplad till ledamot)
  data/personroster.csv en rad per kandidat med personröster (alla, inte bara valda)

    python3 valda.py --zips .cache/zips --out-dir data
Endast standardbibliotek. Klarar att nycklar saknas (filen loggar vad som hittats).
"""
import argparse, csv, glob, io, json, os, re, sys, zipfile
from collections import defaultdict

ABBR_FIX = {'FP': 'L'}   # Liberalerna har partikoden/förkortningen FP i Valmyndighetens filer

def abbr(p):
    a = (p.get('partiforkortning') or '').strip()
    return ABBR_FIX.get(a, a) or (p.get('partibeteckning') or '').strip()

def walk_areas(root):
    """Ger (valkretskod, valkretsnamn, objekt) för valområdet och varje valkrets."""
    vo = root.get('valomrade') or {}
    yield None, None, vo
    for vk in vo.get('valkretsLista') or []:
        yield vk.get('kod'), vk.get('namnValkrets'), vk

def person_votes(obj):
    """kandidatnummer -> antalPersonroster ur rostfordelning…partiRoster[].summeradePersonroster[]
       (och listRoster[].personroster[] som reserv)."""
    out = {}
    pr = ((obj.get('rostfordelning') or {}).get('rosterPaverkaMandat') or {}).get('partiRoster') or []
    for p in pr:
        for s in p.get('summeradePersonroster') or []:
            k = s.get('kandidatnummer') or s.get('kandidatNummer')
            if k is not None: out[k] = {'personroster': s.get('antalPersonroster'), 'parti': abbr(p), 'partibeteckning': p.get('partibeteckning'), 'namn': s.get('namn'), 'partiroster': p.get('antalRoster')}
        if not p.get('summeradePersonroster'):
            for l in p.get('listRoster') or []:
                for s in l.get('personroster') or []:
                    k = s.get('kandidatNummer') or s.get('kandidatnummer')
                    if k is None: continue
                    cur = out.setdefault(k, {'personroster': 0, 'parti': abbr(p), 'partibeteckning': p.get('partibeteckning'), 'namn': s.get('namn'), 'partiroster': p.get('antalRoster')})
                    cur['personroster'] = (cur['personroster'] or 0) + (s.get('antalPersonroster') or 0)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zips', default='.cache/zips', help='mapp med Val_2026_slutlig_*.zip (hamta.py)')
    ap.add_argument('--out-dir', default='data')
    a = ap.parse_args()
    # slutliga filer ligger under s/ på resultat.val.se -> cachens namn börjar på "s_" (hamta.py ersätter / med _)
    files = sorted(set(glob.glob(os.path.join(a.zips, 's_*.zip')) + glob.glob(os.path.join(a.zips, '*slutlig*.zip'))))
    if not files:
        print(f'Inga slutliga zip-filer i {a.zips} – kör hamta.py med --pattern-rd s/rd/ --pattern-rf s/rf/ --pattern-kf s/kf/ först. Finns i cachen: {sorted(os.listdir(a.zips))[:10] if os.path.isdir(a.zips) else "ingen mapp"}', file=sys.stderr)
        sys.exit(1)
    valda, ers, pers = [], [], []
    n_files = 0; n_valda_areas = 0
    for zp in files:
        m = re.search(r'_([0-9A-Z]{2,4})_(RD|RF|KF)\.zip$', os.path.basename(zp))
        if not m: continue
        kod, vt = m.group(1), m.group(2)
        try:
            with zipfile.ZipFile(zp) as z:
                names = [n for n in z.namelist() if 'mandatfordelning' in n and n.endswith('.json')]
                if not names: continue
                root = json.load(io.TextIOWrapper(z.open(names[0]), encoding='utf-8'))
        except Exception as e:
            print(f'{zp}: kunde inte läsa ({e})', file=sys.stderr); continue
        n_files += 1
        vo = root.get('valomrade') or {}
        omr_namn = vo.get('namn'); omr_kod = vo.get('kod') or kod
        # Personröster räknas per valkrets. I riksdagsvalet står t.ex. partiledare på listor i flera valkretsar, så
        # samma kandidatnummer finns i många valkretsar: håll isär per valkrets och summera till totalt.
        kval = {}; pv_vk = {}
        for vkk, vkn, obj in walk_areas(root):
            key = vkk or ''
            for q in obj.get('kvalificeradeForPersonvalLista') or []:
                kval[(key, q.get('kandidatnummer'))] = q.get('andelPersonroster')
            pv_vk[key] = person_votes(obj)
        area_pv = pv_vk.get('', {}); vk_keys = [k for k in pv_vk if k]
        def pr_in(vk, knr):
            v = (pv_vk.get(vk or '', {}) or {}).get(knr) or area_pv.get(knr) or {}
            return v.get('personroster')
        def pr_total(knr):
            if vk_keys:
                vals = [pv_vk[k][knr]['personroster'] or 0 for k in vk_keys if knr in pv_vk[k]]
                if vals: return sum(vals)
            return (area_pv.get(knr) or {}).get('personroster')
        def kval_in(vk, knr):
            for k in ((vk or ''), ''):
                if (k, knr) in kval: return kval[(k, knr)]
            return None
        # personröster för alla kandidater, en rad per valkrets (valkretskod tom = hela valområdet)
        for vk, d in pv_vk.items():
            if vk == '' and vk_keys: continue
            for knr, v in d.items():
                andel = None
                if v.get('partiroster'): andel = round(100.0 * (v.get('personroster') or 0) / v['partiroster'], 2)
                pers.append(dict(valtyp=vt, valomrkod=omr_kod, valomrnamn=omr_namn, valkretskod=vk, parti=v['parti'], partibeteckning=v['partibeteckning'],
                                 kandidatnummer=knr, namn=v.get('namn'), personroster=v.get('personroster'), personroster_totalt=pr_total(knr), andel_personroster=andel,
                                 kvalificerad='Ja' if kval_in(vk, knr) is not None else 'Nej', invald='Nej'))
        # valda + ersättare
        got = False
        for vkk, vkn, obj in walk_areas(root):
            valda_obj = obj.get('valda') or {}
            for pl in valda_obj.get('partiLedamoterLista') or []:
                pa = abbr(pl)
                for led in pl.get('ledamoter') or []:
                    got = True
                    knr = led.get('kandidatnummer')
                    valda.append(dict(valtyp=vt, valomrkod=omr_kod, valomrnamn=omr_namn,
                        valkretskod=led.get('valkretskod') or vkk or omr_kod, valkretsnamn=led.get('valkretsnamn') or vkn or omr_namn,
                        parti=pa, partibeteckning=pl.get('partibeteckning'), kandidatnummer=knr, namn=led.get('namn'),
                        invalsordning=led.get('invalsordning'), valgrund=led.get('valgrundText'),
                        personroster=pr_in(led.get('valkretskod') or vkk, knr), personroster_totalt=pr_total(knr),
                        andel_personroster=kval_in(led.get('valkretskod') or vkk, knr),
                        kvalificerad='Ja' if kval_in(led.get('valkretskod') or vkk, knr) is not None else 'Nej', tomma_stolar=pl.get('antalTommaStolar')))
                    for e in led.get('ersattareList') or []:
                        ers.append(dict(valtyp=vt, valomrkod=omr_kod, valomrnamn=omr_namn, valkretskod=led.get('valkretskod') or vkk or omr_kod,
                            parti=pa, ledamot=led.get('namn'), ledamot_kandidatnummer=knr, ersattarordning=e.get('ersattarordning'),
                            kandidatnummer=e.get('kandidatnummer'), namn=e.get('namn'), valgrund=e.get('valgrundText'),
                            personroster=pr_in(led.get('valkretskod') or vkk, e.get('kandidatnummer'))))
        if got: n_valda_areas += 1
    # Samma ledamot kan stå både på valområdesnivå och i valkretsLista (t.ex. riksdagen) -> en rad per mandat.
    # Behåll en rad per (val, valområde, kandidatnummer); valkretsnivåns uppgifter (valkretskod/-namn) vinner.
    def dedupe(rows, key, prefer):
        out = {}
        for r in rows:
            k = key(r)
            if k not in out or prefer(r, out[k]): out[k] = r
        return list(out.values())
    is_vk = lambda r: r.get('valkretskod') not in (None, '', r.get('valomrkod'))
    valda = dedupe(valda, lambda r: (r['valtyp'], r['valomrkod'], r['kandidatnummer'] or r['namn']), lambda new, old: is_vk(new) and not is_vk(old))
    ers = dedupe(ers, lambda r: (r['valtyp'], r['valomrkod'], r['ledamot_kandidatnummer'], r['kandidatnummer'] or r['namn']), lambda new, old: is_vk(new) and not is_vk(old))
    pers = dedupe(pers, lambda r: (r['valtyp'], r['valomrkod'], r['valkretskod'], r['kandidatnummer']), lambda new, old: False)
    inv = {(r['valtyp'], r['valomrkod'], r['kandidatnummer']) for r in valda}
    for r in pers:
        if (r['valtyp'], r['valomrkod'], r['kandidatnummer']) in inv: r['invald'] = 'Ja'
    os.makedirs(a.out_dir, exist_ok=True)
    def write(name, rows):
        if not rows: print(f'{name}: inga rader', file=sys.stderr); return
        with open(os.path.join(a.out_dir, name), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print(f'Skrev {os.path.join(a.out_dir, name)}: {len(rows)} rader', file=sys.stderr)
    write('valda.csv', valda); write('ersattare.csv', ers); write('personroster.csv', pers)
    print(f'{n_files} filer lästa, {n_valda_areas} valområden med fastställda valda, '
          f'{len(valda)} ledamöter, {len(ers)} ersättare, {len(pers)} kandidater med personröster.', file=sys.stderr)

if __name__ == '__main__':
    main()
