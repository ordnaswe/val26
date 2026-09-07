#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — bygger en självständig valdistrikts-HTML från riktiga indatafiler.

Kör utan argument -> SYNTETISKT exempeldata (med geometri) och sidan byggs:
    python3 build.py
    -> dist/valdistrikt.html  (Kartogram/Geografi/Rutnät fungerar direkt)

Med riktiga filer:
    python3 build.py --districts distrikt.csv --covariates scb.csv \\
                     --history historik.csv --geojson valdistrikt.geojson

Skapa exempel-filer (inkl. GeoJSON) att utgå ifrån:
    python3 build.py --emit-sample sample/

Endast Python-standardbibliotek.

------------------------------------------------------------------------------
SCHEMA (CSV, UTF-8, komma-separerat, header rad 1)
------------------------------------------------------------------------------
distrikt.csv  (partikolumner = ANTAL RÖSTER)
    distrikt_kod,distrikt_namn,kommun_kod,kommun_namn,lan_namn,rost_berattigade,V,S,MP,C,L,KD,M,SD
scb.csv       (kovariater; valfria kolumner)
    distrikt_kod,income,edu,foreign,turnout,age,hyra
historik.csv  (lång form; VALFRI)
    distrikt_kod,year,party,share

GEOJSON (valfri): FeatureCollection av valdistrikt-polygoner.
    Varje feature kopplas till distrikt via en property som matchar distrikt_kod.
    Ange vilken med --geo-code-prop (default provar flera vanliga namn).
    Koordinater i valfritt CRS (lon/lat eller SWEREF99 TM) – de skalas till en
    normaliserad ruta. OBS: läget blir korrekt, men detta gör ingen egentlig
    kartprojektion; för millimeterrätt läge projicera i förväg till WGS84.
------------------------------------------------------------------------------
"""

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

PARTIES = [
    {"id": "V",  "namn": "Vänsterpartiet",      "color": "#a30b28"},
    {"id": "S",  "namn": "Socialdemokraterna",  "color": "#e11d2a"},
    {"id": "MP", "namn": "Miljöpartiet",        "color": "#6cc24a"},
    {"id": "C",  "namn": "Centerpartiet",       "color": "#0a8a3f"},
    {"id": "L",  "namn": "Liberalerna",         "color": "#5fb4e5"},
    {"id": "KD", "namn": "Kristdemokraterna",   "color": "#1d2a76"},
    {"id": "M",  "namn": "Moderaterna",         "color": "#1e5bb8"},
    {"id": "SD", "namn": "Sverigedemokraterna", "color": "#e0b400"},
]
PIDS = [p["id"] for p in PARTIES]

COV_META = {
    "income":  {"lab": "Medianinkomst (tkr)",                 "unit": "tkr"},
    "edu":     {"lab": "Andel eftergymnasialt utbildade (%)", "unit": "%"},
    "foreign": {"lab": "Andel med utländsk bakgrund (%)",     "unit": "%"},
    "turnout": {"lab": "Valdeltagande (%)",                   "unit": "%"},
    "age":     {"lab": "Medelålder (år)",                     "unit": "år"},
    "hyra":    {"lab": "Andel i hyresrätt (%)",               "unit": "%"},
}
COV_KEYS = list(COV_META.keys())
MODEL_PREDICTORS = ["income", "edu", "foreign"]

ELYEARS = [2014, 2018, 2022, 2026]
CURRENT_YEAR = ELYEARS[-1]
PREV_YEAR = ELYEARS[-2]

# de tre valen
VALS = ["RD", "RF", "KF"]
VAL_NAMN = {"RD": "Riksdagsval", "RF": "Regionval", "KF": "Kommunval"}

# partimodell (delas av synth och synth_geo)
_BASE = {"V": 7, "S": 26, "MP": 5, "C": 7, "L": 5, "KD": 5, "M": 19, "SD": 20}
_BINC = {"V": -1, "S": -4.5, "MP": .5, "C": .5, "L": 3, "KD": 1, "M": 6, "SD": -4}
_BEDU = {"V": 4, "S": -2, "MP": 4, "C": -.5, "L": 3, "KD": -.5, "M": 3.5, "SD": -6.5}
_BURB = {"V": 3, "S": .5, "MP": 3.5, "C": -4, "L": 1.5, "KD": -.5, "M": .8, "SD": -3}
_NAT = {"V": [-1, 0, 1, 1], "S": [4, 2, 0, -1], "MP": [2, 1, -1, 0], "C": [-1, 1, 1, -1],
        "L": [1, 0, -1, -1], "KD": [-1, -1, 1, 0], "M": [3, 1, 0, -1], "SD": [-6, -2, 1, 4]}
# röstsplittring: hur valet skiljer sig från riksdagsvalet (additiv tilt före normalisering)
_TILT = {"RD": {}, "RF": {"S": 2, "C": 1.5, "SD": -1.5, "MP": -.5, "V": .5},
         "KF": {"S": 4, "C": 3, "SD": -3, "MP": -1, "M": -1, "L": -.5}}


def _norm100(d):
    s = sum(d.values())
    return {k: (v / s * 100 if s else 0) for k, v in d.items()}


def gen_elections(aff, urb, edu, rng):
    """Skapa tre val (RD/RF/KF) med realistisk röstsplittring OCH en egen
    historik-serie per val. Returnerar (el, rd_series) där varje el[val] har
    shares/changes/top/series."""
    rawRD = {p: _BASE[p] + _BINC[p] * aff + _BEDU[p] * ((edu - 40) / 12) + _BURB[p] * urb for p in PIDS}
    el = {}
    for val in VALS:
        tilt = _TILT[val]
        ser = {p: [max(.3, min(62, rawRD[p] + tilt.get(p, 0) + _NAT[p][t] + rng.gauss(0, 1.5)))
                   for t in range(len(ELYEARS))] for p in PIDS}
        for t in range(len(ELYEARS)):
            s = sum(ser[p][t] for p in PIDS)
            for p in PIDS:
                ser[p][t] = ser[p][t] / s * 100.0
        cur = {p: ser[p][-1] for p in PIDS}
        el[val] = {"shares": cur, "series": ser,
                   "changes": {p: ser[p][-1] - ser[p][-2] for p in PIDS},
                   "top": max(PIDS, key=lambda p: cur[p]),
                   "w": [None] * len(ELYEARS)}
    return el, el["RD"]["series"]

# normaliserad ritruta för geometrin
GEO_W = 1000.0
GEO_CODE_PROP_CANDIDATES = ["distrikt_kod", "Vdkod", "VDKOD", "Lkfv", "LKFV", "vdkod", "kod", "code"]


# ============================================================
#  Inläsning (CSV)
# ============================================================
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_float(v):
    if v is None:
        return None
    v = str(v).strip().replace(" ", "").replace(",", ".")
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_real(dist_path, cov_path, hist_path):
    districts = []
    for r in read_csv(dist_path):
        votes = {pid: (to_float(r.get(pid)) or 0.0) for pid in PIDS}
        giltiga = to_float(r.get("giltiga"))
        total = giltiga if (giltiga and giltiga > 0) else sum(votes.values())
        shares = {pid: (votes[pid] / total * 100.0 if total else 0.0) for pid in PIDS}
        d = {
            "distrikt_kod": (r.get("distrikt_kod") or "").strip(),
            "namn": (r.get("distrikt_namn") or "").strip(),
            "kommun": (r.get("kommun_namn") or "").strip(),
            "lan": (r.get("lan_namn") or "").strip(),
            "rost": int(to_float(r.get("rost_berattigade")) or 0),
            "raknat": 1 if (to_float(r.get("raknat")) or (1 if (giltiga and giltiga > 0) else 0)) else 0,
            "shares": shares,
            "series": {pid: [None] * len(ELYEARS) for pid in PIDS},
        }
        for pid in PIDS:
            d["series"][pid][ELYEARS.index(CURRENT_YEAR)] = shares[pid]
        districts.append(d)

    by_kod = {d["distrikt_kod"]: d for d in districts}

    if cov_path:
        for r in read_csv(cov_path):
            d = by_kod.get((r.get("distrikt_kod") or "").strip())
            if d:
                for k in COV_KEYS:
                    d[k] = to_float(r.get(k))
    for d in districts:
        for k in COV_KEYS:
            d.setdefault(k, None)

    if hist_path:
        for r in read_csv(hist_path):
            d = by_kod.get((r.get("distrikt_kod") or "").strip())
            if not d:
                continue
            yr, pid, sh = to_float(r.get("year")), (r.get("party") or "").strip(), to_float(r.get("share"))
            if yr is not None and pid in PIDS and sh is not None and int(yr) in ELYEARS:
                d["series"][pid][ELYEARS.index(int(yr))] = sh

    return districts


# ============================================================
#  GeoJSON
# ============================================================
def _outer_ring(geom):
    """Returnera yttre ringen (lista av [x,y]) för Polygon/MultiPolygon; störst vinner."""
    t = geom.get("type")
    if t == "Polygon":
        return geom["coordinates"][0] if geom["coordinates"] else None
    if t == "MultiPolygon":
        best, bestn = None, -1
        for poly in geom["coordinates"]:
            if poly and len(poly[0]) > bestn:
                best, bestn = poly[0], len(poly[0])
        return best
    return None


def _read_geojson_features(path):
    """Läs features ur .geojson/.json ELLER ur en .zip (t.ex. val.se:s länsfiler
    eller riksfilen). Slår ihop alla json-medlemmar i zippen."""
    import zipfile
    p = Path(path)
    feats = []
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.lower().endswith((".geojson", ".json")):
                    gj = json.loads(z.read(n).decode("utf-8", "replace"))
                    feats += gj.get("features", [])
    else:
        gj = json.loads(p.read_text(encoding="utf-8"))
        feats += gj.get("features", [])
    return feats


def load_geojson(path, code_prop, district_codes=None):
    """Returnerar (rings_by_code, valt_kodfält). Om code_prop saknas väljs det
    property vars värden bäst matchar distriktskoderna i datan – så det funkar
    oavsett vad val.se döpt fältet till."""
    feats = _read_geojson_features(path)
    if not feats:
        return {}, code_prop, {}
    props0 = feats[0].get("properties", {}) or {}
    if not code_prop:
        dc = {str(c).strip() for c in (district_codes or set())}
        if dc:
            best, best_hits = None, -1
            for k, v in props0.items():
                if not isinstance(v, (str, int, float)):
                    continue
                hits = sum(1 for ft in feats
                           if str((ft.get("properties") or {}).get(k, "")).strip() in dc)
                if hits > best_hits:
                    best, best_hits = k, hits
            code_prop = best
            print(f"GeoJSON: valt kodfält '{code_prop}' ({best_hits} träffar mot distriktskoder).",
                  file=sys.stderr)
        else:
            # ingen datamatchning (förhandsvisning): välj fält vars värden ser ut
            # som valdistriktskoder (mest siffersträngar av längd 6–10, unika).
            best, best_score = None, -1.0
            for k in props0.keys():
                vals = [str((ft.get("properties") or {}).get(k, "")).strip() for ft in feats]
                digitish = sum(1 for v in vals if v.isdigit() and 6 <= len(v) <= 10)
                uniq = len(set(vals))
                score = digitish + uniq * 0.001
                if score > best_score:
                    best, best_score = k, score
            code_prop = best
            print(f"GeoJSON: gissade kodfält '{code_prop}' utifrån kodformat.", file=sys.stderr)
    if not code_prop:
        sys.exit("Kunde inte hitta GeoJSON-kodfält. Ange --geo-code-prop. "
                 f"Tillgängliga properties: {', '.join(props0.keys())}")
    rings = {}
    for ft in feats:
        code = str((ft.get("properties") or {}).get(code_prop, "")).strip()
        ring = _outer_ring(ft.get("geometry") or {})
        if code and ring:
            rings[code] = [[float(p[0]), float(p[1])] for p in ring]
    # hitta namnfält: mest bokstäver + högst unikhet (valdistriktsnamn är distinkt),
    # men inte kodfältet.
    name_prop, best = None, -1.0
    for k in props0.keys():
        if k == code_prop:
            continue
        vals = [str((ft.get("properties") or {}).get(k, "")) for ft in feats]
        alpha = sum(1 for v in vals if any(c.isalpha() for c in v))
        score = alpha + len(set(vals)) * 0.002
        if score > best:
            name_prop, best = k, score
    names = {}
    if name_prop:
        for ft in feats:
            code = str((ft.get("properties") or {}).get(code_prop, "")).strip()
            nm = str((ft.get("properties") or {}).get(name_prop, "")).strip()
            if code and nm:
                names[code] = nm
        print(f"GeoJSON: namnfält '{name_prop}'.", file=sys.stderr)
    return rings, code_prop, names


def _bbox(all_pts):
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    return min(xs), min(ys), max(xs), max(ys)


def make_projector(rings_by_code):
    all_pts = [p for ring in rings_by_code.values() for p in ring]
    if not all_pts:
        return None, GEO_W, GEO_W * 0.6
    minx, miny, maxx, maxy = _bbox(all_pts)
    dx, dy = (maxx - minx) or 1.0, (maxy - miny) or 1.0
    degrees = (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90)
    xscale = math.cos(math.radians((miny + maxy) / 2)) if degrees else 1.0
    effdx = dx * xscale
    W = GEO_W
    H = W * (dy / effdx) if effdx else W * 0.6

    def proj(x, y):
        px = (x - minx) * xscale / effdx * W
        py = (maxy - y) / dy * H          # flippa så norr är upp
        return [round(px, 1), round(py, 1)]

    return proj, round(W, 1), round(H, 1)


def _rdp(points, eps):
    """Douglas–Peucker, iterativ (klarar stora ringar utan rekursionsdjup)."""
    n = len(points)
    if n < 3:
        return points[:]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        ax, ay = points[s]
        bx, by = points[e]
        dx, dy = bx - ax, by - ay
        nrm = math.hypot(dx, dy) or 1e-9
        idx, dmax = -1, eps
        for i in range(s + 1, e):
            px, py = points[i]
            d = abs((px - ax) * dy - (py - ay) * dx) / nrm
            if d > dmax:
                idx, dmax = i, d
        if idx != -1:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [points[i] for i in range(n) if keep[i]]


def simplify_ring(ring, max_points):
    """Förenkla en (projicerad) sluten ring formtroget med Douglas–Peucker.
    Slutna ringar delas vid den mest avlägsna punkten för att undvika en
    degenererad startlinje (annars kollapsar ringen)."""
    if len(ring) <= 6:
        return ring
    closed = ring[0] == ring[-1]
    pts = ring[:-1] if closed else ring[:]
    if len(pts) <= 4:
        return ring
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    eps = diag * 0.0012
    a = pts[0]
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - a[0]) ** 2 + (pts[i][1] - a[1]) ** 2)
    r = _rdp(pts[:far + 1], eps)[:-1] + _rdp(pts[far:] + [pts[0]], eps)[:-1]
    if len(r) > max_points:
        step = len(r) / max_points
        r = [r[int(i * step)] for i in range(max_points)]
    if r:
        r.append(r[0])
    return r


def polygon_centroid(ring):
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def dorling(items, canvas_w, canvas_h, iters=90, pad=0.6, spring=0.02, damping=0.5):
    """Dorling-cartogram: sprid cirklar (yta ∝ rost) från sina ankarpunkter
    tills de inte överlappar. Grid-baserad grannkoll -> nära O(n) per varv."""
    if not items:
        return
    med_r = sorted(c["r"] for c in items)[len(items) // 2]
    cell = max(1.0, med_r * 2.0)
    for _ in range(iters):
        grid = {}
        for idx, c in enumerate(items):
            grid.setdefault((int(c["x"] // cell), int(c["y"] // cell)), []).append(idx)
        for idx, c in enumerate(items):
            gx, gy = int(c["x"] // cell), int(c["y"] // cell)
            for ny in range(gy - 1, gy + 2):
                for nx in range(gx - 1, gx + 2):
                    for jdx in grid.get((nx, ny), ()):
                        if jdx <= idx:
                            continue
                        o = items[jdx]
                        ddx, ddy = o["x"] - c["x"], o["y"] - c["y"]
                        d = math.hypot(ddx, ddy) or 1e-6
                        mind = c["r"] + o["r"] + pad
                        if d < mind:
                            push = (mind - d) / 2 * damping
                            ux, uy = ddx / d, ddy / d
                            c["x"] -= ux * push; c["y"] -= uy * push
                            o["x"] += ux * push; o["y"] += uy * push
            c["x"] += (c["ax"] - c["x"]) * spring
            c["y"] += (c["ay"] - c["y"]) * spring
        for c in items:
            c["x"] = min(canvas_w - c["r"], max(c["r"], c["x"]))
            c["y"] = min(canvas_h - c["r"], max(c["r"], c["y"]))


def attach_geometry(districts, rings_by_code, max_points):
    """Projicerar polygoner, förenklar dem, och bygger Dorling-layout.
    Returnerar (geo_w, geo_h, has_geo)."""
    have = {d["distrikt_kod"]: d for d in districts if d.get("distrikt_kod") in rings_by_code}
    if not have:
        return GEO_W, GEO_W * 0.6, False
    proj, geo_w, geo_h = make_projector({k: rings_by_code[k] for k in have})
    # projicera + förenkla polygoner, räkna centroid
    anchors = []
    for kod, d in have.items():
        ring = [proj(x, y) for x, y in rings_by_code[kod]]
        d["poly"] = simplify_ring(ring, max_points)
        cx, cy = polygon_centroid(ring)
        d["_cx"], d["_cy"] = cx, cy
    # Dorling: radie ∝ sqrt(rost), fyller ~55 % av ytan
    n = len(have)
    rosts = [max(1, d.get("rost", 1)) for d in have.values()]
    mean_rost = sum(rosts) / n
    rbar = math.sqrt(0.55 * geo_w * geo_h / (math.pi * n))
    items, order = [], list(have.values())
    for d in order:
        r = rbar * math.sqrt(max(1, d.get("rost", 1)) / mean_rost)
        items.append({"x": d["_cx"], "y": d["_cy"], "ax": d["_cx"], "ay": d["_cy"], "r": r})
    dorling(items, geo_w, geo_h)
    for d, it in zip(order, items):
        d["dor"] = {"x": round(it["x"], 1), "y": round(it["y"], 1), "r": round(it["r"], 1)}
    return geo_w, geo_h, True


# ============================================================
#  Syntetiskt exempeldata (med geometri: verkliga kommun-koordinater)
# ============================================================
KOM_CENTER = {  # ungefärliga lon/lat – bara för att ge igenkännbar Sverige-form
    "Stockholm": (18.07, 59.33), "Värmdö": (18.40, 59.31), "Nacka": (18.16, 59.31),
    "Solna": (18.00, 59.36), "Botkyrka": (17.83, 59.20), "Täby": (18.06, 59.44),
    "Göteborg": (11.97, 57.70), "Malmö": (13.00, 55.60), "Uppsala": (17.64, 59.86),
    "Borlänge": (15.42, 60.48), "Sundsvall": (17.31, 62.39), "Umeå": (20.26, 63.83),
}
KOM2LAN = {
    "Stockholm": "Stockholms län", "Värmdö": "Stockholms län", "Nacka": "Stockholms län",
    "Solna": "Stockholms län", "Botkyrka": "Stockholms län", "Täby": "Stockholms län",
    "Göteborg": "Västra Götaland", "Malmö": "Skåne", "Uppsala": "Uppsala län",
    "Borlänge": "Dalarna", "Sundsvall": "Västernorrland", "Umeå": "Västerbotten",
}


def synth(n=620, seed=42):
    random.seed(seed)
    koms = list(KOM_CENTER.keys())
    ort = ["Centrum", "Norra", "Södra", "Östra", "Västra", "Höjden", "Strand",
           "Berga", "Ängsvik", "Hamnen", "Gärdet", "Åsen", "Bruket", "Lugnet"]
    base = {"V": 7, "S": 26, "MP": 5, "C": 7, "L": 5, "KD": 5, "M": 19, "SD": 20}
    binc = {"V": -1, "S": -4.5, "MP": .5, "C": .5, "L": 3, "KD": 1, "M": 6, "SD": -4}
    bedu = {"V": 4, "S": -2, "MP": 4, "C": -.5, "L": 3, "KD": -.5, "M": 3.5, "SD": -6.5}
    burb = {"V": 3, "S": .5, "MP": 3.5, "C": -4, "L": 1.5, "KD": -.5, "M": .8, "SD": -3}
    nat = {"V": [-1, 0, 1, 1], "S": [4, 2, 0, -1], "MP": [2, 1, -1, 0], "C": [-1, 1, 1, -1],
           "L": [1, 0, -1, -1], "KD": [-1, -1, 1, 0], "M": [3, 1, 0, -1], "SD": [-6, -2, 1, 4]}
    districts, rings = [], {}
    for i in range(n):
        aff = max(-2.6, min(2.6, random.gauss(0, 1)))
        urb = max(-2.6, min(2.6, random.gauss(0, 1)))
        income = round(max(190, min(470, 300 + aff * 55 + random.gauss(0, 12))))
        edu = max(12, min(78, 38 + aff * 6 + urb * 7 + random.gauss(0, 4)))
        foreign = max(3, min(68, 22 - aff * 7 + urb * 5 + random.gauss(0, 5)))
        turnout = max(55, min(96, 84 + aff * 3 + edu * .08 - foreign * .12 + random.gauss(0, 2.5)))
        age = max(28, min(60, 43 - urb * 3 + aff * 1.5 + random.gauss(0, 3)))
        hyra = max(3, min(85, 30 + urb * 10 - aff * 8 + random.gauss(0, 6)))
        rost = round(max(500, min(2600, 1300 + urb * 250 + random.gauss(0, 350))))
        kommun = random.choice(koms)
        kod = f"D{i:04d}"
        namn = f"{kommun} {i % 40 + 1} {random.choice(ort)}"
        el, series = gen_elections(aff, urb, edu, random)
        shares = el["RD"]["shares"]
        # syntetisk geometri: liten fyrkant kring kommun-centrum + jitter
        clon, clat = KOM_CENTER[kommun]
        jx = random.gauss(0, 0.06); jy = random.gauss(0, 0.06)
        cx, cy = clon + jx, clat + jy
        h = 0.012
        rings[kod] = [[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h], [cx - h, cy - h]]
        districts.append({
            "distrikt_kod": kod, "namn": namn, "kommun": kommun, "lan": KOM2LAN[kommun],
            "rost": rost, "income": income, "edu": edu, "foreign": foreign,
            "turnout": turnout, "age": age, "hyra": hyra, "shares": shares, "series": series, "el": el,
        })
    return districts, rings


LAN_NAMN = {
    "01": "Stockholms län", "03": "Uppsala län", "04": "Södermanlands län",
    "05": "Östergötlands län", "06": "Jönköpings län", "07": "Kronobergs län",
    "08": "Kalmar län", "09": "Gotlands län", "10": "Blekinge län",
    "12": "Skåne län", "13": "Hallands län", "14": "Västra Götalands län",
    "17": "Värmlands län", "18": "Örebro län", "19": "Västmanlands län",
    "20": "Dalarnas län", "21": "Gävleborgs län", "22": "Västernorrlands län",
    "23": "Jämtlands län", "24": "Västerbottens län", "25": "Norrbottens län",
}


def synth_geo(rings, kommun_lookup, names=None, seed=42):
    """Förhandsvisning: skapa syntetiska distrikt kopplade till de VERKLIGA
    koderna i geojson-filen (så geometrin matchar), med påhittade röster.
    Kommun/län härleds ur valdistriktskoden (fyra första = kommunkod).
    Distriktsnamn tas från geojson om det finns, annars koden."""
    random.seed(seed)
    names = names or {}
    base = {"V": 7, "S": 26, "MP": 5, "C": 7, "L": 5, "KD": 5, "M": 19, "SD": 20}
    binc = {"V": -1, "S": -4.5, "MP": .5, "C": .5, "L": 3, "KD": 1, "M": 6, "SD": -4}
    bedu = {"V": 4, "S": -2, "MP": 4, "C": -.5, "L": 3, "KD": -.5, "M": 3.5, "SD": -6.5}
    burb = {"V": 3, "S": .5, "MP": 3.5, "C": -4, "L": 1.5, "KD": -.5, "M": .8, "SD": -3}
    nat = {"V": [-1, 0, 1, 1], "S": [4, 2, 0, -1], "MP": [2, 1, -1, 0], "C": [-1, 1, 1, -1],
           "L": [1, 0, -1, -1], "KD": [-1, -1, 1, 0], "M": [3, 1, 0, -1], "SD": [-6, -2, 1, 4]}
    districts = []
    for kod in sorted(rings.keys()):
        kkod = str(kod)[:4].zfill(4)
        lkod = kkod[:2]
        kommun = kommun_lookup.get(kkod, kkod)
        lan = LAN_NAMN.get(lkod, lkod)
        aff = max(-2.6, min(2.6, random.gauss(0, 1)))
        urb = max(-2.6, min(2.6, random.gauss(0, 1)))
        income = round(max(190, min(470, 300 + aff * 55 + random.gauss(0, 12))))
        edu = max(12, min(78, 38 + aff * 6 + urb * 7 + random.gauss(0, 4)))
        foreign = max(3, min(68, 22 - aff * 7 + urb * 5 + random.gauss(0, 5)))
        turnout = max(55, min(96, 84 + aff * 3 + edu * .08 - foreign * .12 + random.gauss(0, 2.5)))
        age = max(28, min(60, 43 - urb * 3 + aff * 1.5 + random.gauss(0, 3)))
        hyra = max(3, min(85, 30 + urb * 10 - aff * 8 + random.gauss(0, 6)))
        rost = round(max(500, min(2600, 1300 + urb * 250 + random.gauss(0, 350))))
        el, series = gen_elections(aff, urb, edu, random)
        shares = el["RD"]["shares"]
        districts.append({
            "distrikt_kod": kod, "namn": names.get(kod, kod), "kommun": kommun, "lan": lan,
            "rost": rost, "income": income, "edu": edu, "foreign": foreign,
            "turnout": turnout, "age": age, "hyra": hyra, "shares": shares, "series": series, "el": el,
        })
    return districts


def _load_shares_csv(path):
    """Läs en distrikt-CSV (partikolumner = röster) -> {distrikt_kod: {pid: andel}}."""
    out = {}
    for r in read_csv(path):
        votes = {pid: (to_float(r.get(pid)) or 0.0) for pid in PIDS}
        giltiga = to_float(r.get("giltiga"))
        tot = giltiga if (giltiga and giltiga > 0) else sum(votes.values())
        kod = (r.get("distrikt_kod") or "").strip()
        if tot and kod:
            out[kod] = {pid: votes[pid] / tot * 100.0 for pid in PIDS}
    return out


def attach_elections_real(districts, primary_val, rf_path, kf_path):
    """Bygg d['el'] för riktig data: primärvalet + ev. region/kommunval.
    Varje el[val] får en tom historik-serie (fylls sedan av apply_history)."""
    def blank_series(cur):
        s = {p: [None] * len(ELYEARS) for p in PIDS}
        for p in PIDS:
            s[p][ELYEARS.index(CURRENT_YEAR)] = cur[p]
        return s
    for d in districts:
        sh = d["shares"]
        d["el"] = {primary_val: {"shares": sh, "changes": {p: 0.0 for p in PIDS},
                                 "top": max(PIDS, key=lambda p: sh[p]), "series": blank_series(sh),
                                 "w": [None] * len(ELYEARS)}}
        d["series"] = d["el"][primary_val]["series"]   # aktiv serie = primärvalets
    for val, path in [("RF", rf_path), ("KF", kf_path)]:
        if path and Path(path).exists():
            shares = _load_shares_csv(path)
            for d in districts:
                s = shares.get(d["distrikt_kod"])
                if s:
                    d["el"][val] = {"shares": s, "changes": {p: 0.0 for p in PIDS},
                                    "top": max(PIDS, key=lambda p: s[p]), "series": blank_series(s),
                                    "w": [None] * len(ELYEARS)}


def apply_covariates(districts, cov_path):
    """Lägg riktiga SCB-kovariater på förhandsvisningens distrikt (matchar på kod)."""
    if not cov_path or not Path(cov_path).exists():
        return 0
    by = {d["distrikt_kod"]: d for d in districts}
    n = 0
    for r in read_csv(cov_path):
        d = by.get((r.get("distrikt_kod") or "").strip())
        if not d:
            continue
        for k in COV_KEYS:
            v = to_float(r.get(k))
            if v is not None:
                d[k] = v
        n += 1
    return n


def apply_history(districts, hist_path):
    """Lägg in riktig historik på distrikten där koden matchar. Stödjer val-kolumn
    (RD/RF/KF); saknas den antas RD. Skriver in i el[val]['series'] och även d['series']
    för RD (aktiv default). 2026 (sista året) behålls."""
    by = {d["distrikt_kod"]: d for d in districts}
    hit = set()
    for r in read_csv(hist_path):
        d = by.get((r.get("distrikt_kod") or "").strip())
        if not d:
            continue
        yr = to_float(r.get("year"))
        val = (r.get("val") or "RD").strip().upper()
        pid = (r.get("party") or "").strip()
        sh = to_float(r.get("share"))
        wt = to_float(r.get("roster"))
        if yr is None or pid not in PIDS or sh is None or int(yr) not in ELYEARS:
            continue
        t = ELYEARS.index(int(yr))
        el = d.get("el") or {}
        if val in el and el[val].get("series"):
            el[val]["series"][pid][t] = sh
            if wt is not None and el[val].get("w") is not None:
                el[val]["w"][t] = wt
            hit.add(d["distrikt_kod"])
    return len(hit)


def load_valkrets(path):
    """kommunkod -> valkretskod, och valkretskod -> {namn, fasta} (riksdag)."""
    kom2vk, vk = {}, {}
    if not path or not Path(path).exists():
        return kom2vk, vk
    for r in read_csv(path):
        kk = (r.get("kommunkod") or "").strip()
        vkk = (r.get("valkretskod") or "").strip()
        namn = (r.get("valkretsnamn") or "").strip()
        fasta = to_float(r.get("fasta"))
        if kk and vkk:
            kom2vk[kk] = vkk
            if vkk not in vk:
                vk[vkk] = {"namn": namn, "fasta": int(fasta) if fasta else 0}
    return kom2vk, vk


def load_areas(path):
    """Läs omraden.csv -> {niva:{kod:{val:{year:{pid:share}}}}} (exakta områdestotaler)."""
    out = {}
    if not path or not Path(path).exists():
        return out
    for r in read_csv(path):
        niva = (r.get("niva") or "").strip()
        kod = (r.get("kod") or "").strip()
        val = (r.get("val") or "").strip().upper()
        yr = to_float(r.get("year"))
        pid = (r.get("party") or "").strip()
        sh = to_float(r.get("share"))
        if not niva or yr is None or pid not in PIDS or sh is None:
            continue
        out.setdefault(niva, {}).setdefault(kod, {}).setdefault(val, {}).setdefault(int(yr), {})[pid] = sh
    return out


def load_kommun_lookup(path):
    out = {}
    if path and Path(path).exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                kod = (r.get("kommun_kod") or r.get("kommunkod") or "").strip()
                namn = (r.get("kommun_namn") or r.get("kommun") or "").strip()
                if kod and namn:
                    out[kod] = namn
    return out
def compute_changes_and_top(districts):
    ci, pi = ELYEARS.index(CURRENT_YEAR), ELYEARS.index(PREV_YEAR)
    for d in districts:
        ch = {}
        for pid in PIDS:
            cur, prev = d["series"][pid][ci], d["series"][pid][pi]
            ch[pid] = (cur - prev) if (cur is not None and prev is not None) else 0.0
        d["changes"] = ch
        d["top"] = max(PIDS, key=lambda p: d["shares"][p])


def zstats(districts, keys):
    stats = {}
    for k in keys:
        vals = [d[k] for d in districts if d.get(k) is not None]
        if not vals:
            stats[k] = {"mean": 0.0, "sd": 1.0}
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[k] = {"mean": mean, "sd": math.sqrt(var) or 1.0}
    return stats


def solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        d = M[col][col] or 1e-9
        for r in range(n):
            if r == col:
                continue
            f = M[r][col] / d
            for k in range(col, n + 1):
                M[r][k] -= f * M[col][k]
    return [M[i][n] / (M[i][i] or 1e-9) for i in range(n)]


def compute_residuals(districts, zst):
    preds = MODEL_PREDICTORS
    usable = [d for d in districts if all(d.get(k) is not None for k in preds)]
    for d in districts:
        d["pred"], d["resid"] = {}, {}
    if len(usable) <= len(preds) + 1:
        return

    def zrow(d):
        return [1.0] + [(d[k] - zst[k]["mean"]) / (zst[k]["sd"] or 1.0) for k in preds]

    X = [zrow(d) for d in usable]
    k = len(preds) + 1
    for pid in PIDS:
        y = [d["shares"][pid] for d in usable]
        XtX = [[0.0] * k for _ in range(k)]
        Xty = [0.0] * k
        for r in range(len(X)):
            for a in range(k):
                Xty[a] += X[r][a] * y[r]
                for c in range(k):
                    XtX[a][c] += X[r][a] * X[r][c]
        beta = solve(XtX, Xty)
        for d, xr in zip(usable, X):
            p = sum(xr[a] * beta[a] for a in range(k))
            d["pred"][pid] = p
            d["resid"][pid] = d["shares"][pid] - p


# ============================================================
#  DATA-objekt + skriv HTML
# ============================================================
def round_opt(v, nd=2):
    return None if v is None else round(v, nd)


def build_data(districts, meta, geo_w, geo_h, has_geo):
    zst = zstats(districts, COV_KEYS)
    compute_changes_and_top(districts)
    compute_residuals(districts, zst)

    lan_order = []
    for d in districts:
        if d["lan"] and d["lan"] not in lan_order:
            lan_order.append(d["lan"])

    cov = {k: {"lab": COV_META[k]["lab"], "unit": COV_META[k]["unit"],
               "mean": round(zst[k]["mean"], 4), "sd": round(zst[k]["sd"], 4)} for k in COV_KEYS}

    out = []
    for i, d in enumerate(districts):
        rec = {
            "i": i, "namn": d["namn"], "kommun": d["kommun"], "lan": d["lan"],
            "rost": d.get("rost", 0), "top": d["top"], "raknat": int(d.get("raknat", 1)), "vk": d.get("vk"),
            "shares": {p: round(d["shares"][p], 2) for p in PIDS},
            "changes": {p: round(d["changes"][p], 2) for p in PIDS},
            "series": {p: [round_opt(v, 2) for v in d["series"][p]] for p in PIDS},
        }
        for k in COV_KEYS:
            rec[k] = round_opt(d.get(k), 2)
        if d.get("el"):
            rec["el"] = {}
            ci = ELYEARS.index(CURRENT_YEAR)
            for val, e in d["el"].items():
                if e.get("w") is not None and e["w"][ci] is None:
                    e["w"][ci] = d.get("rost", 0)
                rec["el"][val] = {
                    "shares": {p: round(e["shares"][p], 2) for p in PIDS},
                    "changes": {p: round(e["changes"][p], 2) for p in PIDS},
                    "top": e["top"],
                }
                if e.get("series"):
                    rec["el"][val]["series"] = {p: [round_opt(v, 2) for v in e["series"][p]] for p in PIDS}
                if e.get("w"):
                    rec["el"][val]["w"] = [None if v is None else int(round(v)) for v in e["w"]]
        if d.get("poly"):
            rec["poly"] = [[round(x, 1), round(y, 1)] for x, y in d["poly"]]
        if d.get("dor"):
            rec["dor"] = d["dor"]
        out.append(rec)

    meta = dict(meta)
    meta["hasGeo"] = bool(has_geo)
    return {
        "parties": PARTIES, "covKeys": COV_KEYS, "cov": cov, "elyears": ELYEARS,
        "vals": [v for v in VALS if any(v in (d.get("el") or {}) for d in districts)],
        "valNamn": VAL_NAMN,
        "lanOrder": lan_order, "meta": meta,
        "geoW": round(geo_w, 1), "geoH": round(geo_h, 1),
        "districts": out,
    }


def render_site(data, template_path, out_path):
    tpl = Path(template_path).read_text(encoding="utf-8")
    marker = "/*__DATA__*/"
    if marker not in tpl:
        sys.exit(f"Hittar inte injektionsmarkören {marker} i {template_path}")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace(marker, blob)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html, encoding="utf-8")
    return len(html), len(data["districts"])


# ============================================================
#  Exempel-filer
# ============================================================
def emit_sample(dirpath):
    d, rings = synth()
    p = Path(dirpath); p.mkdir(parents=True, exist_ok=True)
    with open(p / "distrikt.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["distrikt_kod", "distrikt_namn", "kommun_kod", "kommun_namn", "lan_namn", "rost_berattigade"] + PIDS)
        for x in d:
            votes = [round(x["shares"][pid] / 100.0 * x["rost"] * 0.82) for pid in PIDS]
            w.writerow([x["distrikt_kod"], x["namn"], "", x["kommun"], x["lan"], x["rost"]] + votes)
    with open(p / "scb.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["distrikt_kod"] + COV_KEYS)
        for x in d:
            w.writerow([x["distrikt_kod"]] + [round(x[k], 1) for k in COV_KEYS])
    with open(p / "historik.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["distrikt_kod", "year", "party", "share"])
        for x in d:
            for yi, yr in enumerate(ELYEARS):
                if yr == CURRENT_YEAR:
                    continue
                for pid in PIDS:
                    w.writerow([x["distrikt_kod"], yr, pid, round(x["series"][pid][yi], 2)])
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"distrikt_kod": x["distrikt_kod"], "distrikt_namn": x["namn"]},
         "geometry": {"type": "Polygon", "coordinates": [rings[x["distrikt_kod"]]]}} for x in d]}
    (p / "valdistrikt.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"Skrev exempel till {p}/ (distrikt.csv, scb.csv, historik.csv, valdistrikt.geojson)")


# ============================================================
#  main
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="Bygg valdistrikts-HTML från CSV + GeoJSON.")
    ap.add_argument("--districts")
    ap.add_argument("--rf", help="Distrikt-CSV för regionval (RF), samma schema")
    ap.add_argument("--kf", help="Distrikt-CSV för kommunval (KF), samma schema")
    ap.add_argument("--primary-val", default="RD", choices=["RD", "RF", "KF"],
                    help="Vilket val --districts innehåller (default RD)")
    ap.add_argument("--covariates")
    ap.add_argument("--history")
    ap.add_argument("--areas", default="data/omraden.csv", help="Exakta områdestotaler (omraden.csv från historik.py)")
    ap.add_argument("--geojson")
    ap.add_argument("--geo-code-prop", default=None, help="GeoJSON-property som matchar distrikt_kod")
    ap.add_argument("--geo-max-points", type=int, default=80, help="Max punkter per polygon (tak; Douglas–Peucker används)")
    ap.add_argument("--kommuner", default="data/kommuner.csv", help="CSV kommun_kod,kommun_namn (för förhandsvisning)")
    ap.add_argument("--mandat", default="data/mandat.csv", help="CSV niva,kod,antal med mandat per kommun/region (valfri)")
    ap.add_argument("--valkrets", default="data/valkrets.csv", help="CSV kommunkod,valkretskod,valkretsnamn,fasta (riksdag)")
    ap.add_argument("--template", default=str(Path(__file__).with_name("template.html")))
    ap.add_argument("--out", default="dist/valdistrikt.html")
    ap.add_argument("--title", default="Valutfall")
    ap.add_argument("--source-label", default=None)
    ap.add_argument("--status", default="")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--emit-sample", metavar="DIR")
    args = ap.parse_args()

    if args.emit_sample:
        emit_sample(args.emit_sample)
        return

    rings, geojson_path = {}, args.geojson
    if args.districts:
        districts = load_real(args.districts, args.covariates, None)
        attach_elections_real(districts, args.primary_val, args.rf, args.kf)
        if args.history and Path(args.history).exists():
            m = apply_history(districts, args.history)
            print(f"Historik: {m} distrikt fick riktig historik.", file=sys.stderr)
        source = args.source_label or "Källa: Valmyndigheten (röstfördelning) + SCB (kovariater)"
        if geojson_path:
            codes = {d["distrikt_kod"] for d in districts}
            rings, used, _names = load_geojson(geojson_path, args.geo_code_prop, codes)
            print(f"GeoJSON: {len(rings)} distriktpolygoner (kodfält '{used}').", file=sys.stderr)
    elif geojson_path and Path(geojson_path).exists():
        # FÖRHANDSVISNING: riktig geometri + syntetiska röster, kopplade till de riktiga koderna
        rings, used, names = load_geojson(geojson_path, args.geo_code_prop, None)
        districts = synth_geo(rings, load_kommun_lookup(args.kommuner), names)
        if args.covariates and Path(args.covariates).exists():
            mc = apply_covariates(districts, args.covariates)
            print(f"SCB-kovariater: {mc} distrikt fick riktiga värden.", file=sys.stderr)
        if args.history and Path(args.history).exists():
            m = apply_history(districts, args.history)
            print(f"Historik: {m} distrikt fick riktig 2014–2022-historik.", file=sys.stderr)
        source = args.source_label or "SYNTETISKA RÖSTER på verklig geometri – siffrorna är påhittade"
        print(f"GeoJSON: {len(rings)} distriktpolygoner (kodfält '{used}'). Förhandsvisning med syntetiska röster.", file=sys.stderr)
    else:
        districts, rings = synth()
        source = args.source_label or "SYNTETISKT EXEMPELDATA – siffrorna och geometrin är påhittade"
        print("Ingen --districts angiven: bygger med syntetiskt exempeldata (med geometri).", file=sys.stderr)

    geo_w, geo_h, has_geo = attach_geometry(districts, rings, args.geo_max_points)
    if geojson_path and not has_geo:
        print("VARNING: inga GeoJSON-koder matchade distrikt_kod – kontrollera --geo-code-prop.", file=sys.stderr)

    meta = {"title": args.title, "source_label": source, "status": args.status, "live": bool(args.live)}
    # riksdagens valkretsar: koppla varje distrikt till sin valkrets före bygget
    KOM2VK, RIKSVK = load_valkrets(args.valkrets)
    for d in districts:
        kk = (d.get("distrikt_kod") or "")[:4]
        if kk in KOM2VK:
            d["vk"] = KOM2VK[kk]
    data = build_data(districts, meta, geo_w, geo_h, has_geo)
    # exakta områdestotaler + namn->kod-uppslag
    data["areaHist"] = load_areas(args.areas)
    kl = load_kommun_lookup(args.kommuner)
    data["komKod"] = {namn: kod for kod, namn in kl.items()}
    data["lanKod"] = {namn: kod for kod, namn in LAN_NAMN.items()}
    # mandat: riksdag 349 känt; kommun/region ur valfri data/mandat.csv (niva,kod,antal)
    seats = {"riket": 349, "kommun": {}, "lan": {}}
    valkretsar = {}   # kommunkod -> antal valkretsar (för 2%/3%-spärr i KF)
    if args.mandat and Path(args.mandat).exists():
        for r in read_csv(args.mandat):
            niva = (r.get("niva") or "").strip().lower()
            kod = (r.get("kod") or "").strip()
            antal = to_float(r.get("antal"))
            vk = to_float(r.get("valkretsar"))
            if niva in ("kommun", "lan") and kod and antal:
                seats[niva][kod] = int(antal)
            if niva == "kommun" and kod and vk:
                valkretsar[kod] = int(vk)
    data["seats"] = seats
    data["valkretsar"] = valkretsar
    data["thresholds"] = {"RD": 4.0, "RF": 3.0, "KF": 2.0}   # KF: 2% (1 valkrets) / 3% (fler) väljs i klienten
    data["riksvalkretsar"] = RIKSVK
    size, n = render_site(data, args.template, args.out)
    print(f"Byggde {args.out}  ·  {n} distrikt  ·  geo={'ja' if has_geo else 'nej'}  ·  {size:,} tecken".replace(",", " "))


if __name__ == "__main__":
    main()
