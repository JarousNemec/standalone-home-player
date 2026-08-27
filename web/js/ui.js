"use strict";

// Sdílené komponenty: dlaždice, řádek skladby, chipy, spodní menu a dialogy.

import {API} from "./api.js";
import {button, el, empty, fmtTime, thumb, toast} from "./dom.js";
import {go} from "./router.js";
import {store} from "./store.js";

export {empty, sectionTitle, toast} from "./dom.js";

// --------------------------------------------------------------------------
// Dlaždice (home / hledání / knihovna / související)
// --------------------------------------------------------------------------
export function openCard(item) {
    if (item.type === "song") {
        // bez zachycení by 401/502 zmizelo a klik by vypadal jako bez odezvy
        return API.play({source: "song", id: item.id}).catch((e) =>
            toast(e.status === 401 ? "Nejsi přihlášen." : `Chyba: ${e.message}`));
    }
    if (item.type === "album") return go.album(item.id);
    if (item.type === "playlist") return go.playlist(item.id);
    if (item.type === "artist") return go.artist(item.id);
}

export function makeCard(item) {
    const node = el("div", "card");
    node.append(
        thumb(item.thumbnail),
        el("div", "card-title", item.title),
        el("div", "card-sub", item.subtitle || ""),
    );
    if (item.type === "artist") node.classList.add("round");
    node.addEventListener("click", () => openCard(item));
    return node;
}

export function cardGrid(items, className = "cards") {
    const box = el("div", className);
    for (const it of items) box.appendChild(makeCard(it));
    return box;
}

export function section(title, items) {
    const frag = document.createDocumentFragment();
    if (title) frag.appendChild(el("h2", "section-title", title));
    frag.appendChild(cardGrid(items));
    return frag;
}

// --------------------------------------------------------------------------
// Řádek skladby
// --------------------------------------------------------------------------
/**
 * @param track  track dict z backendu
 * @param opts   {onPlay, extraActions, onRemove, removeLabel}
 */
export function makeRow(track, opts = {}) {
    const row = el("div", "row");
    row.dataset.vid = track.videoId || "";

    const meta = el("div", "row-meta");
    const title = el("div", "row-title link", track.title || "");
    title.addEventListener("click", (e) => {
        e.stopPropagation();
        if (track.videoId) go.song(track.videoId);
    });

    const sub = el("div", "row-sub");
    if (track.artists) {
        const artist = el("span", track.artistId ? "link" : "", track.artists);
        if (track.artistId) {
            artist.addEventListener("click", (e) => {
                e.stopPropagation();
                go.artist(track.artistId);
            });
        }
        sub.appendChild(artist);
    }
    meta.append(title, sub);

    const menu = button("⋮", "icon-btn row-menu", (e) => {
        e.stopPropagation();
        openTrackMenu(track, opts);
    });
    menu.title = "Další možnosti";

    row.append(
        thumb(track.thumbnail),
        meta,
        el("div", "row-dur", track.duration ? fmtTime(track.duration) : ""),
        menu,
    );
    if (opts.onPlay) row.addEventListener("click", () => opts.onPlay());
    return row;
}

export function trackList(tracks, makeOpts) {
    const list = el("div", "list");
    tracks.forEach((t, i) => list.appendChild(makeRow(t, makeOpts(t, i))));
    return list;
}

// --------------------------------------------------------------------------
// Hlavička detailu (playlist / album / interpret / skladba)
// --------------------------------------------------------------------------
/** @param opts {thumbnail, title, subtitle, meta, round, actions:[{label,className,run}]} */
export function detailHeader(opts) {
    const head = el("div", "detail-head");
    const cover = thumb(opts.thumbnail, "detail-cover" + (opts.round ? " round" : ""));
    const info = el("div", "detail-info");
    info.appendChild(el("h2", "detail-title", opts.title || ""));
    if (opts.subtitle) info.appendChild(el("div", "detail-sub", opts.subtitle));
    if (opts.meta) info.appendChild(el("div", "detail-meta", opts.meta));

    const actions = el("div", "detail-actions");
    for (const a of opts.actions || []) {
        if (!a) continue;
        actions.appendChild(button(a.label, a.className || "ghost-btn", async () => {
            try {
                await a.run();
            } catch (e) {
                toast(e.status === 401 ? "Nejsi přihlášen." : `Chyba: ${e.message}`);
            }
        }));
    }
    info.appendChild(actions);
    head.append(cover, info);
    return head;
}

// --------------------------------------------------------------------------
// Chipy (filtry)
// --------------------------------------------------------------------------
export function chips(options, active, onPick) {
    const box = el("div", "chips");
    for (const opt of options) {
        const b = button(opt.label, "chip", () => {
            if (b.classList.contains("active")) return;
            for (const c of box.children) c.classList.remove("active");
            b.classList.add("active");
            onPick(opt.value);
        });
        if (opt.value === active) b.classList.add("active");
        box.appendChild(b);
    }
    return box;
}

// --------------------------------------------------------------------------
// Spodní menu (bottom sheet) a dialogy
// --------------------------------------------------------------------------
export function closeSheet() {
    const root = document.getElementById("sheet-root");
    root.replaceChildren();
    document.body.classList.remove("sheet-open");
}

/** @param actions [{label, run, disabled}] — null položky se přeskočí */
export function openSheet(title, actions) {
    const root = document.getElementById("sheet-root");
    const overlay = el("div", "sheet-overlay");
    const sheet = el("div", "sheet");
    if (title) sheet.appendChild(el("div", "sheet-title", title));

    for (const action of actions) {
        if (!action) continue;
        const item = button(action.label, "sheet-item", async () => {
            closeSheet();
            try {
                await action.run();
            } catch (e) {
                toast(e.status === 401 ? "Nejsi přihlášen." : `Chyba: ${e.message}`);
            }
        });
        if (action.disabled) item.disabled = true;
        sheet.appendChild(item);
    }
    sheet.appendChild(button("Zavřít", "sheet-item cancel", closeSheet));

    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) closeSheet();
    });
    overlay.appendChild(sheet);
    root.replaceChildren(overlay);
    document.body.classList.add("sheet-open");
}

export function prompt(title, placeholder = "") {
    return new Promise((resolve) => {
        const root = document.getElementById("sheet-root");
        const overlay = el("div", "sheet-overlay");
        const form = el("form", "sheet dialog");
        form.appendChild(el("div", "sheet-title", title));

        const input = el("input", "dialog-input");
        input.type = "text";
        input.placeholder = placeholder;
        form.appendChild(input);

        const actions = el("div", "dialog-actions");
        actions.append(
            button("Zrušit", "ghost-btn", () => {
                closeSheet();
                resolve(null);
            }),
            button("Vytvořit", "play-all"),
        );
        actions.lastChild.type = "submit";
        form.appendChild(actions);

        form.addEventListener("submit", (e) => {
            e.preventDefault();
            const value = input.value.trim();
            closeSheet();
            resolve(value || null);
        });
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                closeSheet();
                resolve(null);
            }
        });
        overlay.appendChild(form);
        root.replaceChildren(overlay);
        document.body.classList.add("sheet-open");
        input.focus();
    });
}

// --------------------------------------------------------------------------
// Kontextové menu skladby
// --------------------------------------------------------------------------
async function addToPlaylist(track) {
    let playlists;
    try {
        playlists = await API.playlists();
    } catch (e) {
        toast(e.status === 401 ? "Nejsi přihlášen." : `Chyba: ${e.message}`);
        return;
    }
    const actions = playlists.map((p) => ({
        label: p.title,
        run: async () => {
            await API.playlistAdd(p.playlistId, [track]);
            toast(`Přidáno do „${p.title}“`);
        },
    }));
    actions.unshift({
        label: "➕ Nový playlist…",
        run: async () => {
            const title = await prompt("Název nového playlistu", "Můj playlist");
            if (!title) return;
            await API.playlistCreate(title, [track.videoId]);
            toast(`Playlist „${title}“ vytvořen`);
        },
    });
    openSheet("Přidat do playlistu", actions);
}

export function openTrackMenu(track, opts = {}) {
    const liked = track.likeStatus === "LIKE";
    const disliked = track.likeStatus === "DISLIKE";
    const canRate = store.state.canRate;

    const actions = [
        {
            label: "▶ Přehrát další",
            run: () => API.queueAdd(track, "next").then(() => toast("Přehraje se další")),
        },
        {
            label: "➕ Přidat do fronty",
            run: () => API.queueAdd(track, "end").then(() => toast("Přidáno do fronty")),
        },
        {
            label: "📻 Spustit rádio",
            run: () => API.play({source: "song", id: track.videoId}),
        },
        track.artistId
            ? {label: "👤 Přejít na interpreta", run: () => go.artist(track.artistId)}
            : null,
        track.albumId
            ? {label: "💿 Přejít na album", run: () => go.album(track.albumId)}
            : null,
        {
            label: liked ? "💔 Zrušit „líbí se mi“" : "👍 Líbí se mi",
            disabled: !canRate,
            run: () => API.rate(track.videoId, liked ? "INDIFFERENT" : "LIKE")
                .then(() => toast(liked ? "Hodnocení zrušeno" : "Přidáno do Liked")),
        },
        {
            label: disliked ? "🚫 Zrušit „nelíbí se mi“" : "👎 Nelíbí se mi",
            disabled: !canRate,
            run: () => API.rate(track.videoId, disliked ? "INDIFFERENT" : "DISLIKE")
                .then(() => toast(disliked ? "Hodnocení zrušeno" : "Uloženo")),
        },
        {
            label: "🎵 Přidat do playlistu…",
            disabled: !canRate,
            run: () => addToPlaylist(track),
        },
        ...(opts.extraActions || []),
        opts.onRemove
            ? {label: opts.removeLabel || "🗑 Odebrat", run: opts.onRemove}
            : null,
    ];
    openSheet(track.title || "Skladba", actions);
}
