"""Model-based agents of the review. Each one has a narrow job and a strict output schema; the document goes into
the (cached) system prompt once and is shared by all of them."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLMError, llm
from ..models import Document
from .models import Defect, Question, Requirement
from .standards import REQ_PROPS, SET_PROPS

log = logging.getLogger("review")

ReqProp = Literal["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable", "correct", "conforming"]
SetProp = Literal["complete", "consistent", "feasible", "comprehensible", "validatable", "ranked", "modifiable", "traceable"]
Sev = Literal["critical", "major", "minor"]

RULES = ("Правила ответа: только конкретные дефекты формулировок, каждый с дословной цитатой из документа (quote — точный "
         "фрагмент, 3–25 слов, без перефразирования). Никаких общих фраз без привязки к тексту. Не придумывай требования, "
         "которых нет, и не исправляй документ — только ревью. Пиши по-русски, коротко: problem — 1–2 предложения, что именно "
         "не так и чем это грозит разработке/тестированию; fix — как переформулировать. severity: critical — нельзя "
         "реализовать или проверить, противоречие; major — разработчик/тестировщик поймут по-разному; minor — оформление.")


def doc_text(doc: Document, limit: int = 30000) -> str:
    """The document as the agents see it: headings and text, without our internal numbering."""
    out = []
    for s in doc.sections:
        if s.level == 1:
            out.append(f"\n## {s.title}".rstrip() + (f"\n{s.text}" if s.text else ""))
        else:
            out.append(f"- {s.text}")
    return "\n".join(out)[:limit]


def _req_list(reqs: list[Requirement]) -> str:
    return "\n".join(f"{r.rid} [{r.doc_id}; {r.section}; {r.kind}]: {r.text}" for r in reqs)


# ---------------------------------------------------------------- 1. per requirement
class RDef(BaseModel):
    rid: str
    prop: ReqProp
    severity: Sev
    quote: str
    problem: str
    fix: str


class RDefs(BaseModel):
    defects: list[RDef] = Field(default_factory=list)


async def analyse_requirements(doc: Document, reqs: list[Requirement], batch: int = 14, on_batch=None) -> list[Defect]:
    props = "\n".join(f"- {k} — {v['name']} ({v['src']}): {v['ask']}" for k, v in REQ_PROPS.items())
    system = ("Ты — аналитик требований в команде ревью. Проверь каждое требование из списка по свойствам качественного "
              f"требования ISO/IEC/IEEE 29148:2018 §5.2.5:\n{props}\n\n" + RULES +
              " Для каждого требования верни 0–3 самых важных дефекта; если требование качественное — не возвращай для него ничего. "
              "Учитывай весь документ: если требование противоречит другому месту, это дефект correct с цитатой из этого требования.")
    known = {r.rid for r in reqs}
    parts = [reqs[i:i + batch] for i in range(0, len(reqs), batch)]
    sem = asyncio.Semaphore(int(os.getenv("REVIEW_PARALLEL", "4")))   # free tiers: keep it modest

    async def one(k: int, part: list[Requirement]) -> list[Defect]:
        async with sem:
            if on_batch:
                on_batch(k, len(parts), part)
            try:
                res = await llm.complete_json(system, "Требования для проверки:\n" + _req_list(part), RDefs, tier="fast",
                                              doc=doc_text(doc), max_tokens=8000, agent="analyst",
                                              purpose=f"требования {part[0].rid}–{part[-1].rid}")
            except LLMError as e:
                log.warning("requirement batch failed: %s", e)
                return []
        return [Defect(prop=d.prop, severity=d.severity, quote=d.quote, problem=d.problem, fix=d.fix,
                       rids=[d.rid], source="llm", agent="analyst") for d in res.defects if d.rid in known]

    results = await asyncio.gather(*(one(k, p) for k, p in enumerate(parts)))
    return [d for r in results for d in r]


# ---------------------------------------------------------------- 2. the set as a whole
class SDef(BaseModel):
    prop: SetProp
    severity: Sev
    rids: list[str]
    quote: str
    place: str
    problem: str
    fix: str


class SDefs(BaseModel):
    defects: list[SDef] = Field(default_factory=list)


async def analyse_set(doc: Document, reqs: list[Requirement], known: list[Defect]) -> list[Defect]:
    props = "\n".join(f"- {k} — {v['name']} ({v['src']}): {v['ask']}" for k, v in SET_PROPS.items())
    already = "\n".join(f"- {d.prop}: {d.problem}" for d in known) or "—"
    system = ("Ты — агент «Согласованность» в команде ревью. Проверь НАБОР требований целиком по свойствам "
              f"ISO/IEC/IEEE 29148:2018 §5.2.6 и IEEE 830 §4.3:\n{props}\n\n" + RULES +
              " Обязательно сверь каждое функциональное требование с каждой строкой критериев приёмки и примерами: если ожидаемый "
              "результат расходится с правилом (даты, суммы, условия) — это consistent, critical, rids обоих. "
              "Главное: противоречия между требованиями, между требованиями и критериями приёмки/примерами, между частью A и "
              "дочерним документом (часть B); пропущенные сценарии (ошибки, повторы, граничные случаи, откат), без которых нельзя "
              "разрабатывать. В rids перечисли все задействованные требования, в quote — цитату из одного из них, в place — разделы. "
              "Не повторяй уже найденное. Верни 3–10 дефектов.")
    try:
        res = await llm.complete_json(system, f"Требования:\n{_req_list(reqs)}\n\nУже найдено правилами (не повторять):\n{already}",
                                      SDefs, tier="strong", doc=doc_text(doc), max_tokens=8000, agent="contradictions",
                                      purpose="проверка набора")
    except LLMError as e:
        log.warning("set analysis failed: %s", e)
        return []
    ids = {r.rid for r in reqs}
    return [Defect(prop=d.prop, severity=d.severity, quote=d.quote, problem=d.problem, fix=d.fix, place=d.place,
                   rids=[x for x in d.rids if x in ids], source="llm", agent="contradictions") for d in res.defects]


# ---------------------------------------------------------------- 3. the Critic
class Ruling(BaseModel):
    n: int
    keep: bool
    severity: Sev
    reason: str


class Rulings(BaseModel):
    rulings: list[Ruling] = Field(default_factory=list)


async def critic(doc: Document, defects: list[Defect]) -> dict[int, Ruling]:
    """The Critic re-reads the model's findings against the document: drops the unfounded, fixes the severity."""
    llm_d = [(i, d) for i, d in enumerate(defects) if d.source == "llm"]
    if not llm_d:
        return {}
    listing = "\n".join(f"{i}. [{d.prop}; {d.severity}; {', '.join(d.rids) or d.place}] «{d.quote}» — {d.problem}" for i, d in llm_d)
    try:
        res = await llm.complete_json(
            "Ты — Критик в команде ревью требований. Для каждого замечания реши: keep=true, если дефект реальный и подтверждается "
            "текстом документа; keep=false — если это придирка, вкусовщина, дубль другого замечания или документ на самом деле "
            "это описывает. Поправь severity, если она завышена или занижена. reason — одно предложение. "
            "Читай буквально: если два места опираются на разные основания (дата совершения и дата проведения, "
            "сумма в тиынах и в тенге, «не более одного» и «независимо от истории») — противоречие реально, keep=true. "
            "Имя класса, контроллера или поля хранения (AlertsController, limit_kzt, card_id) — лишнее проектное решение, "
            "keep=true, даже если раздел шаблона называется «Архитектура» или «Схема». "
            "Если сомневаешься — keep=true. Если замечание повторяет другое из списка (та же проблема в тех же или "
            "соседних требованиях, другими словами) — keep=false, а reason начни со слова «Дубль n», где n — номер "
            "оставляемого замечания.",
            listing, Rulings, tier="strong", doc=doc_text(doc), max_tokens=6000, agent="critic", purpose="перепроверка замечаний")
    except LLMError as e:
        log.warning("critic failed: %s", e)
        return {}
    return {r.n: r for r in res.rulings}


# ---------------------------------------------------------------- 4. the Clarifier
class Q(BaseModel):
    text: str
    options: list[str]
    rids: list[str]
    why: str


class Qs(BaseModel):
    questions: list[Q] = Field(default_factory=list)


async def clarify(doc: Document, defects: list[Defect], reqs: list[Requirement]) -> list[Question]:
    top = [d for d in defects if d.severity != "minor"][:18]
    listing = "\n".join(f"- [{', '.join(d.rids) or d.place}] {d.problem}" for d in top)
    try:
        res = await llm.complete_json(
            "Ты — Уточнитель. По найденным дефектам сформулируй 5–8 уточняющих вопросов аналитику/заказчику — тех, без ответа "
            "на которые нельзя начать разработку. Каждый вопрос — про одно решение, конкретный, со ссылкой на требования (rids), "
            "2–3 варианта ответа (options) из практики банковских продуктов; why — зачем это знать разработке/тестированию. По-русски.",
            listing, Qs, tier="fast", doc=doc_text(doc), max_tokens=5000, agent="clarifier", purpose="уточняющие вопросы")
    except LLMError as e:
        log.warning("clarifier failed: %s", e)
        return []
    ids = {r.rid for r in reqs}
    return [Question(text=q.text, options=q.options[:3], rids=[x for x in q.rids if x in ids], why=q.why) for q in res.questions[:8]]
