// Audit log: a vertical timeline of records with filters (agent / type / status / search) and a context menu.
// Vanilla port of the shadcn-style AuditLog idea; renders the same item shape everywhere.
//   item = { id, title, description?, timestamp, actor?, type?, status?, severity?, ref?, fid? }
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { escapeHtml as esc } from "./chain.js";

const SEV_ICON = { critical: "alert-circle", important: "alert-triangle", minor: "info" };
const FIELDS = [["actor", "log.actor"], ["type", "log.type"], ["status", "log.status"]];

export function auditItemHtml(it) {
  const a = (k) => esc(it[k] || "");
  return `<div class="al-item" tabindex="0" data-id="${a("id")}" data-actor="${a("actor")}" data-type="${a("type")}" data-status="${a("status")}"
      data-ref="${a("ref")}" data-fid="${a("fid")}">
    <span class="al-dot ${a("severity")}">${icon(SEV_ICON[it.severity] || "history", 12)}</span>
    <div class="al-main">
      <div class="al-top"><span class="al-title">${a("title")}</span><span class="al-time">${a("timestamp")}</span></div>
      ${it.description ? `<div class="al-desc">${a("description")}</div>` : ""}
      <div class="al-tags">${it.actor ? `<b>${a("actor")}</b>` : ""}${it.type && it.type !== it.actor ? `<span class="al-chip">${a("type")}</span>` : ""}${it.status ? `<span class="al-chip ${a("severity")}">${a("status")}</span>` : ""}</div>
    </div>
    <button class="al-more" aria-label="${t("log.menu")}">${icon("more", 16)}</button>
  </div>`;
}

export function auditLogHtml(items = [], { filters = false } = {}) {
  const uniq = (k) => [...new Set(items.map((i) => i[k]).filter(Boolean))].sort();
  const bar = filters ? `<div class="al-filters">
      ${FIELDS.map(([k, lab]) => uniq(k).length > 1 ? `<label class="al-sel"><span>${t(lab)}</span><select data-f="${k}"><option value="">${t("log.any")}</option>
        ${uniq(k).map((v) => `<option>${esc(v)}</option>`).join("")}</select>${icon("chevron-down", 13)}</label>` : "").join("")}
      <label class="al-search">${icon("search", 14)}<input data-f="search" type="search" placeholder="${t("log.search")}"></label>
      <button class="al-reset" hidden>${t("log.reset")}</button>
    </div>` : "";
  return `<div class="al ${filters ? "has-filters" : ""}">${bar}<div class="al-list">${items.map(auditItemHtml).join("")}</div>
    <div class="al-empty" hidden>${t("log.empty")}</div></div>`;
}

/** Recompute which items are visible and where the timeline line ends. */
export function refreshAuditLog(root) {
  const f = {};
  root.querySelectorAll(".al-filters [data-f]").forEach((el) => { if (el.value.trim()) f[el.dataset.f] = el.value.trim().toLowerCase(); });
  let shown = 0, lastEl = null;
  root.querySelectorAll(".al-item").forEach((el) => {
    const ok = ["actor", "type", "status"].every((k) => !f[k] || (el.dataset[k] || "").toLowerCase() === f[k])
      && (!f.search || el.textContent.toLowerCase().includes(f.search));
    el.hidden = !ok;
    el.classList.remove("is-last");
    if (ok) { shown++; lastEl = el; }
  });
  lastEl?.classList.add("is-last");
  const empty = root.querySelector(".al-empty");
  if (empty) empty.hidden = shown > 0 || !root.querySelector(".al-item");
  const reset = root.querySelector(".al-reset");
  if (reset) reset.hidden = !Object.keys(f).length;
}

let menu = null, menuItem = null, handlers = {};
function closeMenu() { if (menu) menu.hidden = true; menuItem = null; }
function openMenu(x, y, itemEl) {
  if (!menu) {
    menu = document.createElement("div");
    menu.className = "al-menu";
    menu.setAttribute("role", "menu");
    menu.innerHTML = `<button data-act="open">${icon("external", 15)}${t("log.open")}</button>
      <button data-act="review">${icon("file-search", 15)}${t("log.review")}</button><hr>
      <button data-act="copy">${icon("copy", 15)}${t("log.copy")}</button>`;
    document.body.appendChild(menu);
    menu.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (!b || !menuItem) return;
      const d = { ...menuItem.dataset };
      if (b.dataset.act === "copy") navigator.clipboard?.writeText(d.fid || d.id).catch(() => {});
      else handlers[b.dataset.act]?.(d);
      closeMenu();
    });
    addEventListener("pointerdown", (e) => { if (menu && !menu.contains(e.target)) closeMenu(); }, true);
    addEventListener("keydown", (e) => e.key === "Escape" && closeMenu());
    addEventListener("scroll", closeMenu, true);
  }
  menuItem = itemEl;
  const canReview = !!handlers.canReview?.(itemEl.dataset);
  menu.querySelector('[data-act="review"]').hidden = !canReview;
  menu.hidden = false;
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
}

/** Wire filters, click, "…" button and right-click for every audit log inside `root` (event delegation). */
export function wireAuditLogs(root, opts) {
  handlers = opts;
  if (root._alWired) return;   // the chat container is reused between sessions: wire once, swap handlers
  root._alWired = true;
  root.addEventListener("input", (e) => { const al = e.target.closest(".al"); if (al && e.target.dataset.f) refreshAuditLog(al); });
  root.addEventListener("click", (e) => {
    const reset = e.target.closest(".al-reset");
    if (reset) {
      const al = reset.closest(".al");
      al.querySelectorAll(".al-filters [data-f]").forEach((el) => (el.value = ""));
      return refreshAuditLog(al);
    }
    const more = e.target.closest(".al-more");
    if (more) { const r = more.getBoundingClientRect(); return openMenu(r.right - 180, r.bottom + 4, more.closest(".al-item")); }
    const it = e.target.closest(".al-item");
    if (it && !e.target.closest(".al-filters")) handlers.open?.({ ...it.dataset });
  });
  root.addEventListener("contextmenu", (e) => {
    const it = e.target.closest(".al-item");
    if (!it) return;
    e.preventDefault();
    openMenu(e.clientX, e.clientY, it);
  });
  root.addEventListener("keydown", (e) => {
    const it = e.target.closest?.(".al-item");
    if (it && e.key === "Enter") handlers.open?.({ ...it.dataset });
  });
}
