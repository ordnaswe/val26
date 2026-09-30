# Eftervalsanalys del 1 – undersidan public/analys.html

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
- `.github/workflows/bygg-och-deploy.yml` – bygger analys.html vid push.

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
