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

## Geografi / Kartogram – fyll ut hela Sverige (frivilligt men rekommenderat)

Bygget kan läsa Valmyndighetens officiella valdistriktsgeometri direkt (även som
zip – ingen uppackning behövs). Det känner själv igen vilket fält som är
distriktskoden.

1. Ladda ner (på val.se, "Rådata val 2026" → "Valdistrikt i val 2026 – kartor"):
   - Hela Sverige (~27 MB): valdistrikt-riket-2026.zip
   - eller ett enskilt län för snabbare test, t.ex. Stockholm (~2 MB).
   Lägg filen i `data/` som `data/valdistrikt-riket-2026.zip`.

2. Förhandsgranska nu (riktig geometri + syntetiska röster):
   `python3 build.py --geojson data/valdistrikt-riket-2026.zip --out public/index.html`
   Öppna public/index.html – nu fylls hela Sverige ut i Kartogram och Geografi.

3. På valnatten sker det automatiskt: `hamta.py` letar efter
   `data/valdistrikt-riket-2026.zip` och kopplar in den utan extra flaggor.

Storlek: hela riket är ~6 500 distrikt. Blir HTML-filen stor kan du förenkla
polygonerna med t.ex. `--geo-max-points 20`.

Koordinatsystemet är SWEREF99 TM; läget blir korrekt men det är ingen exakt
kartprojektion (det räcker gott för kartogram och översiktskarta).

## Tre val + röstsplittring (RD/RF/KF)

Verktyget kan nu bära alla tre valen samtidigt och visa röstsplittringen mellan
dem (fliken Röstsplittring), plus en valväxlare överst och alla tre valen i
distriktsrutan. I förhandsvisningen finns alla tre (syntetiska).

På valnatten bygger du med tre distrikt-CSV:er (en per val ur adaptern):

```
python3 adapter.py Val_2026_preliminar_00_RD.zip  -o data/rd.csv
python3 adapter.py Val_2026_preliminar_*_RF.zip   -o data/rf.csv
python3 adapter.py Val_2026_preliminar_*_KF.zip   -o data/kf.csv
python3 build.py --districts data/rd.csv --rf data/rf.csv --kf data/kf.csv \
  --geojson data/valdistrikt-riket-2026.zip --kommuner data/kommuner.csv \
  --out public/index.html
```

Distrikten joinas på valdistriktskod (samma över alla tre valen). Anger du bara
--districts blir det ett val och valväxlaren döljs. Den automatiska
valnattshämtningen av alla tre nivåerna (hämta.py) kan wire:as som nästa steg –
i nuläget hämtar den ett val i taget via --pattern.

Obs: förändringstal per val (jämförelse mot föregående val) finns i
röstfördelningsfilen men läses inte ut av adaptern ännu; i riktig flernivådata
visas därför förändring som 0 tills det kopplas in.

## Riktig historik (2014/2018/2022) – historik.py

Historiken i förhandsvisningen är syntetisk. För riktig historik:

1. Ladda ner per-valdistrikt-filerna från val.se:
   - 2022: "Rådata från val 2002–2022" → "Röster per distrikt … riksdagsvalet" (xlsx)
   - 2018: historik.val.se/val/val2018/statistik → 2018_R_per_valdistrikt.xlsx
   - 2014: historik.val.se/val/val2014/statistik → 2014_riksdagsval_per_valdistrikt.skv
2. xlsx går inte att läsa med Python-stdlib – spara om 2018/2022-filerna till CSV
   i Excel/Numbers. 2014-.skv:n funkar direkt (semikolon-CSV).
3. Se kolumnerna: `python3 historik.py --inspect 2014_riksdagsval_per_valdistrikt.skv`
4. Bygg: `python3 historik.py --year 2014 f14.skv --year 2018 f18.csv --year 2022 f22.csv -o data/historik.csv`

Distriktsomritning: utan omkodning joinas på oförändrad distriktskod (de flesta).
För full korrekthet behövs Valmyndighetens jämförbarhetsbedömningar
("Jämförelser mellan valdistrikt 2018 och 2022" m.fl.), kedjade fram till 2026,
och matas in med `--remap ÅR fil.csv`. Detta är den mest arbetskrävande biten och
måste verifieras mot de riktiga filernas kolumner.

## Riktiga kovariater (SCB) – nästa databit

inkomst/utbildning/utländsk bakgrund/medelålder/hyresrätt per valdistrikt kommer
från SCB (valdistrikts-/DeSO-data). Fyll `data/scb.csv` enligt exemplet. Utan den
visas ändå valdeltagande live ur röstfördelningsfilen. Ett eget hämtningsskript
för SCB-datan kan byggas separat.


## Historik per valnivå (RD/RF/KF)

historik.py stödjer nu alla tre nivåerna via --src ÅR NIVÅ FIL (RD=riksdag,
RF=region/landsting, KF=kommun). Kör alla filer i ett svep:

    python3 historik.py \
      --src 2014 RD 2014_riksdagsval_per_valdistrikt.csv \
      --src 2014 RF 2014_landstingsval_per_valdistrikt.csv \
      --src 2014 KF 2014_kommunval_per_valdistrikt.csv \
      --src 2018 RD 2018_R_per_valdistrikt.csv \
      --src 2018 RF 2018_L_per_valdistrikt.csv \
      --src 2018 KF 2018_K_per_valdistrikt.csv \
      --src 2022 RD "Roster-per-distrikt-...-riksdagsvalet-2022.csv" \
      -o data/historik.csv

Historik-kurvan byter då med valväxlaren (RD/RF/KF). För 2022 region/kommun
behövs L-/K-filerna från val.se om du vill ha 2022 även för RF/KF.
