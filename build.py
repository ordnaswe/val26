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
        total = sum(votes.values())
        shares = {pid: (votes[pid] / total * 100.0 if total else 0.0) for pid in PIDS}
        d = {
            "distrikt_kod": (r.get("distrikt_kod") or "").strip(),
            "namn": (r.get("distrikt_namn") or "").strip(),
            "kommun": (r.get("kommun_namn") or "").strip(),
            "lan": (r.get("lan_namn") or "").strip(),
            "rost": int(to_float(r.get("rost_berattigade")) or 0),
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


def load_geojson(path, code_prop):
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    feats = gj.get("features", [])
    props0 = feats[0]["properties"] if feats else {}
    if not code_prop:
        code_prop = next((c for c in GEO_CODE_PROP_CANDIDATES if c in props0), None)
    if not code_prop:
        sys.exit("Kunde inte gissa GeoJSON-kodfält. Ange --geo-code-prop. "
                 f"Tillgängliga properties: {', '.join(props0.keys())}")
    rings = {}
    for ft in feats:
        code = str(ft.get("properties", {}).get(code_prop, "")).strip()
        ring = _outer_ring(ft.get("geometry") or {})
        if code and ring:
            rings[code] = [[float(p[0]), float(p[1])] for p in ring]
    return rings, code_prop


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


def simplify_ring(ring, max_points):
    """Enkel likformig gallring till max_points (behåller form, billigt)."""
    n = len(ring)
    if n <= max_points:
        return ring
    step = n / max_points
    return [ring[int(i * step)] for i in range(max_points)]


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
        raw = {p: base[p] + binc[p] * aff + bedu[p] * ((edu - 40) / 12) + burb[p] * urb for p in PIDS}
        series = {p: [max(.3, min(62, raw[p] + nat[p][t] + random.gauss(0, 1.5))) for t in range(len(ELYEARS))] for p in PIDS}
        for t in range(len(ELYEARS)):
            s = sum(series[p][t] for p in PIDS)
            for p in PIDS:
                series[p][t] = series[p][t] / s * 100.0
        shares = {p: series[p][ELYEARS.index(CURRENT_YEAR)] for p in PIDS}
        # syntetisk geometri: liten fyrkant kring kommun-centrum + jitter
        clon, clat = KOM_CENTER[kommun]
        jx = random.gauss(0, 0.06); jy = random.gauss(0, 0.06)
        cx, cy = clon + jx, clat + jy
        h = 0.012
        rings[kod] = [[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h], [cx - h, cy - h]]
        districts.append({
            "distrikt_kod": kod, "namn": namn, "kommun": kommun, "lan": KOM2LAN[kommun],
            "rost": rost, "income": income, "edu": edu, "foreign": foreign,
            "turnout": turnout, "age": age, "hyra": hyra, "shares": shares, "series": series,
        })
    return districts, rings


# ============================================================
#  Beräkningar
# ============================================================
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
            "rost": d.get("rost", 0), "top": d["top"],
            "shares": {p: round(d["shares"][p], 2) for p in PIDS},
            "changes": {p: round(d["changes"][p], 2) for p in PIDS},
            "series": {p: [round_opt(v, 2) for v in d["series"][p]] for p in PIDS},
        }
        for k in COV_KEYS:
            rec[k] = round_opt(d.get(k), 2)
        if d.get("pred"):
            rec["pred"] = {p: round_opt(d["pred"].get(p), 2) for p in PIDS}
            rec["resid"] = {p: round_opt(d["resid"].get(p), 2) for p in PIDS}
        if d.get("poly"):
            rec["poly"] = [[round(x, 1), round(y, 1)] for x, y in d["poly"]]
        if d.get("dor"):
            rec["dor"] = d["dor"]
        out.append(rec)

    meta = dict(meta)
    meta["hasGeo"] = bool(has_geo)
    return {
        "parties": PARTIES, "covKeys": COV_KEYS, "cov": cov, "elyears": ELYEARS,
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
    ap.add_argument("--covariates")
    ap.add_argument("--history")
    ap.add_argument("--geojson")
    ap.add_argument("--geo-code-prop", default=None, help="GeoJSON-property som matchar distrikt_kod")
    ap.add_argument("--geo-max-points", type=int, default=40, help="Max punkter per polygon (förenkling)")
    ap.add_argument("--template", default=str(Path(__file__).with_name("template.html")))
    ap.add_argument("--out", default="dist/valdistrikt.html")
    ap.add_argument("--title", default="Valdistrikt – analysvyer")
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
        districts = load_real(args.districts, args.covariates, args.history)
        source = args.source_label or "Källa: Valmyndigheten (röstfördelning) + SCB (kovariater)"
        if geojson_path:
            rings, used = load_geojson(geojson_path, args.geo_code_prop)
            print(f"GeoJSON: {len(rings)} distriktpolygoner (kodfält '{used}').", file=sys.stderr)
    else:
        districts, rings = synth()
        source = args.source_label or "SYNTETISKT EXEMPELDATA – siffrorna och geometrin är påhittade"
        print("Ingen --districts angiven: bygger med syntetiskt exempeldata (med geometri).", file=sys.stderr)

    geo_w, geo_h, has_geo = attach_geometry(districts, rings, args.geo_max_points)
    if geojson_path and not has_geo:
        print("VARNING: inga GeoJSON-koder matchade distrikt_kod – kontrollera --geo-code-prop.", file=sys.stderr)

    meta = {"title": args.title, "source_label": source, "status": args.status, "live": bool(args.live)}
    data = build_data(districts, meta, geo_w, geo_h, has_geo)
    size, n = render_site(data, args.template, args.out)
    print(f"Byggde {args.out}  ·  {n} distrikt  ·  geo={'ja' if has_geo else 'nej'}  ·  {size:,} tecken".replace(",", " "))


if __name__ == "__main__":
    main()
