"use strict";

// Spodní lišta „právě hraje“ — jediné místo, které sahá na ovládací prvky.

import {API} from "./api.js";
import {$, $$, fmtTime, img, toast} from "./dom.js";
import {go} from "./router.js";
import {patch, store, subscribe} from "./store.js";

const REPEAT_NEXT = {off: "all", all: "one", one: "off"};
const REPEAT_ICON = {off: "🔁", all: "🔁", one: "🔂"};
const REPEAT_TITLE = {
    off: "Opakování vypnuto",
    all: "Opakovat frontu",
    one: "Opakovat skladbu",
};

let seeking = false;
let volTimer = null;

export function initPlayer() {
    const bar = $("#player-bar");
    const elThumb = $("#np-thumb"), elTitle = $("#np-title"), elArtist = $("#np-artist");
    const elRadio = $("#np-radio"), elCur = $("#np-cur"), elDur = $("#np-dur");
    const elSeek = $("#np-seek"), elVol = $("#np-vol"), elPlay = $("#btn-play");
    const elShuffle = $("#btn-shuffle"), elRepeat = $("#btn-repeat"), elLike = $("#btn-like");

    function updateProgress(pos, dur) {
        elCur.textContent = fmtTime(pos);
        elDur.textContent = fmtTime(dur);
        if (!seeking) {
            elSeek.max = Math.max(1, Math.floor(dur || 1));
            elSeek.value = Math.floor(pos || 0);
        }
    }

    function applyState(s) {
        const cur = s.current;
        bar.classList.toggle("hidden", !cur);
        elShuffle.classList.toggle("on", !!s.shuffle);
        elRepeat.textContent = REPEAT_ICON[s.repeat] || "🔁";
        elRepeat.classList.toggle("on", s.repeat !== "off");
        elRepeat.title = REPEAT_TITLE[s.repeat] || REPEAT_TITLE.off;
        if (!cur) return;

        img(elThumb, cur.thumbnail);
        elTitle.textContent = cur.title || "—";
        elArtist.textContent = cur.artists || "";
        elArtist.classList.toggle("link", !!cur.artistId);
        elRadio.classList.toggle("hidden", !s.radio);
        elPlay.textContent = s.paused ? "▶" : "⏸";
        elVol.value = s.volume ?? 100;

        const liked = (s.likeStatus || cur.likeStatus) === "LIKE";
        elLike.textContent = liked ? "♥" : "♡";
        elLike.classList.toggle("on", liked);
        elLike.classList.toggle("hidden", !s.canRate);

        updateProgress(s.position, s.duration);
        // zvýraznit hrající řádek ve viditelných seznamech
        for (const r of $$(".row")) {
            r.classList.toggle("playing", r.dataset.vid === cur.videoId);
        }
    }

    subscribe((s, kind) => {
        if (kind === "progress") updateProgress(s.position, s.duration);
        else if (kind === "conn") {
            $("#conn").className = "conn " + (store.connected ? "online" : "offline");
        } else applyState(s);
    });

    // --- ovládání ---
    elPlay.addEventListener("click", () => API.control("toggle"));
    $("#btn-next").addEventListener("click", () => API.control("next"));
    $("#btn-prev").addEventListener("click", () => API.control("prev"));

    elShuffle.addEventListener("click", () => {
        const on = !store.state.shuffle;
        patch({shuffle: on});                     // ať přepínač nebliká
        API.mode({shuffle: on}).catch((e) => toast(`Chyba: ${e.message}`));
    });

    elRepeat.addEventListener("click", () => {
        const mode = REPEAT_NEXT[store.state.repeat] || "all";
        patch({repeat: mode});
        API.mode({repeat: mode}).catch((e) => toast(`Chyba: ${e.message}`));
    });

    elLike.addEventListener("click", async () => {
        const cur = store.state.current;
        if (!cur) return;
        const liked = (store.state.likeStatus || cur.likeStatus) === "LIKE";
        const next = liked ? "INDIFFERENT" : "LIKE";
        patch({likeStatus: next});
        try {
            await API.rate(cur.videoId, next);
            toast(liked ? "Hodnocení zrušeno" : "Přidáno do Liked");
        } catch (e) {
            patch({likeStatus: liked ? "LIKE" : "INDIFFERENT"});
            toast(e.status === 401 ? "Nejsi přihlášen." : `Chyba: ${e.message}`);
        }
    });

    elTitle.addEventListener("click", () => {
        const cur = store.state.current;
        if (cur?.videoId) go.song(cur.videoId);
    });
    elArtist.addEventListener("click", () => {
        const cur = store.state.current;
        if (cur?.artistId) go.artist(cur.artistId);
    });

    elSeek.addEventListener("input", () => {
        seeking = true;
        elCur.textContent = fmtTime(elSeek.value);
    });
    elSeek.addEventListener("change", () => {
        API.control("seek", `?pos=${elSeek.value}`);
        seeking = false;
    });

    elVol.addEventListener("input", () => {
        clearTimeout(volTimer);
        volTimer = setTimeout(() => API.volume(elVol.value), 120);
    });
}
