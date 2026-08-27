"use strict";

import {API} from "./api.js";
import {$} from "./dom.js";
import {initPlayer} from "./player.js";
import {invalidate, register, start} from "./router.js";
import {connect, patch} from "./store.js";
import {albumView} from "./views/album.js";
import {artistView} from "./views/artist.js";
import {homeView} from "./views/home.js";
import {libraryView} from "./views/library.js";
import {playlistView} from "./views/playlist.js";
import {queueView} from "./views/queue.js";
import {searchView} from "./views/search.js";
import {songView} from "./views/song.js";

// --------------------------------------------------------------------------
// Banner: neaktivní session
// --------------------------------------------------------------------------
let dismissed = false;

function showGate(reason) {
    if (dismissed) return;
    $("#gate-reason").textContent = reason || "";
    $("#auth-gate").classList.remove("hidden");
}

function hideGate() {
    $("#auth-gate").classList.add("hidden");
}

async function checkAuth(refresh = false) {
    try {
        const status = await API.status(refresh);
        patch({canRate: status.authenticated});
        if (status.authenticated) {
            dismissed = false;
            hideGate();
            // po obnovení přihlášení se personalizované záložky musí načíst znovu
            invalidate("home");
            invalidate("library");
        } else {
            showGate(status.reason);
        }
        return status.authenticated;
    } catch (e) {
        console.error("kontrola přihlášení selhala", e);
        return false;
    }
}

function initGate() {
    $("#gate-retry").addEventListener("click", async () => {
        const btn = $("#gate-retry");
        btn.disabled = true;
        btn.textContent = "Ověřuji…";
        await checkAuth(true);
        btn.disabled = false;
        btn.textContent = "Zkusit znovu";
    });
    $("#gate-dismiss").addEventListener("click", () => {
        dismissed = true;
        hideGate();
    });
    // 401 z jakéhokoli endpointu = session mezitím vypršela
    window.addEventListener("ytm-unauthorized", (e) => showGate(e.detail));
}

// --------------------------------------------------------------------------
// Start
// --------------------------------------------------------------------------
register("/home", homeView, "home");
register("/search", searchView, "search");
register("/library", libraryView, "library");
register("/queue", queueView, "queue");
register("/playlist/:id", playlistView);
register("/album/:id", albumView);
register("/artist/:id", artistView);
register("/song/:id", songView);

initGate();
initPlayer();
connect();
start($("#content"));
checkAuth();
