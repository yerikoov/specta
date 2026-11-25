"""Base class for specialist agents: rules in plain Python + optional LLM pass."""
from __future__ import annotations

import logging
import re
from typing import Iterator, Optional

from pydantic import BaseModel, Field

from ..llm import LLMError, llm
from ..models import Document, Finding, FixOption, PatchOp, Section
from ..parsing import sentences
from .registry import AGENTS

log = logging.getLogger("agents")
KEYS = "ABCDEFG"


class LLMOption(BaseModel):
    label: str
    new_text: str


class LLMFinding(BaseModel):
    section_ref: Optional[str] = None
    quote: Optional[str] = None
    text: str
    severity: str = "important"
    question: str = ""
    why: str = ""
    options: list[LLMOption] = Field(default_factory=list)


class LLMFindings(BaseModel):
    findings: list[LLMFinding] = Field(default_factory=list)


def iter_sentences(doc: Document) -> Iterator[tuple[Section, str]]:
    for sec in doc.sections:
        if sec.text:
            for s in sentences(sec.text):
                yield sec, s


def make_options(items: list[tuple[str, list[PatchOp]]]) -> list[FixOption]:
    return [FixOption(key=KEYS[i], label=label, ops=ops) for i, (label, ops) in enumerate(items)]


def doc_for_prompt(doc: Document, limit: int = 24000) -> str:
    lines = []
    for s in doc.sections:
        lines.append(f"[п. {s.ref}] {s.title}".rstrip() + (f"\n{s.text}" if s.text else ""))
    body = "\n".join(lines)[:limit]
    if doc.appendix and len(body) < limit:   # appendices: context for the agents, not part of the TZ itself
        body += "\n\n=== ПРИЛОЖЕНИЯ (не часть ТЗ, только справка; цитаты бери из ТЗ выше) ===\n" + "\n\n".join(doc.appendix)
    return body[:limit]


class BaseAgent:
    id: str = ""
    focus: str = ""          # what the LLM pass should look for
    use_llm: bool = False

    def __init__(self, ctx: dict):
        self.ctx = ctx       # template, rules, context string, etc.
        self.cfg = AGENTS[self.id]
        self.notes: list[str] = []      # status lines for the UI

    # deterministic part — also used for re-checks after edits
    def rules(self, doc: Document) -> list[Finding]:
        return []

    async def analyze(self, doc: Document) -> list[Finding]:
        found = self.rules(doc)
        if self.use_llm and not llm.mock:
            try:
                found += await self.llm_pass(doc, found)
            except LLMError as e:
                log.warning("%s LLM pass failed: %s", self.id, e)
                self.notes.append("LLM недоступен — использую только правила")
        return found

    def finding(self, **kw) -> Finding:
        kw.setdefault("agent", self.id)
        kw.setdefault("criterion", self.cfg.get("criterion", "clarity"))
        return Finding(**kw)

    async def llm_pass(self, doc: Document, known: list[Finding]) -> list[Finding]:
        known_txt = "\n".join(f"- п. {f.section_ref}: {f.text}" for f in known) or "—"
        system = (
            f"Ты — агент «{self.cfg['name']}» ({self.cfg['role']}) в команде, которая проверяет ТЗ финтех-проекта "
            f"перед передачей в разработку. Твой фокус: {self.focus}\n"
            "Найди ДОПОЛНИТЕЛЬНЫЕ проблемы, которых нет в списке уже найденных. Не выдумывай: поле quote должно "
            "дословно встречаться в тексте ТЗ. Для каждой проблемы сформулируй уточняющий вопрос и 2–3 варианта "
            "ответа; new_text — готовая формулировка требования, которой заменится quote. Максимум 4 проблемы. "
            "Пиши по-русски."
        )
        user = (
            f"Контекст проекта: {self.ctx.get('context') or '—'}\n\nУже найдено:\n{known_txt}\n\n"
            f"{self.extra_prompt(doc)}Найди дополнительные проблемы в ТЗ выше."
        )
        # specialists use the cheap model; the TZ is a cached prefix shared by every agent, and the agent
        # may call its tools (knowledge base, facts table, template checklist, clause lookup) before answering
        from .tools import run_tool, tool_hint, tools_for
        from .. import learning
        system = system + (" " + tool_hint(self.cfg) if tool_hint(self.cfg) else "")
        res = await llm.run_agent(system, user, LLMFindings, tier="fast", doc=doc_for_prompt(doc),
                                  tools=tools_for(self.cfg), run_tool=lambda n, a: run_tool(n, a, doc),
                                  max_steps=3, agent=self.id, purpose="поиск проблем",
                                  learned=learning.lessons_prompt(self.ctx.get("scope", "local"), self.id))
        out = []
        for lf in res.findings[:4]:
            sev = lf.severity if lf.severity in ("critical", "important", "minor") else "important"
            opts = []
            for o in lf.options[:3]:
                if lf.quote:
                    ops = [PatchOp(mode="replace_sentence", section_ref=lf.section_ref, find=lf.quote, text=o.new_text)]
                else:
                    ops = [PatchOp(mode="append", section_ref=lf.section_ref, text=o.new_text)]
                opts.append((o.label, ops))
            slug = re.sub(r"\W+", "_", lf.text.lower())[:30]
            out.append(self.finding(
                severity=sev, key=f"llm:{slug}", section_ref=lf.section_ref,
                quote=lf.quote, text=lf.text, question=lf.question or None, why=lf.why or None,
                options=make_options(opts), confidence=0.8,
            ))
        return out

    def extra_prompt(self, doc: Document) -> str:
        return ""

    def summary(self, found: list[Finding]) -> str:
        n = len(found)
        if not n:
            return "Проблем не нашёл"
        return f"Нашёл {n} {plural(n, 'проблему', 'проблемы', 'проблем')}"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many
