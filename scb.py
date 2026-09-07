#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scb.py — SCB:s DeSO-filer + DeSO-gränser -> data/scb.csv per valdistrikt.

Två lägen:
  Utan geometri:  läser de fem SCB-filerna -> data/scb_deso.csv (kovariater per DeSO)
  Med geometri:   kopplar DeSO -> valdistrikt geografiskt -> data/scb.csv per valdistrikt

Kopplingen: för varje valdistrikt hittas det DeSO dess mittpunkt ligger i
(punkt-i-polygon). DeSO-gränserna läses ur SCB:s GeoPackage (.gpkg) med enbart
standardbiblioteket (sqlite3 + egen WKB-tolk). Koordinatsystem SWEREF99 TM,
samma som Valmyndighetens valdistriktsgeometri.

Exempel:
  python3 scb.py --income inkomst.csv --hyra hyresra_tt.csv --edu utbildning.csv \\
    --foreign utla_ndsk_bakgrund.csv --age a_lder.csv \\
    --deso-gpkg DeSO_2025.gpkg --valdistrikt data/valdistrikt-riket-2026.zip \\
    -o data/scb.csv

Endast Python-standardbibliotek. SCB-filerna är cp1252 med titelrad + tomrad + rubrik.
"""

import argparse
import csv
import io
import json
import re
import sqlite3
import struct
import sys
import zipfile
from pathlib import Path

DESO_YEARCOL = -1


# ---------- SCB-tabeller (per DeSO) ----------
def read_scb(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    reader = list(csv.reader(io.StringIO(text)))
    hi = 0
    for i, r in enumerate(reader[:12]):
        if any((c or "").strip().lower() == "region" for c in r):
            hi = i; break
    headers = [(c or "").strip() for c in reader[hi]]
    rows = [r for r in reader[hi + 1:] if any((c or "").strip() for c in r)]
    return headers, rows


def num(v):
    v = (v or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if v in ("", "..", ".", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def col(h, name):
    for i, c in enumerate(h):
        if c.strip().lower() == name:
            return i
    return None


def parse_income(path):
    h, rows = read_scb(path); ri = col(h, "region")
    return {r[ri].strip(): num(r[DESO_YEARCOL]) for r in rows if ri is not None and len(r) > ri and r[ri].strip()}


def parse_share(path, catname, num_cats, den_cats):
    h, rows = read_scb(path); ri = col(h, "region"); ci = col(h, catname)
    if ri is None or ci is None:
        sys.exit(f"Hittar inte region/'{catname}' i {path}. Rubriker: {h}")
    acc = {}
    for r in rows:
        if len(r) <= max(ri, ci):
            continue
        reg = r[ri].strip()
        if reg:
            acc.setdefault(reg, {})[r[ci].strip().lower()] = num(r[DESO_YEARCOL])
    out = {}
    for reg, d in acc.items():
        den = None
        for c in den_cats:
            if c == "__sum__":
                den = sum(v for v in d.values() if v is not None); break
            if d.get(c) is not None:
                den = d[c]; break
        if den and den > 0:
            out[reg] = sum((d.get(c) or 0) for c in num_cats) / den * 100.0
    return out


def _age_mid(cat):
    c = cat.lower().replace("år", "").strip()
    if c == "totalt":
        return None
    if c.startswith("80") or c.endswith(("-", "–", "+")):
        return 85.0
    m = re.findall(r"\d+", c)
    if len(m) >= 2:
        return (int(m[0]) + int(m[1])) / 2.0
    return float(m[0]) if m else None


def parse_age(path):
    h, rows = read_scb(path); ri = col(h, "region"); ci = col(h, "ålder")
    if ri is None or ci is None:
        sys.exit(f"Hittar inte region/ålder i {path}. Rubriker: {h}")
    acc = {}
    for r in rows:
        if len(r) <= max(ri, ci):
            continue
        reg = r[ri].strip(); v = num(r[DESO_YEARCOL])
        if not reg or v is None:
            continue
        d = acc.setdefault(reg, {"s": 0.0, "n": 0.0})
        m = _age_mid(r[ci].strip())
        if m is not None:
            d["s"] += m * v; d["n"] += v
    return {reg: d["s"] / d["n"] for reg, d in acc.items() if d["n"] > 0}


def per_deso(args):
    cov = {"income": {}, "hyra": {}, "edu": {}, "foreign": {}, "age": {}}
    if args.income and Path(args.income).exists():
        cov["income"] = parse_income(args.income)
    if args.hyra and Path(args.hyra).exists():
        cov["hyra"] = parse_share(args.hyra, "upplåtelseform", ["hyresrätt"], ["totalt"])
    if args.edu and Path(args.edu).exists():
        cov["edu"] = parse_share(args.edu, "utbildningsnivå",
                                 ["eftergymnasial utbildning, mindre än 3 år",
                                  "eftergymnasial utbildning, 3 år eller mer"], ["totalt", "__sum__"])
    if args.foreign and Path(args.foreign).exists():
        cov["foreign"] = parse_share(args.foreign, "utländsk/svensk bakgrund", ["utländsk bakgrund"], ["totalt"])
    if args.age and Path(args.age).exists():
        cov["age"] = parse_age(args.age)
    return cov


# ---------- DeSO-geometri (GPKG, stdlib) ----------
def _gpkg_rings(blob):
    flags = blob[3]; env = (flags >> 1) & 0x07
    envlen = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    wkb = blob[8 + envlen:]
    bo = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(bo + "I", wkb[1:5])[0] & 0xff
    off = 5; rings = []
    def rd(off):
        n = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4; rs = []
        for _ in range(n):
            m = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
            pts = struct.unpack(bo + f"{2*m}d", wkb[off:off + 16 * m]); off += 16 * m
            rs.append([(pts[2 * i], pts[2 * i + 1]) for i in range(m)])
        return rs, off
    if gtype == 3:
        rings, off = rd(off)
    elif gtype == 6:
        np_ = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
        for _ in range(np_):
            off += 5; rs, off = rd(off); rings += rs
    return rings


def _centroid(ring):
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]; x1, y1 = ring[i + 1]; cr = x0 * y1 - x1 * y0
        a += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
    if abs(a) < 1e-9:
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    a *= 0.5; return cx / (6 * a), cy / (6 * a)


def _pip(x, y, ring):
    inside = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def load_deso_polys(gpkg):
    con = sqlite3.connect(gpkg); cur = con.cursor()
    lyr = cur.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()[0]
    out = []
    for kod, kk, blob in cur.execute(f"SELECT desokod,kommunkod,sp_geometry FROM '{lyr}'"):
        try:
            ring = _gpkg_rings(blob)[0]
        except Exception:
            continue
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        out.append({"deso": kod, "kommun": str(kk).zfill(4), "ring": ring,
                    "bb": (min(xs), min(ys), max(xs), max(ys)), "c": _centroid(ring)})
    con.close(); return out


def _vd_features(path):
    p = Path(path); feats = []
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.lower().endswith((".geojson", ".json")):
                    feats += json.loads(z.read(n).decode("utf-8", "replace")).get("features", [])
    else:
        feats += json.loads(p.read_text(encoding="utf-8")).get("features", [])
    return feats


def _ring_of(geom):
    t = geom.get("type")
    if t == "Polygon":
        return geom["coordinates"][0]
    if t == "MultiPolygon":
        best, bn = None, -1
        for poly in geom["coordinates"]:
            if poly and len(poly[0]) > bn:
                best, bn = poly[0], len(poly[0])
        return best
    return None


def join_to_valdistrikt(cov, gpkg, vd_path, code_prop=None):
    polys = load_deso_polys(gpkg)
    CELL = 5000.0
    grid = {}
    for i, d in enumerate(polys):
        x0, y0, x1, y1 = d["bb"]
        for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
            for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
                grid.setdefault((gx, gy), []).append(i)
    feats = _vd_features(vd_path)
    props0 = feats[0].get("properties", {}) if feats else {}
    if not code_prop:
        code_prop = next((k for k in props0 if "valdist" in k.lower() and "kod" in k.lower()), None) \
            or next((k for k, v in props0.items() if isinstance(v, (str, int)) and str(v).isdigit() and 6 <= len(str(v)) <= 10), None)
    if not code_prop:
        sys.exit(f"Hittar inget valdistriktskod-fält i geojson. Properties: {list(props0)}")
    out = {}; miss = 0
    for ft in feats:
        code = str((ft.get("properties") or {}).get(code_prop, "")).strip()
        ring = _ring_of(ft.get("geometry") or {})
        if not code or not ring:
            continue
        cx, cy = _centroid(ring)
        hit = None
        for i in grid.get((int(cx // CELL), int(cy // CELL)), []):
            if _pip(cx, cy, polys[i]["ring"]):
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
        out[code] = {k: cov.get(k, {}).get(hit["deso"]) for k in ("income", "hyra", "edu", "foreign", "age")}
    return out, miss, code_prop


def main():
    ap = argparse.ArgumentParser(description="SCB DeSO-filer -> kovariater per DeSO/valdistrikt")
    ap.add_argument("--income"); ap.add_argument("--hyra"); ap.add_argument("--edu")
    ap.add_argument("--foreign"); ap.add_argument("--age")
    ap.add_argument("--deso-gpkg", help="SCB DeSO-gränser (GeoPackage .gpkg)")
    ap.add_argument("--valdistrikt", help="Valdistriktsgeometri (val.se geojson/zip)")
    ap.add_argument("--geo-code-prop", default=None)
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    cov = per_deso(args)
    for k, m in cov.items():
        print(f"  {k}: {len(m)} DeSO med värde" + ("  (TOM – saknar 'totalt'?)" if not m else ""))

    if args.deso_gpkg and args.valdistrikt:
        out = args.out or "data/scb.csv"
        vd, miss, cp = join_to_valdistrikt(cov, args.deso_gpkg, args.valdistrikt, args.geo_code_prop)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["distrikt_kod", "income", "edu", "foreign", "turnout", "age", "hyra"])
            for code in sorted(vd):
                c = vd[code]
                g = lambda k: "" if c.get(k) is None else round(c[k], 2)
                w.writerow([code, g("income"), g("edu"), g("foreign"), "", g("age"), g("hyra")])
        print(f"Kopplade {len(vd)} valdistrikt till DeSO (kodfält '{cp}', {miss} utan träff).")
        print(f"Skrev {out} per valdistrikt.")
    else:
        out = args.out or "data/scb_deso.csv"
        desos = set()
        for m in cov.values():
            desos |= set(m)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["deso", "income", "hyra", "edu", "foreign", "age"])
            for d in sorted(desos):
                g = lambda k: "" if cov[k].get(d) is None else round(cov[k][d], 2)
                w.writerow([d, g("income"), g("hyra"), g("edu"), g("foreign"), g("age")])
        print(f"Skrev {out} ({len(desos)} DeSO). Ange --deso-gpkg och --valdistrikt för koppling till valdistrikt.")


if __name__ == "__main__":
    main()
