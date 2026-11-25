"""The review run: read → cut into requirements → rule checks → model checks (each requirement, then the set) →
Critic (quotes must exist in the document, the model's findings re-checked) → Clarifier → verdict.

`on_event(agent, stage, text)` reports progress (the terminal animation listens to it)."""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from ..llm import llm, meter, trace
from ..parsing import parse_bytes
from . import agents
from .checks import is_design_decision, requirement_checks, set_checks
from .models import Defect, Review
from .slicer import slice_requirements
from .standards import CRITICAL_KINDS, SEV_ORDER

AGENT_VERSION = "1.0.0"
Event = Callable[[str, str, str], None]


def agent_version() -> str:
    """«1.0.0 (git a1b2c3d)» — the commit the report was produced with («+изменения», if the tree is dirty)."""
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=3).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True, text=True, timeout=3).stdout.strip()
        return f"{AGENT_VERSION} (git {sha}{' + незакоммиченные изменения' if dirty else ''})" if sha else AGENT_VERSION
    except (OSError, subprocess.SubprocessError):
        return AGENT_VERSION


def _norm(s: str) -> str:
    s = re.sub(r"```\w*", " ", s.lower()).replace("ё", "е").replace("**", "").replace("`", "")
    return re.sub(r"[\s«»\"'“”]+", " ", s).strip(" .,;:")


def _quote_ok(quote: str, text: str) -> bool:
    q = _norm(quote)
    if not q:
        return True
    if q in text:
        return True
    # tolerate a model that trimmed or joined lines: 80% of the quote's words in order inside the document
    words = q.split()
    return len(words) >= 4 and _norm(" ".join(words[: max(4, int(len(words) * 0.8))])) in text


def _dedupe(defects: list[Defect]) -> list[Defect]:
    seen, out = set(), []
    for d in sorted(defects, key=lambda d: (SEV_ORDER[d.severity], d.source != "rules")):
        key = (d.prop, tuple(sorted(d.rids)) or d.place, _norm(d.quote)[:40])
        alt = (d.prop, tuple(sorted(d.rids)))
        if key in seen or (d.rids and alt in seen):
            continue
        seen.add(key)
        if d.rids:
            seen.add(alt)
        out.append(d)
    return out


def _n(n: int, one: str, few: str, many: str) -> str:
    k = abs(n) % 100
    w = many if 10 < k < 20 else one if k % 10 == 1 else few if 2 <= k % 10 <= 4 else many
    return f"{n} {w}"


def verdict(review: Review) -> dict:
    allp = review.req_defects + review.set_defects
    crit = [d for d in allp if d.severity == "critical"]
    major = [d for d in allp if d.severity == "major"]
    untestable = [d for d in allp if d.prop in ("verifiable",) and d.severity != "minor"]
    contradictory = [d for d in allp if d.prop in ("correct", "consistent") and d.severity != "minor"]
    incomplete = [d for d in allp if d.prop == "complete" and d.severity != "minor"]
    if crit:
        dev = "Нет"
        dev_why = f"{_n(len(crit), 'критичный дефект', 'критичных дефекта', 'критичных дефектов')}: по таким требованиям команда реализует разное поведение."
    elif len(major) > 5:
        dev = "С оговорками"
        dev_why = f"Критичных дефектов нет, но {_n(len(major), 'существенный', 'существенных', 'существенных')} — начинать можно только с однозначных требований."
    else:
        dev = "Да"
        dev_why = "Критичных дефектов нет."
    test = "Нет" if (untestable or contradictory) else ("С оговорками" if incomplete else "Да")
    parts = [x for x in (_n(len(contradictory), "противоречие", "противоречия", "противоречий") if contradictory else "",
                         _n(len(untestable), "непроверяемая формулировка", "непроверяемые формулировки", "непроверяемых формулировок") if untestable else "") if x]
    test_why = (" и ".join(parts) + ": ожидаемый результат тестов не определён."
                if test == "Нет" else ("Не хватает данных для части проверок." if test != "Да" else "Ожидаемые результаты определены."))
    first, seen = [], set()
    for d in sorted(crit + major, key=lambda d: (SEV_ORDER[d.severity], 0 if d.prop in CRITICAL_KINDS else 1)):
        key = set(d.rids) or {d.place}
        if key & seen:                     # the same requirement already has a first-priority fix
            continue
        seen |= key
        first.append(d)
        if len(first) == 6:
            break
    return {"development": dev, "development_why": dev_why, "testing": test, "testing_why": test_why,
            "first": [d.model_dump() for d in first]}


async def run_review(data: bytes, filename: str, on_event: Optional[Event] = None, use_llm: bool = True,
                     pace: float = 0) -> Review:
    ev = on_event or (lambda *a: None)
    usage: dict = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}
    tr: list = []
    meter.set(usage)
    trace.set(tr)
    t0 = time.time()

    ev("parser", "read", f"Читаю «{filename}»")
    doc = parse_bytes(filename, data)
    return await review_document(doc, filename, on_event, use_llm, started=t0, usage=usage, tr=tr, pace=pace)


async def review_document(doc, filename: str, on_event: Optional[Event] = None, use_llm: bool = True,
                          started: Optional[float] = None, usage: Optional[dict] = None, tr: Optional[list] = None,
                          pace: float = 0) -> Review:
    """The review of an already parsed document (the website reuses the document of a check).
    `pace` > 0 (the CLI's --demo): pause after each step and walk through every agent, without calling a model."""
    emit = on_event or (lambda *a: None)

    async def ev(agent: str, stage: str, text: str) -> None:
        emit(agent, stage, text)
        if pace:
            await asyncio.sleep(pace)
    if usage is None:
        usage = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}
        meter.set(usage)
    if tr is None:
        tr = []
        trace.set(tr)
    t0 = started or time.time()
    review = Review(title=doc.title or Path(filename).stem, filename=filename, started=t0,
                    engine=llm.engine if use_llm else "rules", model=_model_line(use_llm), version=agent_version())
    await ev("parser", "read", f"Разделов: {sum(1 for s in doc.sections if s.level == 1)}, строк и пунктов: {sum(1 for s in doc.sections if s.level > 1)}")

    await ev("dispatcher", "slice", "Нарезаю документ на отдельные требования")
    reqs, skipped = slice_requirements(doc)
    review.requirements, review.skipped = reqs, skipped
    await ev("dispatcher", "slice", f"Требований: {len(reqs)}, служебных блоков пропущено: {len(skipped)}")

    await ev("ambiguity", "rules", "Правила: размытые слова, атомарность, HTTP-семантика, пустые значения")
    req_d = requirement_checks(reqs)
    set_d = set_checks(doc, reqs, skipped)
    await ev("ambiguity", "rules", f"Правила нашли {len(req_d) + len(set_d)} дефектов")

    if pace and not (use_llm and not llm.mock):     # demo: show every agent of the model part, without a model
        for k, who in enumerate(["testability", "completeness", "ambiguity", "nfr"]):
            part = reqs[k * len(reqs) // 4:(k + 1) * len(reqs) // 4] or reqs[:1]
            await ev(who, "analyse", f"Демо: {part[0].rid}–{part[-1].rid} по 9 свойствам ISO 29148 ({k + 1}/4)")
        await ev("contradictions", "set", "Демо: набор — противоречия, пропуски, связь частей")
    if use_llm and not llm.mock:
        def on_batch(i, n, part):
            who = ["testability", "completeness", "ambiguity", "nfr"][i % 4]
            emit(who, "analyse", f"Проверяю {part[0].rid}–{part[-1].rid} по 9 свойствам ISO 29148 ({i + 1}/{n})")
        req_d += await agents.analyse_requirements(doc, reqs, on_batch=on_batch)
        await ev("contradictions", "set", "Проверяю набор: противоречия, пропуски, связь части A и B")
        set_d += await agents.analyse_set(doc, reqs, set_d)

    # the Critic: every quote must exist in the document; the model's findings are re-read against it
    await ev("critic", "critic", "Перепроверяю замечания: цитаты и обоснованность")
    text = _norm(doc.full_text())
    pool = req_d + set_d
    dropped = []
    for d in pool:
        if not _quote_ok(d.quote, text):
            d.problem = f"{d.problem} [снято: цитата не найдена в документе]"
            dropped.append(d)
    pool = [d for d in pool if d not in dropped]
    if use_llm and not llm.mock:
        rulings = await agents.critic(doc, pool)
        kept = []
        for i, d in enumerate(pool):
            r = rulings.get(i)
            if r and not r.keep and d.severity == "critical" and "дубл" not in r.reason.lower():
                # a critical finding is only dropped as a duplicate; otherwise the Critic may only lower its severity
                d.severity = "major"
                kept.append(d)
                continue
            if r and not r.keep:
                if is_design_decision(d):
                    # a named class or a storage column is a real defect even when the section is a template slot
                    kept.append(d)
                    continue
                d.problem = f"{d.problem} [снято Критиком: {r.reason}]"
                dropped.append(d)
                continue
            if r:
                d.severity = r.severity
            kept.append(d)
        pool = kept
    pool = _dedupe(pool)
    review.req_defects = [d for d in pool if d in req_d]
    review.set_defects = [d for d in pool if d in set_d]
    review.dropped = dropped
    await ev("critic", "critic", f"Подтверждено {len(pool)}, снято {len(dropped)}")

    if pace and not (use_llm and not llm.mock):
        await ev("clarifier", "questions", "Демо: вопросы аналитику формулирует модель")
    if use_llm and not llm.mock:
        await ev("clarifier", "questions", "Формулирую вопросы аналитику")
        review.questions = await agents.clarify(doc, pool, reqs)

    await ev("reporter", "verdict", "Решаю, можно ли начинать разработку и тестирование")
    review.verdict = verdict(review)
    review.usage = {**usage, "trace": tr}
    review.finished = time.time()
    await ev("reporter", "done", f"Готово за {review.finished - t0:.0f} с")
    return review


def _model_line(use_llm: bool) -> str:
    if not use_llm or llm.mock:
        return "без модели (только правила)"
    m = llm.models
    names = list(dict.fromkeys([m["fast"], m["strong"]]))
    return f"{llm.engine}: " + " / ".join(names)
