"""Critic: re-checks every finding and removes false positives / duplicates."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import LLMError, llm
from ..models import Document, Finding
from .registry import AGENTS, COVERED_BY


class Verdict(BaseModel):
    id: str
    keep: bool
    reason: str = ""


class Verdicts(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


async def review(doc: Document, findings: list[Finding], active: set[str]) -> list[Finding]:
    """Marks dropped findings in place (status='dropped'). Returns the dropped ones."""
    text = _norm(doc.full_text())
    dropped: list[Finding] = []

    def drop(f: Finding, reason: str):
        f.status, f.drop_reason = "dropped", reason
        dropped.append(f)

    seen: set[str] = set()
    for f in findings:
        if f.confidence < 0.5:
            drop(f, f.drop_reason or "низкая уверенность")
        elif f.quote and _norm(f.quote) not in text:
            drop(f, "цитата не найдена в документе")
        elif f.signature in seen:
            drop(f, "дубль")
        else:
            seen.add(f.signature)

    # missing section that a specialist covers in detail
    for f in findings:
        if f.status != "open" or f.agent != "completeness" or not (f.topic or "").startswith("section:"):
            continue
        key = f.topic.split(":", 1)[1]
        owner = COVERED_BY.get(key)
        if owner in active and any(g.agent == owner and g.status == "open" for g in findings):
            drop(f, f"раздел детально разберёт агент «{AGENTS[owner]['name']}»")

    # same topic: keep the finding that points to a concrete quote
    by_topic: dict[str, list[Finding]] = {}
    for f in findings:
        if f.status == "open" and f.topic and not f.topic.startswith(("section:", "kb:")):
            by_topic.setdefault(f.topic, []).append(f)
    for group in by_topic.values():
        if any(g.quote for g in group):
            for g in group:
                if not g.quote:
                    drop(g, "дубль: то же самое уже отмечено с цитатой")

    # the Claude-powered second opinion happens in the debate (agents.debate), not here
    return dropped
