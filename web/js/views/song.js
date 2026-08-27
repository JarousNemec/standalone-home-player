"use strict";

import {API} from "../api.js";
import {empty, fmtTime, toast} from "../dom.js";
import {go, setTitle} from "../router.js";
import {detailHeader, section} from "../ui.js";
import {store} from "../store.js";

export const songView = {
    async render(box, {id}) {
        const {track, sections} = await API.song(id);
        setTitle(track.title || "Skladba");
        box.replaceChildren();

        const liked = track.likeStatus === "LIKE";
        const meta = [track.album, track.duration ? fmtTime(track.duration) : null]
            .filter(Boolean).join(" · ");

        box.appendChild(detailHeader({
            thumbnail: track.thumbnail,
            title: track.title || "Skladba",
            subtitle: track.artists,
            meta,
            actions: [
                {
                    label: "▶ Přehrát", className: "play-all",
                    run: () => API.play({source: "tracks", tracks: [track]}),
                },
                {
                    label: "⏭ Přehrát další",
                    run: () => API.queueAdd(track, "next").then(() => toast("Přehraje se další")),
                },
                {
                    label: "➕ Do fronty",
                    run: () => API.queueAdd(track, "end").then(() => toast("Přidáno do fronty")),
                },
                {label: "📻 Rádio", run: () => API.play({source: "song", id})},
                store.state.canRate
                    ? {
                        label: liked ? "♥ Líbí se mi" : "♡ Líbí se mi",
                        run: async () => {
                            await API.rate(id, liked ? "INDIFFERENT" : "LIKE");
                            toast(liked ? "Hodnocení zrušeno" : "Přidáno do Liked");
                            songView.render(box, {id});
                        },
                    }
                    : null,
                track.artistId
                    ? {label: "👤 Interpret", run: () => go.artist(track.artistId)}
                    : null,
                track.albumId
                    ? {label: "💿 Album", run: () => go.album(track.albumId)}
                    : null,
            ],
        }));

        if (!sections.length) {
            box.appendChild(empty("Pro tuhle skladbu nemá YouTube žádná doporučení."));
            return;
        }
        for (const sec of sections) box.appendChild(section(sec.title, sec.items));
    },
};

