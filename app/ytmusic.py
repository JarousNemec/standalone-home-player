"""Obal nad ytmusicapi.

Sjednocuje různé tvary odpovědí do konzistentního "track" dictu:
    {videoId, title, artists, album, duration, thumbnail}

Všechny metody jsou SYNCHRONNÍ (blokující síť) — volej je z async kódu
přes `asyncio.to_thread(...)`, ať neblokují event loop.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from ytmusicapi import YTMusic

from . import config

log = logging.getLogger("ytmusic")


# --------------------------------------------------------------------------- #
# Normalizace                                                                  #
# --------------------------------------------------------------------------- #
def _artists(item: dict) -> str:
    arts = item.get("artists") or []
    names = [a.get("name") for a in arts if isinstance(a, dict) and a.get("name")]
    if names:
        return ", ".join(names)
    # fallbacky
    if item.get("author"):
        return str(item["author"])
    by = item.get("subtitle")
    return str(by) if by else ""


def _album(item: dict) -> Optional[str]:
    alb = item.get("album")
    if isinstance(alb, dict):
        return alb.get("name")
    if isinstance(alb, str):
        return alb
    return None


def _duration(item: dict) -> Optional[int]:
    if item.get("duration_seconds"):
        try:
            return int(item["duration_seconds"])
        except (TypeError, ValueError):
            pass
    # "3:45" / "1:02:03"
    text = item.get("duration") or item.get("length")
    if isinstance(text, str) and ":" in text:
        try:
            parts = [int(p) for p in text.split(":")]
            secs = 0
            for p in parts:
                secs = secs * 60 + p
            return secs
        except ValueError:
            return None
    return None


def _thumbnail(item: dict) -> Optional[str]:
    # get_playlist/search: item["thumbnails"] = [ {url,...}, ... ]
    # get_watch_playlist: item["thumbnail"] = [ {url,...}, ... ]
    thumbs = item.get("thumbnails")
    if not thumbs:
        t = item.get("thumbnail")
        if isinstance(t, dict):
            thumbs = t.get("thumbnails")
        elif isinstance(t, list):
            thumbs = t
    if isinstance(thumbs, list) and thumbs:
        return thumbs[-1].get("url")  # poslední = největší
    return None


def normalize_track(item: dict) -> Optional[dict]:
    """Vrátí přehratelný track dict, nebo None pokud nemá videoId."""
    vid = item.get("videoId")
    if not vid:
        return None
    return {
        "videoId": vid,
        "title": item.get("title") or "",
        "artists": _artists(item),
        "album": _album(item),
        "duration": _duration(item),
        "thumbnail": _thumbnail(item),
    }


def _normalize_tracks(items: list[dict]) -> list[dict]:
    out = []
    for it in items or []:
        t = normalize_track(it)
        if t and it.get("isAvailable", True):
            out.append(t)
    return out


def _normalize_home_item(it: dict) -> Optional[dict]:
    """Home/hledání vrací heterogenní karty: song / playlist / album / artist."""
    if it.get("videoId"):
        return {
            "type": "song",
            "id": it["videoId"],
            "title": it.get("title") or "",
            "subtitle": _artists(it),
            "thumbnail": _thumbnail(it),
        }
    if it.get("playlistId"):
        return {
            "type": "playlist",
            "id": it["playlistId"],
            "title": it.get("title") or "",
            "subtitle": _artists(it) or "Playlist",
            "thumbnail": _thumbnail(it),
        }
    if it.get("browseId"):
        rtype = it.get("resultType") or ("artist" if str(it["browseId"]).startswith("UC") else "album")
        return {
            "type": "artist" if rtype == "artist" else "album",
            "id": it["browseId"],
            "title": it.get("title") or "",
            "subtitle": _artists(it) or ("Interpret" if rtype == "artist" else "Album"),
            "thumbnail": _thumbnail(it),
        }
    return None


# --------------------------------------------------------------------------- #
# Klient                                                                       #
# --------------------------------------------------------------------------- #
class YTM:
    def __init__(self) -> None:
        auth = config.YTMUSIC_AUTH
        if auth and os.path.exists(auth):
            self.yt = YTMusic(auth)
            self.authenticated = True
            log.info("ytmusicapi: přihlášeno přes %s", auth)
        else:
            self.yt = YTMusic()  # anonymní režim (search/radio funguje)
            self.authenticated = False
            log.warning(
                "ytmusicapi: auth soubor %s nenalezen — jedu anonymně "
                "(personalizace nebude fungovat)", auth,
            )

    # ---- Knihovna / personalizace (vyžaduje auth) ---------------------------
    def get_playlists(self) -> list[dict]:
        try:
            res = self.yt.get_library_playlists(limit=100)
        except Exception as e:  # noqa: BLE001
            log.warning("get_library_playlists selhalo: %s", e)
            return []
        out = []
        for p in res or []:
            out.append({
                "playlistId": p.get("playlistId"),
                "title": p.get("title") or "",
                "count": p.get("count"),
                "thumbnail": _thumbnail(p),
            })
        return [p for p in out if p["playlistId"]]

    def get_liked(self) -> list[dict]:
        try:
            res = self.yt.get_liked_songs(limit=500)
        except Exception as e:  # noqa: BLE001
            log.warning("get_liked_songs selhalo: %s", e)
            return []
        return _normalize_tracks((res or {}).get("tracks", []))

    def get_home(self) -> list[dict]:
        try:
            sections = self.yt.get_home(limit=6)
        except Exception as e:  # noqa: BLE001
            log.warning("get_home selhalo: %s", e)
            return []
        out = []
        for sec in sections or []:
            items = []
            for it in sec.get("contents") or []:
                norm = _normalize_home_item(it)
                if norm:
                    items.append(norm)
            if items:
                out.append({"title": sec.get("title") or "", "items": items})
        return out

    # ---- Obsah --------------------------------------------------------------
    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        try:
            res = self.yt.get_playlist(playlist_id, limit=1000)
        except Exception as e:  # noqa: BLE001
            log.warning("get_playlist(%s) selhalo: %s", playlist_id, e)
            return []
        return _normalize_tracks((res or {}).get("tracks", []))

    def get_album_tracks(self, browse_id: str) -> list[dict]:
        try:
            res = self.yt.get_album(browse_id)
        except Exception as e:  # noqa: BLE001
            log.warning("get_album(%s) selhalo: %s", browse_id, e)
            return []
        tracks = _normalize_tracks((res or {}).get("tracks", []))
        # album tracky občas nemají vlastní thumbnail → doplň obalem alba
        cover = _thumbnail(res or {})
        for t in tracks:
            if not t.get("thumbnail"):
                t["thumbnail"] = cover
        return tracks

    def get_radio(self, video_id: str, limit: int = 50) -> list[dict]:
        """Algoritmem generovaná stanice (autoplay) seedovaná ze skladby."""
        try:
            res = self.yt.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
        except Exception as e:  # noqa: BLE001
            log.warning("get_watch_playlist(%s) selhalo: %s", video_id, e)
            return []
        return _normalize_tracks((res or {}).get("tracks", []))

    def search(self, query: str, kind: Optional[str] = None) -> list[dict]:
        filt = {
            "songs": "songs",
            "albums": "albums",
            "artists": "artists",
            "playlists": "playlists",
        }.get(kind or "", None)
        try:
            res = self.yt.search(query, filter=filt, limit=25)
        except Exception as e:  # noqa: BLE001
            log.warning("search(%s) selhalo: %s", query, e)
            return []
        out = []
        for it in res or []:
            norm = _normalize_home_item(it)
            if norm:
                out.append(norm)
        return out
