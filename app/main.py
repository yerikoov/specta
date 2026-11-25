"""FastAPI app: REST + SSE, serves the vanilla frontend from /static."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Optional  # noqa: E402

import secrets  # noqa: E402

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import export, orchestrator  # noqa: E402
from .agents.registry import public_agents  # noqa: E402
from .db import AuthError, save_now, supa  # noqa: E402
from .llm import llm, meter, trace  # noqa: E402
from .models import AnswerIn, MessageIn, UndoIn  # noqa: E402
from .parsing import parse_bytes  # noqa: E402
from .store import SESSIONS, EventLog, Session, create_session, get_session, restore  # noqa: E402
from pydantic import BaseModel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_tz_p2p.md"
MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED = {".docx", ".pdf", ".txt", ".md", ".markdown"}

app = FastAPI(title="TZ agents", version="1.0")
_bg: set[asyncio.Task] = set()
_actions: dict[str, set[asyncio.Task]] = {}


def spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def track(sid: str, coro) -> None:
    """A user action that «Остановить» is allowed to cancel. Analysis stays on spawn."""
    t = asyncio.create_task(coro)
    _bg.add(t)
    _actions.setdefault(sid, set()).add(t)

    def _done(task: asyncio.Task, sid: str = sid) -> None:
        _bg.discard(task)
        group = _actions.get(sid)
        if not group:
            return
        group.discard(task)
        if not group:
            _actions.pop(sid, None)

    t.add_done_callback(_done)


def _speaker(s: Session, text: str, command: str | None) -> str:
    if command == "skip":
        q = s.question((text or "").strip())
        return q.agent if q else "clarifier"
    if command:
        return {
            "findings": "critic", "start": "clarifier", "questions": "clarifier",
            "improve": "dispatcher", "tests": "testability", "score": "critic", "report": "reporter",
        }.get(command, "dispatcher")
    ids = orchestrator.mentioned_agents(text or "")
    return ids[0] if ids else "dispatcher"


# ------------------------------------------------------------------ auth
async def current_user(authorization: str = Header("")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token and supa.enabled:
        raise HTTPException(401, "Нужно войти")
    try:
        return await supa.user(token)
    except AuthError as e:
        raise HTTPException(e.status, str(e))


async def owned(sid: str, user: dict) -> Session:
    """The user's check: from memory, or reopened from Supabase."""
    s = get_session(sid)
    if not s:
        row = await supa.load(sid)
        if row and row.get("user_id") == user["id"]:
            s = restore(row)
    if not s or (s.user_id and s.user_id != user["id"]):
        raise HTTPException(404, "Проверка не найдена")
    return s


async def need(sid: str, user: dict = Depends(current_user)) -> Session:
    return await owned(sid, user)


async def need_key(sid: str, k: str = "") -> Session:
    """SSE and file downloads can't send headers: they carry the per-check stream key instead."""
    s = get_session(sid)
    if not s:
        row = await supa.load(sid)
        if row and (row.get("state") or {}).get("stream_key") == k:
            s = restore(row)
    if not s or not k or not secrets.compare_digest(s.stream_key, k):
        raise HTTPException(404, "Проверка не найдена")
    return s


class SignupIn(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


@app.post("/api/auth/signup")
async def signup(body: SignupIn):
    if len(body.password) < 6:
        raise HTTPException(400, "Пароль — минимум 6 символов")
    try:
        return await supa.signup(body.email.strip().lower(), body.password, body.name.strip()[:80])
    except AuthError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/auth/login")
async def login(body: LoginIn):
    try:
        return await supa.login(body.email.strip().lower(), body.password)
    except AuthError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/auth/refresh")
async def refresh(body: RefreshIn):
    try:
        return await supa.refresh(body.refresh_token)
    except AuthError as e:
        raise HTTPException(e.status, str(e))


@app.get("/api/me")
async def me(user: dict = Depends(current_user)):
    return user


# ------------------------------------------------------------------ history
@app.get("/api/sessions")
async def sessions(user: dict = Depends(current_user)):
    return await supa.list(user["id"])


@app.get("/api/sessions/{sid}")
async def open_session(sid: str, user: dict = Depends(current_user)):
    s = await owned(sid, user)
    return {"session_id": s.id, "title": s.doc.title, "filename": s.doc.filename, "stream_key": s.stream_key,
            "analyzed": s.analyzed.is_set()}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str, user: dict = Depends(current_user)):
    await owned(sid, user)
    SESSIONS.pop(sid, None)
    await supa.delete(sid, user["id"])
    return {"ok": True}


@app.post("/api/sessions/{sid}/share")
async def share(sid: str, request: Request, user: dict = Depends(current_user)):
    s = await owned(sid, user)
    if not s.share_token:
        s.share_token = secrets.token_urlsafe(12)
        await save_now(s)
    return {"token": s.share_token, "url": f"{str(request.base_url).rstrip('/')}/r/{s.share_token}"}


@app.get("/api/share/{token}")
async def shared(token: str):
    row = await supa.by_share(token)
    if not row:
        raise HTTPException(404, "Ссылка недействительна")
    st = row["state"]
    findings = st.get("findings", [])
    still = [f for f in findings if f["status"] == "open"]
    return {
        "title": row.get("title"), "filename": row.get("filename"), "updated_at": row.get("updated_at"),
        "score_before": st.get("score_before"), "score": st.get("score"), "summary": st.get("summary"),
        "resolved": sum(1 for f in findings if f["status"] == "resolved"), "open": len(still),
        "risks": [{"ref": f.get("section_ref"), "text": f["text"], "severity": f["severity"]} for f in still][:12],
        "changes": sum(len(v.get("changes", [])) for v in st.get("versions", [])),
        "tests": st.get("tests", [])[:20], "debate": len(st.get("debate") or []),
    }


@app.get("/api/share/{token}/export")
async def shared_export(token: str):
    row = await supa.by_share(token)
    if not row:
        raise HTTPException(404, "Ссылка недействительна")
    s = get_session(row["id"]) or restore(row)
    return Response(export.improved_docx(s),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="tz_improved.docx"'})


@app.get("/r/{token}")
def report_page(token: str):
    return FileResponse(ROOT / "static" / "report.html")


def sse(log: EventLog, since: int) -> StreamingResponse:
    async def gen():
        yield "retry: 2000\n\n"
        async for idx, item in log.follow(since):
            if item is None:
                yield ": keepalive\n\n"
            else:
                yield f"id: {idx + 1}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _since(request: Request, since: int) -> int:
    last = request.headers.get("last-event-id")
    return int(last) if last and last.isdigit() else since


# ------------------------------------------------------------------ meta
@app.get("/api/config")
def config():
    return {"engine": llm.engine, "models": llm.models, "auth": supa.enabled}


@app.get("/api/agents")
def agents():
    return public_agents()


# ------------------------------------------------------------------ upload / analyze
MAX_EXTRA = 5


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    name = file.filename or "tz.txt"
    if Path(name).suffix.lower() not in ALLOWED:
        raise HTTPException(400, f"«{name}»: поддерживаются .docx, .pdf, .txt, .md")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"«{name}» больше 15 МБ")
    return name, data


@app.post("/api/upload")
async def upload(file: Optional[UploadFile] = File(None), extra: list[UploadFile] = File(default=[]),
                 sample: bool = Form(False), context: str = Form(""), user: dict = Depends(current_user)):
    """The TZ (`file`) plus up to 5 extra files (`extra`: appendices, API spec, regulator requirements).
    Appendices are read by the agents together with the TZ but are not edited or scored themselves."""
    if sample or file is None:
        name, data = SAMPLE.name, SAMPLE.read_bytes()
    else:
        name, data = await _read_upload(file)
    if len(extra) > MAX_EXTRA:
        raise HTTPException(400, f"Не больше {MAX_EXTRA} дополнительных файлов")
    try:
        doc = parse_bytes(name, data)
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    if not doc.sections:
        raise HTTPException(400, "В документе не найдено текста")
    for f in extra:
        ename, edata = await _read_upload(f)
        try:
            doc.appendix.append(f"[{ename}]\n{parse_bytes(ename, edata).full_text()}")
        except Exception as e:
            raise HTTPException(400, f"Не удалось прочитать «{ename}»: {e}")
    s = create_session(doc, context.strip()[:1000], user_id=user["id"])
    await save_now(s)
    return {"session_id": s.id, "title": doc.title, "filename": doc.filename, "stream_key": s.stream_key,
            "appendix": len(doc.appendix)}


@app.get("/api/analyze/{sid}/stream")
async def analyze_stream(sid: str, request: Request, since: int = 0, k: str = ""):
    s = await need_key(sid, k)
    if not s.analyze_started:
        s.analyze_started = True
        spawn(orchestrator.run_analysis(s))
    return sse(s.analyze_log, _since(request, since))


# ------------------------------------------------------------------ chat
@app.get("/api/chat/{sid}/stream")
async def chat_stream(sid: str, request: Request, since: int = 0, k: str = ""):
    s = await need_key(sid, k)
    if not s.analyze_started:
        s.analyze_started = True
        spawn(orchestrator.run_analysis(s))
    if not s.chat_started:
        s.chat_started = True
        spawn(_locked(s, orchestrator.run_chat_intro(s)))
    return sse(s.chat_log, _since(request, since))


async def _locked(s: Session, coro):
    meter.set(s.usage)   # Claude spend of this check is accounted on the session
    trace.set(s.trace)
    async with s.lock:
        return await coro


@app.post("/api/chat/{sid}/answer")
async def chat_answer(sid: str, body: AnswerIn, s: Session = Depends(need)):
    if not body.choice_key and not (body.custom_text or "").strip():
        raise HTTPException(400, "Нужен choice_key или custom_text")
    q = s.question(body.question_id)
    if not q:
        raise HTTPException(404, "Вопрос не найден")
    if q.status == "answered":
        raise HTTPException(409, "На вопрос уже ответили")
    s.pending_agent = q.agent
    track(sid, _safe(s, orchestrator.answer(s, body.question_id, body.choice_key, body.custom_text)))
    return {"ok": True}


@app.post("/api/chat/{sid}/undo")
async def chat_undo(sid: str, body: UndoIn, s: Session = Depends(need)):
    q = s.question(body.question_id)
    if not q or q.status != "answered":
        raise HTTPException(409, "Нечего отменять")
    s.pending_agent = q.agent
    track(sid, _safe(s, orchestrator.undo_answer(s, body.question_id)))
    return {"ok": True}


@app.post("/api/chat/{sid}/message")
async def chat_message(sid: str, body: MessageIn, s: Session = Depends(need)):
    if not body.command and not body.text.strip():
        raise HTTPException(400, "Пустое сообщение")
    s.pending_agent = _speaker(s, body.text, body.command)
    track(sid, _safe(s, orchestrator.handle_message(s, body.text[:4000], body.command)))
    return {"ok": True}


@app.post("/api/chat/{sid}/attach")
async def chat_attach(sid: str, file: UploadFile = File(...), s: Session = Depends(need)):
    name = file.filename or "attachment.txt"
    if Path(name).suffix.lower() not in ALLOWED:
        raise HTTPException(400, "Поддерживаются .docx, .pdf, .txt, .md")
    data = await file.read()
    try:
        extra = parse_bytes(name, data)
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    s.pending_agent = "parser"
    track(sid, _safe(s, orchestrator.handle_attachment(s, name, extra.full_text(), len(extra.sections))))
    return {"ok": True}


@app.post("/api/chat/{sid}/cancel")
async def chat_cancel(sid: str, s: Session = Depends(need)):
    s.cancel_token = getattr(s, "cancel_token", 0) + 1
    for t in list(_actions.get(sid, ())):
        t.cancel()
    return {"ok": True}


async def _safe(s: Session, coro):
    from .models import Event
    meter.set(s.usage)
    trace.set(s.trace)
    try:
        async with s.lock:
            try:
                return await coro
            except orchestrator.AnswerError as e:
                await s.emit(Event(agent="clarifier", type="status", emotion="sad", text=str(e)))
            except Exception as e:  # never kill the chat
                logging.exception("chat action failed")
                await s.emit(Event(agent="dispatcher", type="status", emotion="sad", text=f"Ошибка: {e}"))
    except asyncio.CancelledError:
        token = getattr(s, "cancel_token", None)
        if getattr(s, "_stopped_token", None) == token and token is not None:
            return
        s._stopped_token = token
        who = getattr(s, "pending_agent", None) or "dispatcher"
        try:
            async with s.lock:
                await s.emit(Event(agent=who, type="status", emotion="neutral", text="Остановил."))
        except asyncio.CancelledError:
            return


# ------------------------------------------------------------------ document / report
@app.get("/api/doc/{sid}")
def document(sid: str, s: Session = Depends(need)):
    changed: dict[str, int] = {}
    for v in s.versions:
        for d in v.get("changes", []):
            changed[d["section_ref"]] = v["n"]
    return {
        "title": s.doc.title, "filename": s.doc.filename,
        "sections": [sec.model_dump() for sec in s.doc.sections],
        "versions": [{"n": v["n"], "ts": v["ts"], "label": v["label"], "count": len(v.get("changes", []))} for v in s.versions],
        "highlights": [{"finding_id": f.id, "section_ref": f.section_ref, "quote": f.quote, "severity": f.severity,
                        "agent": f.agent} for f in s.findings if f.status == "open" and f.section_ref],
        "changed": changed,
    }


@app.get("/api/cache")
def cache_stats():
    """What the persistent cache and the team's memory hold (no client data, only counts)."""
    from . import cache
    return cache.stats()


@app.get("/api/trace/{sid}")
def agent_trace(sid: str, s: Session = Depends(need)):
    """How the agents worked on this check: every Claude call (model, tokens, cache, cost), tool call and rule pass."""
    from .agents.registry import AGENTS
    rows = [{**r, "name": AGENTS.get(r["agent"], {}).get("name", r["agent"])} for r in s.trace]
    llm_rows = [r for r in rows if r["kind"] == "llm"]
    models: dict[str, dict] = {}
    for r in llm_rows:
        m = models.setdefault(r["model"], {"calls": 0, "usd": 0.0, "input": 0, "output": 0, "cached": 0})
        m["calls"] += 1; m["usd"] += r["usd"]; m["input"] += r["input"]; m["output"] += r["output"]; m["cached"] += r["cached"]
    inp = sum(r["input"] for r in llm_rows)
    return {"engine": llm.engine, "rows": rows,
            "totals": {"llm_calls": len(llm_rows), "tool_calls": sum(r["kind"] == "tool" for r in rows),
                       "rule_passes": sum(r["kind"] == "rules" for r in rows), "usd": round(s.usage.get("usd", 0), 5),
                       "cache_hits": sum(r["kind"] == "cache" for r in rows),
                       "pii_masked": s.usage.get("pii_masked", 0),
                       "saved_usd": round(sum(r.get("saved_usd", 0) for r in rows if r["kind"] == "cache"), 5),
                       "input": inp, "output": sum(r["output"] for r in llm_rows),
                       "cache_share": round(sum(r["cached"] for r in llm_rows) / inp, 3) if inp else 0},
            "models": models}


@app.get("/api/report/{sid}")
def report(sid: str, s: Session = Depends(need)):
    if not s.score:
        raise HTTPException(409, "Анализ ещё не завершён")
    return export.report_json(s)


@app.get("/api/report/{sid}/export")
async def report_export(sid: str, format: str = "md", kind: str = "tz", k: str = ""):
    s = await need_key(sid, k)
    if not s.score:
        raise HTTPException(409, "Анализ ещё не завершён")
    base = "report" if kind == "report" else "tz_improved"
    if format == "docx" and kind != "report":
        return Response(export.improved_docx(s),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{base}.docx"'})
    body = export.report_md(s) if kind == "report" else export.improved_md(s)
    return Response(body, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}.md"'})


@app.get("/api/review/{sid}/standard")
async def standard_review(sid: str, k: str = ""):
    """The same static review as `specta check` (ISO/IEC/IEEE 29148, IEEE 830) for the document of a check."""
    s = await need_key(sid, k)
    from .review.pipeline import review_document
    from .review.report import render
    rev = await review_document(s.original.model_copy(deep=True), s.original.filename)
    name = f"{Path(s.original.filename).stem}_review_iso29148.md"
    return Response(render(rev), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ static
@app.middleware("http")
async def revalidate_static(request, call_next):
    """ES modules are cached hard by browsers; make them revalidate so edits show up on reload."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/dashboard")
@app.get("/dashboard/")
def dashboard():
    """The signed-in workspace: same single-page app, routed by the URL on the client."""
    return FileResponse(ROOT / "static" / "index.html")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    detail = getattr(exc, "detail", "Not found")
    return JSONResponse({"detail": detail}, status_code=404)
