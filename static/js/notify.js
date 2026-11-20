// In-app notifications (replace the old toast): stacked cards with an icon, a close button and a
// draining progress bar; hover pauses them. Same message twice in a row is merged, not repeated.
import { escapeHtml as esc } from "./chain.js";
import { icon } from "./icons.js";

const ICON = { success: "check", error: "alert-circle", info: "info" };
const LIFE = { success: 3200, info: 4200, error: 6500 };
let stack = null;
const live = new Map();   // text → item

/** @param {string} text @param {{type?: "success"|"error"|"info", duration?: number}} [o] */
export function notify(text, o = {}) {
  if (!text) return;
  const type = o.type || "info";
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "ntf-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  const dup = live.get(type + text);
  if (dup) { dup.bump(); return; }
  const el = document.createElement("div");
  el.className = `ntf ${type}`;
  el.setAttribute("role", type === "error" ? "alert" : "status");
  el.innerHTML = `<span class="ntf-ic">${icon(ICON[type], 15)}</span><div class="ntf-t">${esc(text)}</div>
    <button class="ntf-x" aria-label="Закрыть">${icon("x", 14)}</button><i class="ntf-bar"></i>`;
  stack.appendChild(el);
  while (stack.children.length > 4) stack.firstElementChild.remove();
  const life = o.duration || LIFE[type];
  let left = life, started = performance.now(), timer = 0, count = 1;
  const bar = el.querySelector(".ntf-bar");
  const run = () => {
    started = performance.now();
    bar.style.transition = `transform ${left}ms linear`;
    bar.style.transform = "scaleX(0)";
    timer = setTimeout(close, left);
  };
  const pause = () => {
    clearTimeout(timer);
    left -= performance.now() - started;
    const k = Math.max(0, left / life);
    bar.style.transition = "none";
    bar.style.transform = `scaleX(${k})`;
  };
  function close() {
    clearTimeout(timer);
    live.delete(type + text);
    el.classList.add("is-out");
    setTimeout(() => el.remove(), 220);
  }
  const item = {
    bump() {   // same message again: show a counter and restart the timer
      count++;
      let c = el.querySelector(".ntf-n");
      if (!c) { c = document.createElement("span"); c.className = "ntf-n"; el.querySelector(".ntf-t").appendChild(c); }
      c.textContent = `×${count}`;
      clearTimeout(timer); left = life;
      bar.style.transition = "none"; bar.style.transform = "scaleX(1)";
      requestAnimationFrame(() => requestAnimationFrame(run));
    },
  };
  live.set(type + text, item);
  el.addEventListener("mouseenter", pause);
  el.addEventListener("mouseleave", run);
  el.querySelector(".ntf-x").onclick = close;
  requestAnimationFrame(() => { el.classList.add("is-on"); requestAnimationFrame(run); });
}
