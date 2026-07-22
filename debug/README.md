# Debug spuštění na Windows (Docker Desktop)

Rychlý způsob, jak si appku vyzkoušet **bez audio hardwaru**. mpv běží
s `MPV_AO=null` — přehrávání „naslepo": čas plyne v reálné rychlosti, fronta
a autoplay fungují, jen z toho není slyšet zvuk.

## Spuštění

Z **kořene projektu** (ne ze složky `debug/`):

```powershell
docker compose -f debug/docker-compose.debug.yml up --build
```

Pak otevři: **http://localhost:8080**

Zastavení: `Ctrl+C`, případně:

```powershell
docker compose -f debug/docker-compose.debug.yml down
```

## Co půjde otestovat

| Funkce | Bez přihlášení | S `config/browser.json` (+ `cookies.txt`) |
|---|---|---|
| Vyhledávání | ✅ | ✅ |
| Přehrát skladbu → autoplay stanice | ✅ | ✅ (lepší kvalita) |
| Tvoje playlisty | ❌ (prázdné) | ✅ |
| Domů / doporučení / Liked | ❌ (prázdné) | ✅ |
| WebSocket sync (víc oken) | ✅ | ✅ |
| Skutečný zvuk z jacku | ❌ (jen na serveru) | ❌ (jen na serveru) |

> **Rychlý test i bez přihlášení:** jdi na záložku **Hledat**, najdi skladbu,
> klikni → spustí se stanice. V dolní liště poběží čas, funguje ⏮/⏸/⏭,
> hlasitost i seek. Autoplay na další skladbu ověříš nejrychleji tak, že
> seekem přetáhneš skoro na konec skladby a počkáš na přechod.

## Tipy k přihlášení pro plný test

Vlož do `config/`:
- `browser.json` — `ytmusicapi browser` (viz hlavní README)
- `cookies.txt` — export přes rozšíření „Get cookies.txt LOCALLY" z youtube.com

Pokud `config/cookies.txt` necháš **prázdný** nebo v něm bude nevalidní obsah
a yt-dlp bude hlásit chyby streamu, buď ho vyplň validním exportem, nebo
soubor smaž (appka pak jede bez cookies).

## Poznámky

- První build stáhne image a nainstaluje mpv/ffmpeg → chvíli to trvá.
- Streamování vyžaduje internet (yt-dlp resolvuje audio z YouTube).
- Logy: `docker compose -f debug/docker-compose.debug.yml logs -f`
