"""Document parsing: .docx / .pdf / .txt / .md  ->  Document with numbered sections.

Template-agnostic: headings are detected by markdown '#', docx heading styles or
numbering ("3.", "3.2", "3.2.1"). Every numbered line becomes its own node so that
findings can cite "п. 3.2".
"""
from __future__ import annotations

import io
import unicodedata
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


ID_LINE = re.compile(r"^\s*[А-ЯЁA-Z]{1,5}[-–]\d{1,3}(?:\.\d+)*\.?\s")
MARK_RE = re.compile(r"^\s*(?:\d{1,2}[.)]|[•·▪◦‣*-])\s*$")


def _pdf_lines(r) -> list[tuple[str, str]]:
    """Rebuild structure from the PDF layout.
    * headings — bigger or all-bold short lines;
    * tables — a line that splits into cells starts a table; column x positions come from that header row, and rows
      are bands between vertical gaps (a cell may wrap and be vertically centered against its neighbours);
      one row → «cell — cell — …», the header (and its repeats after a page break) is skipped;
    * lists — a «1.»/«•» marker fragment; requirement ids («Ф-1.») and HTTP statuses («404.») start a new item;
    * wrapped lines of a paragraph are joined back."""
    segs = []
    for pi, page in enumerate(r.pages):
        def visit(text, cm, tm, font, size, pi=pi):
            if not text or not text.strip():
                return
            base = (font or {}).get("/BaseFont", "") if hasattr(font, "get") else ""
            segs.append({"p": pi, "size": round(size * (tm[0] or 1), 1), "bold": "Bold" in base or "Black" in base,
                         "x": tm[4], "y": tm[5], "t": text.replace("\n", " ")})
        page.extract_text(visitor_text=visit)
    if not segs:
        return []
    weights: dict[float, int] = {}
    for s in segs:
        weights[s["size"]] = weights.get(s["size"], 0) + len(s["t"])
    body = max(weights, key=weights.get)
    down = sum(1 for a, b in zip(segs, segs[1:]) if a["p"] == b["p"] and b["y"] > a["y"]) >= len(segs) / 2
    Y = (lambda s: (s["p"], s["y"])) if down else (lambda s: (s["p"], -s["y"]))     # reading order top → bottom

    buckets: dict[tuple, list[dict]] = {}
    for s in segs:
        key = next((k for k in buckets if k[0] == s["p"] and abs(k[1] - s["y"]) < 1.5), None) or (s["p"], s["y"])
        buckets.setdefault(key, []).append(s)
    lines = sorted((sorted(v, key=lambda s: s["x"]) for v in buckets.values()), key=lambda row: Y(row[0]))

    def cells_of(row):
        cells = [[row[0]["x"], row[0]["t"]]]
        end = row[0]["x"] + len(row[0]["t"].strip()) * row[0]["size"] * 0.5
        for a in row[1:]:
            gap = a["x"] - end
            glyph = len(a["t"].strip()) <= 1      # «₸» drawn in another font never starts a cell
            if not glyph and (gap > 18 or (a["t"][:1] == " " and gap > 12)):
                cells.append([a["x"], a["t"]])
            else:
                cells[-1][1] += a["t"]
            end = a["x"] + len(a["t"].strip()) * a["size"] * 0.5
        return [[x, " ".join(t.split())] for x, t in cells]

    def ydist(a, b):
        return abs(Y(a)[1] - Y(b)[1]) if a["p"] == b["p"] else 0.0        # a page break does not end a table

    def text_of(row):
        out_t, end = "", None
        for a in row:
            gap = end is not None and a["x"] - end > 2 and not a["t"][:1].isspace() and not out_t.endswith(" ")
            out_t += (" " if gap else "") + a["t"]
            end = a["x"] + len(a["t"].strip()) * a["size"] * 0.5
        return " ".join(out_t.split())

    left = min(s["x"] for s in segs)            # the page's text margin; list items are indented from it

    def table_rows(frags, cols, header, size):
        """Fragments of a table → one «cell — cell — …» line per row. Rows are bands between vertical gaps
        (cells may wrap and be vertically centred); a fragment belongs to the column whose left edge it is in."""
        bands: list[list[dict]] = []
        for f in sorted(frags, key=Y):
            if bands and bands[-1][-1]["p"] == f["p"] and ydist(bands[-1][-1], f) <= size * 1.3:
                bands[-1].append(f)
            else:
                bands.append([f])
        rows_out = []
        for band in bands:
            by_col: dict[int, list[dict]] = {}
            for f in band:
                k = max([k for k, c in enumerate(cols) if c <= f["x"] + 8] or [0])
                by_col.setdefault(k, []).append(f)
            vals = []
            for k in sorted(by_col):
                parts, cur_y = [], None
                for f in sorted(by_col[k], key=lambda f: (Y(f), f["x"])):
                    parts.append(("" if cur_y is not None and abs(f["y"] - cur_y) < 1.5 else " ") + f["t"])
                    cur_y = f["y"]
                vals.append(" ".join("".join(parts).split()))
            if vals == header or not any(vals):
                continue                  # the header repeated after a page break
            rows_out.append(("li", " — ".join(dict.fromkeys(v for v in vals if v))))
        return rows_out

    out: list[tuple[str, str]] = []
    last = None                     # last emitted (kind, y-fragment) for paragraph joining
    i = 0
    while i < len(lines):
        row = lines[i]
        text = text_of(row)
        size = max(s["size"] for s in row)
        cells = cells_of(row) if len(row) > 1 and not ID_LINE.match(text) and not MARK_RE.match(row[0]["t"]) else []
        if sum(1 for _, c in cells if len(re.sub(r"\W", "", c)) >= 2) < 2:
            cells = []                    # «Content-Type: application/json .» is a sentence, not a table header
        if len(cells) > 1:
            # ---- a table: gather its fragments until a heading, a big gap or text outside the columns
            cols = [x for x, _ in cells]
            header = [c for _, c in cells]
            frags, prev, j = [], row, i + 1
            while j < len(lines):
                nxt = lines[j]
                big = max(s["size"] for s in nxt) > body * 1.08
                near = min(abs(nxt[0]["x"] - c) for c in cols) < 40      # the line starts inside a column
                if big or ydist(prev[0], nxt[0]) > size * 2.3 or not near:
                    break
                frags += nxt
                prev, j = nxt, j + 1
            if frags:                     # (a single line with a gap in it is not a table)
                # a header cell wrapped above the line with cells was already emitted as a heading: take it back
                if i > 0 and out and out[-1][1] == text_of(lines[i - 1]) and all(f["bold"] for f in lines[i - 1]) \
                        and ydist(lines[i - 1][0], row[0]) <= size * 1.3:
                    out.pop()
                # header cells wrapped below it are bold too: they belong to the header, not to the first row
                while frags and frags[0]["bold"] and ydist(row[0], frags[0]) <= size * 1.3 and all(
                        f["bold"] for f in frags if abs(f["y"] - frags[0]["y"]) < 1.5):
                    y0 = frags[0]["y"]
                    frags = [f for f in frags if abs(f["y"] - y0) >= 1.5]
                out += table_rows(frags, cols, header, size)
                last = None
                i = j
                continue
            cells = []
        # ---- not a table
        if MARK_RE.match(row[0]["t"]) and len(row) > 1:
            out.append(("li", text_of(row[1:])))
            last = row[0]
        elif (size > body * 1.08 or (all(s["bold"] for s in row) and len(text) < 90 and len(re.sub(r"[^A-Za-zА-Яа-яЁё]", "", text)) >= 3)) \
                and not text.endswith((".", ",", ";", ":")) and not ID_LINE.match(text):
            out.append(("h", text))
            last = None
        elif last is not None and out and out[-1][0] in ("p", "li") and ydist(last, row[0]) <= size * 1.35 \
                and not ID_LINE.match(text) and not re.match(r"^(\d{3}\.|\d{1,2}(\.\d{1,2})+\.?)\s", text) \
                and (ID_LINE.match(out[-1][1]) or
                     not (row[0]["x"] > left + 20 and abs(row[0]["x"] - last["x"]) < 3 and out[-1][1].rstrip().endswith(".")
                          and text[:1].isupper())):
            out[-1] = (out[-1][0], out[-1][1] + " " + text)
            last = row[0]
        else:
            indented = row[0]["x"] > left + 20
            out.append(("li" if ID_LINE.match(text) or indented else "p", text))
            last = row[0]
        i += 1
    return out


def _extract_pdf(data: bytes) -> tuple[list[tuple[str, str]], int]:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(data))
    try:
        lines = _pdf_lines(r)
    except Exception:      # an odd PDF: plain text extraction below
        lines = []
    if sum(1 for k, _ in lines if k == "h") >= 3:
        return lines, len(r.pages)
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
    doc.numbered = sum(1 for k, t in lines if NUM_RE.match(t) and "." in NUM_RE.match(t).group(1)) >= 3

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
            # «1. … 2. …» restarting inside a section is a list there, not a new top-level section
            if level == 1 and current is not None and int(ref) <= top_counter and not _is_heading_like(rest):
                kind = "li"
                text = rest
                m = None
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
    # «й», «ё» copied on macOS often arrive decomposed («и» + U+0306): compose them, or headings and words won't match
    lines = [(k, unicodedata.normalize("NFC", t)) for k, t in lines]
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
