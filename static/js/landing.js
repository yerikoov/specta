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

  // how it works — bento with live-looking mocks
  const av = (id, emo, s = 20) => blobSVG(A[id], emo, { size: s, glow: false });
  document.getElementById("bento").innerHTML = `
    <div class="tile"><div><h3>${t("how.s1.t")}</h3><p>${t("how.s1.d")}</p></div>
      <div class="mock">
        <div class="m-file"><span class="ico">${icon("file-text", 18)}</span><div><b>tz_p2p_v3.docx</b><span>8 разделов · 27 пунктов · 2 стр.</span></div><span style="margin-left:auto">${av("parser", "curious", 28)}</span></div>
        <div class="m-progress"><i></i></div>
        <div class="m-sections"><div><span>3.2</span><span>Перевод подтверждается одноразовым SMS-кодом…</span></div>
          <div><span>3.3</span><span>Суточный лимит переводов — 500 000 ₸</span></div><div><span>4.1</span><span>Приложение должно работать быстро</span></div></div>
      </div></div>
    <div class="tile"><div><h3>${t("how.s2.t")}</h3><p>${t("how.s2.d")}</p></div>
      <div class="mock"><div class="m-chain">
        ${[["done", "contradictions", "surprised", "Согласованность", "5 противоречий", "warn"],
           ["done", "ambiguity", "surprised", "Ясность", "7 формулировок", "warn"],
           ["run", "regulatory", "curious", "Комплаенс", "проверяет KYC…", "run"],
           ["done", "critic", "wink", "Критик", "убрал 6 ложных", "ok"],
           ["skip", "security", "sleepy", "Безопасность", "не нужна", ""]].map(([st, id, emo, n, tag, c]) => `
          <div class="m-row"><span class="st ${st}">${st === "done" ? icon("check", 10) : ""}</span>${av(id, emo)}<b>${n}</b><span class="tag ${c}">${tag}</span></div>`).join("")}
      </div></div></div>
    <div class="tile tile--wide"><div><h3>${t("how.s3.t")}</h3><p>${t("how.s3.d")}</p></div>
      <div class="mock"><div class="m-chat">
        <div class="m-q"><div class="h">${av("contradictions", "angry", 22)}<b>Согласованность</b><span>· Критично · п. 3.3</span></div>
          <div class="t">Суточный лимит: какое значение верное?</div>
          <div class="m-opt on"><span class="k">A)</span>500 000 ₸ (как в п. 3.3)</div>
          <div class="m-opt"><span class="k">B)</span>1 000 000 тенге (как в п. 5.2)</div>
          <div class="m-opt"><span class="k">C)</span>Разные лимиты: до и после полной идентификации</div>
          <div class="m-opt"><span class="k">D)</span>Другое…</div></div>
        <div class="m-side">
          <div class="m-diff"><div class="r">п. 5.2</div><div class="o">Лимит переводов в сутки составляет <del>1 000 000 тенге</del>.</div>
            <div class="n">Лимит переводов в сутки составляет <ins>500 000 ₸</ins>.</div></div>
          <div class="m-score">${av("reporter", "happy", 26)}<b>58</b><span>/100</span><span class="up">+4</span><span style="margin-left:auto">Пересчитал оценку</span></div>
          <div class="m-score">${av("critic", "wink", 26)}<span>Перепроверил п. 5.2 — новых проблем нет.</span></div>
        </div>
      </div></div></div>
    <div class="tile"><div><h3>${t("how.s4.t")}</h3><p>${t("how.s4.d")}</p></div>
      <div class="mock">${matrixHtml("bentoDots")}</div></div>
    <div class="tile"><div><h3>${t("how.s5.t")}</h3><p>${t("how.s5.d")}</p></div>
      <div class="mock"><div class="m-doc">
        <div class="ln"><span>4.1</span>Приложение должно работать не более чем за 1 секунду для 95% запросов.</div>
        <div class="ln new"><span>9.1</span>Переводы доступны только клиентам, прошедшим полную идентификацию.</div>
        <div class="ln new"><span>11.1</span>Каждое требование подтверждается тест-кейсом TC-x.y.</div>
        <div class="m-dl"><span class="pri">${icon("download", 14)}Улучшенное ТЗ (.docx)</span><span>Отчёт (.md)</span><span>14 тест-кейсов</span></div>
      </div></div></div>`;

  // before → after playground
  const play = document.getElementById("play");
  play.innerHTML = `
    <div class="play__stage"><div class="play__center"><div id="playAv"></div>
        <div class="play__score"><span class="n" id="playN">4</span><span class="of">/10</span></div>
        <div class="play__quote" id="playQ"></div></div>
      <div class="play__foot"><span id="playFoot">score.total = 42</span><span>sample_tz_p2p.md</span></div></div>
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
    document.getElementById("playN").textContent = after ? "8" : "4";
    document.getElementById("playN").style.color = after ? "#7be08a" : "#ff9c9c";
    document.getElementById("playFoot").textContent = after ? "score.total = 86" : "score.total = 42";
    document.getElementById("playQ").textContent = after ? "35 замечаний закрыто, ТЗ можно отдавать в разработку." : "22 дефекта: размытые формулировки, противоречия в лимитах, нет KYC/AML.";
    const fix = document.getElementById("playFix");
    fix.classList.toggle("after", after);
    fix.textContent = after ? "4.1 Приложение должно работать не более чем за 1 секунду для 95% запросов." : "4.1 Приложение должно работать быстро.";
    drawInto(document.getElementById("playDots"), k);
  };
  play.querySelector("#playSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setPlay(+b.dataset.k); });
  setPlay(1);

  // coverage — API-style list
  const COV = [
    ["kyc_identification", "ПОД/ФТ", "Как банк идентифицирует отправителя и получателя: ИИН, документ, eGov, биометрия.", "критично"],
    ["aml_monitoring", "ПОД/ФТ", "Мониторинг подозрительных операций и передача сведений в АФМ.", "критично"],
    ["sanctions", "ПОД/ФТ", "Проверка по санкционным перечням и перечню лиц, связанных с терроризмом.", "важно"],
    ["pd_consent", "Закон о ПДн", "Согласие на обработку, хранение баз на территории РК, сроки хранения и маскирование.", "критично"],
    ["pci_dss", "Платёжные карты", "Токенизация, запрет хранения PAN, контур PCI DSS — если в ТЗ есть карты.", "критично"],
    ["nbrk_payments", "НБ РК", "Закон «О платежах и платёжных системах»: сроки исполнения, информирование клиента.", "важно"],
    ["encryption", "ИБ", "Шифрование при передаче (TLS 1.2+) и хранении, ключи в HSM.", "критично"],
    ["antifraud", "ИБ", "Антифрод-мониторинг и защита от социальной инженерии в P2P-переводах.", "критично"],
  ];
  document.getElementById("covList").innerHTML = COV.map(([id, type, d, sev]) => `
    <div class="api__item"><div class="api__name"><code>${id}</code><span>${type}</span></div><p>${d}</p>
      <div class="def">${t("cov.checks")}: <b>${sev}</b></div></div>`).join("");

  // banner
  document.getElementById("proCard").innerHTML = `
    <div><span class="pro__chip">${t("pro.chip")}</span><h3>${t("pro.title")}</h3><p>${t("pro.sub")}</p></div>
    <div><div class="pro__stats"><div><b>13</b><span>${t("pro.s1")}</span></div><div><b>8</b><span>${t("pro.s2")}</span></div>
      <div><b>5</b><span>${t("pro.s3")}</span></div><div><b>22/22</b><span>${t("pro.s4")}</span></div></div>
      <button class="btn btn-primary" data-action="sample">${t("pro.btn")}</button></div>`;

  // CTA
  document.getElementById("ctaAvatar").innerHTML = blobSVG(A.testability, "happy", { size: 120 });

  // reveal bars when scrolled in
  const io2 = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.querySelectorAll(".bar > i[data-w]").forEach((i) => (i.style.width = i.dataset.w + "%"));
    const dots = e.target.querySelector("#bentoDots");
    if (dots) drawInto(dots, 2);   // dots pop in when the tile scrolls into view
    io2.unobserve(e.target);
  }), { threshold: 0.25 });
  drawInto(document.getElementById("bentoDots"), 2);   // drawn right away, replayed when it scrolls into view
  document.querySelectorAll("#bento .tile").forEach((el) => io2.observe(el));
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
