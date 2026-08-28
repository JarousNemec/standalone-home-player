r"""Vyrobí config/browser.json z hlaviček zkopírovaných z prohlížeče.

Použití (z rootu projektu):
    docker run --rm -v "${PWD}\config:/config" -v "${PWD}\debug:/debug" ^
        debug-player:latest python /debug/make_auth.py
    .venv\Scripts\python.exe debug\make_auth.py        # bez Dockeru

Přečte debug/headers.txt, nechá `ytmusicapi.setup()` udělat JSON, ověří ho
skutečným dotazem na YouTube a teprve při úspěchu přepíše config/browser.json.
Když je session mrtvá, stávající soubor zůstane nedotčený.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Windows konzole bývá cp1252 → logy obsahují češtinu a emoji
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def fail(msg: str, *hints: str) -> int:
    print(f"\n❌ {msg}")
    for h in hints:
        print(f"   {h}")
    print()
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="headers.txt → browser.json")
    ap.add_argument("--headers", type=pathlib.Path,
                    default=ROOT / "debug" / "headers.txt",
                    help="vstupní hlavičky (default: debug/headers.txt)")
    ap.add_argument("--out", type=pathlib.Path,
                    default=ROOT / "config" / "browser.json",
                    help="výstupní soubor (default: config/browser.json)")
    ap.add_argument("--no-check", action="store_true",
                    help="přeskočit ověření dotazem na YouTube")
    args = ap.parse_args()

    if not args.headers.is_file():
        return fail(
            f"Nenašel jsem {args.headers}",
            "Ve Firefoxu na music.youtube.com: F12 → Network → filtr /youtubei/v1/,",
            "pravý klik na POST → Copy → Copy Request Headers, vložit do toho souboru.",
        )

    raw = args.headers.read_text(encoding="utf-8")
    if not raw.strip():
        return fail(f"{args.headers} je prázdný.")

    import ytmusicapi
    from ytmusicapi import YTMusic
    from ytmusicapi.exceptions import YTMusicError, YTMusicUserError

    tmp = args.out.with_suffix(args.out.suffix + ".new")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        ytmusicapi.setup(filepath=str(tmp), headers_raw=raw)
    except YTMusicUserError as e:
        tmp.unlink(missing_ok=True)
        return fail(
            f"Hlavičky nejsou použitelné: {e}",
            "Musí obsahovat řádky 'Cookie:' a 'X-Goog-AuthUser:'.",
            "HAR export nestačí — prohlížeč z něj cookies vyřezává.",
        )
    except YTMusicError as e:
        tmp.unlink(missing_ok=True)
        return fail(f"ytmusicapi.setup() selhalo: {e}")

    print(f"✔ Vygenerováno: {tmp}")

    if args.no_check:
        tmp.replace(args.out)
        print(f"✔ Uloženo bez ověření: {args.out}\n")
        return 0

    try:
        yt = YTMusic(str(tmp))
        account = yt.get_account_info().get("accountName")
        playlists = len(yt.get_library_playlists())
    except Exception as e:  # noqa: BLE001
        return fail(
            "Session z těchto hlaviček nefunguje — YouTube odpovídá jako nepřihlášenému.",
            f"({type(e).__name__}: {str(e)[:200]})",
            "Zkopíruj hlavičky znovu z čerstvě načteného music.youtube.com.",
            f"Stávající {args.out} jsem nechal beze změny, nový je v {tmp}.",
        )

    tmp.replace(args.out)
    print(f"✔ Přihlášeno jako: {account}")
    print(f"✔ Playlistů v knihovně: {playlists}")
    print(f"✔ Uloženo: {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
