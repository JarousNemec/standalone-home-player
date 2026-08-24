"""Přehrávač postavený na mpv (libmpv přes python-mpv).

- Frontu (list track dictů) drží Python, mpv přehrává vždy jednu skladbu.
- Konec skladby detekujeme událostí 'end-file' (reason=EOF) → přejdeme na další.
- Autoplay: u konečné fronty (playlist/album) na konci naváže "radio" seedované
  z poslední skladby; u radio fronty se doplňuje průběžně před koncem.
- Stav se pushuje přes StateManager. Callbacky z mpv běží v jiném vlákně, proto
  se broadcast plánuje do event loopu přes call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import mpv

from . import config
from .state import StateManager
from .ytmusic import YTM

log = logging.getLogger("player")


def _yt_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


class Player:
    def __init__(self, ytm: YTM, state: StateManager) -> None:
        self.ytm = ytm
        self.state = state

        self.queue: list[dict] = []
        self.index: int = -1
        self.radio: bool = False        # nekonečná stanice (průběžné doplňování)
        self.auto_radio: bool = True     # na konci konečné fronty navázat stanicí

        self.volume: int = max(0, min(100, config.DEFAULT_VOLUME))
        self._position: float = 0.0
        self._duration: float = 0.0

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._advance_lock = asyncio.Lock()
        self._last_progress_sec: int = -1
        self._seed_id: Optional[str] = None  # z čeho se doplňuje stanice

        self.mpv = self._build_mpv()
        self._register_observers()

    # ------------------------------------------------------------------ setup
    def _build_mpv(self) -> "mpv.MPV":
        kwargs: dict[str, Any] = dict(
            ytdl=True,
            video=False,
            idle=True,
            ytdl_format="bestaudio/best",
        )
        if config.MPV_AO:
            kwargs["ao"] = config.MPV_AO
        if config.MPV_AUDIO_DEVICE:
            kwargs["audio_device"] = config.MPV_AUDIO_DEVICE
        if config.YTDLP_COOKIES and os.path.exists(config.YTDLP_COOKIES):
            # předá cookies do yt-dlp → Premium kvalita + soukromý obsah
            kwargs["ytdl_raw_options"] = f"cookies={config.YTDLP_COOKIES}"
            log.info("mpv: yt-dlp cookies %s", config.YTDLP_COOKIES)
        else:
            log.warning("mpv: cookies nenalezeny — nižší kvalita / bez Premium")

        m = mpv.MPV(log_handler=self._on_mpv_log, loglevel="warn", **kwargs)
        m.volume = self.volume
        return m

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _register_observers(self) -> None:
        self.mpv.observe_property("time-pos", self._on_time_pos)
        self.mpv.observe_property("duration", self._on_duration)
        self.mpv.observe_property("pause", self._on_pause)
        # Konec skladby přes událost 'end-file'. Property 'eof-reached' je
        # spolehlivá jen s keep-open=yes; s výchozím keep-open=no mpv soubor po
        # dohrání rovnou uvolní a observer se nezavolá → fronta se neposouvala.
        self.mpv.event_callback("end-file")(self._on_end_file)

    # -------------------------------------------------------------- observers
    # (běží v mpv vlákně → broadcast plánujeme přes _threadsafe)
    def _on_time_pos(self, _name: str, value: Any) -> None:
        if value is None:
            return
        self._position = float(value)
        sec = int(value)
        if sec != self._last_progress_sec:
            self._last_progress_sec = sec
            self._threadsafe(self._emit_progress())

    def _on_duration(self, _name: str, value: Any) -> None:
        self._duration = float(value or 0.0)

    def _on_pause(self, _name: str, value: Any) -> None:
        self._threadsafe(self._emit_state())

    def _on_end_file(self, event: Any) -> None:
        # Postoupíme jen když skladba přirozeně dohrála (EOF) nebo skončila
        # chybou (ERROR → přeskoč rozbitou skladbu). Ostatní důvody (ABORTED při
        # stopu / načtení další, REDIRECT, QUIT) ignorujeme — jinak by se fronta
        # posouvala dvakrát.
        try:
            reason = event.data.reason
        except AttributeError:
            return
        if reason == mpv.MpvEventEndFile.ERROR:
            track = self.current or {}
            log.warning(
                "Skladba selhala (mpv error %s) → přeskakuji: %s — %s",
                getattr(event.data, "error", "?"),
                track.get("artists", ""), track.get("title", ""),
            )
        if reason in (mpv.MpvEventEndFile.EOF, mpv.MpvEventEndFile.ERROR):
            self._threadsafe(self._advance(auto=True))

    def _on_mpv_log(self, level: str, prefix: str, text: str) -> None:
        # mpv/ytdl_hook hlásí chyby jen do svého logu; bez tohohle mostu
        # vypadá selhání streamu jako tiché přeskočení skladby.
        log.warning("mpv[%s/%s] %s", prefix, level, text.rstrip())

    def _threadsafe(self, coro) -> None:
        loop = self._loop
        if loop is None:
            coro.close()
            return
        loop.call_soon_threadsafe(lambda: asyncio.create_task(coro))

    # ------------------------------------------------------------- přehrávání
    def _load_current(self) -> None:
        track = self.current
        if not track:
            return
        self._position = 0.0
        self._duration = float(track.get("duration") or 0.0)
        self._last_progress_sec = -1
        self.mpv.pause = False
        self.mpv.play(_yt_url(track["videoId"]))
        log.info("▶ %s — %s", track.get("artists", ""), track.get("title", ""))

    async def play_tracks(
        self,
        tracks: list[dict],
        start: int = 0,
        radio: bool = False,
        auto_radio: bool = True,
        seed_id: Optional[str] = None,
    ) -> None:
        tracks = [t for t in tracks if t.get("videoId")]
        if not tracks:
            return
        self.queue = tracks
        self.index = max(0, min(start, len(tracks) - 1))
        self.radio = radio
        self.auto_radio = auto_radio
        self._seed_id = seed_id or (radio and tracks[0]["videoId"]) or None
        self._load_current()
        await self._emit_state()

    async def _advance(self, auto: bool = False) -> None:
        async with self._advance_lock:
            if not self.queue:
                return
            next_index = self.index + 1

            # doplnění stanice před koncem (radio režim)
            if self.radio and next_index >= len(self.queue) - config.RADIO_REFILL_THRESHOLD:
                await self._refill_radio()

            # konec konečné fronty → případně navázat autoradiem
            if next_index >= len(self.queue):
                if self.auto_radio and not self.radio:
                    seed = self.queue[self.index]["videoId"]
                    await self._start_radio_from(seed)
                    next_index = self.index + 1
                if next_index >= len(self.queue):
                    self._stop()
                    await self._emit_state()
                    return

            self.index = next_index
            self._load_current()
            await self._emit_state()

    async def _refill_radio(self) -> None:
        # seedujeme z POSLEDNÍ skladby fronty → čerstvá pokračování,
        # ne pořád stejný seznam z původního seedu
        seed = None
        if self.queue:
            seed = self.queue[-1].get("videoId")
        seed = seed or self._seed_id or (self.current or {}).get("videoId")
        if not seed:
            return
        more = await asyncio.to_thread(self.ytm.get_radio, seed)
        existing = {t["videoId"] for t in self.queue}
        added = [t for t in more if t["videoId"] not in existing]
        if added:
            self.queue.extend(added)
            log.info("Autoplay: doplněno %d skladeb do stanice", len(added))

    async def _start_radio_from(self, seed: str) -> None:
        tracks = await asyncio.to_thread(self.ytm.get_radio, seed)
        existing = {t["videoId"] for t in self.queue}
        added = [t for t in tracks if t["videoId"] not in existing]
        if added:
            self.queue.extend(added)
            self.radio = True
            self._seed_id = seed
            log.info("Fronta dohrála → navázána stanice (%d skladeb)", len(added))

    def _stop(self) -> None:
        try:
            self.mpv.command("stop")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- ovládání
    async def toggle_pause(self) -> None:
        self.mpv.pause = not bool(self.mpv.pause)
        # _on_pause observer odešle stav

    async def resume(self) -> None:
        self.mpv.pause = False

    async def pause(self) -> None:
        self.mpv.pause = True

    async def next(self) -> None:
        await self._advance(auto=False)

    async def prev(self) -> None:
        async with self._advance_lock:
            if self._position > 3 or self.index <= 0:
                # restart aktuální skladby
                self._load_current()
            else:
                self.index -= 1
                self._load_current()
            await self._emit_state()

    async def seek(self, pos: float) -> None:
        try:
            self.mpv.command("seek", pos, "absolute")
        except Exception as e:  # noqa: BLE001
            log.warning("seek selhal: %s", e)

    async def set_volume(self, level: int) -> None:
        self.volume = max(0, min(100, int(level)))
        self.mpv.volume = self.volume
        await self._emit_state()

    async def play_index(self, index: int) -> None:
        async with self._advance_lock:
            if 0 <= index < len(self.queue):
                self.index = index
                self._load_current()
                await self._emit_state()

    async def add_to_queue(self, track: dict) -> None:
        if track.get("videoId"):
            self.queue.append(track)
            if self.index < 0:  # nic nehraje → rovnou spusť
                self.index = len(self.queue) - 1
                self._load_current()
            await self._emit_state()

    # --------------------------------------------------------------- stav
    @property
    def current(self) -> Optional[dict]:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def snapshot(self) -> dict:
        cur = self.current
        try:
            paused = bool(self.mpv.pause)
        except Exception:  # noqa: BLE001
            paused = True
        return {
            "type": "state",
            "current": cur,
            "index": self.index,
            "queue": self.queue,
            "paused": paused,
            "playing": cur is not None and not paused,
            "volume": self.volume,
            "position": round(self._position, 1),
            "duration": round(self._duration, 1),
            "radio": self.radio,
        }

    async def _emit_state(self) -> None:
        await self.state.broadcast(self.snapshot())

    async def _emit_progress(self) -> None:
        await self.state.broadcast({
            "type": "progress",
            "position": round(self._position, 1),
            "duration": round(self._duration, 1),
        })

    def shutdown(self) -> None:
        try:
            self.mpv.terminate()
        except Exception:  # noqa: BLE001
            pass
