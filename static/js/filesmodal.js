// «Это всё или есть ещё файлы?» — after the first file: add appendices (API spec, regulator requirements…),
// choose which file is the TZ, then «Далее» uploads everything, «Отмена» closes.
import { BRAND, blobSVG } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

const OK = /\.(docx|pdf|txt|md)$/i;
const MAX = 6;
const size = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(b / 1024))} КБ`);

/** @returns {Promise<{main: File, extras: File[]} | null>} */
export function pickFiles(initial) {
  let files = [], main = 0, err = "";
  const host = document.createElement("div");
  host.className = "fm";
  host.innerHTML = `<div class="fm-card" role="dialog" aria-modal="true" aria-labelledby="fmTitle">
      <button class="icon-btn ghost fm-x" data-v="cancel" aria-label="${t("auth.close")}">${icon("x", 18)}</button>
      <div class="fm-ava" aria-hidden="true">${blobSVG(BRAND, "curious", { size: 60 })}</div>
      <h3 id="fmTitle">${t("fm.title")}</h3>
      <p class="fm-sub">${t("fm.sub")}</p>
      <ul class="fm-list"></ul>
      <div class="fm-err" role="alert" hidden></div>
      <button class="fm-add" data-v="add">${icon("plus", 16)}<span>${t("fm.add")}</span><small>${t("fm.addHint")}</small></button>
      <input type="file" accept=".docx,.pdf,.txt,.md" multiple hidden>
      <div class="fm-acts">
        <button class="btn btn-outline" data-v="cancel">${t("fm.cancel")}</button>
        <button class="btn btn-primary" data-v="next">${t("fm.next")}${icon("arrow-right", 15)}</button>
      </div></div>`;
  document.body.appendChild(host);
  const list = host.querySelector(".fm-list"), input = host.querySelector("input"), errEl = host.querySelector(".fm-err");
  const prev = document.activeElement;

  function add(fs) {
    err = "";
    for (const f of fs) {
      if (!OK.test(f.name)) { err = t("fm.badFormat", { name: f.name }); continue; }
      if (files.length >= MAX) { err = t("fm.tooMany", { n: MAX }); break; }
      if (files.some((x) => x.name === f.name && x.size === f.size)) continue;
      files.push(f);
    }
    render();
  }
  function render() {
    list.innerHTML = files.map((f, i) => `<li class="${i === main ? "is-main" : ""}">
        <span class="fm-ic">${icon("file", 18)}</span>
        <span class="fm-name"><b>${esc(f.name)}</b><small>${size(f.size)}</small></span>
        ${i === main ? `<span class="fm-badge main">${t("fm.main")}</span>`
          : `<button class="fm-badge" data-main="${i}" title="${t("fm.makeMain")}">${t("fm.appendix")}</button>`}
        <button class="icon-btn ghost fm-rm" data-rm="${i}" aria-label="${t("fm.remove")}">${icon("x", 15)}</button></li>`).join("");
    errEl.textContent = err;
    errEl.hidden = !err;
    host.querySelector('[data-v="next"]').disabled = !files.length;
  }

  add(initial);
  requestAnimationFrame(() => host.classList.add("is-on"));
  host.querySelector('[data-v="next"]').focus();

  return new Promise((resolve) => {
    const done = (v) => {
      removeEventListener("keydown", onKey, true);
      host.classList.remove("is-on");
      setTimeout(() => host.remove(), 200);
      prev?.focus?.();
      resolve(v);
    };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); done(null); } };
    addEventListener("keydown", onKey, true);
    host.addEventListener("click", (e) => {
      if (e.target === host) return done(null);
      const b = e.target.closest("[data-v],[data-rm],[data-main]");
      if (!b) return;
      if (b.dataset.rm != null) {
        const i = +b.dataset.rm;
        files.splice(i, 1);
        main = i === main ? 0 : main > i ? main - 1 : main;
        return render();
      }
      if (b.dataset.main != null) { main = +b.dataset.main; return render(); }
      const v = b.dataset.v;
      if (v === "cancel") done(null);
      else if (v === "add") input.click();
      else if (v === "next" && files.length) done({ main: files[main], extras: files.filter((_, i) => i !== main) });
    });
    input.addEventListener("change", () => { add([...input.files]); input.value = ""; });
    // drop more files right into the dialog
    const card = host.querySelector(".fm-card");
    card.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); card.classList.add("is-drag"); });
    card.addEventListener("dragleave", () => card.classList.remove("is-drag"));
    card.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); card.classList.remove("is-drag"); add([...(e.dataTransfer?.files || [])]); });
  });
}

export const filesModalOpen = () => !!document.querySelector(".fm");
