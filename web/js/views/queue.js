"use strict";

import {API} from "../api.js";
import {button, el, empty, toast} from "../dom.js";
import {setTitle} from "../router.js";
import {store, subscribe} from "../store.js";
import {closeSheet, makeRow} from "../ui.js";

let mounted = null;   // element, do kterého se kreslí fronta

function render(box) {
    const {queue, index} = store.state;
    box.replaceChildren();

    const bar = el("div", "detail-actions");
    bar.append(
        button("🗑 Vyprázdnit", "ghost-btn", () =>
            API.queueClear(false).then(() => toast("Fronta vyprázdněna"))),
        button("✂ Nechat jen hrající", "ghost-btn", () =>
            API.queueClear(true).then(() => toast("Fronta oříznuta"))),
    );
    box.appendChild(bar);

    if (!queue.length) {
        box.appendChild(empty("Fronta je prázdná."));
        return;
    }

    const list = el("div", "list");
    queue.forEach((t, i) => {
        const row = makeRow(t, {
            onPlay: () => API.playIndex(i),
            onRemove: () => API.queueRemove(i),
            removeLabel: "🗑 Odebrat z fronty",
            extraActions: [
                i > 0 ? {label: "⬆ Posunout nahoru", run: () => API.queueMove(i, i - 1)} : null,
                i < queue.length - 1
                    ? {label: "⬇ Posunout dolů", run: () => API.queueMove(i, i + 1)}
                    : null,
            ].filter(Boolean),
        });
        if (i === index) row.classList.add("playing");
        list.appendChild(row);
    });
    box.appendChild(list);
}

/** Otisk fronty — slouží k poznání, že se posunuly indexy položek. */
function signature(state) {
    return `${state.index}|${(state.queue || []).map((t) => t.videoId).join(",")}`;
}

let lastSignature = "";

// Fronta žije ze stavu přes WebSocket — překresli ji, kdykoli se změní
// a je zrovna vidět.
subscribe((state, kind) => {
    if (kind !== "state") return;
    const sig = signature(state);
    const changed = sig !== lastSignature;
    lastSignature = sig;
    // Otevřené menu si drží index řádku z doby vykreslení. Když se fronta
    // mezitím přeskládá (jiný klient, doběhlá skladba), zavři ho — jinak by
    // „Odebrat“ nebo „Posunout“ sáhlo na cizí položku.
    if (changed) closeSheet();
    if (mounted && mounted.isConnected) render(mounted);
});

export const queueView = {
    async render(box) {
        setTitle("Fronta");
        mounted = box;
        render(box);
    },
    refresh(box) {
        setTitle("Fronta");
        mounted = box;
        render(box);
    },
};
