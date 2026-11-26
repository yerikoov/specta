// Accounts: the sign-in / sign-up card (an agent greets you and reacts) and the account chip on the landing.
import { api } from "./api.js";
import { BRAND, blobSVG, setEmotion } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

let modal, pending = null, opts = {};
const HOST = BRAND;   // the green brand agent (as in the nav bar) welcomes people

export function initAuth(o) {
  opts = o;
  buildModal();
  renderChip();
  api.onAuth(renderChip);
}

/** Resolves once the user is signed in (opens the card if needed). */
export function requireAuth(mode = "login") {
  if (api.user) return Promise.resolve(api.user);
  if (api.local) return api.enter();
  openModal(mode);
  return new Promise((res, rej) => (pending = { res, rej }));
}
export const openAuth = (mode = "signup") => openModal(mode);

/** Show a spinner on a button while a promise runs. */
export async function withSpinner(btn, fn) {
  if (!btn) return fn();
  btn.classList.add("is-loading");
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  try { return await fn(); } finally { btn.classList.remove("is-loading"); btn.disabled = false; btn.removeAttribute("aria-busy"); }
}

// ---------------------------------------------------------------- landing chip
function renderChip() {
  const host = document.getElementById("navAccount");
  if (!host) return;
  host.innerHTML = api.user
    ? `<button class="acc-btn" data-auth="app">${icon("panel-left", 15)}${t("auth.cabinet")}</button>`
    : `<button class="acc-btn" data-auth="login">${t("auth.login")}</button>`;
  host.onclick = (e) => {
    const b = e.target.closest("[data-auth]");
    if (b?.dataset.auth === "login") openModal("login");
    else if (b?.dataset.auth === "app") opts.onLogin?.();
  };
}

// ---------------------------------------------------------------- the card
function buildModal() {
  modal = document.createElement("div");
  modal.className = "auth-modal";
  modal.hidden = true;
  modal.innerHTML = `<div class="auth-wrap">
      <div class="auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">
        <button class="icon-btn ghost auth-x" data-close aria-label="${t("auth.close")}">${icon("x", 18)}</button>
        <div class="auth-logo" aria-hidden="true">${blobSVG(HOST, "happy", { size: 76 })}</div>
        <h3 id="authTitle"></h3><p class="auth-sub"></p>
        <form class="auth-form" novalidate>
          <label class="auth-f auth-name"><span>${t("auth.name")}</span><input name="name" autocomplete="name" maxlength="80" placeholder="${t("auth.namePh")}"></label>
          <label class="auth-f"><span>Email</span><input name="email" type="email" autocomplete="email" required placeholder="you@bank.kz"></label>
          <label class="auth-f"><span>${t("auth.password")}</span><input name="password" type="password" minlength="6" required placeholder="${t("auth.passPh")}"></label>
          <div class="auth-err" role="alert" hidden></div>
          <button class="btn btn-primary auth-go" type="submit"><span class="ic-wrap">${icon("mail", 16)}</span><span class="lbl"></span></button>
        </form>
        <div class="auth-or"><span>${t("auth.or")}</span></div>
        <button class="btn btn-outline auth-switch" type="button"></button>
      </div>
      <p class="auth-foot">${t("auth.foot")}</p>
    </div>`;
  document.body.appendChild(modal);
  const form = modal.querySelector("form"), err = modal.querySelector(".auth-err");
  const face = () => modal.querySelector(".auth-logo .blob");
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) closeModal(true);
    if (e.target.closest(".auth-switch")) setMode(modal.dataset.mode === "signup" ? "login" : "signup");
  });
  form.addEventListener("input", () => setEmotion(face(), "curious"));
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(true); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    err.hidden = true;
    const go = modal.querySelector(".auth-go");
    setEmotion(face(), "thinking");
    try {
      await withSpinner(go, () => modal.dataset.mode === "signup" ? api.signup(f.email, f.password, f.name) : api.login(f.email, f.password));
      setEmotion(face(), "excited");
      await new Promise((r) => setTimeout(r, 380));
      closeModal(false);
      opts.toast?.(t("auth.welcome", { name: api.user.name || api.user.email }), "success");
      if (pending) { pending.res(api.user); pending = null; } else opts.onLogin?.();
      form.reset();
    } catch (ex) {
      setEmotion(face(), "sad");
      err.textContent = ex.message; err.hidden = false;
      modal.querySelector(".auth-card").classList.remove("shake"); void modal.offsetWidth; modal.querySelector(".auth-card").classList.add("shake");
    }
  });
}
function setMode(mode) {
  modal.dataset.mode = mode;
  const up = mode === "signup";
  modal.querySelector("#authTitle").textContent = t(up ? "auth.signupTitle" : "auth.loginTitle");
  modal.querySelector(".auth-sub").textContent = t(up ? "auth.signupSub" : "auth.sub");
  modal.querySelector(".auth-go .lbl").textContent = t(up ? "auth.signupGo" : "auth.loginGo");
  modal.querySelector(".auth-switch").textContent = t(up ? "auth.haveAccount" : "auth.noAccount");
  modal.querySelector(".auth-name").hidden = !up;
  modal.querySelector('[name="password"]').autocomplete = up ? "new-password" : "current-password";
  modal.querySelector(".auth-err").hidden = true;
  setEmotion(modal.querySelector(".auth-logo .blob"), up ? "happy" : "wink");
}
function openModal(mode) {
  setMode(mode);
  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("is-on"));
  setTimeout(() => modal.querySelector(mode === "signup" ? '[name="name"]' : '[name="email"]').focus(), 80);
}
function closeModal(cancelled) {
  modal.classList.remove("is-on");
  setTimeout(() => (modal.hidden = true), 220);
  if (cancelled && pending) { pending.rej(new Error("cancelled")); pending = null; }
}
export { esc as _esc };
