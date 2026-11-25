import { blobSVG, setEmotion } from "./blobs.js";
import { drawMatrix } from "./dotscore.js";
import { createLiquidNav, NavIcons } from "./liquidnav.js";
import { PRODUCT_NAME } from "./config.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

// floating glass characters around the hero (x/y = % of the hero box)
// on scroll they circle around the title and drift away; only the one with `lead` drops into the team stage
const HERO_BLOBS = [
  { id: "contradictions", size: 150, x: 11, y: 27, emo: "surprised", d: 7.5 },
  { id: "dispatcher", size: 150, x: 31, y: 6, emo: "excited", d: 8.5, lead: true },
  { id: "ambiguity", size: 140, x: 66, y: 8, emo: "happy", d: 7 },
  { id: "parser", size: 132, x: 89, y: 26, emo: "thinking", d: 9 },
  { id: "completeness", size: 150, x: 9, y: 76, emo: "curious", d: 8 },
  { id: "testability", size: 150, x: 88, y: 74, emo: "wink", d: 7.8 },
  { id: "clarifier", size: 140, x: 50, y: 100, emo: "shy", d: 9.5 },
];
const FLY = 240;  // hero characters are drawn at stage size and scaled down, so they stay crisp when they grow

// team scrollytelling: each agent arrives calm ("neutral"), scrolling further switches it to its own state
const TEAM = [
  ["dispatcher", "excited"], ["completeness", "thinking"], ["ambiguity", "surprised"], ["contradictions", "angry"],
  ["testability", "focused"], ["regulatory", "curious"], ["security", "sleepy"], ["integrations", "sad"],
  ["critic", "wink"], ["clarifier", "shy"], ["reporter", "happy"],
];
const EMO_COLOR = {
  neutral: "#9a9aa6", curious: "#60a5fa", surprised: "#f5a524", angry: "#ff8080", happy: "#31c943", sleepy: "#80808c",
  sad: "#a48bff", wink: "#fb6adc", thinking: "#7cf5c8", focused: "#2fd6b5", excited: "#ffd166", shy: "#ff7ab6",
};

const CRIT = [["Полнота", 35, 85, "completeness"], ["Ясность", 30, 90, "clarity"], ["Тестируемость", 45, 88, "testability"],
  ["Согласованность", 40, 100, "consistency"], ["Комплаенс", 14, 70, "compliance"]];
const critItems = (k) => CRIT.map((c) => ({ key: c[3], label: c[0], value: c[k] }));
const BEFORE = Object.fromEntries(CRIT.map((c) => [c[3], c[1]]));
const matrixHtml = (id) => `<div class="dsc-body dsc-mini" id="${id}"><div class="dsc-tip"></div><div class="dsc-graph"></div></div>`;
const drawInto = (box, k) => drawMatrix(box.querySelector(".dsc-graph"), box.querySelector(".dsc-tip"), critItems(k), { before: k === 2 ? BEFORE : null });
const barColor = (v) => (v >= 75 ? "#31c943" : v >= 50 ? "#f5a524" : "#ff8080");

export function renderLanding(agents) {
  const A = Object.fromEntries(agents.map((a) => [a.id, a]));

  // brand
  const logo = blobSVG({ shape: "bumps", color: "#31c943" }, "neutral", { size: 22, glow: false });
  document.getElementById("brandLogo").innerHTML = logo;
  document.getElementById("brandLogo2").innerHTML = blobSVG({ shape: "bumps", color: "#31c943" }, "neutral", { size: 18, glow: false });

  // hero
  const heroBlobs = HERO_BLOBS.filter((b) => A[b.id]);
  document.getElementById("heroBlobs").innerHTML = heroBlobs.map((b, i) => `
    <div class="hero-blob" style="left:${b.x}%;top:${b.y}%"><div class="fly" style="transform:scale(${b.size / FLY})">
      <div class="fl" style="--i:${i};--d:${b.d}s;--delay:${-i * 1.1}s;--r0:${i % 2 ? 3 : -3}deg;--r1:${i % 2 ? -3 : 3}deg">
      ${blobSVG(A[b.id], b.emo, { size: FLY })}</div></div></div>`).join("");

  // team
  const list = document.getElementById("teamList");
  list.innerHTML = `<li class="team__intro"><h2>${t("team.title")}</h2><p>${t("team.sub")}</p></li>` +
    TEAM.filter(([id]) => A[id]).map(([id, emo], i) => `
      <li class="team__item" data-i="${i}"><div class="team__name">${A[id].name}</div>
        <div class="team__role">${A[id].role}</div><div class="team__desc">${A[id].line}</div></li>`).join("");
  const stage = document.getElementById("teamAvatar");
  const state = document.getElementById("teamState");
  const items = [...list.querySelectorAll(".team__item")];
  const small = () => matchMedia("(max-width: 720px)").matches;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let cur = -1, landed = false;
  const label = (emo) => { state.textContent = t("emo." + emo); state.style.setProperty("--c", EMO_COLOR[emo]); };
  // One step per agent: the next agent simply takes the stage, starting with the previous face,
  // and its eyes morph into its own emotion.
  const setActive = (i) => {
    if (i === cur) return;
    const prev = cur;
    cur = i;
    items.forEach((el) => el.classList.toggle("is-on", +el.dataset.i === i));
    const [id, emo] = TEAM[i];
    const was = prev < 0 || !landed || reduce ? emo : stage.querySelector(".blob")?.dataset.emotion || emo;
    stage.innerHTML = blobSVG(A[id], was, { size: small() ? 140 : 240 });
    if (was !== emo) setEmotion(stage.querySelector(".blob"), emo);
    label(emo);
  };
  stage._onLand = (v) => { landed = v; };
  setActive(0);
  initFlight(heroBlobs, stage);
  // the active agent is the item that holds the middle of the screen (items are tall, so no flicker)
  let traf = 0;
  const pick = () => {
    traf = 0;
    if (jumping) return;   // a nav jump is in progress: don't flip through every agent on the way
    const mid = innerHeight / 2;
    let best = 0;
    items.forEach((el, k) => { if (el.getBoundingClientRect().top <= mid) best = k; });
    setActive(best);
  };
  addEventListener("scroll", () => { if (!traf) traf = requestAnimationFrame(pick); }, { passive: true });
  initNav(pick);

  // how it works — steps on the left, a live product screen on the right that follows the active step
  const av = (id, emo, sz = 20) => blobSVG(A[id], emo, { size: sz, glow: false });
  const mark = (st) => st === "done"
    ? `<span class="tk-mark done">${icon("check", 11)}</span>`
    : st === "run"
      ? `<span class="tk-mark run"></span>`
      : `<span class="tk-mark"></span>`;
  const SCREENS = [
    { file: "Новая проверка", body: `
      <div class="up">
        <div class="up-drop">
          <span class="up-ico">${icon("upload", 20)}</span>
          <p>Перетащите ТЗ или <b>выберите файл</b></p>
          <small>DOCX, PDF, Markdown · до 15 МБ</small>
        </div>
        <div class="up-file">
          <span class="up-badge doc">${icon("file-text", 16)}</span>
          <div><b>tz_bnpl_v2.docx</b><span>8 разделов · 35 пунктов</span><i class="up-bar"><i></i></i></div>
          <em>78%</em>
        </div>
        <div class="up-file is-done">
          <span class="up-badge pdf">${icon("file", 16)}</span>
          <div><b>api_spec.pdf</b><span>Приложение · 12 стр.</span></div>
          <em class="ok">${icon("check", 13)}</em>
        </div>
      </div>` },
    { file: "Команда проверки", body: `
      <div class="tk">
        <div class="tk-h"><b>Команда проверяет</b><span>4 / 5</span></div>
        ${[["done", "contradictions", "surprised", "Согласованность", "5 противоречий", "готово"],
           ["done", "ambiguity", "surprised", "Ясность", "7 размытых формулировок", "готово"],
           ["run", "regulatory", "curious", "Комплаенс", "сверяет KYC и ПДн", "сейчас"],
           ["done", "testability", "happy", "Тестируемость", "6 непроверяемых", "готово"],
           ["done", "critic", "wink", "Критик", "снял 6 ложных", "готово"]].map(([st, id, emo, n, sub, tag]) => `
          <div class="tk-row ${st}">${mark(st)}${av(id, emo, 26)}<div><b>${n}</b><span>${sub}</span></div><em>${tag}</em></div>`).join("")}
      </div>` },
    { file: "Вопрос 1 из 18", body: `
      <div class="qn">
        <div class="qn-top">${av("contradictions", "angry", 22)}<b>Согласованность</b><span class="qn-n">1 из 18</span><span class="qn-dashes"><i class="on"></i><i></i><i></i></span></div>
        <h3>Сумма одной операции: какое значение верное?</h3>
        <p>В п. 3.4 и п. 5.2 стоят разные пределы.</p>
        <div class="qn-opt on"><span>1</span><div><b>500 000 ₸</b><small>как в п. 3.4</small></div><i></i></div>
        <div class="qn-opt"><span>2</span><div><b>300 000 ₸</b><small>как в п. 5.2</small></div><i></i></div>
        <div class="qn-opt"><span>3</span><div><b>Два предела</b><small>до и после полной идентификации</small></div><i></i></div>
        <div class="qn-foot"><span>1–3 — выбрать</span><span class="qn-go">Применить</span></div>
      </div>` },
    { file: "tz_bnpl_v3.docx", body: `
      <div class="df">
        <div class="df-h"><span>tz_bnpl_v3.docx</span><b class="add">+3</b><b class="del">−1</b></div>
        <div class="df-ln"><s>4.1</s><span>Страница оформления загружается не более чем за 1 с для 95% запросов.</span></div>
        <div class="df-ln del"><s>−</s><span>Максимальная сумма одной операции — 300 000 ₸</span></div>
        <div class="df-ln add"><s>+</s><span>Максимальная сумма одной операции — 500 000 ₸</span></div>
        <div class="df-ln add"><s>+</s><span>Операция доступна клиенту только после полной идентификации.</span></div>
        <div class="df-ln add"><s>+</s><span>Клиент даёт отдельное согласие на запрос в бюро.</span></div>
      </div>
      <div class="fs-dl"><span class="pri">${icon("download", 14)}Улучшенное ТЗ .docx</span><span>14 тест-кейсов</span><span>Ссылка для заказчика</span>
        <span class="ok">${icon("check", 14)}94 / 100</span></div>` },
  ];
  const how = document.getElementById("bento");
  how.className = "flow";
  how.innerHTML = `
    <ol class="flow__steps" role="tablist">${[1, 2, 3, 4].map((n, k) => `
      <li><button class="flow__step" role="tab" data-k="${k}" aria-selected="false">
        <span class="n">0${n}</span><span class="tx"><b>${t(`how.s${n}.t`)}</b><span>${t(`how.s${n}.d`)}</span></span>
        <i class="bar"><i></i></i></button></li>`).join("")}</ol>
    <div class="flow__screen" aria-live="polite">
      <div class="flow__bar"><span class="dots"><i></i><i></i><i></i></span><span class="name" id="flowName"></span><span class="brand">${PRODUCT_NAME}</span></div>
      <div class="flow__body" id="flowBody"></div>
    </div>`;
  const steps = [...how.querySelectorAll(".flow__step")];
  const body = document.getElementById("flowBody");
  const DUR = 5200;
  let step = -1, timer = 0;
  const show = (k, auto = false) => {
    step = k;
    steps.forEach((b, i) => { b.classList.toggle("is-on", i === k); b.setAttribute("aria-selected", i === k); });
    const strip = how.querySelector(".flow__steps");   // phones: the steps are a horizontal strip — keep the active one in view
    if (strip.scrollWidth > strip.clientWidth) strip.scrollTo({ left: steps[k].parentElement.offsetLeft - 20, behavior: reduce ? "auto" : "smooth" });
    how.style.setProperty("--dur", reduce ? "0ms" : `${DUR}ms`);
    document.getElementById("flowName").textContent = SCREENS[k].file;
    body.classList.remove("in"); void body.offsetWidth;
    body.innerHTML = SCREENS[k].body;
    body.classList.add("in");
    clearTimeout(timer);
    if (!reduce && !how.matches(":hover")) timer = setTimeout(() => show((k + 1) % SCREENS.length, true), DUR);
  };
  steps.forEach((b) => b.addEventListener("click", () => show(+b.dataset.k)));
  how.addEventListener("mouseenter", () => { clearTimeout(timer); how.classList.add("is-paused"); });
  how.addEventListener("mouseleave", () => { how.classList.remove("is-paused"); show(step); });
  // start when the section scrolls into view, so the first step isn't over before anyone sees it
  new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { show(0); o.disconnect(); } }, { threshold: 0.35 }).observe(how);
  show(0);
  clearTimeout(timer);

  // before → after playground
  const play = document.getElementById("play");
  play.innerHTML = `
    <div class="play__stage"><div class="play__center"><div id="playAv"></div>
        <div class="play__score"><span class="n" id="playN">42</span><span class="of">/100</span></div>
        <div class="play__quote" id="playQ"></div></div>
      <div class="play__foot"><span id="playFoot"></span><span>sample_tz_p2p.md</span></div></div>
    <div class="play__panel">
      <div class="play__head"><span>${t("ex.panel")}</span><span class="label">${icon("chart", 14)}</span></div>
      <div class="seg" id="playSeg"><button data-k="1" class="is-on">${t("ex.before")}</button><button data-k="2">${t("ex.after")}</button></div>
      <div><div class="plab">${t("ex.criteria")}</div>${matrixHtml("playDots")}</div>
      <div><div class="plab">${t("ex.fix")}</div><div class="pfix" id="playFix"></div></div>
    </div>`;
  const setPlay = (k) => {
    const after = k === 2;
    play.querySelectorAll("#playSeg button").forEach((b) => b.classList.toggle("is-on", +b.dataset.k === k));
    document.getElementById("playAv").innerHTML = blobSVG(A.reporter, after ? "happy" : "sad", { size: 130 });
    document.getElementById("playN").textContent = after ? "94" : "42";
    document.getElementById("playN").style.color = after ? "#7be08a" : "#ff9c9c";
    document.getElementById("playFoot").textContent = after ? t("ex.after") : t("ex.before");
    document.getElementById("playQ").textContent = after ? t("ex.cap2") : t("ex.cap1");
    const fix = document.getElementById("playFix");
    fix.classList.toggle("after", after);
    fix.textContent = after ? "4.1 Приложение должно работать не более чем за 1 секунду для 95% запросов." : "4.1 Приложение должно работать быстро.";
    drawInto(document.getElementById("playDots"), k);
  };
  play.querySelector("#playSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setPlay(+b.dataset.k); });
  setPlay(1);

  // coverage — the regulator's checklist as a grid of short tiles
  const COV = [
    ["user-check", "KYC", "Идентификация клиента", "crit"],
    ["activity", "AML", "Подозрительные операции", "crit"],
    ["shield", "Санкции", "Перечни АФМ", "imp"],
    ["lock", "ПДн", "Согласие и хранение в РК", "crit"],
    ["credit-card", "PCI DSS", "Карточные данные", "crit"],
    ["landmark", "НБ РК", "Закон о платежах", "imp"],
    ["key", "Шифрование", "TLS 1.2+, ключи в HSM", "crit"],
    ["alert-triangle", "Антифрод", "Социальная инженерия", "crit"],
  ];
  document.getElementById("covList").innerHTML = COV.map(([ic, name, d, sev], i) => `
    <div class="reg__tile ${sev}" style="--i:${i}"><span class="reg__ic">${icon(ic, 20)}</span>
      <b>${name}</b><span>${d}</span></div>`).join("");

  // numbers + trust
  document.getElementById("proCard").innerHTML = `
    <div class="pro__top"><span class="pro__chip">${t("pro.chip")}</span><h3>${t("pro.title")}</h3></div>
    <div class="pro__stats">
      <div><b>22<i>/22</i></b><span>${t("pro.s1")}</span></div>
      <div><b>~1<i> мин</i></b><span>${t("pro.s2")}</span></div>
      <div><b>54<i>→</i>20</b><span>${t("pro.s3")}</span></div>
      <div><b>0<i> ₸</i></b><span>${t("pro.s4")}</span></div>
    </div>
    <div class="pro__foot">
      <div class="pro__trust">${[["lock", "pro.t1"], ["server", "pro.t2"], ["shield", "pro.t3"]].map(([ic, k]) => `<span>${icon(ic, 15)}${t(k)}</span>`).join("")}</div>
      <button class="btn btn-primary" data-action="sample">${t("pro.btn")}${icon("arrow-right", 15)}</button>
    </div>`;

  // CTA
  document.getElementById("ctaAvatar").innerHTML = blobSVG(A.testability, "happy", { size: 120 });

}

/**
 * Scroll choreography: the hero characters circle around the title and drift away, while the lead
 * character peels off the circle and drops into the sticky team stage. Pure function of scroll
 * position, so it plays backwards too.
 */
function initFlight(blobs, stage) {
  const host = document.getElementById("heroBlobs");
  const hero = document.getElementById("hero");
  const team = document.getElementById("team");
  const items = [...host.querySelectorAll(".hero-blob")].map((el, i) => ({ el, fly: el.firstElementChild, b: blobs[i] }));
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const clamp = (v) => Math.max(0, Math.min(1, v));
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TURN = 1.7;  // radians the ring turns over the whole hero scroll
  let raf = 0, wasLanded = null;

  function frame() {
    raf = 0;
    const end = team.offsetTop - 64;                 // scroll position where the stage gets stuck
    const p = reduce ? 0 : clamp(scrollY / Math.max(1, end));
    const hr = hero.getBoundingClientRect();
    const cx = hr.left + hr.width / 2, cy = hr.top + hr.height * 0.45;
    const sr = stage.getBoundingClientRect();
    const tx = sr.left + sr.width / 2, ty = sr.top + sr.height / 2, tw = sr.width;
    for (const { el, fly, b } of items) {
      const r = el.getBoundingClientRect();
      const ps = r.width / FLY || 1;                  // parent scale (mobile shrinks the hero)
      const hx = r.left + r.width / 2, hy = r.top + r.height / 2;
      // position on the turning ring
      const a0 = Math.atan2(hy - cy, hx - cx), r0 = Math.hypot(hx - cx, hy - cy);
      const a = a0 + p * TURN, rad = r0 * (1 + 0.3 * p);
      let x = cx + Math.cos(a) * rad, y = cy + Math.sin(a) * rad;
      let sc = b.size / FLY, op = 1, rot = p * 16;
      if (b.lead) {
        const k = ease(clamp((p - 0.12) / 0.88));    // leaves the ring and falls into the stage
        x += (tx - x) * k; y += (ty - y) * k;
        sc += (tw / (FLY * ps) - sc) * k;
        rot *= 1 - k;
        op = p >= 0.995 ? 0 : 1;
      } else {
        sc *= 1 - 0.2 * p;
        op = 1 - clamp((p - 0.45) / 0.4);
      }
      fly.style.transform = p ? `translate(${(x - hx) / ps}px, ${(y - hy) / ps}px) rotate(${rot}deg) scale(${sc})` : `scale(${sc})`;
      fly.style.opacity = op;
    }
    const isLanded = p >= 0.995 || reduce;
    if (isLanded !== wasLanded) {
      wasLanded = isLanded;
      stage.classList.toggle("is-waiting", !isLanded);
      stage._onLand?.(isLanded);
    }
  }
  const ask = () => { if (!raf) raf = requestAnimationFrame(frame); };
  addEventListener("scroll", ask, { passive: true });
  addEventListener("resize", ask);
  frame();
}

// ---------------------------------------------------------------- liquid nav + calm section jumps
let jumping = false;
const SECTIONS = [["team", "nav.team", "team", "glow"], ["how", "nav.how", "how", "spin"], ["example", "nav.example", "chart", "drop"],
  ["coverage", "nav.coverage", "shield", "wave"]];

function initNav(afterJump) {
  const host = document.getElementById("liquidNav");
  if (!host || host.firstChild) return;
  const landing = document.getElementById("landing");
  const logo = blobSVG({ shape: "bumps", color: "#31c943" }, "neutral", { size: 22, glow: false });
  const nav = createLiquidNav(host, {
    tone: "dark",
    look: "glass",
    brand: `<span class="brand-logo">${logo}</span><span class="nimbus-brand-name">${PRODUCT_NAME}</span>`,
    onBrand: () => jumpTo("hero"),
    items: SECTIONS.map(([, key, ic, fx]) => ({ label: t(key), icon: NavIcons[ic], fx })),
    onChange: (i) => jumpTo(SECTIONS[i][0]),
  });
  // phones: the pill floats at the bottom of the screen. It must live in <body>: the blurred header and the
  // animated screen both become the containing block for position: fixed and would pin it in place.
  const navInner = host.parentElement, mq = matchMedia("(max-width: 720px)");
  const place = () => (mq.matches ? document.body.appendChild(host) : navInner.insertBefore(host, navInner.querySelector(".nav__account")));
  place();
  mq.addEventListener("change", place);
  // a jump fades the page out, moves instantly (no flipping through the team steps), and fades back in
  function jumpTo(id) {
    const el = document.getElementById(id);
    if (!el || jumping) return;
    jumping = true;
    landing.classList.add("is-jumping");
    setTimeout(() => {
      const html = document.documentElement, prev = html.style.scrollBehavior;
      html.style.scrollBehavior = "auto";
      scrollTo(0, id === "hero" ? 0 : el.getBoundingClientRect().top + scrollY - (id === "team" ? 0 : 64));
      html.style.scrollBehavior = prev;
      requestAnimationFrame(() => {
        jumping = false;
        afterJump();
        landing.classList.remove("is-jumping");
      });
    }, 240);
  }
  // scroll spy: the water follows the section you are reading
  let raf = 0;
  addEventListener("scroll", () => {
    if (raf || jumping) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      let k = 0;
      SECTIONS.forEach(([id], i) => { const el = document.getElementById(id); if (el && el.getBoundingClientRect().top < innerHeight * 0.45) k = i; });
      nav.setActive(k);
    });
  }, { passive: true });
}
