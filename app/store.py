"""In-memory sessions with replayable event logs (SSE-friendly)."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from .models import Document, Event, Finding, Question


class EventLog:
    """Append-only log; any number of SSE clients can replay from an index and wait for more."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.closed = False
        self._cond = asyncio.Condition()

    async def push(self, item: dict) -> None:
        async with self._cond:
            self.items.append(item)
            self._cond.notify_all()

    async def close(self) -> None:
        async with self._cond:
            self.closed = True
            self._cond.notify_all()

    async def follow(self, since: int = 0, keepalive: float = 15.0) -> AsyncIterator[tuple[int, Optional[dict]]]:
        """Yields (index, item); item None = keepalive tick."""
        idx = since
        while True:
            while idx < len(self.items):
                yield idx, self.items[idx]
                idx += 1
            if self.closed:
                return
            async with self._cond:
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield idx, None


@dataclass
class Session:
    id: str
    doc: Document
    original: Document
    context: str = ""
    created: float = field(default_factory=time.time)
    plan: list[dict] = field(default_factory=list)          # dispatcher decisions
    findings: list[Finding] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    tests: list[dict] = field(default_factory=list)
    versions: list[dict] = field(default_factory=list)
    score_before: Optional[dict] = None
    score: Optional[dict] = None
    analyze_log: EventLog = field(default_factory=EventLog)
    chat_log: EventLog = field(default_factory=EventLog)
    analyze_started: bool = False
    analyzed: asyncio.Event = field(default_factory=asyncio.Event)
    chat_started: bool = False
    intro_done: bool = False
    reported: bool = False
    minor_ok: bool = False      # user chose to go through minor questions one by one
    minor_asked: bool = False   # we already offered "apply recommendations for the minor ones"
    warning: str = ""           # e.g. «документ не похож на ТЗ: …» (shown in the summary and the export)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    agent_state: dict[str, str] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)   # free-text messages from the user
    user_id: Optional[str] = None                                # owner (Supabase auth user)
    stream_key: str = field(default_factory=lambda: secrets.token_urlsafe(16))  # SSE access (EventSource has no headers)
    share_token: Optional[str] = None                            # public read-only report link
    debate: list[dict] = field(default_factory=list)             # agents' discussion transcript
    summary: Optional[dict] = None                               # executive summary for the client
    usage: dict[str, float] = field(default_factory=lambda: {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0})
    trace: list[dict] = field(default_factory=list)              # every Claude call, tool call and rule pass

    async def emit(self, ev: Event) -> Event:
        self.agent_state[ev.agent] = ev.emotion
        await self.chat_log.push(ev.model_dump())
        from .db import schedule_save
        schedule_save(self)
        return ev

    def finding(self, fid: str) -> Optional[Finding]:
        return next((f for f in self.findings if f.id == fid), None)

    def question(self, qid: str) -> Optional[Question]:
        return next((q for q in self.questions if q.id == qid), None)


SESSIONS: dict[str, Session] = {}


def create_session(doc: Document, context: str = "", user_id: Optional[str] = None) -> Session:
    sid = uuid.uuid4().hex[:12]
    s = Session(id=sid, doc=doc, original=doc.model_copy(deep=True), context=context, user_id=user_id)
    s.versions.append({"n": 1, "ts": time.time(), "label": "Исходная версия", "changes": []})
    SESSIONS[sid] = s
    return s


def get_session(sid: str) -> Optional[Session]:
    return SESSIONS.get(sid)


# ---------------------------------------------------------------------- persistence
STATE_FIELDS = ("context", "created", "plan", "tests", "versions", "score_before", "score", "reported", "minor_ok",
                "minor_asked", "notes", "debate", "summary", "usage", "stream_key", "critic_dropped", "trace", "warning")


def snapshot(s: Session) -> dict:
    """Everything needed to reopen a check later: document, findings, questions, chat log."""
    state = {k: getattr(s, k, None) for k in STATE_FIELDS}
    state.update(doc=s.doc.model_dump(), original=s.original.model_dump(),
                 findings=[f.model_dump() for f in s.findings], questions=[q.model_dump() for q in s.questions])
    open_q = any(q.status in ("open", "queued") for q in s.questions)
    return {"id": s.id, "user_id": s.user_id, "title": s.doc.title, "filename": s.doc.filename,
            "score_before": (s.score_before or {}).get("total"), "score": (s.score or {}).get("total"),
            "status": "done" if s.reported or (s.intro_done and not open_q) else "active",
            "share_token": s.share_token, "state": state, "events": list(s.chat_log.items),
            "cost_usd": round(float(s.usage.get("usd", 0)), 5), "created_at": _iso(s.created)}


def restore(row: dict) -> Session:
    st = row["state"]
    doc = Document.model_validate(st["doc"])
    s = Session(id=row["id"], doc=doc, original=Document.model_validate(st["original"]), user_id=row["user_id"])
    for k in STATE_FIELDS:
        if st.get(k) is not None:
            setattr(s, k, st[k])
    s.findings = [Finding.model_validate(f) for f in st.get("findings", [])]
    s.questions = [Question.model_validate(q) for q in st.get("questions", [])]
    s.share_token = row.get("share_token")
    if st.get("score") is None:      # saved before the analysis finished: start it again from the document
        s.findings, s.questions, s.plan = [], [], []
        SESSIONS[s.id] = s
        return s
    s.chat_log.items = list(row.get("events") or [])
    s.analyze_log.items = [{"type": "done"}]
    s.analyze_log.closed = True
    s.analyze_started = s.chat_started = s.intro_done = True
    s.analyzed.set()
    SESSIONS[s.id] = s
    return s


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
