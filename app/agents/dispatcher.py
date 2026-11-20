"""Dispatcher: chooses which specialist agents run for THIS document (plain Python)."""
from __future__ import annotations

import re

from ..models import Document
from ..parsing import load_rules
from .contradictions import facts_table
from .registry import AGENTS, SPECIALISTS

ROUTES = [  # free-text message routing: regex -> agent
    (r"лимит|сумм|противореч|дат|комисси", "contradictions"),
    (r"kyc|aml|идентифик|регулятор|комплаенс|персональн|pci|санкц", "regulatory"),
    (r"безопасн|шифр|фрод|мошен|журнал|аудит", "security"),
    (r"тест|приёмк|приемк|провер", "testability"),
    (r"интеграц|api|процессинг|шлюз", "integrations"),
    (r"нагрузк|доступност|sla|rto|rpo", "nfr"),
    (r"раздел|шаблон|не хватает|отсутств", "completeness"),
    (r"формулир|размыт|понятн|быстро|удобн", "ambiguity"),
]


def decide(doc: Document, template: dict) -> list[dict]:
    text = (doc.full_text() + "\n" + "\n".join(doc.appendix)).lower()
    n_req = len(re.findall(r"должн|необходимо|выполня|может", text))
    n_facts = len(facts_table(doc, load_rules()["fact_keys"]))
    plan = []
    for aid in SPECIALISTS:
        cfg = AGENTS[aid]
        hits: dict[str, int] = {}
        for p in cfg.get("triggers", []):
            found = [m.group(0) for m in re.finditer(p, text)]
            if found and p != ".":
                hits[found[0].strip()] = hits.get(found[0].strip(), 0) + len(found)
        chosen = bool(hits) or aid == "completeness"
        if aid == "contradictions":
            chosen = n_facts >= 2
        hit_txt = ", ".join(f"«{w}» ×{c}" for w, c in sorted(hits.items(), key=lambda x: -x[1])[:2])
        reason = cfg.get("reason", "").format(template=template.get("template_name", "шаблон"), n=n_req if aid != "contradictions" else n_facts, hits=hit_txt)
        if not chosen:
            reason = "пропущен — " + cfg.get("skip_reason", "тема не встречается в ТЗ")
        plan.append({"agent": aid, "chosen": chosen, "reason": reason})
    return plan


def route(message: str) -> str:
    low = message.lower()
    for rx, agent in ROUTES:
        if re.search(rx, low):
            return agent
    return "dispatcher"


# ---------------------------------------------------------------------- Claude-powered team selection
from pydantic import BaseModel  # noqa: E402

from ..llm import LLMError, llm  # noqa: E402
from .base import doc_for_prompt  # noqa: E402


class Pick(BaseModel):
    agent: str
    chosen: bool
    reason: str


class TeamPlan(BaseModel):
    agents: list[Pick]


async def decide_llm(doc: Document, template: dict, rules_plan: list[dict]) -> list[dict]:
    """The Dispatcher (Claude Haiku) reads the TZ and picks the team. The rule-based plan is a hint and the
    fallback. Same model and same cached TZ prefix as the specialists, so their calls then read it from cache."""
    roster = "\n".join(f"- {aid}: {AGENTS[aid]['name']} — {AGENTS[aid]['role']}. {AGENTS[aid]['line']}" for aid in SPECIALISTS)
    hint = "\n".join(f"- {p['agent']}: {'да' if p['chosen'] else 'нет'} ({p['reason']})" for p in rules_plan)
    try:
        res = await llm.complete_json(
            "Ты — Диспетчер команды проверки ТЗ. Реши, какие эксперты нужны именно этому документу. "
            "Полнота нужна всегда. Комплаенс и Безопасность — если есть деньги, карты, персональные данные или вход в систему. "
            "Интеграции — если есть внешние системы. НФТ — если есть требования к скорости, нагрузке, доступности. "
            "reason — коротко, почему (по-русски, со ссылкой на то, что в ТЗ).",
            f"Эксперты:\n{roster}\n\nПредварительный выбор по правилам:\n{hint}", TeamPlan, tier="fast",
            doc=doc_for_prompt(doc), max_tokens=6000, agent="dispatcher", purpose="выбор команды")
    except LLMError:
        return rules_plan
    picks = {p.agent: p for p in res.agents if p.agent in SPECIALISTS}
    out = []
    for p in rules_plan:
        q = picks.get(p["agent"])
        if q and p["agent"] != "completeness":
            out.append({"agent": p["agent"], "chosen": q.chosen, "reason": q.reason if q.chosen else "пропущен — " + q.reason})
        else:
            out.append(p)
    return out
