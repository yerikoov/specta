// Group chat of sub-agents. Renders ONLY the unified event schema — no agent-specific code.
import { api } from "./api.js";
import { blobSVG, setEmotion } from "./blobs.js";
import { escapeHtml as esc } from "./chain.js";
import { createDocPanel } from "./docpanel.js";
import { icon } from "./icons.js";
import { dotScoreCard } from "./dotscore.js";
import { auditItemHtml, auditLogHtml, refreshAuditLog, wireAuditLogs } from "./auditlog.js";
import { t } from "./i18n.js";

// few, calm entry points: the score lives in the header pill, a new upload is the back arrow
const PILLS = [["findings", "list"], ["improve", "sparkles"], ["tests", "flask"], ["report", "download"]];
const PIPELINE = ["dispatcher", "critic", "clarifier", "reporter"];

export function createChat({ sid, agentsById, title, onHome, toast }) {
  const top = document.getElementById("chatTop");
  const stream = document.getElementById("stream");
  const inner = document.getElementById("streamInner");
  const typing = document.getElementById("typing");
  const input = document.getElementById("msgInput");
  const send = document.getElementById("sendBtn");
  const form = document.getElementById("composer");
  const pill = document.getElementById("scorePill");
  const barAv = document.getElementById("barAvatars");
  const attachInput = document.getElementById("attachInput");
  document.getElementById("barFile").textContent = title || "";
  inner.innerHTML = ""; barAv.innerHTML = "";
  document.getElementById("chatHeroBlob").innerHTML = `<div class="fl">${blobSVG(agentsById.dispatcher || {}, "curious", { size: 104 })}</div>`;
  top.classList.remove("compact");

  const doc = createDocPanel(sid);
  const seen = new Set();
  const qcards = new Map();
  const fidToQ = new Map();
  const headerAv = new Map();
  let last = null, lastScore = null, scoreCount = 0, es = null, closed = false;

  // ---------------------------------------------------------------- helpers
  // follow new messages unless the user scrolled up to read
  let stick = true;
  const distance = () => stream.scrollHeight - stream.scrollTop - stream.clientHeight;
  const nearBottom = () => stick;
  let userScroll = 0;
  ["wheel", "touchmove", "keydown", "pointerdown"].forEach((e) => stream.addEventListener(e, () => (userScroll = Date.now()), { passive: true }));
  stream.onscroll = () => {
    if (distance() < 140) stick = true;
    else if (Date.now() - userScroll < 600) stick = false;   // only the user can un-stick
  };
  const scrollDown = (force) => {
    if (force) stick = true;
    if (stick) requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; });
  };
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const agent = (id) => agentsById[id] || { id, name: id, role: "", shape: "cloud", color: "#a48bff" };
  const setTyping = (on) => { typing.hidden = !on; if (on) scrollDown(); };

  function ensureHeaderAvatar(id, emo = "neutral") {
    if (headerAv.has(id)) return headerAv.get(id);
    const a = agent(id);
    const span = document.createElement("span");
    span.className = "av";
    span.innerHTML = `${blobSVG(a, emo, { size: 30, glow: false })}<span class="tip">${esc(a.name)}</span>`;
    barAv.appendChild(span);
    headerAv.set(id, span);
    return span;
  }
  function setState(id, emo) {
    if (!emo || !agentsById[id]) return;
    const span = headerAv.get(id);
    if (span) setEmotion(span.querySelector(".blob"), emo);
  }

  function shell(ev, inner_html, cls = "") {
    const a = agent(ev.agent);
    const cont = last && last.agent === ev.agent && ev.ts - last.ts < 90 && !["score", "done", "question"].includes(ev.type) && !["question", "score"].includes(last.type) && !last.data?.group;
    const el = document.createElement("div");
    el.className = `msg msg--${ev.type} ${cont ? "cont" : ""} ${cls}`;
    el.dataset.agent = ev.agent;
    el.innerHTML = `
      <div class="msg-avatar">${blobSVG(a, ev.emotion, { size: 40 })}</div>
      <div class="msg-body">
        <div class="msg-meta"><span class="msg-name">${esc(a.name)}</span>${ev.data?.to && agentsById[ev.data.to]
          ? `<span class="to-tag">→ ${chipHtml(agent(ev.data.to))}</span>` : `<span class="role-tag">${esc(a.role)}</span>`}<time>${time(ev.ts)}</time></div>
        ${inner_html}
      </div>`;
    last = ev;
    return el;
  }

  const chipHtml = (a) => `<span class="agent-chip" data-id="${esc(a.id)}" data-name="${esc(a.name)}" style="--ac:${a.color}">${blobSVG(a, "happy", { size: 18, glow: false, star: false })}<b>${esc(a.name)}</b></span>`;
  const sevLabel = (s) => `<span class="sev ${s}">${t("sev." + s)}</span>`;
  const refChip = (ref, fid) => ref ? `<button class="ref-chip" data-ref="${esc(ref)}" data-fid="${fid || ""}">п. ${esc(ref)}</button>` : "";
  const list = (items) => items?.length ? `<ul class="msg-list">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";

  function testsHtml(tests, open = false) {
    if (!tests?.length) return "";
    return `<details class="tests" ${open ? "open" : ""}><summary>${icon("chevron-down", 14)}${t("done.tests")} (${tests.length})</summary>
      <div class="tcases">${tests.map((tc) => `<div class="tcase"><span class="tid">${esc(tc.id)}</span><span class="tt">${esc(tc.title)}</span>
        <dl><dt>${t("done.given")}</dt><dd>${esc(tc.given)}</dd><dt>${t("done.when")}</dt><dd>${esc(tc.when)}</dd><dt>${t("done.then")}</dt><dd>${esc(tc.then)}</dd></dl></div>`).join("")}</div></details>`;
  }

  function diffHtml(d) {
    const a = d.old || "", b = d.new || "";
    let p = 0;
    while (p < a.length && p < b.length && a[p] === b[p]) p++;
    let s = 0;
    while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
    const old = a ? `<div class="diff-old">${esc(a.slice(0, p))}<del>${esc(a.slice(p, a.length - s))}</del>${esc(a.slice(a.length - s))}</div>` : "";
    const neu = `<div class="diff-new">${esc(b.slice(0, p))}<ins>${esc(b.slice(p, b.length - s))}</ins>${esc(b.slice(b.length - s))}</div>`;
    return `<div class="diff"><div class="diff-ref">п. ${esc(d.section_ref)}</div>${old}${neu}</div>`;
  }

  function animateNumber(el, from, to, dur = 900) {
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function barsHtml(criteria, prev) {
    return `<div class="bars">${criteria.map((c) => `
      <div class="bar-row"><span>${esc(c.label)}</span><div class="bar"><i data-w="${c.value}" style="width:${prev ? (prev.find((p) => p.key === c.key)?.value ?? 0) : 0}%;background:${barColor(c.value)}"></i></div><span class="v">${c.value}</span></div>`).join("")}</div>`;
  }
  const barColor = (v) => (v >= 75 ? "#31c943" : v >= 50 ? "#f5a524" : "#ff8080");

  // ---------------------------------------------------------------- groups
  // A status event with data.group creates a container card; later events with data.in = its id
  // render inside it (into data.row when the group has rows, or into data.footer). A question card is
  // a container too: events with data.in = question_id become its thread. Generic, no agent-specific code.
  const groups = new Map();
  const countsHtml = (c) => ["critical", "important", "minor"].filter((k) => c?.[k])
    .map((k) => `<span class="cnt ${k}" title="${t("sev." + k)}">${c[k]}</span>`).join("") || `<span class="cnt ok">${icon("check", 13)}</span>`;

  function groupHtml(g) {
    const rows = (g.rows || []).map((r) => {
      const a = agent(r.agent);
      return `<details class="brow is-pending" data-row="${esc(r.agent)}">
        <summary><span class="brow-av">${blobSVG(a, "curious", { size: 30, glow: false })}</span>
          <span class="brow-main"><b>${esc(a.name)}</b><span class="brow-text">${esc(r.text || a.role)}</span></span>
          <span class="brow-counts"><span class="spin"></span></span><span class="brow-chev">${icon("chevron-down", 15)}</span></summary>
        <div class="brow-body"><div class="al"><div class="al-list"></div></div></div></details>`;
    }).join("");
    const who = g.rows ? g.rows.map((r) => r.agent) : g.agents || [];
    const avs = g.collapsed ? `<span class="group-avs">${who.map((id) =>
      `<span class="gav ${g.rows ? "is-pending" : ""}" data-row="${esc(id)}">${blobSVG(agent(id), "curious", { size: 24, glow: false, star: false })}</span>`).join("")}</span>` : "";
    return `<div class="mcard group ${g.collapsed ? "collapsed" : ""}" data-gid="${esc(g.id)}">
      <${g.collapsed ? "button" : "div"} class="group-head">${avs}<span class="group-title">${esc(g.title || "")}</span>${g.rows ? `<span class="group-prog">0 / ${g.rows.length}</span>` : ""}${g.collapsed ? `<span class="group-chev">${icon("chevron-down", 16)}</span>` : ""}</${g.collapsed ? "button" : "div"}>
      ${g.rows ? `<div class="group-rows">${rows}</div>` : `<div class="group-lines"></div>`}
      <div class="group-foot" hidden></div></div>`;
  }

  function registerGroup(el, g) {
    const card = el.querySelector(`.group[data-gid="${CSS.escape(g.id)}"]`);
    groups.set(g.id, { card, done: 0, total: (g.rows || []).length, sum: 0 });
    if (g.collapsed) card.querySelector(".group-head").addEventListener("click", () => card.classList.toggle("collapsed"));
    card.querySelectorAll(".brow").forEach((d) => d.querySelector("summary").addEventListener("click", (e) => {
      if (!d.classList.contains("has-items")) e.preventDefault();
    }));
  }

  // compact, in-container renderings of the same unified events
  // a finding event as an audit-log record
  const logItem = (ev) => ({
    id: ev.id, fid: ev.data?.finding_id || "", title: ev.text, description: ev.quote ? `«${ev.quote}»` : "",
    timestamp: ev.section_ref ? `п. ${ev.section_ref}` : t("log.whole"), actor: agent(ev.agent).name,
    type: ev.data?.criterion_label || "", status: t("sev." + ev.severity), severity: ev.severity, ref: ev.section_ref || "",
  });
  const C = {
    finding(ev) {
      return `<div class="al"><div class="al-list">${auditItemHtml({ ...logItem(ev) })}</div></div>`;
    },
    applied(ev) {
      const d = ev.data || {};
      const cls = d.undo ? "undo" : d.auto ? "auto" : "";
      return `<div class="tline ${cls}"><span class="tl-av">${blobSVG(agent(ev.agent), ev.emotion, { size: 22, glow: false, star: false })}</span>
        <div class="tl-body"><div class="applied-line">${icon(d.undo ? "undo" : "check", 14)}<span>${esc(ev.text)}</span></div>
        ${(d.diff || []).slice(0, 3).map(diffHtml).join("")}</div></div>`;
    },
    status(ev) {
      return `<div class="tline"><span class="tl-av">${blobSVG(agent(ev.agent), ev.emotion, { size: 22, glow: false, star: false })}</span>
        <div class="tl-body"><div class="tl-text">${esc(ev.text)}</div>${list(ev.data?.items)}</div></div>`;
    },
    score(ev) {
      const d = ev.data, delta = d.prev != null ? d.total - d.prev : 0;
      return `<div class="sline"><span class="sl-label">${esc(ev.text)}</span>
        <span class="sl-num"><b>${d.total}</b>/100</span>${delta ? `<span class="s-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "+" : ""}${delta}</span>` : ""}
        <span class="sl-bar"><i style="width:${d.prev ?? d.total}%" data-w="${d.total}"></i></span></div>`;
    },
  };

  function intoGroup(ev) {
    const d = ev.data || {};
    // question thread
    if (qcards.has(d.in)) {
      const card = qcards.get(d.in);
      if (ev.type === "applied") applyToCards(ev);
      if (ev.type === "score") updatePill(d.total, lastScore?.total), (lastScore = d);
      if (!C[ev.type]) return false;
      if (ev.type === "applied" && d.undo && d.question_id === d.in) card.querySelector(".q-thread").innerHTML = "";
      card.querySelector(".q-thread").insertAdjacentHTML("beforeend", C[ev.type](ev));
      return card;
    }
    const g = groups.get(d.in);
    if (!g) return false;
    if (ev.type === "applied") applyToCards(ev);
    if (d.footer) {
      const foot = g.card.querySelector(".group-foot");
      foot.hidden = false;
      foot.innerHTML = `<div class="gf-text">${blobSVG(agent(ev.agent), ev.emotion, { size: 22, glow: false, star: false })}<span>${esc(ev.text)}</span></div>
        ${d.items?.length ? `<details class="gf-more"><summary>${icon("chevron-down", 14)}${t("chat.details")} (${d.items.length})</summary>${list(d.items)}</details>` : ""}`;
      return g.card;
    }
    const row = d.row && g.card.querySelector(`.brow[data-row="${CSS.escape(d.row)}"]`);
    if (row && ev.type === "status") {
      if (row.classList.contains("is-pending")) {
        g.done++;
        g.sum += Object.values(d.counts || {}).reduce((a, b) => a + b, 0);
        g.card.querySelector(".group-prog").textContent = g.done === g.total ? t("chat.issues", { n: g.sum }) : `${g.done} / ${g.total}`;
        if (g.done === g.total) g.card.classList.add("is-done");
      }
      const gav = g.card.querySelector(`.gav[data-row="${CSS.escape(d.row)}"]`);
      if (gav) { gav.classList.remove("is-pending"); setEmotion(gav.querySelector(".blob"), ev.emotion); }
      row.classList.remove("is-pending");
      row.querySelector(".brow-text").textContent = ev.text;
      row.querySelector(".brow-counts").innerHTML = countsHtml(d.counts);
      setEmotion(row.querySelector(".blob"), ev.emotion);
      row.classList.add("flash-in");
      return g.card;
    }
    if (row && ev.type === "finding") {
      row.classList.add("has-items");
      const al = row.querySelector(".brow-body .al");
      al.querySelector(".al-list").insertAdjacentHTML("beforeend", auditItemHtml({ ...logItem(ev), actor: "" }));  // the row already names the agent
      refreshAuditLog(al);
      return g.card;
    }
    const lines = g.card.querySelector(".group-lines");
    if (lines && C[ev.type]) {
      lines.insertAdjacentHTML("beforeend", C[ev.type](ev));
      const n = lines.children.length;
      if (n > 3 && !g.card.querySelector(".group-avs")) {  // long groups stay short: first 3 lines + "show all"
        let more = g.card.querySelector(".group-more");
        if (!more) {
          lines.insertAdjacentHTML("afterend", `<button class="group-more">${icon("chevron-down", 14)}<span></span></button>`);
          more = g.card.querySelector(".group-more");
          more.onclick = () => g.card.classList.toggle("expanded");
        }
        more.querySelector("span").textContent = t("chat.showAll", { n });
      }
      return g.card;
    }
    return false;
  }

  function applyToCards(ev) {
    const d = ev.data || {};
    if (d.question_id && qcards.has(d.question_id)) {
      const card = qcards.get(d.question_id);
      if (d.skipped) { markAnswered(card, "", t("chat.skipped")); card.classList.add("is-skipped"); }
      else if (d.split) markAnswered(card, "", t("chat.split"));
      else if (d.undo) reopen(card); else markAnswered(card, d.auto ? t("chat.auto") : (d.choice_key === "custom" ? t("chat.other").replace("…", "") : d.choice_key), d.auto ? "" : d.label);
    }
    doc.refreshSoon();
  }

  // ---------------------------------------------------------------- summary + actions
  const actionsHtml = (acts) => acts?.length ? `<div class="msg-actions">${acts.map((a) =>
    `<button class="btn ${a.primary ? "btn-primary" : "btn-outline"} btn-sm act-btn" data-cmd="${esc(a.cmd)}">${esc(a.label)}${a.primary ? icon("arrow-right", 15) : ""}</button>`).join("")}</div>` : "";

  // first thing after upload: the dot-matrix score card, plus the verdict, what is wrong and what to do
  function summaryCard(d, title) {
    const s = d.summary, c = s.counts;
    const chip = (k) => c[k] ? `<span class="sum-cnt ${k}">${c[k]} ${t("sum." + k)}</span>` : "";
    const head = `<p class="sum-verdict${s.warning ? " warn" : ""}">${s.warning ? icon("info", 16) : ""}${esc(s.verdict)}</p><div class="sum-counts">${chip("critical")}${chip("important")}${chip("minor")}</div>`;
    const foot = `${s.top.length ? `<div class="sum-issues"><div class="sum-h">${t("sum.top")}</div>${s.top.map((x) => `
        <button class="sum-issue" data-ref="${esc(x.ref)}" data-fid="${esc(x.fid)}"><span class="sum-dot ${x.severity}"></span>
          <span class="sum-txt">${esc(x.text)}</span>${x.ref ? `<span class="sum-ref">п. ${esc(x.ref)}</span>` : ""}</button>`).join("")}</div>` : ""}
      ${actionsHtml(s.actions)}`;
    const card = dotScoreCard(d, title, { head, foot });
    card.classList.add("sumcard");
    return card;
  }

  // ---------------------------------------------------------------- renderers
  const R = {
    status(ev) {
      const d = ev.data || {};
      const el = shell(ev, `<div class="msg-text">${esc(ev.text)}</div>${list(d.items)}${testsHtml(d.tests, true)}${d.group ? groupHtml(d.group) : ""}${d.log?.length ? `<div class="mcard logcard">${auditLogHtml(d.log, { filters: d.log.length > 3 })}</div>` : ""}${actionsHtml(d.actions)}`);
      el.querySelectorAll(".al").forEach(refreshAuditLog);
      if (d.group) registerGroup(el, d.group);
      if (d.team) {
        [...d.team, ...PIPELINE].forEach((id) => ensureHeaderAvatar(id, d.states?.[id] || "neutral"));
      }
      if (d.scroll_to && qcards.has(d.scroll_to)) {
        const c = qcards.get(d.scroll_to);
        setTimeout(() => { c.scrollIntoView({ behavior: "smooth", block: "center" }); c.classList.remove("flash"); void c.offsetWidth; c.classList.add("flash"); }, 200);
      }
      return el;
    },
    finding(ev) {
      return shell(ev, `<div class="mcard logcard">${C.finding(ev)}</div>`);
    },
    question(ev) {
      const d = ev.data || {};
      const qid = d.question_id;
      const el = shell(ev, `<div class="mcard qcard ${ev.severity}" data-qid="${qid}">
        <div class="q-full">
          ${d.total ? `<div class="q-progress"><i style="width:${Math.round(((d.n - 1) / d.total) * 100)}%"></i></div>` : ""}
          <div class="card-head">${d.total ? `<span class="q-n">${t("chat.qn", { n: d.n, total: d.total })}</span>` : ""}${sevLabel(ev.severity)}${refChip(ev.section_ref, d.finding_id)}</div>
          <div class="q-text">${esc(ev.text)}</div>
          ${ev.quote ? `<button class="quote" data-ref="${esc(ev.section_ref || "")}" data-fid="${d.finding_id || ""}">«${esc(ev.quote)}»</button>` : ""}
          ${d.items?.length ? `<ul class="q-items">${d.items.map((it) => `<li class="${it.severity}"><button class="q-item" data-ref="${esc(it.ref.startsWith("п. ") ? it.ref.slice(3) : "")}" data-fid="${esc(it.fid)}">
              <span class="qi-ref">${esc(it.ref)}</span><span class="qi-q">${esc(it.text)}</span><span class="qi-fix">${icon("arrow-right", 12)}${esc(it.fix)}</span></button></li>`).join("")}</ul>` : ""}
          ${d.why ? `<div class="q-why">${esc(d.why)}</div>` : ""}
          ${d.popular ? `<div class="q-popular">${icon("sparkles", 13)}${esc(t("chat.popular", d.popular))}</div>` : ""}
          ${d.also?.length ? `<div class="q-also">${t("chat.also")} ${d.also.map((id) => chipHtml({ ...agent(id), id })).join(" ")}</div>` : ""}
          <div class="q-opts">
            ${ev.options.map((o, i) => `<button class="q-opt" data-key="${o.key}"><span class="k">${String.fromCharCode(65 + i)}</span><span>${esc(o.label)}</span></button>`).join("")}
            ${ev.allow_custom ? `<button class="q-opt q-other"><span class="k">${String.fromCharCode(65 + ev.options.length)}</span><span>${t("chat.other")}</span></button>
            <div class="q-custom"><textarea rows="1" placeholder="${t("chat.otherPh")}"></textarea><button class="btn btn-primary btn-sm q-send">${t("chat.send")}</button></div>` : ""}
          </div>
          <div class="q-foot"><button class="q-skip">${t("chat.skip")}</button></div>
        </div>
        <div class="q-answered"><span class="ok">${icon("check", 16)}</span><span class="q-sum"></span>
          <button class="btn btn-ghost btn-xs q-undo">${icon("undo", 13)} ${t("chat.undo")}</button></div>
        <div class="q-thread"></div>
      </div>`);
      const card = el.querySelector(".qcard");
      card._options = ev.options;
      card._text = ev.text;
      qcards.set(qid, card);
      if (d.finding_id) fidToQ.set(d.finding_id, qid);
      wireQuestion(card, qid);
      return el;
    },
    applied(ev) {
      applyToCards(ev);
      return shell(ev, C.applied(ev).replace('class="tline', 'class="tline solo'));
    },
    score(ev) {
      const d = ev.data;
      const el = shell(ev, "");
      el.querySelector(".msg-body").appendChild(d.summary ? summaryCard(d, ev.text) : dotScoreCard(d, ev.text));
      updatePill(d.total, lastScore?.total);
      lastScore = d;
      return el;
    },
    done(ev) {
      const d = ev.data;
      updatePill(d.after.total, lastScore?.total);
      lastScore = d.after;
      return shell(ev, `<div class="mcard dcard">
        <div class="msg-text">${esc(ev.text)}</div>
        <div class="d-ba"><span class="n before">${d.before.total}</span>${icon("arrow-right", 20)}<span class="n after">${d.after.total}</span><span class="of">/100</span></div>
        ${barsHtml(d.after.criteria, d.before.criteria)}
        ${testsHtml(d.tests)}
        ${d.summary ? `<div class="d-sum"><div class="d-sum-h">${esc(d.summary.headline)}</div><p>${esc(d.summary.verdict)}</p>
          ${d.summary.highlights?.length ? `<ul class="msg-list">${d.summary.highlights.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>` : ""}
        <div class="d-actions">${d.downloads.map((x, i) => `<a class="btn ${i === 0 ? "btn-primary" : "btn-outline"} btn-sm" href="${api.withKey(x.url)}" download>${i === 0 ? icon("download", 15) : ""}${esc(x.label)}</a>`).join("")}
          ${d.share ? `<button class="btn btn-outline btn-sm d-share">${icon("external", 15)}${t("share.button")}</button>` : ""}</div>
        <div class="d-link" hidden></div>
      </div>`);
    },
  };

  function updatePill(total, prev) {
    pill.querySelector(".sp-num").textContent = total;
    if (prev != null && total !== prev) {
      pill.classList.add("bump");
      setTimeout(() => pill.classList.remove("bump"), 1200);
    }
  }

  function markAnswered(card, key, label) {
    card.classList.remove("is-busy");
    card.classList.add("answered");
    card.querySelector(".q-sum").innerHTML = key ? `${t("chat.answer")}: <b>${esc(key)}</b>${label ? " — " + esc(label) : ""}` : esc(label);
    card.querySelector(".q-undo").hidden = !key || key === t("chat.auto");
  }
  function reopen(card) {
    card.classList.remove("answered", "is-busy");
    card.querySelectorAll(".q-opt").forEach((b) => b.classList.remove("is-chosen"));
  }

  function wireQuestion(card, qid) {
    const answer = async (body, btn) => {
      card.classList.add("is-busy");
      btn?.classList.add("is-chosen");
      stick = true;  // answering means "show me what happens next"
      setTyping(true);
      try { await api.answer(sid, { question_id: qid, ...body }); }
      catch (e) { toast(e.message, "error"); reopen(card); setTyping(false); }
    };
    card.querySelectorAll(".q-opt[data-key]").forEach((b) => b.addEventListener("click", () => answer({ choice_key: b.dataset.key }, b)));
    const other = card.querySelector(".q-other");
    const box = card.querySelector(".q-custom");
    if (other) {
      const ta = box.querySelector("textarea");
      other.addEventListener("click", () => { box.classList.toggle("open"); if (box.classList.contains("open")) ta.focus(); });
      const submit = () => ta.value.trim() && answer({ custom_text: ta.value.trim() });
      box.querySelector(".q-send").addEventListener("click", submit);
      ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
    }
    card.querySelector(".q-skip")?.addEventListener("click", async () => {
      card.classList.add("is-busy"); stick = true; setTyping(true);
      try { await api.message(sid, qid, "skip"); } catch (e) { toast(e.message, "error"); card.classList.remove("is-busy"); setTyping(false); }
    });
    card.querySelector(".q-undo").addEventListener("click", async () => {
      try { await api.undo(sid, qid); setTyping(true); } catch (e) { toast(e.message, "error"); }
    });
  }

  // audit logs: click → document, right click / "…" → menu
  const flashCard = (c) => { c.scrollIntoView({ behavior: "smooth", block: "center" }); c.classList.remove("flash"); void c.offsetWidth; c.classList.add("flash"); };
  wireAuditLogs(inner, {
    open: (d) => doc.focus(d.ref, d.fid),
    review: (d) => { const c = qcards.get(fidToQ.get(d.fid)); if (c) flashCard(c); },
    canReview: (d) => qcards.has(fidToQ.get(d.fid)),
  });

  // clicks on section refs / quotes → document panel
  inner.onclick = (e) => {   // assigned, not added: the stream element is reused between sessions
    const act = e.target.closest(".act-btn");
    if (act) {
      act.closest(".msg-actions").classList.add("is-used");   // one choice per message
      stick = true;
      return command(act.dataset.cmd, act.textContent.trim());
    }
    const sh = e.target.closest(".d-share");
    if (sh) {
      api.share(sid).then(async (r) => {
        const box = sh.closest(".dcard").querySelector(".d-link");
        box.hidden = false;
        box.innerHTML = `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a>`;
        try { await navigator.clipboard.writeText(r.url); toast(t("share.copied"), "success"); } catch { toast(t("share.ready")); }
      }).catch((ex) => toast(ex.message, "error"));
      return;
    }
    const issue = e.target.closest(".sum-issue");
    if (issue) return doc.focus(issue.dataset.ref, issue.dataset.fid);
    const b = e.target.closest(".ref-chip, .quote, .q-item");
    if (b) doc.focus(b.dataset.ref, b.dataset.fid);
  };

  function handle(ev) {
    if (seen.has(ev.id)) return;
    seen.add(ev.id);
    setTyping(false);
    const r = R[ev.type];
    if (!r) return;
    const force = nearBottom();
    if (!top.classList.contains("compact")) top.classList.add("compact");
    ensureHeaderAvatar(ev.agent, ev.emotion);
    const into = ev.data?.in && intoGroup(ev);
    const node = into || r(ev);
    if (!into) inner.appendChild(node);
    setTimeout(() => node.querySelectorAll(".bar > i[data-w]").forEach((i) => (i.style.width = i.dataset.w + "%")), 80);
    setState(ev.agent, ev.emotion);
    if (ev.data?.states) Object.entries(ev.data.states).forEach(([id, emo]) => setState(id, emo));
    scrollDown(force);
  }

  // ---------------------------------------------------------------- composer
  // The composer is a contenteditable line: agents tagged with "@" become inline chips (icon + name in the
  // agent's colour). Several chips = the agents discuss the question between themselves.
  const getText = () => {
    let out = "";
    const walk = (n) => n.childNodes.forEach((c) => {
      if (c.nodeType === 3) out += c.textContent;
      else if (c.classList?.contains("agent-chip")) out += `@${c.dataset.name}`;
      else if (c.nodeName === "BR") out += "\n";
      else { if (c.nodeName === "DIV" && out && !out.endsWith("\n")) out += "\n"; walk(c); }
    });
    walk(input);
    return out.replace(/ /g, " ");
  };
  const refresh = () => {
    const txt = getText();
    input.classList.toggle("is-empty", !txt.trim() && !input.querySelector(".agent-chip"));
    send.disabled = !txt.trim();
  };
  const clear = () => { input.innerHTML = ""; refresh(); };
  input.dataset.placeholder = t("chat.placeholder");
  const pop = form.querySelector(".mention-pop") || form.appendChild(Object.assign(document.createElement("div"), { className: "mention-pop", role: "listbox" }));
  pop.hidden = true;
  let mItems = [], mIdx = 0;
  const mentionAt = () => {   // the "@query" right before the caret, inside one text node
    const sel = getSelection();
    if (!sel.rangeCount || !input.contains(sel.anchorNode) || sel.anchorNode.nodeType !== 3) return null;
    const node = sel.anchorNode, pos = sel.anchorOffset;
    const m = node.textContent.slice(0, pos).match(/(^|\s)@([А-Яа-яЁёA-Za-z]*)$/);
    return m ? { q: m[2].toLowerCase(), node, start: pos - m[2].length - 1, end: pos } : null;
  };
  const tagged = () => [...input.querySelectorAll(".agent-chip")].map((c) => c.dataset.id);
  function roster() {
    const team = [...headerAv.keys()];
    return Object.values(agentsById).filter((a) => a.id !== "parser")
      .sort((a, b) => (team.includes(b.id) - team.includes(a.id)) || a.name.localeCompare(b.name, "ru"));
  }
  function updateMention() {
    const at = mentionAt();
    if (!at) { pop.hidden = true; return; }
    const all = roster().filter((a) => !tagged().includes(a.id));   // name matches first, then role matches
    mItems = [...all.filter((a) => a.name.toLowerCase().startsWith(at.q)),
              ...all.filter((a) => !a.name.toLowerCase().startsWith(at.q) && at.q && a.role.toLowerCase().includes(at.q))].slice(0, 8);
    mIdx = Math.min(mIdx, Math.max(0, mItems.length - 1));
    pop.innerHTML = mItems.length ? mItems.map((a, i) => `<button type="button" class="mention-opt ${i === mIdx ? "is-on" : ""}" data-i="${i}" role="option">
        ${blobSVG(a, headerAv.has(a.id) ? "happy" : "sleepy", { size: 26, glow: false, star: false })}<span><b>${esc(a.name)}</b><small>${esc(a.role)}</small></span></button>`).join("")
      : `<div class="mention-empty">${t("chat.mentionEmpty")}</div>`;
    pop.hidden = false;
  }
  function pickMention(i) {
    const a = mItems[i], at = mentionAt();
    if (!a || !at) return;
    const { node } = at;
    const after = node.splitText(at.start);        // "…text " | "@que|ry rest"
    after.textContent = after.textContent.slice(at.end - at.start);
    const chip = document.createElement("span");
    chip.innerHTML = chipHtml(a);
    const el = chip.firstElementChild;
    el.contentEditable = "false";
    node.parentNode.insertBefore(el, after);
    if (!after.textContent.startsWith(" ")) after.textContent = " " + after.textContent;
    const r = document.createRange();
    r.setStart(after, 1); r.collapse(true);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    pop.hidden = true;
    input.focus(); refresh();
  }
  pop.addEventListener("mousedown", (e) => { const b = e.target.closest(".mention-opt"); if (b) { e.preventDefault(); pickMention(+b.dataset.i); } });
  document.getElementById("mentionBtn").onclick = () => {
    input.focus();
    const txt = getText();
    document.execCommand("insertText", false, txt && !/\s$/.test(txt) ? " @" : "@");
    mIdx = 0; updateMention();
  };
  input.addEventListener("paste", (e) => { e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain")); });
  input.onblur = () => setTimeout(() => (pop.hidden = true), 120);
  input.onclick = updateMention;
  input.oninput = () => { if (!input.textContent && !input.querySelector(".agent-chip")) input.innerHTML = ""; refresh(); mIdx = 0; updateMention(); };
  input.onkeyup = (e) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) updateMention(); };
  input.onkeydown = (e) => {
    if (!pop.hidden && mItems.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        mIdx = (mIdx + (e.key === "ArrowDown" ? 1 : -1) + mItems.length) % mItems.length;
        updateMention(); return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && !e.isComposing) { e.preventDefault(); pickMention(mIdx); return; }
    }
    if (e.key === "Escape") { pop.hidden = true; return; }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  };
  refresh();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const text = getText().replace(/\s+\n/g, "\n").trim();
    if (!text) return;
    clear(); send.disabled = true;
    userBubble(text);
    setTyping(true);
    try { await api.message(sid, text); } catch (err) { toast(err.message, "error"); setTyping(false); }
  };
  function userBubble(text) {
    const el = document.createElement("div");
    el.className = "msg msg--user";
    const byName = Object.fromEntries(Object.values(agentsById).map((a) => [a.name.toLowerCase(), a]));
    const html = esc(text).replace(/@([А-Яа-яЁёA-Za-z]+)/g, (m, n) => (byName[n.toLowerCase()] ? chipHtml(byName[n.toLowerCase()]) : m));
    el.innerHTML = `<div class="user-bubble">${html}</div>`;
    inner.appendChild(el);
    last = null;
    top.classList.add("compact");
    scrollDown(true);
  }
  attachInput.onchange = async () => {
    const f = attachInput.files[0];
    attachInput.value = "";
    if (!f) return;
    userBubble(`📎 ${f.name}`);
    setTyping(true);
    try { await api.attach(sid, f); } catch (err) { toast(err.message, "error"); setTyping(false); }
  };

  document.getElementById("pills").innerHTML = PILLS.map(([cmd, ic]) =>
    `<button class="pill" data-cmd="${cmd}">${icon(ic, 16)}<span>${t("pill." + cmd)}</span></button>`).join("");
  document.getElementById("pills").onclick = (e) => {
    const b = e.target.closest(".pill");
    if (b) command(b.dataset.cmd, b.textContent.trim());
  };
  async function command(cmd, label) {
    if (cmd === "new") return onHome();
    if (cmd === "report") { window.location.href = api.exportUrl(sid, "md", "report"); return; }
    if (label) userBubble(label);
    setTyping(true);
    try { await api.message(sid, "", cmd); } catch (err) { toast(err.message, "error"); setTyping(false); }
  }

  // ---------------------------------------------------------------- stream
  setTyping(true);
  es = api.stream(`/api/chat/${sid}/stream`, handle, {
    onError: () => { if (!closed) toast(t("err.network"), "error"); },
  });

  return {
    command,
    toggleDoc: () => doc.toggle(),
    close() { closed = true; es && es.close(); document.getElementById("chat").classList.remove("doc-open"); },
  };
}
