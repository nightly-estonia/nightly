# NIGHTLY: tasuta avalike Facebooki ürituste leidmine

See lahendus ei kasuta Facebooki API-t, ei nõua Facebooki kontot ega tasulist teenust. GitHub Actions käivitab iga päev avaliku Bingi RSS-otsingu ja salvestab leitud sündmused faili `data/facebook-events.json`. Ainult otsingutulemustes selgelt nimetatud tulevase kuupäevaga Tallinna Facebooki üritused lisatakse. Facebooki piirangute ja otsingu indekseerimise tõttu võib tulemus olla **0** ja kõiki sündmusi ei ole võimalik leida.

## Käivitamine (tasuta avalik GitHubi repo + GitHub Pages)
1. Loo GitHubis **public** repository `nightly`.
2. Laadi selle ZIPi sisu repository juurkausta (sh `.github/workflows/update-facebook.yml`).
3. Ava **Actions → Update public Facebook events → Run workflow**. Veendu, et `data/facebook-events.json` uueneb. Vajadusel luba repo **Settings → Actions → General → Workflow permissions → Read and write permissions**.
4. Ava **Settings → Pages → Build and deployment → Deploy from a branch → main / (root)**. Veebileht asub seejärel `https://KASUTAJANIMI.github.io/nightly/`.
5. Uuendus käivitub iga päev, kuid GitHub võib ajastatud tööde käivitamist edasi lükata.

Veebileht loeb JSONi suhtelisest aadressist `./data/facebook-events.json`. Kohalikul `file://` HTML eelvaatel `fetch` tavaliselt ei tööta; kasuta GitHub Pagesi või lokaalset HTTP serverit (`python -m http.server 8000`).

**Piirangud:** See on tasuta, kuid mitte garanteeritud Facebooki täielik voog. Avalik otsing ei taga ürituste täielikkust, õigsust ega ajakohasust. Ürituse originaallink tuleb enne avaldamist kontrollida. Tõsiseltvõetava konto- ja paroolisüsteemi jaoks on vaja päris autentimist: praegune HTMLi lokaalne demokonto ei sobi tootmiskeskkonda.
