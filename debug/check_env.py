"""Diagnostika prostředí — ověří, že je vše připravené k běhu na Windows.

    .venv\\Scripts\\python.exe debug\\check_env.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Windows konzole bývá cp1252 → přepni na UTF-8, ať nepadá na češtině/emoji
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

import _libmpv  # noqa: E402

OK, BAD, WARN = "✔", "❌", "⚠"


def line(mark: str, msg: str) -> None:
    print(f"  {mark}  {msg}")


def main() -> int:
    print("\n=== Kontrola prostředí ===")
    problems = 0

    # Python
    v = sys.version_info
    line(OK if v >= (3, 10) else BAD, f"Python {v.major}.{v.minor}.{v.micro}")
    if v < (3, 10):
        problems += 1

    # Python balíčky
    for mod, pkg in [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn[standard]"),
        ("ytmusicapi", "ytmusicapi"),
        ("yt_dlp", "yt-dlp"),
        ("pydantic", "pydantic"),
    ]:
        try:
            __import__(mod)
            line(OK, f"balíček {mod}")
        except ImportError:
            line(BAD, f"chybí balíček '{mod}' → pip install {pkg}")
            problems += 1

    # yt-dlp.exe na PATH (pro mpv)
    scripts = ROOT / ".venv" / "Scripts"
    if scripts.exists():
        os.environ["PATH"] = str(scripts) + os.pathsep + os.environ.get("PATH", "")
    if shutil.which("yt-dlp"):
        line(OK, f"yt-dlp.exe nalezen ({shutil.which('yt-dlp')})")
    else:
        line(WARN, "yt-dlp.exe není na PATH — run.py ho přidá z .venv\\Scripts")

    # libmpv
    found = _libmpv.ensure_libmpv(ROOT)
    if found:
        line(OK, f"libmpv: {found}")
        try:
            import mpv
            m = mpv.MPV(ao="null", video=False)
            m.terminate()
            line(OK, "python-mpv inicializace OK")
        except Exception as e:  # noqa: BLE001
            line(BAD, f"python-mpv se nepodařilo spustit: {e}")
            problems += 1
    else:
        line(BAD, "libmpv (DLL) nenalezena — viz README v debug/ (scoop install mpv / stáhnout mpv-dev)")
        problems += 1

    # ytmusicapi anonymní test (síť)
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        res = yt.search("daft punk", filter="songs", limit=1)
        line(OK if res else WARN, f"ytmusicapi anonymní search vrátil {len(res)} výsledků")
    except Exception as e:  # noqa: BLE001
        line(WARN, f"ytmusicapi test selhal (síť?): {e}")

    # Přihlašovací soubory
    for label, path in [("browser.json", ROOT / "config" / "browser.json"),
                        ("cookies.txt", ROOT / "config" / "cookies.txt")]:
        if path.exists():
            line(OK, f"config/{label} přítomen (personalizace zapnuta)")
        else:
            line(WARN, f"config/{label} chybí → anonymní režim (jen search + rádia)")

    print("\n" + ("✔ Připraveno ke spuštění: python debug\\run.py"
                  if problems == 0 else
                  f"❌ Najdi {problems} problém(ů) výše, pak spusť znovu."))
    print()
    return problems


if __name__ == "__main__":
    raise SystemExit(0 if main() == 0 else 1)
