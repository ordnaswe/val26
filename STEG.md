# Deploy – Valutfall (väg A: bygg lokalt, committa public/)

Sajten `public/index.html` är **självständig** – all data och geometri bakas in vid bygget.
Netlify servar den filen; GitHub-Action deployar den vid varje push.

## Engångs-städning av repot
Rådata och den stora geometrin ska inte ligga i repot. Flytta undan råfilerna och
sluta spåra dem i git:

    mkdir -p ../källdata
    mv DeSO_2025.gpkg inkomst.csv utbildning.csv ålder.csv "hyresrätt.csv" "utländsk bakgrund.csv" \
       2014_*_per_valdistrikt.csv 2018_*_per_valdistrikt.csv [Rr]oster-per-distrikt-*.csv ../källdata/ 2>/dev/null
    # om de redan committats tidigare:
    git rm -r --cached --ignore-unmatch *.gpkg inkomst.csv utbildning.csv ålder.csv "hyresrätt.csv" \
       "utländsk bakgrund.csv" 2014_*_per_valdistrikt.csv 2018_*_per_valdistrikt.csv \
       "Roster-per-distrikt-*.csv" "roster-per-distrikt-*.csv" data/*.zip
    # ta bort den gamla schemalagda workflowen (används inte i väg A):
    git rm -f --ignore-unmatch .github/workflows/valnatt.yml

Geometrin `data/valdistrikt-riket-2026.zip` blir kvar lokalt (ignorerad av git) – den
behövs bara när du bygger.

## Bygg och deploya
1. Bygg sajten lokalt:

       python3 build.py --geojson data/valdistrikt-riket-2026.zip --history data/historik.csv \
         --kommuner data/kommuner.csv --covariates data/scb.csv --out public/index.html

2. Committa och pusha:

       git add -A
       git commit -m "Ny build"
       git push

   GitHub-Action `Deploy till Netlify` kör och lägger upp `public/` på sajten.

## Valnatten 13/9
Kör hämtaren lokalt – den laddar ned nya siffror, bygger om public/ och deployar direkt:

       python3 hamta.py --loop 90 --deploy

(NETLIFY_SITE_ID och NETLIFY_AUTH_TOKEN måste finnas som miljövariabler; se FÖRBEREDELSER.md.)
Alternativt: bygg om lokalt och `git push` – Action deployar då den nya public/.
