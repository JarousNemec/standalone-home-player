"""Udržování přihlašovací session naživu — rotace cookies jako v prohlížeči.

Google session tokeny `__Secure-1PSIDTS` / `__Secure-3PSIDTS` **rotují**: server
vydá nový a starý zneplatní. Prohlížeč si o nový říká sám, vyexportované hlavičky
ne — a proto přihlášení z `config/browser.json` umřelo po ~10 minutách.

Tenhle modul dělá totéž co prohlížeč: zavolá
`POST accounts.youtube.com/RotateCookies`, ze `Set-Cookie` si vezme čerstvý token
a podstrčí ho živému `ytmusicapi` klientovi i souboru pro yt-dlp.

Rotace není „obnov token“, ale POSUN ŘETÍZKU: jakmile se přetočí S0 -> S1 -> S2,
staré S0 přestane platit — a to i pro samotné přihlášení. Token tedy neumírá
stářím, ale nahrazením. Z toho plynou dvě věci:

1. Rotuje se **jen když je proč** — periodicky se pouze OVĚŘÍ, že session žije
   (`SESSION_CHECK_INTERVAL`, jen síťový dotaz). Rotace se spustí až při selhání
   ověření nebo když token překročí `SESSION_MAX_TOKEN_AGE`.
2. Hlava řetízku se hned po rotaci uloží zpět do seed souboru — jinak by ji
   restart kontejneru ztratil a přihlášení by spadlo.

Rotace je proto JEDINÝ okamžik, kdy se sahá na disk (při výchozím nastavení
jednotky zápisů denně). Cookie jar jinak žije v RAM a soubor pro yt-dlp se
generuje na tmpfs (`/dev/shm`) — yt-dlp si ho po každé skladbě ukládá zpátky
a na disku by to znamenalo zápis do flash při každé písničce.

POZOR: jednu session smí rotovat jen jeden klient. Když zůstane přihlášené i okno
prohlížeče se stejnou session, přebíjejí se navzájem. Proto se hlavičky exportují
z anonymního okna, které se pak zavře bez odhlášení.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

log = logging.getLogger("session")

#: Rotační endpoint. POZOR na host: `accounts.google.com` naše cookies odmítá
#: (401), protože jsou z domény .youtube.com — YouTube má vlastní. Ověřeno,
#: `accounts.youtube.com` vrací kompletní sadu včetně 3P variant a SIDCC.
ROTATE_URL = "https://accounts.youtube.com/RotateCookies"
#: tělo, kterým si o rotaci říká prohlížeč (nulový "session index")
ROTATE_BODY = '[000,"-0000000000000000000"]'
YTM_URL = "https://music.youtube.com/"

#: cookies, které rotují — jediné, co se mezi během mění
ROTATING = ("__Secure-1PSIDTS", "__Secure-3PSIDTS")

#: jak často ověřit, že session žije (jen síťový dotaz, disku se to netýká)
DEFAULT_CHECK = 540.0
MIN_INTERVAL, MAX_INTERVAL = 120.0, 3600.0
#: strop stáří tokenu — pojistka, aby nezestárnul přes bezpečnou hranici.
#: 0 = rotovat výhradně tehdy, když ověření selže.
#: Změřeno: nerotovaný snímek byl po 3 h 10 min pořád přihlášený,
#: strop je proto s rezervou pod ověřenou hranicí.
DEFAULT_MAX_AGE = 2 * 3600.0
#: jak často zkoušet znovu, když je session mrtvá (čeká se na nový export)
DEAD_RETRY = 300.0
#: strop exponenciálního backoffu při výpadku sítě
MAX_BACKOFF = 300.0

HTTP_TIMEOUT = 20.0
#: expirace zapisovaná do cookie souboru pro yt-dlp; skutečnou platnost stejně
#: řídí server, tohle jen brání yt-dlp řádky zahodit jako prošlé
COOKIE_TTL = 400 * 24 * 3600


# --------------------------------------------------------------------------- #
# Cookie jar ⇄ textové formáty                                                 #
# --------------------------------------------------------------------------- #
def parse_cookie_header(raw: str) -> dict[str, str]:
    """"a=1; b=2" → {"a": "1", "b": "2"} (pořadí zachováno)."""
    jar: dict[str, str] = {}
    for part in (raw or "").split(";"):
        name, sep, value = part.partition("=")
        if sep and name.strip():
            jar[name.strip()] = value.strip()
    return jar


def build_cookie_header(jar: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def to_netscape(jar: dict[str, str]) -> str:
    """Cookie jar → Netscape formát pro yt-dlp.

    První řádek je povinný — bez něj yt-dlp soubor odmítne jako cizí formát.
    Všechny cookies z hlavičky pro music.youtube.com patří doméně `.youtube.com`.
    """
    expiry = int(time.time()) + COOKIE_TTL
    lines = ["# Netscape HTTP Cookie File",
             "# Generováno automaticky (app/session.py) — needituj ručně.", ""]
    for name, value in jar.items():
        lines.append(f".youtube.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def hint_interval(body: str) -> Optional[float]:
    """Z odpovědi rotace vytáhne, za jak dlouho se má volat příště.

    Server posílá `)]}'\\n\\n[["identity.hfcr",600],…]` — 600 s je perioda rotace.
    Bereme ji o minutu kratší, ať nejedeme po hraně.
    """
    text = (body or "").lstrip()
    if text.startswith(")]}'"):
        text = text[4:]
    try:
        data = json.loads(text)
    except ValueError:
        return None
    for item in data if isinstance(data, list) else []:
        if isinstance(item, list) and len(item) == 2 and item[0] == "identity.hfcr":
            try:
                return max(MIN_INTERVAL, min(MAX_INTERVAL, float(item[1]) - 60.0))
            except (TypeError, ValueError):
                return None
    return None


def runtime_path(path: str) -> str:
    """Cesta pro generovaný cookie soubor; mimo kontejner `/dev/shm` neexistuje."""
    parent = os.path.dirname(path) or "."
    if os.path.isdir(parent):
        return path
    fallback = os.path.join(tempfile.gettempdir(), os.path.basename(path))
    log.info("%s neexistuje → cookies pro yt-dlp budou v %s", parent, fallback)
    return fallback


# --------------------------------------------------------------------------- #
# Rotátor                                                                      #
# --------------------------------------------------------------------------- #
class CookieRotator:
    def __init__(self, auth_path: str, cookies_path: str, ytm: Any,
                 enabled: bool = True, check_interval: float = DEFAULT_CHECK,
                 max_token_age: float = DEFAULT_MAX_AGE) -> None:
        self.auth_path = auth_path
        self.cookies_path = runtime_path(cookies_path) if cookies_path else ""
        self.ytm = ytm
        self.interval = max(MIN_INTERVAL, min(MAX_INTERVAL, float(check_interval)))
        self.max_token_age = max(0.0, float(max_token_age))

        self._jar: dict[str, str] = {}
        self._seed_headers: dict[str, str] = {}
        self._seed_mtime: float = 0.0
        #: kdy vznikl token, který máme v jaru. Po startu = mtime seed souboru:
        #: ten se přepisuje jen při rotaci, takže je to přesně její čas.
        self._token_at: float = 0.0

        self._last_ok: Optional[float] = None
        self._last_check: Optional[float] = None
        self._next_at: Optional[float] = None
        self._error: Optional[str] = None

        self.reseed()
        self.enabled = bool(enabled and self._jar)

    # ---- Seed ---------------------------------------------------------------
    def reseed(self, force: bool = False) -> bool:
        """Načte cookies ze seed souboru. Vrací True, když se něco změnilo."""
        if not self.auth_path or not os.path.exists(self.auth_path):
            return False
        try:
            mtime = os.path.getmtime(self.auth_path)
            if not force and mtime == self._seed_mtime and self._jar:
                return False
            with open(self.auth_path, encoding="utf-8") as f:
                headers = json.load(f)
        except (OSError, ValueError) as e:
            log.warning("seed %s nejde přečíst: %s", self.auth_path, e)
            return False

        cookie, seed = "", {}
        for key, value in headers.items():
            if not isinstance(value, str):
                continue
            if key.lower() == "cookie":
                cookie = value
            else:
                seed[key.lower()] = value
        jar = parse_cookie_header(cookie)
        if not jar:
            log.warning("v %s není použitelná cookie hlavička", self.auth_path)
            return False

        self._jar = jar
        self._seed_headers = seed
        self._seed_mtime = mtime
        self._token_at = mtime
        log.info("seed načten (%d cookies)", len(jar))
        return True

    # ---- Výstupy ------------------------------------------------------------
    def sync_cookie_file(self) -> None:
        """Vygeneruje cookie soubor pro yt-dlp. Zápis je atomický — yt-dlp z něj
        čte při každé skladbě a nesmí chytit rozepsaný obsah."""
        if not self.cookies_path or not self._jar:
            return
        tmp = f"{self.cookies_path}.new"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(to_netscape(self._jar))
            os.replace(tmp, self.cookies_path)
        except OSError as e:
            log.warning("cookies pro yt-dlp nejdou zapsat (%s): %s",
                        self.cookies_path, e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def persist(self) -> bool:
        """Uloží aktuální cookies zpět do seed souboru — jinak restart shodí
        přihlášení (rotace posouvá řetízek a starý token zneplatní).

        Přepisuje se jen hodnota `cookie`, ostatní hlavičky zůstávají. Zápis je
        atomický, ať výpadek uprostřed nenechá na disku půlku souboru."""
        if not self.auth_path or not self._jar:
            return False
        tmp = f"{self.auth_path}.new"
        try:
            with open(self.auth_path, encoding="utf-8") as f:
                headers = json.load(f)
            key = next((k for k in headers if k.lower() == "cookie"), "cookie")
            headers[key] = build_cookie_header(self._jar)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(headers, f, ensure_ascii=True, indent=4, sort_keys=True)
            os.replace(tmp, self.auth_path)
            # ať si reseed() nemyslí, že soubor vyměnil uživatel
            self._seed_mtime = os.path.getmtime(self.auth_path)
            return True
        except (OSError, ValueError) as e:
            log.warning("cookies nejdou uložit do %s: %s", self.auth_path, e)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False

    def _publish(self) -> None:
        """Rozešle čerstvé cookies všem, kdo je používají. Zápis na disk je tady
        jediný — a děje se jen po rotaci, která je sama o sobě vzácná."""
        self.ytm.apply_cookie(build_cookie_header(self._jar))
        self.sync_cookie_file()
        self._token_at = time.time()
        self.persist()

    # ---- Rotace -------------------------------------------------------------
    def _absorb(self, response: requests.Response) -> list[str]:
        """Vezme Set-Cookie z odpovědi do jaru (přesně jak to dělá prohlížeč)."""
        changed = []
        for cookie in response.cookies:
            if cookie.value and self._jar.get(cookie.name) != cookie.value:
                self._jar[cookie.name] = cookie.value
                changed.append(cookie.name)
        # 1P a 3P varianta sdílejí hodnotu; server často pošle jen jednu.
        # Dopsat tu druhou smíme jen tehdy, když ji v odpovědi neposlal sám.
        sent = {c.name for c in response.cookies}
        for name, twin in (ROTATING, ROTATING[::-1]):
            if name in changed and twin not in sent and self._jar.get(twin) != self._jar[name]:
                self._jar[twin] = self._jar[name]
                changed.append(twin)
        return changed

    def _post_rotate(self, jar: dict[str, str]) -> requests.Response:
        return requests.post(
            ROTATE_URL,
            headers={
                "Content-Type": "application/json",
                "User-Agent": self._seed_headers.get("user-agent", "Mozilla/5.0"),
            },
            cookies=jar, data=ROTATE_BODY,
            timeout=HTTP_TIMEOUT, allow_redirects=False,
        )

    def _touch_youtube(self) -> list[str]:
        """Doplňkově si sáhne na music.youtube.com a sebere, co pošle za cookies
        (čerstvé SIDCC). Selhání je neškodné — hlavní práci dělá rotace."""
        try:
            r = requests.get(
                YTM_URL,
                headers={"User-Agent": self._seed_headers.get("user-agent", "Mozilla/5.0")},
                cookies=self._jar, timeout=HTTP_TIMEOUT, allow_redirects=False,
            )
            return self._absorb(r)
        except requests.RequestException as e:
            log.debug("dotaz na %s selhal: %s", YTM_URL, e)
            return []

    def rotate_once(self) -> dict:
        """Jeden rotační cyklus. BLOKUJE (síť). Výjimky nechává probublat."""
        if not self._jar:
            return {"ok": False, "dead": True, "error": "Chybí přihlašovací cookies."}

        # Rotovat jde jen se stávajícím tokenem v jaru — bez něj Google odpoví
        # 401 (ověřeno). Dlouhodobý __Secure-1PSID sám o sobě nestačí.
        response = self._post_rotate(self._jar)
        if response.status_code in (401, 403):
            # 401 ≠ mrtvá session! Server odmítá i rotace nakupené po sobě
            # (proto hlásí `hfcr`, jak často se smí). Ověřeno měřením: token
            # starý 25 minut projde, ale druhá rotace hned za sebou dostane 401
            # při naprosto živé session. O smrti proto rozhoduje až skutečný
            # autentizovaný dotaz, ne návratový kód rotace.
            if self.ytm.check_auth(force=True)["authenticated"]:
                return {"ok": False, "dead": False, "interval": self.interval,
                        "error": f"Obnovení odmítnuto (HTTP {response.status_code}), "
                                 f"session ale žije — zkusím to znovu."}
            return {"ok": False, "dead": True,
                    "error": "Session vypršela — Google odmítl obnovení přihlášení."}
        if response.status_code != 200:
            return {"ok": False, "dead": False,
                    "error": f"Rotace selhala: HTTP {response.status_code}."}

        changed = self._absorb(response)
        if not any(name in changed for name in ROTATING):
            # 200 bez nového tokenu = nic jsme nezískali; není důvod hlásit úspěch
            return {"ok": False, "dead": False,
                    "error": "Rotace proběhla, ale server neposlal nový token."}

        changed += self._touch_youtube()
        self._publish()
        return {"ok": True, "dead": False, "error": None,
                "changed": changed, "interval": hint_interval(response.text)}

    # ---- Smyčka -------------------------------------------------------------
    def _guarded(self) -> dict:
        try:
            result = self.rotate_once()
        except requests.RequestException as e:
            result = {"ok": False, "dead": False, "error": f"Síť: {e}"}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "dead": False, "error": f"{type(e).__name__}: {e}"}

        if result["ok"]:
            self._last_ok = time.time()
            self._error = None
            log.info("cookies obnoveny (%s)",
                     ", ".join(result.get("changed") or []) or "beze změny")
        else:
            self._error = result.get("error")
            if result.get("dead"):
                self.ytm.invalidate_auth()
                log.warning("%s", self._error)
            else:
                log.warning("obnovení selhalo — %s", self._error)
        return result

    def _needs_rotation(self) -> Optional[str]:
        """Důvod, proč rotovat i při živé session, nebo None když není proč.

        Pojistka proti tomu, aby token zestárnul přes bezpečnou hranici — kdyby
        session umřela způsobem, který rotace nespraví, ověření à pár minut by to
        zjistilo až po funuse.
        """
        if not self.max_token_age or not self._token_at:
            return None
        age = time.time() - self._token_at
        if age >= self.max_token_age:
            return f"token je starý {age / 3600:.1f} h"
        return None

    def _tick(self) -> dict:
        """Jedno kolo: ověř, a rotuj jen když je proč. BLOKUJE (síť).

        Ověření je jen dotaz po síti — na disk se sahá výhradně při rotaci.
        """
        alive = self.ytm.check_auth(force=True)["authenticated"]
        self._last_check = time.time()

        reason = "session neodpovídá jako přihlášená" if not alive             else self._needs_rotation()
        if reason is None:
            self._error = None
            return {"ok": True, "dead": False, "rotated": False}

        log.info("rotuji — %s", reason)
        result = self._guarded()
        result["rotated"] = True
        if result["ok"]:
            # cookies se vyměnily → ať si UI nedrží starý stav „nepřihlášen"
            self.ytm.invalidate_auth()
        return result

    async def run(self) -> None:
        """Hlídá session po celý život aplikace. Rotace není periodická akce,
        ale reakce — a jediný okamžik, kdy se zapisuje na disk."""
        if not self.enabled:
            log.info("automatická obnova session vypnutá")
            return
        delay, failures = 0.0, 0
        while True:
            if delay:
                await asyncio.sleep(delay)
            result = await asyncio.to_thread(self._tick)

            if result["ok"]:
                failures = 0
                delay = self.interval
            elif result.get("dead"):
                failures = 0
                delay = DEAD_RETRY
                # mezitím mohl přistát nový export — vezmi ho, až se bude zkoušet znovu
                await asyncio.to_thread(self.reseed)
            else:
                failures += 1
                # server si o interval řekl sám → respektuj ho místo backoffu
                delay = result.get("interval") or min(30.0 * 2 ** (failures - 1),
                                                      MAX_BACKOFF)
            self._next_at = time.time() + delay

    # ---- Stav pro API -------------------------------------------------------
    def status(self) -> dict:
        def iso(t: Optional[float]) -> Optional[str]:
            return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None

        return {"enabled": self.enabled,
                "lastCheck": iso(self._last_check),
                "lastRotation": iso(self._last_ok),
                "tokenAge": int(time.time() - self._token_at) if self._token_at else None,
                "nextAt": iso(self._next_at),
                "error": self._error}
