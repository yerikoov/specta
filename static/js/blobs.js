// Glass agent characters: dark-to-bright glass body, glowing inner rim, soft star inside,
// glowing white eyes. 8 emotions: neutral, curious, surprised, angry, happy, sleepy, sad, wink.

export const SHAPES = {
  ball: "M50 8C73 8 92 27 92 50 92 73 73 92 50 92 27 92 8 73 8 50 8 27 27 8 50 8Z",
  cloud: "M30 80C15 80 7 69 10 58 4 50 8 36 21 35 23 22 37 15 49 21 58 12 77 15 81 31 93 34 97 49 90 59 94 71 84 81 70 80Z",
  heart: "M50 88C34 78 9 62 10 39 11 24 23 15 35 15 42 15 47 19 50 25 53 19 58 15 65 15 77 15 89 24 90 39 91 62 66 78 50 88Z",
  drop: "M50 8C60 24 84 42 84 63 84 81 69 92 50 92 31 92 16 81 16 63 16 42 40 24 50 8Z",
  hexagon: "M43 11Q50 7 57 11L80 24Q87 28 87 36V64Q87 72 80 76L57 89Q50 93 43 89L20 76Q13 72 13 64V36Q13 28 20 24Z",
  clover: "M50 10C63 10 70 20 68 31 79 29 90 37 90 50 90 63 79 71 68 69 70 80 63 90 50 90 37 90 30 80 32 69 21 71 10 63 10 50 10 37 21 29 32 31 30 20 37 10 50 10Z",
  bumps: "M30 10C38 10 44 14 50 18 56 14 62 10 70 10 82 10 90 18 90 30 90 38 86 44 82 50 86 56 90 62 90 70 90 82 82 90 70 90 62 90 56 86 50 82 44 86 38 90 30 90 18 90 10 82 10 70 10 62 14 56 18 50 14 44 10 38 10 30 10 18 18 10 30 10Z",
};

let uid = Math.floor(Math.random() * 1e6);

function mix(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  const t = amt < 0 ? 0 : 255, k = Math.abs(amt);
  r = Math.round(r + (t - r) * k); g = Math.round(g + (t - g) * k); b = Math.round(b + (t - b) * k);
  return `rgb(${r},${g},${b})`;
}

// ---------------------------------------------------------------- eyes
// Every eye is ONE glowing stroke: a line of half-length h, bent by b, turned by r, at (x, y), width w.
// An emotion is just these numbers, so switching emotions is a smooth morph of numbers, not a swap.
const P = (x, y, h, b, r, w) => ({ x, y, h, b, r, w });
const NEUTRAL = [P(39, 49, 6.2, 0, 18, 7.5), P(61, 49, 6.2, 0, 18, 7.5)];
const HAPPY_R = P(61, 49.5, 5, -5.5, 90, 5);
export const EMOTIONS = {
  neutral: { eyes: NEUTRAL },
  curious: { eyes: [P(39, 50, 4.2, 0, 18, 6.5), P(61, 48, 5.8, 0, 18, 7.5)], look: true },
  surprised: { eyes: [P(39, 48, 5.4, 0, 0, 8.8), P(61, 48, 5.4, 0, 0, 8.8)] },
  angry: { eyes: [P(40, 50.5, 4.6, 0, -32, 6.5), P(60, 50.5, 4.6, 0, 32, 6.5)] },
  happy: { eyes: [P(39, 49.5, 5, -5.5, 90, 5), HAPPY_R] },
  sleepy: { eyes: [P(39, 52, 4.2, 0, 90, 4.6), P(61, 52, 4.2, 0, 90, 4.6)] },
  sad: { eyes: [P(39, 52, 3.6, 0, 30, 6), P(61, 52, 3.6, 0, -30, 6)] },
  wink: { eyes: [NEUTRAL[0], HAPPY_R] },
  thinking: { eyes: [P(44, 44, 4.4, 0, 6, 7), P(65, 43, 4.4, 0, 6, 7)] },
  focused: { eyes: [P(39, 50, 1.4, 0, 0, 9.5), P(61, 50, 1.4, 0, 0, 9.5)] },
  excited: { eyes: [P(39.5, 49, 6, 6.5, 0, 6), P(60.5, 49, 6, -6.5, 0, 6)] },
  shy: { eyes: [P(41, 55, 3.2, 0, 0, 6.5), P(59, 55, 3.2, 0, 0, 6.5)], blush: 1 },
};
const params = (emo) => {
  const e = EMOTIONS[emo] || EMOTIONS.neutral;
  return { eyes: e.eyes.map((q) => ({ ...q })), blush: e.blush || 0 };
};
const eyeD = (q) => `M0 ${-Math.max(0, q.h)}Q${q.b} 0 0 ${Math.max(0, q.h)}`;
const eyeT = (q) => `translate(${q.x} ${q.y}) rotate(${q.r})`;
const eyePath = (q, i) => `<path data-eye="${i}" d="${eyeD(q)}" transform="${eyeT(q)}" stroke="#fff" stroke-width="${q.w}" stroke-linecap="round" fill="none"/>`;

export function face(emotion, id = "x") {
  const p = params(emotion);
  const look = EMOTIONS[emotion]?.look ? " look" : "";
  const paths = p.eyes.map(eyePath).join("");
  return `<g class="blush" opacity="${p.blush * 0.6}"><ellipse cx="29" cy="63" rx="8" ry="4.5" fill="#ff7ab6" filter="url(#${id}k)"/><ellipse cx="71" cy="63" rx="8" ry="4.5" fill="#ff7ab6" filter="url(#${id}k)"/></g>
    <g class="eyes${look}"><g transform="translate(50 50) scale(1.2) translate(-50 -50)"><g filter="url(#${id}e)" opacity=".85">${paths}</g>${paths}</g></g>`;
}

const STAR = "M50 26C52.5 44 56 47.5 74 52 56 56.5 52.5 60 50 78 47.5 60 44 56.5 26 52 44 47.5 47.5 44 50 26Z";

// hue-shifted companion colour for the inner shimmer
function shift(hex, deg) {
  const n = parseInt(hex.slice(1), 16);
  let r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  let h = 0, sat = 0;
  if (d) {
    sat = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h *= 60;
  }
  h = (h + deg + 360) % 360;
  return `hsl(${Math.round(h)} ${Math.round(Math.max(sat, 0.8) * 100)}% ${Math.round(Math.min(Math.max(l, 0.58), 0.68) * 100)}%)`;
}

/**
 * Glass character. Layers (all clipped to the body): soft vertical base, a drifting hue-shifted shimmer,
 * one big softly-edged sparkle spinning in place, a top highlight and an inner rim light; glowing white eyes on top.
 * @param {{shape:string,color:string,star?:string}} meta
 * @param {string} emotion
 * @param {{size?:number, glow?:boolean, cls?:string, star?:boolean, live?:boolean}} opts
 */
export function blobSVG(meta, emotion = "neutral", opts = {}) {
  const { size = 40, glow = true, cls = "", star = true } = opts;
  const live = opts.live ?? size >= 72;
  const id = `b${++uid}`;
  const c = meta?.color || "#a48bff";
  const s2 = meta?.star || shift(c, -48);
  const d = SHAPES[meta?.shape] || SHAPES.cloud;
  const n = parseInt(c.slice(1), 16);
  const light = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255 > 0.62;  // pale colours get a deeper body so the eyes read
  return `<svg class="blob ${live ? "live" : ""} ${cls}" data-emotion="${emotion}" data-id="${id}" width="${size}" height="${size}" viewBox="-8 -8 116 116" aria-hidden="true">
  <defs>
    <linearGradient id="${id}f" x1="0" y1="0" x2=".25" y2="1">
      <stop offset="0" stop-color="${mix(c, light ? 0 : 0.12)}"/><stop offset=".5" stop-color="${mix(c, light ? -0.32 : -0.12)}"/><stop offset="1" stop-color="${mix(c, light ? -0.62 : -0.5)}"/>
    </linearGradient>
    <radialGradient id="${id}m" cx=".5" cy=".5" r=".5">
      <stop offset="0" stop-color="${s2}" stop-opacity=".95"/><stop offset=".6" stop-color="${s2}" stop-opacity=".45"/><stop offset="1" stop-color="${s2}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="${id}s" cx=".5" cy=".5" r=".5">
      <stop offset="0" stop-color="#fff" stop-opacity=".85"/><stop offset=".3" stop-color="#ffe6f2" stop-opacity=".6"/><stop offset=".7" stop-color="${s2}" stop-opacity=".55"/><stop offset="1" stop-color="${s2}" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="${id}c"><path d="${d}"/></clipPath>
    <filter id="${id}g" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
    <filter id="${id}b" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="7"/></filter>
    <filter id="${id}k" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1"/></filter>
    <filter id="${id}r" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="4.5" result="bl"/>
      <feComposite in="SourceAlpha" in2="bl" operator="arithmetic" k2="1.6" k3="-1.6" result="edge"/>
      <feFlood flood-color="${mix(c, 0.72)}"/><feComposite in2="edge" operator="in"/><feGaussianBlur stdDeviation=".8"/>
    </filter>
    <filter id="${id}w" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="1.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/></feMerge>
    </filter>
    <filter id="${id}e" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.4"/></filter>
  </defs>
  ${glow ? `<path d="${d}" fill="${c}" opacity=".42" filter="url(#${id}g)"/>` : ""}
  <g clip-path="url(#${id}c)">
    <rect x="-8" y="-8" width="116" height="116" fill="url(#${id}f)"/>
    <rect x="-8" y="-8" width="116" height="116" fill="#0b0820" opacity=".14"/>
    <g class="shimmer"><ellipse cx="62" cy="64" rx="36" ry="30" fill="url(#${id}m)" filter="url(#${id}b)" opacity=".9"/></g>
    ${star ? `<g class="spark"><path d="${STAR}" fill="url(#${id}s)" filter="url(#${id}k)" opacity=".9" transform="translate(57 47) scale(1.45) rotate(14) translate(-50 -52)"/></g>` : ""}
    <ellipse cx="34" cy="20" rx="22" ry="8" fill="#fff" opacity=".2" filter="url(#${id}k)" transform="rotate(-22 34 20)"/>
    <path d="${d}" fill="#fff" filter="url(#${id}r)" style="mix-blend-mode:screen"/>
  </g>
  <path d="${d}" fill="none" stroke="${mix(c, 0.85)}" stroke-opacity=".55" stroke-width=".9"/>
  <g class="face">${face(emotion, id)}</g>
</svg>`;
}

/** Eyes follow the pointer: every visible character turns its face toward the cursor. */
export function initGaze() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let x = -1, y = -1, raf = 0;
  const run = () => {
    raf = 0;
    document.querySelectorAll(".blob .face").forEach((f) => {
      const svg = f.ownerSVGElement;
      const r = svg.getBoundingClientRect();
      if (!r.width || r.bottom < 0 || r.top > innerHeight) return;
      const dx = x - (r.left + r.width / 2), dy = y - (r.top + r.height / 2);
      const dist = Math.hypot(dx, dy) || 1;
      const k = 6.5 * Math.min(1, dist / (r.width * 2.2));   // in viewBox units → same look at any size
      f.style.transform = `translate(${(dx / dist) * k}px, ${(dy / dist) * k * 0.8}px)`;
    });
  };
  const ask = () => { if (!raf) raf = requestAnimationFrame(run); };
  window.addEventListener("pointermove", (e) => { x = e.clientX; y = e.clientY; ask(); }, { passive: true });
  window.addEventListener("scroll", () => x >= 0 && ask(), { passive: true, capture: true });
}

/** Morph the face of an existing character to another emotion: eyes bend, turn and slide into place. */
const lerp = (a, b, t) => a + (b - a) * t;
const springy = (t) => { const c1 = 1.5, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
export function setEmotion(svgEl, emotion, dur = 560) {
  if (!svgEl || svgEl.dataset.emotion === emotion) return;
  const f = svgEl.querySelector(".face");
  if (!f) return;
  const from = svgEl._face || params(svgEl.dataset.emotion);
  const to = params(emotion);
  svgEl.dataset.emotion = emotion;
  f.querySelector(".eyes")?.classList.toggle("look", !!EMOTIONS[emotion]?.look);
  const paths = [...f.querySelectorAll("path[data-eye]")];
  const blush = f.querySelector(".blush");
  const token = (svgEl._morph = (svgEl._morph || 0) + 1);
  const draw = (k) => {
    const cur = {
      eyes: from.eyes.map((a, i) => {
        const b = to.eyes[i];
        return { x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), h: lerp(a.h, b.h, k), b: lerp(a.b, b.b, k), r: lerp(a.r, b.r, k), w: Math.max(1, lerp(a.w, b.w, k)) };
      }),
      blush: lerp(from.blush, to.blush, Math.min(1, k)),
    };
    paths.forEach((p) => {
      const q = cur.eyes[+p.dataset.eye];
      p.setAttribute("d", eyeD(q)); p.setAttribute("transform", eyeT(q)); p.setAttribute("stroke-width", q.w.toFixed(2));
    });
    if (blush) blush.setAttribute("opacity", (cur.blush * 0.6).toFixed(3));
    svgEl._face = cur;
  };
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return draw(1);
  const t0 = performance.now();
  const step = (now) => {
    if (svgEl._morph !== token) return;
    const t = Math.min(1, (now - t0) / dur);
    draw(springy(t));
    if (t < 1) requestAnimationFrame(step); else svgEl._face = to;
  };
  requestAnimationFrame(step);
  setTimeout(() => { if (svgEl._morph === token && svgEl._face !== to) { draw(1); svgEl._face = to; } }, dur + 120);
}


// The brand agent (green, as in the nav bar and the sidebar) — also the browser-tab icon.
export const BRAND = { shape: "bumps", color: "#31c943" };

export function setFavicon() {
  const svg = blobSVG(BRAND, "neutral", { size: 64, glow: false }).replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  let link = document.querySelector("link[rel~='icon']");
  if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
  link.type = "image/svg+xml";
  link.href = "data:image/svg+xml," + encodeURIComponent(svg);
}
