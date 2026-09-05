# Publicera valdistrikt-sajten

Samma mönster som förtidsröster-sajten och Faktadriven: ett stdlib-Python-skript
bygger en självständig `public/index.html`, och **GitHub Actions bygger och
deployar `public/` till Netlify**. `public/` committas aldrig. `index.html`
redigeras aldrig för hand — bara `template.html` och byggskripten.

## Repo-innehåll

Lägg dessa i repots rot:

```
adapter.py            # Valmyndighetens JSON/ZIP -> data/distrikt.csv
build.py              # bygger public/index.html
template.html         # UI:t (redigeras för hand, inte index.html)
data/                 # committad indata (valfritt tills datasteget finns)
  distrikt.csv        #   – finns den bygger Action:en från den
  scb.csv             #   – valfri
  historik.csv        #   – valfri
  valdistrikt.geojson #   – valfri (ger Kartogram/Geografi-läge)
  status.txt          #   – valfri, t.ex. "4 231 av 6 578 valdistrikt räknade"
.github/workflows/bygg-och-deploy.yml
```

Finns ingen `data/distrikt.csv` bygger Action:en med **syntetiskt exempeldata**,
så sajten kommer upp direkt. Byt in riktig data när du är redo.

---

## A. Netlify — skapa sajt och hämta två värden

1. netlify.com → **Add new site → Deploy manually**. Dra in valfri mapp (kör du
   `python3 build.py --out public/index.html` lokalt en gång får du en `public`-mapp
   att dra in — annars duger en tom mapp; Action:en skriver ändå över den).
2. Öppna sajten → **Site configuration → Site details** → kopiera **API ID**.
   Det är värdet till `NETLIFY_SITE_ID` (API-ID:t, inte sajtens namn eller URL).
3. Profilbilden uppe till höger → **User settings → Applications → Personal access
   tokens → New access token**. Namnge det. Kräver ditt team SSO: bocka i **Allow
   access to my SAML-based Netlify team**. **Generate token** och **kopiera strängen
   direkt** — den visas bara en gång. Det är `NETLIFY_AUTH_TOKEN`.
4. Se till att sajten och token ligger på **samma Netlify-konto/team**.

## B. GitHub — lägg in de två värdena som secrets

5. Repot → **Settings** (repots egna, i menyraden) → **Secrets and variables → Actions**.
6. **New repository secret** → Name: `NETLIFY_AUTH_TOKEN`, Secret: token-strängen från steg 3. Spara.
7. **New repository secret** igen → Name: `NETLIFY_SITE_ID`, Secret: API-ID:t från steg 2. Spara.

Kontrollera: båda ligger under **Secrets** (inte Variables), namnen exakt rätt,
inga mellanslag/radbrytningar. (Detta är repots secrets — inte fine-grained tokens.)

## C. Kör och verifiera

8. Repot → **Actions** → **Bygg och deploy valdistrikt-sajt** → **Run workflow**.
9. Öppna körningen. Grön = sajten är uppe på Netlify. Därefter bygger den om vid
   varje push till `main`.

Om deploy-steget säger `Unauthorized`, isolera med samma två värden i terminalen:

```
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer DIN_TOKEN" \
  https://api.netlify.com/api/v1/sites/DITT_SITE_ID
```

`200` = värdena funkar (då är det hur secreten klistrats in), `401` = token, `404` = fel site-ID.

## D. Undvik dubbla byggen

Låt Netlify-sajten **inte** vara kopplad till repot för egen auto-build. Valde du
"Import an existing project" av misstag: **Site configuration → Build & deploy** →
lämna build-kommandot tomt eller koppla bort repot. Det är GitHub Actions som
bygger och skickar färdiga filer till Netlify.

## E. Egen domän (Loopia)

10. Netlify → **Domain management → Add a domain** → ange domänen.
11. Netlify visar vilka DNS-poster som krävs (en CNAME för www, samt A/ALIAS för
    apex). Logga in på **Loopia → DNS-redigering** för domänen och lägg in exakt
    de poster Netlify anger. Peka inte om något annat än det Netlify listar.
12. Vänta på DNS-propagering och låt Netlify utfärda TLS-certifikatet (Let's Encrypt)
    automatiskt.

---

## Bygga om med riktig data

Lokalt, eller som ett steg före deploy:

```
# 1) Valmyndighetens JSON/ZIP -> data/distrikt.csv
python3 adapter.py --inspect resultat_kf_0120.json      # se strukturen först
python3 adapter.py resultat_kf_*.json -o data/distrikt.csv

# 2) bygg
python3 build.py --districts data/distrikt.csv \
  --covariates data/scb.csv --history data/historik.csv \
  --geojson data/valdistrikt.geojson \
  --status "4 231 av 6 578 valdistrikt räknade" --live \
  --out public/index.html
```

Committar du uppdaterad `data/`-fil och pushar till `main` bygger och deployar
Action:en automatiskt. Den kontinuerliga valnatts-hämtningen (cron + nedladdning
av ändrade zip från `index.md5`) är nästa steg — då avkommenteras `schedule` i
workflow-filen.
