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
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "/config/cookies.txt")

# Audio
MPV_AO = os.getenv("MPV_AO", "alsa")
MPV_AUDIO_DEVICE = os.getenv("MPV_AUDIO_DEVICE", "").strip()

# Přehrávání
DEFAULT_VOLUME = _int("DEFAULT_VOLUME", 100)
RADIO_REFILL_THRESHOLD = _int("RADIO_REFILL_THRESHOLD", 3)
