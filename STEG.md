# Deploy – Valutfall (väg B: allt i molnet via GitHub)

Sajten byggs och deployas **i molnet** – din dator behöver inte vara på.
- Vid **push**: GitHub bygger sajten och deployar (workflow "Bygg och deploya").
- På **valnatten**: en schemalagd workflow kör var 5:e minut kl 20–01, hämtar
  alla tre valen från val.se, bygger om och deployar ("Valnatt").

## Vad som ska ligga i repot (väg B)
Koden + dessa databyggstenar (så att CI kan bygga):
- data/historik.csv, data/omraden.csv, data/scb.csv, data/mandat.csv, data/kommuner.csv
- data/valdistrikt-riket-2026.zip  (geometrin, ~27 MB)
Rådata (SCB-filer, .gpkg, per-distrikt-CSV:er) ska INTE ligga i repot.

## Engångs-omställning från väg A
1. Packa upp väg B-paketet (skriver över .gitignore och .github/workflows/*).
2. Sluta spåra den byggda sajten (byggs nu i CI i stället):
       git rm -r --cached public
3. Lägg till databyggstenarna (inkl. geometrin):
       git add -f data/valdistrikt-riket-2026.zip
       git add data/historik.csv data/omraden.csv data/scb.csv data/mandat.csv data/kommuner.csv
4. git add -A && git commit -m "Valutfall – väg B (moln-deploy)" && git push

## Secrets i GitHub (Settings → Secrets and variables → Actions)
- NETLIFY_SITE_ID
- NETLIFY_AUTH_TOKEN
(Netlify ska INTE ha egen git-koppling; vi deployar via CLI från Action.)

## Före valnatten – verifiera filmönstren (VIKTIGT)
Result­filerna finns på val.se först kl 20 valdagen. Mönstren för region/kommun
(--pattern-rf / --pattern-kf) är kvalificerade gissningar och MÅSTE verifieras:
- Kör workflow "Valnatt" manuellt (Actions → Run workflow) strax efter kl 20,
  ELLER lokalt:  python3 hamta.py --list
- Ser du att RF/KF-filerna heter annat än 'preliminar_00_RF' / '...KF', ändra
  standardvärdena i hamta.py (--pattern-rf/--pattern-kf) och pusha.

## Ärliga begränsningar
- GitHub-cron är ungefärlig och kan bli fördröjd 5–15+ min, särskilt en valnatt.
  Vill du minutsnabbt: kör som backup lokalt  python3 hamta.py --loop 90 --deploy
- Varje CI-körning laddar ner filerna på nytt (ingen beständig cache). Det är ok.
- Pusha INTE designändringar under själva räkningen – då kan push-bygget
  (exempel-2026) råka deployas över de riktiga siffrorna. Vänta till efter.
