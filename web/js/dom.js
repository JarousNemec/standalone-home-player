"use strict";

// Primitiva bez závislostí — smí je importovat kdokoli včetně routeru.
// Text se VŽDY vkládá přes textContent, nikdy přes innerHTML (obsah chodí
// z YouTube a nesmí se dostat do DOM jako HTML).

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const PLACEHOLDER =
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect width='80' height='80' fill='%2324242e'/%3E%3Ctext x='50%25' y='54%25' font-size='34' text-anchor='middle' fill='%239a9aa8'%3E%E2%99%AA%3C/text%3E%3C/svg%3E";

export function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
}

export function img(node, url) {
    node.src = url || PLACEHOLDER;
    node.onerror = () => {
        node.onerror = null;
        node.src = PLACEHOLDER;
    };
    return node;
}

export function thumb(url, className = "") {
    return img(el("img", className), url);
}

export function fmtTime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60);
    const s = String(sec % 60).padStart(2, "0");
    const h = Math.floor(m / 60);
    return h > 0 ? `${h}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export const empty = (text) => el("div", "empty", text);

export function sectionTitle(text) {
    return el("h2", "section-title", text);
}

export function button(label, className = "", onClick = null) {
    const b = el("button", className, label);
    if (onClick) b.addEventListener("click", onClick);
    return b;
}

let toastTimer = null;

export function toast(message) {
    let node = $("#toast");
    if (!node) {
        node = el("div", "toast");
        node.id = "toast";
        document.body.appendChild(node);
    }
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
}
