// Thin API client. All endpoints in one place.
// Auth: Supabase session (access + refresh token) kept in localStorage; every request carries
// `Authorization: Bearer …`. SSE and file downloads can't send headers, so they use the per-check
// stream key the server hands out with each check.
const AUTH_KEY = "specta.auth";
const keys = {};               // session id → stream key
let auth = null;
try { auth = JSON.parse(localStorage.getItem(AUTH_KEY) || "null"); } catch { auth = null; }
const listeners = new Set();

function saveAuth(a) {
  auth = a;
  try { a ? localStorage.setItem(AUTH_KEY, JSON.stringify(a)) : localStorage.removeItem(AUTH_KEY); } catch {}
  listeners.forEach((fn) => fn(auth));
}

async function json(res) {
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

let refreshing = null;
async function call(url, opts = {}, retry = true) {
  const headers = { ...(opts.headers || {}) };
  if (auth?.access_token) headers.Authorization = `Bearer ${auth.access_token}`;
  const res = await fetch(url, { ...opts, headers });
  if (res.status === 401 && retry && auth?.refresh_token) {
    refreshing ||= fetch("/api/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: auth.refresh_token }) }).then(json).then(saveAuth)
      .catch(() => saveAuth(null)).finally(() => (refreshing = null));
    await refreshing;
    if (auth) return call(url, opts, false);
  }
  if (res.status === 401) saveAuth(null);
  return json(res);
}
const post = (url, body) => call(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const remember = (r) => { if (r?.session_id && r.stream_key) keys[r.session_id] = r.stream_key; return r; };

export const api = {
  // ---- account
  get user() { return auth?.user || null; },
  onAuth(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  signup: (email, password, name) => post("/api/auth/signup", { email, password, name }).then((a) => (saveAuth(a), a)),
  login: (email, password) => post("/api/auth/login", { email, password }).then((a) => (saveAuth(a), a)),
  logout: () => saveAuth(null),
  // ---- meta
  config: () => fetch("/api/config").then(json),
  agents: () => fetch("/api/agents").then(json),
  // ---- checks
  upload(file, context = "", sample = false) {
    const fd = new FormData();
    if (file) fd.append("file", file);
    fd.append("sample", sample ? "true" : "false");
    fd.append("context", context);
    return call("/api/upload", { method: "POST", body: fd }).then(remember);
  },
  sessions: () => call("/api/sessions"),
  session: (sid) => call(`/api/sessions/${sid}`).then(remember),
  remove: (sid) => call(`/api/sessions/${sid}`, { method: "DELETE" }),
  share: (sid) => post(`/api/sessions/${sid}/share`, {}),
  answer: (sid, body) => post(`/api/chat/${sid}/answer`, body),
  undo: (sid, question_id) => post(`/api/chat/${sid}/undo`, { question_id }),
  message: (sid, text, command = null) => post(`/api/chat/${sid}/message`, { text, command }),
  attach(sid, file) {
    const fd = new FormData();
    fd.append("file", file);
    return call(`/api/chat/${sid}/attach`, { method: "POST", body: fd });
  },
  doc: (sid) => call(`/api/doc/${sid}`),
  trace: (sid) => call(`/api/trace/${sid}`),
  withKey(url) {
    const m = url.match(/\/api\/(?:analyze|chat|report)\/([a-f0-9]+)\//);
    const k = m && keys[m[1]];
    return k ? `${url}${url.includes("?") ? "&" : "?"}k=${encodeURIComponent(k)}` : url;
  },
  exportUrl(sid, format = "docx", kind = "tz") { return this.withKey(`/api/report/${sid}/export?format=${format}&kind=${kind}`); },
  /** SSE with auto-reconnect (EventSource resends Last-Event-ID itself). */
  stream(path, onEvent, { onError, onEnd } = {}) {
    const es = new EventSource(this.withKey(path));
    es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    es.addEventListener("end", () => { es.close(); onEnd && onEnd(); });
    es.onerror = () => onError && onError(es);
    return es;
  },
};
