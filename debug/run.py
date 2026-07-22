"""Debug spouštěč pro Windows.

Použití (z rootu projektu):
    .venv\\Scripts\\python.exe debug\\run.py

Nastaví prostředí z debug/.env, zpřístupní libmpv i yt-dlp.exe a spustí uvicorn.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))   # aby šlo naimportovat balík `app`
os.chdir(ROOT)

# Windows konzole bývá cp1252 → přepni na UTF-8 (logy appky obsahují češtinu/emoji)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

import _libmpv  # noqa: E402  (leží ve stejné složce)


def load_env(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ[key.strip()] = val.strip().strip('"').strip("'")


def main() -> int:
    load_env(ROOT / "debug" / ".env")

    # yt-dlp.exe z venv na PATH (mpv ytdl hook ho hledá v PATH)
    scripts = ROOT / ".venv" / "Scripts"
    if scripts.exists():
        os.environ["PATH"] = str(scripts) + os.pathsep + os.environ.get("PATH", "")

    found = _libmpv.ensure_libmpv(ROOT)
    if not found:
        print("\n" + "=" * 64)
        print("  ❌ libmpv (DLL) nenalezena — bez ní python-mpv nenaběhne.")
        print("=" * 64)
        print("  Udělej JEDNO z:")
        print("   A) Nainstaluj mpv (skript ho pak najde sám):")
        print("        scoop install mpv        (nebo)   choco install mpv")
        print("   B) Stáhni 'mpv-dev' (libmpv) a zkopíruj libmpv-2.dll sem:")
        print(f"        {ROOT / 'debug' / 'lib'}")
        print("        https://sourceforge.net/projects/mpv-player-windows/files/libmpv/")
        print("=" * 64 + "\n")
        return 1

    print(f"✔ libmpv: {found}")
    port = int(os.environ.get("PORT", "8080"))
    print(f"✔ Spouštím na http://localhost:{port}  (Ctrl+C pro ukončení)\n")

    import uvicorn
    # reload=False schválně: reloader by běžel v subprocesu bez nastavené DLL cesty
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
