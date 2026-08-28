r"""Ruční test obnovování session (rotace cookies).

Použití (z rootu projektu):
    docker run --rm -v "${PWD}\config:/config" -v "${PWD}\debug:/debug" ^
        debug-player:latest python /debug/rotate.py

Zavolá jednu rotaci přes `app.session.CookieRotator`, vypíše, co se změnilo,
a hned ověří, jestli s čerstvými cookies funguje přihlášení k YouTube Music.
Hodnoty cookies se NIKDY netisknou — jen jména a délky.

POZOR: rotace posouvá řetízek a starý token zneplatní. `/config` proto připoj
pro ZÁPIS (bez `:ro`), ať se hlava řetízku uloží — jinak si testem shodíš
přihlášení a budeš muset znovu exportovat hlavičky.

Přepínače pro ověření návrhu:
    --no-sidts      rotace bez rotujících tokenů (jako po restartu aplikace)
    --stale-sidts   rotace se zastaralým tokenem (rotuje 2x, podruhé vrátí starý)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path[:0] = [os.getcwd(), str(pathlib.Path(__file__).resolve().parents[1])]

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

from app import config  # noqa: E402
from app.session import ROTATING, CookieRotator  # noqa: E402
from app.ytmusic import YTM  # noqa: E402


def show(label: str, result: dict, jar: dict) -> None:
    mark = "✔" if result["ok"] else "❌"
    print(f"\n{mark} {label}")
    print(f"   ok={result['ok']} dead={result.get('dead')} "
          f"interval={result.get('interval')}")
    if result.get("error"):
        print(f"   chyba: {result['error']}")
    for name in result.get("changed") or []:
        print(f"   nové: {name} (délka {len(jar.get(name, ''))})")


def main() -> int:
    ap = argparse.ArgumentParser(description="test rotace cookies")
    ap.add_argument("--no-sidts", action="store_true",
                    help="rotovat bez __Secure-*PSIDTS (stav po restartu)")
    ap.add_argument("--stale-sidts", action="store_true",
                    help="rotovat se zastaralým tokenem (2. rotace starou hodnotou)")
    args = ap.parse_args()

    print(f"auth:    {config.YTMUSIC_AUTH}")
    print(f"cookies: {config.YTDLP_COOKIES}")

    ytm = YTM()
    rot = CookieRotator(config.YTMUSIC_AUTH, config.YTDLP_COOKIES, ytm)
    if not rot.enabled:
        print("\n❌ Chybí přihlašovací cookies — není co rotovat.")
        return 1
    jar = rot._jar  # noqa: SLF001  (ladicí nástroj smí sáhnout dovnitř)
    print(f"cookies v jaru: {len(jar)}")

    if args.no_sidts:
        for name in ROTATING:
            jar.pop(name, None)
        print(f"vyhozeno ze jaru: {', '.join(ROTATING)}")

    result = rot.rotate_once()
    show("1. rotace", result, jar)

    if args.stale_sidts:
        if not result["ok"]:
            print("\n   (2. rotaci nemá smysl zkoušet, první selhala)")
        else:
            old = {n: v for n, v in jar.items() if n in ROTATING}
            result = rot.rotate_once()
            show("2. rotace (čerstvým tokenem)", result, jar)
            jar.update(old)
            print("\n→ vracím starý token a rotuji znovu (simulace restartu)")
            result = rot.rotate_once()
            show("3. rotace (zastaralým tokenem)", result, jar)

    state = ytm.check_auth(force=True)
    print(f"\nPřihlášení po rotaci: authenticated={state['authenticated']} "
          f"account={state['account']}")
    if state["reason"]:
        print(f"   {state['reason']}")

    if os.path.exists(rot.cookies_path):
        size = os.path.getsize(rot.cookies_path)
        print(f"cookies pro yt-dlp: {rot.cookies_path} ({size} B)")

    print()
    return 0 if result["ok"] and state["authenticated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
