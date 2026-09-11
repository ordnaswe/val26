#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
syss.py — lägger till SYSSELSÄTTNINGSGRAD (andel förvärvsarbetande 20-64 år, %) per
valdistrikt i data/scb.csv, ur SCB:s DeSO-tabell BefDeSoSyssN (2021).

Per DeSO: förvärvsfrekvens = förvärvsarbetande / (förvärvsarbetande + ej förvärvsarbetande) × 100.
Varje valdistrikt får värdet för den DeSO dess mittpunkt ligger i (samma punkt-i-polygon
som scb.py/urban.py). Rör inte övriga kolumner — lägger bara till 'syss'.

Kör:
  python3 syss.py --deso-gpkg ../Bakgrundsfiler/DeSO_2025.gpkg \
        --valdistrikt data/valdistrikt-riket-2026.zip \
        --syssfil ../Bakgrundsfiler/deso_sysselsattning.csv --scb data/scb.csv
"""
import argparse, csv, sys, io
from pathlib import Path
import scb  # scb.py i samma mapp

def read_deso_freq(path):
    """SCB PxWeb-CSV (latin-1, ';') -> {desokod: förvärvsfrekvens %}."""
    raw = Path(path).read_bytes().decode("latin-1")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    # hitta header-raden med 'region'
    hi = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "region"), None)
    if hi is None:
        sys.exit("Hittar ingen 'region'-header i syssfilen.")
    hdr = [c.strip().lower() for c in rows[hi]]
    ri = hdr.index("region"); si = hdr.index("sysselsättning") if "sysselsättning" in hdr else 1
    vi = len(hdr) - 1  # sista kolumnen = årtalet (2021)
    agg = {}
    for r in rows[hi + 1:]:
        if len(r) <= vi or not r[ri].strip():
            continue
        deso = r[ri].strip()
        kat = r[si].strip().lower()
        try:
            v = float((r[vi] or "0").replace(" ", "").replace(",", "."))
        except ValueError:
            continue
        d = agg.setdefault(deso, {"forv": 0.0, "ej": 0.0})
        if kat.startswith("ej"):
            d["ej"] += v
        elif "förv" in kat:
            d["forv"] += v
    freq = {}
    for deso, d in agg.items():
        tot = d["forv"] + d["ej"]
        if tot > 0:
            freq[deso] = round(d["forv"] / tot * 100, 2)
    return freq

def valdistrikt_syss(gpkg, vd_path, freq, code_prop=None):
    polys = scb.load_deso_polys(gpkg)
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
        out[code] = freq.get(hit["deso"])
    return out, miss, code_prop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deso-gpkg", required=True)
    ap.add_argument("--valdistrikt", required=True)
    ap.add_argument("--syssfil", required=True)
    ap.add_argument("--scb", default="data/scb.csv")
    ap.add_argument("--geo-code-prop", default=None)
    a = ap.parse_args()
    freq = read_deso_freq(a.syssfil)
    print(f"Läste förvärvsfrekvens för {len(freq)} DeSO (medel {sum(freq.values())/len(freq):.1f} %).", file=sys.stderr)
    vd, miss, cp = valdistrikt_syss(a.deso_gpkg, a.valdistrikt, freq, a.geo_code_prop)
    have = sum(1 for v in vd.values() if v is not None)
    print(f"Kopplade {len(vd)} valdistrikt (kodfält '{cp}', {miss} utan träff), {have} med värde.", file=sys.stderr)

    rows = list(csv.reader(open(a.scb, encoding="utf-8")))
    hdr = rows[0]
    if "syss" in hdr:
        si = hdr.index("syss")
    else:
        hdr.append("syss"); si = len(hdr) - 1
        for r in rows[1:]:
            r.append("")
    kod_i = hdr.index("distrikt_kod")
    n = 0
    for r in rows[1:]:
        while len(r) <= si: r.append("")
        v = vd.get(r[kod_i].strip())
        r[si] = "" if v is None else v
        if v is not None: n += 1
    with open(a.scb, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"Skrev 'syss' till {a.scb} för {n} distrikt.", file=sys.stderr)

if __name__ == "__main__":
    main()
