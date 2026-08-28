# config/ — přihlašovací údaje (necommitovat!)

Sem patří tvoje soukromé přihlášení k YouTube (Music). Obsah této složky je
v `.gitignore` a nikdy se necommituje.

Potřebný je **jediný soubor**:

- **`browser.json`** — auth pro `ytmusicapi` (hlavičky z přihlášeného prohlížeče).
  Vyrobíš přes `debug/make_auth.py` (viz hlavní README, sekce „Přihlášení").

Session si aplikace obnovuje sama, takže jeden export vydrží měsíce. Do
`browser.json` si přitom ukládá přetočené cookies — bez toho by přihlášení shodil
každý restart. Děje se to jen při skutečné rotaci (ve výchozím nastavení pár zápisů
denně, viz `SESSION_MAX_TOKEN_AGE` v README), ne průběžně. Cookies pro `yt-dlp`
si generuje do RAM (`/dev/shm/yt-cookies.txt`), na disk nejdou vůbec.

Starý `cookies.txt` z dřívějších verzí se už nepoužívá a můžeš ho smazat.

Bez `browser.json` jede aplikace v anonymním režimu (funguje jen vyhledávání
a song-rádia, bez tvých playlistů / doporučení / Premium kvality).
