#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
omraden_alla.py — ALLA partier (≥ tröskel) per område, ur långforматs-filerna
(Val;...;Valdistriktskod;...;Valkretskod;Valkretsnamn;Parti;Röster;...).

Nivåer:
  kommun  -> kommunkod (valdistriktskod[:4])      (från kommunvalsfilen, KF)
  region  -> länskod  (valdistriktskod[:2])        (från regionvalsfilen, RF)
  valkrets-> riksdagsvalkrets (Valkretsnamn)       (från riksdagsfilen, RD)
  riket   -> "00"                                  (från riksdagsfilen, RD)

Utdata: niva,kod,namn,val,parti,andel   (parti = partinamn; de 8 får sin kod)

    python3 omraden_alla.py --kf kommunval.csv --rf regionval.csv --rd riksdag.csv \\
        -o data/omraden_alla.csv --min 1.0

Endast standardbibliotek.
"""
import argparse, csv, io
from collections import defaultdict
from pathlib import Path

PID = {"vänsterpartiet": "V", "arbetarepartiet-socialdemokraterna": "S", "miljöpartiet de gröna": "MP",
       "centerpartiet": "C", "liberalerna (tidigare folkpartiet)": "L", "liberalerna": "L",
       "kristdemokraterna": "KD", "moderaterna": "M", "sverigedemokraterna": "SD"}
SKIP = ("summa giltiga", "valdeltag", "blanka", "ogiltiga", "övriga anmälda", "ej anmält")


def read_long(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    h = [c.strip() for c in rows[0]]
    ix = {c.lower(): i for i, c in enumerate(h)}
    def col(*names):
        for n in names:
            if n in ix: return ix[n]
        return None
    return rows[1:], {
        "kod": col("valdistriktskod"), "parti": col("parti"),
        "roster": col("röster", "roster"), "vkk": col("valkretskod"),
        "vkn": col("valkretsnamn"),
    }


def parti_name(p):
    return PID.get(p.strip().lower(), p.strip())


def is_skip(p):
    pl = p.lower()
    return any(s in pl for s in SKIP)


def aggregate(path, niva, keyfn, namefn=None):
    """-> {kod: {"namn":..., "v":{parti:röster}, "tot":giltiga}}"""
    if not path or not Path(path).exists():
        return {}
    rows, c = read_long(path)
    areas = defaultdict(lambda: {"namn": "", "v": defaultdict(float), "tot": 0.0})
    for r in rows:
        if not r or c["kod"] is None or len(r) <= c["kod"]:
            continue
        kod = keyfn(r, c)
        if kod is None:
            continue
        parti = (r[c["parti"]] or "").strip() if c["parti"] is not None else ""
        try:
            rost = float((r[c["roster"]] or "0").replace("\xa0", "").replace(" ", "").replace(",", ".") or 0)
        except ValueError:
            rost = 0.0
        a = areas[kod]
        if namefn and not a["namn"]:
            a["namn"] = namefn(r, c)
        pl = parti.lower()
        if "giltiga" in pl and "ogilt" not in pl and "blank" not in pl:
            a["tot"] += rost; continue
        if is_skip(pl) or not parti:
            continue
        a["v"][parti] += rost
    return areas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kf"); ap.add_argument("--rf"); ap.add_argument("--rd")
    ap.add_argument("--min", type=float, default=1.0, help="Tröskel i procent (default 1.0)")
    ap.add_argument("-o", "--out", default="data/omraden_alla.csv")
    args = ap.parse_args()

    out_rows = []

    def emit(areas, niva, val):
        for kod, a in areas.items():
            tot = a["tot"] or sum(a["v"].values())
            if tot <= 0:
                continue
            for parti, rost in a["v"].items():
                andel = rost / tot * 100.0
                if andel >= args.min:
                    out_rows.append([niva, kod, a["namn"], val, parti_name(parti), round(andel, 2)])

    if args.kf:
        emit(aggregate(args.kf, "kommun",
                       keyfn=lambda r, c: (r[c["kod"]] or "").strip()[:4] if len(r[c["kod"]]) >= 4 else None,
                       namefn=lambda r, c: ""), "kommun", "KF")
    if args.rf:
        emit(aggregate(args.rf, "region",
                       keyfn=lambda r, c: (r[c["kod"]] or "").strip()[:2] if len(r[c["kod"]]) >= 2 else None,
                       namefn=lambda r, c: ""), "region", "RF")
    if args.rd:
        # per riksdagsvalkrets (namn) + riket
        vk = aggregate(args.rd, "valkrets",
                       keyfn=lambda r, c: (r[c["vkn"]] or "").strip() if c["vkn"] is not None else None,
                       namefn=lambda r, c: (r[c["vkn"]] or "").strip() if c["vkn"] is not None else "")
        emit(vk, "valkrets", "RD")
        riket = aggregate(args.rd, "riket", keyfn=lambda r, c: "00", namefn=lambda r, c: "Riket")
        emit(riket, "riket", "RD")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["niva", "kod", "namn", "val", "parti", "andel"])
        w.writerows(sorted(out_rows))
    print(f"Skrev {args.out}: {len(out_rows)} rader (partier ≥ {args.min}% per område).")


if __name__ == "__main__":
    main()
