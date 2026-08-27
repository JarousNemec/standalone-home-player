"use strict";

// Jediné místo, kde se sahá na backend. Odpověď 401 znamená vypršelou session
// (viz YTMAuthError v app/ytmusic.py) → vystřelíme událost a UI ukáže banner.

export class ApiError extends Error {
    constructor(path, status, detail) {
        super(detail || `${path} → ${status}`);
        this.status = status;
        this.path = path;
    }
}

async function request(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
        let detail = "";
        try {
            detail = (await res.json()).detail || "";
        } catch {
            /* odpověď nemusí být JSON */
        }
        if (res.status === 401) {
            window.dispatchEvent(new CustomEvent("ytm-unauthorized", {detail}));
        }
        throw new ApiError(path, res.status, detail);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? res.json() : res.text();
}

const get = (path) => request(path);

const post = (path, body) =>
    request(path, {
        method: "POST",
        headers: body ? {"Content-Type": "application/json"} : {},
        body: body ? JSON.stringify(body) : undefined,
    });

const q = encodeURIComponent;

export const API = {
    // stav
    status: (refresh = false) => get(`/api/status${refresh ? "?refresh=true" : ""}`),
    now: () => get("/api/now"),

    // obsah
    home: () => get("/api/home"),
    playlists: () => get("/api/playlists"),
    playlist: (id) => get(`/api/playlist/${q(id)}`),
    album: (id) => get(`/api/album/${q(id)}`),
    artist: (id) => get(`/api/artist/${q(id)}`),
    artistAlbums: (id, params) => get(`/api/artist/${q(id)}/albums?params=${q(params)}`),
    song: (id) => get(`/api/song/${q(id)}`),
    liked: () => get("/api/liked"),
    librarySongs: () => get("/api/library/songs"),
    libraryAlbums: () => get("/api/library/albums"),
    libraryArtists: () => get("/api/library/artists"),
    search: (query, type) =>
        get(`/api/search?q=${q(query)}${type ? `&type=${q(type)}` : ""}`),
    suggestions: (query) => get(`/api/suggestions?q=${q(query)}`),

    // přehrávání
    play: (body) => post("/api/play", body),
    playIndex: (index) => post(`/api/play_index?index=${index}`),
    control: (action, qs = "") => post(`/api/control/${action}${qs}`),
    volume: (level) => post(`/api/volume?level=${level}`),
    mode: (mode) => post("/api/mode", mode),
    rate: (videoId, status) => post("/api/rate", {videoId, status}),

    // fronta
    queueAdd: (track, position = "end") => post("/api/queue/add", {...track, position}),
    queueRemove: (index) => post("/api/queue/remove", {index}),
    queueMove: (fromIndex, toIndex) => post("/api/queue/move", {fromIndex, toIndex}),
    queueClear: (keepCurrent = true) => post("/api/queue/clear", {keepCurrent}),

    // playlisty
    playlistCreate: (title, videoIds = []) =>
        post("/api/playlist/create", {title, description: "", videoIds}),
    playlistAdd: (id, items) => post(`/api/playlist/${q(id)}/add`, {items}),
    playlistRemove: (id, items) => post(`/api/playlist/${q(id)}/remove`, {items}),
};
