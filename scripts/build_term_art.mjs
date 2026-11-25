// Dev tool: renders the terminal animation frames of the agents from the same blobSVG the website draws.
//   python scripts/build_term_art.py     (runs this, then Chrome headless → PNG, then chafa → app/review/term_art/*.ans)
// Frames per agent: in0,in1 (grow in) · m0..m3 (eyes morph neutral → own emotion, same lerp as setEmotion) ·
// gL2,gL1,gR1,gR2 (gaze left/right, about twice the site's amplitude: a terminal cell is coarse, so it must be visible) · blink.
import { writeFileSync, mkdirSync } from "node:fs";
import { blobSVG, EMOTIONS } from "../static/js/blobs.js";

const out = process.argv[2] || "build/term_svg";
mkdirSync(out, { recursive: true });
const AGENTS = {
  parser: [{ shape: "drop", color: "#6aa8ff" }, "curious"],
  dispatcher: [{ shape: "ball", color: "#8b5cf6" }, "excited"],
  ambiguity: [{ shape: "heart", color: "#f5b592" }, "surprised"],
  testability: [{ shape: "bumps", color: "#31c943" }, "focused"],
  completeness: [{ shape: "hexagon", color: "#7cf5c8" }, "thinking"],
  nfr: [{ shape: "ball", color: "#2fd6b5" }, "curious"],
  contradictions: [{ shape: "clover", color: "#fb6adc" }, "angry"],
  integrations: [{ shape: "cloud", color: "#f5a524" }, "thinking"],
  critic: [{ shape: "heart", color: "#ff7a8a" }, "wink"],
  clarifier: [{ shape: "cloud", color: "#b9a6ff" }, "shy"],
  reporter: [{ shape: "clover", color: "#31c943" }, "happy"],
};
const lerp = (a, b, k) => a + (b - a) * k;
const mixEyes = (from, to, k) => EMOTIONS[from].eyes.map((a, i) => {
  const b = EMOTIONS[to].eyes[i];
  return { x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), h: lerp(a.h, b.h, k), b: lerp(a.b, b.b, k), r: lerp(a.r, b.r, k), w: Math.max(1, lerp(a.w, b.w, k)) };
});
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

function svg(meta, eyes, { scale = 1, gx = 0, gy = 0, blush = 0 } = {}) {
  EMOTIONS.__frame = { eyes, blush };
  let s = blobSVG(meta, "__frame", { size: 512, glow: false, live: false });
  s = s.replace('<g class="face">', `<g class="face" transform="translate(${gx} ${gy})">`);
  if (scale !== 1) {
    const a = s.indexOf(">") + 1, b = s.lastIndexOf("</svg>");
    s = s.slice(0, a) + `<g transform="translate(50 50) scale(${scale}) translate(-50 -50)">` + s.slice(a, b) + "</g>" + s.slice(b);
  }
  return s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
}

const manifest = [];
for (const [id, [meta, emo]] of Object.entries(AGENTS)) {
  const own = EMOTIONS[emo].eyes, blush = EMOTIONS[emo].blush || 0;
  const frames = {
    in0: svg(meta, EMOTIONS.neutral.eyes, { scale: 0.55 }),
    in1: svg(meta, EMOTIONS.neutral.eyes, { scale: 0.82 }),
    m0: svg(meta, EMOTIONS.neutral.eyes),
    m1: svg(meta, mixEyes("neutral", emo, ease(0.34)), { blush: blush * 0.34 }),
    m2: svg(meta, mixEyes("neutral", emo, ease(0.67)), { blush: blush * 0.67 }),
    m3: svg(meta, own, { blush }),
    gL2: svg(meta, own, { gx: -9, gy: 1.1, blush }),
    gL1: svg(meta, own, { gx: -4.5, gy: 0.6, blush }),
    gR1: svg(meta, own, { gx: 4.5, gy: 0.6, blush }),
    gR2: svg(meta, own, { gx: 9, gy: 1.1, blush }),
    blink: svg(meta, own.map((q) => ({ ...q, h: Math.max(0.6, q.h * 0.12), b: 0 })), { blush }),
  };
  mkdirSync(`${out}/${id}`, { recursive: true });
  for (const [k, s] of Object.entries(frames)) {
    writeFileSync(`${out}/${id}/${k}.svg`, s);
    manifest.push(`${id}/${k}`);
  }
}
writeFileSync(`${out}/manifest.txt`, manifest.join("\n") + "\n");
console.log(manifest.length, "frames →", out);
