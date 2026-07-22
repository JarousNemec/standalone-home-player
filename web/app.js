"use strict";

// --------------------------------------------------------------------------
// Pomocné
// --------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect width='80' height='80' fill='%2324242e'/%3E%3Ctext x='50%25' y='54%25' font-size='34' text-anchor='middle' fill='%239a9aa8'%3E%E2%99%AA%3C/text%3E%3C/svg%3E";

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60);
  const s = String(sec % 60).padStart(2, "0");
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
}

function img(el, url) {
  el.src = url || PLACEHOLDER;
  el.onerror = () => { el.onerror = null; el.src = PLACEHOLDER; };
}

// --------------------------------------------------------------------------
// Přehrávání (akce)
// --------------------------------------------------------------------------
const play = (source, id, startIndex = 0) =>
  post("/api/play", { source, id, startIndex }).catch((e) => alert("Chyba: " + e.message));

const control = (action, qs = "") => post(`/api/control/${action}${qs}`);

// --------------------------------------------------------------------------
// Taby
// --------------------------------------------------------------------------
const loaded = {};
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const name = tab.dataset.tab;
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === name));
    ensureLoaded(name);
  });
});

function ensureLoaded(name) {
  if (name === "queue") { renderQueue(); return; } // vždy čerstvá
  if (loaded[name]) return;
  loaded[name] = true;
  if (name === "home") loadHome();
  if (name === "playlists") loadPlaylists();
  if (name === "liked") loadLiked();
}

// --------------------------------------------------------------------------
// HOME
// --------------------------------------------------------------------------
async function loadHome() {
  const box = $("#home-sections");
  box.innerHTML = '<div class="empty">Načítám…</div>';
  try {
    const sections = await api("/api/home");
    if (!sections.length) { box.innerHTML = '<div class="empty">Nic tu není. Přihlášen? (viz README)</div>'; return; }
    box.innerHTML = "";
    for (const sec of sections) {
      const h = document.createElement("h2");
      h.className = "section-title";
      h.textContent = sec.title;
      box.appendChild(h);
      const cards = document.createElement("div");
      cards.className = "cards";
      for (const it of sec.items) cards.appendChild(makeCard(it));
      box.appendChild(cards);
    }
  } catch (e) {
    box.innerHTML = `<div class="empty">Chyba: ${e.message}</div>`;
  }
}

function makeCard(it) {
  const el = document.createElement("div");
  el.className = "card";
  const im = document.createElement("img");
  img(im, it.thumbnail);
  const t = document.createElement("div");
  t.className = "card-title"; t.textContent = it.title;
  const s = document.createElement("div");
  s.className = "card-sub"; s.textContent = it.subtitle || "";
  el.append(im, t, s);
  el.addEventListener("click", () => onItemClick(it));
  return el;
}

function onItemClick(it) {
  if (it.type === "song") return play("song", it.id);
  if (it.type === "album") return openAlbum(it.id, it.title);
  if (it.type === "playlist") return openPlaylist(it.id, it.title);
  // artist zatím neřešíme
}

// --------------------------------------------------------------------------
// PLAYLISTS
// --------------------------------------------------------------------------
async function loadPlaylists() {
  const grid = $("#playlist-grid");
  grid.innerHTML = '<div class="empty">Načítám…</div>';
  try {
    const pls = await api("/api/playlists");
    if (!pls.length) { grid.innerHTML = '<div class="empty">Žádné playlisty. Přihlášen? (viz README)</div>'; return; }
    grid.innerHTML = "";
    for (const p of pls) {
      grid.appendChild(makeCard({
        type: "playlist", id: p.playlistId, title: p.title,
        subtitle: p.count ? `${p.count} skladeb` : "Playlist", thumbnail: p.thumbnail,
      }));
    }
  } catch (e) {
    grid.innerHTML = `<div class="empty">Chyba: ${e.message}</div>`;
  }
}

async function openPlaylist(id, title) {
  openDetail(title, () => api(`/api/playlist/${id}`), (i) => play("playlist", id, i), () => play("playlist", id, 0));
}
async function openAlbum(id, title) {
  openDetail(title, () => api(`/api/album/${id}`), null, () => play("album", id, 0));
  // pro album spouštíme přes source album; klik na řádek → od indexu
  detailPlayRow = (i) => play("album", id, i);
}

let detailPlayRow = null;

async function openDetail(title, fetcher, rowPlay, playAll) {
  switchTab("playlists");
  const grid = $("#playlist-grid");
  const detail = $("#playlist-detail");
  grid.classList.add("hidden");
  detail.classList.remove("hidden");
  detail.innerHTML = '<div class="empty">Načítám…</div>';
  detailPlayRow = rowPlay;
  try {
    const tracks = await fetcher();
    detail.innerHTML = "";
    const back = document.createElement("button");
    back.className = "back-btn"; back.textContent = "← Zpět";
    back.onclick = () => { detail.classList.add("hidden"); grid.classList.remove("hidden"); };
    const h = document.createElement("h2"); h.textContent = title;
    const actions = document.createElement("div"); actions.className = "detail-actions";
    const pa = document.createElement("button"); pa.className = "play-all";
    pa.textContent = "▶ Přehrát vše"; pa.onclick = playAll;
    actions.appendChild(pa);
    const list = document.createElement("div"); list.className = "list";
    tracks.forEach((t, i) => list.appendChild(makeRow(t, () => (detailPlayRow || (() => {}))(i))));
    detail.append(back, h, actions, list);
  } catch (e) {
    detail.innerHTML = `<div class="empty">Chyba: ${e.message}</div>`;
  }
}

// --------------------------------------------------------------------------
// SEARCH
// --------------------------------------------------------------------------
$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#search-input").value.trim();
  if (!q) return;
  const box = $("#search-results");
  box.innerHTML = '<div class="empty">Hledám…</div>';
  try {
    const results = await api(`/api/search?q=${encodeURIComponent(q)}`);
    if (!results.length) { box.innerHTML = '<div class="empty">Nic nenalezeno.</div>'; return; }
    box.innerHTML = "";
    for (const it of results) box.appendChild(makeResultRow(it));
  } catch (err) {
    box.innerHTML = `<div class="empty">Chyba: ${err.message}</div>`;
  }
});

function makeResultRow(it) {
  const row = document.createElement("div");
  row.className = "row";
  const im = document.createElement("img"); img(im, it.thumbnail);
  const meta = document.createElement("div"); meta.className = "row-meta";
  const t = document.createElement("div"); t.className = "row-title"; t.textContent = it.title;
  const s = document.createElement("div"); s.className = "row-sub";
  const label = { song: "Skladba", album: "Album", playlist: "Playlist", artist: "Interpret" }[it.type] || "";
  s.textContent = (it.subtitle ? it.subtitle + " · " : "") + label;
  meta.append(t, s);
  row.append(im, meta);
  row.addEventListener("click", () => onItemClick(it));
  return row;
}

// --------------------------------------------------------------------------
// LIKED
// --------------------------------------------------------------------------
async function loadLiked() {
  const box = $("#liked-list");
  box.innerHTML = '<div class="empty">Načítám…</div>';
  try {
    const tracks = await api("/api/liked");
    if (!tracks.length) { box.innerHTML = '<div class="empty">Žádné oblíbené. Přihlášen? (viz README)</div>'; return; }
    box.innerHTML = "";
    // liked jako stanice od kliknuté skladby (autoplay)
    tracks.forEach((t) => box.appendChild(makeRow(t, () => play("song", t.videoId))));
  } catch (e) {
    box.innerHTML = `<div class="empty">Chyba: ${e.message}</div>`;
  }
}

// --------------------------------------------------------------------------
// QUEUE
// --------------------------------------------------------------------------
function renderQueue() {
  const box = $("#queue-list");
  const q = lastState.queue || [];
  if (!q.length) { box.innerHTML = '<div class="empty">Fronta je prázdná.</div>'; return; }
  box.innerHTML = "";
  q.forEach((t, i) => {
    const row = makeRow(t, () => post(`/api/play_index?index=${i}`));
    if (i === lastState.index) row.classList.add("playing");
    box.appendChild(row);
  });
}

// --------------------------------------------------------------------------
// Track row (společné)
// --------------------------------------------------------------------------
function makeRow(t, onClick) {
  const row = document.createElement("div");
  row.className = "row";
  row.dataset.vid = t.videoId;
  const im = document.createElement("img"); img(im, t.thumbnail);
  const meta = document.createElement("div"); meta.className = "row-meta";
  const title = document.createElement("div"); title.className = "row-title"; title.textContent = t.title;
  const sub = document.createElement("div"); sub.className = "row-sub"; sub.textContent = t.artists || "";
  meta.append(title, sub);
  const dur = document.createElement("div"); dur.className = "row-dur";
  dur.textContent = t.duration ? fmtTime(t.duration) : "";
  row.append(im, meta, dur);
  row.addEventListener("click", onClick);
  return row;
}

function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === name));
  ensureLoaded(name);
}

// --------------------------------------------------------------------------
// Player bar + WebSocket
// --------------------------------------------------------------------------
let lastState = { queue: [], index: -1 };
let seeking = false;

const bar = $("#player-bar");
const elThumb = $("#np-thumb"), elTitle = $("#np-title"), elArtist = $("#np-artist");
const elRadio = $("#np-radio"), elCur = $("#np-cur"), elDur = $("#np-dur");
const elSeek = $("#np-seek"), elVol = $("#np-vol"), elPlay = $("#btn-play");

function applyState(s) {
  lastState = s;
  const cur = s.current;
  if (!cur) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  img(elThumb, cur.thumbnail);
  elTitle.textContent = cur.title || "—";
  elArtist.textContent = cur.artists || "";
  elRadio.classList.toggle("hidden", !s.radio);
  elPlay.textContent = s.paused ? "▶" : "⏸";
  elVol.value = s.volume ?? 100;
  updateProgress(s.position, s.duration);
  // zvýraznit hrající řádek ve viditelných seznamech
  $$(".row").forEach((r) => r.classList.toggle("playing", r.dataset.vid === cur.videoId));
  if ($('.view[data-view="queue"]').classList.contains("active")) renderQueue();
}

function updateProgress(pos, dur) {
  elCur.textContent = fmtTime(pos);
  elDur.textContent = fmtTime(dur);
  if (!seeking) {
    elSeek.max = Math.max(1, Math.floor(dur || 1));
    elSeek.value = Math.floor(pos || 0);
  }
}

// ovládání
elPlay.addEventListener("click", () => control("toggle"));
$("#btn-next").addEventListener("click", () => control("next"));
$("#btn-prev").addEventListener("click", () => control("prev"));

elSeek.addEventListener("input", () => { seeking = true; elCur.textContent = fmtTime(elSeek.value); });
elSeek.addEventListener("change", () => { control("seek", `?pos=${elSeek.value}`); seeking = false; });

let volTimer = null;
elVol.addEventListener("input", () => {
  clearTimeout(volTimer);
  volTimer = setTimeout(() => post(`/api/volume?level=${elVol.value}`), 120);
});

// WebSocket
let ws = null;
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => $("#conn").className = "conn online";
  ws.onclose = () => { $("#conn").className = "conn offline"; setTimeout(connectWS, 2000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") applyState(msg);
    else if (msg.type === "progress") { lastState.position = msg.position; lastState.duration = msg.duration; updateProgress(msg.position, msg.duration); }
  };
}

// start
connectWS();
ensureLoaded("home");
