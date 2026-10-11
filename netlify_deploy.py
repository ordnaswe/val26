#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlify_deploy.py — deployar en mapp till Netlify och VÄNTAR tills Netlify har publicerat den.
Avslutar med felkod om Netlify inte publicerar, så att GitHub-jobbet blir rött i stället för grönt.

    NETLIFY_SITE_ID=… NETLIFY_AUTH_TOKEN=… python3 netlify_deploy.py public_allavalda
Endast standardbibliotek.
"""
import io, json, os, sys, time, urllib.error, urllib.request, zipfile
from pathlib import Path

def api(method, url, token, data=None, ctype=None, timeout=600):
    h = {'Authorization': 'Bearer ' + token, 'User-Agent': 'allavalda-deploy/1.0'}
    if ctype: h['Content-Type'] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode('utf-8', 'ignore') or '{}')

def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else 'public_allavalda')
    site, token = os.environ.get('NETLIFY_SITE_ID'), os.environ.get('NETLIFY_AUTH_TOKEN')
    if not (site and token): sys.exit('NETLIFY_SITE_ID eller NETLIFY_AUTH_TOKEN saknas.')
    if not (folder / 'index.html').exists(): sys.exit(f'{folder}/index.html saknas – bygget har inte skapat sajten.')
    buf = io.BytesIO(); n = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file(): z.write(p, p.relative_to(folder).as_posix()); n += 1
    data = buf.getvalue()
    print(f'Skickar {n} filer ({len(data)//1024//1024} MB zip) till Netlify …', flush=True)
    try:
        d = api('POST', f'https://api.netlify.com/api/v1/sites/{site}/deploys', token, data, 'application/zip')
    except urllib.error.HTTPError as e:
        sys.exit(f'Netlify svarade {e.code}: {e.read().decode("utf-8", "ignore")[:300]}')
    did = d.get('id'); print(f'Deploy {did} skapad, väntar på att Netlify publicerar …', flush=True)
    for i in range(90):                                   # upp till 15 minuter
        time.sleep(10)
        try: d = api('GET', f'https://api.netlify.com/api/v1/deploys/{did}', token, timeout=60)
        except Exception as e: print(f'  (kunde inte läsa status: {e})'); continue
        st = d.get('state'); print(f'  status: {st}', flush=True)
        if st == 'ready':
            print(f'Publicerad: {d.get("ssl_url") or d.get("url")} (deploy {did})'); return
        if st in ('error', 'rejected'):
            sys.exit(f'Netlify publicerade inte: {d.get("error_message") or st}')
    sys.exit('Netlify blev inte klar inom 15 minuter – kontrollera under Deploys i Netlify.')

if __name__ == '__main__':
    main()
