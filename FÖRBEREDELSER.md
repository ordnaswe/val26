# Checklista inför valnatten 13 september 2026

Allt som går att förbereda i förväg är gjort. Det enda som återstår kräver
data som inte finns förrän rösträkningen börjar (kl 20 på valdagen).

## Klart och testat
- **build.py / template.html** – bygger sajten (karta, samband, avvikelse, historik, tabell, bevakning).
- **adapter.py** – översätter Valmyndighetens röstfördelnings-JSON → distrikt.csv. Byggd mot bekräftad fältbeskrivning. Plockar rätt json inuti zippen, läser partiröster, länsnamn, valdeltagande och räknestatus.
- **hamta.py** – jämför index.md5, laddar bara ändrade zip, verifierar md5, kör adapter → build → deploy. Valfri signaturkontroll med `--verify`.
- **data/kommuner.csv** – alla 290 kommuner (kod → namn). Ger läsbara kommunnamn i kartan.
- **Publicering** – GitHub + Netlify. Workflowen `.github/workflows/valnatt.yml` har schemat påslaget.

## Så funkar det på valnatten (inget du behöver göra manuellt om schemat är på)
Var 5:e minut kl 20–01 kör GitHub Actions `hamta.py`, som hämtar riksdagens
preliminära röstfördelning (`--pattern preliminar_00_RD`), bygger om sajten och
deployar. Vill du köra snabbare/stabilare: kör på en VPS med
`python3 hamta.py --loop 90 --deploy`.

## Gör detta strax efter kl 20 på valdagen
1. `python3 hamta.py --list`  → ska nu lista riktiga filnamn (inte 404).
2. Bekräfta att `preliminar_00_RD` matchar riksdagsfilen (eller byt `--pattern`).
3. Låt Actions rulla, eller starta VPS-loopen.

## Valfritt – kan läggas till när/om du vill
- **Signaturverifiering**: lägg `--verify` (kräver openssl). Extra äkthetskoll utöver md5.
- **SCB-kovariater** (inkomst, utbildning, utländsk bakgrund, medelålder, hyresrätt):
  fyll `data/scb.csv` enligt `data/scb.csv.exempel`. Källa: SCB:s valdistrikts-/DeSO-data.
  Utan denna visas ändå **valdeltagande** som kovariat (hämtas live ur röstfördelningsfilen).
- **Historik** (2014–2022 per distrikt): fyll `data/historik.csv` enligt exemplet.
  Källa: Valmyndighetens historiska röstfördelning + deras jämförbarhetsbedömning
  (distrikt ritas om mellan val).
- **Geografi/kartogram**: lägg `data/valdistrikt.geojson` (val.se, Rådata val 2026,
  SWEREF99 TM). Ange `--geojson data/valdistrikt.geojson` och rätt `--geo-code-prop`.

## Vill du visa kommunvalet i stället för riksdagen?
Byt mönster till kommunfilerna, t.ex. Värmdö: `--pattern preliminar_0120_KF`
(eller alla kommuner: `--pattern _KF`).
