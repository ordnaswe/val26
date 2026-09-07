#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adapter.py — Valmyndighetens röstfördelning (JSON/ZIP) -> distrikt.csv

Sluter kedjan: adapter.py -> distrikt.csv -> build.py -> självständig HTML.

Byggd mot Valmyndighetens bekräftade fältbeskrivning för preliminär
röstfördelning (val.se, prel-rostfordelning.md, uppd. 2026-04-14). Partiröster
läses ur rostfordelning.rosterPaverkaMandat.partiRoster[] (partiforkortning +
antalRoster). Verifiera vid behov med --inspect på en riktig fil.

Vanlig körning (en zip per val; adaptern plockar röstfördelnings-json inuti):
    python3 adapter.py Val_2026_preliminar_00_RD.zip -o distrikt.csv
Flera filer (t.ex. alla 290 KF-zip):
    python3 adapter.py "*_KF.zip" -o distrikt.csv

Se strukturen på en riktig/simulerad fil:
    python3 adapter.py --inspect Val_2026_preliminar_00_RD.zip

Testa mekaniken utan riktig fil (skriver en fil i RÄTT struktur):
    python3 adapter.py --sample-json prov.json
    python3 adapter.py prov.json -o distrikt.csv

Endast Python-standardbibliotek.
"""

import argparse
import csv
import glob
import io
import json
import sys
import zipfile
from pathlib import Path

PIDS = ["V", "S", "MP", "C", "L", "KD", "M", "SD"]

# partiforkortning -> vår kod (rostfordelning använder förkortningar)
PARTY_ALIAS = {
    "v": "V", "s": "S", "mp": "MP", "c": "C", "l": "L", "fp": "L",
    "kd": "KD", "m": "M", "sd": "SD",
}

# 2-ställig länskod -> länsnamn (stabil standard)
LAN_NAMN = {
    "01": "Stockholms län", "03": "Uppsala län", "04": "Södermanlands län",
    "05": "Östergötlands län", "06": "Jönköpings län", "07": "Kronobergs län",
    "08": "Kalmar län", "09": "Gotlands län", "10": "Blekinge län",
    "12": "Skåne län", "13": "Hallands län", "14": "Västra Götalands län",
    "17": "Värmlands län", "18": "Örebro län", "19": "Västmanlands län",
    "20": "Dalarnas län", "21": "Gävleborgs län", "22": "Västernorrlands län",
    "23": "Jämtlands län", "24": "Västerbottens län", "25": "Norrbottens län",
}

# ----------------------------------------------------------------------------
# MAPPING — bekräftad mot prel-rostfordelning.md. Justera bara om Valmyndigheten
# ändrar schemat (kontrollera då med --inspect).
# ----------------------------------------------------------------------------
MAPPING = {
    "district_list":   "valdistrikt",
    "district_code":   "valdistriktskod",
    "district_name":   "namn",
    "kommun_kod":      "kommunkod",
    "lan_kod":         "lankod",
    "rostberattigade": "antalRostberattigade",
    "turnout":         "valdeltagandeVallokal",
    # partiröster (giltiga, påverkar mandat)
    "party_list_path": "rostfordelning.rosterPaverkaMandat.partiRoster",
    "party_code_key":  "partiforkortning",
    "party_votes_key": "antalRoster",
    # totala giltiga röster (nämnare) och "övriga partier"-klumpen
    "valid_total":     "rostfordelning.rosterPaverkaMandat.antalRoster",
    "ovriga_votes":    "rostfordelning.rosterPaverkaMandat.rosterOvrigaPartier.antalRoster",
    # räknestatus på rot-nivå
    "raknade":  "antalValdistriktRaknade",
    "ska":      "antalValdistriktSomSkaRaknas",
}


def dig(obj, path):
    cur = obj
    for key in (path or "").split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def norm_party(code):
    return PARTY_ALIAS.get(str(code).strip().lower()) if code is not None else None


def to_int(v):
    if v is None:
        return 0
    try:
        return int(round(float(str(v).replace(" ", "").replace(",", "."))))
    except (ValueError, TypeError):
        return 0


def zpad2(code):
    c = str(code or "").strip()
    return c.zfill(2) if c.isdigit() else c


# ----------------------------------------------------------------------------
# Läs json/zip. Ur en zip plockas endast json vars namn matchar json_filter.
# ----------------------------------------------------------------------------
def load_json_blobs(path, json_filter="rostfordelning"):
    p = Path(path)
    blobs = []
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                low = name.lower()
                if low.endswith(".json") and json_filter in low:
                    with z.open(name) as f:
                        blobs.append((f"{p.name}:{name}", json.load(io.TextIOWrapper(f, "utf-8"))))
    else:
        blobs.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
    return blobs


def extract_votes(rec):
    votes = {pid: 0 for pid in PIDS}
    arr = dig(rec, MAPPING["party_list_path"])
    if isinstance(arr, list):
        for item in arr:
            if isinstance(item, dict):
                pid = norm_party(item.get(MAPPING["party_code_key"]))
                if pid:
                    votes[pid] = to_int(item.get(MAPPING["party_votes_key"]))
    return votes


def rows_from_blob(obj, kommun_lookup):
    dl = dig(obj, MAPPING["district_list"])
    if not isinstance(dl, list):
        return [], (0, 0)
    rows = []
    for rec in dl:
        if not isinstance(rec, dict):
            continue
        lankod = zpad2(dig(rec, MAPPING["lan_kod"]))
        kkod = str(dig(rec, MAPPING["kommun_kod"]) or "").strip()
        turnout = dig(rec, MAPPING["turnout"])
        votes = extract_votes(rec)
        # nämnare = totala giltiga röster; annars 8 partier + övriga-klumpen
        giltiga = to_int(dig(rec, MAPPING["valid_total"]))
        if giltiga <= 0:
            giltiga = sum(votes.values()) + to_int(dig(rec, MAPPING["ovriga_votes"]))
        rows.append({
            "distrikt_kod": str(dig(rec, MAPPING["district_code"]) or "").strip(),
            "distrikt_namn": dig(rec, MAPPING["district_name"]) or "",
            "kommun_kod": kkod,
            "kommun_namn": kommun_lookup.get(kkod, kkod),   # fallback: koden
            "lan_namn": LAN_NAMN.get(lankod, lankod),
            "rost_berattigade": to_int(dig(rec, MAPPING["rostberattigade"])),
            "giltiga": giltiga,
            "raknat": 1 if giltiga > 0 else 0,   # räknat = distriktet har rapporterat
            "_turnout": turnout,   # valdeltagande (till kovariater), skrivs ej i distrikt.csv
            **votes,
        })
    raknade = to_int(dig(obj, MAPPING["raknade"]))
    ska = to_int(dig(obj, MAPPING["ska"]))
    return rows, (raknade, ska)


def write_csv(rows, out_path):
    cols = ["distrikt_kod", "distrikt_namn", "kommun_kod", "kommun_namn",
            "lan_namn", "rost_berattigade", "giltiga", "raknat"] + PIDS
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def load_kommun_lookup(path):
    if not path:
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            kod = (r.get("kommun_kod") or r.get("kommunkod") or "").strip()
            namn = (r.get("kommun_namn") or r.get("kommun") or "").strip()
            if kod and namn:
                out[kod] = namn
    return out


# ----------------------------------------------------------------------------
# --inspect
# ----------------------------------------------------------------------------
def inspect(path, json_filter):
    for name, obj in load_json_blobs(path, json_filter):
        print(f"\n=== {name} ===")
        print("Rot-fält:", ", ".join(obj.keys()) if isinstance(obj, dict) else type(obj).__name__)
        dl = dig(obj, MAPPING["district_list"])
        if isinstance(dl, list) and dl:
            print(f"valdistrikt: {len(dl)} st. Första distriktets fält:")
            print("  " + ", ".join(dl[0].keys()))
            print("Räknade / ska räknas:",
                  dig(obj, MAPPING["raknade"]), "/", dig(obj, MAPPING["ska"]))
            v = extract_votes(dl[0])
            got = {p: n for p, n in v.items() if n}
            print("Tolkade partiröster i distrikt 1:", got or "INGA – kontrollera MAPPING/PARTY_ALIAS")
        else:
            print("Hittade ingen 'valdistrikt'-array – fel filtyp? (--inspect plockar json som matchar --json-filter)")
        break


# ----------------------------------------------------------------------------
# --sample-json: syntetisk fil i RÄTT struktur (för test utan riktig fil)
# ----------------------------------------------------------------------------
def write_sample_json(path):
    import random
    random.seed(7)
    fk = {"V": "v", "S": "s", "MP": "mp", "C": "c", "L": "l", "KD": "kd", "M": "m", "SD": "sd"}
    dists = []
    for i in range(28):
        votes = {p: max(0, int(random.gauss(120, 90))) for p in PIDS}
        votes["S"] += 250; votes["M"] += 180
        partiRoster = [{"partibeteckning": p, "partiforkortning": fk[p], "partikod": str(k),
                        "antalRoster": votes[p], "andelRoster": 0.0} for k, p in enumerate(PIDS)]
        ovriga = max(0, int(random.gauss(60, 30)))   # småpartier klumpade
        giltiga = sum(votes.values()) + ovriga
        dists.append({
            "namn": f"Värmdö {i+1}", "valdistriktstyp": "Valdistrikt",
            "valdistriktskod": f"0120{i+1:04d}", "kommunkod": "0120", "lankod": "01",
            "valomradeskod": "00", "antalRostberattigade": random.randint(900, 2000),
            "rostfordelning": {"rosterPaverkaMandat": {"partiRoster": partiRoster,
                                                       "rosterOvrigaPartier": {"antalRoster": ovriga},
                                                       "antalRoster": giltiga}},
        })
    obj = {"valtillfalle": "Val 2026", "rakningstillfalle": "preliminär", "valtyp": "KF",
           "valdatum": "2026-09-13", "antalValdistriktRaknade": 28,
           "antalValdistriktSomSkaRaknas": 28, "valdistrikt": dists}
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Skrev syntetisk provfil {path} (28 distrikt) i Valmyndighetens struktur.")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Valmyndighetens röstfördelning JSON/ZIP -> distrikt.csv")
    ap.add_argument("inputs", nargs="*", help=".json/.zip-filer eller glob-mönster")
    ap.add_argument("-o", "--out", default="distrikt.csv")
    ap.add_argument("--json-filter", default="rostfordelning",
                    help="Delsträng som väljer rätt json inuti varje zip (default: rostfordelning)")
    ap.add_argument("--kommuner", help="CSV kommun_kod,kommun_namn för läsbara kommunnamn (valfri)")
    ap.add_argument("--status-out", help="Skriv 'X av Y valdistrikt räknade' till denna fil (valfri)")
    ap.add_argument("--covariates-out", help="Skriv distrikt_kod,turnout (valdeltagande ur filen) hit (valfri)")
    ap.add_argument("--inspect", metavar="FILE")
    ap.add_argument("--sample-json", metavar="FILE")
    args = ap.parse_args()

    if args.sample_json:
        write_sample_json(args.sample_json); return
    if args.inspect:
        inspect(args.inspect, args.json_filter); return
    if not args.inputs:
        ap.error("ange indatafiler (eller använd --inspect/--sample-json)")

    paths = []
    for pat in args.inputs:
        paths.extend(sorted(glob.glob(pat)) or [pat])

    kommun_lookup = load_kommun_lookup(args.kommuner)
    rows, seen, tot_r, tot_s = [], set(), 0, 0
    for path in paths:
        for _, obj in load_json_blobs(path, args.json_filter):
            blob_rows, (r, s) = rows_from_blob(obj, kommun_lookup)
            tot_r += r; tot_s += s
            for row in blob_rows:
                key = row["distrikt_kod"] or (row["kommun_kod"], row["distrikt_namn"])
                if key in seen:
                    continue
                seen.add(key); rows.append(row)

    if not rows:
        sys.exit("Inga distrikt extraherade. Kör --inspect och kontrollera --json-filter / MAPPING.")

    write_csv(rows, args.out)
    if args.covariates_out:
        Path(args.covariates_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.covariates_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["distrikt_kod", "turnout"])
            for r in rows:
                t = r.get("_turnout")
                if r["distrikt_kod"] and t is not None:
                    w.writerow([r["distrikt_kod"], t])
    if args.status_out and tot_s:
        Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.status_out).write_text(f"{tot_r} av {tot_s} valdistrikt räknade",
                                         encoding="utf-8")
    with_votes = sum(1 for r in rows if any(r[p] for p in PIDS))
    extra = f" · status {tot_r}/{tot_s}" if tot_s else ""
    print(f"Skrev {args.out}: {len(rows)} distrikt ({with_votes} med röster) "
          f"från {len(paths)} fil(er){extra}.")


if __name__ == "__main__":
    main()
