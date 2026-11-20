"""Clarifier: merges findings into ranked questions, max N open at a time."""
from __future__ import annotations

import re

from ..models import Finding, FixOption, Question

RANK = {"critical": 0, "important": 1, "minor": 2}
AGENT_ORDER = ["contradictions", "regulatory", "security", "completeness", "ambiguity", "testability", "integrations", "nfr"]
MAX_OPEN = 1  # one question at a time keeps the chat readable


def _refkey(ref: str | None):
    return [int(x) for x in re.findall(r"\d+", ref or "99")] or [99]


def build_questions(findings: list[Finding], existing: list[Question]) -> list[Question]:
    have = {fid for q in existing for fid in (q.members or [q.finding_id]) + q.also}
    qs = []
    for f in findings:
        if f.status != "open" or not f.options or f.id in have:
            continue
        qs.append(Question(finding_id=f.id, agent=f.agent, priority=f.severity,
                           text=f.question or f.text, why=f.why or "", options=f.options))
    return qs


# ---------------------------------------------------------------- bundles
# Questions that are really "accept the recommended wording?" are merged into one card per theme.
# The bundle's option A applies exactly the same patches as answering every member with its option A,
# so the final TZ is identical — the user just clicks once instead of N times (and can split it back).
THEMES = {
    "sections": ("Недостающие разделы", "Добавлю типовые разделы по шаблону банка:"),
    "compliance": ("Требования регулятора и ИБ", "Предлагаю типовые формулировки для банка:"),
    "clarity": ("Размытые формулировки", "Заменю на измеримые значения:"),
    "testability": ("Непроверяемые требования", "Добавлю критерии, которые можно проверить на приёмке:"),
    "completeness": ("Недостающие детали", "Допишу недостающее:"),
}
BUNDLE_MAX = 8
SPLIT = "split"


def _theme(f: Finding) -> str | None:
    if f.severity == "critical" or f.criterion == "consistency":
        return None            # real decisions (and conflicting facts) are always asked one by one
    if (f.topic or "").startswith("section:"):
        return "sections"
    return f.criterion if f.criterion in THEMES else None


def _ref_label(f: Finding) -> str:
    return f"п. {f.section_ref}" if f.section_ref else "весь документ"


def bundle(questions: list[Question], findings: dict[str, Finding]) -> list[Question]:
    """Merge same-theme, same-priority, non-critical questions into one question per theme (max BUNDLE_MAX)."""
    groups: dict[tuple, list[Question]] = {}
    out: list[Question] = []
    for q in questions:
        f = findings.get(q.finding_id)
        th = _theme(f) if f and q.options and not q.members else None
        if th:
            groups.setdefault(th, []).append(q)
        else:
            out.append(q)
    for th, qs in groups.items():
        qs.sort(key=lambda q: _refkey(findings[q.finding_id].section_ref))
        for i in range(0, len(qs), BUNDLE_MAX):
            chunk = qs[i:i + BUNDLE_MAX]
            if len(chunk) == 1:
                out.extend(chunk)
                continue
            title, lead = THEMES[th]
            prio = min((q.priority for q in chunk), key=RANK.get)
            agent = max({q.agent for q in chunk}, key=lambda a: sum(q.agent == a for q in chunk))
            ops = [op for q in chunk for op in q.options[0].ops]
            items = [{"fid": q.finding_id, "ref": _ref_label(findings[q.finding_id]), "text": q.text,
                      "fix": q.options[0].label, "severity": q.priority, "agent": q.agent} for q in chunk]
            out.append(Question(
                finding_id=chunk[0].finding_id, agent=agent, priority=prio,
                text=f"{title}: {len(chunk)} {_plural(len(chunk))}. {lead}",
                why="Решение по каждому пункту — как если бы вы выбрали рекомендованный вариант. Хотите иначе — разберём по одному.",
                options=[FixOption(key="A", label=f"Применить рекомендации ко всем ({len(chunk)})", ops=ops),
                         FixOption(key=SPLIT, label="Разобрать по одному", ops=[])],
                members=[q.finding_id for q in chunk], items=items))
    return out


def unbundle(b: Question, findings: dict[str, Finding]) -> list[Question]:
    """The single questions of a bundle, for the members that are still open."""
    return build_questions([findings[fid] for fid in b.members if fid in findings and findings[fid].status == "open"], [])


def _plural(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "пункт"
    return "пункта" if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else "пунктов"


def merge_duplicates(questions: list[Question], groups: list[list[int]]) -> list[Question]:
    """Same decision asked by several agents → one question (the most severe one); the others' findings
    are closed by its answer (`also`). `groups` are indexes into `questions`."""
    drop: set[int] = set()
    for g in groups:
        g = sorted({i for i in g if 0 <= i < len(questions) and i not in drop})
        if len(g) < 2:
            continue
        keep = min(g, key=lambda i: (RANK[questions[i].priority], i))
        for i in g:
            if i != keep:
                questions[keep].also.append(questions[i].finding_id)
                drop.add(i)
    return [q for i, q in enumerate(questions) if i not in drop]


def make_questions(findings: list[Finding], duplicates: list[list[int]] | None = None) -> tuple[list[Question], int]:
    """All questions for a fresh check: duplicates merged, similar ones bundled.
    Returns (questions, how many single questions there were before)."""
    singles = ordered(build_questions(findings, []))
    merged = merge_duplicates(list(singles), duplicates or [])
    return ordered(bundle(merged, {f.id: f for f in findings})), len(singles)


def ordered(questions: list[Question]) -> list[Question]:
    return sorted(questions, key=lambda q: (q.skipped, RANK[q.priority],
                                            AGENT_ORDER.index(q.agent) if q.agent in AGENT_ORDER else 99))


def next_batch(questions: list[Question], max_open: int = MAX_OPEN) -> list[Question]:
    """Questions to open now: only when no critical question is still open, top up to max_open."""
    open_q = [q for q in questions if q.status == "open"]
    if any(q.priority == "critical" for q in open_q) and open_q:
        return []
    room = max_open - len(open_q)
    if room <= 0:
        return []
    return ordered([q for q in questions if q.status == "queued"])[:room]
