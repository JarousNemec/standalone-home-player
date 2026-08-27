"use strict";

import {API} from "../api.js";
import {button, el, empty} from "../dom.js";
import {setTitle} from "../router.js";
import {cardGrid, detailHeader, makeRow, toast} from "../ui.js";

/** Interpreta pouštíme z jeho playlistu top skladeb; když chybí, ze seznamu. */
function playBody(artist, shuffle) {
    if (artist.songsPlaylistId) {
        return {source: "playlist", id: artist.songsPlaylistId, shuffle};
    }
    return {source: "tracks", tracks: artist.songs, shuffle};
}

function albumSection(title, items, params) {
    if (!items.length) return null;
    const frag = document.createDocumentFragment();
    const head = el("div", "section-head");
    head.appendChild(el("h2", "section-title", title));
    if (params?.browseId && params?.params) {
        const grid = el("div", "cards");
        head.appendChild(button("Zobrazit vše", "ghost-btn small", async () => {
            try {
                const all = await API.artistAlbums(params.browseId, params.params);
                grid.replaceChildren(...cardGrid(all).childNodes);
            } catch (e) {
                toast(`Nepodařilo se načíst všechna alba: ${e.message}`);
            }
        }));
        frag.append(head, grid);
        grid.replaceChildren(...cardGrid(items).childNodes);
        return frag;
    }
    frag.append(head, cardGrid(items));
    return frag;
}

export const artistView = {
    async render(box, {id}) {
        const artist = await API.artist(id);
        setTitle(artist.name || "Interpret");
        box.replaceChildren();

        box.appendChild(detailHeader({
            thumbnail: artist.thumbnail,
            title: artist.name || "Interpret",
            subtitle: artist.subscribers ? `${artist.subscribers} odběratelů` : "",
            round: true,
            actions: [
                artist.songs.length
                    ? {
                        label: "▶ Přehrát", className: "play-all",
                        run: () => API.play(playBody(artist, false)),
                    }
                    : null,
                artist.songs.length
                    ? {label: "🔀 Zamíchat", run: () => API.play(playBody(artist, true))}
                    : null,
                artist.songs.length
                    ? {
                        label: "📻 Rádio",
                        run: () => API.play({source: "song", id: artist.songs[0].videoId}),
                    }
                    : null,
            ],
        }));

        if (artist.songs.length) {
            box.appendChild(el("h2", "section-title", "Nejlepší skladby"));
            const list = el("div", "list");
            artist.songs.forEach((t, i) => {
                list.appendChild(makeRow(t, {
                    onPlay: () => API.play({
                        source: "tracks", tracks: artist.songs, startIndex: i,
                    }),
                }));
            });
            box.appendChild(list);
        }

        const albums = albumSection("Alba", artist.albums, artist.albumsParams);
        if (albums) box.appendChild(albums);
        const singles = albumSection("Singly", artist.singles, artist.singlesParams);
        if (singles) box.appendChild(singles);

        if (artist.related.length) {
            box.appendChild(el("h2", "section-title", "Fanoušci mají rádi také"));
            box.appendChild(cardGrid(artist.related));
        }

        if (artist.description) {
            box.appendChild(el("h2", "section-title", "O interpretovi"));
            box.appendChild(el("p", "description", artist.description));
        }

        if (!artist.name && !artist.songs.length) {
            box.appendChild(empty("Interpreta se nepodařilo načíst."));
        }
    },
};
