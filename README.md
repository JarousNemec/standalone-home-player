# 🎵 Domácí YouTube Music přehrávač

Malá dockerizovaná služba, která běží na domácím serveru (Dell Wyse 5070,
Debian/Ubuntu) a přehrává hudbu z tvého **YouTube Music Premium** účtu do
reproduktorů připojených přes **3,5mm jack**. Ovládáš ji z webu (mobil i PC)
v domácí síti — vlastní „Spotify Connect", akorát pro YouTube.

- **Bez reklam**, Premium kvalita, tvoje playlisty a doporučení.
- **Auto-rádio / autoplay** — pustíš album/skladbu a ono to samo pokračuje
  podobnými songy (algoritmus přímo z YouTube Music).
- **Knihovna** (playlisty, skladby, alba, interpreti), **Liked**, **hodnocení**
  (palec nahoru/dolů) a správa vlastních playlistů.
- **Vyhledávání s filtry** (skladby / videa / alba / interpreti / playlisty /
  komunitní / podcasty) a výsledky seskupené jako v oficiální appce.
- **Shuffle** a **opakování** (vypnuto / celá fronta / jedna skladba).
- **Stránka interpreta** a **profil skladby** včetně doporučení, správa fronty
  (přehrát další, přesun, odebrání) a kontextové menu u každé skladby.
- Ovládání z více zařízení najednou (živá synchronizace přes WebSocket).

## Jak to funguje

```
mobil / PC (LAN) ──HTTP + WebSocket──► FastAPI (Docker)
                                          ├── ytmusicapi  → „mozek": search, home, playlisty, rádio
                                          └── mpv (libmpv) → přehrává přes ALSA → jack
                                                └── yt-dlp → resolvuje audio stream
```

Doporučení a autoplay fronty se nepočítají lokálně — voláme **vlastní API
YouTube Music** (`ytmusicapi`), takže dostáváš identická rádia jako oficiální
appka, jen bez prohlížeče. `mpv` přehrává, `yt-dlp` resolvuje stream.

---

## 1) Příprava zvuku na hostiteli (jednorázově)

Server je typicky headless bez audio serveru, jedeme přímo přes **ALSA**.

```bash
# a) najdi zvukovku / jack (analogový výstup)
aplay -l
#   např.:  card 0: PCH [HDA Intel PCH], device 0: ... → identifikátor "hw:0,0"

# b) odmutuj a nastav hlasitost (šipky + 'm' na unmute)
alsamixer

# c) otestuj, že z jacku jde zvuk
speaker-test -c2 -twav -l1
```

Zapiš si identifikátor (např. `plughw:0,0`) — půjde do `.env` jako
`MPV_AUDIO_DEVICE=alsa/plughw:0,0`. Pokud necháš prázdné, mpv zvolí default.

> `plughw:` (s „plug") je bezpečnější než `hw:` — dělá automatický převod
> vzorkovací frekvence, takže se vyhneš chybám „device busy / wrong format".

---

## 2) Přihlášení k YouTube Music (jednorázově, s občasným obnovením)

Pro tvoje playlisty, doporučení, „liked" a Premium kvalitu jsou potřeba dva
soubory ve složce `config/`.

### a) `config/browser.json` — pro `ytmusicapi`

Vyrobí se z **request headers** přihlášeného requestu na YouTube Music.
Nejsnáz ve **Firefoxu** (má „Copy Request Headers" na jeden klik):

1. Otevři **music.youtube.com** (přihlášený na Premium).
2. **F12 → Network**, pak dej **F5** (reload) nebo klikni na Knihovnu/playlist —
   naskáčou requesty na `.../youtubei/v1/...` (`browse`, `next`, `search`).
3. Klikni na kterýkoli **POST** z nich → pravý klik → **Copy → Copy Request Headers**.
   (Musí obsahovat řádky `Cookie:` a `X-Goog-AuthUser:`.)
4. Vlož je do souboru **`debug/headers.txt`** (je v `.gitignore`, obsahuje session).
5. Vygeneruj `browser.json` (potřebuje `pip install ytmusicapi`):

   ```bash
   python -c "import ytmusicapi; ytmusicapi.setup(filepath='config/browser.json', headers_raw=open('debug/headers.txt', encoding='utf-8').read())"
   ```

6. Ověření (vypíše počet tvých playlistů):

   ```bash
   python -c "from ytmusicapi import YTMusic; print(len(YTMusic('config/browser.json').get_library_playlists()), 'playlistu OK')"
   ```

> **Zkratka:** kroky 5–6 dělá `debug/make_auth.py` na jeden příkaz — vygeneruje,
> ověří dotazem na YouTube a `config/browser.json` přepíše, jen když session žije:
>
> ```powershell
> docker run --rm -v "${PWD}\config:/config" -v "${PWD}\debug:/debug" `
>   debug-player:latest python /debug/make_auth.py
> ```

> **Pozor:** HAR export z DevTools NEfunguje — Chrome/Edge z něj cookies
> vyřezávají („sanitized HAR"). Použij `Copy Request Headers`, ne HAR.
>
> `browser.json` časem vyprší → zopakuj kroky 1–5 s čerstvými headers.
> Dokumentace: <https://ytmusicapi.readthedocs.io/en/stable/setup/index.html>

### b) `config/cookies.txt` — pro `yt-dlp` (Premium kvalita)

1. V prohlížeči (přihlášený na YT Premium) přidej rozšíření typu
   **„Get cookies.txt LOCALLY"**.
2. Na `youtube.com` exportuj cookies do souboru **Netscape** formátu.
3. Ulož jako `config/cookies.txt`.

Bez těchto souborů poběží aplikace anonymně (jen vyhledávání a song-rádia).

### c) Jak poznáš, že session vypršela

**YouTube na vypršené přihlášení neodpoví chybou** — místo tvých dat pošle
obecný, nepersonalizovaný obsah. Bez kontroly to vypadá, že appka nefunguje:
*Domů* ukazuje cizí žebříčky místo For You a knihovna je prázdná.

Aplikace to proto aktivně hlídá (`GET /api/status` volá `get_account_info`)
a při odhlášení ukáže **banner přes celou obrazovku** s postupem obnovy.
Personalizované endpointy vrací **HTTP 401**, ne prázdný seznam.

Z příkazové řádky se to ověří takhle — musí vypsat jméno účtu:

```bash
python -c "from ytmusicapi import YTMusic; print(YTMusic('config/browser.json').get_account_info())"
```

---

## 3) Konfigurace a spuštění (produkce — image z Docker Hubu)

Na serveru stačí složka `deploy/` — compose tahá hotový image z Docker Hubu
(image staví GitHub Actions při pushi, viz `.github/workflows/build-push.yml`).

```bash
cd deploy
cp .env.example .env
nano .env                 # nastav MPV_AUDIO_DEVICE, případně PORT
mkdir -p config           # sem browser.json a cookies.txt (viz krok 2)

docker compose up -d
docker compose logs -f
```

Otevři v prohlížeči: **http://<IP-serveru>:8080**

> **Lokální build ze zdrojáků** (bez Docker Hubu) — z kořene projektu:
>
> ```bash
> cp .env.example .env                                        # jednou
> docker compose -f debug/docker-compose.yml up --build       # Linux, se zvukem
> ```
>
> Na Windows/macOS Docker Desktopu `/dev/snd` neexistuje a kontejner by
> nenaběhl. Použij variantu bez zvuku (nastav si v `.env` `MPV_AO=null`):
>
> ```bash
> docker compose -f debug/docker-compose.no-audio.yml up --build
> ```
>
> Přihlašovací soubory patří v obou případech do `config/` v kořeni projektu.

---

## 4) Ověření (end-to-end)

- **Přihlášení**: po startu se neobjeví banner a `GET /api/status` vrátí
  `authenticated: true` se jménem účtu.
- **Zvuk**: pusť libovolnou skladbu → z repro se ozve hudba.
- **Personalizace**: *Knihovna* ukáže tvoje playlisty, skladby, alba i interprety;
  *Domů* je bez upozornění „Nepersonalizováno“.
- **Hodnocení**: srdíčko u hrající skladby ji přidá do *Liked* a v oficiální
  appce se objeví taky.
- **Shuffle**: zapnutí přehází zbytek fronty, ale hrající skladba pokračuje
  bez restartu; vypnutí vrátí původní pořadí.
- **Opakování**: *jedna* pustí skladbu znovu, ale ⏭ posune dál; *vše* se na konci
  fronty vrátí na začátek místo spuštění auto-rádia.
- **Autoplay**: pusť krátké album a nech dohrát → fronta se sama doplní
  podobnými songy a hraje dál.
- **Multi-klient**: otevři UI na mobilu i PC, dej pauzu na jednom → druhý se
  přes WebSocket okamžitě zaktualizuje.

---

## API (stručně)

| Metoda | Cesta | Účel |
|---|---|---|
| GET | `/api/status` | stav přihlášení (`authenticated`, `account`, `reason`) |
| GET | `/api/home` | `{personalized, sections}` — bez přihlášení obecný feed |
| GET | `/api/playlists`, `/api/liked`, `/api/library/{songs,albums,artists}` | knihovna (401 bez přihlášení) |
| GET | `/api/playlist/{id}`, `/api/album/{id}`, `/api/artist/{id}`, `/api/song/{id}` | detaily |
| GET | `/api/search?q=&type=` | `type` ∈ songs, videos, albums, artists, playlists, community_playlists, featured_playlists, podcasts, episodes |
| POST | `/api/play` | `source` ∈ playlist, album, radio, song, liked, library, tracks (+ `startIndex`, `shuffle`) |
| POST | `/api/mode` | `{shuffle, repeat, autoRadio}` — absolutní hodnoty, ne toggle |
| POST | `/api/rate` | `{videoId, status}` — LIKE / DISLIKE / INDIFFERENT |
| POST | `/api/queue/{add,remove,move,clear}` | správa fronty |
| POST | `/api/control/{pause,resume,toggle,next,prev,seek}` | přehrávání |
| POST | `/api/playlist/{create,{id}/add,{id}/remove}` | správa playlistů |
| WS | `/ws` | push stavu (`state`, `progress`) |

---

## Vývoj bez zvuku (na Windows/Mac dev stroji)

Logiku a API lze testovat i bez audio hardwaru (mpv přehrává „naslepo"):

```bash
python -m venv .venv && .venv/Scripts/activate    # Windows
pip install -r requirements.txt
# v .env / prostředí nastav:  MPV_AO=null
uvicorn app.main:app --reload --port 8080
```

> `python-mpv` i tak potřebuje knihovnu **libmpv** v systému (na Windows přibal
> `libmpv-2.dll` k Pythonu / do PATH; na Debianu je to balík `libmpv2`).

---

## Řešení problémů

| Problém | Řešení |
|---|---|
| Není zvuk | Zkontroluj `MPV_AUDIO_DEVICE` (`aplay -l`), odmutuj `alsamixer`. Když nejde přístup k `/dev/snd`, nahraď v compose `group_add: ["audio"]` číselným GID: `getent group audio \| cut -d: -f3`. |
| Banner „Nejsi přihlášen" / prázdná Knihovna | Vypršel `config/browser.json` → vygeneruj znovu (krok 2). Ověř přes `GET /api/status`. |
| Domů hlásí „Nepersonalizováno" | Totéž — bez platné session posílá YouTube obecný feed. |
| Nižší kvalita / chyby streamu | Chybí/vypršel `config/cookies.txt`, nebo je potřeba `pip install -U yt-dlp` (v kontejneru rebuild). |
| Přehrávání se po čase rozbije | YouTube změnil API → rebuild s aktuálním `yt-dlp`/`ytmusicapi`. |
| `libmpv` not found | Chybí balík `libmpv2` (Docker to řeší; na dev stroji doinstaluj). |
| Skladby jen přeskakují (nic nehraje) | yt-dlp nemá JS runtime na řešení YouTube signature/n-challenge (`Signature solving failed`, `The page needs to be reloaded`). Řeší `yt-dlp[default,deno]` v `requirements.txt` → rebuild image. Po 5 selháních za sebou se přehrávání zastaví a do logu přijde `Po sobě selhalo N skladeb`. |
| Filtry ve vyhledávání nevrací nic | `ytmusicapi` je v `requirements.txt` **připnutá na 1.12.1** — 1.12.2 vrací u `filter=songs/albums/artists/videos` prázdno. Před odepnutím to ověř. |

---

## Poznámky / omezení

- `ytmusicapi` a `yt-dlp` jsou **neoficiální** (šedá zóna YT ToS). Pro domácí
  použití OK; občas je potřeba aktualizovat (`docker compose build --pull`).
- Tokeny/cookies časem **vyprší** → znovu vyexportuj (viz krok 2).
- Aplikace nemá autentizaci UI — je určená **jen pro domácí síť**.

## Struktura projektu

```
app/
  main.py      FastAPI: routes, WebSocket, servírování webu
  ytmusic.py   obal ytmusicapi (knihovna, search, home, interpret, hodnocení)
  player.py    mpv ovládání, fronta, shuffle/opakování, autoplay doplňování
  state.py     WebSocket broadcast stavu
  models.py    pydantic modely requestů
  config.py    konfigurace z prostředí
web/
  index.html   kostra UI + banner o vypršené session
  style.css    jediný stylopis (tmavé téma, CSS proměnné)
  js/          ES moduly, bez build kroku
    api.js       všechna volání backendu na jednom místě
    store.js     stav přehrávače z WebSocketu + odběratelé
    router.js    hash router, záložky a zásobník detailů
    dom.js       primitiva (createElement, čas, náhledy, toast)
    ui.js        komponenty: dlaždice, řádek skladby, chipy, menu, dialogy
    player.js    spodní lišta (shuffle, opakování, like, hlasitost)
    views/       home, search, library, queue, playlist, album, artist, song
config/        přihlašovací údaje (gitignored)
deploy/        produkční compose (image z Docker Hubu) + .env.example
debug/         lokální build compose (se zvukem i varianta bez /dev/snd)
.github/       GitHub Actions — build & push image na Docker Hub
Dockerfile · requirements.txt · .env.example
```

## Licence

Kód v tomto repozitáři je pod licencí **MIT** — viz [`LICENSE`](LICENSE).
Můžeš ho používat, upravovat i šířit, jen zachovej copyright a text licence.

Licence se vztahuje **jen na kód tohoto projektu**. `ytmusicapi`, `yt-dlp`,
`mpv` i ostatní závislosti mají vlastní licence a samotná hudba z YouTube Music
pokrytá není — ta se řídí podmínkami YouTube a tvým předplatným.
