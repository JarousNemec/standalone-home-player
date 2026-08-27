"use strict";

import {API} from "../api.js";
import {button, el, empty} from "../dom.js";
import {setTitle} from "../router.js";
import {cardGrid, chips, makeRow} from "../ui.js";

const FILTERS = [
    {label: "Vše", value: ""},
    {label: "Skladby", value: "songs"},
    {label: "Videa", value: "videos"},
    {label: "Alba", value: "albums"},
    {label: "Interpreti", value: "artists"},
    {label: "Playlisty", value: "playlists"},
    {label: "Komunitní", value: "community_playlists"},
    {label: "Podcasty", value: "podcasts"},
];

let filter = "";
let query = "";

/** Skladby hraj jako seznam od kliknuté položky, aby zbytek výsledků následoval. */
function songRows(items) {
    const tracks = items.map((it) => ({
        videoId: it.id, title: it.title, artists: it.subtitle,
        thumbnail: it.thumbnail, likeStatus: "INDIFFERENT",
    }));
    const list = el("div", "list");
    tracks.forEach((t, i) => {
        list.appendChild(makeRow(t, {
            onPlay: () => API.play({source: "tracks", tracks, startIndex: i}),
        }));
    });
    return list;
}

function renderGroup(title, items) {
    const frag = document.createDocumentFragment();
    if (title) frag.appendChild(el("h2", "section-title", title));
    frag.appendChild(
        items.every((it) => it.type === "song") ? songRows(items) : cardGrid(items),
    );
    return frag;
}

// YouTube označí kategorií jen prvních pár výsledků (typicky „Top result“),
// u zbytku ji vynechá — dopočítáme ji z typu položky.
const TYPE_LABEL = {
    song: "Skladby", album: "Alba", artist: "Interpreti", playlist: "Playlisty",
};

function renderResults(box, items) {
    if (!items.length) {
        box.replaceChildren(empty("Nic nenalezeno."));
        return;
    }
    box.replaceChildren();
    if (filter) {
        box.appendChild(renderGroup("", items));
        return;
    }
    const groups = new Map();
    for (const it of items) {
        const key = it.category || TYPE_LABEL[it.type] || "Ostatní";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(it);
    }
    for (const [title, group] of groups) box.appendChild(renderGroup(title, group));
}

export const searchView = {
    async render(box) {
        setTitle("Hledat");
        box.replaceChildren();

        const form = el("form", "search-bar");
        const input = el("input", "");
        input.type = "search";
        input.placeholder = "Hledat skladby, alba, interprety…";
        input.autocomplete = "off";
        input.value = query;
        const submit = button("🔍", "");
        submit.type = "submit";
        form.append(input, submit);

        const results = el("div", "results");
        const filterBar = chips(FILTERS, filter, (value) => {
            filter = value;
            if (query) run();
        });

        async function run() {
            results.replaceChildren(empty("Hledám…"));
            try {
                renderResults(results, await API.search(query, filter));
            } catch (e) {
                results.replaceChildren(empty(`Chyba: ${e.message}`));
            }
        }

        form.addEventListener("submit", (e) => {
            e.preventDefault();
            query = input.value.trim();
            if (query) run();
        });

        box.append(form, filterBar, results);
        if (query) run();
        else results.replaceChildren(empty("Zadej, co chceš poslouchat."));
    },
};
