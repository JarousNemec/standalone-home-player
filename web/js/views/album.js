"use strict";

import {API} from "../api.js";
import {el, empty} from "../dom.js";
import {go, setTitle} from "../router.js";
import {detailHeader, makeRow} from "../ui.js";

export const albumView = {
    async render(box, {id}) {
        const album = await API.album(id);
        setTitle(album.title || "Album");
        box.replaceChildren();

        box.appendChild(detailHeader({
            thumbnail: album.thumbnail,
            title: album.title || "Album",
            subtitle: album.artists,
            meta: [album.year, `${album.tracks.length} skladeb`].filter(Boolean).join(" · "),
            actions: [
                {
                    label: "▶ Přehrát vše", className: "play-all",
                    run: () => API.play({source: "album", id}),
                },
                {
                    label: "🔀 Přehrát náhodně",
                    run: () => API.play({source: "album", id, shuffle: true}),
                },
                album.artistId
                    ? {label: "👤 Interpret", run: () => go.artist(album.artistId)}
                    : null,
            ],
        }));

        if (!album.tracks.length) {
            box.appendChild(empty("Album se nepodařilo načíst."));
            return;
        }

        const list = el("div", "list");
        album.tracks.forEach((t, i) => {
            list.appendChild(makeRow(t, {
                onPlay: () => API.play({source: "album", id, startIndex: i}),
            }));
        });
        box.appendChild(list);
    },
};
