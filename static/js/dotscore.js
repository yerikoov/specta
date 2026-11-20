// Dot-matrix score card: animated total + one block of dots per criterion (each dot = 10 points).
// Tabs switch between "now" and the score at the start of the session; dots pop in with a diagonal
// stagger; hovering a block dims the others and shows a tooltip. Vanilla port of a dot-graph card.
import { escapeHtml as esc } from "./chain.js";
import { t } from "./i18n.js";

const ROWS = 10, COLS = 5;
const easeOutQuart = (x) => 1 - Math.pow(1 - x, 4);
const state = (v) => (v >= 75 ? "good" : v >= 50 ? "mid" : "bad");
const SHORT = { completeness: "Полнота", clarity: "Ясность", testability: "Тесты", consistency: "Согласов.", compliance: "Комплаенс" };

/**
 * @param {{total:number, prev?:number, before?:number, criteria:{key,label,value}[], before_criteria?:{key,value}[]}} d
 * @param {string} title  label shown above the number
 * @param {{head?:string, foot?:string}} [extra]  optional HTML under the number and under the dots
 */
export function dotScoreCard(d, title, extra = {}) {
  const el = document.createElement("div");
  el.className = "mcard dsc";
  const hasBefore = d.before_criteria && d.before != null && d.before !== d.total;
  const delta = d.prev != null ? d.total - d.prev : hasBefore ? d.total - d.before : 0;
  el.innerHTML = `
    <div class="dsc-head">
      <div class="dsc-left"><div class="dsc-label">${esc(title)}</div>
        <div class="dsc-value"><span class="dsc-n">0</span><span class="dsc-of">/100</span>
          ${delta ? `<span class="s-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "+" : ""}${delta}</span>` : ""}</div>
        ${extra.head || ""}</div>
      ${hasBefore ? `<div class="dsc-tabs" role="tablist"><button class="dsc-tab" data-k="before">${t("score.tabBefore")}</button>
        <button class="dsc-tab is-on" data-k="now">${t("score.tabNow")}</button></div>` : ""}
    </div>
    <div class="dsc-div"></div>
    <div class="dsc-body"><div class="dsc-tip"></div><div class="dsc-graph"></div></div>
    ${extra.foot ? `<div class="dsc-div"></div><div class="dsc-extra">${extra.foot}</div>` : ""}`;

  const graph = el.querySelector(".dsc-graph");
  const tip = el.querySelector(".dsc-tip"), num = el.querySelector(".dsc-n");
  const before = Object.fromEntries((d.before_criteria || []).map((c) => [c.key, c.value]));
  let shown = d.prev != null && d.prev !== d.total ? d.prev : 0, raf = 0;

  const count = (to) => {
    cancelAnimationFrame(raf);
    const from = shown, t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 1200);
      shown = Math.round(from + (to - from) * easeOutQuart(p));
      num.textContent = shown;
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    setTimeout(() => { if (shown !== to) { shown = to; num.textContent = to; } }, 1300);  // background tabs throttle rAF
  };

  function draw(mode) {
    const total = mode === "before" ? d.before : d.total;
    const items = d.criteria.map((c) => ({ ...c, value: mode === "before" ? before[c.key] ?? c.value : c.value }));
    drawMatrix(graph, tip, items, { past: mode === "before", before: mode === "now" && hasBefore ? before : null });
    count(total);
  }

  el.querySelector(".dsc-tabs")?.addEventListener("click", (e) => {
    const b = e.target.closest(".dsc-tab");
    if (!b || b.classList.contains("is-on")) return;
    el.querySelectorAll(".dsc-tab").forEach((x) => x.classList.toggle("is-on", x === b));
    draw(b.dataset.k);
  });
  draw("now");
  return el;
}

/**
 * Draw the dot matrix into `graph` (one block per criterion, each dot = 10 points) and wire hover tooltips.
 * @param {HTMLElement} graph  .dsc-graph container
 * @param {HTMLElement} tip    .dsc-tip element (sibling inside .dsc-body)
 * @param {{key:string,label:string,value:number}[]} items
 * @param {{past?:boolean, before?:Object<string,number>|null}} opts  past: grey "start" look; before: highlight gains
 */
export function drawMatrix(graph, tip, items, { past = false, before = null } = {}) {
  graph.innerHTML = "";
  items.forEach((c, b) => {
    const v = c.value;
    const was = before ? Math.round((before[c.key] ?? v) / 10) : ROWS;
    const n = Math.round(v / 10);
    const block = document.createElement("div");
    block.className = `dsc-block ${past ? "past" : state(v)}`;
    for (let col = 0; col < COLS; col++) {
      const column = document.createElement("div");
      column.className = "dsc-col";
      for (let r = 0; r < ROWS; r++) {
        const dot = document.createElement("i");
        dot.className = r < n ? (r >= was ? "on gain" : "on") : "off";
        dot.style.animationDelay = `${(b * COLS + col) * 0.02 + r * 0.04}s`;
        column.appendChild(dot);
      }
      block.appendChild(column);
    }
    const diff = before ? v - (before[c.key] ?? v) : 0;
    block.addEventListener("mouseenter", () => {
      const br = block.getBoundingClientRect();
      tip.innerHTML = `${esc(c.label)} <b>${v}/100</b>${diff ? `<span class="amount">${diff > 0 ? "+" : ""}${diff}</span>` : ""}`;
      tip.classList.add("on");
      // keep the tooltip inside the card: clamp its centre so neither edge leaves the body
      const body = graph.parentElement.getBoundingClientRect(), half = tip.offsetWidth / 2, pad = 8;
      const centre = br.left - body.left + br.width / 2;
      tip.style.left = `${Math.max(half + pad, Math.min(body.width - half - pad, centre))}px`;
    });
    block.addEventListener("mouseleave", () => tip.classList.remove("on"));
    const item = document.createElement("div");
    item.className = "dsc-item";
    item.appendChild(block);
    item.insertAdjacentHTML("beforeend", `<div class="dsc-lab ${past ? "past" : state(v)}"><span>${esc(SHORT[c.key] || c.label)}</span><b>${v}</b></div>`);
    graph.appendChild(item);
  });
}
