# config/ — přihlašovací údaje (necommitovat!)

Sem patří tvoje soukromé přihlášení k YouTube (Music). Obsah této složky je
v `.gitignore` a nikdy se necommituje.

Potřebné soubory:

- **`browser.json`** — auth pro `ytmusicapi` (hlavičky z přihlášeného prohlížeče).
  Vygeneruješ příkazem `ytmusicapi browser` (viz hlavní README, sekce „Přihlášení").
- **`cookies.txt`** — cookies pro `yt-dlp` (Premium kvalita + soukromý obsah).
  Export přes rozšíření prohlížeče typu „Get cookies.txt LOCALLY" z `youtube.com`.

Bez těchto souborů jede aplikace v anonymním režimu (funguje jen vyhledávání
a song-rádia, bez tvých playlistů / doporučení / Premium kvality).
