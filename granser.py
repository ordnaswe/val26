#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
granser.py — slår ihop RegSO-polygoner (SCB GeoPackage) till KOMMUN- och LÄNS-gränser
via kant-cancellering, förenklar dem (Douglas–Peucker) och skriver data/granser.json.

    python3 granser.py RegSO_2025.gpkg -o data/granser.json --tol 200

Utdata (SWEREF99 TM, samma som valdistriktsgeometrin):
    {"kommun": {"0120":[[[x,y],...],...], ...}, "lan": {"18":[[...]], ...}}

Endast standardbibliotek (sqlite3 + egen WKB-tolk).
"""
import argparse, json, math, sqlite3, struct
from collections import defaultdict, Counter
from pathlib import Path


def gpkg_rings(blob):
    flags = blob[3]; env = (flags >> 1) & 0x07
    envlen = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    wkb = blob[8 + envlen:]; bo = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(bo + "I", wkb[1:5])[0] & 0xff; off = 5; rings = []
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


def _ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2.0


def dissolve(feature_rings, Q=1.0, min_area=200000.0):
    """Kant-cancellering + korrekt gränsföljning: kanter utan motsatt tvilling är yttre
    gräns; vid korsningar väljs nästa kant efter vinkel (så ringar sluts rätt utan streck
    tvärs vatten). Behåller slutna ringar över min_area."""
    key = lambda p: (round(p[0] / Q), round(p[1] / Q))
    directed = set()
    for rings in feature_rings:
        for ring in rings:
            for i in range(len(ring) - 1):
                a, b = key(ring[i]), key(ring[i + 1])
                if a != b:
                    directed.add((a, b))
    boundary = set((a, b) for (a, b) in directed if (b, a) not in directed)
    nxt = defaultdict(list)
    for a, b in boundary:
        nxt[a].append(b)
    ang = lambda o, p: math.atan2(p[1] - o[1], p[0] - o[0])
    used = set(); out = []
    for e0 in boundary:
        if e0 in used:
            continue
        a0, b0 = e0; ring = [a0]; cur, nb = a0, b0; closed = False
        while True:
            used.add((cur, nb)); ring.append(nb)
            if nb == a0:
                closed = True; break
            cands = [x for x in nxt[nb] if (nb, x) not in used]
            if not cands:
                break
            if len(cands) == 1:
                nv = cands[0]
            else:
                rev = ang(nb, cur)                      # riktning tillbaka
                def cw(x):
                    d = (rev - ang(nb, x)) % (2 * math.pi)
                    return d if d > 1e-9 else 2 * math.pi
                nv = min(cands, key=cw)                  # nästa kant medurs
            cur, nb = nb, nv
            if len(ring) > 1000000:
                break
        if len(ring) >= 4:
            if ring[-1] != ring[0]:
                ring.append(ring[0])   # tvinga slutning vid dödläge (T-korsningar i rådata)
            r = [(x * Q, y * Q) for x, y in ring]
            if _ring_area(r) >= min_area:
                out.append(r)
    return out


def _perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        d = _perp(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        return rdp(pts[:idx + 1], tol)[:-1] + rdp(pts[idx:], tol)
    return [pts[0], pts[-1]]


def simplify_rings(rings, tol, min_pts=8):
    out = []
    for r in rings:
        s = rdp(r, tol)
        if len(s) >= 4:
            out.append([[round(x, 1), round(y, 1)] for x, y in s])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpkg")
    ap.add_argument("-o", "--out", default="data/granser.json")
    ap.add_argument("--tol", type=float, default=150.0, help="Förenklingstolerans i meter (default 150)")
    ap.add_argument("--snap", type=float, default=1.0, help="Snäpp hörn till N meter vid sammanslagning (default 50)")
    ap.add_argument("--minkm2", type=float, default=0.2, help="Minsta ytstorlek som behålls, km² (default 0.2)")
    args = ap.parse_args()

    con = sqlite3.connect(args.gpkg); cur = con.cursor()
    lyr = cur.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()[0]
    by_kom, by_lan = defaultdict(list), defaultdict(list)
    for kk, lk, blob in cur.execute(f"SELECT kommunkod,lanskod,sp_geometry FROM '{lyr}'"):
        try:
            r = gpkg_rings(blob)
        except Exception:
            continue
        by_kom[str(kk).zfill(4)].append(r)
        by_lan[str(lk).zfill(2)].append(r)
    con.close()

    min_area = args.minkm2 * 1_000_000.0
    # steg 1: exakta kommun-ringar (Q=1, ingen förenkling ännu)
    kom_exact = {}
    for kk, feats in by_kom.items():
        dz = dissolve(feats, args.snap, min_area)
        if not dz:   # fallback: råa RegSO-ringar för kommunen
            dz = [ring for f in feats for ring in f if len(ring) >= 4 and _ring_area(ring) >= min_area]
        kom_exact[kk] = dz
    # steg 2: län = sammanslagning av länets exakta kommun-ringar (färre T-korsningar -> rena länskonturer)
    lan_koms = defaultdict(list)
    for kk in kom_exact:
        lan_koms[kk[:2]].append(kk)
    out = {"kommun": {}, "lan": {}}
    for kk, rr in kom_exact.items():
        out["kommun"][kk] = simplify_rings(rr, args.tol)
    for lk, koms in lan_koms.items():
        feats = [kom_exact[kk] for kk in koms if kom_exact[kk]]
        dz = dissolve(feats, args.snap, min_area)
        if not dz:   # sista fallback: länets kommun-ringar
            dz = [r for kk in koms for r in kom_exact[kk]]
        out["lan"][lk] = simplify_rings(dz, args.tol)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    kpts = sum(len(r) for rr in out["kommun"].values() for r in rr)
    lpts = sum(len(r) for rr in out["lan"].values() for r in rr)
    print(f"Skrev {args.out}: {len(out['kommun'])} kommuner ({kpts} punkter), "
          f"{len(out['lan'])} län ({lpts} punkter), {Path(args.out).stat().st_size//1024} kB.")


if __name__ == "__main__":
    main()
