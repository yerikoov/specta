"""Export: improved ТЗ (.md / .docx) and the score report."""
from __future__ import annotations

import io
import os
import time

from .scoring import CRITERIA
from .store import Session

PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Specta")
SEV = {"critical": "Критично", "important": "Важно", "minor": "Желательно"}


def _change(v: dict) -> str:
    """Change-log line in full (the label in the UI is shortened)."""
    if v.get("question"):
        refs = ", ".join(sorted({c["section_ref"] for c in v.get("changes", [])}))
        return f"{v['question']} → {v['answer']}" + (f" (п. {refs})" if refs else "")
    return v["label"]


def improved_md(s: Session) -> str:
    out = [f"# {s.doc.title}", "", f"_Улучшено {PRODUCT_NAME} · {time.strftime('%d.%m.%Y %H:%M')} · "
           f"оценка {s.score_before['total']} → {s.score['total']}/100_", ""]
    if getattr(s, "warning", ""):
        out += [f"> **Внимание:** {s.warning}", ""]
    for sec in s.doc.sections:
        if sec.level == 1:
            out += ["", f"## {sec.ref}. {sec.title}".rstrip()]
            if sec.text:
                out.append(sec.text)
        else:
            out.append(f"{sec.ref} {sec.text}".rstrip())
    changes = [v for v in s.versions[1:] if v.get("changes")]
    if changes:
        out += ["", "---", "## Журнал изменений", ""]
        out += [f"{i}. {_change(v)}" for i, v in enumerate(changes, 1)]
    return "\n".join(out).strip() + "\n"


def report_md(s: Session) -> str:
    sb, sa = s.score_before, s.score
    out = [f"# Отчёт о качестве ТЗ — {s.doc.title}", "", f"**Оценка:** {sb['total']} → **{sa['total']}** / 100", "",
           "| Критерий | До | После |", "|---|---|---|"]
    for b, a in zip(sb["criteria"], sa["criteria"]):
        out.append(f"| {a['label']} | {b['value']} | {a['value']} |")
    open_f = [f for f in s.findings if f.status == "open"]
    out += ["", f"## Открытые замечания ({len(open_f)})", ""]
    out += [f"- **{SEV[f.severity]}** · п. {f.section_ref or '—'} · {f.text}" for f in open_f] or ["Нет."]
    res = [f for f in s.findings if f.status == "resolved"]
    out += ["", f"## Исправлено ({len(res)})", ""]
    out += [f"- п. {f.section_ref or '—'} · {f.text}" for f in res] or ["—"]
    if s.tests:
        out += ["", "## Приёмочные тест-кейсы", ""]
        for t in s.tests:
            out += [f"### {t['id']} — {t['title']}", f"- **Дано:** {t['given']}", f"- **Когда:** {t['when']}",
                    f"- **Тогда:** {t['then']}", ""]
    return "\n".join(out) + "\n"


def improved_docx(s: Session) -> bytes:
    import docx
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading(s.doc.title, 0)
    p = d.add_paragraph(f"Улучшено {PRODUCT_NAME}: оценка {s.score_before['total']} → {s.score['total']}/100")
    p.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x8C)
    if getattr(s, "warning", ""):
        w = d.add_paragraph(f"Внимание: {s.warning}")
        w.runs[0].font.color.rgb = RGBColor(0xC2, 0x41, 0x0C)
    for sec in s.doc.sections:
        if sec.level == 1:
            d.add_heading(f"{sec.ref}. {sec.title}", 1)
            if sec.text:
                d.add_paragraph(sec.text)
        else:
            para = d.add_paragraph()
            para.add_run(f"{sec.ref} ").bold = True
            r = para.add_run(sec.text)
            if sec.created:
                r.font.color.rgb = RGBColor(0x1F, 0x8A, 0x3A)
    changes = [v for v in s.versions[1:] if v.get("changes")]
    if changes:
        d.add_heading("Журнал изменений", 1)
        for v in changes:
            d.add_paragraph(_change(v), style="List Number")
    if s.tests:
        d.add_heading("Приложение: приёмочные тест-кейсы", 1)
        for t in s.tests:
            d.add_heading(f"{t['id']} — {t['title']}", 3)
            d.add_paragraph(f"Дано: {t['given']}\nКогда: {t['when']}\nТогда: {t['then']}")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def report_json(s: Session) -> dict:
    return {
        "session_id": s.id, "title": s.doc.title, "score_before": s.score_before, "score": s.score,
        "criteria_labels": CRITERIA,
        "findings": [f.model_dump(exclude={"options"}) for f in s.findings],
        "questions": [q.model_dump(exclude={"options", "undo"}) for q in s.questions],
        "tests": s.tests, "versions": s.versions, "plan": s.plan,
    }
