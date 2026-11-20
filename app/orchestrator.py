"""Orchestration: Parser → Dispatcher → specialists (parallel) → Critic → Clarifier → Reporter.

All chat output goes through Session.emit(Event) — one schema for every agent.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from pydantic import BaseModel

from . import scoring
from .agents import clarifier, critic, debate
from .agents.ambiguity import AmbiguityAgent
from .agents.base import BaseAgent, doc_for_prompt, plural
from .doccheck import tz_likeness
from .agents.completeness import CompletenessAgent
from .agents.contradictions import ContradictionsAgent
from .agents.dispatcher import decide, decide_llm, route
from .agents.integrations import IntegrationsAgent
from .agents.kbcheck import RegulatoryAgent, SecurityAgent
from .agents.nfr import NFRAgent
from .agents.registry import AGENTS, emotion
from .agents.testability import TestabilityAgent
from . import learning
from .agents.tools import run_tool, tool_hint, tools_for
from .llm import LLMError, llm, meter, record, trace
from .models import Event, Finding, Option, Question
from .parsing import load_rules, load_template
from .patching import apply_custom, apply_ops, undo
from .db import save_now
from .store import Session

log = logging.getLogger("orchestrator")

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    c.id: c for c in (CompletenessAgent, AmbiguityAgent, ContradictionsAgent, TestabilityAgent,
                      RegulatoryAgent, SecurityAgent, IntegrationsAgent, NFRAgent)
}


def ctx_for(s: Session) -> dict:
    return {"template": load_template(), "rules": load_rules(), "context": s.context, "scope": s.user_id or "local"}


async def pause(lo: float = 0.3, hi: float = 0.9) -> None:
    d = llm.mock_delay(lo, hi) if llm.mock else min(0.25, llm.mock_delay(lo, hi))
    if d > 0:
        await asyncio.sleep(d)


def name(aid: str) -> str:
    return AGENTS[aid]["name"]


def short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ====================================================================== ANALYSIS
async def run_analysis(s: Session) -> None:
    meter.set(s.usage)
    trace.set(s.trace)
    log_ = s.analyze_log

    async def step(key: str, state: str):
        await log_.push({"type": "step", "step": key, "state": state})

    async def item(key: str, text: str, agent: str | None = None, emo: str | None = None):
        await pause()
        await log_.push({"type": "item", "step": key, "text": text, "agent": agent, "emotion": emo})

    try:
        doc, template = s.doc, load_template()
        # 1. read ------------------------------------------------------------
        await step("read", "active")
        top = [x for x in doc.sections if x.level == 1]
        items = [x for x in doc.sections if x.level > 1]
        await item("read", f"Файл: {doc.filename} ({doc.filetype.upper()})", "parser", "curious")
        await item("read", f"Страниц: {doc.pages}")
        await item("read", f"Найдено разделов: {len(top)}, пронумерованных пунктов: {len(items)}", "parser", "happy")
        if s.context:
            await item("read", f"Контекст проекта учтён: «{short(s.context, 70)}»")
        like = tz_likeness(doc)
        if not like["ok"]:
            s.warning = f"Документ не похож на техническое задание: {like['reason']}."
            await item("read", f"Внимание: {s.warning[0].lower()}{s.warning[1:]} Проверю, но оценка будет формальной.", "parser", "surprised")
        await step("read", "done")

        # 2. structure ---------------------------------------------------------
        await step("structure", "active")
        mapped = [x for x in top if x.template_key]
        tpl = template["sections"]
        await item("structure", f"Шаблон: {template.get('template_name', 'шаблон')} — {len(tpl)} разделов")
        await item("structure", "Сопоставлено: " + ", ".join(f"п. {x.ref} → {next(t['name'] for t in tpl if t['key'] == x.template_key)}" for x in mapped[:6]) + ("…" if len(mapped) > 6 else ""))
        missing = [t for t in tpl if t.get("required") and not doc.by_template(t["key"])]
        for t in missing:
            await item("structure", f"Нет раздела: «{t['name']}»", "completeness", "surprised")
        await item("structure", f"Покрытие шаблона: {len(mapped)} из {len(tpl)}")
        await step("structure", "done")

        # 3. team --------------------------------------------------------------
        await step("team", "active")
        t0 = time.perf_counter()
        s.plan = decide(doc, template)
        record("rules", "dispatcher", purpose="выбор команды по ключевым словам", found=sum(p["chosen"] for p in s.plan),
               ms=round((time.perf_counter() - t0) * 1000, 1))
        await item("team", "Диспетчер анализирует темы документа…", "dispatcher", "curious")
        if not llm.mock:
            s.plan = await decide_llm(doc, template, s.plan)
        for p in sorted(s.plan, key=lambda p: not p["chosen"]):
            emo = "happy" if p["chosen"] else "sleepy"
            await item("team", f"{name(p['agent'])}: {p['reason']}", p["agent"], emo)
        await step("team", "done")

        # 4. checks (parallel) ---------------------------------------------------
        await step("checks", "active")
        ctx = ctx_for(s)
        active = [p["agent"] for p in s.plan if p["chosen"]]

        async def run_one(aid: str):
            agent = AGENT_CLASSES[aid](ctx)
            await asyncio.sleep(llm.mock_delay(0.6, 2.4) if llm.mock else 0)
            try:
                t0 = time.perf_counter()
                found = await agent.analyze(doc)
                record("rules", aid, purpose="правила + проверки", found=len(found), ms=round((time.perf_counter() - t0) * 1000, 1))
                return aid, agent, found, None
            except Exception as e:  # an agent failing must not break the run
                log.exception("agent %s failed", aid)
                return aid, agent, [], e

        tasks = [asyncio.create_task(run_one(a)) for a in active]
        for fut in asyncio.as_completed(tasks):
            aid, agent, found, err = await fut
            s.findings.extend(found)
            entry = next(p for p in s.plan if p["agent"] == aid)
            entry["summary"] = agent.summary(found) if not err else "Ошибка проверки"
            entry["notes"] = agent.notes
            entry["failed"] = bool(err)
            emo = "sad" if err else ("surprised" if found else "happy")
            await log_.push({"type": "item", "step": "checks", "text": f"{name(aid)}: {entry['summary']}", "agent": aid, "emotion": emo})
        # agents finish in random order: put findings in team order and number them stably, so the critic,
        # the debate and the duplicate merge see the same prompt for the same TZ (→ answers come from the cache)
        s.findings.sort(key=lambda f: active.index(f.agent) if f.agent in active else 99)
        for i, f in enumerate(s.findings, 1):
            f.id = f"fk{i}"
        dropped = await critic.review(doc, s.findings, set(active))
        s.critic_dropped = [f.id for f in dropped]
        await item("checks", f"Критик: перепроверил {len(s.findings)} {plural(len(s.findings), 'замечание', 'замечания', 'замечаний')}, отклонил {len(dropped)}", "critic", "wink")
        # the Critic argues with the authors about the findings it doubts (Claude: Sonnet vs Haiku)
        before_open = sum(1 for f in s.findings if f.status == "open")
        s.debate = await debate.run(doc, s.findings)
        removed = before_open - sum(1 for f in s.findings if f.status == "open")
        n_obj = sum(1 for t in s.debate if t["kind"] == "objection")
        await item("checks", f"Обсуждение: Критик оспорил {n_obj}, после спора снято ещё {removed}" if n_obj
                   else "Обсуждение: спорных замечаний нет", "critic", "curious")
        # what the team rejected becomes a lesson for that agent's next checks
        scope = ctx_for(s)["scope"]
        used = sum(len(learning.lessons(scope, p["agent"])) for p in s.plan if p["chosen"]) if not llm.mock else 0
        new_l = [f for f in s.findings if f.status == "dropped" and f.key.startswith("llm:")]
        for f in new_l:
            learning.record_rejected(scope, f, f.drop_reason or "")
        if used or new_l:
            await item("checks", "Опыт: " + ", ".join(x for x in (
                f"агенты учли {used} {plural(used, 'урок', 'урока', 'уроков')} прошлых проверок" if used else "",
                f"запомнил {len(new_l)} {plural(len(new_l), 'отклонённое замечание', 'отклонённых замечания', 'отклонённых замечаний')} на будущее" if new_l else "")
                if x), "critic", "wink")
        await step("checks", "done")

        # 5. questions ----------------------------------------------------------
        await step("questions", "active")
        await adapt_wording(s)
        dupes = await find_duplicates(s)
        s.questions, singles = clarifier.make_questions(s.findings, dupes)
        crit = sum(1 for q in s.questions if q.priority == "critical")
        n_dup = sum(len(q.also) for q in s.questions)
        await item("questions", f"Уточнитель: {len(s.questions)} вопросов, из них критичных — {crit}", "clarifier", "curious")
        if singles > len(s.questions):
            await item("questions", f"Было {singles} уточнений → стало {len(s.questions)}: "
                       + (f"{n_dup} {plural(n_dup, 'повтор', 'повтора', 'повторов')} от разных агентов слил, " if n_dup else "")
                       + "похожие собрал в группы. Итоговое ТЗ то же", "clarifier", "happy")
        first = min(clarifier.MAX_OPEN, len(s.questions))
        await item("questions", f"Первая партия: {first} {plural(first, 'вопрос', 'вопроса', 'вопросов')} — начнём с критичных")
        s.score_before = s.score = score_of(s)
        await item("questions", f"Стартовая оценка: {s.score['total']}/100", "reporter", "neutral")
        await step("questions", "done")
        await log_.push({"type": "done"})
        await save_now(s)
    except Exception as e:
        log.exception("analysis failed")
        await log_.push({"type": "error", "text": str(e)})
        if s.score is None:   # keep the check usable with what was found so far
            s.questions = s.questions or clarifier.make_questions(s.findings)[0]
            s.score_before = s.score = score_of(s)
    finally:
        s.analyzed.set()
        await log_.close()


# ====================================================================== CHAT
class Adapted(BaseModel):
    class Item(BaseModel):
        i: int
        text: str
    items: list[Item] = []


def _digits(t: str) -> list[str]:
    return re.findall(r"\d+", t)


async def adapt_wording(s: Session) -> None:
    """Ready-made fixes from the rules / KB are written in neutral words («операция», «клиент»).
    One cheap Haiku call rewrites them in this TZ's own terms (рассрочка, депозит, перевод…) without touching
    any number; a rewrite that changes a number is ignored. Cached like every other call."""
    if llm.mock:
        return
    ops = [op for f in s.findings if f.status == "open" and not f.key.startswith("llm:")
           for o in f.options for op in o.ops if op.text and len(op.text) > 25]
    texts = list(dict.fromkeys(op.text for op in ops))
    if not texts:
        return
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    try:
        res = await llm.complete_json(
            "Ты — редактор ТЗ. Ниже — готовые формулировки требований, написанные нейтрально. Перепиши каждую "
            "в терминах ТЗ выше: тот же продукт, те же участники и объекты (например, «операция» → «оформление рассрочки», "
            "если ТЗ о рассрочке). Не меняй ни одного числа, единицы и смысла требования, не добавляй новых условий. "
            "Если формулировка уже подходит — верни её без изменений. Верни все номера.",
            listing, Adapted, tier="fast", doc=doc_for_prompt(s.doc), max_tokens=8000,
            agent="clarifier", purpose="формулировки под ТЗ")
    except LLMError as e:
        log.warning("wording adaptation skipped: %s", e)
        return
    new = {it.i: it.text.strip() for it in res.items if 0 <= it.i < len(texts) and it.text.strip()}
    swap = {texts[i]: t for i, t in new.items() if _digits(t) == _digits(texts[i])}
    for op in ops:
        op.text = swap.get(op.text, op.text)


class Dupes(BaseModel):
    groups: list[list[int]] = []


async def find_duplicates(s: Session) -> list[list[int]]:
    """One cheap Haiku call: which questions from different agents ask for the same decision."""
    if llm.mock:
        return []
    qs = clarifier.ordered(clarifier.build_questions(s.findings, []))
    if len(qs) < 4:
        return []
    listing = "\n".join(f"{i}. [{name(q.agent)}] {q.text}" for i, q in enumerate(qs))
    try:
        res = await llm.complete_json(
            "Ты — Уточнитель в команде проверки ТЗ. Найди вопросы, которые по сути об одном и том же решении "
            "(ответ на один закрывает другой), даже если их задали разные агенты разными словами. "
            "Не объединяй вопросы о разных параметрах или разных пунктах. Верни группы номеров; вопросы без пары не включай.",
            listing, Dupes, tier="fast", max_tokens=2000, agent="clarifier", purpose="слияние повторов")
        return [g for g in res.groups if len(g) > 1]
    except LLMError as e:
        log.warning("duplicate merge skipped: %s", e)
        return []


def score_of(s: Session) -> dict:
    return scoring.compute(s.findings, cap=scoring.NOT_TZ_CAP if s.warning else None)


def agent_states(s: Session) -> dict[str, str]:
    st = {}
    for p in s.plan:
        aid = p["agent"]
        if not p["chosen"]:
            st[aid] = "sleepy"
        elif p.get("failed"):
            st[aid] = "sad"
        elif any(q.agent == aid and q.status == "open" for q in s.questions):
            st[aid] = emotion(aid, "blocked")
        elif any(f.agent == aid and f.status == "open" for f in s.findings):
            st[aid] = "curious"
        else:
            st[aid] = "wink" if s.reported else "happy"
    st["dispatcher"] = "neutral"
    st["critic"] = "wink"
    st["clarifier"] = "angry" if any(q.status == "open" for q in s.questions) else "happy"
    st["reporter"] = "happy" if s.reported else "neutral"
    return st


def finding_event(f: Finding, into: str | None = None) -> Event:
    return Event(agent=f.agent, type="finding", severity=f.severity, section_ref=f.section_ref, text=f.text,
                 quote=f.quote, emotion=emotion(f.agent, "found"),
                 data={"finding_id": f.id, "refs": f.refs, "criterion": f.criterion,
                       "criterion_label": scoring.CRITERIA.get(f.criterion, f.criterion), "in": into, "row": f.agent})


def question_progress(s: Session, q: Question) -> dict:
    """«Вопрос n из total»: count only the important ones until the user opts into the minor ones."""
    pool = s.questions if (s.minor_ok or q.priority == "minor") else [x for x in s.questions if x.priority != "minor"]
    return {"n": sum(1 for x in pool if x.status != "queued" or x.skipped), "total": len(pool)}


def question_event(s: Session, q: Question) -> Event:
    f = None if q.members else s.finding(q.finding_id)
    return Event(agent=q.agent, type="question", severity=q.priority, section_ref=f.section_ref if f else None,
                 text=q.text, quote=f.quote if f else None,
                 options=[Option(key=o.key, label=o.label) for o in q.options], allow_custom=not q.members,
                 emotion=emotion(q.agent, "blocked"),
                 data={"question_id": q.id, "why": q.why, "finding_id": q.finding_id, "items": q.items,
                       "popular": learning.popular(f, [o.label for o in q.options]) if f else None,
                       "also": sorted({g.agent for g in (s.finding(x) for x in q.also) if g and g.agent != q.agent}),
                       **question_progress(s, q)})


async def score_event(s: Session, text: str, final: bool = False, agent: str = "reporter", into: str | None = None,
                      extra: dict | None = None) -> None:
    prev = s.score["total"] if s.score else None
    s.score = score_of(s)
    await s.emit(Event(agent=agent, type="score", text=text, emotion="happy" if (prev is None or s.score["total"] >= prev) else "sad",
                       data={**s.score, "prev": prev, "before": s.score_before["total"] if s.score_before else None,
                             "before_criteria": s.score_before["criteria"] if s.score_before else None,
                             "final": final, "states": agent_states(s), "in": into, **(extra or {})}))


def verdict(total: int, crit: int) -> str:
    if total >= 80 and not crit:
        return "ТЗ в хорошем состоянии — осталось несколько уточнений."
    if total >= 60:
        return "ТЗ почти готово, но есть пробелы, которые разработчики заполнят догадками."
    return f"ТЗ пока рано отдавать в разработку: {crit} {plural(crit, 'критичная проблема', 'критичные проблемы', 'критичных проблем')}." if crit \
        else "ТЗ пока рано отдавать в разработку: много размытых и непроверяемых требований."


def summary_data(s: Session) -> dict:
    open_f = [f for f in s.findings if f.status == "open"]
    counts = {k: sum(1 for f in open_f if f.severity == k) for k in ("critical", "important", "minor")}
    # the three most important problems, preferably from different agents (so the card shows breadth)
    ranked = [s.finding(q.finding_id) for q in clarifier.ordered([q for q in s.questions if q.status != "answered"])]
    ranked = [f for f in ranked if f]
    picked, seen_agents = [], set()
    for f in ranked:
        if f.agent not in seen_agents and len(picked) < 3:
            picked.append(f); seen_agents.add(f.agent)
    picked += [f for f in ranked if f not in picked][: 3 - len(picked)]
    order = {"critical": 0, "important": 1, "minor": 2}
    top = [{"text": short(f.text, 120), "ref": f.section_ref or "", "fid": f.id, "severity": f.severity, "agent": f.agent}
           for f in sorted(picked, key=lambda f: order[f.severity])]
    main_q = sum(1 for q in s.questions if q.priority != "minor")
    v = (f"{s.warning} Если файл выбран по ошибке — загрузите ТЗ; оценка ниже посчитана формально."
         if s.warning else verdict(s.score["total"], counts["critical"]))
    return {"verdict": v, "warning": bool(s.warning), "counts": counts, "top": top,
            "questions": len(s.questions), "main_questions": main_q, "minor_questions": len(s.questions) - main_q,
            "actions": [{"label": f"Исправить по шагам · {main_q or len(s.questions)} {plural(main_q or len(s.questions), 'вопрос', 'вопроса', 'вопросов')}",
                         "cmd": "start", "primary": True},
                        {"label": "Применить всё автоматически", "cmd": "improve"}] if s.questions else []}


async def run_chat_intro(s: Session) -> None:
    """Summary-first intro: 1) one compact team board (collapsed), 2) a summary card with the score,
    what is wrong and one primary action. Questions start only when the user asks for them."""
    await s.analyzed.wait()
    if s.intro_done:
        return
    s.intro_done = True
    await asyncio.sleep(1.4 if llm.mock and llm.delay_scale else 0.2)  # let the big title breathe
    chosen = [p for p in s.plan if p["chosen"]]
    skipped = [p for p in s.plan if not p["chosen"]]
    states = agent_states(s) | {p["agent"]: "curious" for p in chosen}
    await s.emit(Event(
        agent="dispatcher", type="status", emotion="happy",
        text=f"Собрал команду из {len(chosen)} {plural(len(chosen), 'агента', 'агентов', 'агентов')} — проверяют «{short(s.doc.title, 60)}».",
        data={"team": [p["agent"] for p in chosen], "states": states,
              "group": {"id": "checks", "title": "Проверка", "collapsed": True,
                        "rows": [{"agent": p["agent"], "text": p["reason"]} for p in chosen]}},
    ))
    for p in chosen:
        aid = p["agent"]
        mine = [f for f in s.findings if f.agent == aid and f.status == "open"]
        await pause(0.35, 0.8)
        extra = (" " + "; ".join(p.get("notes", []))) if p.get("notes") else ""
        counts = {k: sum(1 for f in mine if f.severity == k) for k in ("critical", "important", "minor")}
        await s.emit(Event(agent=aid, type="status", text=(p.get("summary") or "Готово") + extra,
                           emotion=emotion(aid, "found" if mine else ("failed" if p.get("failed") else "done")),
                           data={"in": "checks", "row": aid, "counts": counts}))
        for f in mine:
            await s.emit(finding_event(f, into="checks"))
    dropped = [f for f in s.findings if f.status == "dropped"]
    n_all = len(s.findings)
    await s.emit(Event(
        agent="critic", type="status", emotion="wink",
        text=(f"Критик перепроверил {n_all} {plural(n_all, 'замечание', 'замечания', 'замечаний')} и убрал {len(dropped)} — они не подтвердились."
              if dropped else f"Критик перепроверил {n_all} замечаний — все подтвердились."),
        data={"in": "checks", "footer": True,
              "items": [f"{name(f.agent)}, п. {f.section_ref or '—'}: {short(f.text, 60)} — {f.drop_reason}" for f in dropped]
              + [f"Не понадобился: {name(p['agent'])} — {p['reason']}" for p in skipped]},
    ))
    if s.debate:
        await pause(0.4, 0.8)
        talkers = []
        for t in s.debate:
            for a in (t["agent"], t.get("to")):
                if a and a not in talkers:
                    talkers.append(a)
        await s.emit(Event(agent="critic", type="status", emotion="curious",
                           text="Перед итогом Критик поспорил с авторами сомнительных замечаний:",
                           data={"group": {"id": "debate", "title": f"Обсуждение агентов · {len(s.debate)} "
                                           f"{plural(len(s.debate), 'реплика', 'реплики', 'реплик')}",
                                           "collapsed": True, "agents": talkers}}))
        for t in s.debate:
            to = f" → {name(t['to'])}" if t.get("to") else ""
            emo = {"objection": "curious", "defense": "angry", "concession": "sad", "verdict": "wink"}.get(t["kind"], "neutral")
            await s.emit(Event(agent=t["agent"], type="status", emotion=emo, text=f"{name(t['agent'])}{to}: {t['text']}",
                               data={"in": "debate", "kind": t["kind"], "finding_id": t.get("finding_id")}))
    await pause(0.6, 1.0)
    s.score = score_of(s)
    await score_event(s, "Итог проверки", extra={"summary": summary_data(s)})
    await save_now(s)
    if not s.questions:
        await final_report(s)


async def open_next_batch(s: Session, announce: bool = True, force: bool = False) -> int:
    batch = clarifier.next_batch(s.questions) if not force else clarifier.ordered([q for q in s.questions if q.status == "queued"])[:1]
    if not batch:
        return 0
    # the important ones are done: offer to finish the minor ones in one click instead of N more questions
    if batch[0].priority == "minor" and not s.minor_ok and not s.minor_asked and not force:
        s.minor_asked = True
        n = sum(1 for q in s.questions if q.status == "queued" and q.priority == "minor")
        await s.emit(Event(agent="clarifier", type="status", emotion="happy",
                           text=f"Важное разобрали! Осталось {n} {plural(n, 'мелкое уточнение', 'мелких уточнения', 'мелких уточнений')} — "
                                "применить рекомендованные формулировки сразу или пройти по одному?",
                           data={"actions": [{"label": "Применить рекомендации", "cmd": "improve", "primary": True},
                                             {"label": "Пройти по одному", "cmd": "questions"}]}))
        return 1
    for q in batch:
        q.status = "open"
        await pause(0.2, 0.5)
        await s.emit(question_event(s, q))
    return len(batch)


async def skip_question(s: Session, qid: str) -> None:
    q = s.question(qid)
    if not q or q.status != "open":
        return
    q.status, q.skipped = "queued", True
    await s.emit(Event(agent="clarifier", type="applied", text="Пропустили — вернусь к этому вопросу в конце.", emotion="neutral",
                       data={"question_id": q.id, "skipped": True, "diff": [], "in": q.id}))
    if not await open_next_batch(s, force=True) and not s.reported:
        await final_report(s)


async def maybe_continue(s: Session) -> None:
    if await open_next_batch(s):
        return
    if not any(q.status in ("open", "queued") for q in s.questions) and not s.reported:
        await final_report(s)


async def final_report(s: Session) -> None:
    await pause()
    await s.emit(Event(agent="reporter", type="status", emotion="curious", text="Все вопросы закрыты. Собираю итоговый отчёт и тест-кейсы…"))
    s.tests = await TestabilityAgent(ctx_for(s)).generate_tests(s.doc)
    s.reported = True
    s.score = score_of(s)  # the done card shows before → after itself
    s.summary = await client_summary(s)
    before, after = s.score_before["total"], s.score["total"]
    resolved = sum(1 for f in s.findings if f.status == "resolved")
    still = sum(1 for f in s.findings if f.status == "open")
    await s.emit(Event(
        agent="reporter", type="done", emotion="happy",
        text=f"Готово! Оценка выросла с {before} до {after} из 100. Исправлено замечаний: {resolved}, осталось открытых: {still}. "
             f"Сгенерировал {len(s.tests)} приёмочных тест-кейсов.",
        data={"before": s.score_before, "after": s.score, "resolved": resolved, "open": still, "tests": s.tests,
              "downloads": [
                  {"label": "Скачать улучшенное ТЗ (.docx)", "url": f"/api/report/{s.id}/export?format=docx"},
                  {"label": "Markdown", "url": f"/api/report/{s.id}/export?format=md"},
                  {"label": "Отчёт (.md)", "url": f"/api/report/{s.id}/export?format=md&kind=report"},
              ], "summary": s.summary, "share": True, "cost": round(s.usage.get("usd", 0), 4),
              "states": agent_states(s)},
    ))
    await save_now(s)


class ClientSummary(BaseModel):
    headline: str
    verdict: str
    highlights: list[str]
    risks: list[str]
    next_steps: list[str]


async def client_summary(s: Session) -> dict:
    """One page for the customer: what was wrong, what changed, what is still open. Claude Opus, one call."""
    before, after = s.score_before["total"], s.score["total"]
    resolved = [f for f in s.findings if f.status == "resolved"]
    still = [f for f in s.findings if f.status == "open"]
    fallback = {
        "headline": f"ТЗ «{short(s.doc.title, 70)}»: оценка {before} → {after} из 100",
        "verdict": ("Готово к передаче в разработку." if after >= 80 and not any(f.severity == "critical" for f in still)
                    else "Нужна ещё одна итерация с заказчиком перед разработкой."),
        "highlights": [f"Исправлено замечаний: {len(resolved)}, из них критичных — {sum(f.severity == 'critical' for f in resolved)}",
                       f"Добавлено и уточнено требований: {sum(len(v.get('changes', [])) for v in s.versions)}",
                       f"Подготовлено приёмочных тест-кейсов: {len(s.tests)}"],
        "risks": [f"п. {f.section_ref or '—'}: {short(f.text, 110)}" for f in sorted(still, key=lambda f: f.severity != "critical")[:4]]
                 or ["Открытых рисков нет"],
        "next_steps": ["Согласовать улучшенную версию ТЗ с бизнес-заказчиком",
                       "Передать тест-кейсы команде QA вместе с ТЗ"]
                      + (["Закрыть оставшиеся замечания до старта спринта"] if still else []),
    }
    if llm.mock:
        return fallback
    try:
        facts = (f"Оценка: {before} → {after} из 100. Критерии: "
                 + ", ".join(f"{c['label']} {c['value']}" for c in s.score["criteria"])
                 + "\nИсправлено:\n" + "\n".join(f"- {short(f.text, 140)}" for f in resolved[:25])
                 + "\nОткрыто:\n" + ("\n".join(f"- [{f.severity}] п. {f.section_ref}: {short(f.text, 140)}" for f in still[:15]) or "—"))
        res = await llm.complete_json(
            "Ты — руководитель команды аналитиков. Напиши итог проверки ТЗ для заказчика (не технический язык): "
            "headline — одна строка с главным результатом; verdict — можно ли отдавать в разработку и почему; "
            "highlights — 3-4 главных улучшения; risks — до 4 оставшихся рисков; next_steps — 2-3 шага.",
            facts, ClientSummary, tier="lead", doc=doc_for_prompt(s.doc), max_tokens=6000, agent="reporter", purpose="итог для заказчика")
        return res.model_dump()
    except LLMError as e:
        log.warning("client summary fell back to template: %s", e)
        return fallback


# ====================================================================== ANSWERS
class AnswerError(Exception):
    pass


async def answer(s: Session, qid: str, choice_key: str | None, custom: str | None, quiet: bool = False,
                 into: str | None = None) -> dict:
    q = s.question(qid)
    if not q:
        raise AnswerError("вопрос не найден")
    if q.status == "answered":
        raise AnswerError("на вопрос уже ответили")
    f = s.finding(q.finding_id)
    if q.members and choice_key == clarifier.SPLIT:
        return await split_bundle(s, q, into)
    template = load_template()
    if custom and custom.strip():
        diff, snap = apply_custom(s.doc, f, custom.strip(), template)
        label, key = custom.strip(), "custom"
    else:
        opt = next((o for o in q.options if o.key == choice_key), None)
        if not opt:
            raise AnswerError("нет такого варианта")
        diff, snap = apply_ops(s.doc, opt.ops, template)
        label, key = opt.label, opt.key
    q.status, q.answer_key, q.answer_text, q.undo = "answered", key, label, snap
    if not quiet and not q.members and key != "custom":
        learning.record_choice(f, label)       # «Чаще выбирают» for the same problem in later checks
    for fid in (q.members or [q.finding_id]) + q.also:
        if (m := s.finding(fid)) and m.status == "open":
            m.status, m.closed_by = "resolved", (q.id if m is not f else None)
    s.versions.append({"n": len(s.versions) + 1, "ts": time.time(), "label": short(f"{q.text} → {label}", 110),
                       "question": q.text, "answer": label, "changes": diff, "question_id": q.id})
    refs = sorted({d["section_ref"] for d in diff})
    if diff:
        text = f"Обновил п. {', '.join(refs)}: {short(diff[0]['new'], 120)}"
    else:
        text = f"Принято: «{short(label, 80)}». Текст ТЗ не меняю."
    await s.emit(Event(agent=f.agent, type="applied", section_ref=refs[0] if refs else f.section_ref, text=text,
                       emotion=emotion(f.agent, "done"),
                       data={"question_id": q.id, "choice_key": key, "label": label, "diff": diff,
                             "version": len(s.versions), "in": into or q.id}))
    if not quiet:
        quiet_check = await recheck(s, refs, into=q.id)
        await score_event(s, "Пересчитал оценку" + (f" · п. {', '.join(refs)} перепроверен, новых проблем нет" if quiet_check else ""),
                          into=q.id)
        if s.reported:  # answers after the final report → refresh the report
            s.reported = False
        await maybe_continue(s)
    return {"ok": True, "diff": diff}


async def split_bundle(s: Session, b: Question, into: str | None = None) -> dict:
    """«Разобрать по одному»: the bundle is replaced by its single questions, the first one opens now."""
    singles = clarifier.unbundle(b, {f.id: f for f in s.findings})
    i = s.questions.index(b)
    s.questions[i:i + 1] = singles
    await s.emit(Event(agent="clarifier", type="applied", text=f"Хорошо, разберём {len(singles)} по одному.", emotion="neutral",
                       data={"question_id": b.id, "split": True, "diff": [], "in": into or b.id}))
    await maybe_continue(s)
    return {"ok": True, "diff": []}


async def undo_answer(s: Session, qid: str) -> dict:
    q = s.question(qid)
    if not q or q.status != "answered":
        raise AnswerError("нечего отменять")
    undo(s.doc, q.undo)
    f = s.finding(q.finding_id)
    f.status = "open"
    for fid in q.members + q.also:
        if (m := s.finding(fid)) and m.closed_by == qid:
            m.status, m.closed_by = "open", None
    q.status, q.answer_key, q.answer_text, q.undo = "open", None, None, []
    # re-open findings that were auto-closed by this answer
    reopened = []
    for g in s.findings:
        if g.closed_by == qid and g.status == "resolved":
            g.status, g.closed_by = "open", None
            gq = next((x for x in s.questions if x.finding_id == g.id and x.answer_key == "auto"), None)
            if gq:
                gq.status, gq.answer_key, gq.answer_text = "open", None, None
                reopened.append(gq)
    s.versions.append({"n": len(s.versions) + 1, "ts": time.time(), "label": f"Отмена: {short(q.text, 80)}", "changes": []})
    s.reported = False
    await s.emit(Event(agent=f.agent, type="applied", section_ref=f.section_ref, text="Отменил изменение — вопрос снова открыт.",
                       emotion="neutral", data={"question_id": q.id, "undo": True, "diff": [], "in": q.id}))
    for gq in reopened:
        await s.emit(Event(agent=gq.agent, type="applied", text="Связанный вопрос снова открыт.", emotion="neutral",
                           data={"question_id": gq.id, "undo": True, "diff": [], "in": q.id}))
    await score_event(s, "Пересчитал оценку после отмены", into=q.id)
    return {"ok": True}


async def recheck(s: Session, refs: list[str], doc_level: bool = False, into: str | None = None) -> bool:
    """Re-run rule-based agents. Auto-close sentence-level findings that disappeared in changed sections,
    post new findings found in the changed text. Returns True when nothing changed."""
    if not refs and not doc_level:
        return False
    ctx = ctx_for(s)
    active = [p["agent"] for p in s.plan if p["chosen"]]
    known = {f.signature for f in s.findings}
    last_q = next((v.get("question_id") for v in reversed(s.versions) if v.get("question_id")), None)

    def in_refs(ref):
        return doc_level or (ref and any(ref == r or ref.startswith(r + ".") for r in refs))

    closed, new = [], []
    for aid in active:
        fresh = [f for f in AGENT_CLASSES[aid](ctx).rules(s.doc) if f.confidence >= 0.5]
        sigs = {f.signature for f in fresh}
        for f in s.findings:
            if f.agent != aid or f.status != "open" or f.key.startswith("llm:") or f.signature in sigs:
                continue
            if (f.quote and in_refs(f.section_ref)) or doc_level:
                f.status = "resolved"
                f.closed_by = last_q
                closed.append(f)
        for f in fresh:
            if f.signature not in known and in_refs(f.section_ref):
                new.append(f)
    for f in closed:
        q = next((q for q in s.questions if q.status != "answered" and f.id in (q.members or [q.finding_id])), None)
        if q and q.members and len(q.members) > 1:
            drop_member(s, q, f.id)
            q = None
        if q:
            q.status, q.answer_key, q.answer_text = "answered", "auto", "закрыто автоматически"
        await s.emit(Event(agent=f.agent, type="applied", section_ref=f.section_ref, emotion="wink",
                           text=f"Перепроверил п. {f.section_ref}: замечание «{short(f.text, 60)}» больше не актуально.",
                           data={"question_id": q.id if q else None, "auto": True, "diff": [], "in": into}))
    if new:
        s.findings.extend(new)
        s.questions.extend(clarifier.build_questions(new, s.questions))
        for f in new:
            await s.emit(Event(agent=f.agent, type="status", emotion="surprised",
                               text=f"Перепроверил изменённый текст п. {f.section_ref} — нашёл новое:", data={"in": into}))
            await s.emit(finding_event(f, into=into))
    return bool(refs) and not closed and not new


def drop_member(s: Session, b: Question, fid: str) -> None:
    """A bundle member was closed by a re-check: take it (and its patches) out of the bundle."""
    b.members = [m for m in b.members if m != fid]
    b.items = [it for it in b.items if it["fid"] != fid]
    if b.finding_id == fid:
        b.finding_id = b.members[0]
    left = [g for g in (s.finding(m) for m in b.members) if g and g.options]
    b.options[0].ops = [op for g in left for op in g.options[0].ops]
    b.options[0].label = f"Применить рекомендации ко всем ({len(b.members)})"
    head, _, rest = b.text.partition(": ")
    b.text = f"{head}: {len(b.members)} {clarifier._plural(len(b.members))}." + (rest.split(".", 1)[1] if "." in rest else "")


# ====================================================================== MESSAGES / COMMANDS
class Reply(BaseModel):
    agent: str = "dispatcher"
    reply: str


MENTION_RX = re.compile(r"@([А-Яа-яЁёA-Za-z]+)")


def mentioned_agents(text: str) -> list[str]:
    """`@Ясность спроси у @Комплаенс …` → ["ambiguity", "regulatory"] (in order, no repeats)."""
    by_name = {v["name"].lower(): k for k, v in AGENTS.items()} | {k: k for k in AGENTS}
    out: list[str] = []
    for m in MENTION_RX.finditer(text):
        aid = by_name.get(m.group(1).lower())
        if aid and aid not in out:
            out.append(aid)
    return out


def mentioned_agent(text: str) -> str | None:
    got = mentioned_agents(text)
    return got[0] if got else None


class Turn(BaseModel):
    agent: str
    to: str | None = None
    text: str


class Dialogue(BaseModel):
    turns: list[Turn]


def _relevant(s: Session, aid: str, question: str, k: int = 2, strict: bool = False) -> list[Finding]:
    """The agent's open findings that share the most words with the question (most severe first on ties)."""
    words = {w[:5] for w in re.findall(r"[а-яёa-z0-9]{3,}", question.lower())}
    sev = {"critical": 0, "important": 1, "minor": 2}
    mine = [f for f in s.findings if f.agent == aid and f.status == "open"]
    score = lambda f: len(words & {w[:5] for w in re.findall(r"[а-яёa-z0-9]{3,}", (f.text + " " + (f.quote or "")).lower())})
    if strict:
        mine = [f for f in mine if score(f)]
    return sorted(mine, key=lambda f: (-score(f), sev[f.severity]))[:k]


async def agents_discuss(s: Session, ids: list[str], question: str) -> None:
    """Several agents were tagged: they talk it over in the chat (one Claude call writes the whole exchange)."""
    ids = ids[:4]
    turns: list[dict] = []
    if not llm.mock:
        try:
            roster = "\n".join(f"- {aid}: «{name(aid)}» — {AGENTS[aid]['role']}. Открытые замечания: "
                                + ("; ".join(f"п. {f.section_ref or '—'} {short(f.text, 90)}" for f in _relevant(s, aid, question, 4)) or "нет")
                                for aid in ids)
            res = await llm.complete_json(
                "Ты пишешь короткое обсуждение агентов команды проверки ТЗ в общем чате. Аналитик отметил нескольких агентов. "
                "Первый отмеченный начинает и обращается к коллегам, они отвечают по своей части, первый подводит итог для аналитика. "
                "3-6 реплик, каждая 1-2 предложения, по-русски, со ссылками на пункты ТЗ. Поле agent — id агента из списка, "
                "to — id адресата или пусто, если реплика для аналитика.",
                f"Агенты:\n{roster}\n\nСообщение аналитика: {question}", Dialogue, tier="fast",
                doc=doc_for_prompt(s.doc, 24000), max_tokens=6000, agent=ids[0], purpose="обсуждение агентов")
            turns = [t.model_dump() for t in res.turns if t.agent in ids][:6]
        except LLMError:
            turns = []
    if not turns:  # the same exchange, argued from the agents' own findings
        lead, rest = ids[0], ids[1:]
        own = _relevant(s, lead, question, 1, strict=True)
        turns.append({"agent": lead, "to": rest[0],
                      "text": (f"У меня по этой теме: п. {own[0].section_ref or '—'} — {short(own[0].text.rstrip('.'), 90)}. " if own else "")
                              + ", ".join(name(a) for a in rest) + " — что у вас по этому вопросу?"})
        for aid in rest:
            fs = _relevant(s, aid, question, 2)
            if fs:
                txt = "По моей части: " + "; ".join((f"п. {f.section_ref} — " if f.section_ref else "") + short(f.text.rstrip("."), 80) for f in fs) + "."
            elif not any(p["agent"] == aid and p["chosen"] for p in s.plan) and AGENTS[aid].get("triggers"):
                txt = "В этой проверке я не участвую — для этого ТЗ моя часть не нужна."
            else:
                txt = "По моей части открытых замечаний нет — тут всё описано."
            turns.append({"agent": aid, "to": lead, "text": txt})
        n = sum(len([f for f in s.findings if f.agent == a and f.status == "open"]) for a in ids)
        turns.append({"agent": lead, "to": None,
                      "text": f"Итог: у нас с коллегами {n} {plural(n, 'открытое замечание', 'открытых замечания', 'открытых замечаний')}. "
                              "Ответьте на вопросы ниже — и мы обновим ТЗ." if n else "Итог: по этой теме вопросов к ТЗ нет."})
    for t in turns:
        await pause(0.5, 1.1)
        await s.emit(Event(agent=t["agent"], type="status", emotion="curious" if t.get("to") else "happy", text=t["text"],
                           data={"to": t.get("to"), "discussion": True}))


async def handle_message(s: Session, text: str, command: str | None) -> None:
    if command == "skip":
        return await skip_question(s, text.strip())
    if command:
        return await handle_command(s, command)
    text = text.strip()
    if not text:
        return
    s.notes.append({"ts": time.time(), "text": text})
    s.context = (s.context + "\n" + text).strip()
    tagged = mentioned_agents(text)
    if len(tagged) > 1:
        return await agents_discuss(s, tagged, MENTION_RX.sub(lambda m: name(mentioned_agent(m.group(0)) or "") or m.group(0), text).strip())
    mentioned = tagged[0] if tagged else None
    target = mentioned or route(text)
    if not mentioned and target != "dispatcher" and not any(p["agent"] == target and p["chosen"] for p in s.plan):
        target = "dispatcher"
    if target != "dispatcher" and not mentioned:
        await s.emit(Event(agent="dispatcher", type="status", emotion="neutral", text=f"Передаю агенту «{name(target)}»."))
    question = MENTION_RX.sub("", text).strip() or text
    mine_f = [f for f in s.findings if f.agent == target and f.status == "open"]
    await pause()
    reply = None
    if not llm.mock:
        try:
            own = "\n".join(f"- п. {f.section_ref or '—'}: {f.text}" for f in mine_f)[:3000] or "—"
            others = "\n".join(f"- [{name(f.agent)}] п. {f.section_ref}: {short(f.text, 100)}"
                               for f in s.findings if f.status == "open" and f.agent != target)[:2500] or "—"
            cfg = AGENTS[target]
            res = await llm.run_agent(
                f"Ты — агент «{cfg['name']}» ({cfg['role']}: {cfg['line']}) в команде проверки ТЗ. "
                "Аналитик обратился к тебе в чате. Отвечай от своего лица, в рамках своей роли, коротко (1–4 предложения), "
                "по-русски, ссылаясь на пункты ТЗ. Если вопрос не по твоей части — скажи, кого из команды спросить. "
                "Если для ответа нужна норма или факт вне ТЗ — проверь инструментами и назови источник. " + tool_hint(cfg),
                f"Твои открытые замечания:\n{own}\n\nЗамечания других агентов:\n{others}\n\nСообщение: {question}",
                Reply, tier="fast", doc=doc_for_prompt(s.doc, 24000), tools=tools_for(cfg),
                run_tool=lambda n, a: run_tool(n, a, s.doc), max_steps=3, max_tokens=6000, agent=target, purpose="ответ в чате")
            reply = res.reply
        except LLMError:
            reply = None
    if reply is None:
        words = {w[:5] for w in re.findall(r"[а-яёa-z]{4,}", question.lower())}
        cands = [q for q in s.questions if q.agent == target and q.status == "open"]
        mine = max(cands, key=lambda q: len(words & {w[:5] for w in re.findall(r"[а-яёa-z]{4,}", q.text.lower())}), default=None)
        if target == "dispatcher":
            reply = f"Записал в контекст проекта: «{short(question, 80)}». Все агенты учтут это при следующих проверках."
        elif mine:
            reply = (f"Это похоже на мой открытый вопрос «{short(mine.text, 70)}» — "
                     f"выберите вариант или нажмите «Другое…» и вставьте формулировку, я обновлю ТЗ.")
        elif mentioned:
            cfg = AGENTS[target]
            if mine_f:
                top = sorted(mine_f, key=lambda f: {"critical": 0, "important": 1, "minor": 2}[f.severity])[:3]
                reply = (f"Моя зона — {cfg['role']}. Открытых замечаний у меня {len(mine_f)}, главное: "
                         + "; ".join((f"п. {f.section_ref} — " if f.section_ref else "") + short(f.text.rstrip("."), 90) for f in top) + ".")
            elif not any(p["agent"] == target and p["chosen"] for p in s.plan) and target in AGENTS and AGENTS[target].get("triggers"):
                reply = f"В этой проверке я не участвую: {next((p['reason'] for p in s.plan if p['agent'] == target), 'не нужен для этого ТЗ')}. Ваш вопрос записал в контекст."
            else:
                reply = f"По моей части ({cfg['role']}) открытых замечаний нет. Вопрос «{short(question, 70)}» учту при следующей проверке."
        else:
            reply = f"Принял: «{short(question, 80)}». Добавил в контекст — проверю при следующем изменении документа."
    await s.emit(Event(agent=target, type="status", emotion="happy", text=reply, data={"reply_to": text[:200]} if mentioned else {}))


async def handle_command(s: Session, cmd: str) -> None:
    if cmd == "findings":
        open_f = [f for f in s.findings if f.status == "open"]
        order = {"critical": 0, "important": 1, "minor": 2}
        sev_label = {"critical": "Критично", "important": "Важно", "minor": "Желательно"}
        await s.emit(Event(agent="critic", type="status", emotion="neutral",
                           text=f"Открытых замечаний: {len(open_f)}. Фильтруйте по агенту, критерию и важности; "
                                "клик — открыть в документе, правый клик — меню." if open_f else "Открытых замечаний нет!",
                           data={"log": [{"id": f.id, "fid": f.id, "title": f.text, "description": f"«{f.quote}»" if f.quote else "",
                                          "timestamp": f"п. {f.section_ref}" if f.section_ref else "весь документ",
                                          "actor": name(f.agent), "type": scoring.CRITERIA.get(f.criterion, f.criterion),
                                          "status": sev_label[f.severity], "severity": f.severity, "ref": f.section_ref or ""}
                                         for f in sorted(open_f, key=lambda f: order[f.severity])]}))
    elif cmd == "start":
        open_q = [q for q in s.questions if q.status == "open"]
        if open_q:
            await s.emit(Event(agent="clarifier", type="status", emotion="curious", text="Вопрос уже ждёт вас ниже.",
                               data={"scroll_to": open_q[0].id}))
        elif not await open_next_batch(s) and not s.reported:
            await final_report(s)
    elif cmd == "questions":
        s.minor_ok = True
        n = await open_next_batch(s, force=True)
        if not n:
            open_q = [q for q in s.questions if q.status == "open"]
            await s.emit(Event(agent="clarifier", type="status", emotion="neutral",
                               text=f"Все вопросы уже заданы — открыто {len(open_q)}, они выше в чате." if open_q else "Вопросов больше нет.",
                               data={"scroll_to": open_q[0].id if open_q else None}))
            if not open_q and not s.reported:
                await final_report(s)
    elif cmd == "improve":
        pending = [q for q in clarifier.ordered(s.questions) if q.status in ("open", "queued")]
        if not pending:
            await s.emit(Event(agent="reporter", type="status", emotion="happy", text="Все вопросы уже закрыты."))
            if not s.reported:
                await final_report(s)
            return
        gid = f"improve-{len(s.versions)}"
        await s.emit(Event(agent="dispatcher", type="status", emotion="curious",
                           text=f"Применяю рекомендованные варианты (A) к {len(pending)} оставшимся вопросам:",
                           data={"group": {"id": gid, "title": "Применённые правки"}}))
        for q in pending:
            if q.status == "answered":
                continue
            await pause(0.1, 0.25)
            await answer(s, q.id, q.options[0].key, None, quiet=True, into=gid)
        # re-check the whole document once: placeholders that were added stay open, closed issues disappear
        await recheck(s, [], doc_level=True, into=gid)
        s.reported = False
        await final_report(s)
    elif cmd == "tests":
        tests = await TestabilityAgent(ctx_for(s)).generate_tests(s.doc)
        s.tests = tests
        await s.emit(Event(agent="testability", type="status", emotion="happy",
                           text=f"Сгенерировал {len(tests)} приёмочных тест-кейсов по текущей версии ТЗ:",
                           data={"tests": tests}))
    elif cmd == "score":
        await score_event(s, "Оценка по критериям")
    elif cmd == "report":
        await final_report(s)
    else:
        await s.emit(Event(agent="dispatcher", type="status", emotion="sad", text=f"Не знаю команду «{cmd}»."))


async def handle_attachment(s: Session, filename: str, text: str, n_sections: int) -> None:
    s.doc.appendix.append(f"[{filename}]\n{text}")
    await s.emit(Event(agent="parser", type="status", emotion="happy",
                       text=f"Прочитал приложение «{filename}»: {n_sections} разделов. Перепроверяю ТЗ с учётом приложения…"))
    await recheck(s, [], doc_level=True)
    await score_event(s, "Пересчитал оценку с учётом приложения")
    await maybe_continue(s)
