// Loading screen: AI thought chain driven by /api/analyze/{id}/stream
import { api } from "./api.js";
import { blobSVG } from "./blobs.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

const STEPS = ["read", "structure", "team", "checks", "questions"];

export function runChain(sid, filename, agentsById) {
  return new Promise((resolve, reject) => {
    const root = document.getElementById("chain");
    const avatars = document.getElementById("chainAvatars");
    const err = document.getElementById("chainError");
    document.getElementById("chainFile").textContent = filename || "";
    avatars.innerHTML = ""; err.hidden = true;
    root.innerHTML = STEPS.map((k) => `
      <li class="cstep" data-step="${k}" data-state="pending">
        <div class="cstep-rail"><span class="cstep-icon"></span><span class="cstep-line"></span></div>
        <div class="cstep-main">
          <button class="cstep-title" type="button" aria-expanded="false"><span class="tt">${t("chain.step." + k)}</span>
            <span class="badge-progress" hidden>${t("chain.inProgress")}</span><span class="chev">${icon("chevron-down", 14)}</span></button>
          <div class="cstep-body"><div><ul class="citems"></ul></div></div>
        </div>
      </li>`).join("");
    const el = (k) => root.querySelector(`[data-step="${k}"]`);
    const timers = {};
    root.querySelectorAll(".cstep-title").forEach((b) => b.addEventListener("click", () => {
      const li = b.closest(".cstep");
      if (li.dataset.state === "pending") return;
      clearTimeout(timers[li.dataset.step]);
      toggle(li, !li.classList.contains("is-open"));
    }));
    function toggle(li, open) {
      li.classList.toggle("is-open", open);
      li.querySelector(".cstep-title").setAttribute("aria-expanded", open);
    }
    const shown = new Set();
    let finished = false;

    const es = api.stream(`/api/analyze/${sid}/stream`, (ev) => {
      if (ev.type === "step") {
        const li = el(ev.step);
        li.dataset.state = ev.state;
        li.querySelector(".badge-progress").hidden = ev.state !== "active";
        const ic = li.querySelector(".cstep-icon");
        ic.innerHTML = ev.state === "done" ? icon("check", 12) : "";
        if (ev.state === "active") toggle(li, true);
        if (ev.state === "done") timers[ev.step] = setTimeout(() => toggle(li, false), 1500);
      } else if (ev.type === "item") {
        const ul = el(ev.step).querySelector(".citems");
        const a = ev.agent && agentsById[ev.agent];
        ul.insertAdjacentHTML("beforeend", `<li class="citem">${a ? blobSVG(a, ev.emotion || "neutral", { size: 20, glow: false }) : '<span class="dot"></span>'}<span>${escapeHtml(ev.text)}</span></li>`);
        if (ev.step === "team" && a && ev.emotion !== "sleepy" && !shown.has(ev.agent)) {
          shown.add(ev.agent);
          avatars.insertAdjacentHTML("beforeend", `<span class="av" title="${a.name}">${blobSVG(a, "curious", { size: 32 })}</span>`);
        }
        if (ev.step === "checks" && a) {
          const av = [...avatars.children].find((x) => x.title === a.name);
          if (av) av.innerHTML = blobSVG(a, ev.emotion || "happy", { size: 32 });
        }
      } else if (ev.type === "done") {
        finished = true; es.close();
        setTimeout(resolve, 600);
      } else if (ev.type === "error") {
        finished = true; es.close();
        err.textContent = ev.text; err.hidden = false;
        reject(new Error(ev.text));
      }
    }, {
      onError: () => { if (!finished) { err.textContent = t("err.network"); err.hidden = false; } },
      onEnd: () => { if (!finished) { finished = true; resolve(); } },
    });
  });
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
