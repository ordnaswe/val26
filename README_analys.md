# Partianalys – undersidan public/partianalys.html (tidigare analys.html)

Byggs av `build_analys.py` ur `public/data.json` + tre committade filer. Hakar i loopen i
`hamta.py` (efter väljaranalysen, egen try/except) och i `.github/workflows/bygg-och-deploy.yml`.

## Nya/ändrade filer
- `build_analys.py` – bygger sidan (endast standardbibliotek).
- `data/styre_kommun_2022.csv` – styre per kommun 2022–2026 (kategori, partier, KSO-parti,
  majoritet/minoritet). Källa: Faktadriven-databasen, hämtat 2026-09-30. ÖP = lokalt parti.
- `data/folkmangd_2024.csv` – SCB folkmängd 2024 via Faktadriven (Kolada N01951).
- `data/slutligt.json` – `{"RD": "2026-09-19"}`. Lägg till `"KF"` och `"RF"` med datum när
  länsstyrelserna fastställt alla val, så byter sidan etikett från "preliminärt" till "slutligt".
- `hamta.py` – anropar build_analys.py; personvalet letar nu först efter `data/kandidaturer.csv`
  (tidigare bara `../Bakgrundsfiler/`, vilket saknas på workern -> personvalet.html gav 404).
- `.github/workflows/bygg-och-deploy.yml` – bygger partianalys.html vid push.

## Flikar
Riket (resultat, mandat, län, valkretsar) · Regeringsbildning (koalitionsräknare, 175-regeln) ·
Regioner (mandat 2026/2022, block, RS-ordförande, koalitionsräknare, listettor) · Kommuner (samma +
sittande styre och om det behåller majoritet; >100k som standard, sök, län via kartan, CSV-export) ·
Avvikelser (kommuner/distrikt mot strömmen per parti) · Demografi (korrelation nivå och förändring
per faktor) · Sektorer (vägvisare per sektor).

## Viktigt om datan
- Sidan upptäcker själv om KF/RF-andelarna i data.json är identiska med 2022 (= inte inlästa) och
  visar då en tydlig varning. I den deployade data.json (2026-09-28) är bara RD live: hamta.py
  har körts utan `--pattern-rf`/`--pattern-kf`. Kör t.ex.
  `python3 hamta.py --deploy --live --pattern-rf "p/rf/" --pattern-kf "p/kf/"`
  (eller motsvarande `s/`-filer för slutliga resultat – kontrollera namnen med `--list`).
- RF/KF-mandat räknas ur områdesandelarna (jämkade uddatalsmetoden, spärr 3 % resp. 2/3 %),
  kommunen/regionen som en valkrets. Kontrollerat mot 2022: Stockholm KF och Göteborg KF samt
  Region Stockholm RF stämmer exakt med det fastställda resultatet. Personröster ingår inte.
- RD per kommun och län aggregeras ur jämförbara valdistrikt (viktat med röstberättigade).
- Koalitioner i regionerna 2022–2026 visas inte (verifierad källa saknas i repot); RS-ordförande
  m.fl. kommer från nyckelpersoner.csv (Plenum).

## Ändringar 2026-10-01
- Namnbyte Eftervalsanalys → Partianalys (`public/partianalys.html`; `analys.html` är en omdirigering).
- Karta ovanför flikarna på alla undersidor; länsfiltret gäller nu även Avvikelser och Demografi
  (korrelationer och distriktslistor räknas per län i bygget).
- Koalitioner byggs med drag-och-släpp (även riksplanet: Regering / Släpper fram / Utanför).
  Tryck utan drag flyttar partiet ett steg. Fungerar med mus och touch.
- Sektorer-fliken borttagen. Alla CSV-knappar borttagna utom mandat-exporten på startsidan.
- Väljaranalys: prickarna i punktdiagrammen är klickbara och öppnar kommunen i Partianalys
  (`/partianalys.html#kommuner&k=<kommunkod>`).
- `lan_geo.py`: byter länspolygonerna i `data/granser.json` mot Natural Earth 10m (riktig kustlinje,
  skärgård, Öland, Gotland). Kommunpolygoner och valkretslager orörda. Kör om vid behov:
  `python3 lan_geo.py` (hämtar från GitHub) eller `--src <lokal geojson>`.
- Samma statusrad överst på alla sidor, styrd av `data/slutligt.json`. hamta.py och workflowet
  kopierar filen till `public/slutligt.json` så startsidan kan läsa den.
- Footer överallt: "valutfall.se är gjord av Influera Sveriges Sandro Wennberg med hjälp av AI (Anthropic)."
- Startsidan: hero med beskrivning och kort till undersidorna, nav-knappar.
