// "How the agents worked": every Claude call (agent, model, tokens, cache, cost, time), every tool the
// agents called and every rule-engine pass — the architecture, visible on a real check.
import { api } from "./api.js";
import { blobSVG } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

let panel = null;
const MODEL = { "claude-haiku-5-5": "Haiku 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-opus-5-5": "Opus 5.5" };
const WEB = new Set(["web_search", "read_page"]);
const usd = (v) => (v >= 0.01 ? `$${v.toFixed(3)}` : v > 0 ? `$${v.toFixed(5)}` : "$0");
const num = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export async function openTrace(sid, agentsById) {
  if (!panel) {
    panel = document.createElement("aside");
    panel.className = "trace";
    panel.setAttribute("aria-label", t("trace.title"));
    document.body.appendChild(panel);
    panel.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) panel.classList.remove("is-on"); });
    addEventListener("keydown", (e) => { if (e.key === "Escape") panel?.classList.remove("is-on"); });
  }
  panel.innerHTML = `<div class="trace-head"><h3>${t("trace.title")}</h3><button class="icon-btn ghost" data-close aria-label="${t("auth.close")}">${icon("x", 18)}</button></div>
    <div class="trace-body"><div class="trace-empty">${t("history.loading")}</div></div>`;
  panel.classList.add("is-on");
  let d;
  try { d = await api.trace(sid); } catch (e) { panel.querySelector(".trace-body").innerHTML = `<div class="trace-empty">${esc(e.message)}</div>`; return; }
  const T = d.totals;
  const A = (id) => agentsById[id] || { shape: "ball", color: "#a48bff", name: id };
  const models = Object.entries(d.models).map(([m, v]) => `<div class="tr-model"><b>${esc(MODEL[m] || m)}</b>
      <span>${v.calls} ${t("trace.calls")}</span><span>${num(v.input)} → ${num(v.output)}</span><span>${usd(v.usd)}</span></div>`).join("");
  const rows = d.rows.map((r) => {
    const a = A(r.agent);
    const kind = r.kind === "cache" ? `<span class="tr-k cache">${icon("check", 11)}${t("trace.fromCache")}</span>`
      : r.kind === "llm" ? `<span class="tr-k llm">${esc(MODEL[r.model] || r.model)}</span>`
      : r.kind === "tool" ? `<span class="tr-k tool${WEB.has(r.tool) ? " web" : ""}">${icon(WEB.has(r.tool) ? "globe" : "wrench", 11)}${esc(r.tool)}</span>` : `<span class="tr-k rules">${t("trace.rules")}</span>`;
    const what = r.kind === "llm" || r.kind === "cache" ? esc(r.purpose || "")
      : r.kind === "tool" ? esc(Object.values(r.args || {}).join(", ") || t("trace.noArgs"))
      : `${esc(r.purpose || "")}${r.found != null ? ` · ${r.found}` : ""}`;
    const meta = r.kind === "cache" ? `<i class="saved">−${usd(r.saved_usd || 0)} · ${num(r.saved_tokens || 0)} ${t("trace.tokens")}</i>`
      : r.kind === "llm"
      ? `${num(r.input)}${r.cached ? ` <i>(${Math.round((r.cached / r.input) * 100)}% ${t("trace.cache")})</i>` : ""} → ${num(r.output)} · ${usd(r.usd)}`
      : `${r.ms ?? 0} мс`;
    const emo = r.kind === "tool" ? "focused" : r.kind === "llm" ? "thinking" : r.kind === "cache" ? "happy" : "neutral";
    return `<div class="tr-row ${r.kind}">${blobSVG(a, emo, { size: 22, glow: false, star: false })}
      <div class="tr-main"><div class="tr-top"><b>${esc(r.name || a.name)}</b>${kind}</div><div class="tr-what">${what}</div></div>
      <div class="tr-meta">${meta}</div></div>`;
  }).join("");
  const cache = T.input ? `<div class="tr-cache"><span>${t("trace.cacheShare")}</span><div class="bar"><i style="width:${Math.round(T.cache_share * 100)}%;background:#31c943"></i></div><b>${Math.round(T.cache_share * 100)}%</b></div>` : "";
  panel.querySelector(".trace-body").innerHTML = `
    ${d.engine === "rules" ? `<div class="tr-note">${icon("info", 15)}<span>${t("trace.rulesOnly")}</span></div>` : ""}
    <div class="tr-stats"><div><b>${T.llm_calls}</b><span>${t("trace.llm")}</span></div><div><b>${T.tool_calls}</b><span>${t("trace.tools")}</span></div>
      <div><b>${T.rule_passes}</b><span>${t("trace.passes")}</span></div><div><b>${usd(T.usd)}</b><span>${t("trace.cost")}</span></div></div>
    ${cache}
    ${T.pii_masked ? `<div class="tr-note saved">${icon("lock", 15)}<span>${t("trace.pii", { n: T.pii_masked })}</span></div>` : ""}
    ${d.engine === "local" ? `<div class="tr-note saved">${icon("lock", 15)}<span>${t("trace.local")}</span></div>` : ""}
    ${T.cache_hits ? `<div class="tr-note saved">${icon("check", 15)}<span>${t("trace.savedNote", { n: T.cache_hits, usd: usd(T.saved_usd) })}</span></div>` : ""}
    ${models ? `<div class="tr-h">${t("trace.byModel")}</div><div class="tr-models">${models}</div>` : ""}
    <div class="tr-h">${t("trace.timeline")}</div><div class="tr-list">${rows || `<div class="trace-empty">${t("trace.empty")}</div>`}</div>`;
}
