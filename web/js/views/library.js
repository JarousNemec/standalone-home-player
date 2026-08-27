"use strict";

import {API} from "../api.js";
import {el, empty} from "../dom.js";
import {setTitle} from "../router.js";
import {cardGrid, chips, makeCard, makeRow} from "../ui.js";

const SECTIONS = [
    {label: "Playlisty", value: "playlists"},
    {label: "Liked", value: "liked"},
    {label: "Skladby", value: "songs"},
    {label: "Alba", value: "albums"},
    {label: "Interpreti", value: "artists"},
];

let active = "playlists";

/** Kliknutí na skladbu spustí CELÝ seznam od té pozice (jako v YT Music). */
function songList(tracks, source) {
    if (!tracks.length) return empty("Zatím je tu prázdno.");
    const list = el("div", "list");
    tracks.forEach((t, i) => {
        list.appendChild(makeRow(t, {
            onPlay: () => API.play({source, startIndex: i}),
        }));
    });
    return list;
}

async function load(kind) {
    if (kind === "playlists") {
        const pls = await API.playlists();
        if (!pls.length) return empty("Žádné playlisty.");
        const grid = el("div", "grid");
        for (const p of pls) {
            grid.appendChild(makeCard({
                type: "playlist", id: p.playlistId, title: p.title,
                subtitle: p.count ? `${p.count} skladeb` : "Playlist",
                thumbnail: p.thumbnail,
            }));
        }
        return grid;
    }
    if (kind === "liked") return songList(await API.liked(), "liked");
    if (kind === "songs") return songList(await API.librarySongs(), "library");
    if (kind === "albums") {
        const items = await API.libraryAlbums();
        return items.length ? cardGrid(items, "grid") : empty("Žádná alba.");
    }
    const items = await API.libraryArtists();
    return items.length ? cardGrid(items, "grid") : empty("Žádní interpreti.");
}

export const libraryView = {
    async render(box) {
        setTitle("Knihovna");
        box.replaceChildren();
        const content = el("div", "results");

        async function show(kind) {
            active = kind;
            content.replaceChildren(empty("Načítám…"));
            try {
                content.replaceChildren(await load(kind));
            } catch (e) {
                content.replaceChildren(empty(
                    e.status === 401
                        ? "Knihovna potřebuje přihlášení k YouTube Music."
                        : `Chyba: ${e.message}`,
                ));
            }
        }

        box.append(chips(SECTIONS, active, show), content);
        await show(active);
    },
};

