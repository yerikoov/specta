"""Document parsing: .docx / .pdf / .txt / .md  ->  Document with numbered sections.

Template-agnostic: headings are detected by markdown '#', docx heading styles or
numbering ("3.", "3.2", "3.2.1"). Every numbered line becomes its own node so that
findings can cite "п. 3.2".
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import yaml

from .models import Document, Section

ROOT = Path(__file__).resolve().parent.parent
NUM_RE = re.compile(r"^\s*(?:п\.\s*)?(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+(.+)$")
MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(.+)$")
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9«\"])")


def load_template(path: Path | None = None) -> dict:
    path = path or ROOT / "config" / "template.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rules() -> dict:
    with open(ROOT / "config" / "rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.extend(s.strip() for s in SENT_RE.split(line) if s.strip())
    return out


# ---------------------------------------------------------------- raw extract
def _table_rows(rows: list[list[str]]) -> list[str]:
    """Table → one line per data row («ячейка — ячейка — …»); the header row and separators are skipped."""
    rows = [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]
    rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) or not c for c in r)]
    if len(rows) > 1:
        rows = rows[1:]                     # header
    return [" — ".join(dict.fromkeys(c for c in r if c)) for r in rows]


def _extract_docx(data: bytes) -> tuple[list[tuple[str, str]], int]:
    """Returns (kind, text) lines in document order; kind = 'h' (heading) | 'li' (list item) | 'p'."""
    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    lines: list[tuple[str, str]] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            t = Table(el, d)
            lines += [("li", r) for r in _table_rows([[c.text for c in row.cells] for row in t.rows])]
            continue
        if tag != "p":
            continue
        p = Paragraph(el, d)
        t = p.text.strip()
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if style.startswith(("heading", "заголовок", "title")):
            lines.append(("h", t))
        elif "list" in style or "нумерованный" in style or "маркированный" in style:
            lines.append(("li", t))
        else:
            lines.extend(_md_lines(t))          # markdown pasted into Word: tables / bullets inside a paragraph
    chars = sum(len(t) for _, t in lines)
    return lines, max(1, round(chars / 1800))


def _extract_pdf(data: bytes) -> tuple[list[tuple[str, str]], int]:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    return [("p", ln) for ln in text.splitlines() if ln.strip()], len(r.pages)


BULLET_RE = re.compile(r"^\s*[-*•–]\s+(.+)$")


def _clean_md(t: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`", lambda m: next(g for g in m.groups() if g), t).strip()


def _md_lines(text: str) -> list[tuple[str, str]]:
    """Markdown block → lines: '#' headings, '- ' bullets and '|' table rows become list items."""
    out: list[tuple[str, str]] = []
    table: list[list[str]] = []

    def flush():
        if table:
            out.extend(("li", _clean_md(r)) for r in _table_rows(table))
            table.clear()

    for ln in text.splitlines():
        st = ln.strip()
        if not st:
            flush()
            continue
        if st.startswith("|") and st.count("|") >= 2:
            table.append(st.strip("|").split("|"))
            continue
        flush()
        if m := MD_HEAD_RE.match(st):
            out.append(("h", _clean_md(m.group(2))))
        elif (m := BULLET_RE.match(st)) and not NUM_RE.match(st):
            out.append(("li", _clean_md(m.group(1))))
        else:
            out.append(("p", _clean_md(st)))
    flush()
    return out


def _extract_text(data: bytes) -> tuple[list[tuple[str, str]], int]:
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return _md_lines(text), max(1, round(len(text) / 1800))


# ---------------------------------------------------------------- structure
def _is_heading_like(rest: str) -> bool:
    return len(rest) <= 70 and not rest.rstrip().endswith((".", ";", ":", ",")) and rest[:1].isupper()


def build_document(filename: str, lines: list[tuple[str, str]], pages: int) -> Document:
    doc = Document(filename=filename, filetype=Path(filename).suffix.lower().lstrip(".") or "txt", pages=pages)
    current: Section | None = None
    top_counter = 0
    list_counter = 0
    has_numbered_headings = any(NUM_RE.match(t) for k, t in lines if k == "h")

    def push(sec: Section) -> Section:
        doc.sections.append(sec)
        return sec

    for kind, text in lines:
        # «- п. 3.8 …» in a list is a reference to another clause, not this item's number
        m = None if kind == "li" and re.match(r"\s*п\.", text, re.I) else NUM_RE.match(text)
        if kind == "h":
            if m:
                ref, rest = m.group(1), m.group(2).strip()
                level = ref.count(".") + 1
                if level == 1:
                    top_counter = int(ref)
                current = push(Section(ref=ref, title=rest, level=level))
                list_counter = 0
            elif not doc.title and not doc.sections:
                doc.title = text
            else:
                if has_numbered_headings and current is not None and len(text) > 70:
                    current.text += ("\n" if current.text else "") + text
                    continue
                top_counter += 1
                current = push(Section(ref=str(top_counter), title=text, level=1))
                list_counter = 0
            continue
        if m and (len(m.group(1)) > 1 or "." in m.group(1) or kind != "li"):
            ref, rest = m.group(1), m.group(2).strip()
            level = ref.count(".") + 1
            if level == 1 and _is_heading_like(rest):
                top_counter = int(ref)
                current = push(Section(ref=ref, title=rest, level=1))
                list_counter = 0
            else:
                current = push(Section(ref=ref, title="", level=level, text=rest))
            continue
        if kind == "li" and current is not None:
            parent = current.ref.split(".")[0] if current.level > 1 else current.ref
            taken = [int(x.ref.split(".")[1]) for x in doc.sections
                     if x.ref.startswith(parent + ".") and x.ref.count(".") == 1 and x.ref.split(".")[1].isdigit()]
            list_counter = max(taken + [list_counter]) + 1
            current = push(Section(ref=f"{parent}.{list_counter}", level=2, text=text))
            continue
        if current is None:
            if not doc.title:
                doc.title = text
                continue
            top_counter += 1
            current = push(Section(ref=str(top_counter), title="Введение", level=1))
        current.text += ("\n" if current.text else "") + text
    if not doc.title:
        doc.title = Path(filename).stem
    return doc


def parse_bytes(filename: str, data: bytes) -> Document:
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        lines, pages = _extract_docx(data)
    elif ext == ".pdf":
        lines, pages = _extract_pdf(data)
    elif ext in (".txt", ".md", ".markdown", ""):
        lines, pages = _extract_text(data)
    else:
        raise ValueError(f"Неподдерживаемый формат: {ext}")
    doc = build_document(filename, lines, pages)
    map_template(doc, load_template())
    return doc


def map_template(doc: Document, template: dict) -> dict[str, str]:
    """Assign template keys to top-level sections by name / synonyms. Returns key -> ref."""
    mapping: dict[str, str] = {}
    for sec in doc.sections:
        if sec.level != 1 or not sec.title:
            continue
        title = sec.title.lower()
        for t in template["sections"]:
            if t["key"] in mapping:
                continue
            names = [t["name"].lower(), *[s.lower() for s in t.get("synonyms", [])]]
            if any(n in title for n in names):
                sec.template_key = t["key"]
                mapping[t["key"]] = sec.ref
                break
    return mapping


def section_body(doc: Document, ref: str) -> str:
    """Text of a section including its sub-items."""
    parts = []
    for s in doc.sections:
        if s.ref == ref or s.ref.startswith(ref + "."):
            parts.append(((s.title + "\n") if s.title else "") + s.text)
    return "\n".join(parts).strip()
