"""The report file, in Russian, in the order the task asks for (section 6):
passport · how the requirements were cut · each requirement · the set · summary · verdict.
Every defect is tied to a place: requirement id, the document's own id and a verbatim quote."""
from __future__ import annotations

import time

from .models import Defect, Review
from .standards import CRITICAL_KINDS, REQ_PROPS, SET_PROPS, SEV_ORDER, SEVERITY, STANDARDS_LINE

MARK = {"critical": "🔴", "major": "🟠", "minor": "⚪"}


def _cell(s: str) -> str:
    return " ".join((s or "").split()).replace("|", "\\|")


def _where(d: Defect, rev: Review) -> str:
    by = {r.rid: r for r in rev.requirements}
    if d.place and d.place.startswith(("разделы", "все ", "«")):
        return d.place                                    # a set-level place that already names the requirements
    if d.rids:
        return ", ".join(f"{x} ({by[x].doc_id})" for x in d.rids if x in by)
    return d.place or "документ целиком"


def _defect(d: Defect, rev: Review, props: dict, with_where: bool = False) -> list[str]:
    head = f"- {MARK[d.severity]} **{props.get(d.prop, {}).get('name', d.prop)}** · {SEVERITY[d.severity]}"
    if with_where:
        head += f" · {_where(d, rev)}"
    out = [head]
    if d.quote:
        out.append(f"  > «{_cell(d.quote)}»")
    out.append(f"  - Проблема: {_cell(d.problem)}")
    if d.fix:
        out.append(f"  - Как исправить: {_cell(d.fix)}")
    return out


def render(rev: Review) -> str:
    reqs = rev.requirements
    by_rid: dict[str, list[Defect]] = {r.rid: [] for r in reqs}
    for d in rev.req_defects:
        for x in d.rids or []:
            by_rid.setdefault(x, []).append(d)
    alld = rev.req_defects + rev.set_defects
    sev = {k: sum(1 for d in alld if d.severity == k) for k in SEVERITY}
    with_def = sum(1 for r in reqs if by_rid.get(r.rid))
    dur = max(0, rev.finished - rev.started)
    dur_txt = f"{dur:.0f}" if dur >= 10 else f"{dur:.1f}"
    v = rev.verdict or {}
    L: list[str] = []
    w = L.append

    w(f"# Отчёт о проверке требований: «{rev.title}»")
    w("")
    w("> Сформирован агентом Specta автоматически по выданному документу. Документ не изменялся — это ревью до разработки.")
    w("")
    # 1 — passport
    w("## 1. Паспорт прогона")
    w("")
    w("| Поле | Значение |")
    w("|---|---|")
    w(f"| Документ | {_cell(rev.title)} |")
    w(f"| Файл | `{rev.filename}` |")
    w(f"| Дата прогона | {time.strftime('%d.%m.%Y %H:%M', time.localtime(rev.started))} |")
    w(f"| Модель | {_cell(rev.model)} |")
    w(f"| Версия агента | {_cell(rev.version)} |")
    w(f"| Критерии | {STANDARDS_LINE} |")
    calls, hits = rev.usage.get("calls", 0), rev.usage.get("cache_hits", 0)
    calls_txt = f"{calls + hits}" + (f" (из них {hits} — ответы из кеша для того же документа)" if hits else "")
    w(f"| Прогон | {dur_txt} с · обращений к модели: {calls_txt} · требований: {len(reqs)} |")
    w("")
    # 2 — slicing
    w("## 2. Как агент нарезал требования")
    w("")
    w("Агент выделил отдельные проверяемые утверждения. Если в документе был свой номер (Ф-1…), он сохранён; "
      "если номера не было — указано место в документе, а формулировка сохранена цитатой в разделе 3.")
    w("")
    w("| ID в отчёте | ID / место в документе | Раздел | Краткая формулировка |")
    w("|---|---|---|---|")
    for r in reqs:
        w(f"| {r.rid} | {_cell(r.doc_id)} | {_cell(r.section)} | {_cell(r.short)} |")
    if rev.skipped:
        w("")
        w("Не нарезались как требования (служебные блоки, проверены в разделе 4):")
        for s in rev.skipped:
            w(f"- {_cell(s)}")
    w("")
    # 3 — each requirement
    w("## 3. Проверка каждого требования")
    w("")
    w("Свойства ISO/IEC/IEEE 29148:2018 §5.2.5: " + ", ".join(f"{v['name']}" for v in REQ_PROPS.values()) +
      ". Сначала — матрица (✗ — найдено нарушение свойства), затем замечания с цитатами.")
    w("")
    short = {"necessary": "Нужн.", "appropriate": "Уровень", "unambiguous": "Однозн.", "complete": "Полн.", "singular": "Атом.",
             "feasible": "Выполн.", "verifiable": "Провер.", "correct": "Корр.", "conforming": "Шаблон"}
    w("| ID | В документе | " + " | ".join(short.values()) + " |")
    w("|---|---|" + "---|" * len(short))
    for r in reqs:
        bad = {d.prop: d.severity for d in by_rid.get(r.rid, [])}
        cells = [("✗" + ("!" if bad[p] == "critical" else "")) if p in bad else "✓" for p in short]
        w(f"| {r.rid} | {_cell(r.doc_id)} | " + " | ".join(cells) + " |")
    w("")
    for r in reqs:
        ds = sorted(by_rid.get(r.rid, []), key=lambda d: SEV_ORDER[d.severity])
        w(f"### {r.rid} · {_cell(r.doc_id)}")
        w(f"> {_cell(r.text)}")
        w("")
        if not ds:
            w("Нарушений не найдено.")
        else:
            for d in ds:
                L.extend(_defect(d, rev, REQ_PROPS))
        w("")
    # 4 — the set
    w("## 4. Проверка всего набора требований")
    w("")
    w("Свойства набора — ISO/IEC/IEEE 29148:2018 §5.2.6 и IEEE 830-1998 §4.3.")
    w("")
    w("| Свойство | Источник | Итог |")
    w("|---|---|---|")
    for k, p in SET_PROPS.items():
        ds = [d for d in rev.set_defects if d.prop == k]
        worst = min((SEV_ORDER[d.severity] for d in ds), default=None)
        mark = "✓ без замечаний" if worst is None else f"{MARK[['critical', 'major', 'minor'][worst]]} {len(ds)} замеч."
        w(f"| {p['name']} | {p['src']} | {mark} |")
    w("")
    for k, p in SET_PROPS.items():
        ds = sorted([d for d in rev.set_defects if d.prop == k], key=lambda d: SEV_ORDER[d.severity])
        if not ds:
            continue
        w(f"### {p['name']}")
        for d in ds:
            L.extend(_defect(d, rev, SET_PROPS, with_where=True))
        w("")
    # 5 — summary
    w("## 5. Сводка")
    w("")
    w(f"- Требований выделено: **{len(reqs)}**, из них с нарушениями: **{with_def}**.")
    w(f"- Нарушений всего: **{len(alld)}** — {MARK['critical']} критичных {sev['critical']}, "
      f"{MARK['major']} существенных {sev['major']}, {MARK['minor']} незначительных {sev['minor']}.")
    w(f"- По отдельным требованиям: {len(rev.req_defects)}, по набору: {len(rev.set_defects)}. "
      f"Снято Критиком как неподтверждённые: {len(rev.dropped)}.")
    w("")
    crit = [d for d in alld if d.prop in CRITICAL_KINDS and d.severity in ("critical", "major")]
    if crit:
        w("**Критичные дефекты** (непроверяемые, противоречивые, неполные, двусмысленные формулировки):")
        w("")
        w("| # | Тип | Где | Суть |")
        w("|---|---|---|---|")
        for i, d in enumerate(sorted(crit, key=lambda d: SEV_ORDER[d.severity]), 1):
            w(f"| {i} | {MARK[d.severity]} {CRITICAL_KINDS[d.prop]} | {_cell(_where(d, rev))} | {_cell(d.problem)} |")
        w("")
    # questions (clarification)
    if rev.questions:
        w("### Вопросы к аналитику")
        w("")
        w("Без ответа на эти вопросы разработка и тесты будут построены на догадках:")
        w("")
        for i, q in enumerate(rev.questions, 1):
            w(f"{i}. **{_cell(q.text)}**" + (f" ({', '.join(q.rids)})" if q.rids else ""))
            if q.options:
                w("   " + " · ".join(f"{'ABC'[j]}) {_cell(o)}" for j, o in enumerate(q.options)))
            if q.why:
                w(f"   _Зачем: {_cell(q.why)}_")
        w("")
    # 6 — verdict
    w("## 6. Итог")
    w("")
    w(f"- **Можно ли начинать разработку:** {v.get('development', '—')}. {v.get('development_why', '')}")
    w(f"- **Можно ли начинать тестирование:** {v.get('testing', '—')}. {v.get('testing_why', '')}")
    w("")
    if v.get("first"):
        w("**Что исправить в первую очередь:**")
        w("")
        for i, d in enumerate(v["first"], 1):
            dd = Defect(**d)
            w(f"{i}. {_cell(_where(dd, rev))} — {_cell(dd.problem)}" + (f" → {_cell(dd.fix)}" if dd.fix else ""))
        w("")
    if rev.dropped:
        w("<details><summary>Снятые замечания (для прозрачности)</summary>")
        w("")
        for d in rev.dropped:
            w(f"- {_cell(_where(d, rev))}: {_cell(d.problem)}")
        w("")
        w("</details>")
        w("")
    return "\n".join(L).rstrip() + "\n"
