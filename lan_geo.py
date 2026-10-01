#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lan_geo.py — byter ut länspolygonerna i data/granser.json mot rena län med riktig kustlinje.

Bakgrund: granser.py bygger länen ur SCB:s RegSO-polygoner, som sträcker sig ut i havet
(territorialvatten). Kusten blir därför rak och skärgård/öar försvinner. Det här skriptet
hämtar i stället Natural Earth 10m "admin 1" (public domain), filtrerar ut Sveriges 21 län,
projicerar till SWEREF99 TM (EPSG:3006, samma referenssystem som valdistriktsgeometrin och
granser.json) och skriver över nyckeln "lan" i data/granser.json. Kommunpolygonerna rörs inte.
build.py projicerar sedan allt till kartans koordinater som vanligt.

    python3 lan_geo.py                         # hämtar från GitHub (nvkelso/natural-earth-vector)
    python3 lan_geo.py --src ne_10m_admin_1_states_provinces.geojson
    python3 lan_geo.py --granser data/granser.json --dry-run

Endast standardbibliotek.
Källa: Natural Earth, ne_10m_admin_1_states_provinces (naturalearthdata.com, public domain).
"""
import argparse, json, math, urllib.request
from pathlib import Path

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
          "ne_10m_admin_1_states_provinces.geojson")
# ISO 3166-2:SE -> länskod (SCB)
ISO2KOD = {'AB': '01', 'C': '03', 'D': '04', 'E': '05', 'F': '06', 'G': '07', 'H': '08', 'I': '09',
           'K': '10', 'M': '12', 'N': '13', 'O': '14', 'S': '17', 'T': '18', 'U': '19', 'W': '20',
           'X': '21', 'Y': '22', 'Z': '23', 'AC': '24', 'BD': '25'}

# ---- SWEREF99 TM (GRS80, lon0=15, k0=0.9996, FE=500000) – Krügers serieutveckling (mm-noggrannhet) ----
_a = 6378137.0; _f = 1/298.257222101; _k0 = 0.9996; _lon0 = math.radians(15.0); _FE = 500000.0
_n = _f/(2-_f); _n2, _n3, _n4 = _n**2, _n**3, _n**4
_A = _a/(1+_n)*(1+_n2/4+_n4/64)
_alpha = (_n/2 - 2*_n2/3 + 5*_n3/16, 13*_n2/48 - 3*_n3/5, 61*_n3/240)
_e = math.sqrt(_f*(2-_f))

def sweref99tm(lon, lat):
    phi = math.radians(lat); lam = math.radians(lon) - _lon0
    t = math.sinh(math.atanh(math.sin(phi)) - _e*math.atanh(_e*math.sin(phi)))
    xi = math.atan2(t, math.cos(lam)); eta = math.atanh(math.sin(lam)/math.sqrt(1+t*t))
    x = eta; y = xi
    for j, a in enumerate(_alpha, start=1):
        x += a*math.cos(2*j*xi)*math.sinh(2*j*eta); y += a*math.sin(2*j*xi)*math.cosh(2*j*eta)
    return _FE + _k0*_A*x, _k0*_A*y

def ring_area(r):
    return abs(sum(r[i][0]*r[(i+1) % len(r)][1] - r[(i+1) % len(r)][0]*r[i][1] for i in range(len(r))))/2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', help='Lokal Natural Earth-geojson (annars hämtas den)')
    ap.add_argument('--granser', default='data/granser.json')
    ap.add_argument('--min-km2', type=float, default=0.5, help='Släng öar mindre än så (km²)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.src:
        gj = json.loads(Path(a.src).read_text(encoding='utf-8'))
    else:
        print('Hämtar Natural Earth 10m admin-1 …')
        with urllib.request.urlopen(NE_URL, timeout=300) as r: gj = json.loads(r.read().decode('utf-8'))
    lan = {}
    for f in gj['features']:
        p = f['properties']
        if p.get('iso_a2') != 'SE' and p.get('adm0_a3') != 'SWE': continue
        iso = (p.get('iso_3166_2') or '').split('-')[-1]
        kod = ISO2KOD.get(iso)
        if not kod: print('Okänt län:', p.get('name'), iso); continue
        geom = f['geometry']; polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        rings = []
        for poly in polys:
            outer = [[round(x, 1), round(y, 1)] for x, y in (sweref99tm(lon, lat) for lon, lat in poly[0])]
            if ring_area(outer) < a.min_km2*1e6: continue
            rings.append(outer)                      # hål (sjöar) ignoreras – fylls som land
        lan[kod] = rings
    print(f'{len(lan)} län, {sum(len(r) for r in lan.values())} ringar, '
          f'{sum(len(x) for r in lan.values() for x in r)} punkter')
    gp = Path(a.granser)
    g = json.loads(gp.read_text(encoding='utf-8')) if gp.exists() else {}
    g['lan'] = lan
    g.pop('meta', None)   # build.py tolkar varje toppnyckel som en kartnivå – inga metadata här
    if a.dry_run: print('dry-run: skriver inte'); return
    gp.write_text(json.dumps(g, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('Skrev', gp)

if __name__ == '__main__':
    main()
