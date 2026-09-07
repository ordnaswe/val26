#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
historik.py — bygg data/historik.csv från Valmyndighetens historiska
per-valdistrikt-filer (2014/2018/2022), per valnivå (RD/RF/KF).

Klarar de format vi sett:
- 2022: långt format (Parti/Röster-kolumner), 8-siffrig Valdistriktskod.
- 2018: brett format, kod uppdelad i LÄNSKOD/KOMMUNKOD/VALDISTRIKTSKOD.
- 2014: brett format med titel-/tomrader överst, "M tal"/"M proc"-kolumner,
  och DUBBLETTER av rubriker (LÄN/KOM/VALDISTRIKT som både kod och namn).
Läser positionellt och väljer de kolumner som innehåller SIFFROR (koderna),
inte namnen. Sätter ihop 8-siffrig kod (län2+kommun2+distrikt4) när koden är
uppdelad. FP tolkas som L.

ANVÄNDNING
    python3 historik.py --inspect FIL
    python3 historik.py --src 2014 RD fil.csv --src 2018 RF fil.csv ... -o data/historik.csv
    python3 historik.py --year 2014 fil.csv   # genväg för RD

--src ÅR NIVÅ FIL   (NIVÅ = RD riksdag / RF region-landsting / KF kommun)
--remap ÅR FIL      (omkodning gammalt kod -> 2026 kod; valfri, för omritade distrikt)

Endast Python-standardbibliotek.
"""

import argparse
import csv
import io
import sys
from pathlib import Path

PIDS = ["V", "S", "MP", "C", "L", "KD", "M", "SD"]

PARTY_ALIAS = {
    "v": "V", "vänsterpartiet": "V", "vansterpartiet": "V",
    "s": "S", "arbetarepartiet-socialdemokraterna": "S", "arbetarepartiet socialdemokraterna": "S", "socialdemokraterna": "S",
    "mp": "MP", "miljöpartiet de gröna": "MP", "miljopartiet de grona": "MP", "miljöpartiet": "MP",
    "c": "C", "centerpartiet": "C",
    "l": "L", "fp": "L", "liberalerna": "L", "folkpartiet": "L", "folkpartiet liberalerna": "L",
    "liberalerna (tidigare folkpartiet)": "L",
    "kd": "KD", "kristdemokraterna": "KD",
    "m": "M", "moderaterna": "M",
    "sd": "SD", "sverigedemokraterna": "SD",
}


def norm(s):
    return (s or "").strip().lower()


def to_num(v):
    if v is None:
        return None
    v = str(v).strip().replace("\xa0", "").replace(" ", "").replace("%", "").replace(",", ".")
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def party_of(header):
    """Partikod ur en rubrik: 'M', 'M tal', 'FP tal'. 'M proc' -> None (vi tar antal)."""
    n = norm(header)
    if not n:
        return None
    if n.endswith(("proc", "procent", "%", "andel")):
        return None
    for suf in (" tal", " antal", "tal", "antal"):
        if n.endswith(suf):
            n = n[:-len(suf)].strip()
            break
    return PARTY_ALIAS.get(n)


def sniff_delim(line):
    return max((";", ",", "\t"), key=lambda d: line.count(d))


def _looks_like_header(fields):
    low = [norm(f) for f in fields]
    joined = " ".join(low)
    has_code = ("valdist" in joined) or (("län" in joined or "lan" in joined) and "kom" in joined)
    has_party = any(party_of(f) for f in fields) or ("parti" in low and any(t in low for t in ("röster", "roster", "antal")))
    return has_code and has_party


def read_rows(path):
    """Returnerar (headers, rows) där rader är listor av strängar. Hittar den
    riktiga rubrikraden (kan ligga efter titel-/tomrader)."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()
    probe = max(lines[:40], key=lambda l: max(l.count(";"), l.count(","), l.count("\t")), default="")
    delim = sniff_delim(probe)
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    hidx = 0
    for i, fields in enumerate(reader[:40]):
        if _looks_like_header(fields):
            hidx = i
            break
    headers = [h.strip() for h in reader[hidx]]
    rows = [r for r in reader[hidx + 1:] if any(c.strip() for c in r)]
    return headers, rows


def _val_at(row, i):
    return row[i].strip() if (i is not None and i < len(row)) else ""


def resolve_code(headers, sample):
    """Returnerar en funktion rad->8-siffrig kod. Väljer sifferkolumner (koder),
    inte namnkolumner, och sätter ihop län2+kommun2+distrikt4 vid behov."""
    def idxs(*names):
        return [i for i, h in enumerate(headers) if norm(h) in names]
    def is_num(i):
        v = _val_at(sample, i).replace(" ", "")
        return v.isdigit()

    # 1) komplett kod (≥7 siffror) i en kolumn?
    for i in idxs("valdistriktskod", "vdkod", "valdist", "valdistrikt"):
        v = _val_at(sample, i).replace(" ", "")
        if v.isdigit() and len(v) >= 7:
            return (lambda r, i=i: _val_at(r, i).replace(" ", "")), "full"
    # 2) sätt ihop från sifferkolumner
    lan = next((i for i in idxs("länskod", "lanskod", "lan", "län") if is_num(i)), None)
    kom = next((i for i in idxs("kommunkod", "kom") if is_num(i)), None)
    vd = next((i for i in idxs("valdistriktskod", "valdist", "valdistrikt", "vd") if is_num(i)), None)
    if lan is not None and kom is not None and vd is not None:
        return (lambda r, a=lan, b=kom, c=vd:
                _val_at(r, a).zfill(2) + _val_at(r, b).zfill(2) + _val_at(r, c).zfill(4)), "compose"
    # 3) enstaka sifferkod-kolumn
    single = next((i for i in range(len(headers))
                   if ("kod" in norm(headers[i]) or norm(headers[i]) in ("valdist", "valdistrikt")) and is_num(i)), None)
    if single is not None:
        return (lambda r, i=single: _val_at(r, i).replace(" ", "")), "single"
    return None, None


def find_long(headers):
    parti = next((i for i, h in enumerate(headers) if norm(h) in ("parti", "party", "partinamn")), None)
    roster = next((i for i, h in enumerate(headers) if norm(h) in ("röster", "roster", "antal", "antal röster")), None)
    return parti, roster


def find_party_idx(headers):
    out = {}
    for i, h in enumerate(headers):
        pid = party_of(h)
        if pid and pid not in out.values():
            out[i] = pid
    return out


def _valid_col(headers):
    for i, h in enumerate(headers):
        n = norm(h)
        if "giltig" in n and "ogilt" not in n:
            return i
    return None


def load_shares(path):
    headers, rows = read_rows(path)
    if not headers or not rows:
        return {}
    code_fn, kind = resolve_code(headers, rows[0])
    if not code_fn:
        sys.exit(f"Hittade ingen sifferkod för valdistrikt i {path}. Kör --inspect.")
    parti_i, roster_i = find_long(headers)
    acc, valid = {}, {}
    if parti_i is not None and roster_i is not None:
        for r in rows:
            kod = code_fn(r)
            if not kod:
                continue
            pn = norm(_val_at(r, parti_i))
            if "giltiga" in pn and "ogilt" not in pn and "blank" not in pn:
                valid[kod] = to_num(_val_at(r, roster_i)) or 0.0   # "Summa giltiga röster"
                continue
            pid = PARTY_ALIAS.get(pn)
            if pid:
                acc.setdefault(kod, {p: 0.0 for p in PIDS})[pid] += (to_num(_val_at(r, roster_i)) or 0.0)
    else:
        pidx = find_party_idx(headers)
        if not pidx:
            sys.exit(f"Hittade inga partikolumner i {path}. Kör --inspect.")
        gi = _valid_col(headers)
        for r in rows:
            kod = code_fn(r)
            if not kod:
                continue
            d = acc.setdefault(kod, {p: 0.0 for p in PIDS})
            for i, pid in pidx.items():
                d[pid] += (to_num(_val_at(r, i)) or 0.0)
            if gi is not None:
                valid[kod] = to_num(_val_at(r, gi)) or 0.0
    out = {}
    for kod, votes in acc.items():
        # nämnare = alla giltiga röster (inkl småpartier). Faller tillbaka på de 8 om kolumn saknas.
        tv = valid.get(kod) or sum(votes.values())
        if tv > 0:
            out[kod] = {"shares": {p: votes[p] / tv * 100.0 for p in PIDS}, "w": tv}
    return out


def load_remap(path):
    headers, rows = read_rows_simple(path)
    m = {}
    if not rows:
        return m
    low = {norm(h): i for i, h in enumerate(headers)}
    oc = next((low[k] for k in low if "old" in k or "2018" in k or "gammal" in k or "från" in k), 0)
    nc = next((low[k] for k in low if "new" in k or "2022" in k or "2026" in k or "motsvar" in k or "till" in k), 1 if len(headers) > 1 else 0)
    wc = next((low[k] for k in low if "vikt" in k or "procent" in k or "mappning" in k), None)
    for r in rows:
        o = _val_at(r, oc); n = _val_at(r, nc)
        w = (to_num(_val_at(r, wc)) if wc is not None else None) or 100.0
        if o and n:
            m.setdefault(o, []).append((n, w / 100.0))
    return m


def read_rows_simple(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    delim = sniff_delim(text.splitlines()[0] if text else "")
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    return ([h.strip() for h in reader[0]], reader[1:]) if reader else ([], [])


def apply_remap(data, remap):
    if not remap:
        return data
    acc = {}
    for old, rec in data.items():
        for new, frac in remap.get(old, []):
            a = acc.setdefault(new, {"sv": {p: 0.0 for p in PIDS}, "w": 0.0})
            w = rec["w"] * frac
            for p in PIDS:
                a["sv"][p] += rec["shares"][p] * w
            a["w"] += w
    out = {}
    for new, a in acc.items():
        if a["w"] > 0:
            out[new] = {"shares": {p: a["sv"][p] / a["w"] for p in PIDS}, "w": a["w"]}
    return out


def inspect(path):
    headers, rows = read_rows(path)
    print(f"\n=== {path} ===")
    print(f"{len(rows)} datarader. Rubriker (första 14): {headers[:14]}")
    if not rows:
        print("Inga datarader hittades."); return
    code_fn, kind = resolve_code(headers, rows[0])
    print("Kod-tolkning:", kind, "| exempelkod:", code_fn(rows[0]) if code_fn else "MISSLYCKADES")
    parti_i, roster_i = find_long(headers)
    if parti_i is not None and roster_i is not None:
        print(f"Format: LÅNGT (Parti-kol {parti_i}, Röster-kol {roster_i}).")
    else:
        pidx = find_party_idx(headers)
        print("Format: BRETT. Partikolumner:", {headers[i]: p for i, p in pidx.items()} or "INGA")


def main():
    ap = argparse.ArgumentParser(description="Historiska per-valdistrikt-filer -> historik.csv")
    ap.add_argument("--src", nargs=3, action="append", metavar=("ÅR", "NIVÅ", "FIL"), default=[],
                    help="År, nivå (RD/RF/KF) och fil (upprepa).")
    ap.add_argument("--year", nargs=2, action="append", metavar=("ÅR", "FIL"), default=[],
                    help="Genväg: år + fil för riksdag (RD).")
    ap.add_argument("--remap", nargs=2, action="append", metavar=("ÅR", "FIL"), default=[])
    ap.add_argument("-o", "--out", default="data/historik.csv")
    ap.add_argument("--inspect", metavar="FIL")
    args = ap.parse_args()

    if args.inspect:
        inspect(args.inspect); return
    sources = [(yr, v.upper(), p) for yr, v, p in args.src] + [(yr, "RD", p) for yr, p in args.year]
    if not sources:
        ap.error("ange --src ÅR NIVÅ FIL eller --year ÅR FIL (eller --inspect)")

    remaps = {yr: load_remap(f) for yr, f in args.remap}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    areas = {}   # (niva, kod, year, val) -> {"v":{pid:votes}, "w":total}
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["distrikt_kod", "year", "val", "party", "share", "roster"])
        total = 0
        for yr, val, path in sources:
            data = apply_remap(load_shares(path), remaps.get(yr))
            for kod, rec in data.items():
                for p in PIDS:
                    w.writerow([kod, yr, val, p, round(rec["shares"][p], 2), int(round(rec["w"]))])
                total += 1
                # exakta områdestotaler (oberoende av distriktsindelning)
                for niva, key in (("riket", "00"), ("lan", kod[:2]), ("kommun", kod[:4])):
                    a = areas.setdefault((niva, key, yr, val), {"v": {p: 0.0 for p in PIDS}, "w": 0.0})
                    for p in PIDS:
                        a["v"][p] += rec["shares"][p] / 100.0 * rec["w"]
                    a["w"] += rec["w"]
            print(f"{yr} {val}: {len(data)} distrikt från {Path(path).name}")
        print(f"Skrev {args.out} ({total} distrikt-val-år).")
    # skriv omraden.csv bredvid historik.csv
    apath = Path(args.out).with_name("omraden.csv")
    with open(apath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["niva", "kod", "year", "val", "party", "share", "roster"])
        for (niva, key, yr, val), a in sorted(areas.items()):
            if a["w"] <= 0:
                continue
            for p in PIDS:
                w.writerow([niva, key, yr, val, p, round(a["v"][p] / a["w"] * 100.0, 2), int(round(a["w"]))])
    print(f"Skrev {apath} (exakta totaler per riket/län/kommun).")


if __name__ == "__main__":
    main()
