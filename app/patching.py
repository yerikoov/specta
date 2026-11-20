"""Apply / undo document patches chosen by the user."""
from __future__ import annotations

import re

from .models import Document, PatchOp, Section
from .parsing import SENT_RE


def _top_numbers(doc: Document) -> list[int]:
    return [int(s.ref) for s in doc.sections if s.level == 1 and s.ref.isdigit()]


def _ensure_section(doc: Document, key: str, template: dict, snap: list) -> Section:
    sec = doc.by_template(key)
    if sec:
        return sec
    t = next((t for t in template["sections"] if t["key"] == key), {"name": key})
    ref = str(max(_top_numbers(doc) or [0]) + 1)
    sec = Section(ref=ref, title=t["name"], level=1, template_key=key, created=True)
    doc.sections.append(sec)
    snap.append({"ref": ref, "created": True})
    return sec


def _add_item(doc: Document, parent: Section, text: str, snap: list) -> Section:
    kids = [s for s in doc.sections if s.ref.startswith(parent.ref + ".") and s.ref.count(".") == parent.ref.count(".") + 1]
    n = max([int(s.ref.split(".")[-1]) for s in kids if s.ref.split(".")[-1].isdigit()] or [0]) + 1
    item = Section(ref=f"{parent.ref}.{n}", level=parent.level + 1, text=text, created=True)
    last = max([doc.sections.index(s) for s in kids] or [doc.sections.index(parent)])
    doc.sections.insert(last + 1, item)
    snap.append({"ref": item.ref, "created": True})
    return item


def _snapshot(sec: Section, snap: list) -> None:
    if not any(x["ref"] == sec.ref for x in snap):
        snap.append({"ref": sec.ref, "created": False, "text": sec.text, "title": sec.title})


def apply_ops(doc: Document, ops: list[PatchOp], template: dict) -> tuple[list[dict], list[dict]]:
    """Returns (diff, snapshot). diff = [{section_ref, old, new}]"""
    diff: list[dict] = []
    snap: list[dict] = []
    for op in ops:
        if op.mode == "none":
            continue
        if op.mode == "create":
            existed = doc.by_template(op.template_key) is not None
            sec = _ensure_section(doc, op.template_key, template, snap)
            if op.text and not existed:
                item = _add_item(doc, sec, op.text, snap)
                diff.append({"section_ref": sec.ref, "old": "", "new": f"{sec.ref}. {sec.title}\n{item.ref} {op.text}"})
            continue
        sec = doc.get(op.section_ref) if op.section_ref else None
        if sec is None and op.template_key:
            sec = _ensure_section(doc, op.template_key, template, snap)
        if sec is None:
            continue
        if op.mode == "append":
            target = sec if sec.level == 1 else (doc.get(sec.ref.split(".")[0]) or sec)
            if target.level == 1:
                item = _add_item(doc, target, op.text, snap)
                diff.append({"section_ref": item.ref, "old": "", "new": op.text})
            else:
                _snapshot(sec, snap)
                old = sec.text
                sec.text = (sec.text + "\n" if sec.text else "") + op.text
                diff.append({"section_ref": sec.ref, "old": old, "new": sec.text})
            continue
        old = sec.text
        new = None
        if op.mode == "replace":
            if op.find and op.find in sec.text:
                new = sec.text.replace(op.find, op.text, 1)
            elif op.pattern and re.search(op.pattern, sec.text, flags=re.I):
                new = re.sub(op.pattern, lambda _m: op.text, sec.text, count=1, flags=re.I)
        elif op.mode == "replace_sentence":
            if op.find and op.find in sec.text:
                new = sec.text.replace(op.find, op.text, 1)
            elif op.pattern:
                parts = SENT_RE.split(sec.text)
                for i, p in enumerate(parts):
                    if re.search(op.pattern, p, flags=re.I):
                        parts[i] = op.text
                        new = " ".join(parts)
                        break
        if new is None:
            if op.mode == "replace":
                continue          # the text was already rewritten by another answer — nothing to do
            new = (sec.text + " " if sec.text else "") + op.text   # fallback: append clarification
        new = re.sub(r"\s+([.,;:)\]»])", r"\1", new)          # «ЕНП )» → «ЕНП)»
        new = re.sub(r"([(\[«])\s+", r"\1", new)
        new = re.sub(r"\(\s*\)|,\s*\)", lambda m: "" if m.group(0).startswith("(") else ")", new)
        new = re.sub(r"[ \t]{2,}", " ", new)
        _snapshot(sec, snap)
        sec.text = new
        diff.append({"section_ref": sec.ref, "old": old, "new": new})
    return diff, snap


def undo(doc: Document, snap: list[dict]) -> None:
    for entry in reversed(snap):
        if entry["created"]:
            doc.sections = [s for s in doc.sections if s.ref != entry["ref"]]
        else:
            sec = doc.get(entry["ref"])
            if sec:
                sec.text, sec.title = entry["text"], entry["title"]


def apply_custom(doc: Document, finding, text: str, template: dict) -> tuple[list[dict], list[dict]]:
    """Free-form answer: replace the quoted sentence, or append to the target section."""
    if finding.quote and finding.section_ref:
        ops = [PatchOp(mode="replace_sentence", section_ref=finding.section_ref, find=finding.quote, text=text)]
    elif finding.section_ref:
        ops = [PatchOp(mode="append", section_ref=finding.section_ref, text=text)]
    else:
        key = next((op.template_key for o in finding.options for op in o.ops if op.template_key), None)
        ops = [PatchOp(mode="append", template_key=key or "functional", text=text)]
    return apply_ops(doc, ops, template)
