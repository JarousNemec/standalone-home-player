"use strict";

import {API} from "../api.js";
import {el, empty, toast} from "../dom.js";
import {setTitle} from "../router.js";
import {detailHeader, makeRow} from "../ui.js";

export const playlistView = {
    async render(box, {id}) {
        const pl = await API.playlist(id);
        setTitle(pl.title || "Playlist");
        box.replaceChildren();

        box.appendChild(detailHeader({
            thumbnail: pl.thumbnail,
            title: pl.title || "Playlist",
            subtitle: pl.count ? `${pl.count} skladeb` : `${pl.tracks.length} skladeb`,
            actions: [
                {
                    label: "▶ Přehrát vše", className: "play-all",
                    run: () => API.play({source: "playlist", id}),
                },
                {
                    label: "🔀 Přehrát náhodně",
                    run: () => API.play({source: "playlist", id, shuffle: true}),
                },
            ],
        }));

        if (!pl.tracks.length) {
            box.appendChild(empty("Playlist je prázdný."));
            return;
        }

        const list = el("div", "list");
        pl.tracks.forEach((t, i) => {
            list.appendChild(makeRow(t, {
                onPlay: () => API.play({source: "playlist", id, startIndex: i}),
                // odebírat jde jen z vlastního playlistu a jen když YouTube
                // poslalo setVideoId (bez něj to API odmítne)
                onRemove: pl.owned && t.setVideoId
                    ? async () => {
                        await API.playlistRemove(id, [t]);
                        toast("Odebráno z playlistu");
                        // překreslit celý detail: po odebrání se posunou indexy,
                        // ze kterých se skládá startIndex u ostatních řádků
                        await playlistView.render(box, {id});
                    }
                    : null,
                removeLabel: "🗑 Odebrat z playlistu",
            }));
        });
        box.appendChild(list);
    },
};
