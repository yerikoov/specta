// Liquid glass navbar ("Waterline"), vanilla port of the Nimbus UI React component.
// A pill of water: the active drop stretches toward the picked item, splits into droplets on long
// jumps and merges back with a ripple; the cursor lifts a meniscus; each icon plays its own scene.
// Water is a tiny WebGL shader (only inside the pill, paused off-screen); without WebGL a CSS drop.
const PAD = 14; // canvas bleed around the pill, for shadows and ripples

const VERT = `attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}`;
const FRAG = `precision highp float;
uniform vec2 uRes;uniform float uDpr;uniform float uTime;uniform vec4 uPill;
uniform vec4 uBlob[6];uniform float uSy[6];uniform vec4 uRip[6];uniform vec3 uMouse;uniform float uDark;uniform float uAmb;
float sdRB(vec2 p,vec2 b,float r){vec2 q=abs(p)-b+r;return length(max(q,0.))+min(max(q.x,q.y),0.)-r;}
float sdCap(vec2 p,vec4 B,float sy){p-=B.xy;p.y/=sy;p.x=max(abs(p.x)-B.z,0.);return(length(p)-B.w)*min(1.,sy);}
float smin(float a,float b,float k){float h=clamp(.5+.5*(b-a)/k,0.,1.);return mix(b,a,h)-k*h*(1.-h);}
float dropD(vec2 p){float d=1e4;for(int i=0;i<6;i++){if(uBlob[i].w>.5){d=smin(d,sdCap(p,uBlob[i],uSy[i]),13.);}}return d;}
float pillD(vec2 p){vec2 h=uPill.zw*.5;return sdRB(p-uPill.xy-h,h,h.y);}
float lens(float d,float w){float t=clamp(-d/w,0.,1.);return sqrt(1.-(1.-t)*(1.-t));}
float waves(vec2 p){float w=0.;
 for(int i=0;i<6;i++){vec4 R=uRip[i];if(R.w>0.){float x=length(p-R.xy)-R.z*240.;w+=R.w*exp(-R.z*1.7)*sin(x*.3)*exp(-x*x/700.);}}
 vec2 m=p-uMouse.xy;w+=uMouse.z*3.6*exp(-dot(m,m)/1000.);
 w+=uAmb*(sin(p.x*.05+uTime*1.2)*.45+sin(p.x*.13-uTime*.85+p.y*.2)*.25);return w;}
float H(vec2 p){float dp=pillD(p);return lens(dp,uPill.w*.36)*2.4+lens(dropD(p),11.)*7.5+waves(p)*smoothstep(0.,7.,-dp);}
float caus(vec2 p,float t){vec2 q=p;float c=0.;for(int i=0;i<3;i++){q+=vec2(sin(q.y*1.1+t),cos(q.x*1.3-t*.7))*.6;c+=1./(1.+16.*abs(sin(q.x)*sin(q.y)));}return c/3.;}
void main(){
 vec2 p=vec2(gl_FragCoord.x,uRes.y*uDpr-gl_FragCoord.y)/uDpr;
 float dp=pillD(p);float dd=dropD(p);
 float h0=H(p);vec3 n=normalize(vec3(h0-H(p+vec2(1.,0.)),h0-H(p+vec2(0.,1.)),1.));
 vec3 V=vec3(0.,0.,1.);
 float spec=pow(max(dot(reflect(-normalize(vec3(-.45,-.8,.85)),n),V),0.),70.);
 float spec2=pow(max(dot(reflect(-normalize(vec3(.6,.75,.7)),n),V),0.),22.)*.3;
 float fres=clamp((1.-n.z)*4.,0.,1.);
 vec3 irid=.5+.5*cos(6.2831*(vec3(0.,.33,.67)+fres*.85+p.x*.0028+uTime*.035));
 float pm=smoothstep(1.,-1.,dp);float dm=smoothstep(1.,-1.,dd)*smoothstep(1.,-2.,dp);
 float sh=smoothstep(9.,-9.,dropD(p-vec2(0.,5.)))*(1.-dm)*pm*(.11+.07*uDark);
 vec3 c=vec3(0.,.14,.36)*sh;float a=sh;
 float pa=clamp(pm*(fres*.5+spec*.9+spec2),0.,1.);
 c=mix(vec3(1.),irid,.5*fres)*pa+c*(1.-pa);a=pa+a*(1.-pa);
 float th=lens(dd,11.);
 float cs=caus((p+n.xy*th*18.)*.085,uTime*.9);
 vec3 tint=mix(vec3(.80,.95,1.),vec3(.55,.82,1.),uDark);
 float rim=dm*(1.-smoothstep(0.,8.,-dd));
 float cres=dm*smoothstep(.12,.55,dot(n.xy,normalize(vec2(.55,.85))))*smoothstep(0.,3.,-dd);
 float body=.5+.5*clamp(-n.y*3.,-1.,1.);
 float da=dm*(.26+.14*body)*(1.-.35*uDark);vec3 dc=mix(tint,vec3(1.),body*.6);
 float la=rim*.22;vec3 lc=mix(vec3(0.,.42,.78),vec3(.1,.55,.95),uDark);dc=lc*la+dc*da*(1.-la);da=la+da*(1.-la);
 la=clamp(cres*.7+smoothstep(.6,1.,cs)*.28*th*dm,0.,1.);dc=vec3(1.)*la+dc*(1.-la);da=la+da*(1.-la);
 la=clamp(dm*(spec*1.2+spec2*.5),0.,1.);dc=vec3(1.)*la+dc*(1.-la);da=la+da*(1.-la);
 la=dm*smoothstep(-2.,0.,dd)*.4;dc=mix(vec3(1.),irid,.35)*la+dc*(1.-la);da=la+da*(1.-la);
 c=dc+c*(1.-da);a=da+a*(1.-da);
 gl_FragColor=vec4(c,a);
}`;

const svg = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
export const NavIcons = {
  team: svg('<circle cx="9" cy="8.5" r="3.4"/><path d="M3.2 19.5c.9-3 3.2-4.6 5.8-4.6s4.9 1.6 5.8 4.6"/><path class="nv-door" d="M15.5 5.4a3.2 3.2 0 0 1 0 6.2M17.4 14.6c1.8.6 3 2.2 3.4 4.9"/>'),
  how: svg('<path d="M12 3.5l1.9 5.2 5.4.3-4.2 3.4 1.4 5.3L12 14.8l-4.5 2.9 1.4-5.3-4.2-3.4 5.4-.3Z"/>'),
  chart: svg('<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8.5 16v-4M13 16V8M17.5 16v-6"/>'),
  shield: svg('<path d="M12 3.5 5 6.2v5.3c0 4.3 2.9 7.6 7 9 4.1-1.4 7-4.7 7-9V6.2Z"/><path d="m9 12 2.2 2.2L15.3 10"/>'),
};

const CSS = `
.nimbus-nav{--n-tint:rgba(255,255,255,.14);--n-fg:#0B132B;--n-fg-soft:rgba(11,19,43,.6);--n-rim:rgba(255,255,255,.7);
  position:relative;display:inline-flex;align-items:center;gap:2px;padding:6px;border-radius:999px;isolation:isolate;
  font-family:inherit;-webkit-font-smoothing:antialiased;user-select:none;-webkit-tap-highlight-color:transparent}
.nimbus-nav[data-tone="dark"]{--n-tint:rgba(10,18,40,.26);--n-fg:#F1F7FF;--n-fg-soft:rgba(241,247,255,.66);--n-rim:rgba(255,255,255,.34)}
.nimbus-glass{position:absolute;inset:0;border-radius:inherit;z-index:-2;overflow:hidden;background:var(--n-tint);
  -webkit-backdrop-filter:blur(10px) saturate(1.2) brightness(1.08);backdrop-filter:blur(10px) saturate(1.2) brightness(1.08);
  box-shadow:inset 0 1px 1px var(--n-rim),inset 0 0 0 1px rgba(255,255,255,.2),0 12px 32px -14px rgba(0,40,90,.5),0 2px 6px rgba(0,40,90,.1)}
.nimbus-nav[data-refract="on"] .nimbus-glass{-webkit-backdrop-filter:url(#nimbus-refract) blur(2px) saturate(1.2) brightness(1.08);backdrop-filter:url(#nimbus-refract) blur(2px) saturate(1.2) brightness(1.08)}
.nimbus-water{position:absolute;left:${-PAD}px;top:${-PAD}px;z-index:-1;pointer-events:none}
.nimbus-nav[data-gl="off"] .nimbus-water{display:none}
.nimbus-drop{display:none;position:absolute;top:6px;bottom:6px;left:0;border-radius:999px;z-index:-1;pointer-events:none;will-change:transform,width;
  background:radial-gradient(120% 140% at 30% 0%,rgba(255,255,255,.75),rgba(255,255,255,0) 55%),rgba(255,255,255,.38);
  box-shadow:inset 0 1px 1px rgba(255,255,255,.95),inset 0 -2px 6px rgba(0,162,255,.22),inset 0 0 0 1px rgba(255,255,255,.55),0 6px 16px -6px rgba(0,70,140,.45)}
.nimbus-nav[data-gl="off"] .nimbus-drop{display:block}
.nimbus-item{position:relative;z-index:1;display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 16px;border:0;border-radius:999px;background:none;color:var(--n-fg-soft);
  font-family:inherit;font-weight:500;font-size:14px;line-height:1;letter-spacing:-.01em;white-space:nowrap;text-decoration:none;cursor:pointer;transition:color .25s}
.nimbus-item:hover,.nimbus-item[aria-current="page"]{color:var(--n-fg)}
.nimbus-item:focus-visible{outline:2px solid #00A2FF;outline-offset:2px}
.nv-ico{position:relative;display:inline-flex;flex:none}
.nv-ico svg{transition:transform .45s cubic-bezier(.3,1.6,.5,1)}
.nimbus-item[aria-current="page"] .nv-ico svg{transform:translateY(-1px) scale(1.08)}
.nv-door{fill:transparent}
.nv-ico[data-fx="pop"] svg{animation:nvPop .5s cubic-bezier(.3,1.6,.5,1) both}
@keyframes nvPop{0%{transform:scale(.72)}60%{transform:scale(1.2)}100%{transform:translateY(-1px) scale(1.08)}}
.nv-ico[data-fx="drop"] svg{animation:nvDrop .95s cubic-bezier(.4,0,.3,1) both;transform-origin:50% 100%}
@keyframes nvDrop{0%{transform:translateY(-1px)}26%{transform:translateY(-13px) scale(.88,1.12)}46%{transform:translateY(3px) scale(1.3,.68)}62%{transform:translateY(-3px) scale(.92,1.08)}80%{transform:translateY(0) scale(1.04,.97)}100%{transform:translateY(-1px) scale(1.08)}}
.nv-ico[data-fx="spin"] svg{animation:nvSpin 1s cubic-bezier(.2,.75,.25,1) both}
@keyframes nvSpin{0%{transform:perspective(80px) rotateY(0)}100%{transform:perspective(80px) rotateY(360deg) translateY(-1px) scale(1.08)}}
.nv-ico[data-fx="glow"] svg{animation:nvHop .8s cubic-bezier(.3,1.4,.5,1) both;transform-origin:50% 100%}
@keyframes nvHop{0%{transform:none}30%{transform:translateY(-5px) scale(1.04,.96)}55%{transform:translateY(0) scale(1.12,.88)}75%{transform:translateY(-2px) scale(.98,1.04)}100%{transform:translateY(-1px) scale(1.08)}}
.nv-ico[data-fx="glow"] .nv-door{animation:nvDoor 1.3s ease both}
@keyframes nvDoor{0%{fill:transparent}30%{fill:#FFF3A8}100%{fill:rgba(126,232,255,.6)}}
.nv-ico[data-fx="wave"] svg{animation:nvWave .9s ease-in-out both;transform-origin:50% 92%}
@keyframes nvWave{0%{transform:none}20%{transform:rotate(-15deg)}40%{transform:rotate(12deg)}60%{transform:rotate(-8deg)}80%{transform:rotate(4deg)}100%{transform:translateY(-1px) scale(1.08)}}
.nimbus-nav[data-compact="true"] .nimbus-item{padding:0 13px}
.nimbus-nav[data-compact="true"] .nimbus-label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:820px){.nimbus-nav .nimbus-item{padding:0 13px}.nimbus-nav .nimbus-label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}
/* ---- "glass" variant: iOS-style liquid glass instead of water ---- */
.nimbus-nav[data-look="glass"]{--n-fg:#fff;--n-fg-soft:rgba(255,255,255,.62);padding:5px}
.nimbus-nav[data-look="glass"] .nimbus-glass{overflow:visible;background:linear-gradient(180deg,rgba(255,255,255,.085),rgba(255,255,255,.035));
  -webkit-backdrop-filter:blur(18px) saturate(1.8) brightness(1.05);backdrop-filter:blur(18px) saturate(1.8) brightness(1.05);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22),inset 0 -1px 0 rgba(255,255,255,.05),0 12px 34px -14px rgba(0,0,0,.75),0 1px 2px rgba(0,0,0,.35)}
.nimbus-nav[data-look="glass"][data-refract="on"] .nimbus-glass{-webkit-backdrop-filter:url(#nimbus-refract) blur(14px) saturate(1.8) brightness(1.05);backdrop-filter:url(#nimbus-refract) blur(14px) saturate(1.8) brightness(1.05)}
/* bright rim that catches light at the top-left and bottom-right, like a glass edge */
.nimbus-nav[data-look="glass"] .nimbus-glass::before,.nimbus-nav[data-look="glass"] .nimbus-drop::before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;pointer-events:none;
  background:linear-gradient(135deg,rgba(255,255,255,.55),rgba(255,255,255,.08) 32%,rgba(255,255,255,.02) 55%,rgba(255,255,255,.08) 75%,rgba(255,255,255,.32));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0)}
.nimbus-nav[data-look="glass"] .nimbus-drop{display:block;top:5px;bottom:5px;
  background:radial-gradient(90% 120% at 30% -10%,rgba(255,255,255,.28),rgba(255,255,255,0) 60%),linear-gradient(180deg,rgba(255,255,255,.14),rgba(255,255,255,.06));
  -webkit-backdrop-filter:blur(6px) saturate(2) brightness(1.2);backdrop-filter:blur(6px) saturate(2) brightness(1.2);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.4),inset 0 -1px 1px rgba(255,255,255,.08),0 6px 18px -6px rgba(0,0,0,.55),0 0 0 .5px rgba(255,255,255,.08)}
.nimbus-nav[data-look="glass"] .nimbus-item{height:40px;padding:0 15px}
.nimbus-brand{display:inline-flex;align-items:center;gap:9px;height:40px;padding:0 14px 0 10px;color:#fff;text-decoration:none;font-weight:600;font-size:13px;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap}
.nimbus-brand .brand-logo{width:22px;height:22px;display:inline-grid;place-items:center}
.nimbus-sep{width:1px;height:20px;margin:0 4px 0 2px;background:linear-gradient(transparent,rgba(255,255,255,.22),transparent);flex:none}
@media (max-width:820px){.nimbus-brand .nimbus-brand-name{display:none}.nimbus-brand{padding:0 8px}}
@media (max-width:720px){.nimbus-brand,.nimbus-sep{display:none}}
@media (prefers-reduced-motion:reduce){.nv-ico svg,.nv-ico::before,.nv-ico::after,.nv-door{animation:none!important;transition:none}}
`;

function initGL(canvas) {
  const gl = canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!gl) return null;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
  const vs = sh(gl.VERTEX_SHADER, VERT), fs = sh(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const p = gl.createProgram();
  gl.attachShader(p, vs); gl.attachShader(p, fs); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) return null;
  gl.useProgram(p);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(p, "a");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const u = {};
  for (const n of ["uRes", "uDpr", "uTime", "uPill", "uBlob", "uSy", "uRip", "uMouse", "uDark", "uAmb"]) u[n] = gl.getUniformLocation(p, n);
  return { gl, u };
}
const supportsRefraction = () => /Chrome\/|Chromium\/|Edg\//.test(navigator.userAgent) && !/Firefox\//.test(navigator.userAgent) && !!CSS.supports?.("backdrop-filter", "url(#a)");

/**
 * @param {HTMLElement} host  where the nav is mounted
 * @param {{items:{label:string,icon?:string,fx?:string}[], active?:number, tone?:"light"|"dark", onChange?:(i:number)=>void}} opts
 * @returns {{setActive:(i:number)=>void, el:HTMLElement}}
 */
export function createLiquidNav(host, { items, active = 0, tone = "dark", onChange, look = "water", brand = "", onBrand } = {}) {
  if (!document.getElementById("nimbus-css")) {
    const st = document.createElement("style"); st.id = "nimbus-css"; st.textContent = CSS; document.head.appendChild(st);
  }
  const nav = document.createElement("nav");
  nav.className = "nimbus-nav";
  nav.dataset.tone = tone;
  nav.dataset.gl = look === "glass" ? "off" : "on";
  nav.dataset.look = look;
  nav.dataset.refract = supportsRefraction() ? "on" : "off";
  nav.setAttribute("aria-label", "Main");
  nav.innerHTML = `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="nimbus-refract" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.006 0.02" numOctaves="2" seed="7" result="noise"/><feGaussianBlur in="noise" stdDeviation="2" result="soft"/>
      <feDisplacementMap in="SourceGraphic" in2="soft" scale="${look === "glass" ? 16 : 60}" xChannelSelector="R" yChannelSelector="G"/></filter></svg>
    <span class="nimbus-glass" aria-hidden="true"></span><canvas class="nimbus-water" aria-hidden="true"></canvas><span class="nimbus-drop" aria-hidden="true"></span>
    ${brand ? `<a class="nimbus-brand" href="#">${brand}</a><span class="nimbus-sep" aria-hidden="true"></span>` : ""}
    ${items.map((it, i) => `<button type="button" class="nimbus-item" data-i="${i}" aria-label="${it.label}">${it.icon ? `<span class="nv-ico">${it.icon}</span>` : ""}<span class="nimbus-label">${it.label}</span></button>`).join("")}`;
  host.appendChild(nav);
  const canvas = nav.querySelector("canvas"), drop = nav.querySelector(".nimbus-drop");
  const btns = [...nav.querySelectorAll(".nimbus-item")];
  const dark = tone === "dark" ? 1 : 0;
  let current = active;

  const s = {
    a: { x: 0, v: 0 }, b: { x: 0, v: 0 }, sy: { s: 1, v: 0 }, lead: 0, lagFrom: 0, sats: [], rips: [],
    t: { x: 0, cy: 0, q: 0, r: 21 }, q: 0, mouse: { x: 0, y: 0, s: 0, on: false },
    moving: false, split: false, ready: false, w: 0, h: 0, visible: true,
    reduce: matchMedia("(prefers-reduced-motion: reduce)").matches, raf: 0, last: 0, time: 0, glc: look === "glass" ? null : initGL(canvas),
  };
  if (!s.glc) nav.dataset.gl = "off";
  nav.querySelector(".nimbus-brand")?.addEventListener("click", (e) => { e.preventDefault(); onBrand?.(); });
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); s.glc = null; nav.dataset.gl = "off"; });

  function draw() {
    const T = s.t, sep = Math.abs(s.a.x - s.b.x);
    const thin = Math.min(sep / (2 * (s.q + T.r) || 1), 1);
    const r = T.r * (1 - 0.3 * thin);
    if (s.glc) {
      const { gl: g, u } = s.glc;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      g.viewport(0, 0, g.drawingBufferWidth, g.drawingBufferHeight);
      g.uniform2f(u.uRes, s.w + PAD * 2, s.h + PAD * 2);
      g.uniform1f(u.uDpr, dpr);
      g.uniform1f(u.uTime, s.time);
      g.uniform4f(u.uPill, PAD, PAD, s.w, s.h);
      const blobs = new Float32Array(24), sy = new Float32Array(6).fill(1);
      const head = s.lead === 0 ? s.a : s.b, tail = s.lead === 0 ? s.b : s.a;
      blobs.set([head.x, T.cy, s.q * (1 - 0.25 * thin), T.r * (1 - 0.12 * thin), tail.x, T.cy, s.q * (1 - 0.8 * thin), T.r * (1 - 0.5 * thin)], 0);
      sy[0] = sy[1] = s.sy.s;
      s.sats.slice(0, 4).forEach((d, i) => blobs.set([d.x, d.y, 0, d.r], 8 + i * 4));
      g.uniform4fv(u.uBlob, blobs);
      g.uniform1fv(u.uSy, sy);
      const rips = new Float32Array(24);
      s.rips.slice(-6).forEach((p, i) => rips.set([p.x, p.y, p.age, p.amp], i * 4));
      g.uniform4fv(u.uRip, rips);
      g.uniform3f(u.uMouse, s.mouse.x, s.mouse.y, s.mouse.s);
      g.uniform1f(u.uDark, dark);
      g.uniform1f(u.uAmb, s.reduce ? 0 : 1);
      g.clearColor(0, 0, 0, 0);
      g.clear(g.COLOR_BUFFER_BIT);
      g.drawArrays(g.TRIANGLES, 0, 3);
    } else {
      const left = Math.min(s.a.x, s.b.x) - s.q - r - PAD;
      drop.style.width = `${sep + 2 * (s.q + r)}px`;
      drop.style.transform = `translateX(${left}px) scaleY(${s.sy.s})`;
    }
  }

  function step(dt, now) {
    const T = s.t;
    s.time += dt;
    s.q += (T.q - s.q) * Math.min(1, dt * 12);
    const bodies = [s.a, s.b];
    let still = true;
    if (s.reduce) {
      s.a.x = s.b.x = T.x; s.a.v = s.b.v = 0; s.sy.s = 1; s.sats = [];
    } else {
      bodies.forEach((B, i) => {
        const lead = i === s.lead, k = lead ? 210 : 72, c = lead ? 25 : 13;
        const f = !lead && now < s.lagFrom ? 0.08 : 1;
        B.v += (k * (T.x - B.x) - c * B.v) * dt * f;
        B.x += B.v * dt;
        const lo = PAD + 6 + s.q + T.r - 3, hi = PAD + s.w - 6 - s.q - T.r + 3;
        if (B.x < lo || B.x > hi) { s.sy.v -= Math.min(Math.abs(B.v), 900) * 0.0016; B.x = Math.max(lo, Math.min(hi, B.x)); B.v *= -0.25; }
        if (Math.abs(T.x - B.x) > 0.3 || Math.abs(B.v) > 3) still = false;
      });
      const L = bodies[s.lead];
      const syT = 1 - 0.2 * Math.min(Math.abs(L.v) / 1500, 1);
      s.sy.v += (280 * (syT - s.sy.s) - 9 * s.sy.v) * dt;
      s.sy.s += s.sy.v * dt;
      if (Math.abs(s.sy.s - 1) > 0.002 || Math.abs(s.sy.v) > 0.02) still = false;
      // break the neck: spawn droplets between head and tail
      const sep = Math.abs(s.a.x - s.b.x);
      const r = T.r * (1 - 0.3 * Math.min(sep / (2 * (T.q + T.r) || 1), 1));
      if (!s.split && s.moving && sep - 2 * T.q - 2 * r > -6) {
        s.split = true;
        const lo = bodies[1 - s.lead], hi = bodies[s.lead];
        [0.3, 0.5, 0.72].forEach((t, j) => s.sats.push({
          x: lo.x + (hi.x - lo.x) * t + (Math.random() - 0.5) * 6, y: T.cy + (Math.random() - 0.5) * 10,
          vx: (lo.v + hi.v) * 0.45, vy: (Math.random() - 0.5) * 60, r: 5 + Math.random() * 3 - j * 0.5, k: 70 + Math.random() * 90,
        }));
      }
      s.sats = s.sats.filter((d) => {
        d.vx += (d.k * (T.x - d.x) - 9 * d.vx) * dt;
        d.vy += (90 * (T.cy - d.y) - 7 * d.vy) * dt;
        d.x += d.vx * dt; d.y += d.vy * dt;
        d.x = Math.max(PAD + 8 + d.r, Math.min(PAD + s.w - 8 - d.r, d.x));
        d.y = Math.max(T.cy - T.r + d.r, Math.min(T.cy + T.r - d.r, d.y));
        if (Math.abs(T.x - d.x) < T.q + T.r * 0.5) d.r -= dt * 26;
        return d.r > 0.6;
      });
      if (s.sats.length) still = false;
    }
    if (s.moving && still) {
      s.moving = false;
      s.rips.push({ x: T.x, y: T.cy, age: 0, amp: s.split ? 1.2 : 0.7 });
    }
    s.rips.forEach((p) => (p.age += dt));
    s.rips = s.rips.filter((p) => p.age < 2.4);
    s.mouse.s += ((s.mouse.on ? 1 : 0) - s.mouse.s) * Math.min(1, dt * 7);
  }

  function loop() {
    if (s.raf) return;
    s.last = performance.now();
    const tick = (now) => {
      const dt = Math.min((now - s.last) / 1000, 1 / 30);
      s.last = now;
      step(dt, now);
      draw();
      const busy = s.moving || s.rips.length || s.sats.length || s.mouse.s > 0.01;
      if (s.visible && (!s.reduce || busy)) s.raf = requestAnimationFrame(tick); else s.raf = 0;
    };
    s.raf = requestAnimationFrame(tick);
  }

  function measure() {
    const el = btns[current];
    if (!el || !nav.offsetWidth) return;
    s.w = nav.offsetWidth; s.h = nav.offsetHeight;
    const T = s.t;
    T.r = el.offsetHeight / 2;
    T.q = Math.max(0, el.offsetWidth / 2 - T.r);
    T.cy = PAD + el.offsetTop + el.offsetHeight / 2;
    const nx = PAD + el.offsetLeft + el.offsetWidth / 2;
    if (!s.ready) { s.a.x = s.b.x = nx; s.q = T.q; s.ready = true; }
    else if (Math.abs(nx - T.x) > 0.5) {
      s.lead = Math.abs(nx - s.a.x) <= Math.abs(nx - s.b.x) ? 0 : 1;
      s.lagFrom = performance.now() + 70;
      s.moving = true; s.split = false;
    }
    T.x = nx;
    const dpr = Math.min(devicePixelRatio || 1, 2), W = s.w + PAD * 2, Hh = s.h + PAD * 2;
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(Hh * dpr)) {
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(Hh * dpr);
      canvas.style.width = `${W}px`; canvas.style.height = `${Hh}px`;
    }
    loop();
  }

  const local = (x, y) => { const r = nav.getBoundingClientRect(); return { x: x - r.left + PAD, y: y - r.top + PAD }; };
  const ripple = (x, y, amp) => { if (s.reduce) return; s.rips.push({ x, y, age: 0, amp }); loop(); };

  function mark() { btns.forEach((b, i) => (i === current ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"))); }
  function play(i) {
    const ico = btns[i].querySelector(".nv-ico");
    if (!ico) return;
    ico.removeAttribute("data-fx"); void ico.offsetWidth;
    ico.dataset.fx = items[i].fx || "pop";
    if (ico.dataset.fx === "drop") { const b = ico.getBoundingClientRect(), c = local(b.left + b.width / 2, b.top); setTimeout(() => ripple(c.x, s.t.cy, 1.4), 430); }
  }
  function setActive(i) {
    if (i === current || i < 0 || i >= items.length) return;
    current = i; mark(); measure();
  }

  btns.forEach((b, i) => b.addEventListener("click", () => { play(i); const changed = i !== current; setActive(i); if (changed || true) onChange?.(i, items[i]); }));
  nav.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const n = (current + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    btns[n].click(); btns[n].focus();
  });
  nav.addEventListener("pointermove", (e) => { if (e.pointerType !== "mouse") return; const p = local(e.clientX, e.clientY); Object.assign(s.mouse, p, { on: true }); loop(); });
  nav.addEventListener("pointerleave", () => { s.mouse.on = false; loop(); });
  nav.addEventListener("pointerdown", (e) => { const p = local(e.clientX, e.clientY); ripple(p.x, p.y, 0.8); });
  new IntersectionObserver(([e]) => { s.visible = e.isIntersecting; if (s.visible) loop(); }).observe(nav);
  document.addEventListener("visibilitychange", () => { s.visible = document.visibilityState === "visible"; if (s.visible) loop(); });
  let lastW = -1;
  new ResizeObserver(() => { if (nav.offsetWidth !== lastW) { lastW = nav.offsetWidth; s.ready = false; measure(); } }).observe(nav);

  mark();
  requestAnimationFrame(measure);
  return { setActive, el: nav };
}
