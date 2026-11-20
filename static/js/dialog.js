// In-app confirmation dialog (replaces window.confirm): an agent, a title, a short text and two buttons.
import { blobSVG } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";

let host = null;

/**
 * @param {{title:string, text?:string, ok?:string, cancel?:string, danger?:boolean, agent?:{shape:string,color:string}, emotion?:string}} o
 * @returns {Promise<boolean>} true when confirmed
 */
export function confirmDialog(o) {
  host?.remove();
  host = document.createElement("div");
  host.className = "dlg";
  host.innerHTML = `<div class="dlg-card" role="alertdialog" aria-modal="true" aria-labelledby="dlgTitle" aria-describedby="dlgText">
      <div class="dlg-ava" aria-hidden="true">${blobSVG(o.agent || { shape: "heart", color: "#ff7a8a" }, o.emotion || (o.danger ? "sad" : "curious"), { size: 64 })}</div>
      <h3 id="dlgTitle">${esc(o.title)}</h3>
      ${o.text ? `<p id="dlgText">${esc(o.text)}</p>` : ""}
      <div class="dlg-acts">
        <button class="btn btn-outline" data-v="0">${esc(o.cancel || "Отмена")}</button>
        <button class="btn ${o.danger ? "btn-danger" : "btn-primary"}" data-v="1">${esc(o.ok || "OK")}</button>
      </div></div>`;
  document.body.appendChild(host);
  const prev = document.activeElement;
  requestAnimationFrame(() => host.classList.add("is-on"));
  const okBtn = host.querySelector('[data-v="1"]'), cancelBtn = host.querySelector('[data-v="0"]');
  (o.danger ? cancelBtn : okBtn).focus();
  return new Promise((resolve) => {
    const done = (v) => {
      removeEventListener("keydown", onKey, true);
      host.classList.remove("is-on");
      const el = host;
      setTimeout(() => el.remove(), 200);
      prev?.focus?.();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); done(false); }
      else if (e.key === "Tab") { e.preventDefault(); (document.activeElement === okBtn ? cancelBtn : okBtn).focus(); }
    };
    addEventListener("keydown", onKey, true);
    host.addEventListener("click", (e) => {
      if (e.target === host) return done(false);
      const b = e.target.closest("[data-v]");
      if (b) done(b.dataset.v === "1");
    });
  });
}
