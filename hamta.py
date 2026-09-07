#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hamta.py — hämtar Valmyndighetens resultatfiler och bygger om sajten.

Ett varv: jämför index.md5 mot lokal cache -> ladda ner ENBART ändrade zip ->
verifiera checksumma -> kör adapter.py (zip -> distrikt.csv) -> build.py
(-> public/index.html) -> (valfritt) deploya till Netlify.

VIKTIGT OM URL:ER OCH FILNAMN
-----------------------------
Bas-URL och index nedan är satta efter Valmyndighetens tekniska beskrivning,
men kunde inte verifieras när detta skrevs. Bekräfta först med --list, som
skriver ut de verkliga filnamnen ur index.md5:

    python3 hamta.py --list

Välj sedan vilka filer du vill följa med --pattern (delsträng som matchar
filnamnen, t.ex. röstfördelning för riksdagen). Kör med --list tills mönstret
träffar rätt filer.

VALNATTSDRIFT
-------------
GitHub Actions-cron är grov (minst ~5 min, ofta fördröjd) och saknar beständig
cache -> laddar om stora filer varje varv. För minutsnabb valnattsdrift kör
hellre detta på en liten VPS i en loop:

    while true; do python3 hamta.py --deploy; sleep 90; done
    # eller: python3 hamta.py --loop 90 --deploy

TEST UTAN NÄT
-------------
    python3 hamta.py --index-file ./index.md5 --base-dir ./zips --pattern rostfordelning

Endast Python-standardbibliotek.
(Full signaturverifiering mot _sign.sha256 + Valmyndighetens certifikat är ett
ytterligare steg; här verifieras md5 mot index.md5, vilket är den dokumenterade
integritetskontrollen.)
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- bekräftat mot val.se (teknisk beskrivning, uppd. 24 aug 2026) ---
# Filerna finns publicerade forst under rostrakningen; fore dess svarar
# servern 404. Simuleringsfilerna (genrep) raderas mellan simuleringsveckorna.
BASE_VAL = "https://resultat.val.se/resultatfiler/val2026/"
BASE_GENREP = "https://resultat.val.se/resultatfiler/genrep2026/"
INDEX_NAME = "index.md5"
CERT_URL = "https://resultat.val.se/keys/val-sign-crt.pem"

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
ZIPDIR = CACHE / "zips"
STATE = CACHE / "state.json"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------
# Nedladdning med backoff (respekterar Retry-After / 429 / 5xx)
# ------------------------------------------------------------------
def http_get(url, tries=5):
    delay = 2.0
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "valdistrikt-hamtare/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries:
                wait = float(e.headers.get("Retry-After", delay))
                log(f"HTTP {e.code} på {url} – väntar {wait:.0f}s (försök {attempt}/{tries})")
                time.sleep(wait); delay *= 2; continue
            raise
        except urllib.error.URLError as e:
            if attempt < tries:
                log(f"Nätfel {e} – väntar {delay:.0f}s"); time.sleep(delay); delay *= 2; continue
            raise
    raise RuntimeError(f"Kunde inte hämta {url}")


# ------------------------------------------------------------------
# index.md5
# ------------------------------------------------------------------
def parse_index(text):
    """Rader: '<md5> <relativ sökväg>', t.ex.
       '721f...  ./p/rd/Val_2026_preliminar_00_RD.zip'.
       Returnerar {relativ_sökväg: md5} med './'-prefix borttaget."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        md5 = next((p for p in parts if len(p) == 32 and all(c in "0123456789abcdef" for c in p.lower())), None)
        rel = next((p for p in parts if p != md5), None)
        if md5 and rel:
            out[rel.lstrip("./")] = md5.lower()
    return out


def get_index(args):
    if args.index_file:
        return parse_index(Path(args.index_file).read_text(encoding="utf-8", errors="replace"))
    base = BASE_GENREP if args.genrep else BASE_VAL
    return parse_index(http_get(base + INDEX_NAME).decode("utf-8", "replace"))


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_zip(relpath, args, dest):
    """Hämta en zip till dest. relpath är den relativa sökvägen ur index.md5."""
    if args.base_dir:
        # lokalt test: filen ligger platt (utan underkataloger) i base_dir
        src = Path(args.base_dir) / Path(relpath).name
        shutil.copyfile(src, dest)
    else:
        base = BASE_GENREP if args.genrep else BASE_VAL
        data = http_get(base + relpath)
        dest.write_bytes(data)


def flat(relpath):
    """Platt lokalt filnamn för en relativ indexsökväg."""
    return relpath.replace("/", "_")


# ------------------------------------------------------------------
# state (nedladdade checksummor)
# ------------------------------------------------------------------
def ensure_pubkey():
    """Ladda ner Valmyndighetens certifikat och ta fram publik nyckel (en gång)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    pub = CACHE / "val-pub.pem"
    if pub.exists():
        return pub
    cert = CACHE / "val-sign-crt.pem"
    cert.write_bytes(http_get(CERT_URL))
    subprocess.run(["openssl", "x509", "-pubkey", "-noout", "-in", str(cert)],
                   check=True, stdout=open(pub, "wb"))
    return pub


def verify_zip(zip_path, json_filter="rostfordelning"):
    """Verifiera signaturen för json:erna i zippen mot Valmyndighetens nyckel.
    Returnerar True om alla matchande json validerar, annars False."""
    import tempfile
    pub = ensure_pubkey()
    ok_any = False
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        for name in names:
            low = name.lower()
            if not (low.endswith(".json") and json_filter in low):
                continue
            sig = name[:-5] + "_sign.sha256"
            if sig not in names:
                log(f"  ! saknar signaturfil för {name}"); return False
            with tempfile.TemporaryDirectory() as td:
                jp = Path(td) / "d.json"; sp = Path(td) / "d.sig"
                jp.write_bytes(z.read(name)); sp.write_bytes(z.read(sig))
                r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub),
                                    "-signature", str(sp), str(jp)],
                                   capture_output=True, text=True)
                if "Verified OK" not in (r.stdout + r.stderr):
                    log(f"  ! signaturverifiering MISSLYCKADES för {name}"); return False
                ok_any = True
    return ok_any


def load_state():
    if STATE.exists():
        import json
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    import json
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------
# Ett varv
# ------------------------------------------------------------------
def one_cycle(args):
    ZIPDIR.mkdir(parents=True, exist_ok=True)
    index = get_index(args)
    if not index:
        log("Tomt/oläsbart index."); return False

    # vilka val ska hämtas
    vals = [("RD", args.pattern_rd, args.rd_out),
            ("RF", args.pattern_rf, args.rf_out),
            ("KF", args.pattern_kf, args.kf_out)]
    if args.only:
        vals = [v for v in vals if v[0] == args.only]
    # bakåtkomp: om användaren gav ett eget --pattern (ej default) och inget --only,
    # tolka det som "bara detta mönster" (ett val)
    if args.pattern != "preliminar_00_RD" and not args.only:
        vals = [("RD", args.pattern, args.rd_out)]

    state = load_state()
    any_changed = False
    built = {}          # "RD" -> csv-path (om filer fanns)
    rd_status = None
    for val, pattern, out_csv in vals:
        targets = {n: m for n, m in index.items() if pattern in n}
        if not targets:
            log(f"{val}: inga filer matchar mönstret '{pattern}'. Kör --list och justera --pattern-{val.lower()}.")
            continue
        changed = []
        for relpath, md5 in sorted(targets.items()):
            local = ZIPDIR / flat(relpath)
            if state.get(relpath) == md5 and local.exists():
                continue
            log(f"{val}: hämtar {relpath}")
            tmp = local.with_suffix(local.suffix + ".part")
            fetch_zip(relpath, args, tmp)
            got = md5_of(tmp)
            if got != md5:
                log(f"  ! checksumma fel för {relpath} – hoppar"); tmp.unlink(missing_ok=True); continue
            if args.verify:
                try:
                    if not verify_zip(tmp):
                        log(f"  ! signatur underkänd för {relpath} – hoppar"); tmp.unlink(missing_ok=True); continue
                except FileNotFoundError:
                    log("  ! openssl saknas – kör utan --verify."); tmp.unlink(missing_ok=True); continue
            tmp.replace(local); state[relpath] = md5; changed.append(relpath)
        zips = [str(ZIPDIR / flat(r)) for r in sorted(targets) if (ZIPDIR / flat(r)).exists()]
        if not zips:
            continue
        built[val] = out_csv
        if changed:
            any_changed = True
        # kör adaptern för detta val (även om oförändrat, så csv:n finns till bygget)
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        acmd = [sys.executable, str(HERE / "adapter.py"), *zips, "-o", out_csv]
        if args.kommuner and Path(args.kommuner).exists():
            acmd += ["--kommuner", args.kommuner]
        if val == "RD":
            acmd += ["--covariates-out", str(Path(args.rd_out).parent / "scb_live.csv")]
            if args.status_file:
                acmd += ["--status-out", args.status_file]
        run(acmd)

    if not built:
        log("Inga målfiler hittades för något val. Kör --list."); return False
    if not any_changed and not args.force:
        log("Inga ändringar i något val. Bygger inte om."); return False
    save_state(state)

    # bygg: primärvalet (RD om det finns, annars första) + ev. RF/KF
    primary = "RD" if "RD" in built else next(iter(built))
    cmd = [sys.executable, str(HERE / "build.py"), "--districts", built[primary], "--out", args.out,
           "--primary-val", primary]
    if "RF" in built and primary != "RF":
        cmd += ["--rf", built["RF"]]
    if "KF" in built and primary != "KF":
        cmd += ["--kf", built["KF"]]
    live_cov = str(Path(args.rd_out).parent / "scb_live.csv")
    covariates = args.covariates if Path(args.covariates).exists() else (live_cov if Path(live_cov).exists() else None)
    for flag, path in [("--covariates", covariates), ("--history", args.history), ("--geojson", args.geojson)]:
        if path and Path(path).exists():
            cmd += [flag, path]
    if args.status_file and Path(args.status_file).exists():
        cmd += ["--status", Path(args.status_file).read_text(encoding="utf-8").strip()]
    if args.live:
        cmd += ["--live"]
    run(cmd)

    if args.deploy:
        deploy(args.out)
    log(f"Klart. Byggde från {', '.join(built)}.")
    return True


def run(cmd):
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def deploy(out_html):
    site = os.environ.get("NETLIFY_SITE_ID")
    token = os.environ.get("NETLIFY_AUTH_TOKEN")
    if not (site and token):
        log("Hoppar deploy: NETLIFY_SITE_ID / NETLIFY_AUTH_TOKEN saknas i miljön.")
        return
    pub = str(Path(out_html).parent)
    run(["npx", "--yes", "netlify-cli@17", "deploy", "--prod", "--dir", pub,
         "--site", site, "--auth", token])


def list_index(args):
    index = get_index(args)
    log(f"{len(index)} poster i index:")
    for name in sorted(index):
        print("  " + name)


def main():
    ap = argparse.ArgumentParser(description="Hämta Valmyndighetens resultatfiler och bygg om sajten.")
    ap.add_argument("--pattern", default="preliminar_00_RD",
                    help="(bakåtkomp.) enkelt mönster om bara ETT val ska hämtas.")
    ap.add_argument("--pattern-rd", default="preliminar_00_RD",
                    help="Mönster för riksdagsvalet i index.md5. Default: preliminar_00_RD")
    ap.add_argument("--pattern-rf", default="preliminar_00_RF",
                    help="Mönster för regionvalet. Verifiera med --list; ofta '_RF'.")
    ap.add_argument("--pattern-kf", default="preliminar_00_KF",
                    help="Mönster för kommunvalet. Verifiera med --list; ofta '_KF'.")
    ap.add_argument("--only", choices=["RD", "RF", "KF"], help="Hämta bara ett val (annars alla tre).")
    ap.add_argument("--kommuner", default="data/kommuner.csv",
                    help="CSV kommun_kod,kommun_namn för läsbara kommunnamn (valfri)")
    ap.add_argument("--out", default="public/index.html")
    ap.add_argument("--rd-out", default="data/rd.csv")
    ap.add_argument("--rf-out", default="data/rf.csv")
    ap.add_argument("--kf-out", default="data/kf.csv")
    ap.add_argument("--covariates", default="data/scb.csv")
    ap.add_argument("--history", default="data/historik.csv")
    ap.add_argument("--geojson", default="data/valdistrikt-riket-2026.zip",
                    help="Valdistrikts-GeoJSON/zip från val.se (valfri; ger Kartogram/Geografi)")
    ap.add_argument("--status-file", default="data/status.txt")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--deploy", action="store_true", help="Deploya till Netlify (kräver env-variabler)")
    ap.add_argument("--verify", action="store_true", help="Signaturverifiera filerna (kräver openssl)")
    ap.add_argument("--force", action="store_true", help="Bygg om även utan ändringar")
    ap.add_argument("--genrep", action="store_true", help="Använd genrep2026 (generalrepetition)")
    ap.add_argument("--loop", type=int, metavar="SEK", help="Kör om och om, med SEK sekunders paus")
    ap.add_argument("--list", action="store_true", help="Skriv ut filnamnen i index.md5 och avsluta")
    # test-/offline-överstyrningar
    ap.add_argument("--index-file", help="Läs index.md5 lokalt i stället för via nät")
    ap.add_argument("--base-dir", help="Hämta zip från lokal mapp i stället för via nät")
    args = ap.parse_args()

    if args.list:
        list_index(args); return

    if args.loop:
        log(f"Loop var {args.loop}s. Avbryt med Ctrl+C.")
        while True:
            try:
                one_cycle(args)
            except Exception as e:
                log(f"FEL i varv: {e}")
            time.sleep(args.loop)
    else:
        one_cycle(args)


if __name__ == "__main__":
    main()
