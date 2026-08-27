"""Přehrávač postavený na mpv (libmpv přes python-mpv).

- Frontu (list track dictů) drží Python, mpv přehrává vždy jednu skladbu.
- Konec skladby detekujeme událostí 'end-file' (reason=EOF) → přejdeme na další.
- Autoplay: u konečné fronty (playlist/album) na konci naváže "radio" seedované
  z poslední skladby; u radio fronty se doplňuje průběžně před koncem.
- Stav se pushuje přes StateManager. Callbacky z mpv běží v jiném vlákně, proto
  se broadcast plánuje do event loopu přes call_soon_threadsafe.

SHUFFLE: `self.queue` je vždy POŘADÍ PŘEHRÁVÁNÍ (to je veřejný kontrakt vůči
WebSocketu i /api/play_index). Původní pořadí se při zapnutí shufflu odloží do
`self._original`, který drží TYTÉŽ objekty dictů, jen v jiném pořadí.

    INVARIANT: jakmile je track dict ve frontě, nikdo ho nekopíruje.
    Všechna dohledání proto jdou přes identitu (`_pos`), ne přes videoId —
    playlist smí obsahovat tutéž skladbu vícekrát.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Optional

import mpv

from . import config
from .state import StateManager
from .ytmusic import YTM

log = logging.getLogger("player")

#: strop pro síťové dotazy držené pod _advance_lock (viz H3 v plánu)
FETCH_TIMEOUT = 15.0

#: kolik skladeb smí selhat po sobě, než se přehrávání vzdá. Bez toho by
#: repeat="all" nad frontou, která se nedá načíst (vypršelé cookies), skákal
#: donekonečna na začátek a tloukl do YouTube.
MAX_CONSECUTIVE_ERRORS = 5


def _yt_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


def _pos(seq: list[dict], track: Optional[dict]) -> int:
    """Pozice konkrétního objektu v seznamu (identita, ne rovnost). -1 = není tam."""
    if track is None:
        return -1
    for i, t in enumerate(seq):
        if t is track:
            return i
    return -1


class Player:
    def __init__(self, ytm: YTM, state: StateManager) -> None:
        self.ytm = ytm
        self.state = state

        self.queue: list[dict] = []      # pořadí přehrávání
        self.index: int = -1
        self.radio: bool = False         # nekonečná stanice (průběžné doplňování)
        self.auto_radio: bool = True     # na konci konečné fronty navázat stanicí

        self.shuffle: bool = False
        self.repeat: str = "off"         # "off" | "all" | "one"
        self._original: Optional[list[dict]] = None   # None ⟺ shuffle vypnutý

        self.volume: int = max(0, min(100, config.DEFAULT_VOLUME))
        self._position: float = 0.0
        self._duration: float = 0.0

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._advance_lock = asyncio.Lock()
        self._last_progress_sec: int = -1
        self._seed_id: Optional[str] = None  # z čeho se doplňuje stanice
        self._error_streak: int = 0          # kolik skladeb selhalo po sobě

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
        if value > 0:
            self._error_streak = 0   # něco se opravdu přehrálo
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
        if reason == mpv.MpvEventEndFile.EOF:
            self._threadsafe(self._advance(auto=True))
        elif reason == mpv.MpvEventEndFile.ERROR:
            track = self.current or {}
            log.warning(
                "Skladba selhala (mpv error %s) → přeskakuji: %s — %s",
                getattr(event.data, "error", "?"),
                track.get("artists", ""), track.get("title", ""),
            )
            self._error_streak += 1
            # auto=True kvůli ochraně před zastaralou událostí, ale bez
            # repeat="one" — rozbitá skladba se nesmí opakovat donekonečna
            self._threadsafe(self._advance(auto=True, allow_repeat_one=False))

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
        shuffle: bool = False,
    ) -> None:
        tracks = [t for t in tracks if t.get("videoId")]
        if not tracks:
            return
        async with self._advance_lock:
            if shuffle:
                # "Přehrát náhodně": zamíchá se celý seznam a jede se od začátku
                self._original = list(tracks)
                tracks = list(tracks)
                random.shuffle(tracks)
                self.shuffle = True
                start = 0
            else:
                self._original = None
                self.shuffle = False
            self.queue = tracks
            self.index = max(0, min(start, len(tracks) - 1))
            self._error_streak = 0
            self.radio = radio
            self.auto_radio = auto_radio
            self._seed_id = seed_id or (radio and tracks[0]["videoId"]) or None
            self._load_current()
            await self._emit_state()

    async def _advance(self, auto: bool = False, allow_repeat_one: bool = True) -> None:
        # Zachyceno PŘED zámkem: doplnění stanice uvnitř drží zámek i sekundy
        # a fronta se mezitím může posunout → zastaralý EOF nesmí přeskočit dál.
        token = (self.index, id(self.current))

        async with self._advance_lock:
            if not self.queue:
                return
            if auto and token != (self.index, id(self.current)):
                return  # zastaralá událost, mezitím se už posunulo jinde

            if self._error_streak >= MAX_CONSECUTIVE_ERRORS:
                # počítadlo se schválně nenuluje — vynuluje ho až skutečné
                # přehrávání nebo ruční zásah (⏭, klik do fronty, nová fronta),
                # jinak by každá další chybová událost rozjela cyklus znovu
                log.error(
                    "Po sobě selhalo %d skladeb → zastavuji. Zkontroluj "
                    "config/cookies.txt a aktuálnost yt-dlp.", self._error_streak,
                )
                self._stop()
                await self._emit_state()
                return

            # repeat="one" platí jen pro přirozený konec; ⏭/⏮ uživatele ho obchází
            if self.repeat == "one" and auto and allow_repeat_one and self.current is not None:
                self._load_current()
                await self._emit_state()
                return

            next_index = self.index + 1

            # doplnění stanice před koncem (radio režim) — může frontu prodloužit,
            # proto běží ještě před kontrolou konce
            if self.radio and next_index >= len(self.queue) - config.RADIO_REFILL_THRESHOLD:
                await self._refill_radio()

            if next_index < len(self.queue):
                self.index = next_index
                self._load_current()
                await self._emit_state()
                return

            # --- konec fronty ---
            # repeat="all" má přednost před autoradiem (uživatel si smyčku vyžádal)
            if self.repeat == "all":
                if self.shuffle:
                    random.shuffle(self.queue)  # nový náhodný průchod
                self.index = 0
                self._load_current()
                await self._emit_state()
                return

            # konec konečné fronty → případně navázat autoradiem
            if self.auto_radio and not self.radio:
                seed = self.queue[self.index]["videoId"]
                await self._start_radio_from(seed)
                if self.index + 1 < len(self.queue):
                    self.index += 1
                    self._load_current()
                    await self._emit_state()
                    return

            self._stop()
            await self._emit_state()

    async def _fetch_radio(self, seed: str) -> list[dict]:
        """Stáhne stanici s časovým stropem — zámek nesmí viset na síti donekonečna."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.ytm.get_radio, seed), timeout=FETCH_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("Doplnění stanice trvalo přes %.0f s → přeskakuji", FETCH_TIMEOUT)
            return []
        except Exception as e:  # noqa: BLE001
            log.warning("Doplnění stanice selhalo: %s", e)
            return []

    def _extend(self, tracks: list[dict]) -> list[dict]:
        """Přidá nové skladby do fronty i do původního pořadí (tytéž objekty)."""
        existing = {t["videoId"] for t in self.queue}
        added = [t for t in tracks if t["videoId"] not in existing]
        if added:
            self.queue.extend(added)
            if self._original is not None:
                # nové skladby se nemíchají — stanice je už algoritmicky seřazená
                self._original.extend(added)
        return added

    async def _refill_radio(self) -> None:
        # seedujeme z POSLEDNÍ skladby fronty → čerstvá pokračování,
        # ne pořád stejný seznam z původního seedu
        seed = None
        if self.queue:
            seed = self.queue[-1].get("videoId")
        seed = seed or self._seed_id or (self.current or {}).get("videoId")
        if not seed:
            return
        added = self._extend(await self._fetch_radio(seed))
        if added:
            log.info("Autoplay: doplněno %d skladeb do stanice", len(added))

    async def _start_radio_from(self, seed: str) -> None:
        added = self._extend(await self._fetch_radio(seed))
        if added:
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
        self._error_streak = 0
        await self._advance(auto=False)

    async def prev(self) -> None:
        async with self._advance_lock:
            if not self.queue:
                return
            if self._position > 3 or (self.index <= 0 and self.repeat != "all"):
                # restart aktuální skladby
                self._load_current()
            else:
                self.index = self.index - 1 if self.index > 0 else len(self.queue) - 1
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
                self._error_streak = 0
                self.index = index
                self._load_current()
                await self._emit_state()

    # --------------------------------------------------------- režimy
    async def set_mode(
        self,
        shuffle: Optional[bool] = None,
        repeat: Optional[str] = None,
        auto_radio: Optional[bool] = None,
    ) -> None:
        async with self._advance_lock:
            if repeat in ("off", "all", "one"):
                self.repeat = repeat
            if auto_radio is not None:
                self.auto_radio = bool(auto_radio)
            if shuffle is not None and bool(shuffle) != self.shuffle:
                self._apply_shuffle(bool(shuffle))
            await self._emit_state()

    def _apply_shuffle(self, on: bool) -> None:
        """Přepne pořadí fronty. Nikdy nevolá _load_current() — skladba hraje dál."""
        current = self.current
        if on:
            self._original = list(self.queue)
            tail = self.queue[self.index + 1:]
            random.shuffle(tail)
            self.queue[self.index + 1:] = tail
            self.shuffle = True
        else:
            if self._original is not None:
                self.queue = list(self._original)
            self._original = None
            self.shuffle = False
            found = _pos(self.queue, current)
            if found < 0 and current is not None:
                log.warning("Obnova pořadí: hrající skladba ve frontě nenalezena")
            self.index = found if found >= 0 else min(self.index, len(self.queue) - 1)

    # --------------------------------------------------------- mutace fronty
    async def add_to_queue(self, track: dict, position: str = "end") -> None:
        if not track.get("videoId"):
            return
        async with self._advance_lock:
            if position == "next" and self.index >= 0:
                self.queue.insert(self.index + 1, track)
                if self._original is not None:
                    # přilepí se za aktuální skladbu i v původním pořadí, aby
                    # po vypnutí shufflu zůstala hned za ní (jako v YT Music)
                    self._original.insert(_pos(self._original, self.current) + 1, track)
            else:
                self.queue.append(track)
                if self._original is not None:
                    self._original.append(track)
            if self.index < 0:  # nic nehraje → rovnou spusť
                self.index = len(self.queue) - 1
                self._load_current()
            await self._emit_state()

    async def remove_at(self, index: int) -> None:
        async with self._advance_lock:
            if not (0 <= index < len(self.queue)):
                return
            track = self.queue.pop(index)
            if self._original is not None:
                orig = _pos(self._original, track)
                if orig >= 0:
                    self._original.pop(orig)

            if not self.queue:
                self.index = -1
                self._stop()
            elif index < self.index:
                self.index -= 1
            elif index == self.index:
                # další skladba se posunula do uvolněného slotu → chová se
                # jako přeskočení; na konci fronty buď wrap, nebo stop
                if self.index >= len(self.queue):
                    if self.repeat == "all":
                        self.index = 0
                    else:
                        self.index = len(self.queue) - 1
                        self._stop()
                        await self._emit_state()
                        return
                self._load_current()
            await self._emit_state()

    async def move_item(self, src: int, dst: int) -> None:
        async with self._advance_lock:
            if not (0 <= src < len(self.queue)) or src == dst:
                return
            current = self.current
            track = self.queue.pop(src)
            dst = max(0, min(dst, len(self.queue)))
            self.queue.insert(dst, track)
            if self._original is not None:
                orig = _pos(self._original, track)
                if orig >= 0:
                    self._original.pop(orig)
                anchor = self.queue[dst - 1] if dst > 0 else None
                at = _pos(self._original, anchor) + 1 if anchor is not None else 0
                self._original.insert(at, track)
            # index dopočítat z identity — pokrývá všechny tři případy naráz
            found = _pos(self.queue, current)
            if found >= 0:
                self.index = found
            await self._emit_state()

    async def clear_queue(self, keep_current: bool = True) -> None:
        async with self._advance_lock:
            current = self.current
            if keep_current and current is not None:
                self.queue = [current]
                self._original = [current] if self._original is not None else None
                self.index = 0
            else:
                self.queue = []
                self._original = None
                self.index = -1
                self._stop()
            await self._emit_state()

    # --------------------------------------------------------------- hodnocení
    async def rate(self, video_id: str, status: str) -> bool:
        """Zámek nepotřebuje — nemění pořadí ani index, jen obsah dictů."""
        ok = await asyncio.to_thread(self.ytm.rate, video_id, status)
        if ok:
            seen: set[int] = set()
            for seq in (self.queue, self._original or []):
                for t in seq:
                    if t.get("videoId") == video_id and id(t) not in seen:
                        seen.add(id(t))
                        t["likeStatus"] = status
            await self._emit_state()
        return ok

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
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "autoRadio": self.auto_radio,
            "likeStatus": (cur or {}).get("likeStatus", "INDIFFERENT"),
            "canRate": self.ytm.is_signed_in,
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
