"""Konfigurace čtená z prostředí (.env přes docker-compose)."""
import os


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# HTTP
PORT = _int("PORT", 8080)

# Přihlášení
YTMUSIC_AUTH = os.getenv("YTMUSIC_AUTH", "/config/browser.json")
# Cookies pro yt-dlp si aplikace GENERUJE z YTMUSIC_AUTH. Default míří na tmpfs
# (RAM) schválně: yt-dlp si soubor po každé skladbě ukládá zpátky, a na disku by
# to znamenalo zápis do flash při každé písničce.
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "/dev/shm/yt-cookies.txt")

# Obnovování session (rotace __Secure-*PSIDTS jako v prohlížeči)
SESSION_ROTATE = os.getenv("SESSION_ROTATE", "1").strip().lower() not in ("0", "false", "no", "")
# Jak často ověřit, že session žije. Jen dotaz po síti — disku se netýká.
SESSION_CHECK_INTERVAL = _int("SESSION_CHECK_INTERVAL", 540)
# Strop stáří tokenu. Rotace (a s ní jediný zápis na disk) se jinak spustí až
# tehdy, když ověření selže. 0 = žádný strop, rotovat výhradně při selhání.
SESSION_MAX_TOKEN_AGE = _int("SESSION_MAX_TOKEN_AGE", 2 * 3600)

# Audio
MPV_AO = os.getenv("MPV_AO", "alsa")
MPV_AUDIO_DEVICE = os.getenv("MPV_AUDIO_DEVICE", "").strip()

# Přehrávání
DEFAULT_VOLUME = _int("DEFAULT_VOLUME", 100)
RADIO_REFILL_THRESHOLD = _int("RADIO_REFILL_THRESHOLD", 3)

# Jazyk a region dat z YouTube Music (viz ytmusicapi/locales)
YTM_LANGUAGE = os.getenv("YTM_LANGUAGE", "cs").strip() or "cs"
YTM_LOCATION = os.getenv("YTM_LOCATION", "CZ").strip()
