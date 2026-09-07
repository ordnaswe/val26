#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kandidater.py — Valmyndighetens kandidaturfil -> kompakt data/kandidater.csv.

Behåller de åtta riksdagspartierna, rader med listordning (ORDNING), och per
(valtyp, område, parti) den lista (LISTNUMMER) som har flest kandidater
(partiets huvudlista). Nyckel:
  KF -> kommunkod (VALOMRÅDESKOD, 4 siffror)
  RD -> valkretsnamn (matchas mot riksvalkretsar i bygget)
  RF -> länskod (VALOMRÅDESKOD) – approximativt (region), tas med men märks.

Utdata: valtyp,omrade,parti,ordning,namn

Endast Python-standardbibliotek.
"""
import argparse
import csv
import io
from collections import defaultdict
from pathlib import Path

PIDS = {"V", "S", "MP", "C", "L", "KD", "M", "SD"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("-o", "--out", default="data/kandidater.csv")
    args = ap.parse_args()

    raw = Path(args.infile).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    h = [c.strip() for c in rows[0]]
    ix = {name: i for i, name in enumerate(h)}
    C = lambda r, name: (r[ix[name]].strip() if ix.get(name) is not None and len(r) > ix[name] else "")

    # samla per (valtyp, omrade, parti, lista) -> [(ordning, namn)]
    lists = defaultdict(list)
    for r in rows[1:]:
        if not r:
            continue
        parti = C(r, "PARTIFÖRKORTNING").upper()
        if parti not in PIDS:
            continue
        if C(r, "SAMTYCKE") == "N":     # kandidat utan samtycke – ej valbar
            continue
        ordn = C(r, "ORDNING")
        if not ordn.isdigit():
            continue
        namn = C(r, "NAMN")
        if not namn or "inte lämnat samtycke" in namn.lower():
            continue
        valtyp = C(r, "VALTYP")
        if valtyp == "KF":
            omrade = C(r, "VALOMRÅDESKOD").zfill(4)
        elif valtyp == "RD":
            omrade = C(r, "VALKRETSNAMN")
        elif valtyp == "RF":
            omrade = C(r, "VALOMRÅDESKOD").zfill(2)
        else:
            continue
        lista = C(r, "LISTNUMMER")
        lists[(valtyp, omrade, parti, lista)].append((int(ordn), namn))

    # för varje (valtyp, omrade, parti): välj listan med flest kandidater (huvudlistan)
    best = {}
    for (valtyp, omrade, parti, lista), cands in lists.items():
        key = (valtyp, omrade, parti)
        if key not in best or len(cands) > len(best[key]):
            best[key] = cands

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["valtyp", "omrade", "parti", "ordning", "namn"])
        for (valtyp, omrade, parti), cands in sorted(best.items()):
            for ordn, namn in sorted(cands)[:60]:     # tak: 60 namn per lista
                w.writerow([valtyp, omrade, parti, ordn, namn]); n += 1
    print(f"Skrev {args.out}: {n} kandidatrader, {len(best)} listor "
          f"(KF/RD/RF, 8 partier, huvudlista per område).")


if __name__ == "__main__":
    main()
