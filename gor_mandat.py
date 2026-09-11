#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gor_mandat.py — räknar mandat per parti per valkrets och skriver mandat_person.csv
(som invalda.py läser). Del av personlagret för valutfall.se.

RD (exakt): läser EXAKTA röstetal per parti per distrikt ur distrikt.csv (adaptern),
  mappar distrikt -> riksvalkrets via data/valkrets.csv, kör jämkade uddatalsmetoden
  (första deltal 1,2) med fasta valkretsmandat + 39 utjämningsmandat och spärr
  4 % nationellt eller 12 % i en valkrets. Verifierat mot 2022 (S107/SD73/M68/V24/
  C24/KD19/MP18/L16, summa 349).

RF (approx i v1): räknas ur regionandelarna i data.json (avrundade) × seats.lan,
  spärr 3 %. Blir exakt när den pekas mot ett RF-distrikt.csv (steg 2).

Kör i loopen efter varje build:
  python3 gor_mandat.py --distrikt distrikt.csv --data public/data.json \
                        --valkrets data/valkrets.csv --out data/mandat_person.csv
  python3 invalda.py --kandidaturer ../Bakgrundsfiler/kandidaturer.csv \
                     --nyckelpersoner nyckelpersoner.csv --mandat data/mandat_person.csv
"""
import csv, json, argparse, sys
from collections import defaultdict

PIDS = ['V','S','MP','C','L','KD','M','SD']   # kolumnnamn i distrikt.csv (exakta röster)

def to_int(v):
    try: return int(float(str(v).strip()))
    except: return 0

def jamkad(votes, nseats, first=1.2):
    seats = {p:0 for p in votes}
    for _ in range(int(nseats)):
        best, bq = None, -1.0
        for p,v in votes.items():
            div = first if seats[p]==0 else (2*seats[p]+1)
            q = v/div
            if q > bq: bq, best = q, p
        if best is None: break
        seats[best]+=1
    return seats

def national_target(natvotes, total_seats, fasta_won):
    """349-fördelning med hantering av överskottsmandat."""
    fixed, parties, left = {}, dict(natvotes), total_seats
    while True:
        alloc = jamkad(parties, left)
        overs = [p for p in parties if fasta_won.get(p,0) > alloc[p]]
        if not overs:
            out = dict(fixed); out.update(alloc); return out
        for p in overs:
            fixed[p] = fasta_won[p]; left -= fasta_won[p]; del parties[p]

def load_distrikt(path, komKod, lanKod, kom2vk):
    """-> vk_votes[vk][p], nat[p], valid, lan_votes[lk][p], lan_valid[lk]"""
    vk_votes = defaultdict(lambda: defaultdict(float)); nat = defaultdict(float); valid = 0.0
    lan_votes = defaultdict(lambda: defaultdict(float)); lan_valid = defaultdict(float)
    okv = miss = 0
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            giltiga = to_int(r.get('giltiga'))
            komnamn = (r.get('kommun_namn') or '').strip()
            lannamn = (r.get('lan_namn') or '').strip()
            kk = komKod.get(komnamn); vk = kom2vk.get(kk); lk = lanKod.get(lannamn)
            if vk: okv += 1
            else: miss += 1
            valid += giltiga
            if lk: lan_valid[lk] += giltiga
            for p in PIDS:
                c = to_int(r.get(p))
                if not c: continue
                nat[p] += c
                if vk: vk_votes[vk][p] += c
                if lk: lan_votes[lk][p] += c
    return vk_votes, nat, valid, lan_votes, lan_valid, okv, miss

def rd_seats(vk_votes, nat, valid, riksvalkretsar):
    natshare = {p: (nat[p]/valid*100 if valid else 0) for p in nat}
    over12 = set()
    for vk, pv in vk_votes.items():
        tot = sum(pv.values()) or 1
        for p, v in pv.items():
            if v/tot*100 >= 12.0: over12.add(p)
    qualified   = {p for p in nat if natshare[p] >= 4.0} | over12
    utj_eligible = {p for p in nat if natshare[p] >= 4.0}
    fasta = {}; fasta_won = defaultdict(int)
    for vk, info in riksvalkretsar.items():
        a = jamkad({p: vk_votes[vk].get(p,0.0) for p in qualified}, info.get('fasta',0))
        fasta[vk] = a
        for p,s in a.items(): fasta_won[p]+=s
    target = national_target({p:nat[p] for p in utj_eligible}, 349,
                             {p:fasta_won[p] for p in utj_eligible})
    utj = {p: max(0, target[p]-fasta_won[p]) for p in utj_eligible}
    seats = {vk: dict(fasta[vk]) for vk in fasta}
    for p, n in utj.items():
        for _ in range(n):
            best, bq = None, -1.0
            for vk in riksvalkretsar:
                q = vk_votes[vk].get(p,0.0) / (2*seats[vk].get(p,0)+1)
                if q > bq: bq, best = q, vk
            seats[best][p] = seats[best].get(p,0)+1
    return seats, {p:target.get(p,0) for p in utj_eligible}

def rf_seats_from_shares(d):
    """Approx: regionandelar (avrundade) × seats.lan, spärr 3 %."""
    out = {}
    reg = d['allresults'].get('region', {})
    for lk, tot in d['seats']['lan'].items():
        rows = reg.get(lk, {}).get('RF', [])
        votes = {x['p']: x['a'] for x in rows if x['p'] in PIDS and x['a'] >= 3.0}
        out[lk] = jamkad(votes, tot)
    return out

def rf_seats_exact(lan_votes, lan_valid, seats_lan):
    """Exakt: RF-röster per region (ur data/rf.csv), spärr 3 % i regionen.
       Region behandlas som en valkrets (approx för delade regioner)."""
    out = {}
    for lk, tot in seats_lan.items():
        valid = lan_valid.get(lk, 0) or 1
        votes = {p: v for p, v in lan_votes.get(lk, {}).items() if v/valid*100 >= 3.0}
        out[lk] = jamkad(votes, tot)
    return out

def kf_seats_from_shares(d, valkretsar):
    """KF-mandat per kommun ur allresults.kommun (ALLA partier inkl. lokala), spärr
       2 % (en valkrets) / 3 % (flera valkretsar). Kommunen behandlas som EN valkrets
       (approx för delade kommuner). Andelar är avrundade (2 dec) i data.json -> KF är
       approximativt på personlagernivå; personröster ingår heller inte. Partinyckeln
       är förkortning för de 8 riksdagspartierna och fullständigt namn för lokala partier
       (så som allresults anger dem), vilket matchar kandidaturernas PARTIBETECKNING."""
    out = {}
    kom = d['allresults'].get('kommun', {})
    for kk, tot in d['seats'].get('kommun', {}).items():
        rows = kom.get(kk, {}).get('KF', [])
        thr = 3.0 if valkretsar.get(kk, 1) > 1 else 2.0
        votes = {x['p']: x['a'] for x in rows if x.get('a', 0) >= thr and x.get('p')}
        if not votes or not tot:
            out[kk] = {}; continue
        out[kk] = jamkad(votes, tot)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--distrikt', help='RD-distrikt.csv med exakta röster (adaptern: data/rd.csv). Saknas den används --distrikt-fallback, annars hoppas RD över (RF/KF körs ändå).')
    ap.add_argument('--distrikt-fallback', help='RD-baslinje (t.ex. data/rd_baseline.csv, 2022 speglat) som används när live-rd.csv saknas -> RD-namn i förhandsläget.')
    ap.add_argument('--distrikt-rf', help='RF-distrikt.csv med exakta röster (adaptern: data/rf.csv) -> RF exakt')
    ap.add_argument('--data', default='public/data.json')
    ap.add_argument('--valkrets', default='data/valkrets.csv')
    ap.add_argument('--mandat', default='data/mandat.csv', help='niva,kod,antal,valkretsar (för KF-spärr 2/3 %)')
    ap.add_argument('--out', default='data/mandat_person.csv')
    ap.add_argument('--rf-approx', action='store_true', help='räkna RF ur regionandelar i data.json (om --distrikt-rf saknas)')
    ap.add_argument('--no-kf', action='store_true', help='hoppa över KF (kommunmandat ur allresults.kommun)')
    a = ap.parse_args()
    import os
    d = json.load(open(a.data, encoding='utf-8'))
    komKod = {k:v for k,v in d['komKod'].items()}
    lanKod = {k:v for k,v in d['lanKod'].items()}
    kom2vk = {}
    for r in csv.DictReader(open(a.valkrets, encoding='utf-8-sig')):
        kom2vk[(r.get('kommunkod') or '').strip()] = (r.get('valkretskod') or '').strip()

    rows = []
    rd = None; okv = miss = 0; rd_src = None
    rd_file = a.distrikt if (a.distrikt and os.path.exists(a.distrikt)) else \
              (a.distrikt_fallback if (a.distrikt_fallback and os.path.exists(a.distrikt_fallback)) else None)
    if rd_file:
        rd_src = 'live (data/rd.csv)' if rd_file == a.distrikt else 'baslinje (2022 speglat)'
        vk_votes, nat, valid, lan_votes, lan_valid, okv, miss = load_distrikt(rd_file, komKod, lanKod, kom2vk)
        rd, target = rd_seats(vk_votes, nat, valid, d['riksvalkretsar'])
        for vk, pv in rd.items():
            for p,s in pv.items():
                if s>0: rows.append(('RD','00',vk,p,s))
    rf = None; rf_mode = None
    if a.distrikt_rf and os.path.exists(a.distrikt_rf):
        _vk, _nat, _val, lan_votes_rf, lan_valid_rf, _o, _m = load_distrikt(a.distrikt_rf, komKod, lanKod, kom2vk)
        rf = rf_seats_exact(lan_votes_rf, lan_valid_rf, d['seats']['lan']); rf_mode = 'exakt (data/rf.csv)'
    elif a.rf_approx or a.distrikt_rf:   # RF-fil angiven men saknas ännu -> approx tills den finns
        rf = rf_seats_from_shares(d); rf_mode = 'approx (regionandelar; RF-distriktfil saknas)'
    if rf:
        for lk, pv in rf.items():
            for p,s in pv.items():
                if s>0: rows.append(('RF',lk,lk,p,s))

    # KF: kommunmandat ur allresults.kommun (alla partier inkl. lokala)
    kf = None
    if not a.no_kf and d.get('allresults', {}).get('kommun') and d.get('seats', {}).get('kommun'):
        valkretsar = {}
        if os.path.exists(a.mandat):
            for r in csv.DictReader(open(a.mandat, encoding='utf-8-sig')):
                if (r.get('niva') or '').strip() == 'kommun':
                    try: valkretsar[(r.get('kod') or '').strip()] = int(r.get('valkretsar') or 1)
                    except: pass
        kf = kf_seats_from_shares(d, valkretsar)
        for kk, pv in kf.items():
            for p, s in pv.items():
                if s > 0: rows.append(('KF', kk, kk, p, s))

    with open(a.out,'w',encoding='utf-8',newline='') as f:
        w = csv.writer(f); w.writerow(['valtyp','valomradeskod','valkretskod','parti_abbr','mandat'])
        w.writerows(rows)

    # verifiering till stderr
    if rd is not None:
        natrd = defaultdict(int)
        for vk,pv in rd.items():
            for p,s in pv.items(): natrd[p]+=s
        print(f"RD-källa: {rd_src}; {okv} distrikt mappade till riksvalkrets, {miss} utan.", file=sys.stderr)
        print("RD nationellt:", {p:natrd[p] for p in sorted(natrd,key=lambda x:-natrd[x])},
              "summa", sum(natrd.values()), file=sys.stderr)
    else:
        print("RD: hoppades över (ingen RD-distriktfil eller baslinje).", file=sys.stderr)
    if rf is not None:
        rf_tot = sum(s for pv in rf.values() for s in pv.values())
        print(f"RF: {rf_mode}, {len(rf)} regioner, {rf_tot} mandat (mål {sum(d['seats']['lan'].values())}).", file=sys.stderr)
    if kf is not None:
        kf_tot = sum(s for pv in kf.values() for s in pv.values())
        kf_mal = sum(d['seats']['kommun'].values())
        nonzero = sum(1 for pv in kf.values() if pv)
        print(f"KF: approx (allresults.kommun-andelar), {nonzero}/{len(kf)} kommuner, "
              f"{kf_tot} mandat (mål {kf_mal}).", file=sys.stderr)
    print(f"Skrev {a.out} ({len(rows)} rader).", file=sys.stderr)

if __name__=='__main__':
    main()
