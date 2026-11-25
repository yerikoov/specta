"""Pydantic models: the single event schema, findings, questions, document."""
from __future__ import annotations

import itertools
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

EventType = Literal["status", "finding", "question", "score", "applied", "done"]
Severity = Literal["critical", "important", "minor"]
Emotion = Literal["neutral", "curious", "surprised", "angry", "happy", "sleepy", "sad", "wink"]

_ids = itertools.count(1)


def new_id(prefix: str) -> str:
    return f"{prefix}{next(_ids)}"


class Option(BaseModel):
    key: str
    label: str


class Event(BaseModel):
    """THE event schema. Every agent emits only this. The frontend only renders this."""
    id: str = Field(default_factory=lambda: new_id("e"))
    agent: str
    type: EventType
    severity: Optional[Severity] = None
    section_ref: Optional[str] = None
    text: str = ""
    quote: Optional[str] = None
    options: list[Option] = Field(default_factory=list)
    allow_custom: bool = False
    emotion: Emotion = "neutral"
    # optional extras (score criteria, diffs, question ids, lists...)
    data: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


class PatchOp(BaseModel):
    """How to change the document when an option is chosen."""
    mode: Literal["replace", "append", "create", "replace_sentence", "none"] = "replace"
    section_ref: Optional[str] = None      # target section
    template_key: Optional[str] = None     # or target by template key (created if missing)
    find: Optional[str] = None             # text to replace (mode=replace)
    pattern: Optional[str] = None          # regex fallback when `find` is gone (text already edited)
    text: str = ""                         # new text


class FixOption(BaseModel):
    key: str
    label: str
    ops: list[PatchOp] = Field(default_factory=list)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("f"))
    agent: str
    criterion: Literal["completeness", "clarity", "testability", "consistency", "compliance"]
    severity: Severity
    key: str = ""                          # rule id / fact id (used for signatures & tests)
    topic: Optional[str] = None            # shared topic for cross-agent de-duplication
    section_ref: Optional[str] = None
    refs: list[str] = Field(default_factory=list)
    quote: Optional[str] = None
    text: str
    question: Optional[str] = None
    why: Optional[str] = None
    options: list[FixOption] = Field(default_factory=list)
    confidence: float = 1.0
    status: Literal["open", "resolved", "dropped"] = "open"
    drop_reason: Optional[str] = None
    closed_by: Optional[str] = None        # question id that auto-closed this finding

    @property
    def signature(self) -> str:
        return f"{self.agent}|{self.key}|{self.section_ref or ''}"


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    finding_id: str
    agent: str
    priority: Severity
    text: str
    why: str = ""
    options: list[FixOption]
    status: Literal["queued", "open", "answered"] = "queued"
    members: list[str] = Field(default_factory=list)       # bundle: all finding ids it closes (incl. finding_id)
    items: list[dict[str, Any]] = Field(default_factory=list)  # bundle: [{fid, ref, text, fix, severity}] for the card
    also: list[str] = Field(default_factory=list)           # duplicates from other agents, closed by the same answer
    skipped: bool = False                 # the user postponed it: it goes to the back of the queue
    answer_key: Optional[str] = None
    answer_text: Optional[str] = None
    undo: list[dict[str, Any]] = Field(default_factory=list)   # snapshots for undo


class Section(BaseModel):
    ref: str
    title: str = ""
    level: int = 1
    text: str = ""
    template_key: Optional[str] = None
    created: bool = False   # added by the agents


class Document(BaseModel):
    filename: str
    filetype: str
    pages: int = 1
    title: str = ""
    sections: list[Section] = Field(default_factory=list)
    appendix: list[str] = Field(default_factory=list)     # extra attached files (text)
    numbered: bool = False                                # the document numbers its own clauses («3.1»)

    def get(self, ref: str) -> Optional[Section]:
        for s in self.sections:
            if s.ref == ref:
                return s
        return None

    def by_template(self, key: str) -> Optional[Section]:
        for s in self.sections:
            if s.template_key == key:
                return s
        return None

    def full_text(self) -> str:
        out = []
        for s in self.sections:
            head = f"{s.ref} {s.title}".strip()
            out.append(head + ("\n" + s.text if s.text else ""))
        return "\n".join(out)


class AnswerIn(BaseModel):
    question_id: str
    choice_key: Optional[str] = None
    custom_text: Optional[str] = None


class MessageIn(BaseModel):
    text: str = ""
    command: Optional[str] = None


class UndoIn(BaseModel):
    question_id: str
