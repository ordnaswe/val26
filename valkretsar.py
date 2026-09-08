#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valkretsar.py — kopplingar för kart-lagren:
  region   -> kommunkod       -> regionvalkrets (ur regionvalsfilen, RF)
  kommunvk -> valdistriktskod  -> kommunvalkrets (ur kommunvalsfilen, KF; endast
              kommuner med FLER än en valkrets – annars ointressant)

    python3 valkretsar.py --rf regionval_2022.csv --kf kommunval_2022.csv -o data/valkretsar.csv

Utdata: typ,nyckel,namn      (typ = region | kommunvk)
Endast standardbibliotek. Läser långforматs-CSV (Valdistriktskod;…;Valkretsnamn;…).
"""
import argparse, csv, io
from collections import defaultdict, Counter
from pathlib import Path


def read_long(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    h = [c.strip().lower() for c in rows[0]]
    ix = lambda n: h.index(n) if n in h else None
    return rows[1:], ix("valdistriktskod"), ix("valkretsnamn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rf", help="Regionval per valdistrikt (CSV, långformat)")
    ap.add_argument("--kf", help="Kommunval per valdistrikt (CSV, långformat)")
    ap.add_argument("-o", "--out", default="data/valkretsar.csv")
    args = ap.parse_args()

    out = []

    # region: kommun -> regionvalkrets (vanligaste valkretsnamnet i kommunen)
    if args.rf and Path(args.rf).exists():
        rows, kc, vkn = read_long(args.rf)
        by_kom = defaultdict(Counter)
        for r in rows:
            if kc is None or vkn is None or len(r) <= max(kc, vkn):
                continue
            kod = (r[kc] or "").strip()
            namn = (r[vkn] or "").strip()
            if len(kod) >= 4 and namn:
                by_kom[kod[:4]][namn] += 1
        for kk, c in sorted(by_kom.items()):
            out.append(["region", kk, c.most_common(1)[0][0]])

    # kommunvk: valdistrikt -> kommunvalkrets, bara för kommuner med >1 valkrets
    if args.kf and Path(args.kf).exists():
        rows, kc, vkn = read_long(args.kf)
        dist_vk = {}
        kom_vks = defaultdict(set)
        for r in rows:
            if kc is None or vkn is None or len(r) <= max(kc, vkn):
                continue
            kod = (r[kc] or "").strip()
            namn = (r[vkn] or "").strip()
            if len(kod) >= 8 and namn:
                dist_vk[kod] = namn
                kom_vks[kod[:4]].add(namn)
        multi = {kk for kk, s in kom_vks.items() if len(s) > 1}
        for kod, namn in sorted(dist_vk.items()):
            if kod[:4] in multi:
                out.append(["kommunvk", kod, namn])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["typ", "nyckel", "namn"]); w.writerows(out)
    nreg = sum(1 for r in out if r[0] == "region")
    nkvk = sum(1 for r in out if r[0] == "kommunvk")
    print(f"Skrev {args.out}: {nreg} kommun→regionvalkrets, {nkvk} distrikt→kommunvalkrets "
          f"(i {len({r[1][:4] for r in out if r[0]=='kommunvk'})} fler-valkretskommuner).")


if __name__ == "__main__":
    main()
