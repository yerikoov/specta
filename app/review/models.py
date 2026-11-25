"""Data of one review run: requirements cut from the document, defects, the report."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "major", "minor"]


class Requirement(BaseModel):
    rid: str                      # id in the report: R-01…
    doc_id: str                   # id / place in the document: «Ф-2», «Критерии приемки, строка 2»
    section: str                  # section title path: «Часть A · Функциональные требования»
    kind: str                     # functional | nfr | data | integration | ui | process | business | acceptance | api | design
    text: str                     # full quote from the document
    short: str                    # short wording for the slicing table
    ref: str = ""                 # parser section ref (for focusing in the UI)


class Defect(BaseModel):
    prop: str                     # property key from standards.REQ_PROPS / SET_PROPS
    severity: Severity
    quote: str = ""               # verbatim fragment of the document
    problem: str                  # what exactly is wrong, tied to the text
    fix: str = ""                 # how to fix
    rids: list[str] = Field(default_factory=list)   # requirements involved
    place: str = ""               # where in the document (when no requirement id: a section)
    source: Literal["rules", "llm"] = "rules"
    agent: str = ""               # which agent found it


class Question(BaseModel):
    text: str
    options: list[str] = Field(default_factory=list)
    rids: list[str] = Field(default_factory=list)
    why: str = ""


class Review(BaseModel):
    title: str
    filename: str
    requirements: list[Requirement] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)          # sections not cut into requirements (and why)
    req_defects: list[Defect] = Field(default_factory=list)   # about one requirement
    set_defects: list[Defect] = Field(default_factory=list)   # about the set
    questions: list[Question] = Field(default_factory=list)
    dropped: list[Defect] = Field(default_factory=list)       # removed by the Critic
    started: float = 0
    finished: float = 0
    model: str = ""
    engine: str = ""
    version: str = ""
    usage: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    verdict: Optional[dict] = None
