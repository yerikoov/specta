// App entry: landing (signed out) → dashboard (signed in) → thought chain → chat.
// Vanilla ES modules, no build step. The dashboard sidebar stays on screen around the chain and the chat.
import { api } from "./api.js";
import { initAuth, requireAuth } from "./auth.js";
import { initGaze, setFavicon } from "./blobs.js";
import { runChain } from "./chain.js";
import { createChat } from "./chat.js";
import { PRODUCT_NAME } from "./config.js";
import { createDashboard } from "./dashboard.js";
import { filesModalOpen, pickFiles } from "./filesmodal.js";
import { applyI18n, t } from "./i18n.js";
import { hydrateIcons } from "./icons.js";
import { renderLanding } from "./landing.js";
import { openTrace } from "./trace.js";
import { notify } from "./notify.js";

const $ = (id) => document.getElementById(id);
let agentsById = {}, chat = null, busy = false, dash = null;

const toast = (msg, type = "info") => notify(msg, { type });

function show(id) {
  const cur = document.querySelector(".screen.is-active");
  const next = $(id);
  if (cur === next) return Promise.resolve();
  return new Promise((res) => {
    if (cur) {
      cur.classList.add("is-leaving");
      cur.classList.remove("is-active");
      setTimeout(() => { cur.classList.remove("is-leaving"); next.classList.add("is-active"); window.scrollTo(0, 0); res(); }, 380);
    } else { next.classList.add("is-active"); res(); }
  });
}
const inApp = (on) => document.body.classList.toggle("in-app", on);
// URLs: "/" is the landing page, "/dashboard" the workspace, "/dashboard#s=<id>" an open check
const DASH = "/dashboard";
function go(url, replace = false) {
  if (location.pathname + location.hash === url) return;
  history[replace ? "replaceState" : "pushState"](null, "", url);
}

async function goDash(replace = false) {
  chat?.close(); chat = null;
  go(DASH, replace);
  inApp(true);
  dash.setActive(null);
  await show("dash");
  dash.refresh();
}

async function goLanding(replace = false) {
  chat?.close(); chat = null;
  go("/", replace);
  inApp(false);
  document.body.classList.remove("sb-open");
  await show("landing");
}

/** Files picked or dropped on the dashboard → «Это всё или есть ещё файлы?» → upload. */
async function chooseFiles(list) {
  const fs = [...list];
  if (!fs.length || busy) return;
  const picked = await pickFiles(fs);
  if (picked) start({ file: picked.main, extras: picked.extras });
}

async function start({ file = null, extras = [], sample = false, home = false } = {}) {
  if (home) return goDash();
  if (busy) return;
  try { await requireAuth(); } catch { return; }   // checks are saved to the user's account
  if (!document.body.classList.contains("in-app")) await goDash();
  const err = $("dzError");
  if (err) err.hidden = true;
  if (file && !/\.(docx|pdf|txt|md)$/i.test(file.name)) { if (err) { err.textContent = t("err.format"); err.hidden = false; } return; }
  busy = true;
  dash.busy(true, sample ? null : file?.name, extras.length);
  try {
    const r = await api.upload(file, $("ctxInput")?.value || "", sample, extras);
    go(`${DASH}#s=${r.session_id}`, true);
    dash.refresh().then(() => dash.setActive(r.session_id));
    await show("loading");
    await runChain(r.session_id, r.filename, agentsById);
    openChat(r.session_id, r.title);
  } catch (e) {
    toast(`${t("err.upload")}: ${e.message}`, "error");
    await goDash();
  } finally {
    busy = false;
    dash.busy(false);
  }
}

async function openChat(sid, title) {
  chat?.close();
  inApp(true);
  dash.setActive(sid);
  await show("chat");
  chat = createChat({ sid, agentsById, title, onHome: goDash, toast });
}

/** Open a saved check (sidebar, recent cards or a reload): the server reopens it from the local file if needed. */
async function reopen(sid) {
  try {
    const r = await api.session(sid);
    go(`${DASH}#s=${sid}`);
    inApp(true);
    dash.setActive(sid);
    if (!r.analyzed) { await show("loading"); await runChain(sid, r.filename, agentsById); }
    openChat(sid, r.title);
  } catch (e) { toast(e.message, "error"); goDash(); }
}

function wire() {
  const fileInput = $("fileInput");
  const overlay = $("dropOverlay");
  const canDrop = () => $("dash").classList.contains("is-active") && !filesModalOpen() && !busy;
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-action]");
    if (!a) return;
    const act = a.dataset.action;
    if (act === "pick") { e.preventDefault(); fileInput.click(); }
    else if (act === "start") { e.preventDefault(); requireAuth("signup").then(() => goDash()).catch(() => {}); }
    else if (act === "sample") start({ sample: true });
    else if (act === "toggle-context") { const box = $("contextBox"); box.hidden = !box.hidden; if (!box.hidden) $("ctxInput").focus(); }
    else if (act === "home") { e.preventDefault(); document.body.classList.contains("in-app") ? goDash() : goLanding(); }
    else if (act === "sidebar") dash.toggle();
    else if (act === "toggle-doc") chat?.toggleDoc();
    else if (act === "trace") { const m = location.hash.match(/s=([a-f0-9]+)/); if (m) openTrace(m[1], agentsById); }
    else if (act === "attach") $("attachInput").click();
    else if (act === "cmd") chat?.command(a.dataset.cmd);
  });
  fileInput.addEventListener("change", () => { const fs = [...fileInput.files]; fileInput.value = ""; chooseFiles(fs); });
  // drop a TZ anywhere on the dashboard home
  let depth = 0;
  document.addEventListener("dragenter", (e) => { if (!canDrop() || !e.dataTransfer?.types?.includes("Files")) return; depth++; overlay.classList.add("is-on"); });
  document.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) overlay.classList.remove("is-on"); });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; overlay.classList.remove("is-on");
    const fs = e.dataTransfer?.files;
    if (fs?.length && canDrop()) chooseFiles(fs);
  });
}

async function init() {
  document.querySelectorAll("[data-product]").forEach((el) => (el.textContent = PRODUCT_NAME));
  document.title = `${PRODUCT_NAME} — проверка ТЗ командой агентов`;
  applyI18n();
  setFavicon();
  hydrateIcons();
  wire();
  initAuth({ toast, onLogin: () => goDash(), onLogout: () => goLanding() });
  try {
    const [cfg, agents] = await Promise.all([api.config(), api.agents()]);
    if (api.local && !api.user) await api.enter();
    agentsById = Object.fromEntries(agents.map((a) => [a.id, a]));
    renderLanding(agents);
    initGaze();
    hydrateIcons();
  } catch (e) { toast(t("err.network"), "error"); }
  dash = createDashboard({ agentsById, toast, onOpen: reopen, onStart: start, onLanding: () => goLanding(), onLogout: () => goLanding() });
  api.onAuth((u) => { if (!u && document.body.classList.contains("in-app")) goLanding(true); });
  addEventListener("popstate", route);
  route();
}

/** Show whatever the URL points at (first load and browser back/forward). */
function route() {
  const m = location.hash.match(/s=([a-f0-9]+)/);
  if (!location.pathname.startsWith(DASH)) {
    if (m) return go("/", true), goLanding(true);   // old-style links "/#s=…" land on the home page
    return goLanding(true);
  }
  if (!api.user) {          // the workspace needs an account: home page + sign-in, then back here
    goLanding(true);
    requireAuth("login").then(() => (m ? reopen(m[1]) : goDash())).catch(() => {});
    return;
  }
  if ($("landing").classList.contains("is-active") && !document.body.classList.contains("in-app")) $("landing").classList.remove("is-active");
  m ? reopen(m[1]) : goDash(true);
}

init();
