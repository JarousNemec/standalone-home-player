"""Obal nad ytmusicapi.

Sjednocuje různé tvary odpovědí do konzistentního "track" dictu:
    {videoId, title, artists, artistId, album, albumId, duration, thumbnail,
     likeStatus, setVideoId}

a do "card" dictu pro heterogenní dlaždice (home / hledání / související):
    {type, id, title, subtitle, thumbnail, category}

Všechny metody jsou SYNCHRONNÍ (blokující síť) — volej je z async kódu
přes `asyncio.to_thread(...)`, ať neblokují event loop.

Vypršelá session se navenek projeví prázdným obsahem, ne chybou (YouTube
místo dat pošle "Sign in"). Proto se každé selhání ověří přes `check_auth()`
a pokud jsme odhlášeni, letí ven `YTMAuthError` → HTTP 401 → banner v UI.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

from ytmusicapi import YTMusic

from . import config

log = logging.getLogger("ytmusic")

#: jak dlouho věříme poslednímu ověření přihlášení (s)
AUTH_TTL = 300.0


class YTMAuthError(Exception):
    """Session u YouTube Music neexistuje nebo vypršela."""


# --------------------------------------------------------------------------- #
# Normalizace                                                                  #
# --------------------------------------------------------------------------- #
def _artists(item: dict) -> str:
    arts = item.get("artists") or []
    names = [a.get("name") for a in arts if isinstance(a, dict) and a.get("name")]
    if names:
        return ", ".join(names)
    # fallbacky
    if item.get("artist"):          # knihovna / skladby na stránce interpreta
        return str(item["artist"])
    if item.get("author"):
        return str(item["author"])
    by = item.get("subtitle")
    return str(by) if by else ""


def _artist_id(item: dict) -> Optional[str]:
    for a in item.get("artists") or []:
        if isinstance(a, dict) and a.get("id"):
            return a["id"]
    return None


def _album(item: dict) -> Optional[str]:
    alb = item.get("album")
    if isinstance(alb, dict):
        return alb.get("name")
    if isinstance(alb, str):
        return alb
    return None


def _album_id(item: dict) -> Optional[str]:
    alb = item.get("album")
    if isinstance(alb, dict):
        return alb.get("id")
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
        "artistId": _artist_id(item),
        "album": _album(item),
        "albumId": _album_id(item),
        "duration": _duration(item),
        "thumbnail": _thumbnail(item),
        # parsery ytmusicapi plní likeStatus u rádia, playlistů a knihovny;
        # u tracků alba ne → zůstane INDIFFERENT, dokud se neohodnotí
        "likeStatus": item.get("likeStatus") or "INDIFFERENT",
        # unikátní id položky V PLAYLISTU, bez něj nejde remove_playlist_items
        "setVideoId": item.get("setVideoId"),
    }


def _normalize_tracks(items: list[dict]) -> list[dict]:
    out = []
    for it in items or []:
        t = normalize_track(it)
        if t and it.get("isAvailable", True):
            out.append(t)
    return out


#: resultType z ytmusicapi → typ karty v našem UI
_RESULT_TYPES = {
    "song": "song",
    "video": "song",
    "album": "album",
    "ep": "album",
    "single": "album",
    "artist": "artist",
    "profile": "artist",
    "playlist": "playlist",
    "podcast": "playlist",
    "episode": "song",
}


def _playlist_id(it: dict) -> Optional[str]:
    pid = it.get("playlistId")
    if pid:
        return pid
    # hledání vrací u playlistů browseId ve tvaru "VL<playlistId>"
    bid = it.get("browseId")
    if isinstance(bid, str) and bid.startswith("VL"):
        return bid[2:]
    return bid


def _normalize_home_item(it: dict) -> Optional[dict]:
    """Home/hledání/související vrací heterogenní karty: song/playlist/album/artist."""
    kind = _RESULT_TYPES.get(str(it.get("resultType") or "").lower())
    if kind is None:
        # home karty resultType nemají → rozhodni podle přítomných klíčů
        if it.get("videoId"):
            kind = "song"
        elif it.get("playlistId"):
            kind = "playlist"
        elif it.get("browseId"):
            kind = "artist" if str(it["browseId"]).startswith("UC") else "album"
        else:
            return None

    if kind == "song":
        ident = it.get("videoId")
        subtitle = _artists(it)
    elif kind == "playlist":
        ident = _playlist_id(it)
        subtitle = _artists(it) or it.get("description") or "Playlist"
    elif kind == "artist":
        ident = it.get("browseId")
        # jméno je už v titulku — jako podtitulek dává smysl počet odběratelů
        subtitle = it.get("subscribers") or "Interpret"
    else:  # album
        ident = it.get("browseId")
        subtitle = _artists(it) or it.get("year") or "Album"
    if not ident:
        return None

    card = {
        "type": kind,
        "id": ident,
        "title": it.get("title") or it.get("artist") or "",
        "subtitle": str(subtitle or ""),
        "thumbnail": _thumbnail(it),
    }
    if it.get("category"):
        card["category"] = it["category"]
    return card


def _cards(items: list) -> list[dict]:
    out = []
    for it in items or []:
        # sekce "Související" mívají mezi kartami i holé texty (popis interpreta)
        if not isinstance(it, dict):
            continue
        card = _normalize_home_item(it)
        if card:
            out.append(card)
    return out


# --------------------------------------------------------------------------- #
# Klient                                                                       #
# --------------------------------------------------------------------------- #
class YTM:
    #: povolené hodnoty ?type= u /api/search → filtr ytmusicapi
    SEARCH_FILTERS = ("songs", "videos", "albums", "artists", "playlists",
                      "community_playlists", "featured_playlists",
                      "podcasts", "episodes")

    def __init__(self) -> None:
        auth = config.YTMUSIC_AUTH
        kwargs: dict[str, Any] = {
            "language": config.YTM_LANGUAGE,
            "location": config.YTM_LOCATION,
        }
        if auth and os.path.exists(auth):
            self.yt = YTMusic(auth, **kwargs)
            self.authenticated = True
            log.info("ytmusicapi: auth soubor %s načten", auth)
        else:
            self.yt = YTMusic(**kwargs)  # anonymní režim (search/radio funguje)
            self.authenticated = False
            log.warning(
                "ytmusicapi: auth soubor %s nenalezen — jedu anonymně "
                "(personalizace nebude fungovat)", auth,
            )
        self._auth_state: Optional[dict] = None
        self._auth_checked_at: float = 0.0

    # ---- Stav přihlášení ----------------------------------------------------
    @property
    def is_signed_in(self) -> bool:
        """Neblokující odhad — poslední známý stav, jinak přítomnost auth souboru."""
        if self._auth_state is not None:
            return bool(self._auth_state["authenticated"])
        return self.authenticated

    def _reload_client(self) -> None:
        """Znovu načte auth soubor — ať „Zkusit znovu“ v UI zabere hned po
        nahrání čerstvého browser.json, bez restartu služby."""
        auth = config.YTMUSIC_AUTH
        kwargs: dict[str, Any] = {
            "language": config.YTM_LANGUAGE,
            "location": config.YTM_LOCATION,
        }
        try:
            if auth and os.path.exists(auth):
                self.yt = YTMusic(auth, **kwargs)
                self.authenticated = True
            else:
                self.yt = YTMusic(**kwargs)
                self.authenticated = False
        except Exception as e:  # noqa: BLE001
            log.warning("ytmusicapi: znovunačtení auth souboru selhalo: %s", e)

    def apply_cookie(self, cookie: str) -> None:
        """Vymění cookie hlavičku živému klientovi — bez restartu, bez souboru.

        `YTMusic.base_headers` je cached_property vracející tentýž dict, ze kterého
        se skládá každý požadavek, takže stačí přepsat položku. `sapisid` ani
        `origin` se přepočítávat nemusí, ty se nemění (rotují jen *PSIDTS).
        """
        if not self.authenticated or not cookie:
            return
        try:
            self.yt._auth_headers["cookie"] = cookie  # noqa: SLF001
        except Exception as e:  # noqa: BLE001
            log.warning("ytmusicapi: výměna cookies za běhu selhala: %s", e)

    def invalidate_auth(self) -> None:
        """Zahodí cache stavu přihlášení — další check_auth() se zeptá znovu."""
        self._auth_state = None
        self._auth_checked_at = 0.0

    def check_auth(self, force: bool = False, reload: bool = False) -> dict:
        """Ověří session skutečným autentizovaným dotazem. BLOKUJE (síť).

        `reload` je jen pro ruční „Zkusit znovu“ z UI — tam uživatel nejspíš
        právě vyměnil přihlašovací soubor. Automatické ověření po selhaném
        volání klienta nepřestavuje, aby se při výpadku sítě nezahazovalo
        navázané spojení.
        """
        fresh = time.monotonic() - self._auth_checked_at < AUTH_TTL
        if self._auth_state is not None and fresh and not force:
            return self._auth_state

        if reload:
            self._reload_client()

        if not self.authenticated:
            state = {"authenticated": False, "account": None,
                     "reason": "Chybí soubor config/browser.json."}
        else:
            try:
                info = self.yt.get_account_info()
                state = {"authenticated": True,
                         "account": info.get("accountName"), "reason": None}
                log.info("ytmusicapi: přihlášeno jako %s", state["account"])
            except Exception as e:  # noqa: BLE001
                state = {
                    "authenticated": False, "account": None,
                    "reason": "Session vypršela — YouTube odpovídá jako nepřihlášenému.",
                }
                log.warning("ytmusicapi: ověření přihlášení selhalo (%s)", e)

        self._auth_state = state
        self._auth_checked_at = time.monotonic()
        return state

    # ---- Volání s obsluhou chyb ---------------------------------------------
    def _call(self, label: str, fn: Callable, *args: Any, default: Any = None,
              needs_auth: bool = True, **kwargs: Any) -> Any:
        """Zavolá ytmusicapi; při selhání odliší vypršelou session od prázdna."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            log.warning("%s selhalo: %s", label, e)
            if needs_auth and not self.check_auth(force=True)["authenticated"]:
                raise YTMAuthError(self._auth_state["reason"]) from e
            return default

    def _require_auth(self) -> None:
        if not self.check_auth()["authenticated"]:
            raise YTMAuthError(self._auth_state["reason"])

    # ---- Knihovna / personalizace (vyžaduje auth) ---------------------------
    def get_playlists(self) -> list[dict]:
        self._require_auth()
        res = self._call("get_library_playlists", self.yt.get_library_playlists,
                         limit=100, default=[]) or []
        out = []
        for p in res:
            if not p.get("playlistId"):
                continue
            out.append({
                "playlistId": p["playlistId"],
                "title": p.get("title") or "",
                "count": p.get("count"),
                "thumbnail": _thumbnail(p),
            })
        return out

    def get_liked(self) -> list[dict]:
        self._require_auth()
        res = self._call("get_liked_songs", self.yt.get_liked_songs,
                         limit=500, default={})
        return _normalize_tracks((res or {}).get("tracks", []))

    def get_library_songs(self) -> list[dict]:
        self._require_auth()
        res = self._call("get_library_songs", self.yt.get_library_songs,
                         limit=500, default=[])
        return _normalize_tracks(res or [])

    def get_library_albums(self) -> list[dict]:
        self._require_auth()
        res = self._call("get_library_albums", self.yt.get_library_albums,
                         limit=200, default=[]) or []
        return _cards([{**a, "resultType": "album"} for a in res])

    def get_library_artists(self) -> list[dict]:
        self._require_auth()
        res = self._call("get_library_artists", self.yt.get_library_artists,
                         limit=200, default=[]) or []
        return _cards([{**a, "resultType": "artist"} for a in res])

    def get_home(self) -> dict:
        """Bez přihlášení YouTube vrátí obecný feed místo For You — proto
        posíláme i příznak `personalized`, ať to UI může říct nahlas."""
        sections = self._call("get_home", self.yt.get_home, limit=6,
                              default=[], needs_auth=False) or []
        out = []
        for sec in sections:
            items = _cards(sec.get("contents") or [])
            if items:
                out.append({"title": sec.get("title") or "", "items": items})
        return {"personalized": self.is_signed_in, "sections": out}

    # ---- Obsah --------------------------------------------------------------
    def get_playlist(self, playlist_id: str) -> dict:
        # v anonymním režimu jsou dostupné jen veřejné playlisty — selhání tam
        # není chyba přihlášení, takže se nemá hlásit jako 401
        res = self._call(f"get_playlist({playlist_id})", self.yt.get_playlist,
                         playlist_id, limit=1000, default={},
                         needs_auth=self.authenticated) or {}
        return {
            "playlistId": playlist_id,
            "title": res.get("title") or "",
            "owned": bool(res.get("owned")),
            "count": res.get("trackCount") or res.get("count"),
            "thumbnail": _thumbnail(res),
            "tracks": _normalize_tracks(res.get("tracks", [])),
        }

    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        return self.get_playlist(playlist_id)["tracks"]

    def get_album(self, browse_id: str) -> dict:
        res = self._call(f"get_album({browse_id})", self.yt.get_album, browse_id,
                         default={}, needs_auth=False) or {}
        tracks = _normalize_tracks(res.get("tracks", []))
        cover = _thumbnail(res)
        for t in tracks:
            # album tracky občas nemají vlastní thumbnail → doplň obalem alba
            if not t.get("thumbnail"):
                t["thumbnail"] = cover
            if not t.get("albumId"):
                t["albumId"] = browse_id
        return {
            "browseId": browse_id,
            "title": res.get("title") or "",
            "artists": _artists(res),
            "artistId": _artist_id(res),
            "year": res.get("year"),
            "thumbnail": cover,
            "tracks": tracks,
        }

    def get_album_tracks(self, browse_id: str) -> list[dict]:
        return self.get_album(browse_id)["tracks"]

    def get_artist(self, browse_id: str) -> dict:
        res = self._call(f"get_artist({browse_id})", self.yt.get_artist, browse_id,
                         default={}, needs_auth=False) or {}

        def section(key: str) -> dict:
            sec = res.get(key) or {}
            return {
                "browseId": sec.get("browseId"),
                "params": sec.get("params"),
                "items": sec.get("results") or [],
            }

        songs, albums = section("songs"), section("albums")
        singles, related = section("singles"), section("related")
        return {
            "browseId": browse_id,
            "name": res.get("name") or "",
            "description": res.get("description"),
            "subscribers": res.get("subscribers"),
            "thumbnail": _thumbnail(res),
            "radioId": res.get("radioId"),
            "shuffleId": res.get("shuffleId"),
            "songsPlaylistId": songs["browseId"],
            "songs": _normalize_tracks(songs["items"]),
            "albums": _cards([{**a, "resultType": "album"} for a in albums["items"]]),
            "albumsParams": {"browseId": albums["browseId"], "params": albums["params"]},
            "singles": _cards([{**s, "resultType": "album"} for s in singles["items"]]),
            "singlesParams": {"browseId": singles["browseId"], "params": singles["params"]},
            "related": _cards([{**r, "resultType": "artist"} for r in related["items"]]),
        }

    def get_artist_albums(self, browse_id: str, params: str) -> list[dict]:
        res = self._call("get_artist_albums", self.yt.get_artist_albums, browse_id,
                         params, limit=100, default=[], needs_auth=False) or []
        return _cards([{**a, "resultType": "album"} for a in res])

    def get_song(self, video_id: str) -> dict:
        """Profil skladby: metadata z watch playlistu + sekce "Související"."""
        watch = self._call(f"get_watch_playlist({video_id})", self.yt.get_watch_playlist,
                           videoId=video_id, limit=1, default={}, needs_auth=False) or {}
        tracks = _normalize_tracks(watch.get("tracks", []))
        track = tracks[0] if tracks else {
            "videoId": video_id, "title": "", "artists": "",
            "likeStatus": "INDIFFERENT",
        }
        sections: list[dict] = []
        if watch.get("related"):
            raw = self._call("get_song_related", self.yt.get_song_related,
                             watch["related"], default=[], needs_auth=False) or []
            for sec in raw:
                items = _cards(sec.get("contents") or [])
                if items:
                    sections.append({"title": sec.get("title") or "", "items": items})
        return {"track": track, "sections": sections}

    def get_radio(self, video_id: str, limit: int = 50) -> list[dict]:
        """Algoritmem generovaná stanice (autoplay) seedovaná ze skladby."""
        res = self._call(f"get_watch_playlist({video_id})", self.yt.get_watch_playlist,
                         videoId=video_id, radio=True, limit=limit,
                         default={}, needs_auth=False)
        return _normalize_tracks((res or {}).get("tracks", []))

    def search(self, query: str, kind: Optional[str] = None) -> list[dict]:
        filt = kind if kind in self.SEARCH_FILTERS else None
        res = self._call(f"search({query})", self.yt.search, query, filter=filt,
                         limit=25, default=[], needs_auth=False)
        return _cards(res or [])

    def get_search_suggestions(self, query: str) -> list[str]:
        res = self._call("get_search_suggestions", self.yt.get_search_suggestions,
                         query, default=[], needs_auth=False) or []
        return [s for s in res if isinstance(s, str)]

    # ---- Zápisy (vždy vyžadují přihlášení) ----------------------------------
    def rate(self, video_id: str, status: str) -> bool:
        self._require_auth()
        try:
            self.yt.rate_song(video_id, status)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("rate_song(%s, %s) selhalo: %s", video_id, status, e)
            return False

    def create_playlist(self, title: str, description: str = "") -> Optional[str]:
        self._require_auth()
        try:
            res = self.yt.create_playlist(title, description, "PRIVATE")
        except Exception as e:  # noqa: BLE001
            log.warning("create_playlist(%s) selhalo: %s", title, e)
            return None
        return res if isinstance(res, str) else None

    def add_playlist_items(self, playlist_id: str, video_ids: list[str]) -> bool:
        self._require_auth()
        try:
            res = self.yt.add_playlist_items(playlist_id, video_ids, duplicates=True)
        except Exception as e:  # noqa: BLE001
            log.warning("add_playlist_items(%s) selhalo: %s", playlist_id, e)
            return False
        status = res.get("status") if isinstance(res, dict) else res
        return "SUCCEEDED" in str(status)

    def remove_playlist_items(self, playlist_id: str, items: list[dict]) -> bool:
        """`items` musí nést videoId i setVideoId (jinak to YouTube odmítne)."""
        self._require_auth()
        videos = [{"videoId": i["videoId"], "setVideoId": i["setVideoId"]}
                  for i in items if i.get("videoId") and i.get("setVideoId")]
        if not videos:
            return False
        try:
            res = self.yt.remove_playlist_items(playlist_id, videos)
        except Exception as e:  # noqa: BLE001
            log.warning("remove_playlist_items(%s) selhalo: %s", playlist_id, e)
            return False
        status = res.get("status") if isinstance(res, dict) else res
        return "SUCCEEDED" in str(status)
