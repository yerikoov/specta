// Right panel "Документ" (bottom sheet on mobile): ТЗ text with highlights + versions.
import { api } from "./api.js";
import { escapeHtml } from "./chain.js";
import { t } from "./i18n.js";

export function createDocPanel(sid) {
  const chatEl = document.getElementById("chat");
  const body = document.getElementById("docBody");
  const vers = document.getElementById("docVersions");
  let data = null, timer = null, pendingFocus = null;

  document.querySelectorAll(".doc-tab").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".doc-tab").forEach((x) => x.classList.toggle("is-active", x === b));
    body.hidden = b.dataset.tab !== "doc";
    vers.hidden = b.dataset.tab !== "versions";
  }));

  async function refresh() {
    try { data = await api.doc(sid); } catch { return; }
    render();
    if (pendingFocus) { focus(...pendingFocus); pendingFocus = null; }
  }

  function marked(text, hls) {
    const ranges = [];
    for (const h of hls) {
      if (!h.quote) continue;
      const i = text.indexOf(h.quote);
      if (i >= 0 && !ranges.some((r) => i < r.e && i + h.quote.length > r.s)) ranges.push({ s: i, e: i + h.quote.length, h });
    }
    ranges.sort((a, b) => a.s - b.s);
    let out = "", pos = 0;
    for (const r of ranges) {
      out += escapeHtml(text.slice(pos, r.s)) + `<mark class="hl ${r.h.severity}" data-fid="${r.h.finding_id}">${escapeHtml(text.slice(r.s, r.e))}</mark>`;
      pos = r.e;
    }
    return out + escapeHtml(text.slice(pos));
  }

  function render() {
    if (!data) { body.innerHTML = `<p class="label">${t("doc.empty")}</p>`; return; }
    const bySec = {};
    data.highlights.forEach((h) => (bySec[h.section_ref] ||= []).push(h));
    body.innerHTML = `<div class="doc-h1">${escapeHtml(data.title)}</div>` + data.sections.map((s) => {
      const hls = bySec[s.ref] || [];
      const cls = ["dsec", `l${s.level}`];
      if (hls.length) cls.push("has-issue", hls.some((h) => h.severity === "critical") ? "crit" : "");
      const ver = data.changed[s.ref];
      if (ver || s.created) cls.push("changed");
      const tag = s.created ? `<span class="dtag">${t("doc.new")}</span>` : ver ? `<span class="dtag">${t("doc.changed")} · v${ver}</span>` : "";
      const head = s.level === 1
        ? `<div class="dtitle"><span class="dref">${escapeHtml(s.ref)}.</span>${escapeHtml(s.title)}${tag}</div>${s.text ? `<div class="dtext">${marked(s.text, hls)}</div>` : ""}`
        : `<span class="dref">${escapeHtml(s.ref)}</span><span class="dtext">${marked(s.text, hls)}</span>${tag}`;
      return `<div class="${cls.join(" ")}" data-ref="${escapeHtml(s.ref)}">${head}</div>`;
    }).join("");
    vers.innerHTML = [...data.versions].reverse().map((v) => `
      <div class="ver"><span class="vn">${v.n}</span><div><div class="vl">${escapeHtml(v.label)}</div>
      <div class="vt">${new Date(v.ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} · ${v.count} изм.</div></div></div>`).join("");
  }

  function focus(ref, findingId) {
    if (!data) { pendingFocus = [ref, findingId]; return; }
    open();
    body.hidden = false; vers.hidden = true;
    document.querySelectorAll(".doc-tab").forEach((x) => x.classList.toggle("is-active", x.dataset.tab === "doc"));
    body.querySelectorAll("mark.active").forEach((m) => m.classList.remove("active"));
    const mark = findingId && body.querySelector(`mark[data-fid="${findingId}"]`);
    const sec = body.querySelector(`.dsec[data-ref="${CSS.escape(ref || "")}"]`);
    const target = mark || sec;
    if (!target) return;
    if (mark) mark.classList.add("active");
    const s = mark ? mark.closest(".dsec") : sec;
    s.classList.remove("pulse"); void s.offsetWidth; s.classList.add("pulse");
    setTimeout(() => {
      const top = target.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
      body.scrollTo({ top: Math.max(0, top - body.clientHeight / 2), behavior: "smooth" });
    }, 320);
  }

  const open = () => chatEl.classList.add("doc-open");
  const close = () => chatEl.classList.remove("doc-open");
  const toggle = () => chatEl.classList.toggle("doc-open");
  const refreshSoon = () => { clearTimeout(timer); timer = setTimeout(refresh, 350); };

  refresh();
  return { refresh, refreshSoon, focus, open, close, toggle };
}
