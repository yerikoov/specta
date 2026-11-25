"""Cut a document into individual requirements («как агент нарезал требования»).

Deterministic, so two runs on the same file give the same R-ids. Keeps the document's own ids (Ф-1, НФТ-2…)
and, where there are none, names the place («Критерии приемки, строка 2», «Логика работы метода, шаг 5»).
Service blocks (passport table, review checklist, approvals, empty headings) are not requirements — they are
listed as skipped and are looked at by the set-level checks.
"""
from __future__ import annotations

import re

from ..models import Document, Section
from .models import Requirement

ID_RE = re.compile(r"^\s*\**\s*((?:[А-ЯЁA-Z]{1,5}[-–.]?)\d{1,3}(?:\.\d{1,3})*)\s*[.)]?\**\s*[.:—-]?\s*(.+)$", re.S)

# section title (lowercase substring) → kind; order matters
KINDS = [
    ("нефункцион", "nfr"), ("функцион", "functional"), ("критери", "acceptance"), ("приемк", "acceptance"), ("приёмк", "acceptance"),
    ("данн", "data"), ("интеграц", "integration"), ("sequence", "integration"), ("дизайн", "ui"), ("ui", "ui"),
    ("bpmn", "process"), ("процесс", "process"), ("цел", "business"), ("архитектур", "design"),
    ("логика", "api"), ("особые правила", "api"), ("параметр", "api"), ("query", "api"), ("path", "api"),
    ("request", "api"), ("ответ", "api"), ("статус", "api"), ("схема", "design"), ("rest", "api"),
    ("successful", "api"), ("unsuccessful", "api"), ("общие параметры", "api"),
]
# service blocks: not requirements
SKIP = [("общие сведения", "паспорт задачи (метаданные, не требования)"), ("ревью требований", "чек-лист ревью (проверяется в наборе)"),
        ("блок согласующих", "лист согласования (проверяется в наборе)"), ("введение", "вводный текст")]
# rows of the API passport that are metadata, not behaviour
META_ROWS = re.compile(r"^(gitlab project|framework|author|developer|controller)\b", re.I)
ROW_NAMES = {"acceptance": "строка", "api": "п."}


def _clean(t: str) -> str:
    t = re.sub(r"```\w*", "", t or "")
    t = t.replace("**", "").replace("`", "")
    return " ".join(t.split()).strip(" .")


def _short(t: str, n: int = 12) -> str:
    words = t.split()
    return " ".join(words[:n]) + ("…" if len(words) > n else "")


def _kind(title: str, part_b: bool) -> str:
    low = title.lower()
    for key, kind in KINDS:
        if key in low:
            return kind
    return "api" if part_b else "functional"      # any other section with clauses is checked as requirements


def slice_requirements(doc: Document) -> tuple[list[Requirement], list[str]]:
    reqs: list[Requirement] = []
    skipped: list[str] = []
    part, head, head_kind, skip_why = "", "", None, None
    row_no = 0
    status_head = ""

    def add(text: str, place: str, kind: str, ref: str, section_title: str | None = None):
        text = _clean(text)
        if len(text) < 6 or re.fullmatch(r"[-—–\s/|]*(да|нет|не требуется|[-—])?[-—–\s/|]*", text.lower()):
            return
        m = ID_RE.match(text)
        if m and re.search(r"\d", m.group(1)) and not re.match(r"^\d", m.group(1)):
            doc_id, body = m.group(1).rstrip(".-–"), m.group(2).strip()
        else:
            doc_id, body = place, text
        h = head if section_title is None else section_title
        reqs.append(Requirement(rid=f"R-{len(reqs) + 1:02d}", doc_id=doc_id, section=" · ".join(x for x in (part, h) if x),
                                kind=kind, text=text, short=_short(body), ref=ref))

    for sec in doc.sections:
        if sec.level == 1:
            title = (sec.title or "").strip()
            if re.match(r"^часть\s+[a-zа-я]\b", title, re.I):
                part, head = title.split(".")[0].strip(), ""
                head_kind, skip_why = None, None
                body = _clean(sec.text)
                continue
            head, row_no = title, 0
            if "статус" in title.lower():
                status_head = title
            low = title.lower()
            skip_why = next((why for key, why in SKIP if key in low), None)
            head_kind = None if skip_why else _kind(title, part.lower().endswith("b"))
            if skip_why:
                skipped.append(f"{' · '.join(x for x in (part, head) if x)} — {skip_why}")
                continue
            body = (sec.text or "").strip()
            if body and re.search(r"заполняются|tbd|todo|не заполнен", body, re.I) and len(body) < 80:
                skipped.append(f"{' · '.join(x for x in (part, head) if x)} — заглушка «{_clean(body)}» (проверяется в наборе)")
                continue
            if body and head_kind:
                lines = [x for x in body.split("\n") if x.strip() and not x.strip().startswith("```")]
                # API: every «NNN. …» status line is its own requirement; the rest of the paragraph stays together
                status = [x for x in lines if re.match(r"^\s*\**\d{3}\b", x)] if head_kind == "api" else []
                rest = [x for x in lines if x not in status]
                if rest:
                    add("\n".join(rest), head, head_kind, sec.ref)
                for x in status:
                    code = re.search(r"\d{3}", x).group(0)
                    # a 401/403/500 line glued into the «200. Successful» example still belongs to «Статусы»
                    where = status_head or head
                    add(x, f"{where}, код {code}", head_kind, sec.ref, section_title=where)
            continue
        # sub-items: list items and table rows of the current section
        if skip_why or not head_kind:
            continue
        row_no += 1
        text = sec.text or ""
        if head_kind == "api" and META_ROWS.match(_clean(text)):
            continue
        if doc.numbered:                 # the document's own clause number
            add(text, f"п. {sec.ref}", head_kind, sec.ref)
            continue
        noun = "строка" if " — " in text and head_kind in ("acceptance", "api", "data") else ("шаг" if "логика" in head.lower() else "п.")
        add(text, f"{head}, {noun} {row_no}", head_kind, sec.ref)
    return reqs, skipped
