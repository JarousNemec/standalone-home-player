"use strict";

// Stav přehrávače držený serverem; sem přitéká přes WebSocket a rozesílá se
// odběratelům. Klient nikdy nic přes socket neposílá — ovládá se přes REST.

const subs = new Set();

export const store = {
    state: {
        queue: [], index: -1, current: null, paused: true, playing: false,
        volume: 100, position: 0, duration: 0, radio: false,
        shuffle: false, repeat: "off", autoRadio: true,
        likeStatus: "INDIFFERENT", canRate: false,
    },
    connected: false,
};

export function subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
}

function notify(kind) {
    for (const fn of subs) {
        try {
            fn(store.state, kind);
        } catch (e) {
            console.error("subscriber selhal", e);
        }
    }
}

/** Optimistický zápis, než dorazí potvrzení ze serveru (přepínače nesmí blikat). */
export function patch(partial) {
    Object.assign(store.state, partial);
    notify("state");
}

let ws = null;

export function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    // socket drž v lokální proměnné: pozdní událost ze starého spojení
    // nesmí sáhnout na to nové, které mezitím vzniklo při reconnectu
    const sock = new WebSocket(`${proto}://${location.host}/ws`);
    ws = sock;

    sock.onopen = () => {
        if (ws !== sock) return;
        store.connected = true;
        notify("conn");
    };
    sock.onclose = () => {
        if (ws !== sock) return;
        store.connected = false;
        notify("conn");
        setTimeout(connect, 2000);
    };
    sock.onerror = () => sock.close();
    sock.onmessage = (ev) => {
        if (ws !== sock) return;
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") {
            store.state = msg;
            notify("state");
        } else if (msg.type === "progress") {
            store.state.position = msg.position;
            store.state.duration = msg.duration;
            notify("progress");
        }
    };
}
