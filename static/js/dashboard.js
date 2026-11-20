// The signed-in workspace: a sidebar (new check, sample, saved chats with TZ, account) and the home view
// (drop a TZ and start; recent checks). Vanilla port of the shadcn Sidebar idea: expanded / collapsed on
// desktop (Cmd/Ctrl+B), off-canvas sheet on phones.
import { api } from "./api.js";
import { withSpinner } from "./auth.js";
import { confirmDialog } from "./dialog.js";
import { blobSVG } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";
import { PRODUCT_NAME } from "./config.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

const mobile = () => matchMedia("(max-width: 820px)").matches;

export function createDashboard({ agentsById, toast, onOpen, onStart, onLanding, onLogout }) {
  const sb = document.getElementById("sidebar");
  const home = document.getElementById("dashHome");
  const A = (id) => agentsById[id] || { shape: "ball", color: "#a48bff" };
  let rows = [], active = null;

  // ---------------------------------------------------------------- sidebar
  sb.innerHTML = `
    <div class="sb-head">
      <button class="sb-brand" data-sb="landing" title="${t("sb.about")}"><span class="brand-logo">${blobSVG({ shape: "bumps", color: "#31c943" }, "neutral", { size: 22, glow: false })}</span><span>${esc(PRODUCT_NAME)}</span></button>
      <button class="icon-btn ghost sb-collapse" data-sb="toggle" title="${t("sb.toggle")} (⌘B)">${icon("panel-left", 17)}</button>
    </div>
    <div class="sb-content">
      <div class="sb-group">
        <div class="sb-label">${t("sb.workspace")}</div>
        <button class="sb-item" data-sb="new">${icon("plus", 16)}<span>${t("sb.new")}</span></button>
        <button class="sb-item" data-sb="sample">${icon("sparkles", 16)}<span>${t("sb.sample")}</span></button>
      </div>
      <div class="sb-group sb-grow">
        <div class="sb-label">${t("sb.chats")}<span class="sb-count"></span></div>
        <div class="sb-list" role="list"></div>
      </div>
    </div>
    <div class="sb-foot">
      <button class="sb-user" data-sb="menu" aria-haspopup="menu"><span class="acc-ava"></span>
        <span class="sb-user__txt"><b></b><small></small></span>${icon("chevrons", 15)}</button>
      <div class="sb-menu" role="menu" hidden>
        <button data-sb="landing">${icon("home", 15)}${t("sb.about")}</button>
        <button data-sb="logout">${icon("logout", 15)}${t("auth.logout")}</button>
      </div>
    </div>`;
  const backdrop = document.createElement("div");
  backdrop.className = "sb-backdrop";
  document.body.appendChild(backdrop);
  backdrop.onclick = () => document.body.classList.remove("sb-open");

  function renderUser() {
    const u = api.user;
    if (!u) return;
    const name = u.name || u.email.split("@")[0];
    sb.querySelector(".acc-ava").textContent = name[0].toUpperCase();
    sb.querySelector(".sb-user__txt b").textContent = name;
    sb.querySelector(".sb-user__txt small").textContent = u.email;
  }

  function renderList() {
    const list = sb.querySelector(".sb-list");
    sb.querySelector(".sb-count").textContent = rows.length ? rows.length : "";
    list.innerHTML = rows.length ? rows.map((r) => {
      const sc = r.score_before != null ? (r.score != null && r.score !== r.score_before ? `${r.score_before}→${r.score}` : `${r.score_before}`) : "";
      return `<div class="sb-chat ${r.id === active ? "is-on" : ""}" role="listitem" data-sid="${esc(r.id)}" data-title="${esc(r.title || "")}" tabindex="0">
        <span class="sb-dot ${r.status === "done" ? "done" : ""}"></span>
        <span class="sb-chat__t">${esc(r.title || r.filename || "ТЗ")}</span>
        ${sc ? `<span class="sb-badge">${esc(sc)}</span>` : ""}
        <span class="sb-acts"><button data-share title="${t("share.button")}">${icon("external", 13)}</button><button data-del title="${t("history.delete")}">${icon("x", 13)}</button></span>
      </div>`;
    }).join("") : `<div class="sb-empty">${t("sb.empty")}</div>`;
  }

  sb.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-sb]");
    const chat = e.target.closest(".sb-chat");
    const menu = sb.querySelector(".sb-menu");
    if (chat) {
      const sid = chat.dataset.sid;
      if (e.target.closest("[data-share]")) {
        try { const r = await api.share(sid); try { await navigator.clipboard.writeText(r.url); toast(t("share.copied"), "success"); } catch { toast(r.url); } }
        catch (ex) { toast(ex.message, "error"); }
      } else if (e.target.closest("[data-del]")) {
        const ok = await confirmDialog({ title: t("history.deleteTitle"), text: t("history.confirmDelete", { title: chat.dataset.title || "ТЗ" }),
          ok: t("history.delete"), cancel: t("common.cancel"), danger: true });
        if (!ok) return;
        try { await api.remove(sid); rows = rows.filter((r) => r.id !== sid); renderList(); renderHome(); if (sid === active) onStart?.({ home: true }); }
        catch (ex) { toast(ex.message, "error"); }
      } else { closeMobile(); onOpen(sid, chat.dataset.title); }
      return;
    }
    if (!b) return;
    const act = b.dataset.sb;
    if (act === "toggle") toggle();
    else if (act === "new") { closeMobile(); onStart?.({ home: true }); setTimeout(() => document.getElementById("fileInput").click(), 50); }
    else if (act === "sample") { closeMobile(); withSpinner(b, () => onStart?.({ sample: true })); }
    else if (act === "menu") menu.hidden = !menu.hidden;
    else if (act === "landing") { menu.hidden = true; closeMobile(); onLanding?.(); }
    else if (act === "logout") { menu.hidden = true; api.logout(); onLogout?.(); }
  });
  sb.addEventListener("keydown", (e) => { const c = e.target.closest(".sb-chat"); if (c && e.key === "Enter") c.click(); });
  document.addEventListener("pointerdown", (e) => { const m = sb.querySelector(".sb-menu"); if (!m.hidden && !e.target.closest(".sb-foot")) m.hidden = true; });
  addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "b" && (e.metaKey || e.ctrlKey) && document.body.classList.contains("in-app")) { e.preventDefault(); toggle(); }
  });

  function toggle() {
    if (mobile()) document.body.classList.toggle("sb-open");
    else {
      document.body.classList.toggle("sb-collapsed");
      try { localStorage.setItem("specta.sb", document.body.classList.contains("sb-collapsed") ? "0" : "1"); } catch {}
    }
  }
  function closeMobile() { document.body.classList.remove("sb-open"); }
  try { if (localStorage.getItem("specta.sb") === "0") document.body.classList.add("sb-collapsed"); } catch {}

  // ---------------------------------------------------------------- home
  function renderHome() {
    const u = api.user;
    if (!u || !home) return;
    const name = u.name || u.email.split("@")[0];
    const fresh = !rows.length;
    const team = ["completeness", "ambiguity", "contradictions", "regulatory", "testability"];
    const done = rows.filter((r) => r.status === "done");
    const gain = done.length ? Math.round(done.reduce((s, r) => s + ((r.score ?? 0) - (r.score_before ?? 0)), 0) / done.length) : 0;
    home.innerHTML = `
      <header class="dh-top"><button class="icon-btn ghost dh-toggle" data-action="sidebar" title="${t("sb.toggle")}">${icon("panel-left", 18)}</button></header>
      <div class="dh-inner">
        <h1>${esc(t(fresh ? "dash.helloNew" : "dash.hello", { name }))}</h1>
        <p class="dh-sub">${t(fresh ? "dash.subNew" : "dash.sub")}</p>
        <div class="dz" id="dashDrop" tabindex="0" role="button" aria-label="${t("dash.drop")}">
          <div class="dz-team" aria-hidden="true">${team.map((id, i) => `<span style="--i:${i}">${blobSVG(A(id), ["curious", "happy", "wink", "thinking", "excited"][i], { size: 52 })}</span>`).join("")}</div>
          <h2>${t("dash.drop")}</h2>
          <p>${t("dash.formats")}</p>
          <div class="dz-acts">
            <button class="btn btn-primary dz-pick" data-action="pick">${icon("upload", 16)}${t("dash.pick")}</button>
            <button class="btn btn-outline dz-sample" data-action="sample">${icon("sparkles", 15)}${t("hero.sample")}</button>
          </div>
          <button class="link-btn dz-ctx" data-action="toggle-context">${icon("plus", 14)}${t("hero.context")}</button>
          <div class="context-box" id="contextBox" hidden>
            <label for="ctxInput" class="label">${t("hero.contextLabel")}</label>
            <textarea id="ctxInput" rows="2" maxlength="1000" placeholder="${t("hero.contextPh")}"></textarea>
          </div>
          <div class="dz-error" id="dzError" role="alert" hidden></div>
        </div>
        ${fresh ? `<div class="dh-steps">${[1, 2, 3].map((n) => `<div class="dh-step"><span>${n}</span><b>${t(`dash.s${n}`)}</b><p>${t(`dash.s${n}d`)}</p></div>`).join("")}</div>`
        : `<div class="dh-stats"><div><b>${rows.length}</b><span>${t("dash.statChecks")}</span></div><div><b>${done.length}</b><span>${t("dash.statDone")}</span></div>
             <div><b>${gain > 0 ? "+" : ""}${gain}</b><span>${t("dash.statGain")}</span></div></div>
           <h3 class="dh-h">${t("dash.recent")}</h3>
           <div class="dh-recent">${rows.slice(0, 6).map((r) => `<button class="dh-card" data-open="${esc(r.id)}" data-title="${esc(r.title || "")}">
              <span class="dh-card__t">${esc(r.title || r.filename || "ТЗ")}</span>
              <span class="dh-card__m">${new Date(r.updated_at || r.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })} · ${r.status === "done" ? t("history.done") : t("dash.inProgress")}</span>
              <span class="dh-card__s">${r.score_before ?? "—"}<i>→</i>${r.score ?? r.score_before ?? "—"}<small>/100</small></span></button>`).join("")}</div>`}
      </div>`;
    home.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => onOpen(b.dataset.open, b.dataset.title)));
    const dz = home.querySelector("#dashDrop");
    dz.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === dz) document.getElementById("fileInput").click(); });
  }

  // until the profile and the saved checks arrive: the greeting place shows a spinner instead of a blank page
  function renderLoading() {
    if (!home || home.querySelector(".dh-inner")) return;
    home.innerHTML = `<header class="dh-top"><button class="icon-btn ghost dh-toggle" data-action="sidebar" title="${t("sb.toggle")}">${icon("panel-left", 18)}</button></header>
      <div class="dh-inner dh-loading" aria-busy="true" aria-live="polite">
        <div class="dh-load-head"><span class="spinner" aria-hidden="true"></span><span>${t("dash.loading")}</span></div>
        <div class="sk sk-h1"></div><div class="sk sk-sub"></div><div class="sk sk-dz"></div>
      </div>`;
  }

  async function refresh() {
    renderLoading();
    renderUser();
    try { rows = await api.sessions(); } catch (ex) { if (ex.status !== 401) toast(ex.message, "error"); rows = []; }
    renderList();
    renderHome();
  }

  return {
    refresh,
    toggle,
    setActive(sid) { active = sid; renderList(); },
    busy(on) { home.querySelector(".dz")?.classList.toggle("is-busy", on); },
  };
}
