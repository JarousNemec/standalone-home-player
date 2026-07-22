"""Najde a zpřístupní libmpv DLL pro python-mpv na Windows.

python-mpv načítá libmpv při importu, takže se musí zavolat PŘED `import mpv`.
Hledá DLL v běžných místech (scoop/choco/Program Files/PATH/debug/lib) a kopii
uloží do debug/lib pod všemi názvy, které různé verze python-mpv zkoušejí.
"""
from __future__ import annotations

import os
import pathlib
import shutil

# různé buildy/verze mají různé názvy
DLL_NAMES = ["libmpv-2.dll", "mpv-2.dll", "mpv-1.dll", "libmpv.dll"]
TARGET_NAMES = ["libmpv-2.dll", "mpv-2.dll", "mpv-1.dll"]


def _candidate_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    dirs: list[pathlib.Path] = [root / "debug" / "lib", root]
    exe = shutil.which("mpv")
    if exe:
        dirs.append(pathlib.Path(exe).parent)
    up = os.environ.get("USERPROFILE", "")
    if up:
        dirs.append(pathlib.Path(up) / "scoop" / "apps" / "mpv" / "current")
    dirs += [
        pathlib.Path(r"C:\Program Files\mpv"),
        pathlib.Path(r"C:\ProgramData\chocolatey\lib\mpv\tools"),
        pathlib.Path(r"C:\mpv"),
    ]
    return dirs


def _find_source(dirs: list[pathlib.Path]) -> pathlib.Path | None:
    for d in dirs:
        try:
            for name in DLL_NAMES:
                p = d / name
                if p.is_file():
                    return p
        except OSError:
            continue
    return None


def ensure_libmpv(root: str | os.PathLike) -> pathlib.Path | None:
    """Zajistí, že python-mpv najde libmpv. Vrátí cestu k nalezené DLL, nebo None."""
    root = pathlib.Path(root)
    libdir = root / "debug" / "lib"
    libdir.mkdir(parents=True, exist_ok=True)

    src = _find_source(_candidate_dirs(root))
    if src is None:
        return None

    # nakopíruj pod všechny názvy do debug/lib
    for name in TARGET_NAMES:
        target = libdir / name
        if not target.exists():
            try:
                shutil.copy2(src, target)
            except OSError:
                pass

    # zpřístupni pro loader DLL i pro PATH (subprocesy)
    try:
        os.add_dll_directory(str(libdir))
    except (AttributeError, OSError):
        pass
    os.environ["PATH"] = str(libdir) + os.pathsep + os.environ.get("PATH", "")
    return src
