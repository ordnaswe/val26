#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
urban.py — lägger till en ORT-TYP-kolumn (urbanitet) per valdistrikt i data/scb.csv.

Härleds ur SCB:s DeSO-kod: femte tecknet är A/B/C = landsbygd / tätortsnära / stad
(SCB:s DeSO-regionindelning). Varje valdistrikt får klassen för den DeSO dess mittpunkt
ligger i (samma punkt-i-polygon-koppling som scb.py använder). Kodas ordinalt:
  A = 0 (landsbygd), B = 1 (tätortsnära), C = 2 (stad).

Återanvänder geometrifunktionerna i scb.py (måste ligga i samma mapp). Rör inte de
befintliga kolumnerna (income/edu/foreign/turnout/age/hyra) — bara lägger till 'urban'.

Kör:
  python3 urban.py --deso-gpkg ../Bakgrundsfiler/DeSO_2025.gpkg \
        --valdistrikt data/valdistrikt-riket-2026.zip --scb data/scb.csv
"""
import argparse, csv, sys
from pathlib import Path
import scb  # scb.py i samma mapp

URBAN = {"A": 0, "B": 1, "C": 2}

def valdistrikt_urban(gpkg, vd_path, code_prop=None):
    polys = scb.load_deso_polys(gpkg)
    for d in polys:
        d["urban"] = URBAN.get((d["deso"][4:5] or "").upper())
    CELL = 5000.0
    grid = {}
    for i, d in enumerate(polys):
        x0, y0, x1, y1 = d["bb"]
        for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
            for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
                grid.setdefault((gx, gy), []).append(i)
    feats = scb._vd_features(vd_path)
    props0 = feats[0].get("properties", {}) if feats else {}
    if not code_prop:
        code_prop = next((k for k in props0 if "valdist" in k.lower() and "kod" in k.lower()), None) \
            or next((k for k, v in props0.items() if isinstance(v, (str, int)) and str(v).isdigit() and 6 <= len(str(v)) <= 10), None)
    if not code_prop:
        sys.exit(f"Hittar inget valdistriktskod-fält. Properties: {list(props0)}")
    out = {}; miss = 0
    for ft in feats:
        code = str((ft.get("properties") or {}).get(code_prop, "")).strip()
        ring = scb._ring_of(ft.get("geometry") or {})
        if not code or not ring:
            continue
        cx, cy = scb._centroid(ring)
        hit = None
        for i in grid.get((int(cx // CELL), int(cy // CELL)), []):
            if scb._pip(cx, cy, polys[i]["ring"]):
                hit = polys[i]; break
        if hit is None:
            kk = code[:4]; best, bd = None, 1e30
            for d in polys:
                if d["kommun"] != kk:
                    continue
                dd = (d["c"][0] - cx) ** 2 + (d["c"][1] - cy) ** 2
                if dd < bd:
                    bd, best = dd, d
            hit = best
        if hit is None:
            miss += 1; continue
        out[code] = hit.get("urban")
    return out, miss, code_prop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deso-gpkg", required=True)
    ap.add_argument("--valdistrikt", required=True)
    ap.add_argument("--scb", default="data/scb.csv")
    ap.add_argument("--geo-code-prop", default=None)
    a = ap.parse_args()
    urb, miss, cp = valdistrikt_urban(a.deso_gpkg, a.valdistrikt, a.geo_code_prop)
    have = sum(1 for v in urb.values() if v is not None)
    print(f"Urbanitet: {len(urb)} valdistrikt kopplade (kodfält '{cp}', {miss} utan träff), {have} med klass.", file=sys.stderr)

    rows = list(csv.reader(open(a.scb, encoding="utf-8")))
    hdr = rows[0]
    if "urban" in hdr:
        ui = hdr.index("urban")
    else:
        hdr.append("urban"); ui = len(hdr) - 1
        for r in rows[1:]:
            r.append("")
    kod_i = hdr.index("distrikt_kod")
    n = 0
    for r in rows[1:]:
        while len(r) <= ui: r.append("")
        v = urb.get(r[kod_i].strip())
        r[ui] = "" if v is None else v
        if v is not None: n += 1
    with open(a.scb, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerows(rows)
    from collections import Counter
    dist = Counter(r[ui] for r in rows[1:])
    print(f"Skrev 'urban' till {a.scb} för {n} distrikt. Fördelning (0 landsb/1 tätortsnära/2 stad):", dict(dist), file=sys.stderr)

if __name__ == "__main__":
    main()
