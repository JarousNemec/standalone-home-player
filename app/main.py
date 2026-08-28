"""FastAPI aplikace — REST API, WebSocket a servírování webového UI."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .models import (
    ModeRequest,
    PlaylistCreateRequest,
    PlaylistItemsRequest,
    PlayRequest,
    QueueAddRequest,
    QueueClearRequest,
    QueueIndexRequest,
    QueueMoveRequest,
    RateRequest,
)
from .player import Player
from .session import CookieRotator
from .state import StateManager
from .ytmusic import YTM, YTMAuthError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("main")

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

# globální singletony (nastaveny v lifespan)
state = StateManager()
ytm: YTM
player: Player
rotator: CookieRotator


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ytm, player, rotator
    log.info("Spouštím YouTube Music přehrávač…")
    ytm = YTM()
    # rotátor musí vyrobit cookies dřív, než si na ně mpv v konstruktoru sáhne
    rotator = CookieRotator(config.YTMUSIC_AUTH, config.YTDLP_COOKIES, ytm,
                            enabled=config.SESSION_ROTATE,
                            check_interval=config.SESSION_CHECK_INTERVAL,
                            max_token_age=config.SESSION_MAX_TOKEN_AGE)
    rotator.sync_cookie_file()
    player = Player(ytm, state)
    player.attach_loop(asyncio.get_running_loop())
    # ověření session na pozadí — ať je v logu hned vidět, jestli jsme přihlášeni.
    # Referenci držíme, jinak může úlohy sebrat garbage collector.
    auth_probe = asyncio.create_task(asyncio.to_thread(ytm.check_auth, True))
    rotate_task = asyncio.create_task(rotator.run())
    log.info("Připraveno na portu %d", config.PORT)
    try:
        yield
    finally:
        rotate_task.cancel()
        auth_probe.cancel()
        player.shutdown()
        log.info("Vypnuto.")


app = FastAPI(title="Home YouTube Music Player", lifespan=lifespan)


@app.exception_handler(YTMAuthError)
async def _auth_error_handler(request: Request, exc: YTMAuthError) -> JSONResponse:
    """Vypršelá session ≠ prázdný obsah — UI podle 401 vyvolá banner."""
    return JSONResponse(status_code=401, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Stav přihlášení                                                              #
# --------------------------------------------------------------------------- #
@app.get("/api/status")
async def api_status(refresh: bool = False):
    # ruční ověření z UI zároveň znovu načte browser.json, ať „Zkusit znovu“
    # zabere hned po jeho výměně a nemusí se restartovat kontejner
    if refresh:
        await asyncio.to_thread(rotator.reseed)
        rotator.sync_cookie_file()
    auth = await asyncio.to_thread(ytm.check_auth, refresh, refresh)
    return {**auth, "rotation": rotator.status()}


# --------------------------------------------------------------------------- #
# Knihovna / obsah                                                             #
# --------------------------------------------------------------------------- #
@app.get("/api/home")
async def api_home():
    return await asyncio.to_thread(ytm.get_home)


@app.get("/api/playlists")
async def api_playlists():
    return await asyncio.to_thread(ytm.get_playlists)


@app.get("/api/liked")
async def api_liked():
    return await asyncio.to_thread(ytm.get_liked)


@app.get("/api/library/songs")
async def api_library_songs():
    return await asyncio.to_thread(ytm.get_library_songs)


@app.get("/api/library/albums")
async def api_library_albums():
    return await asyncio.to_thread(ytm.get_library_albums)


@app.get("/api/library/artists")
async def api_library_artists():
    return await asyncio.to_thread(ytm.get_library_artists)


@app.get("/api/album/{browse_id}")
async def api_album(browse_id: str):
    return await asyncio.to_thread(ytm.get_album, browse_id)


@app.get("/api/artist/{browse_id}")
async def api_artist(browse_id: str):
    return await asyncio.to_thread(ytm.get_artist, browse_id)


@app.get("/api/artist/{browse_id}/albums")
async def api_artist_albums(browse_id: str, params: str = Query(...)):
    return await asyncio.to_thread(ytm.get_artist_albums, browse_id, params)


@app.get("/api/song/{video_id}")
async def api_song(video_id: str):
    return await asyncio.to_thread(ytm.get_song, video_id)


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), type: str | None = None):
    return await asyncio.to_thread(ytm.search, q, type)


@app.get("/api/suggestions")
async def api_suggestions(q: str = Query(..., min_length=1)):
    return await asyncio.to_thread(ytm.get_search_suggestions, q)


# --------------------------------------------------------------------------- #
# Playlisty — zápisy                                                           #
# (musí být PŘED /api/playlist/{playlist_id}, jinak by "create" bylo id)        #
# --------------------------------------------------------------------------- #
@app.post("/api/playlist/create")
async def api_playlist_create(req: PlaylistCreateRequest):
    pid = await asyncio.to_thread(ytm.create_playlist, req.title, req.description)
    if not pid:
        raise HTTPException(status_code=502, detail="Playlist se nepodařilo vytvořit.")
    added = True
    if req.videoIds:
        added = await asyncio.to_thread(ytm.add_playlist_items, pid, req.videoIds)
    # playlist vznikl, ale skladby se do něj nedostaly → ať to klient neschová
    return {"ok": True, "playlistId": pid, "itemsAdded": bool(added)}


@app.post("/api/playlist/{playlist_id}/add")
async def api_playlist_add(playlist_id: str, req: PlaylistItemsRequest):
    ids = [i.videoId for i in req.items if i.videoId]
    ok = await asyncio.to_thread(ytm.add_playlist_items, playlist_id, ids)
    if not ok:
        raise HTTPException(status_code=502, detail="Přidání do playlistu selhalo.")
    return {"ok": True, "count": len(ids)}


@app.post("/api/playlist/{playlist_id}/remove")
async def api_playlist_remove(playlist_id: str, req: PlaylistItemsRequest):
    items = [i.model_dump() for i in req.items]
    ok = await asyncio.to_thread(ytm.remove_playlist_items, playlist_id, items)
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Odebrání selhalo — playlist musí být tvůj vlastní.",
        )
    return {"ok": True}


@app.get("/api/playlist/{playlist_id}")
async def api_playlist(playlist_id: str):
    return await asyncio.to_thread(ytm.get_playlist, playlist_id)


# --------------------------------------------------------------------------- #
# Přehrávání                                                                   #
# --------------------------------------------------------------------------- #
async def _tracks_for(req: PlayRequest) -> list[dict]:
    if req.source == "playlist":
        return await asyncio.to_thread(ytm.get_playlist_tracks, req.id)
    if req.source == "album":
        return await asyncio.to_thread(ytm.get_album_tracks, req.id)
    if req.source == "liked":
        return await asyncio.to_thread(ytm.get_liked)
    if req.source == "library":
        return await asyncio.to_thread(ytm.get_library_songs)
    if req.source == "tracks":
        return [t.model_dump() for t in (req.tracks or [])]
    return []


@app.post("/api/play")
async def api_play(req: PlayRequest):
    # "radio"/"song" = rovnou stanice ze seed videa (nekonečné doplňování)
    radio = req.source in ("radio", "song")
    if radio:
        tracks = await asyncio.to_thread(ytm.get_radio, req.id)
    else:
        tracks = await _tracks_for(req)

    # kontrolovat načtené skladby, ne frontu — jinak by se selhání schovalo
    # za to, co hrálo předtím, a klient by dostal falešné "ok"
    if not tracks:
        raise HTTPException(status_code=404, detail="Nepodařilo se načíst žádné skladby.")

    await player.play_tracks(
        tracks,
        start=0 if radio else req.startIndex,
        radio=radio,
        auto_radio=True,
        seed_id=req.id if radio else None,
        shuffle=req.shuffle,
    )
    return {"ok": True, "count": len(player.queue)}


@app.get("/api/queue")
async def api_queue():
    return {"queue": player.queue, "index": player.index}


@app.post("/api/queue/add")
async def api_queue_add(req: QueueAddRequest):
    track = req.model_dump()
    position = track.pop("position", "end")
    await player.add_to_queue(track, position)
    return {"ok": True}


@app.post("/api/queue/remove")
async def api_queue_remove(req: QueueIndexRequest):
    await player.remove_at(req.index)
    return {"ok": True}


@app.post("/api/queue/move")
async def api_queue_move(req: QueueMoveRequest):
    await player.move_item(req.fromIndex, req.toIndex)
    return {"ok": True}


@app.post("/api/queue/clear")
async def api_queue_clear(req: QueueClearRequest):
    await player.clear_queue(req.keepCurrent)
    return {"ok": True}


@app.post("/api/mode")
async def api_mode(req: ModeRequest):
    await player.set_mode(shuffle=req.shuffle, repeat=req.repeat,
                          auto_radio=req.autoRadio)
    return {"ok": True}


@app.post("/api/rate")
async def api_rate(req: RateRequest):
    video_id = req.videoId or (player.current or {}).get("videoId")
    if not video_id:
        raise HTTPException(status_code=400, detail="Není co hodnotit.")
    ok = await player.rate(video_id, req.status)
    if not ok:
        raise HTTPException(status_code=502, detail="Hodnocení se nepodařilo uložit.")
    return {"ok": True, "videoId": video_id, "likeStatus": req.status}


@app.post("/api/control/{action}")
async def api_control(action: str, pos: float | None = None):
    actions = {
        "pause": player.pause,
        "resume": player.resume,
        "toggle": player.toggle_pause,
        "next": player.next,
        "prev": player.prev,
    }
    if action == "seek":
        if pos is None:
            raise HTTPException(status_code=400, detail="Chybí ?pos=")
        await player.seek(pos)
    elif action in actions:
        await actions[action]()
    else:
        raise HTTPException(status_code=400, detail=f"Neznámá akce: {action}")
    return {"ok": True}


@app.post("/api/play_index")
async def api_play_index(index: int = Query(...)):
    await player.play_index(index)
    return {"ok": True}


@app.post("/api/volume")
async def api_volume(level: int = Query(..., ge=0, le=100)):
    await player.set_volume(level)
    return {"ok": True}


@app.get("/api/now")
async def api_now():
    return player.snapshot()


# --------------------------------------------------------------------------- #
# WebSocket — push stavu                                                       #
# --------------------------------------------------------------------------- #
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await state.connect(ws)
    await state.send_to(ws, player.snapshot())  # iniciální stav
    try:
        while True:
            await ws.receive_text()  # klient jen naslouchá; drží spojení
    except WebSocketDisconnect:
        state.disconnect(ws)
    except Exception:  # noqa: BLE001
        state.disconnect(ws)


# --------------------------------------------------------------------------- #
# Statické UI (mount až nakonec, ať nepřebije /api a /ws)                       #
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
