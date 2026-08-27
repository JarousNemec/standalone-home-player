"use strict";

// Hash router. Záložky si drží vykreslený DOM (návrat zpět zachová i pozici
// scrollu a rozepsané hledání), detailní stránky se staví vždy znovu.

import {button, el, empty} from "./dom.js";

const TABS = ["home", "search", "library", "queue"];

const routes = [];          // {re, keys, view, tab}
const tabCache = new Map(); // tab -> {node, scroll}

let content = null;
let currentTab = "home";
let currentPath = "";

export function register(pattern, view, tab = null) {
    const keys = [];
    const re = new RegExp(
        "^" + pattern.replace(/:([a-zA-Z]+)/g, (_, k) => {
            keys.push(k);
            return "([^/]+)";
        }) + "$",
    );
    routes.push({re, keys, view, tab});
}

export function navigate(path, {replace = false} = {}) {
    const hash = "#" + path;
    if (location.hash === hash) return;
    if (replace) location.replace(hash);
    else location.hash = hash;
}

export const go = {
    tab: (name) => navigate("/" + name),
    playlist: (id) => navigate(`/playlist/${encodeURIComponent(id)}`),
    album: (id) => navigate(`/album/${encodeURIComponent(id)}`),
    artist: (id) => navigate(`/artist/${encodeURIComponent(id)}`),
    song: (id) => navigate(`/song/${encodeURIComponent(id)}`),
};

export function back() {
    if (history.length > 1) history.back();
    else navigate("/home", {replace: true});
}

export function setTitle(text) {
    document.getElementById("page-title").textContent = text;
}

function currentRoute() {
    const path = decodeURI(location.hash.slice(1)) || "/home";
    for (const r of routes) {
        const m = r.re.exec(path);
        if (!m) continue;
        const params = {};
        r.keys.forEach((k, i) => (params[k] = m[i + 1]));
        return {route: r, params, path};
    }
    return null;
}

function markTab(tab) {
    for (const btn of document.querySelectorAll(".tab")) {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    }
}

function show(node) {
    content.replaceChildren(node);
}

async function render() {
    const match = currentRoute();
    if (!match) {
        navigate("/home", {replace: true});
        return;
    }
    const {route, params, path} = match;

    // uložit scroll odcházející záložky
    if (TABS.includes(currentTab) && tabCache.has(currentTab) && currentPath === "/" + currentTab) {
        tabCache.get(currentTab).scroll = window.scrollY;
    }
    currentPath = path;

    const isTab = route.tab !== null;
    document.getElementById("btn-back").classList.toggle("hidden", isTab);
    markTab(isTab ? route.tab : currentTab);
    if (isTab) currentTab = route.tab;

    if (isTab && tabCache.has(route.tab)) {
        const cached = tabCache.get(route.tab);
        show(cached.node);
        route.view.refresh?.(cached.node);
        window.scrollTo(0, cached.scroll || 0);
        return;
    }

    const box = el("div", "page");
    show(box);
    box.append(empty("Načítám…"));

    try {
        await route.view.render(box, params);
        // cachuje se až úspěšné vykreslení — jinak by výpadek sítě zůstal
        // v záložce zamrzlý až do reloadu stránky
        if (isTab) tabCache.set(route.tab, {node: box, scroll: 0});
    } catch (e) {
        const message = e.status === 401
            ? "Tahle sekce potřebuje přihlášení k YouTube Music."
            : `Chyba: ${e.message}`;
        box.replaceChildren(empty(message), button("Zkusit znovu", "ghost-btn", render));
    }
    if (!isTab) window.scrollTo(0, 0);
}

/** Vyhodí uloženou záložku, takže se při dalším zobrazení načte znovu. */
export function invalidate(tab) {
    tabCache.delete(tab);
}

export function start(contentEl) {
    content = contentEl;
    window.addEventListener("hashchange", render);
    document.getElementById("btn-back").addEventListener("click", back);
    for (const btn of document.querySelectorAll(".tab")) {
        btn.addEventListener("click", () => go.tab(btn.dataset.tab));
    }
    if (!location.hash) navigate("/home", {replace: true});
    render();
}
