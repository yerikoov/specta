"""Agents' debate: the Critic challenges findings, their authors defend or concede, the Critic rules.

Budget-aware by design — at most three rounds and a fixed number of calls, whatever the document size:
  1. Critic (strong model) picks up to MAX_CHALLENGES findings it doubts           — 1 call
  2. each challenged author (fast model) answers all its challenges at once        — ≤ 1 call per agent
  3. Critic rules on every disputed finding in one go                              — 1 call
The TZ is a cached prefix, so rounds 2–3 re-read it at a fraction of the price.
Without an API key the same three rounds are played from the rule engine's own evidence.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLMError, llm
from ..models import Document, Finding
from .base import doc_for_prompt
from .registry import AGENTS

log = logging.getLogger("debate")
MAX_CHALLENGES = int(os.getenv("DEBATE_MAX_CHALLENGES", "6"))


class Challenge(BaseModel):
    id: str
    objection: str


class Challenges(BaseModel):
    challenges: list[Challenge] = Field(default_factory=list)


class Reply(BaseModel):
    id: str
    stance: Literal["defend", "concede"]
    argument: str


class Replies(BaseModel):
    replies: list[Reply] = Field(default_factory=list)


class Ruling(BaseModel):
    id: str
    keep: bool
    reason: str


class Rulings(BaseModel):
    rulings: list[Ruling] = Field(default_factory=list)


def _turn(agent: str, to: str | None, kind: str, text: str, fid: str | None = None) -> dict:
    return {"agent": agent, "to": to, "kind": kind, "text": text, "finding_id": fid}


def _name(aid: str) -> str:
    return AGENTS.get(aid, {}).get("name", aid)


async def run(doc: Document, findings: list[Finding]) -> list[dict]:
    """Mutates findings (status='dropped' for those the Critic rejects). Returns the transcript."""
    open_f = [f for f in findings if f.status == "open"]
    if not open_f:
        return []
    if llm.mock:
        return _offline(findings)
    try:
        return await _with_claude(doc, open_f)
    except Exception as e:   # the debate must never break a check
        log.warning("debate fell back to rules: %s", e)
        return _offline(findings)


async def _with_claude(doc: Document, open_f: list[Finding]) -> list[dict]:
    text = doc_for_prompt(doc)
    by_id = {f.id: f for f in open_f}
    listing = "\n".join(f"{f.id} | {_name(f.agent)} | п. {f.section_ref or '—'} | {f.text} | цитата: {f.quote or '—'}"
                        for f in open_f)
    # 1) the Critic picks what it doubts
    ch = await llm.complete_json(
        "Ты — Критик. Ниже замечания агентов к ТЗ. Выбери только те, в которых сомневаешься всерьёз "
        f"(требование на деле измеримо, цитата вырвана из контекста, замечание не про это ТЗ, дубль). "
        f"Не больше {MAX_CHALLENGES}. Если всё верно — верни пустой список. objection — одно предложение.",
        f"Замечания (id | агент | пункт | суть | цитата):\n{listing}", Challenges, tier="strong", doc=text, max_tokens=6000,
        agent="critic", purpose="спор: возражения")
    challenges = [c for c in ch.challenges if c.id in by_id][:MAX_CHALLENGES]
    turns = [_turn("critic", by_id[c.id].agent, "objection", c.objection, c.id) for c in challenges]
    if not challenges:
        return [_turn("critic", None, "verdict", "Перепроверил все замечания — спорных нет.")]
    # 2) each author answers its challenges in one call
    replies: dict[str, Reply] = {}
    for aid in sorted({by_id[c.id].agent for c in challenges}):
        mine = [c for c in challenges if by_id[c.id].agent == aid]
        cfg = AGENTS[aid]
        lst = "\n".join(f"{c.id}: замечание «{by_id[c.id].text}» (п. {by_id[c.id].section_ref or '—'}) — возражение: {c.objection}"
                        for c in mine)
        try:
            res = await llm.complete_json(
                f"Ты — агент «{cfg['name']}» ({cfg['role']}). Критик оспорил твои замечания. По каждому: defend, "
                "если замечание верно (приведи факт из ТЗ), или concede, если критик прав. argument — одно предложение.",
                lst, Replies, tier="fast", doc=text, max_tokens=6000, agent=aid, purpose="спор: ответ критику")
            for r in res.replies:
                if r.id in by_id:
                    replies[r.id] = r
        except LLMError as e:
            log.warning("rebuttal by %s failed: %s", aid, e)
    for c in challenges:
        r = replies.get(c.id)
        if r:
            turns.append(_turn(by_id[c.id].agent, "critic", "defense" if r.stance == "defend" else "concession", r.argument, c.id))
    # 3) the Critic rules on all disputed findings at once
    disputed = "\n".join(f"{c.id}: «{by_id[c.id].text}» — возражение: {c.objection} — ответ автора: "
                         f"{(replies[c.id].stance + ': ' + replies[c.id].argument) if c.id in replies else 'нет ответа'}"
                         for c in challenges)
    ru = await llm.complete_json(
        "Ты — Критик и модератор. Вынеси решение по каждому спорному замечанию: keep=true — оставить, "
        "keep=false — снять. reason — одно предложение.", disputed, Rulings, tier="strong", doc=text, max_tokens=6000,
        agent="critic", purpose="спор: решение")
    for r in ru.rulings:
        f = by_id.get(r.id)
        if not f:
            continue
        if not r.keep:
            f.status, f.drop_reason = "dropped", f"снято после обсуждения: {r.reason}"
        turns.append(_turn("critic", f.agent, "verdict", ("Оставляем: " if r.keep else "Снимаем: ") + r.reason, f.id))
    return turns


def _offline(findings: list[Finding]) -> list[dict]:
    """The same three rounds, argued from the rule engine's evidence (no API calls)."""
    turns: list[dict] = []
    dropped = [f for f in findings if f.status == "dropped"][:3]
    for f in dropped:
        turns.append(_turn("critic", f.agent, "objection", f"«{_short(f.text)}» — сомневаюсь: {f.drop_reason}.", f.id))
        turns.append(_turn(f.agent, "critic", "concession", "Согласен, снимаю это замечание.", f.id))
    shaky = sorted([f for f in findings if f.status == "open" and f.severity != "critical"],
                   key=lambda f: f.confidence)[:2]
    for f in shaky:
        turns.append(_turn("critic", f.agent, "objection",
                           f"п. {f.section_ref or '—'}: «{_short(f.text)}» — точно ли это блокирует разработку?", f.id))
        turns.append(_turn(f.agent, "critic", "defense",
                           (f.why or "Без уточнения разработчик и тестировщик поймут требование по-разному.").rstrip(".") + ".", f.id))
        turns.append(_turn("critic", f.agent, "verdict", "Аргумент принят — оставляем.", f.id))
    if not turns:
        turns.append(_turn("critic", None, "verdict", "Перепроверил все замечания — спорных нет."))
    return turns


def _short(t: str, n: int = 70) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[: n - 1] + "…"
