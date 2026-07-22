"""FastAPI aplikace — REST API, WebSocket a servírování webového UI."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .models import PlayRequest, QueueAddRequest
from .player import Player
from .state import StateManager
from .ytmusic import YTM

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ytm, player
    log.info("Spouštím YouTube Music přehrávač…")
    ytm = YTM()
    player = Player(ytm, state)
    player.attach_loop(asyncio.get_running_loop())
    log.info("Připraveno na portu %d (auth=%s)", config.PORT, ytm.authenticated)
    try:
        yield
    finally:
        player.shutdown()
        log.info("Vypnuto.")


app = FastAPI(title="Home YouTube Music Player", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Knihovna / obsah                                                             #
# --------------------------------------------------------------------------- #
@app.get("/api/home")
async def api_home():
    return await asyncio.to_thread(ytm.get_home)


@app.get("/api/playlists")
async def api_playlists():
    return await asyncio.to_thread(ytm.get_playlists)


@app.get("/api/playlist/{playlist_id}")
async def api_playlist(playlist_id: str):
    return await asyncio.to_thread(ytm.get_playlist_tracks, playlist_id)


@app.get("/api/album/{browse_id}")
async def api_album(browse_id: str):
    return await asyncio.to_thread(ytm.get_album_tracks, browse_id)


@app.get("/api/liked")
async def api_liked():
    return await asyncio.to_thread(ytm.get_liked)


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), type: str | None = None):
    return await asyncio.to_thread(ytm.search, q, type)


# --------------------------------------------------------------------------- #
# Přehrávání                                                                   #
# --------------------------------------------------------------------------- #
@app.post("/api/play")
async def api_play(req: PlayRequest):
    if req.source == "playlist":
        tracks = await asyncio.to_thread(ytm.get_playlist_tracks, req.id)
        await player.play_tracks(tracks, start=req.startIndex, radio=False, auto_radio=True)
    elif req.source == "album":
        tracks = await asyncio.to_thread(ytm.get_album_tracks, req.id)
        await player.play_tracks(tracks, start=req.startIndex, radio=False, auto_radio=True)
    else:  # "radio" nebo "song" → rovnou stanice ze seed videa
        tracks = await asyncio.to_thread(ytm.get_radio, req.id)
        await player.play_tracks(tracks, start=0, radio=True, auto_radio=True, seed_id=req.id)

    if not player.queue:
        raise HTTPException(status_code=404, detail="Nepodařilo se načíst žádné skladby.")
    return {"ok": True, "count": len(player.queue)}


@app.post("/api/queue/add")
async def api_queue_add(req: QueueAddRequest):
    await player.add_to_queue(req.model_dump())
    return {"ok": True}


@app.get("/api/queue")
async def api_queue():
    return {"queue": player.queue, "index": player.index}


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
